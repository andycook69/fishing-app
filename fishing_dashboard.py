"""Northern salmon and sea trout dashboard (single-file Streamlit app).

GitHub: save this file as app.py and add a requirements.txt containing:
    streamlit>=1.42,<2
    pandas>=2,<3
    openpyxl>=3.1,<4

Run: streamlit run app.py
Optional live weather: set WEATHER_API_KEY in Streamlit deployment secrets
or as a server-side environment variable. Never put the key in GitHub.

Data: EA annual declared rod catches (2008–2024, 2024 workbook);
EA 2024 monthly rod catches and estimated grilse; EA gauge readings;
WeatherAPI current conditions; private-test Burnfoot FishPal monthly figures;
optional *permissioned* current-year CSV.
This app has no subscriber authentication or payment integration.
"""

from __future__ import annotations

import datetime as dt
import csv
import io
import math
import os
import re
from collections import Counter
from html.parser import HTMLParser
from urllib.parse import urlencode
from urllib.request import Request, urlopen

import openpyxl
import pandas as pd
import streamlit as st


st.set_page_config(page_title="Northern salmon conditions", page_icon="🎣", layout="wide")

EA_ARCHIVE = (
    "https://www.data.gov.uk/dataset/"
    "d8d55ec7-aead-4a25-9e3f-aa4c74a6529f/"
    "salmonid-and-freshwater-fisheries-statistics-supplementary-data-tables"
)
EA_WORKBOOK = (
    "https://environment.data.gov.uk/api/file/download?"
    "fileDataSetId=00c55f27-6638-448d-9577-71498dd173df&"
    "fileName=Salmonid_and_freshwater_fisheries_statistics_-_"
    "Supplementary_data_tables_2024.xlsx"
)
GAUGE_API = "https://environment.data.gov.uk/flood-monitoring/id/stations"
GOV_GAUGE_CSV = "https://check-for-flooding.service.gov.uk/station-csv/"
WEATHER_API = "https://api.weatherapi.com/v1/current.json"
FISHPAL_BURNFOOT = "https://www.fishpal.com/scotland/borderesk/burnfoot/"
# These RLOI IDs are checked against their individual government station pages.
GOV_DEFAULT_GAUGES = {
    "Border Esk": ("River Esk at Canonbie", "5207"),
    "Yorkshire Esk": ("River Esk at Briggswath", "8233"),
    "Cumbrian Esk": ("River Esk at Cropple How", "5037"),
    "Tyne": ("River Tyne at Hexham", "9006"),
    "Tees": ("River Tees at Barnard Castle", "8014"),
}
RIVERS = {
    "Border Esk": ("Esk Border", "Canonbie, UK"),
    "Yorkshire Esk": ("Esk Yorkshire", "Whitby, UK"),
    "Cumbrian Esk": ("Esk Cumbrian", "Ravenglass, UK"),
    "Tyne": ("Tyne", "Hexham, UK"),
    "Wear": ("Wear", "Durham, UK"),
    "Coquet": ("Coquet", "Rothbury, UK"),
    "Tees": ("Tees", "Barnard Castle, UK"),
    "Aln": ("Aln", "Alnwick, UK"),
    "Eden": ("Eden North West", "Appleby-in-Westmorland, UK"),
    "Lune": ("Lune", "Lancaster, UK"),
    "Ribble": ("Ribble", "Clitheroe, UK"),
    "Derwent": ("Derwent", "Cockermouth, UK"),
    "Ehen": ("Ehen", "Egremont, UK"),
    "Irt": ("Irt", "Ravenglass, UK"),
    "Kent": ("Kent", "Kendal, UK"),
    "Leven": ("Leven", "Ulverston, UK"),
}
ALIASES = {
    "esk (yorks.)": "Esk Yorkshire",
    "esk yorkshire": "Esk Yorkshire",
    "esk border": "Esk Border",
    "border esk": "Esk Border",
    "esk (border)": "Esk Border",
    "esk cumbrian": "Esk Cumbrian",
    "esk (cumbrian)": "Esk Cumbrian",
    "ouse yorkshire*": "Ouse Yorkshire",
}
CURRENT_YEAR = dt.datetime.now(dt.timezone.utc).year


def get_bytes(url: str, timeout: int = 20) -> bytes:
    request = Request(url, headers={"User-Agent": "NorthernSalmonDashboard/1.0"})
    with urlopen(request, timeout=timeout) as response:
        return response.read()


def get_json(url: str, timeout: int = 12) -> dict:
    import json

    return json.loads(get_bytes(url, timeout=timeout))


def river_key(value: object) -> str:
    text = str(value or "").strip().rstrip("*")
    return ALIASES.get(text.lower(), text)


def count(value: object) -> int | None:
    # A missing/withheld value is not a reported zero.
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)) and value >= 0:
        return int(value)
    return None


@st.cache_data(ttl=24 * 60 * 60, show_spinner="Downloading official catch archive…")
def load_ea_archive():
    workbook = openpyxl.load_workbook(
        io.BytesIO(get_bytes(EA_WORKBOOK, timeout=35)), read_only=True, data_only=True
    )
    yearly = {}
    monthly = {}
    grilse = {}
    try:
        # Table 34/35: one row per river, columns 2008..2024.
        for sheet_name, species in (("Table 34", "salmon"), ("Table 35", "sea_trout")):
            sheet = workbook[sheet_name]
            rows = sheet.iter_rows(values_only=True)
            next(rows)  # title
            next(rows)  # blank
            years = list(next(rows))
            for row in rows:
                key = river_key(row[1] if len(row) > 1 else None)
                if key not in {v[0] for v in RIVERS.values()}:
                    continue
                for column, year in enumerate(years):
                    if str(year).isdigit() and 2008 <= int(year) <= 2024:
                        result = count(row[column]) if column < len(row) else None
                        if result is not None:
                            yearly.setdefault((key, int(year)), {})[species] = result

        # Table 27/28: paired columns for total and released, Jan..Dec 2024.
        for sheet_name, species in (("Table 27", "salmon"), ("Table 28", "sea_trout")):
            rows = workbook[sheet_name].iter_rows(values_only=True)
            next(rows)
            next(rows)
            next(rows)
            for row in rows:
                key = river_key(row[1] if len(row) > 1 else None)
                if key not in {v[0] for v in RIVERS.values()}:
                    continue
                for month in range(1, 13):
                    position = 2 + 2 * (month - 1)
                    result = count(row[position]) if position < len(row) else None
                    if result is not None:
                        monthly.setdefault((key, month), {})[species] = result
                # The EA also publishes an 'Unknown' month column (index 26).
                unknown = count(row[26]) if len(row) > 26 else None
                if unknown is not None:
                    monthly.setdefault((key, 0), {})[species] = unknown

        # Table 38: estimates, not observed individual grilse counts.
        rows = workbook["Table 38"].iter_rows(values_only=True)
        for row in list(rows)[3:]:
            key = river_key(row[1] if len(row) > 1 else None)
            if key in {v[0] for v in RIVERS.values()} and isinstance(row[2], (int, float)):
                grilse[key] = float(row[2])
    finally:
        workbook.close()
    if not yearly or not monthly:
        raise ValueError("EA workbook layout changed; catch figures have not been loaded.")
    return yearly, monthly, grilse


@st.cache_data(ttl=60 * 60, show_spinner=False)
def search_gauges(query: str) -> list[dict]:
    url = GAUGE_API + "?" + urlencode({"search": query, "parameter": "level", "_limit": 100})
    return get_json(url).get("items", [])


@st.cache_data(ttl=60 * 60, show_spinner=False)
def gauges_near(latitude: float, longitude: float) -> list[dict]:
    # EA documents geographic station lookup; it returns candidates, not a beat reading.
    url = GAUGE_API + "?" + urlencode({
        "lat": latitude, "long": longitude, "dist": 75,
        "parameter": "level", "status": "Active", "_limit": 500,
    })
    return get_json(url, timeout=16).get("items", [])


def matching_gauges(stations: list[dict], river: str,
                    latitude: float, longitude: float) -> list[dict]:
    term = "Esk" if "Esk" in river else river
    matches = []
    for station in stations:
        measures = station.get("measures", [])
        if isinstance(measures, dict):
            measures = [measures]
        if not any(isinstance(measure, dict) and measure.get("parameter") == "level"
                   and measure.get("qualifier") == "Stage" for measure in measures):
            continue
        name = str(station.get("riverName") or station.get("label") or "")
        if not re.search(r"\b" + re.escape(term) + r"\b", name, flags=re.IGNORECASE):
            continue
        try:
            station_lat = float(station["lat"])
            station_lon = float(station["long"])
            distance = 111.2 * math.hypot(
                station_lat - latitude,
                (station_lon - longitude) * math.cos(math.radians(latitude)),
            )
        except (KeyError, ValueError, TypeError):
            continue
        if distance <= 75:
            matches.append((distance, station))
    return [station for _, station in sorted(matches, key=lambda item: item[0])]


@st.cache_data(ttl=15 * 60, show_spinner=False)
def government_station_reading(rloi_id: str) -> dict:
    # RLOI IDs belong to the public Check for Flooding pages, not necessarily
    # to the separate EA flood-monitoring station endpoint.
    if not rloi_id.isdigit():
        raise ValueError("Invalid government gauge identifier")
    content = get_bytes(GOV_GAUGE_CSV + rloi_id, timeout=18).decode("utf-8-sig")
    readings = []
    for row in csv.DictReader(io.StringIO(content)):
        try:
            if row.get("Type(observed/forecast)", "").strip().lower() == "forecast":
                continue
            timestamp = dt.datetime.fromisoformat(row["Timestamp (UTC)"].replace("Z", "+00:00"))
            height = float(row["Height (m)"])
            if (math.isfinite(height) and timestamp.tzinfo is not None and
                    timestamp <= dt.datetime.now(dt.timezone.utc) + dt.timedelta(minutes=5)):
                readings.append((timestamp, height))
        except (ValueError, KeyError, TypeError):
            continue
    if not readings:
        raise ValueError("No valid recent level in government station CSV")
    timestamp, height = max(readings, key=lambda reading: reading[0])
    known_name = next((name for name, station_id in GOV_DEFAULT_GAUGES.values()
                       if station_id == rloi_id), "Government station " + rloi_id)
    return {"station": known_name,
            "river": "",
            "value": height, "date": timestamp.isoformat(), "unit": "m",
            "measure": "Stage", "source": GOV_GAUGE_CSV + rloi_id}


@st.cache_data(ttl=15 * 60, show_spinner=False)
def gauge_reading(station_id: str, rloi_id: str = "") -> dict:
    # Prefer the official public gauge CSV when an RLOI page ID is known.
    if rloi_id:
        try:
            return government_station_reading(rloi_id)
        except Exception:
            if not station_id:
                raise
    # Station IDs below come only from the EA monitoring-stations response.
    station = get_json(GAUGE_API + "/" + station_id).get("items", {})
    if isinstance(station, list):
        station = station[0] if station else {}
    measures = station.get("measures", [])
    if isinstance(measures, dict):
        measures = [measures]
    stage = [
        measure for measure in measures
        if measure.get("parameter") == "level"
        and measure.get("qualifier") == "Stage"
        and isinstance(measure.get("latestReading"), dict)
        and measure["latestReading"].get("value") is not None
    ]
    # If the station JSON omits latestReading, fetch its level measures individually.
    if not stage:
        for measure in measures:
            if measure.get("parameter") != "level" or measure.get("qualifier") != "Stage":
                continue
            identifier = str(measure.get("@id", "")).rstrip("/").rsplit("/", 1)[-1]
            if not identifier or not all(c.isalnum() or c in "_-" for c in identifier):
                continue
            data = get_json(
                "https://environment.data.gov.uk/flood-monitoring/id/measures/"
                + identifier + "/readings?latest"
            ).get("items", [])
            if data:
                measure = {**measure, "latestReading": data[0]}
                stage.append(measure)
                break
    if not stage:
        return {"station": station.get("label", station_id)}
    chosen = stage[0]
    return {
        "station": station.get("label", station_id),
        "river": station.get("riverName", ""),
        "value": chosen["latestReading"]["value"],
        "date": chosen["latestReading"].get("dateTime", ""),
        "unit": chosen.get("unitName", "m"),
        "measure": chosen.get("qualifier", "Stage"),
    }


@st.cache_data(ttl=15 * 60, show_spinner=False)
def current_weather(key: str, location: str) -> dict:
    url = WEATHER_API + "?" + urlencode({"key": key, "q": location, "aqi": "no"})
    answer = get_json(url)
    if "error" in answer:
        raise ValueError(answer["error"].get("message", "Weather unavailable"))
    return answer


class _CatchTableParser(HTMLParser):
    """Read tables under species headings; fail closed if FishPal changes layout."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.heading_tag = None
        self.heading_words = []
        self.heading = ""
        self.table = None
        self.row = None
        self.cell = None
        self.tables = []

    def handle_starttag(self, tag, attrs):
        if tag in {"h2", "h3", "h4", "h5"}:
            self.heading_tag = tag
            self.heading_words = []
        elif tag == "table" and self.table is None:
            self.table = []
        elif tag == "tr" and self.table is not None:
            self.row = []
        elif tag in {"td", "th"} and self.row is not None:
            self.cell = []

    def handle_data(self, data):
        if self.heading_tag:
            self.heading_words.append(data)
        if self.cell is not None:
            self.cell.append(data)

    def handle_endtag(self, tag):
        if tag == self.heading_tag:
            self.heading = " ".join(" ".join(self.heading_words).split()).lower()
            self.heading_tag = None
        elif tag in {"td", "th"} and self.cell is not None:
            self.row.append(" ".join(" ".join(self.cell).split()))
            self.cell = None
        elif tag == "tr" and self.row is not None:
            if self.row:
                self.table.append(self.row)
            self.row = None
        elif tag == "table" and self.table is not None:
            self.tables.append((self.heading, self.table))
            self.table = None


def parse_burnfoot_catches(html: str, year: int) -> dict:
    parser = _CatchTableParser()
    parser.feed(html)
    species_data = {}
    for heading, rows in parser.tables:
        species = ("salmon" if "atlantic salmon" in heading else
                   "sea_trout" if "sea trout" in heading else None)
        if species is None or species in species_data:
            continue
        header_index = next((i for i, row in enumerate(rows)
                             if any(re.sub(r"[^0-9]", "", value) in
                                    {str(year), str(year)[-2:]} for value in row)), None)
        if header_index is None:
            continue
        header = rows[header_index]
        year_col = next(i for i, value in enumerate(header)
                        if re.sub(r"[^0-9]", "", value) in
                        {str(year), str(year)[-2:]})
        monthly = {}
        declared_total = None
        for row in rows[header_index + 1:]:
            if len(row) <= year_col:
                continue
            label = row[0].strip().lower()[:3]
            if label == "tot":
                declared_total = int(row[year_col].replace(",", ""))
            else:
                for month in range(1, 13):
                    if label == dt.date(2000, month, 1).strftime("%b").lower():
                        monthly[month] = int(row[year_col].replace(",", ""))
                        break
        if len(monthly) != 12 or declared_total != sum(monthly.values()) or any(
            value < 0 for value in monthly.values()
        ):
            raise ValueError("FishPal monthly figures do not match its annual total")
        species_data[species] = monthly
    if set(species_data) != {"salmon", "sea_trout"}:
        raise ValueError("FishPal Burnfoot catch tables could not be read")
    return species_data


@st.cache_data(ttl=60 * 60, show_spinner=False)
def burnfoot_catches(year: int) -> tuple[dict, str]:
    fetched_at = dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    html = get_bytes(FISHPAL_BURNFOOT, timeout=20).decode("utf-8", errors="replace")
    return parse_burnfoot_catches(html, year), fetched_at


def clean_reports(upload, selected_year: int) -> tuple[pd.DataFrame, list[str]]:
    columns = [
        "report_id", "date", "river", "beat", "salmon", "grilse", "sea_trout",
        "time", "method", "pressure_hpa", "weather", "wind_mph", "wind_dir", "source_url",
    ]
    empty = pd.DataFrame(columns=columns)
    if upload is None:
        return empty, []
    if upload.size > 2_000_000:
        return empty, ["CSV exceeds 2 MB; upload a smaller file."]
    try:
        data = pd.read_csv(upload, dtype=str, keep_default_na=False).fillna("")
    except Exception as exc:
        return empty, ["Could not read the CSV: " + str(exc)]
    required = {"report_id", "date", "river", "salmon", "grilse", "sea_trout"}
    if not required.issubset(data.columns):
        return empty, ["Missing CSV columns: " + ", ".join(sorted(required - set(data.columns)))]
    for name in columns:
        if name not in data.columns:
            data[name] = ""
    seen = set()
    good = []
    problems = []
    today = dt.datetime.now(dt.timezone.utc).date()
    for line, record in enumerate(data[columns].to_dict("records"), start=2):
        try:
            record_id = str(record["report_id"]).strip()
            date = dt.date.fromisoformat(str(record["date"]).strip())
            river = str(record["river"]).strip()
            salmon, grilse, trout = (
                int(str(record[field]).strip()) for field in ("salmon", "grilse", "sea_trout")
            )
            if (not record_id or record_id in seen or date.year != selected_year
                    or date > today or river not in RIVERS
                    or min(salmon, grilse, trout) < 0 or grilse > salmon):
                raise ValueError("invalid/duplicate ID, date, river or fish counts")
            pressure = str(record["pressure_hpa"]).strip()
            value = float(pressure) if pressure else None
            if value is not None and not 800 <= value <= 1100:
                raise ValueError("pressure outside 800–1100 hPa")
            wind_text = str(record["wind_mph"]).strip()
            wind_speed = float(wind_text) if wind_text else None
            if wind_speed is not None and not 0 <= wind_speed <= 200:
                raise ValueError("wind speed outside 0–200 mph")
            wind_direction = str(record["wind_dir"]).strip().upper()
            compass = {"N", "NNE", "NE", "ENE", "E", "ESE", "SE", "SSE",
                       "S", "SSW", "SW", "WSW", "W", "WNW", "NW", "NNW"}
            if wind_direction and wind_direction not in compass:
                raise ValueError("wind direction must be a compass point (e.g. SW)")
            record.update(date=date, salmon=salmon, grilse=grilse,
                          sea_trout=trout, pressure_hpa=value,
                          wind_mph=wind_speed, wind_dir=wind_direction)
            good.append(record)
            seen.add(record_id)
        except (ValueError, TypeError) as exc:
            problems.append(f"CSV line {line}: {exc}")
    return pd.DataFrame(good, columns=columns), problems


def metric_or_dash(value: int | None) -> str:
    return f"{value:,}" if value is not None else "—"


st.title("Northern salmon and sea trout")
st.caption("Official annual catch returns and 2024 monthly history · current gauge and weather observations")

with st.sidebar:
    st.header("Filters")
    river = st.selectbox("River", list(RIVERS), index=0)
    official_name, default_weather = RIVERS[river]
    selected_year = st.selectbox("Official catch season", list(range(2024, 2007, -1)))
    st.divider()
    st.subheader(f"{CURRENT_YEAR} permissioned catch reports")
    st.caption("Upload only reports you own or have explicit permission to publish. "
               "The separate Burnfoot FishPal test feed is not included in these CSV totals.")
    upload = st.file_uploader("Catch CSV", type=["csv"])

reports, report_problems = clean_reports(upload, CURRENT_YEAR)
with st.sidebar:
    beat_options = sorted(set(reports.loc[reports["river"] == river, "beat"]) - {""}) if len(reports) else []
    if river == "Border Esk" and "Burnfoot" not in beat_options:
        beat_options.insert(0, "Burnfoot")
    beat = st.selectbox("Beat (current-year reports only)", ["All beats", *beat_options])
    st.caption("EA historical catches are river-wide; selecting a beat cannot narrow them.")
    st.divider()
    default_gauge_search = "Canonbie" if river == "Border Esk" else "Esk" if "Esk" in river else river
    search_term = st.text_input("Search EA gauge stations",
                                value=default_gauge_search,
                                key=f"gauge_search_{river}")
    location = st.text_input("Weather location (approximate)", value=default_weather,
                             key=f"weather_location_{river}")

if report_problems:
    st.warning(f"Skipped {len(report_problems)} invalid/duplicate CSV rows. " + "; ".join(report_problems[:3]))

try:
    yearly, monthly, grilse_estimates = load_ea_archive()
except Exception as exc:
    yearly, monthly, grilse_estimates = {}, {}, {}
    st.error(f"Official catch archive unavailable: {exc}")

try:
    weather_key = st.secrets.get("WEATHER_API_KEY", os.getenv("WEATHER_API_KEY", ""))
except (FileNotFoundError, KeyError):
    weather_key = os.getenv("WEATHER_API_KEY", "")
weather = None
weather_error = None
if weather_key:
    try:
        weather = current_weather(weather_key, location)
    except Exception as exc:
        weather_error = str(exc)

nearby = []
gauge_error = None
if weather and river not in GOV_DEFAULT_GAUGES:
    try:
        nearby = matching_gauges(
            gauges_near(float(weather["location"]["lat"]), float(weather["location"]["lon"])),
            river, float(weather["location"]["lat"]), float(weather["location"]["lon"]),
        )
    except Exception as exc:
        gauge_error = str(exc)
try:
    need_search = search_term.strip() and (
        (not nearby and river not in GOV_DEFAULT_GAUGES)
        or search_term.strip() != default_gauge_search
    )
    stations = search_gauges(search_term.strip()) if need_search else []
except Exception as exc:
    stations = []
    if not nearby:
        gauge_error = str(exc)
station_lookup = {}
if river in GOV_DEFAULT_GAUGES:
    name, rloi_id = GOV_DEFAULT_GAUGES[river]
    station_lookup[f"{name} [{rloi_id}]"] = ("", rloi_id)
for station in nearby:
    station_id = str(station.get("notation", ""))
    if station_id and all(char.isalnum() or char in "_-" for char in station_id):
        label = f"Nearby: {station.get('label', station_id)} · {station.get('riverName', 'river unspecified')} [{station_id}]"
        rloi_id = str(station.get("RLOIid") or "")
        station_lookup[label] = (station_id, rloi_id if rloi_id.isdigit() else "")
automatic_match = bool(station_lookup)
for station in stations:
    station_id = str(station.get("notation", ""))
    if station_id and all(char.isalnum() or char in "_-" for char in station_id):
        label = f"Search: {station.get('label', station_id)} · {station.get('riverName', 'river unspecified')} [{station_id}]"
        rloi_id = str(station.get("RLOIid") or "")
        station_lookup[label] = (station_id, rloi_id if rloi_id.isdigit() else "")
with st.sidebar:
    gauge_label = st.selectbox("River-level gauge", ["No gauge selected", *station_lookup],
                               index=1 if automatic_match else 0,
                               key=f"selected_gauge_v3_{river}_{location.strip().lower()}")
    st.caption("Automatically chooses the nearest matching river gauge when available. "
               "Check the station name; its reading is not measured at the beat.")
    if gauge_error:
        st.caption("EA station search currently unavailable: " + gauge_error)
    elif not automatic_match and river != "Border Esk":
        st.caption("No nearby matching gauge found automatically. Choose a verified search result if available.")

st.subheader("Current conditions")
level_col, weather_col, pressure_col, wind_col = st.columns(4)
if gauge_label != "No gauge selected":
    try:
        gauge = gauge_reading(*station_lookup[gauge_label])
        if "value" in gauge:
            timestamp = dt.datetime.fromisoformat(str(gauge["date"]).replace("Z", "+00:00"))
            if timestamp.tzinfo is None:
                timestamp = timestamp.replace(tzinfo=dt.timezone.utc)
            if dt.datetime.now(dt.timezone.utc) - timestamp > dt.timedelta(hours=48):
                level_col.metric("River level at gauge", "Stale reading")
            else:
                level_col.metric("River level at gauge", f"{gauge['value']} {gauge['unit']}")
            level_col.caption(f"{gauge['station']} · {gauge['measure']} · {gauge['date']} (UTC)")
        else:
            level_col.metric("River level at gauge", "Unavailable")
            level_col.caption(str(gauge.get("station", "")))
    except Exception as exc:
        level_col.metric("River level at gauge", "Unavailable")
        level_col.caption(f"EA gauge request failed: {exc}")
else:
    level_col.metric("River level at gauge", "Select a gauge")

if weather:
    try:
        weather_col.metric("Weather now", weather["current"]["condition"]["text"])
        weather_col.caption(f"{location} · {weather['current']['temp_c']} °C · observed {weather['current']['last_updated']}")
        pressure_col.metric("Barometric pressure now", f"{weather['current']['pressure_mb']} hPa")
        pressure_col.caption("WeatherAPI · nearby location, not the beat")
        wind_speed = weather["current"].get("wind_mph")
        wind_direction = weather["current"].get("wind_dir")
        wind_col.metric("Wind now", f"{wind_direction} · {wind_speed} mph" if wind_direction and wind_speed is not None else "Unavailable")
        wind_col.caption(f"Direction and speed at {location}")
    except Exception as exc:
        weather_col.metric("Weather now", "Unavailable")
        pressure_col.metric("Barometric pressure now", "Unavailable")
        wind_col.metric("Wind now", "Unavailable")
        weather_col.caption(f"Weather response unavailable: {exc}")
else:
    status = "Unavailable" if weather_key else "API key needed"
    weather_col.metric("Weather now", status)
    pressure_col.metric("Barometric pressure now", status)
    wind_col.metric("Wind now", status)
    weather_col.caption("Weather request failed: " + weather_error if weather_error else
                        "Set WEATHER_API_KEY in your deployment secrets.")
if weather_key:
    st.info("Weather conditions and forecasts are uncertain and may differ at your exact river or time. "
            "They are for general information, not the sole basis for personal safety, boating, "
            "emergency or other safety-critical decisions. Check official meteorological services "
            "and relevant authorities when accuracy is critical.")

st.divider()
st.subheader(f"Official declared rod catches · {selected_year} · {river}")
if beat != "All beats":
    st.info("Official figures are available by river, not by beat. They are not shown as Burnfoot/beat catches.")
else:
    figures = yearly.get((official_name, selected_year), {})
    k1, k2, k3 = st.columns(3)
    k1.metric("Salmon caught", metric_or_dash(figures.get("salmon")))
    k2.metric("Sea trout caught", metric_or_dash(figures.get("sea_trout")))
    estimate = grilse_estimates.get(official_name) if selected_year == 2024 else None
    k3.metric("Grilse (estimated)", f"about {round(estimate):,}" if estimate is not None else "Not published")
    st.caption("Grilse are a subset of salmon; never add them to the salmon total. Official records are declared catches, not all fish caught.")
    years = [
        {"Year": year, "Salmon": yearly.get((official_name, year), {}).get("salmon"),
         "Sea trout": yearly.get((official_name, year), {}).get("sea_trout")}
        for year in range(2008, 2025)
    ]
    st.bar_chart(pd.DataFrame(years).set_index("Year"), y=["Salmon", "Sea trout"])
    st.caption("Source: EA 2024 supplementary workbook, Tables 34, 35 and 38 (2008–2024 series).")
    if selected_year == 2024:
        st.subheader("2024 monthly catch pattern (official)")
        history = pd.DataFrame([
            {"Month": dt.date(2024, m, 1).strftime("%b"),
             "Salmon": monthly.get((official_name, m), {}).get("salmon"),
             "Sea trout": monthly.get((official_name, m), {}).get("sea_trout"),
             "Pressure (hPa)": "Not in EA catches", "Weather": "Not in EA catches",
             "Wind (mph)": "Not in EA catches", "Wind direction": "Not in EA catches"}
            for m in range(1, 13)
        ])
        unallocated = monthly.get((official_name, 0), {})
        if any(value for value in unallocated.values()):
            history.loc[len(history)] = {
                "Month": "Unknown month", "Salmon": unallocated.get("salmon"),
                "Sea trout": unallocated.get("sea_trout"),
                "Pressure (hPa)": "Not in EA catches", "Weather": "Not in EA catches",
                "Wind (mph)": "Not in EA catches", "Wind direction": "Not in EA catches",
            }
        st.bar_chart(history.set_index("Month")[["Salmon", "Sea trout"]])
        st.dataframe(history, hide_index=True, use_container_width=True)
        st.caption("EA Tables 27–28. 'Unknown month' keeps undated catches in the official total. Pressure/weather today must not be attached to fish caught in 2024.")
    else:
        st.caption("This archive provides the selected season's annual river figures; the monthly breakdown above is only verified for 2024.")

st.divider()
if river == "Border Esk" and beat in {"All beats", "Burnfoot"}:
    st.subheader(f"Burnfoot beat · {CURRENT_YEAR} FishPal catches (private test)")
    st.caption("Burnfoot only, not the whole Border Esk. Figures are as posted on FishPal; "
               "they are separate from EA annual totals and uploaded catch reports.")
    try:
        fishpal, retrieved_at = burnfoot_catches(CURRENT_YEAR)
        current_month = dt.datetime.now(dt.timezone.utc).month
        month_rows = [
            {"Month": dt.date(CURRENT_YEAR, month, 1).strftime("%b"),
             "Salmon": fishpal["salmon"][month],
             "Sea trout": fishpal["sea_trout"][month]}
            for month in range(1, current_month + 1)
        ]
        x, y, z = st.columns(3)
        x.metric("Burnfoot salmon", sum(row["Salmon"] for row in month_rows))
        y.metric("Burnfoot sea trout", sum(row["Sea trout"] for row in month_rows))
        z.metric("Grilse", "Not separately reported")
        fishpal_monthly = pd.DataFrame(month_rows)
        st.bar_chart(fishpal_monthly.set_index("Month")[["Salmon", "Sea trout"]])
        st.dataframe(fishpal_monthly, hide_index=True, use_container_width=True)
        st.caption(f"[Source: Burnfoot on FishPal]({FISHPAL_BURNFOOT}#CatchesSection) · "
                   f"page retrieved {retrieved_at}; refreshes at most hourly. "
                   "The page gives monthly counts, not catch dates/times, methods, "
                   "or historical weather/pressure. Grilse may be included in salmon.")
    except Exception as exc:
        st.warning("Burnfoot FishPal catch data are unavailable right now; no figures "
                   "have been inferred from a previous snapshot. " + str(exc))
    st.divider()
st.subheader(f"Permissioned reports · 1 January–today {CURRENT_YEAR}")
if len(reports):
    filtered = reports[reports["river"] == river].copy()
    if beat != "All beats":
        filtered = filtered[filtered["beat"] == beat]
    if len(filtered):
        a, b, c = st.columns(3)
        a.metric("Reported salmon", f"{filtered['salmon'].sum():,}")
        b.metric("Of which grilse", f"{filtered['grilse'].sum():,}")
        c.metric("Reported sea trout", f"{filtered['sea_trout'].sum():,}")
        grouped = []
        for month in range(1, dt.datetime.now(dt.timezone.utc).month + 1):
            subset = filtered[filtered["date"].map(lambda date: date.month == month)]
            pressures = subset["pressure_hpa"].dropna()
            weather_words = [str(word).strip() for word in subset["weather"] if str(word).strip()]
            wind_speeds = subset["wind_mph"].dropna()
            wind_directions = [str(direction) for direction in subset["wind_dir"] if str(direction)]
            grouped.append({
                "Month": dt.date(CURRENT_YEAR, month, 1).strftime("%b"),
                "Salmon": int(subset["salmon"].sum()),
                "Grilse (included in salmon)": int(subset["grilse"].sum()),
                "Sea trout": int(subset["sea_trout"].sum()),
                "Average pressure (hPa)": round(float(pressures.mean()), 1) if len(pressures) else None,
                "Weather reported": ", ".join(f"{name} ({n})" for name, n in Counter(weather_words).most_common(3)) or "Not known",
                "Average wind (mph)": round(float(wind_speeds.mean()), 1) if len(wind_speeds) else None,
                "Wind directions reported": ", ".join(f"{name} ({n})" for name, n in Counter(wind_directions).most_common(3)) or "Not known",
            })
        by_month = pd.DataFrame(grouped)
        st.bar_chart(by_month.set_index("Month")[["Salmon", "Sea trout"]])
        st.dataframe(by_month, hide_index=True, use_container_width=True)
        st.caption("Monthly pressure and wind speed average only recorded values; weather and wind directions summarise reports with observations. Missing data remain unknown.")
        st.dataframe(filtered[["date", "river", "beat", "salmon", "grilse", "sea_trout", "time", "method", "pressure_hpa", "weather", "wind_mph", "wind_dir", "source_url"]],
                     hide_index=True, use_container_width=True)
    else:
        st.info("No permissioned reports for this river/beat in the uploaded CSV.")
else:
    st.info("No current-year catch reports loaded. Upload permissioned reports to enable beat totals, time/method details, and monthly pressure/weather/wind alongside catches.")

with st.expander("CSV format, provenance and commercial launch notes"):
    st.code("report_id,date,river,beat,salmon,grilse,sea_trout,time,method,pressure_hpa,weather,wind_mph,wind_dir,source_url\n"
            f"your-unique-id,{CURRENT_YEAR}-06-15,Border Esk,Burnfoot,1,1,0,18:30,Fly,1013,Cloudy,12,SW,https://your-own-permissioned-record.example", language="csv")
    st.write("One unique report_id per catch record; date must be YYYY-MM-DD. Salmon includes grilse."
             " The CSV is session-only and does not update a shared database. A zero means an explicitly reported zero, not missing data.")
    st.write("The Burnfoot FishPal feed is for private testing only; confirm FishPal access rights "
             "or arrange a direct Burnfoot feed before public/commercial launch. Before charging subscribers,"
             " add server-side sign-in, verified payment entitlements, durable permissioned reports and a privacy policy."
             " This file intentionally contains no pretend paywall.")
    st.markdown(f"EA annual catch archive: [data.gov.uk]({EA_ARCHIVE}) (Open Government Licence). "
                "© Environment Agency copyright and/or database right 2015. "
                "[EA gauge API](https://environment.data.gov.uk/flood-monitoring/doc/reference) "
                "(Open Government Licence). "
                "Weather: [WeatherAPI.com](https://www.weatherapi.com/) "
                "([terms](https://www.weatherapi.com/terms.aspx)); check your plan and attribution requirements.")

st.caption("Contains Environment Agency data © Environment Agency copyright and/or database right 2015, "
           "licensed under the Open Government Licence v3.0. Weather data © WeatherAPI.com when configured.")

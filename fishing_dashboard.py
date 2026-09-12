"""Northern salmon and sea trout dashboard (single-file Streamlit app).

GitHub: save this file as app.py and add a requirements.txt containing:
    streamlit>=1.42,<2
    pandas>=2,<3
    openpyxl>=3.1,<4
    altair>=5,<7

Run: streamlit run app.py
Optional live weather: set WEATHER_API_KEY in Streamlit deployment secrets
or as a server-side environment variable. Never put the key in GitHub.
Optional dated beat catches: put a permissioned catch_reports.csv alongside
this .py file in GitHub, or upload one using the sidebar. The upload takes
precedence for that session. Beat names from that file appear under each river.

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
from zoneinfo import ZoneInfo
from urllib.parse import urlencode
from urllib.request import Request, urlopen

import openpyxl
import altair as alt
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
SEPA_CANONBIE_API = "https://timeseries.sepa.org.uk/KiWIS/KiWIS"
SEPA_CANONBIE_STATION = "https://waterlevels.sepa.org.uk/Station/133148"
WEATHER_API = "https://api.weatherapi.com/v1/current.json"
WEATHER_HISTORY_API = "https://api.weatherapi.com/v1/history.json"
FISHPAL_BURNFOOT = "https://www.fishpal.com/scotland/borderesk/burnfoot/"
FISHPAL_BORDER_ESK_DAILY = "https://www.fishpal.com/scotland/borderesk/catches.html"
UK_TIME = ZoneInfo("Europe/London")
WEEKDAY_NAMES = ("monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday")
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
# Verified beats can be listed here; imported catch reports also contribute
# beat names for their own river. Do not infer beat totals from river data.
KNOWN_BEATS = {"Border Esk": ("Burnfoot",)}
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


def parse_gauge_csv(content: str, days: list[dt.date]) -> dict[dt.date, float]:
    by_day = {}
    for row in csv.DictReader(io.StringIO(content)):
        try:
            if row.get("Type(observed/forecast)", "").strip().lower() == "forecast":
                continue
            timestamp = dt.datetime.fromisoformat(row["Timestamp (UTC)"].replace("Z", "+00:00"))
            height = float(row["Height (m)"])
            local_date = timestamp.astimezone(UK_TIME).date() if timestamp.tzinfo else None
            if (local_date in days and timestamp <= dt.datetime.now(dt.timezone.utc)
                    and math.isfinite(height)):
                by_day.setdefault(local_date, []).append(height)
        except (ValueError, KeyError, TypeError):
            continue
    return {day: round(sum(values) / len(values), 3) for day, values in by_day.items()}


def parse_sepa_levels(content: str, days: tuple[dt.date, ...]) -> dict[dt.date, float]:
    """SEPA KiWIS CSV has # metadata lines, then timestamp,value data rows."""
    by_day = {}
    now = dt.datetime.now(dt.timezone.utc)
    for row in csv.reader(io.StringIO(content)):
        if not row or row[0].lstrip().startswith("#"):
            continue
        if len(row) < 2 and ";" in row[0]:
            row = next(csv.reader([row[0]], delimiter=";"))
        if len(row) < 2:
            continue
        try:
            timestamp = dt.datetime.fromisoformat(row[0].strip().strip('"'))
            height = float(row[1].strip().strip('"'))
            if timestamp.tzinfo is None:
                # Never guess an offset on historical readings.
                continue
            day = timestamp.astimezone(UK_TIME).date()
            if day in days and timestamp <= now and math.isfinite(height):
                by_day.setdefault(day, []).append(height)
        except (ValueError, TypeError):
            continue
    return {day: round(sum(values) / len(values), 3) for day, values in by_day.items()}


@st.cache_data(ttl=60 * 60, show_spinner=False)
def sepa_canonbie_daily_levels(days: tuple[dt.date, ...]) -> dict:
    # Station/path comes from SEPA's own Canonbie station page (1-month download).
    query = {
        "service": "kisters", "type": "queryServices", "datasource": "0",
        "request": "getTimeseriesValues", "ts_path": "1/133148/SG/15m.Cmd",
        "period": "P8D", "metadata": "true", "returnfields": "Timestamp,Value",
        "dateformat": "yyyy-MM-dd'T'HH:mm:ssXXX", "format": "csv", "csvdiv": ",",
    }
    content = get_bytes(SEPA_CANONBIE_API + "?" + urlencode(query), timeout=20).decode(
        "utf-8-sig", errors="replace"
    )
    daily = parse_sepa_levels(content, days)
    if not daily:
        raise ValueError("SEPA Canonbie readings were not available in the requested period")
    return daily


@st.cache_data(ttl=60 * 60, show_spinner=False)
def gauge_daily_levels(station_id: str, rloi_id: str, days: tuple[dt.date, ...]) -> dict:
    if rloi_id:
        # Same official public station as the current-level tile.
        body = get_bytes(GOV_GAUGE_CSV + rloi_id, timeout=18).decode("utf-8-sig")
        return parse_gauge_csv(body, list(days))
    if not station_id or not all(c.isalnum() or c in "_-" for c in station_id):
        return {}
    station = get_json(GAUGE_API + "/" + station_id).get("items", {})
    if isinstance(station, list):
        station = station[0] if station else {}
    measures = station.get("measures", [])
    if isinstance(measures, dict):
        measures = [measures]
    stage = next((m for m in measures if m.get("parameter") == "level"
                  and m.get("qualifier") == "Stage"), None)
    identifier = str((stage or {}).get("@id", "")).rstrip("/").rsplit("/", 1)[-1]
    if not identifier or not all(c.isalnum() or c in "_-" for c in identifier):
        return {}
    base = "https://environment.data.gov.uk/flood-monitoring/id/measures/"
    result = get_json(base + identifier + "/readings?" + urlencode({
        "startdate": (days[0] - dt.timedelta(days=1)).isoformat(),
        "enddate": days[-1].isoformat(), "_limit": 10000,
    }), timeout=22).get("items", [])
    by_day = {}
    for reading in result:
        try:
            timestamp = dt.datetime.fromisoformat(reading["dateTime"].replace("Z", "+00:00"))
            level = float(reading["value"])
            local_date = timestamp.astimezone(UK_TIME).date() if timestamp.tzinfo else None
            if local_date in days and math.isfinite(level):
                by_day.setdefault(local_date, []).append(level)
        except (ValueError, TypeError, KeyError):
            continue
    return {day: round(sum(values) / len(values), 3) for day, values in by_day.items()}


@st.cache_data(ttl=60 * 60, show_spinner=False)
def weather_daily_history(key: str, location: str, days: tuple[dt.date, ...]) -> tuple[dict, bool]:
    result = {}
    for day in days:
        if day == dt.datetime.now(dt.timezone.utc).date():
            continue  # Today's current observation is labelled separately.
        try:
            payload = get_json(WEATHER_HISTORY_API + "?" + urlencode({
                "key": key, "q": location, "dt": day.isoformat(),
            }), timeout=12)
            summary = payload["forecast"]["forecastday"][0]["day"]
            result[day] = str(summary["condition"]["text"])
        except Exception:
            # A missing history subscription should never expose the API key in an error.
            return result, False
    return result, True


def weather_icon(condition: str) -> str:
    """Use a simple symbol for a WeatherAPI description; never guess missing days."""
    words = str(condition or "").lower()
    if not words or words == "not available":
        return "—"
    if any(term in words for term in ("thunder", "lightning")):
        return "⛈️"
    if any(term in words for term in ("snow", "blizzard", "ice", "icy")):
        return "🌨️"
    if any(term in words for term in ("sleet", "freezing rain")):
        return "🌧️"
    if any(term in words for term in ("rain", "drizzle", "shower")):
        return "🌧️"
    if any(term in words for term in ("fog", "mist", "haze")):
        return "🌫️"
    if "partly cloudy" in words:
        return "⛅"
    if any(term in words for term in ("overcast", "cloud")):
        return "☁️"
    if any(term in words for term in ("sun", "clear")):
        return "☀️"
    return "🌤️"


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
        self.section_words = []

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
        elif self.table is None and self.heading in {"atlantic salmon", "sea trout"}:
            self.section_words.append(data)
        if self.cell is not None:
            self.cell.append(data)

    def handle_endtag(self, tag):
        if tag == self.heading_tag:
            self.heading = " ".join(" ".join(self.heading_words).split()).lower()
            self.section_words = []
            self.heading_tag = None
        elif tag in {"td", "th"} and self.cell is not None:
            self.row.append(" ".join(" ".join(self.cell).split()))
            self.cell = None
        elif tag == "tr" and self.row is not None:
            if self.row:
                self.table.append(self.row)
            self.row = None
        elif tag == "table" and self.table is not None:
            self.tables.append((self.heading, self.table, " ".join(self.section_words)))
            self.table = None


def parse_burnfoot_catches(html: str, year: int) -> dict:
    parser = _CatchTableParser()
    parser.feed(html)
    species_data = {}
    last_seven = {}
    for heading, rows, section_text in parser.tables:
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
        recent = re.search(r"Last\s*7\s*days\s*:\s*([0-9,]+)", section_text, re.I)
        if recent:
            last_seven[species] = int(recent.group(1).replace(",", ""))
    if set(species_data) != {"salmon", "sea_trout"}:
        raise ValueError("FishPal Burnfoot catch tables could not be read")
    species_data["last_seven"] = last_seven
    return species_data


@st.cache_data(ttl=60 * 60, show_spinner=False)
def burnfoot_catches(year: int) -> tuple[dict, str]:
    fetched_at = dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    html = get_bytes(FISHPAL_BURNFOOT, timeout=20).decode("utf-8", errors="replace")
    return parse_burnfoot_catches(html, year), fetched_at


class _WeekdayCatchParser(HTMLParser):
    """Pick Burnfoot's two species columns, excluding river-wide subtotals."""

    weekdays = set(WEEKDAY_NAMES)

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.current_week = False
        self.day = None
        self.row = None
        self.cell = None
        self.counts = {}
        self.seen_totals = {}

    def handle_starttag(self, tag, attrs):
        if tag == "tr":
            self.row = []
        elif tag in {"td", "th"} and self.row is not None:
            self.cell = []

    def handle_data(self, data):
        text = " ".join(data.split()).lower()
        if "for the current week" in text:
            self.current_week = True
        if "week so far" in text or "last week" in text:
            self.current_week = False
        if self.current_week and text in self.weekdays:
            self.day = text
        if self.cell is not None:
            self.cell.append(data)

    def handle_endtag(self, tag):
        if tag in {"td", "th"} and self.cell is not None:
            self.row.append(" ".join(" ".join(self.cell).split()))
            self.cell = None
        elif tag == "tr" and self.row is not None:
            if self.current_week and self.row:
                for value in self.row:
                    if value.lower() in self.weekdays:
                        self.day = value.lower()
                if self.day and len(self.row) >= 2:
                    for column, species in enumerate(("salmon", "sea_trout")):
                        value = self.row[column]
                        found = re.search(r"\bBurnfoot\s*[-–:]\s*([0-9,]+)\b", value, re.I)
                        if found:
                            day_counts = self.counts.setdefault(self.day, {})
                            # The beat should occur only once per day and species.
                            if species in day_counts:
                                raise ValueError("Duplicate Burnfoot daily catch entry")
                            day_counts[species] = int(found.group(1).replace(",", ""))
                        if re.search(r"\bTotal\s*:\s*[0-9,]+", value, re.I):
                            self.seen_totals.setdefault(self.day, set()).add(species)
            self.row = None


def parse_burnfoot_weekdays(html: str, today: dt.date) -> dict[dt.date, dict]:
    parser = _WeekdayCatchParser()
    parser.feed(html)
    if not parser.seen_totals:
        raise ValueError("FishPal weekly catch table could not be read")
    week_start = today - dt.timedelta(days=today.weekday())
    result = {}
    for name, totals in parser.seen_totals.items():
        day = week_start + dt.timedelta(days=WEEKDAY_NAMES.index(name))
        if day > today:
            continue
        result[day] = {species: parser.counts.get(name, {}).get(species, 0)
                       for species in totals}
    return result


@st.cache_data(ttl=60 * 60, show_spinner=False)
def burnfoot_daily_catches(today: dt.date) -> tuple[dict, str]:
    html = get_bytes(FISHPAL_BORDER_ESK_DAILY, timeout=20).decode("utf-8", errors="replace")
    fetched_at = dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    return parse_burnfoot_weekdays(html, today), fetched_at


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
            beat_name = str(record["beat"]).strip()
            beat_name = next((known for known in KNOWN_BEATS.get(river, ())
                              if known.casefold() == beat_name.casefold()), beat_name)
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
            record.update(date=date, beat=beat_name, salmon=salmon, grilse=grilse,
                          sea_trout=trout, pressure_hpa=value,
                          wind_mph=wind_speed, wind_dir=wind_direction)
            good.append(record)
            seen.add(record_id)
        except (ValueError, TypeError) as exc:
            problems.append(f"CSV line {line}: {exc}")
    return pd.DataFrame(good, columns=columns), problems


def metric_or_dash(value: int | None) -> str:
    return f"{value:,}" if value is not None else "—"


def saved_catch_upload():
    """Load a small permissioned catch CSV checked into the app repository."""
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "catch_reports.csv")
    if not os.path.isfile(path):
        return None
    size = os.path.getsize(path)
    if size > 2_000_000:
        raise ValueError("catch_reports.csv exceeds the 2 MB upload limit")
    with open(path, "rb") as saved:
        data = io.BytesIO(saved.read())
    data.size = size
    return data


st.title("Northern salmon and sea trout")
st.caption("Daily river and weather conditions · Burnfoot seven-day catches · separate EA history")

with st.sidebar:
    st.header("Filters")
    view = st.radio("Dashboard page", ["Last 7 days", "Catch history and reports"])
    river = st.selectbox("River", list(RIVERS), index=0)
    beat_slot = st.container()  # Filled after the catch CSV has been checked.
    official_name, default_weather = RIVERS[river]
    selected_year = (st.selectbox("Official catch season", list(range(2024, 2007, -1)))
                     if view == "Catch history and reports" else 2024)
    st.divider()
    st.subheader(f"{CURRENT_YEAR} permissioned catch reports")
    st.caption("Upload reports you can publish, or save catch_reports.csv next to your app "
               "in GitHub. Uploads replace that saved file for the session. "
               "The Burnfoot FishPal test feed is not included in these CSV totals.")
    upload = st.file_uploader("Catch CSV", type=["csv"])
    st.download_button(
        "Download empty catch CSV template",
        data=("report_id,date,river,beat,salmon,grilse,sea_trout,time,method,"
              "pressure_hpa,weather,wind_mph,wind_dir,source_url\n"),
        file_name="catch_reports.csv", mime="text/csv",
    )

saved_error = None
if upload is None:
    try:
        upload = saved_catch_upload()
    except OSError as exc:
        saved_error = f"Cannot open catch_reports.csv: {exc}"
    except ValueError as exc:
        saved_error = str(exc)
reports, report_problems = clean_reports(upload, CURRENT_YEAR)
with beat_slot:
    uploaded_beats = (set(reports.loc[reports["river"] == river, "beat"]) - {""}
                      if len(reports) else set())
    beat_options = sorted(set(KNOWN_BEATS.get(river, ())) | uploaded_beats,
                          key=str.casefold)
    st.subheader(f"{river} beats")
    beat = st.radio("Select a beat", ["All beats", *beat_options],
                    key=f"selected_beat_{river}")
    if not beat_options:
        st.caption("No named beats loaded for this river. Add their names to KNOWN_BEATS "
                   "in the .py file or add dated catches to catch_reports.csv.")
    if river == "Border Esk":
        st.caption("[Browse FishPal's Border Esk listings](https://www.fishpal.com/search/in/Border%20Esk) "
                   "for reference; they are not imported into this app.")
    st.caption("Beat catches need dated reports for this beat. The EA archive "
               "and gauge are river-wide.")
with st.sidebar:
    st.divider()
    default_gauge_search = "Canonbie" if river == "Border Esk" else "Esk" if "Esk" in river else river
    search_term = st.text_input("Search EA gauge stations",
                                value=default_gauge_search,
                                key=f"gauge_search_{river}")
    location = st.text_input("Weather location (approximate)", value=default_weather,
                             key=f"weather_location_{river}")

if report_problems:
    st.warning(f"Skipped {len(report_problems)} invalid/duplicate CSV rows. " + "; ".join(report_problems[:3]))
if saved_error:
    st.warning(saved_error)

yearly, monthly, grilse_estimates = {}, {}, {}
if view == "Catch history and reports":
    try:
        yearly, monthly, grilse_estimates = load_ea_archive()
    except Exception as exc:
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
if view == "Last 7 days":
    today = dt.datetime.now(UK_TIME).date()
    days = tuple(today - dt.timedelta(days=offset) for offset in range(6, -1, -1))
    st.subheader(f"Past 7 days · {river}" + (f" · {beat}" if beat != "All beats" else ""))
    levels = {}
    level_source = "government gauge"
    if gauge_label != "No gauge selected":
        try:
            station_id, rloi_id = station_lookup[gauge_label]
            if rloi_id == "5207":
                try:
                    levels = sepa_canonbie_daily_levels(days)
                    level_source = "SEPA Canonbie (one source across the seven-day graph)"
                except Exception:
                    levels = gauge_daily_levels(station_id, rloi_id, days)
                    level_source = "GOV.UK Canonbie (five-day CSV fallback)"
            else:
                levels = gauge_daily_levels(station_id, rloi_id, days)
        except Exception:
            st.caption("The selected government gauge has no accessible seven-day history right now.")
    conditions = {}
    history_ok = False
    if weather_key:
        conditions, history_ok = weather_daily_history(weather_key, location, days)
    if weather and weather.get("current", {}).get("condition", {}).get("text"):
        conditions[today] = "Now: " + weather["current"]["condition"]["text"]

    recent_counts = {}
    fishpal_daily = {}
    fishpal_retrieved = ""
    if river == "Border Esk" and beat in {"All beats", "Burnfoot"}:
        try:
            fishpal_week, _ = burnfoot_catches(CURRENT_YEAR)
            recent_counts = fishpal_week.get("last_seven", {})
            if "salmon" in recent_counts:
                st.metric("Burnfoot salmon · last 7 days (FishPal)", recent_counts["salmon"])
        except Exception:
            st.warning("Burnfoot's seven-day FishPal total is temporarily unavailable.")
        try:
            fishpal_daily, fishpal_retrieved = burnfoot_daily_catches(today)
        except Exception:
            st.warning("FishPal's weekday catches are temporarily unavailable; "
                       "only dated CSV reports can appear as daily bars.")

    daily_uploads = reports[reports["river"] == river].copy() if len(reports) else reports.copy()
    if beat != "All beats" and len(daily_uploads):
        daily_uploads = daily_uploads[daily_uploads["beat"] == beat]
    use_fishpal_daily = bool(fishpal_daily)
    catch_source = "FishPal · Burnfoot only" if use_fishpal_daily else "Permissioned dated reports"
    rows = []
    for day in days:
        matching = daily_uploads[daily_uploads["date"] == day] if len(daily_uploads) else daily_uploads
        daily = (fishpal_daily.get(day, {}) if use_fishpal_daily else
                 {"salmon": int(matching["salmon"].sum()),
                  "sea_trout": int(matching["sea_trout"].sum())} if len(matching) else {})
        rows.append({"Date": day, "Day": day.strftime("%a %d %b"),
                     "Water level (m)": levels.get(day),
                     "Reported salmon": daily.get("salmon"),
                     "Reported sea trout": daily.get("sea_trout"),
                     "Weather": conditions.get(day, "Not available"),
                     "Weather icon": weather_icon(conditions.get(day, "Not available"))})
    seven = pd.DataFrame(rows)
    plots = []
    # A categorical day axis gives exactly seven positions; a temporal axis
    # inserted several ticks per day and repeated the same formatted date.
    day_labels = [day.strftime("%a %d %b") for day in days]
    base = alt.Chart(seven).encode(x=alt.X(
        "Day:N", sort=day_labels, title=None,
        axis=alt.Axis(labelAngle=0, labelOverlap=False),
    ))
    if levels:
        plots.append(base.mark_line(point=True, color="#0873b9").encode(
            y=alt.Y("Water level (m):Q", scale=alt.Scale(zero=False)),
            tooltip=[alt.Tooltip("Date:T", format="%a %d %b"),
                     alt.Tooltip("Water level (m):Q", format=".3f")]
        ).properties(height=170, title="Daily mean water level at selected gauge"))
    if seven["Reported salmon"].notna().any():
        plots.append(base.mark_bar(color="#e77d30", size=25).encode(
            y=alt.Y("Reported salmon:Q", title="Reported salmon"),
            tooltip=[alt.Tooltip("Date:T", format="%a %d %b"), "Reported salmon:Q",
                     "Reported sea trout:Q", "Water level (m):Q", "Weather:N"]
        ).properties(height=140, title="Dated catches · " + catch_source))
    weather_strip = base.mark_text(fontSize=28, baseline="middle").encode(
        y=alt.value(32),
        text=alt.Text("Weather icon:N"),
        tooltip=[alt.Tooltip("Date:T", format="%a %d %b"),
                 alt.Tooltip("Weather:N", title="Condition")]
    ).properties(height=64, title="Weather by day · nearby location")
    plots.append(weather_strip)
    st.altair_chart(alt.vconcat(*plots).resolve_scale(x="shared"), use_container_width=True)
    st.dataframe(seven.drop(columns="Day"), hide_index=True, use_container_width=True)
    st.caption("Hover over a weather icon for the exact condition. — means weather data "
               "were unavailable for that day; today’s icon is the current observation.")
    st.caption(f"Gauge: {level_source}; observed daily mean grouped by UK calendar date, "
               "not a reading at the beat. This is a gauge level, not FishPal's height above summer lows. "
               "catch and gauge data are aligned by date, not by exact catch time. Missing days stay blank. "
               "Weather: daily historical condition for prior days; today is the current observation, "
               "not a full-day summary. No weather is assigned to individual catches.")
    if level_source.startswith("SEPA"):
        st.caption(f"[SEPA Canonbie station and data]({SEPA_CANONBIE_STATION}); "
                   "[GOV.UK current Canonbie gauge](https://check-for-flooding.service.gov.uk/station/5207). "
                   "The current-level tile above comes from GOV.UK; the seven-day line uses SEPA. "
                   "Contains SEPA data © Scottish Environment Protection Agency, "
                   "licensed under the Open Government Licence v3.0.")
    if not levels:
        st.info("No daily water levels were available for this gauge. Check the gauge selection or its government feed.")
    if use_fishpal_daily:
        st.caption(f"[Daily Burnfoot catches on FishPal]({FISHPAL_BORDER_ESK_DAILY}) · "
                   f"page retrieved {fishpal_retrieved}. The weekday table covers the current week only; "
                   "days from last week are unknown without a saved dated catch log. "
                   "These bars are Burnfoot-only, even when 'All beats' is selected, and are not added to CSV counts.")
    elif not len(daily_uploads):
        st.info("No dated catches are loaded for this river/beat. Only Burnfoot has a separate "
                "test catch feed; other beats need permissioned catch_reports.csv records "
                "or a sidebar CSV upload. River-wide EA totals are on the history page.")
    elif not seven["Reported salmon"].notna().any():
        st.info("No dated catches were reported for this beat in the past seven days. "
                "This is unknown, not zero; earlier reports are on the history page.")
    if not history_ok:
        st.caption("Past-day weather needs History API access on your WeatherAPI key; "
                   "unavailable days are not filled with today's weather.")
    st.stop()

st.subheader(f"Official declared rod catches · {selected_year} · {river}")
if beat != "All beats":
    st.info(f"These {selected_year} Environment Agency figures are for the whole {river}, "
            f"not {beat}. Beat-specific catches appear below only when dated "
            "permissioned reports or the separate Burnfoot test feed are available.")
    whole_river = yearly.get((official_name, selected_year), {})
    r1, r2 = st.columns(2)
    r1.metric("River-wide salmon", metric_or_dash(whole_river.get("salmon")))
    r2.metric("River-wide sea trout", metric_or_dash(whole_river.get("sea_trout")))
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
        st.info("No permissioned catch reports for this river/beat. Check catch_reports.csv "
                "beside the app or upload a dated CSV in the sidebar.")
else:
    st.info("No current-year beat catch reports loaded. Save permissioned "
            "catch_reports.csv beside the .py file in GitHub or upload one in the sidebar. "
            "The Environment Agency publishes annual river-wide totals, not live beat catches.")

with st.expander("CSV format, provenance and commercial launch notes"):
    st.code("report_id,date,river,beat,salmon,grilse,sea_trout,time,method,pressure_hpa,weather,wind_mph,wind_dir,source_url\n"
            f"your-unique-id,{CURRENT_YEAR}-06-15,Border Esk,Burnfoot,1,1,0,18:30,Fly,1013,Cloudy,12,SW,https://your-own-permissioned-record.example", language="csv")
    st.write("One unique report_id per catch record; date must be YYYY-MM-DD. Salmon includes grilse."
             " A sidebar upload is session-only; catch_reports.csv beside the app loads on restart. "
             "Neither updates a shared database. Zero means an explicitly reported zero, not missing data.")
    st.write("The Burnfoot FishPal feed is for private testing only; confirm FishPal access rights "
             "or arrange a direct Burnfoot feed before public/commercial launch. Before charging subscribers,"
             " add server-side sign-in, verified payment entitlements, durable permissioned reports and a privacy policy."
             " This file intentionally contains no pretend paywall.")
    st.write("SEPA provides Canonbie time-series data under the Open Government Licence; "
             "SEPA recommends registering API access if including the data in a web product. "
             "Anonymous access can be rate-limited. The seven-day graph falls back to the "
             "GOV.UK five-day CSV if the SEPA feed is unavailable.")
    st.markdown(f"EA annual catch archive: [data.gov.uk]({EA_ARCHIVE}) (Open Government Licence). "
                "© Environment Agency copyright and/or database right 2015. "
                "[EA gauge API](https://environment.data.gov.uk/flood-monitoring/doc/reference) "
                "(Open Government Licence). "
                "Weather: [WeatherAPI.com](https://www.weatherapi.com/) "
                "([terms](https://www.weatherapi.com/terms.aspx)); check your plan and attribution requirements.")

st.caption("Contains Environment Agency data © Environment Agency copyright and/or database right 2015, "
           "licensed under the Open Government Licence v3.0. Weather data © WeatherAPI.com when configured.")

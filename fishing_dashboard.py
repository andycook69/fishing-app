"""Northern salmon and sea trout dashboard (single-file Streamlit app).

GitHub: save this file as app.py and add a requirements.txt containing:
    streamlit>=1.42,<2
    pandas>=2,<3
    openpyxl>=3.1,<4
    altair>=5,<7

Run: streamlit run app.py
Place the supplied illustrative salmon_river_banner.png beside app.py for the
banner. If you later have an authorised actual Burnfoot photograph, put it at
burnfoot_header.jpg beside app.py to use it on the Border Esk view instead.
Optional live weather: set WEATHER_API_KEY in Streamlit deployment secrets
or as a server-side environment variable. Never put the key in GitHub.
Optional dated beat catches: put a permissioned catch_reports.csv alongside
this .py file in GitHub, or upload one using the sidebar. The upload takes
precedence for that session. Beat names from that file appear under each river.

Data: EA annual declared rod catches (2008–2024, 2024 workbook);
EA 2024 monthly rod catches and estimated grilse; EA gauge readings;
WeatherAPI current conditions and forecasts; Environment Agency live tide gauges;
Open-Meteo modelled tide fallback for private non-commercial testing;
private-test Burnfoot and Tweed FishPal figures;
optional *permissioned* current-year CSV.
This app has no subscriber authentication or payment integration.
"""

from __future__ import annotations

import datetime as dt
import base64
import csv
import io
import math
import os
import re
from collections import Counter
from html import escape
from pathlib import Path
from statistics import median
from html.parser import HTMLParser
from zoneinfo import ZoneInfo
from urllib.parse import urlencode
from urllib.request import Request, urlopen

import openpyxl
import altair as alt
import pandas as pd
import streamlit as st


st.set_page_config(page_title="Northern salmon conditions", page_icon="🎣", layout="wide")
st.markdown("""<style>
    :root { --river-ink: #17324a; --river-blue: #126b89; }
    [data-testid="stAppViewContainer"] {
        background: linear-gradient(180deg, #edf6f8 0, #f7fafb 310px, #ffffff 620px);
        color: var(--river-ink);
    }
    /* Keep Streamlit's Share/settings controls, but match their header to the page. */
    header[data-testid="stHeader"], header.stAppHeader {
        background: #edf6f8 !important;
    }
    [data-testid="stSidebar"] { background: #eef4f6; }
    [data-testid="stSidebar"] [data-testid="stWidgetLabel"] { font-weight: 600; }
    /* Leave room for the fixed Streamlit toolbar so the first heading is visible. */
    [data-testid="stMainBlockContainer"] { max-width: 1260px; padding-top: 4.5rem; }
    h1, h2, h3 { color: var(--river-ink); letter-spacing: -.025em; }
    h1 { font-size: clamp(2rem, 3vw, 3rem) !important; }
    [data-testid="stMetric"] {
        background: #fff; border: 1px solid #dce9ed; border-radius: 16px;
        padding: 1rem 1.15rem; box-shadow: 0 6px 18px rgba(21, 64, 82, .045);
        min-height: 116px;
    }
    [data-testid="stMetricLabel"] { color: #587182; font-weight: 600; }
    [data-testid="stMetricValue"] { color: #103d57; font-size: clamp(1.35rem, 2vw, 1.9rem); }
    [data-testid="stAlert"] { border-radius: 12px; }
    [data-testid="stExpander"] { border-radius: 12px; }
    .river-kicker { color: var(--river-blue); font-size: .78rem; font-weight: 750;
        letter-spacing: .12em; text-transform: uppercase; margin: 0 0 .4rem; }
    .river-note { color: #567183; margin: -.4rem 0 1.25rem; }
    .river-hero {
        background-color: #244e61; background-size: cover; background-position: center 50%;
        min-height: 250px; border-radius: 20px; padding: 2rem 2.4rem;
        display: flex; flex-direction: column; justify-content: flex-end;
        box-shadow: 0 14px 30px rgba(18, 54, 72, .14);
        margin-bottom: 1rem;
    }
    .river-hero h1 { color: #fff !important; margin: .25rem 0 .45rem;
        text-shadow: 0 2px 12px rgba(0, 0, 0, .4); }
    .river-hero .river-kicker { color: #e5f8fa; text-shadow: 0 1px 6px #122d3b; }
    .river-hero p { color: #f0f9fb; margin: 0; text-shadow: 0 1px 6px #122d3b; }
    .river-hero small { color: #f0f9fb; margin-top: .8rem; font-size: .74rem; }
    @media (max-width: 768px) {
        [data-testid="stMainBlockContainer"] {
            padding: 3.75rem .8rem 2rem !important;
        }
        [data-testid="stSidebar"] { max-width: 320px; }
        [data-testid="stHorizontalBlock"] {
            flex-wrap: wrap !important; gap: .65rem !important;
        }
        [data-testid="stHorizontalBlock"] > [data-testid="column"] {
            flex: 1 1 calc(50% - .65rem) !important;
            min-width: calc(50% - .65rem) !important;
        }
        [data-testid="stMetric"] {
            min-height: 104px; padding: .75rem .8rem;
            border-radius: 13px;
        }
        [data-testid="stMetricLabel"] { font-size: .78rem; }
        [data-testid="stMetricValue"] { font-size: 1.35rem !important; }
        .river-hero {
            min-height: 178px; padding: 1.25rem; border-radius: 14px;
            background-position: 58% center;
        }
        .river-hero h1 { font-size: 1.65rem !important; line-height: 1.08; }
        .river-hero p { font-size: .9rem; }
        .river-hero small { font-size: .66rem; }
        .river-kicker { font-size: .68rem; }
        h2 { font-size: 1.45rem !important; }
        h3 { font-size: 1.2rem !important; }
        [data-testid="stDataFrame"] { overflow-x: auto; }
        .vega-embed { overflow-x: auto; }
        .vega-embed details { display: none; }
    }
    @media (max-width: 370px) {
        [data-testid="stHorizontalBlock"] > [data-testid="column"] {
            flex-basis: 100% !important; min-width: 100% !important;
        }
        .river-hero { min-height: 165px; }
    }
</style>""", unsafe_allow_html=True)

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
WEATHER_FORECAST_API = "https://api.weatherapi.com/v1/forecast.json"
WEATHER_HISTORY_API = "https://api.weatherapi.com/v1/history.json"
EA_TIDE_API = "https://environment.data.gov.uk/flood-monitoring"
OPEN_METEO_MARINE_API = "https://marine-api.open-meteo.com/v1/marine"
FISHPAL_BURNFOOT = "https://www.fishpal.com/scotland/borderesk/burnfoot/"
FISHPAL_BORDER_ESK_DAILY = "https://www.fishpal.com/scotland/borderesk/catches.html"
FISHPAL_TWEED_DAILY = "https://www.fishpal.com/scotland/tweed/catches.html"
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
    "Tweed": ("Tweed", "Kelso, UK"),
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
RIVER_LOCATIONS = {"Wear": ("Durham, UK", "Chester-le-Street, UK")}
# Approximate river-mouth coordinates used to locate the nearest EA live tide
# gauge. These are reference points, not readings at an inland fishing beat.
TIDE_REFERENCES = {
    "Border Esk": ("Solway Firth near the Border Esk mouth", 54.983, -3.020),
    "Yorkshire Esk": ("Whitby Harbour", 54.490, -0.614),
    "Cumbrian Esk": ("Ravenglass estuary", 54.353, -3.408),
    "Tweed": ("Berwick-upon-Tweed / River Tweed mouth", 55.770, -1.985),
    "Tyne": ("Tynemouth / River Tyne mouth", 55.010, -1.421),
    "Wear": ("Sunderland / River Wear mouth", 54.916, -1.355),
    "Coquet": ("Amble Harbour / River Coquet mouth", 55.333, -1.575),
    "Tees": ("Teesmouth", 54.634, -1.133),
    "Aln": ("Alnmouth", 55.387, -1.613),
    "Eden": ("Solway Firth near the River Eden mouth", 54.976, -3.008),
    "Lune": ("Glasson Dock / River Lune estuary", 53.997, -2.850),
    "Ribble": ("Lytham / Ribble estuary", 53.727, -2.978),
    "Derwent": ("Workington / River Derwent mouth", 54.650, -3.572),
    "Ehen": ("Sellafield coast / River Ehen mouth", 54.414, -3.507),
    "Irt": ("Ravenglass estuary", 54.353, -3.408),
    "Kent": ("Arnside / Kent estuary", 54.201, -2.836),
    "Leven": ("Greenodd / Leven estuary", 54.236, -3.060),
}
# Verified beats can be listed here; imported catch reports also contribute
# beat names for their own river. Do not infer beat totals from river data.
KNOWN_BEATS = {
    "Border Esk": ("Burnfoot",),
    # The Tweed menu is supplemented from the named beats in FishPal's live
    # current-week table, so it can follow the report without a code release.
    "Tweed": (),
    "Tyne": (
        "Bywell", "Styford", "Warden Fishing", "Dilston",
        "Haughton Castle", "Chipchase Castle", "Chesters",
    ),
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

# Latest season-to-date totals explicitly confirmed by the fishery. Grilse are
# already included in the salmon figure and must never be added again. Keep
# this override dated so the app cannot present an old total as live.
BURNFOOT_VERIFIED_SEASON = {
    2026: {
        "salmon_including_grilse": 192,
        "reported_date": dt.date(2026, 9, 13),
        "source_label": "Burnfoot Facebook update",
        "source_url": "https://www.facebook.com/BorderEskFishing?locale=en_GB",
    }
}

# Compact, informational tackle guide for the Burnfoot/Border Esk view. The
# Mepps 00/No. 1 note is published in FishPal's Border Esk tackle guide. The
# remaining entries are deliberately described as common starting points, not
# as proven Burnfoot catch statistics or forecasts.
BURNFOOT_METHOD_GUIDE = {
    "Fly": {
        "Ally's Shrimp": {
            "conditions": "A versatile salmon starting pattern; try a smaller dressing in low, clear water.",
            "presentation": "Fish it across and down, adjusting line density and size to the pool and flow.",
            "evidence": "Common UK salmon pattern; confirm the current Burnfoot preference locally.",
        },
        "Cascade": {
            "conditions": "A general salmon and grilse option in a range of flows.",
            "presentation": "Use a size and line that keep the fly fishing at a controlled depth and pace.",
            "evidence": "Common UK salmon pattern; not a verified Burnfoot catch result.",
        },
        "Stoat's Tail": {
            "conditions": "A dark pattern often considered for lower light and sea-trout fishing.",
            "presentation": "Try it through likely lies without repeatedly covering resting fish.",
            "evidence": "Common salmon/sea-trout pattern; not a verified Burnfoot catch result.",
        },
        "Willie Gunn": {
            "conditions": "Often used as a visible salmon pattern when the river carries more colour or flow.",
            "presentation": "Match the dressing weight and line to the depth; avoid fishing below the fish.",
            "evidence": "Common UK salmon pattern; confirm the current Burnfoot preference locally.",
        },
        "Sunray Shadow": {
            "conditions": "A mobile fly commonly tried in low light or when a stronger silhouette is useful.",
            "presentation": "Vary the retrieve and angle, provided the beat's current rules allow it.",
            "evidence": "Common salmon/sea-trout pattern; not a verified Burnfoot catch result.",
        },
    },
    "Spinner": {
        "Mepps 00": {
            "conditions": "FishPal's Border Esk guide specifically mentions this tiny spinner for low water, rapids and streamy runs.",
            "presentation": "Use a light line and a quiet, accurate cast; only spin where the beat permits it.",
            "evidence": "Border Esk-specific guidance published by FishPal.",
        },
        "Mepps No. 1": {
            "conditions": "FishPal's Border Esk guide specifically mentions this small spinner for low water, rapids and streamy runs.",
            "presentation": "Keep it working through the current with minimal disturbance; only spin where permitted.",
            "evidence": "Border Esk-specific guidance published by FishPal.",
        },
        "Mepps No. 2": {
            "conditions": "A slightly larger common option when more presence is wanted than a 00 or No. 1.",
            "presentation": "Control its depth and speed carefully and avoid snag-prone or resting areas.",
            "evidence": "Common spinner option; not verified as Burnfoot-specific guidance.",
        },
        "Flying C": {
            "conditions": "A common salmon spinner considered when extra weight or a stronger flow requires it.",
            "presentation": "Choose the smallest practical weight and retrieve fast enough to keep the blade working.",
            "evidence": "Common salmon spinner; not verified as Burnfoot-specific guidance.",
        },
        "Toby-style spoon": {
            "conditions": "A common choice for covering broader or deeper water where spinning is allowed.",
            "presentation": "Vary casting angle and retrieve while keeping the lure clear of the riverbed.",
            "evidence": "Common salmon/sea-trout lure; not verified as Burnfoot-specific guidance.",
        },
        "Other spinner / local advice": {
            "conditions": "Use this for another spinner recommended by Burnfoot or an experienced local angler.",
            "presentation": "Record the exact model, colour and blade, then confirm that it complies with current beat rules.",
            "evidence": "User-entered option; it is not treated as verified Burnfoot guidance by the app.",
        },
    },
    "Worm (date-restricted)": {
        "Worm fishing": {
            "conditions": "A Burnfoot method only during the beat's permitted worm-fishing dates.",
            "presentation": "Ask the fishery which pools, tackle and hook arrangement are permitted before starting.",
            "evidence": "Burnfoot method confirmed to the app owner, but exact permitted dates have not yet been verified for the app.",
            "date_restricted": True,
        },
    },
    "Prawn (date-restricted)": {
        "Prawn fishing": {
            "conditions": "A Burnfoot method only during the beat's permitted prawn-fishing dates.",
            "presentation": "Confirm the permitted tackle, hook arrangement and areas with the fishery before fishing.",
            "evidence": "Burnfoot method confirmed to the app owner, but exact permitted dates have not yet been verified for the app.",
            "date_restricted": True,
        },
    },
}


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


@st.cache_data(ttl=45 * 60, show_spinner=False)
def nearby_forecast(key: str, location: str) -> list[dict]:
    """Get three future days where supported, falling back to the free tier.

    WeatherAPI counts today in its days parameter. Suppress provider errors so
    responses (which can contain request details) never disclose the API key.
    """
    for forecast_days in (4, 3):
        try:
            payload = get_json(WEATHER_FORECAST_API + "?" + urlencode({
                "key": key, "q": location, "days": forecast_days,
                "aqi": "no", "alerts": "no",
            }), timeout=12)
            if "error" not in payload:
                return payload.get("forecast", {}).get("forecastday", [])
        except Exception:
            pass
    return []


def distance_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Great-circle distance used only to rank nearby monitoring stations."""
    radius = 6371.0
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    d_phi = math.radians(lat2 - lat1)
    d_lon = math.radians(lon2 - lon1)
    part = (math.sin(d_phi / 2) ** 2
            + math.cos(phi1) * math.cos(phi2) * math.sin(d_lon / 2) ** 2)
    return radius * 2 * math.atan2(math.sqrt(part), math.sqrt(1 - part))


def object_list(value: object) -> list[dict]:
    if isinstance(value, dict):
        return [value]
    if isinstance(value, list):
        return [item for item in value if isinstance(item, dict)]
    return []


@st.cache_data(ttl=15 * 60, show_spinner=False)
def live_tide_observations(latitude: float, longitude: float,
                           preferred_search: str = "") -> dict:
    """Return the closest usable EA tidal/estuary gauge and recent readings."""
    candidates = []
    if preferred_search:
        try:
            candidates.extend(object_list(get_json(
                GAUGE_API + "?" + urlencode({
                    "search": preferred_search, "_view": "full", "_limit": 50,
                }), timeout=18).get("items")))
        except Exception:
            pass
    candidates.extend(object_list(get_json(
        GAUGE_API + "?" + urlencode({
            "type": "TideGauge", "unitName": "mAOD",
            "lat": f"{latitude:.4f}", "long": f"{longitude:.4f}",
            "dist": 150, "_view": "full", "_limit": 100,
        }), timeout=20).get("items")))

    unique = {}
    for station in candidates:
        station_id = str(station.get("notation") or station.get("stationReference") or "")
        if station_id:
            unique.setdefault(station_id, station)

    def station_rank(station: dict) -> tuple[int, float]:
        label = str(station.get("label") or "").lower()
        preferred = 0 if preferred_search and preferred_search.lower() in label else 1
        try:
            distance = distance_km(latitude, longitude,
                                   float(station["lat"]), float(station["long"]))
        except (KeyError, TypeError, ValueError):
            distance = 10_000.0
        # Do not select an identically named inland station from another region.
        if preferred == 0 and distance > 80:
            preferred = 2
        return preferred, distance

    for station in sorted(unique.values(), key=station_rank)[:12]:
        station_id = str(station.get("notation") or station.get("stationReference") or "")
        measures = object_list(station.get("measures"))
        if not measures and station_id and all(c.isalnum() or c in "_-" for c in station_id):
            try:
                measures = object_list(get_json(
                    f"{GAUGE_API}/{station_id}/measures", timeout=12).get("items"))
            except Exception:
                continue
        def measure_rank(measure: dict) -> tuple[int, int, float]:
            try:
                period_gap = abs(float(measure.get("period") or 900) - 900)
            except (TypeError, ValueError):
                period_gap = 10_000.0
            return (
                0 if "tidal" in str(measure.get("qualifier") or "").lower() else 1,
                0 if str(measure.get("unitName") or "").lower() == "maod" else 1,
                period_gap,
            )

        measures.sort(key=measure_rank)
        for measure in measures:
            qualifier = str(measure.get("qualifier") or "").lower()
            is_preferred_station = bool(preferred_search) and (
                preferred_search.lower() in str(station.get("label") or "").lower()
            )
            if "tidal" not in qualifier and not is_preferred_station:
                continue
            measure_id = str(measure.get("notation") or "")
            if not measure_id or not all(c.isalnum() or c in "_-" for c in measure_id):
                continue
            since = (dt.datetime.now(dt.timezone.utc) - dt.timedelta(hours=30))
            try:
                payload = get_json(
                    f"{EA_TIDE_API}/id/measures/{measure_id}/readings?" + urlencode({
                        "since": since.isoformat(timespec="seconds"),
                        "_sorted": "", "_limit": 250,
                    }), timeout=18)
            except Exception:
                continue
            observations = []
            for reading in object_list(payload.get("items")):
                try:
                    timestamp = dt.datetime.fromisoformat(
                        str(reading["dateTime"]).replace("Z", "+00:00"))
                    value = float(reading["value"])
                    if timestamp.tzinfo and math.isfinite(value):
                        observations.append((timestamp, value))
                except (KeyError, TypeError, ValueError):
                    continue
            observations.sort(key=lambda item: item[0])
            if not observations:
                continue
            latest_time, latest_value = observations[-1]
            prior = min(observations[:-1] or observations,
                        key=lambda item: abs((item[0] - latest_time
                                              + dt.timedelta(hours=1)).total_seconds()))
            change = latest_value - prior[1]
            trend = "Rising" if change > 0.03 else "Falling" if change < -0.03 else "Steady"
            return {
                "station": station.get("label") or station_id,
                "value": latest_value,
                "unit": measure.get("unitName") or "mAOD",
                "time": latest_time,
                "trend": trend,
                "change": change,
                "distance_km": station_rank(station)[1],
                "observations": observations,
            }
    return {}


@st.cache_data(ttl=30 * 60, show_spinner=False)
def modelled_tide_outlook(latitude: float, longitude: float,
                          forecast_days: int = 4) -> dict:
    """Return hourly modelled sea level and derived high/low turning points."""
    payload = get_json(OPEN_METEO_MARINE_API + "?" + urlencode({
        "latitude": f"{latitude:.4f}",
        "longitude": f"{longitude:.4f}",
        "hourly": "sea_level_height_msl",
        "timezone": "Europe/London",
        "forecast_days": max(1, min(forecast_days, 8)),
        "cell_selection": "sea",
    }), timeout=20)
    hourly = payload.get("hourly", {})
    raw_times = hourly.get("time", [])
    raw_values = hourly.get("sea_level_height_msl", [])
    series = []
    for raw_time, raw_value in zip(raw_times, raw_values):
        try:
            timestamp = dt.datetime.fromisoformat(str(raw_time))
            if timestamp.tzinfo is None:
                timestamp = timestamp.replace(tzinfo=UK_TIME)
            value = float(raw_value)
            if math.isfinite(value):
                series.append((timestamp, value))
        except (TypeError, ValueError):
            continue
    if len(series) < 3:
        return {}

    events = []
    for index in range(1, len(series) - 1):
        previous_value = series[index - 1][1]
        timestamp, value = series[index]
        next_value = series[index + 1][1]
        if value > previous_value and value >= next_value:
            events.append((timestamp, "High", value))
        elif value < previous_value and value <= next_value:
            events.append((timestamp, "Low", value))

    now = dt.datetime.now(UK_TIME)
    nearest_index = min(range(len(series)),
                        key=lambda i: abs((series[i][0] - now).total_seconds()))
    current_time, current_value = series[nearest_index]
    earlier_value = series[max(0, nearest_index - 1)][1]
    change = current_value - earlier_value
    trend = "Rising" if change > 0.02 else "Falling" if change < -0.02 else "Steady"
    return {
        "series": series,
        "events": events,
        "current_time": current_time,
        "current_value": current_value,
        "trend": trend,
        "latitude": payload.get("latitude"),
        "longitude": payload.get("longitude"),
    }


def render_modelled_tide_outlook(tide_name: str, latitude: float,
                                  longitude: float) -> bool:
    """Render a no-key tide-model fallback; return True when data are shown."""
    try:
        outlook = modelled_tide_outlook(latitude, longitude)
    except Exception:
        return False
    if not outlook:
        return False

    now = dt.datetime.now(UK_TIME)
    future_events = [event for event in outlook["events"] if event[0] >= now]
    next_high = next((event for event in future_events if event[1] == "High"), None)
    next_low = next((event for event in future_events if event[1] == "Low"), None)
    current_col, movement_col, high_col, low_col = st.columns(4)
    current_col.metric("Modelled sea level now",
                       f"{outlook['current_value']:.2f} m MSL")
    movement_col.metric("Tide movement", outlook["trend"])
    high_col.metric("Next high tide",
                    next_high[0].strftime("%a %H:%M") if next_high else "—",
                    f"{next_high[2]:.2f} m MSL" if next_high else None)
    low_col.metric("Next low tide",
                   next_low[0].strftime("%a %H:%M") if next_low else "—",
                   f"{next_low[2]:.2f} m MSL" if next_low else None)

    today = now.date()
    table_rows = []
    for day_offset in range(3):
        day = today + dt.timedelta(days=day_offset)
        day_events = [event for event in outlook["events"] if event[0].date() == day]
        highs = [f"{event[0]:%H:%M} ({event[2]:.2f} m)"
                 for event in day_events if event[1] == "High"]
        lows = [f"{event[0]:%H:%M} ({event[2]:.2f} m)"
                for event in day_events if event[1] == "Low"]
        table_rows.append({"Date": day.strftime("%a %d %b"),
                           "High tides": " · ".join(highs) or "—",
                           "Low tides": " · ".join(lows) or "—"})
    st.dataframe(pd.DataFrame(table_rows), hide_index=True, use_container_width=True)

    st.caption(
        f"Modelled tide near {tide_name}, not at Burnfoot. Source: Open-Meteo Marine "
        "API / Météo-France SMOC tides, approximately 8 km model resolution. Heights "
        "are relative to global mean sea level (MSL), not chart datum. Free endpoint "
        "is for this private non-commercial test; commercial launch needs an "
        "appropriate Open-Meteo plan. Not for navigation or wading-safety decisions."
    )
    return True


def render_tide_panel(river: str, beat: str) -> None:
    """Show observed tide data in a consistent, prominent position."""
    burnfoot_tides = river == "Border Esk" and beat in {"All beats", "Burnfoot"}
    tide_heading = ("Live tidal level for Burnfoot" if burnfoot_tides
                    else "Live tide near the river mouth")
    st.markdown(f"#### 🌊 {tide_heading}")
    tide_name, tide_lat, tide_lon = TIDE_REFERENCES[river]
    if burnfoot_tides:
        st.caption(
            "Observed tidal level from the closest suitable government gauge to "
            f"{tide_name}. Burnfoot is upstream, so this is supporting information "
            "rather than a measurement taken inside the beat."
        )
    else:
        st.caption(
            "Observed tidal level from the closest suitable government gauge to "
            f"{tide_name}; this is not a measurement at the selected beat."
        )

    try:
        preferred_station = "Metal Bridge" if river == "Border Esk" else ""
        tide = live_tide_observations(tide_lat, tide_lon, preferred_station)
    except Exception:
        tide = {}

    if not tide:
        st.caption("No suitable recent Environment Agency tide-gauge reading was found; "
                   "using a modelled Solway tide outlook instead.")
        if render_modelled_tide_outlook(tide_name, tide_lat, tide_lon):
            return
        st.info("Both the government observation feed and the modelled tide feed are "
                "temporarily unavailable.")
        if st.button("Retry tide feed", key=f"retry_tide_{river}_{beat}"):
            live_tide_observations.clear()
            modelled_tide_outlook.clear()
            st.rerun()
        return

    cutoff = dt.datetime.now(dt.timezone.utc) - dt.timedelta(hours=24)
    recent = [(timestamp, value) for timestamp, value in tide["observations"]
              if timestamp >= cutoff]
    recent_values = [value for _, value in recent]
    observed_high = max(recent_values) if recent_values else tide["value"]
    observed_low = min(recent_values) if recent_values else tide["value"]

    tide_level_col, tide_trend_col, tide_high_col, tide_low_col = st.columns(4)
    tide_level_col.metric("Latest tidal level", f"{tide['value']:.2f} {tide['unit']}")
    tide_trend_col.metric("Tide movement", tide["trend"],
                          f"{tide['change']:+.2f} m in about 1 hour")
    tide_high_col.metric("Observed 24h high", f"{observed_high:.2f} {tide['unit']}")
    tide_low_col.metric("Observed 24h low", f"{observed_low:.2f} {tide['unit']}")

    distance_text = (f" · approximately {tide['distance_km']:.0f} km from the "
                     "river-mouth reference"
                     if math.isfinite(tide["distance_km"]) else "")
    reading_time = tide["time"].astimezone(UK_TIME).strftime("%H:%M on %a %d %b %Y")
    st.caption(
        f"Gauge: {tide['station']}{distance_text} · latest reading {reading_time} "
        "(local time). Source: Environment Agency real-time tide gauge API (Beta)."
    )


def render_method_guide(river: str, beat: str) -> None:
    """Show a compact tackle selector where some local guidance is available."""
    if river != "Border Esk" or beat not in {"All beats", "Burnfoot"}:
        return

    with st.expander("🎣 Burnfoot fishing method guide", expanded=False):
        st.caption(
            "Choose a method and pattern for a practical starting point. This is "
            "tackle guidance, not a prediction that fish will be caught."
        )
        method_col, choice_col = st.columns(2)
        method = method_col.selectbox(
            "Method",
            list(BURNFOOT_METHOD_GUIDE),
            key=f"method_family_{river}_{beat}",
        )
        choices = list(BURNFOOT_METHOD_GUIDE[method])
        if len(choices) > 1:
            choice = choice_col.selectbox(
                "Pattern or lure",
                choices,
                key=f"method_choice_{river}_{beat}_{method}",
            )
        else:
            choice = choices[0]
            choice_col.markdown("**Selected method**")
            choice_col.write(choice)
        guide = BURNFOOT_METHOD_GUIDE[method][choice]
        if method == "Spinner" and choice == "Flying C":
            colour_col, blade_col = st.columns(2)
            flying_c_colour = colour_col.selectbox(
                "Flying C colour",
                ["Red", "Black", "Black & Yellow"],
                key=f"flying_c_colour_{river}_{beat}",
            )
            flying_c_blade = blade_col.selectbox(
                "Blade finish",
                ["Copper", "Silver"],
                key=f"flying_c_blade_{river}_{beat}",
            )
            st.success(f"Selected spinner: {flying_c_colour} Flying C with a {flying_c_blade.lower()} blade")
        elif method == "Spinner" and choice == "Other spinner / local advice":
            other_spinner = st.text_input(
                "Spinner name, colour and blade",
                placeholder="For example: model, size, colour and blade finish",
                key=f"other_spinner_{river}_{beat}",
            )
            if other_spinner.strip():
                st.success(f"Selected spinner: {other_spinner.strip()}")
        conditions_col, presentation_col = st.columns(2)
        conditions_col.markdown("**When it may suit**")
        conditions_col.write(guide["conditions"])
        presentation_col.markdown("**How to approach it**")
        presentation_col.write(guide["presentation"])
        st.caption(f"Evidence note: {guide['evidence']}")
        if guide.get("date_restricted"):
            st.error(
                "Date-restricted method: do not use this method until Burnfoot "
                "has confirmed that it is permitted on the selected fishing date."
            )
        st.markdown(
            "[FishPal Border Esk tackle and flies]"
            "(https://www.fishpal.com/scotland/borderesk/tackleandflies.html)"
        )
        st.warning(
            "Check Burnfoot's current permitted methods, hook rules, seasonal "
            "restrictions and catch-and-release requirements before fishing. "
            "Conditions and fishery rules can change."
        )


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
def weather_daily_history(key: str, location: str, days: tuple[dt.date, ...]) -> tuple[dict, dict, bool]:
    result, pressures = {}, {}
    for day in days:
        if day == dt.datetime.now(UK_TIME).date():
            continue  # Today's current observation is labelled separately.
        try:
            payload = get_json(WEATHER_HISTORY_API + "?" + urlencode({
                "key": key, "q": location, "dt": day.isoformat(),
            }), timeout=12)
            forecast = payload["forecast"]["forecastday"][0]
            summary = forecast["day"]
            result[day] = str(summary["condition"]["text"])
            hourly = []
            for hour in forecast.get("hour", []):
                try:
                    value = float(hour["pressure_mb"])
                    if 800 <= value <= 1100:
                        hourly.append(value)
                except (KeyError, TypeError, ValueError):
                    continue
            if len(hourly) >= 8:
                pressures[day] = round(sum(hourly) / len(hourly), 1)
        except Exception:
            # A missing history subscription should never expose the API key in an error.
            return result, pressures, False
    return result, pressures, True


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


def weather_group(condition: str) -> str | None:
    """Broad descriptive groups, for comparing local observations only."""
    words = str(condition or "").lower()
    if not words or words == "not available":
        return None
    if any(term in words for term in ("thunder", "lightning")):
        return "storm"
    if any(term in words for term in ("snow", "sleet", "blizzard", "ice")):
        return "wintery"
    if any(term in words for term in ("rain", "drizzle", "shower")):
        return "wet"
    if any(term in words for term in ("fog", "mist", "haze")):
        return "misty"
    if any(term in words for term in ("cloud", "overcast")):
        return "cloudy"
    if any(term in words for term in ("sun", "clear")):
        return "clear"
    return None


def finite_number(value: object) -> float | None:
    try:
        number = float(value)
        return number if math.isfinite(number) else None
    except (TypeError, ValueError):
        return None


def catch_condition_light(rows: list[dict], today: dt.date,
                          current_level: object, current_weather: str,
                          current_pressure: object) -> tuple[str | None, str]:
    """Experimental match to completed catch days, not a catch/safety forecast."""
    level = finite_number(current_level)
    pressure = finite_number(current_pressure)
    group = weather_group(current_weather)
    if level is None or pressure is None or group is None:
        return None, "A fresh gauge level, current weather and air pressure are all needed."
    observed = []
    for row in rows:
        if row["Date"] >= today:
            continue
        salmon = finite_number(row["Reported salmon"])
        trout = finite_number(row["Reported sea trout"])
        past_level = finite_number(row["Water level (m)"])
        past_pressure = finite_number(row["Pressure (hPa)"])
        past_weather = weather_group(row["Weather"])
        if (salmon is None or trout is None or past_level is None
                or past_pressure is None or past_weather is None):
            continue
        observed.append((row["Date"], salmon + trout, past_level,
                         past_pressure, past_weather))
    positive = [sample for sample in observed if sample[1] > 0]
    if len(observed) < 4 or len(positive) < 2:
        return None, (f"Only {len(observed)} complete prior catch/level/weather/pressure "
                      f"days ({len(positive)} with fish). Need at least four complete "
                      "days and two catch days for this beat.")

    recent = sorted(observed, key=lambda sample: sample[0])[-3:]
    catch_points = min(2, sum(sample[1] > 0 for sample in recent))
    good_levels = [sample[2] for sample in positive]
    good_pressures = [sample[3] for sample in positive]
    level_gap = (min(good_levels) - level if level < min(good_levels)
                 else level - max(good_levels) if level > max(good_levels) else 0)
    level_points = 2 if level_gap == 0 else 1 if level_gap <= 0.10 else 0
    pressure_gap = abs(pressure - median(good_pressures))
    pressure_points = 2 if pressure_gap <= 4 else 1 if pressure_gap <= 8 else 0
    groups = Counter(sample[4] for sample in positive)
    weather_points = 2 if group == groups.most_common(1)[0][0] else 1 if group in groups else 0
    points = catch_points + level_points + pressure_points + weather_points
    label = "Excellent" if points >= 7 else "Moderate" if points >= 4 else "Poor"
    note = (f"Experimental match to {len(observed)} recent complete days for this beat "
            f"({len(positive)} with fish). Catch trend {catch_points}/2 · "
            f"gauge level {level_points}/2 · weather {weather_points}/2 · "
            f"pressure {pressure_points}/2. This is not a tested prediction or a safety rating.")
    return label, note


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


class _FishPalRiverWeekParser(HTMLParser):
    """Read current-week river totals and named-beat counts from FishPal."""

    weekdays = set(WEEKDAY_NAMES)

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.current_week = False
        self.day = None
        self.row = None
        self.cell = None
        self.daily_totals = {}
        self.daily_beats = {}

    def handle_starttag(self, tag, attrs):
        if tag == "tr":
            self.row = []
        elif tag in {"td", "th"} and self.row is not None:
            self.cell = []

    def handle_data(self, data):
        text = " ".join(data.split())
        lower = text.lower()
        if "for the current week" in lower:
            self.current_week = True
        if "week so far" in lower or "last week" in lower:
            self.current_week = False
        if self.current_week and lower in self.weekdays:
            self.day = lower
        if self.cell is not None:
            self.cell.append(data)

    def handle_endtag(self, tag):
        if tag in {"td", "th"} and self.cell is not None:
            self.row.append(" ".join(" ".join(self.cell).split()))
            self.cell = None
        elif tag == "tr" and self.row is not None:
            if self.current_week and self.day:
                cells = [value for value in self.row
                         if value.strip().lower() not in self.weekdays]
                if len(cells) >= 2:
                    species_cells = cells[-2:]
                    for species, value in zip(("salmon", "sea_trout"), species_cells):
                        total = re.search(r"\bTotal\s*:\s*([0-9,]+)\b", value, re.I)
                        if total:
                            self.daily_totals.setdefault(self.day, {})[species] = int(
                                total.group(1).replace(",", "")
                            )
                        before_total = re.split(r"\bTotal\s*:", value, maxsplit=1,
                                                flags=re.I)[0]
                        for match in re.finditer(
                            r"([A-Za-z][A-Za-z0-9 '&()./]*?)\s*[-–]\s*([0-9,]+)(?=\s|$)",
                            before_total,
                        ):
                            beat_name = " ".join(match.group(1).split()).strip()
                            if not beat_name:
                                continue
                            count_value = int(match.group(2).replace(",", ""))
                            day_beats = self.daily_beats.setdefault(self.day, {})
                            beat_counts = day_beats.setdefault(beat_name, {})
                            if species in beat_counts:
                                raise ValueError("Duplicate FishPal beat catch entry")
                            beat_counts[species] = count_value
            self.row = None


def parse_fishpal_river_week(html: str, today: dt.date) -> dict:
    parser = _FishPalRiverWeekParser()
    parser.feed(html)
    if not parser.daily_totals:
        raise ValueError("FishPal current-week river table could not be read")
    week_start = today - dt.timedelta(days=today.weekday())
    daily_totals = {}
    daily_beats = {}
    beat_names = set()
    for day_name, totals in parser.daily_totals.items():
        day = week_start + dt.timedelta(days=WEEKDAY_NAMES.index(day_name))
        if day > today:
            continue
        daily_totals[day] = {species: int(totals.get(species, 0))
                             for species in ("salmon", "sea_trout")}
        beat_rows = parser.daily_beats.get(day_name, {})
        daily_beats[day] = {}
        for beat_name, counts in beat_rows.items():
            beat_names.add(beat_name)
            daily_beats[day][beat_name] = {
                species: int(counts.get(species, 0))
                for species in ("salmon", "sea_trout")
            }
    return {"daily_totals": daily_totals,
            "daily_beats": daily_beats,
            "beat_names": sorted(beat_names, key=str.casefold)}


@st.cache_data(ttl=60 * 60, show_spinner=False)
def tweed_daily_catches(today: dt.date) -> tuple[dict, str]:
    html = get_bytes(FISHPAL_TWEED_DAILY, timeout=20).decode("utf-8", errors="replace")
    fetched_at = dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    return parse_fishpal_river_week(html, today), fetched_at


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


with st.sidebar:
    st.header("Explore")
    view = st.radio("View", ["Last 7 days", "Catch history and reports"], horizontal=True)
    river = st.selectbox("River", list(RIVERS), index=0)
    beat_slot = st.container()  # Filled after the catch CSV has been checked.
    official_name, default_weather = RIVERS[river]
    selected_year = (st.selectbox("Official catch season", list(range(2024, 2007, -1)))
                     if view == "Catch history and reports" else 2024)
    with st.expander("Manage catch reports"):
        st.caption(f"{CURRENT_YEAR} reports you have permission to publish. "
                   "Uploads replace the saved CSV for this session; FishPal test figures "
                   "are not included in its totals.")
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
tweed_feed = {}
tweed_feed_retrieved = ""
tweed_feed_error = ""
if river == "Tweed":
    try:
        tweed_feed, tweed_feed_retrieved = tweed_daily_catches(
            dt.datetime.now(UK_TIME).date()
        )
    except Exception as exc:
        tweed_feed_error = str(exc)
with beat_slot:
    uploaded_beats = (set(reports.loc[reports["river"] == river, "beat"]) - {""}
                      if len(reports) else set())
    live_fishpal_beats = set(tweed_feed.get("beat_names", ()))
    beat_options = sorted(set(KNOWN_BEATS.get(river, ())) | uploaded_beats
                          | live_fishpal_beats,
                          key=str.casefold)
    beat = st.selectbox("Beat", ["All beats", *beat_options],
                        key=f"selected_beat_{river}")
    if not beat_options:
        st.caption("No named beats loaded for this river. Add their names to KNOWN_BEATS "
                   "in the .py file or add dated catches to catch_reports.csv.")
    st.caption("Catch reports are beat-specific; gauge and EA archive figures are river-wide.")
    if river == "Border Esk":
        with st.expander("About Border Esk beats"):
            st.caption("[Browse FishPal's Border Esk listings](https://www.fishpal.com/search/in/Border%20Esk) "
                       "for reference; they are not imported into this app.")
    elif river == "Tweed":
        if tweed_feed_error:
            st.caption("FishPal's Tweed beat list is temporarily unavailable: "
                       + tweed_feed_error)
        else:
            st.caption("Named beats are taken from FishPal's current-week Tweed "
                       "catch table and may change as reports are added.")

burnfoot_photo = Path(__file__).with_name("burnfoot_header.jpg")
illustrative_banner = Path(__file__).with_name("salmon_river_banner.png")
use_burnfoot_photo = (river == "Border Esk" and beat in {"All beats", "Burnfoot"}
                      and burnfoot_photo.is_file())
hero_path = burnfoot_photo if use_burnfoot_photo else illustrative_banner
if hero_path.is_file():
    try:
        # Only embed local project assets; never hotlink a third-party fishery image.
        if hero_path.stat().st_size > 6_000_000:
            raise ValueError(f"{hero_path.name} is larger than 6 MB")
        encoded_photo = base64.b64encode(hero_path.read_bytes()).decode("ascii")
        mime = "image/jpeg" if use_burnfoot_photo else "image/png"
        banner = (
            "linear-gradient(90deg, rgba(10,35,51,.88), "
            "rgba(10,35,51,.49) 64%, rgba(10,35,51,.27)), "
            f"url('data:{mime};base64,{encoded_photo}')"
        )
        description = ("Photograph: Burnfoot beat, Border Esk" if use_burnfoot_photo
                       else "Illustrative river scene · not a photograph of this beat")
        st.markdown(
            f'<section class="river-hero" style="background-image:{banner}">'
            '<span class="river-kicker">River & catch dashboard</span>'
            '<h1>Northern salmon &amp; sea trout</h1>'
            '<p>Current river conditions and dated catches</p>'
            f'<small>{description}</small>'
            '</section>', unsafe_allow_html=True,
        )
    except (OSError, ValueError) as exc:
        st.warning(f"Could not load the header image: {escape(str(exc))}")
        st.markdown('<p class="river-kicker">River & catch dashboard</p>', unsafe_allow_html=True)
        st.title("Northern salmon & sea trout")
else:
    st.markdown('<p class="river-kicker">River & catch dashboard</p>', unsafe_allow_html=True)
    st.title("Northern salmon & sea trout")
    st.caption("Current river conditions and dated catches · official catch history on a separate page")

with st.sidebar:
    st.divider()
    st.caption("Nearby conditions and river gauges are approximate, not readings at the beat.")
    if river in RIVER_LOCATIONS:
        chosen_location = st.selectbox("Location on River Wear", RIVER_LOCATIONS[river],
                                       key=f"river_location_{river}")
    else:
        chosen_location = default_weather
    default_gauge_search = "Canonbie" if river == "Border Esk" else "Esk" if "Esk" in river else river
    search_term = st.text_input("Search EA gauge stations",
                                value=default_gauge_search,
                                key=f"gauge_search_{river}")
    location = st.text_input("Weather location (approximate)", value=chosen_location,
                             key=(f"weather_location_{river}_{chosen_location}"
                                  if river in RIVER_LOCATIONS else f"weather_location_{river}"))

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
    with st.expander("Choose river gauge", expanded=not automatic_match):
        gauge_label = st.selectbox("River-level gauge", ["No gauge selected", *station_lookup],
                                   index=1 if automatic_match else 0,
                                   key=f"selected_gauge_v3_{river}_{location.strip().lower()}")
        st.caption("Check the station name: it is not a beat-level measurement.")
        if gauge_error:
            st.caption("EA station search currently unavailable: " + gauge_error)
        elif not automatic_match and river != "Border Esk":
            st.caption("No matching gauge was found automatically. Try a nearby station.")

st.markdown('<p class="river-kicker">Live snapshot</p>', unsafe_allow_html=True)
st.subheader(f"{river}" + (f"  ·  {beat}" if beat != "All beats" else "  ·  All beats"))
st.caption("A river-wide gauge and nearby weather observations · check each reading's timestamp")
level_col, weather_col, pressure_col, wind_col = st.columns(4)
current_level_m = None
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
            if (dt.timedelta(0) <= dt.datetime.now(dt.timezone.utc) - timestamp
                    <= dt.timedelta(hours=6)
                    and str(gauge.get("unit", "")).lower() in {"m", "metres", "metre"}):
                current_level_m = finite_number(gauge["value"])
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

# Reserve a prominent position beneath the live readings. The seven-day data
# needed for the rating is assembled later, then rendered back into this slot.
# This keeps the traffic light visible even when tide and forecast panels grow.
traffic_light_slot = st.empty() if view == "Last 7 days" else None

render_tide_panel(river, beat)
render_method_guide(river, beat)

if view == "Last 7 days":
    st.markdown("#### Weather over the next few days")
    st.caption(f"Near {location} · forecast for "
               + (f"{beat}, {river}" if beat != "All beats" else river)
               + "; not measured at the beat")
    upcoming = []
    if weather_key:
        for forecast_day in nearby_forecast(weather_key, location):
            try:
                forecast_date = dt.date.fromisoformat(forecast_day["date"])
                if forecast_date > dt.datetime.now(UK_TIME).date():
                    upcoming.append((forecast_date, forecast_day))
            except (KeyError, TypeError, ValueError):
                continue
    if upcoming:
        for column, (forecast_date, forecast_entry) in zip(
                st.columns(len(upcoming[:3])), upcoming[:3]):
            day_data = forecast_entry.get("day", {})
            description = day_data.get("condition", {}).get("text", "Unavailable")
            maximum = finite_number(day_data.get("maxtemp_c"))
            minimum = finite_number(day_data.get("mintemp_c"))
            rain = finite_number(day_data.get("daily_chance_of_rain"))
            wind = finite_number(day_data.get("maxwind_mph"))
            noon = next((hour for hour in forecast_entry.get("hour", [])
                         if str(hour.get("time", "")).endswith("12:00")), {})
            noon_wind = finite_number(noon.get("wind_mph"))
            noon_direction = str(noon.get("wind_dir") or "").strip()
            noon_pressure = finite_number(noon.get("pressure_mb"))
            high_low = (f"{maximum:g}°C / {minimum:g}°C" if maximum is not None
                        and minimum is not None else "Temperature unavailable")
            with column.container(border=True):
                st.markdown(f"#### {weather_icon(description)} {forecast_date:%a %d %b}")
                st.write(description)
                st.markdown(f"**{high_low}** · high / low")
                st.caption("Rain chance: " + (f"{rain:g}%" if rain is not None else "—")
                           + " · Max wind: "
                           + (f"{wind:g} mph" if wind is not None else "—"))
                if noon_wind is not None or noon_pressure is not None:
                    st.caption("At 12:00: "
                               + (f"{noon_direction} {noon_wind:g} mph" if noon_direction
                                  and noon_wind is not None else "wind unavailable")
                               + (f" · {noon_pressure:g} hPa" if noon_pressure is not None else ""))
        st.caption("Forecast: [WeatherAPI.com](https://www.weatherapi.com/) · "
                   "subject to change; rain chance and maximum wind are daily forecasts.")
    else:
        st.caption("Forecast unavailable for this location or API plan. "
                   "Current observations above can still be available.")

if weather_key:
    with st.expander("Important information about weather and river readings"):
        st.info("Weather observations and forecasts may differ at the beat and can change. "
                "Estuary tide observations are not beat-level readings. Do not rely on these "
                "data alone for wading, boating or other safety decisions. "
                "Check the relevant authorities when accuracy is critical.")

if view == "Last 7 days":
    today = dt.datetime.now(UK_TIME).date()
    days = tuple(today - dt.timedelta(days=offset) for offset in range(6, -1, -1))
    st.divider()
    st.markdown('<p class="river-kicker">Seven-day view</p>', unsafe_allow_html=True)
    st.subheader("Levels, catches & weather")
    st.caption(f"{days[0]:%d %b}–{days[-1]:%d %b %Y} · "
               + (f"{river} · {beat}" if beat != "All beats" else river))
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
    conditions, daily_pressures = {}, {}
    history_ok = False
    if weather_key:
        conditions, daily_pressures, history_ok = weather_daily_history(weather_key, location, days)
    if weather and weather.get("current", {}).get("condition", {}).get("text"):
        conditions[today] = "Now: " + weather["current"]["condition"]["text"]
        daily_pressures[today] = finite_number(weather["current"].get("pressure_mb"))

    recent_counts = {}
    fishpal_daily = {}
    fishpal_retrieved = ""
    if river == "Border Esk" and beat in {"All beats", "Burnfoot"}:
        season_status = BURNFOOT_VERIFIED_SEASON.get(CURRENT_YEAR)
        season_card, recent_card = st.columns(2)
        if season_status:
            season_card.metric(
                "Burnfoot salmon incl. grilse · season to date",
                f"{season_status['salmon_including_grilse']:,}",
            )
        else:
            season_card.metric("Burnfoot salmon · season to date", "Not verified")
        try:
            fishpal_week, _ = burnfoot_catches(CURRENT_YEAR)
            recent_counts = fishpal_week.get("last_seven", {})
            if "salmon" in recent_counts:
                recent_card.metric("Burnfoot salmon · last 7 days (FishPal)",
                                   recent_counts["salmon"])
            else:
                recent_card.metric("Burnfoot salmon · last 7 days", "Unavailable")
        except Exception:
            recent_card.metric("Burnfoot salmon · last 7 days", "Unavailable")
            st.warning("Burnfoot's seven-day FishPal total is temporarily unavailable.")
        if season_status:
            st.caption(
                f"Season total verified from [{season_status['source_label']}]"
                f"({season_status['source_url']}) on "
                f"{season_status['reported_date']:%d %b %Y}. The 192 total already "
                "includes grilse; the separate FishPal card covers only the last seven days."
            )
        try:
            fishpal_daily, fishpal_retrieved = burnfoot_daily_catches(today)
        except Exception:
            st.warning("FishPal's weekday catches are temporarily unavailable; "
                       "only dated CSV reports can appear as daily bars.")
    elif river == "Tweed":
        fishpal_retrieved = tweed_feed_retrieved
        if tweed_feed:
            if beat == "All beats":
                fishpal_daily = tweed_feed.get("daily_totals", {})
            else:
                fishpal_daily = {
                    day: tweed_feed.get("daily_beats", {}).get(day, {}).get(
                        beat, {"salmon": 0, "sea_trout": 0}
                    )
                    for day in tweed_feed.get("daily_totals", {})
                }
            tweed_salmon = sum(value.get("salmon", 0)
                               for value in fishpal_daily.values())
            tweed_trout = sum(value.get("sea_trout", 0)
                              for value in fishpal_daily.values())
            salmon_card, trout_card = st.columns(2)
            scope_name = "River Tweed" if beat == "All beats" else beat
            salmon_card.metric(f"{scope_name} salmon · week so far (FishPal)",
                               tweed_salmon)
            trout_card.metric(f"{scope_name} sea trout · week so far (FishPal)",
                              tweed_trout)
        else:
            st.warning("FishPal's Tweed current-week catches are temporarily unavailable; "
                       "only dated CSV reports can appear as daily bars."
                       + (" " + tweed_feed_error if tweed_feed_error else ""))

    daily_uploads = reports[reports["river"] == river].copy() if len(reports) else reports.copy()
    if beat != "All beats" and len(daily_uploads):
        daily_uploads = daily_uploads[daily_uploads["beat"] == beat]
    use_fishpal_daily = bool(fishpal_daily)
    catch_source = (("FishPal · Burnfoot only" if river == "Border Esk" else
                     "FishPal · Tweed river" if beat == "All beats" else
                     f"FishPal · Tweed · {beat}")
                    if use_fishpal_daily else "Permissioned dated reports")
    rows = []
    for day in days:
        matching = daily_uploads[daily_uploads["date"] == day] if len(daily_uploads) else daily_uploads
        daily = (fishpal_daily.get(day, {}) if use_fishpal_daily else
                 {"salmon": int(matching["salmon"].sum()),
                  "sea_trout": int(matching["sea_trout"].sum())} if len(matching) else {})
        day_weather = conditions.get(day)
        if day_weather is None and not use_fishpal_daily and len(matching):
            observations = [str(value).strip() for value in matching["weather"]
                            if str(value).strip()]
            if observations:
                day_weather = Counter(observations).most_common(1)[0][0]
        day_pressure = daily_pressures.get(day)
        if day_pressure is None and not use_fishpal_daily and len(matching):
            values = matching["pressure_hpa"].dropna()
            day_pressure = round(float(values.mean()), 1) if len(values) else None
        rows.append({"Date": day, "Day": day.strftime("%a %d %b"),
                     "Water level (m)": levels.get(day),
                     "Pressure (hPa)": day_pressure,
                     "Reported salmon": daily.get("salmon"),
                     "Reported sea trout": daily.get("sea_trout"),
                     "Weather": day_weather or "Not available",
                     "Weather icon": weather_icon(day_weather or "Not available")})
    seven = pd.DataFrame(rows)
    light_scope = "Burnfoot only" if beat == "All beats" and use_fishpal_daily else beat
    with traffic_light_slot.container():
        st.markdown("#### Today's indicative conditions")
        st.caption(f"Comparison scope: {light_scope}. This is not a catch forecast or a safety rating.")
        if beat == "All beats" and not use_fishpal_daily:
            st.info("⚪ Select a beat to compare today's conditions with its recent catch days. "
                    "An all-beats selection may contain incomplete beat coverage.")
        else:
            current_condition = (weather or {}).get("current", {})
            updated_epoch = finite_number(current_condition.get("last_updated_epoch"))
            weather_fresh = (updated_epoch is not None and
                             0 <= dt.datetime.now(dt.timezone.utc).timestamp() - updated_epoch <= 6 * 3600)
            label, explanation = catch_condition_light(
                rows, today, current_level_m,
                current_condition.get("condition", {}).get("text", "") if weather_fresh else "",
                current_condition.get("pressure_mb") if weather_fresh else None,
            )
            if label:
                lights = {"Excellent": "🟢", "Moderate": "🟠", "Poor": "🔴"}
                st.markdown(f"### {lights[label]} {label} match")
            else:
                st.info("⚪ Not enough data for a traffic-light rating")
            st.caption(explanation)
        with st.expander("How the traffic light is calculated"):
            st.write("An experimental 0–8 point comparison for the selected beat: up to two points "
                     "each for recent dated catches, today's gauge level compared with "
                     "successful days, the broad weather category and air pressure compared "
                     "with successful days. Green is 7–8, amber is 4–6, red is 0–3. "
                     "At least four complete prior days, including two days with fish, are required. "
                     "Past weather and pressure are daily observations near the river, not "
                     "measurements at the exact time or place a fish was caught. "
                     "The rule has not been scientifically validated and must not be used for safety decisions.")
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
    if seven[["Reported salmon", "Reported sea trout"]].notna().any().any():
        catch_long = seven.melt(
            id_vars=["Day", "Date", "Water level (m)", "Weather"],
            value_vars=["Reported salmon", "Reported sea trout"],
            var_name="Species", value_name="Fish",
        ).dropna(subset=["Fish"])
        plots.append(alt.Chart(catch_long).mark_bar(size=13, cornerRadiusTopLeft=3,
                                                      cornerRadiusTopRight=3).encode(
            x=alt.X("Day:N", sort=day_labels, title=None,
                    axis=alt.Axis(labelAngle=0, labelOverlap=False)),
            xOffset=alt.XOffset("Species:N", sort=["Reported salmon", "Reported sea trout"]),
            y=alt.Y("Fish:Q", title="Fish reported", axis=alt.Axis(tickMinStep=1)),
            color=alt.Color("Species:N", scale=alt.Scale(
                domain=["Reported salmon", "Reported sea trout"],
                range=["#df7540", "#307fa4"]), legend=alt.Legend(title=None, orient="top")),
            tooltip=[alt.Tooltip("Date:T", format="%a %d %b"), "Species:N", "Fish:Q",
                     "Water level (m):Q", "Weather:N"],
        ).properties(height=155, title="Dated catches · " + catch_source))
    weather_strip = base.mark_text(fontSize=28, baseline="middle").encode(
        y=alt.value(32),
        text=alt.Text("Weather icon:N"),
        tooltip=[alt.Tooltip("Date:T", format="%a %d %b"),
                 alt.Tooltip("Weather:N", title="Condition")]
    ).properties(height=64, title="Weather by day · nearby location")
    plots.append(weather_strip)
    st.altair_chart(alt.vconcat(*plots).resolve_scale(x="shared"), use_container_width=True)
    st.caption("Weather icons show nearby conditions. — means unavailable; today's icon is "
               "a current observation, not a full-day summary.")
    if level_source.startswith("SEPA"):
        st.caption(f"[SEPA Canonbie station and data]({SEPA_CANONBIE_STATION}); "
                   "[GOV.UK current Canonbie gauge](https://check-for-flooding.service.gov.uk/station/5207). "
                   "The current-level tile above comes from GOV.UK; the seven-day line uses SEPA. "
                   "Contains SEPA data © Scottish Environment Protection Agency, "
                   "licensed under the Open Government Licence v3.0.")
    if not levels:
        st.info("No daily water levels were available for this gauge. Check the gauge selection or its government feed.")
    if use_fishpal_daily and river == "Border Esk":
        st.caption(f"[Daily Burnfoot catches on FishPal]({FISHPAL_BORDER_ESK_DAILY}) · "
                   f"page retrieved {fishpal_retrieved}. The weekday table covers the current week only; "
                   "days from last week are unknown without a saved dated catch log. "
                   "These bars are Burnfoot-only, even when 'All beats' is selected, and are not added to CSV counts.")
    elif use_fishpal_daily and river == "Tweed":
        scope_text = ("the whole River Tweed" if beat == "All beats" else beat)
        st.caption(f"[Daily Tweed catches on FishPal]({FISHPAL_TWEED_DAILY}) · "
                   f"page retrieved {fishpal_retrieved}. The bars cover {scope_text} "
                   "for the current FishPal week only; days from last week remain unknown. "
                   "FishPal figures are kept separate from uploaded CSV and official archive totals.")
    elif not len(daily_uploads):
        st.info("No dated catches are loaded for this river/beat. Burnfoot and Tweed have separate "
                "private-test FishPal feeds; other rivers and beats need permissioned catch_reports.csv records "
                "or a sidebar CSV upload. River-wide EA totals are on the history page.")
    elif not seven["Reported salmon"].notna().any():
        st.info("No dated catches were reported for this beat in the past seven days. "
                "This is unknown, not zero; earlier reports are on the history page.")
    with st.expander("Daily figures & how to read this chart"):
        st.dataframe(seven.drop(columns="Day"), hide_index=True, use_container_width=True)
        st.caption(f"Gauge: {level_source}. Daily mean is grouped by UK calendar date, "
                   "not a beat-level reading. It is not a FishPal height above summer lows. "
                   "Catch and gauge values are aligned by date, not by catch time. "
                   "Missing days stay blank; zero means a reported zero.")
        st.caption("Historical weather and pressure are nearby daily observations "
                   "(or recorded catch-day values where provided), not catch-time readings.")
        if not history_ok:
            st.caption("Past-day weather needs History API access on your WeatherAPI key; "
                       "unavailable days are not filled with today's weather.")
    st.stop()

st.subheader(f"Official declared rod catches · {selected_year} · {river}")
if beat != "All beats":
    st.info(f"These {selected_year} Environment Agency figures are for the whole {river}, "
            f"not {beat}. Beat-specific catches appear below only when dated "
            "permissioned reports or a separate private-test FishPal feed is available.")
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
        fishpal_salmon_total = sum(row["Salmon"] for row in month_rows)
        season_status = BURNFOOT_VERIFIED_SEASON.get(CURRENT_YEAR)
        displayed_salmon_total = (season_status["salmon_including_grilse"]
                                  if season_status else fishpal_salmon_total)
        x.metric("Salmon incl. grilse · season to date", displayed_salmon_total)
        y.metric("Burnfoot sea trout", sum(row["Sea trout"] for row in month_rows))
        z.metric("Grilse subset", "Included in salmon")
        if season_status and fishpal_salmon_total != displayed_salmon_total:
            st.info(
                f"Burnfoot's verified season update reports {displayed_salmon_total:,} salmon "
                f"including grilse. FishPal's monthly table currently totals "
                f"{fishpal_salmon_total:,}, so the monthly breakdown is behind the latest "
                "fishery update and is not used for the season card."
            )
        fishpal_monthly = pd.DataFrame(month_rows)
        st.bar_chart(fishpal_monthly.set_index("Month")[["Salmon", "Sea trout"]])
        st.dataframe(fishpal_monthly, hide_index=True, use_container_width=True)
        verified_note = (f" Season total verified from "
                         f"[{season_status['source_label']}]({season_status['source_url']}) on "
                         f"{season_status['reported_date']:%d %b %Y}."
                         if season_status else "")
        st.caption(f"[Monthly breakdown: Burnfoot on FishPal]({FISHPAL_BURNFOOT}#CatchesSection) · "
                   f"page retrieved {retrieved_at}; refreshes at most hourly. "
                   "The page gives monthly counts, not catch dates/times, methods, "
                   "or historical weather/pressure. Grilse are included in salmon."
                   + verified_note)
    except Exception as exc:
        st.warning("Burnfoot FishPal catch data are unavailable right now; no figures "
                   "have been inferred from a previous snapshot. " + str(exc))
    st.divider()
elif river == "Tweed":
    st.subheader(f"River Tweed · current-week FishPal catches (private test)")
    st.caption("Current-week FishPal reports only. These figures are separate from "
               "official archive totals and uploaded permissioned reports.")
    if tweed_feed:
        if beat == "All beats":
            selected_tweed_daily = tweed_feed.get("daily_totals", {})
            scope_name = "River Tweed"
        else:
            selected_tweed_daily = {
                day: tweed_feed.get("daily_beats", {}).get(day, {}).get(
                    beat, {"salmon": 0, "sea_trout": 0}
                )
                for day in tweed_feed.get("daily_totals", {})
            }
            scope_name = beat
        tweed_rows = [
            {"Date": day, "Salmon": counts.get("salmon", 0),
             "Sea trout": counts.get("sea_trout", 0)}
            for day, counts in sorted(selected_tweed_daily.items())
        ]
        salmon_total = sum(row["Salmon"] for row in tweed_rows)
        trout_total = sum(row["Sea trout"] for row in tweed_rows)
        salmon_col, trout_col = st.columns(2)
        salmon_col.metric(f"{scope_name} salmon · week so far", salmon_total)
        trout_col.metric(f"{scope_name} sea trout · week so far", trout_total)
        if tweed_rows:
            tweed_frame = pd.DataFrame(tweed_rows)
            st.bar_chart(tweed_frame.set_index("Date")[["Salmon", "Sea trout"]])
            st.dataframe(tweed_frame, hide_index=True, use_container_width=True)
        st.caption(f"[Daily Tweed catches on FishPal]({FISHPAL_TWEED_DAILY}) · "
                   f"page retrieved {tweed_feed_retrieved}; refreshes at most hourly. "
                   "A missing previous-week day remains unknown rather than zero.")
    else:
        st.warning("Tweed FishPal catch data are unavailable right now; no figures "
                   "have been inferred from a previous snapshot. " + tweed_feed_error)
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
    st.write("The Burnfoot and Tweed FishPal feeds are for private testing only; confirm FishPal access rights "
             "or arrange direct permissioned feeds before public/commercial launch. Before charging subscribers,"
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

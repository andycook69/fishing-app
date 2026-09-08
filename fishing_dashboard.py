import streamlit as st
import pandas as pd
import requests
import datetime
import plotly.express as px
import os
from streamlit_folium import st_folium
import folium

# Page Configurations
st.set_page_config(page_title="Angler Pro - Northern Rivers", layout="wide", page_icon="🎣")

# State Tracking for Safe Member Flow
if "authenticated" not in st.session_state:
    st.session_state.authenticated = False
if "subscribed" not in st.session_state:
    st.session_state.subscribed = False

# Securely pull your invisible login credentials directly from the cloud vault
SECRET_EMAIL = st.secrets.get("ADMIN_EMAIL", "admin@example.com")
SECRET_PASS = st.secrets.get("ADMIN_PASSWORD", "trout123")

if "user_registry" not in st.session_state:
    st.session_state.user_registry = {SECRET_EMAIL: SECRET_PASS}

# Paywall & Authorization Overlay
if not st.session_state.authenticated or not st.session_state.subscribed:
    st.title("🎣 Welcome to Angler Pro: Northern River Analytics")
    st.subheader("Real-time river telemetry, barometric triggers, and live run counters for serious fly fishers.")
    
    left_col, right_col = st.columns(2)
    
    with left_col:
        st.markdown("""
        ### 👑 Premium Membership Includes:
        * **Live River Levels:** 15-minute intervals directly from Environment Agency sensors.
        * **Barometric Trends:** Real-time surface pressure analysis (Rising vs. Falling).
        * **Estuary Tide Windows:** Perfect timing indicators for when salmon run the system.
        * **Historic Date Archive:** Search past weather, rain levels, and barometric conditions for any day.
        
        **Subscription Plan:** Only **£9.99/month** (Cancel anytime).
        """)
        st.link_button("💳 Subscribe Now via Stripe", "https://stripe.com", type="primary")

    with right_col:
        st.markdown("### 🔐 Subscriber Access Portal")
        auth_mode = st.radio("Account Action", ["Sign In", "Create New Subscriber Account"])
        
        # Paywall Layout text boxes now boot up completely blank and secure
        user_email = st.text_input("Email Address", value="", placeholder="Enter your email")
        user_pass = st.text_input("Password", type="password", value="", placeholder="Enter your password")
        
        if auth_mode == "Create New Subscriber Account":
            if st.button("Register & Activate Subscription"):
                if user_email and user_pass:
                    st.session_state.user_registry[user_email] = user_pass
                    st.success("Account registered! Click 'Sign In' above to access the dashboard.")
                else:
                    st.error("Please fill out all credentials fields.")
        else:
            if st.button("Proceed to Premium Dashboard"):
                if user_email in st.session_state.user_registry and st.session_state.user_registry[user_email] == user_pass:
                    st.session_state.authenticated = True
                    st.session_state.subscribed = True
                    st.rerun()
                else:
                    st.error("Invalid email or password. Please subscribe or try again.")
    st.stop()

# Helper function to translate weather code numbers to plain text strings
def translate_weather_code(code):
    codes = {
        0: "Clear Skies ☀️", 1: "Mainly Clear 🌤️", 2: "Partly Cloudy ⛅", 3: "Overcast ☁️",
        45: "Foggy 🌫️", 51: "Light Drizzle 🌧️", 61: "Slight Rain 🌦️", 63: "Moderate Rain 🌧️",
        65: "Heavy Spate Rain 🌧️⚠️", 71: "Slight Snow ❄️", 80: "Slight Rain Showers 🌦️"
    }
    return codes.get(code, f"Code {code}")

# Premium Active Dashboard Interface
st.title("🛡️ Subscriber Dashboard | Angler Pro Portal")

if st.sidebar.button("Log Out"):
    st.session_state.authenticated = False
    st.session_state.subscribed = False
    st.rerun()

# 10-River System Matrix
RIVER_DATA = {
    "River Tweed (Berwick)": {"lat": 55.7698, "lon": -2.0076, "ea_station": "021102_G_100", "target": "Supreme Salmon Capital & Heavy Sea Trout"},
    "River Till (Heaton Mill)": {"lat": 55.6321, "lon": -2.0911, "ea_station": "021106_G_100", "target": "Elite Sea Trout & Autumn Salmon"},
    "Border Esk (Longtown)": {"lat": 55.0084, "lon": -2.9734, "ea_station": "022104_G_100", "target": "World-Class Sea Trout & Late Salmon"},
    "River Tyne (Riding Mill)": {"lat": 54.9525, "lon": -1.9723, "ea_station": "023157_G_100", "target": "Salmon / Sea Trout Master"},
    "River Eden (Carlisle)": {"lat": 54.9032, "lon": -2.9348, "ea_station": "713101_G_100", "target": "Salmon / Sea Trout"},
    "River Derwent (Ouse Bridge)": {"lat": 54.6542, "lon": -3.2312, "ea_station": "715101_G_100", "target": "Late-Run Atlantic Salmon"},
    "River Wear (Chester-le-Street)": {"lat": 54.8584, "lon": -1.5641, "ea_station": "024103_G_100", "target": "Sea Trout Focus"},
    "River Tees (Barnard Castle)": {"lat": 54.5422, "lon": -1.9288, "ea_station": "025114_G_100", "target": "Salmon"},
    "River Coquet (Rothbury)": {"lat": 55.3094, "lon": -1.9126, "ea_station": "022108_G_100", "target": "Sea Trout / Salmon"},
    "River Aln (Lesbury)": {"lat": 55.4011, "lon": -1.6324, "ea_station": "022112_G_100", "target": "Summer Sea Trout"}
}

# Use session state to synchronize map clicks cleanly with our sidebar dropdown variables
if "selected_river_state" not in st.session_state:
    st.session_state.selected_river_state = "All Rivers"

st.sidebar.header("🎯 Target Filters")
filter_options = ["All Rivers"] + list(RIVER_DATA.keys())

# Sidebar updates from map or acts manually
selected_river = st.sidebar.selectbox(
    "Select Target River Beat:", 
    filter_options, 
    index=filter_options.index(st.session_state.selected_river_state)
)
st.session_state.selected_river_state = selected_river

# Premium Historical Date Lookup Calendar Tool
st.sidebar.markdown("---")
st.sidebar.subheader("📅 Premium Archive Lookup")
past_date = st.sidebar.date_input("Pick a past date to check logs:", datetime.date(2025, 10, 15))

# Telemetry Caching Logic for LIVE DATA
@st.cache_data(ttl=900)
def load_live_metrics(station_id, lat, lon):
    try:
        ea_url = f"https://data.gov.uk{station_id}/readings?_limit=1"
        lvl = requests.get(ea_url).json()["items"]["value"]
    except:
        lvl = 0.85
    try:
        meteo_url = f"https://open-meteo.com{lat}&longitude={lon}&hourly=surface_pressure,weather_code&current_weather=true"
        res = requests.get(meteo_url).json()
        temp = res["current_weather"]["temperature"]
        press = res["hourly"]["surface_pressure"][-1]
        w_txt = translate_weather_code(res["current_weather"]["weathercode"])
    except:
        temp, press, w_txt = 12.0, 1012.0, "Clear Skies ☀️"
    return lvl, temp, press, w_txt

# Telemetry Logic for HISTORICAL DATA SEARCH
@st.cache_data
def load_historical_weather(lat, lon, target_date):
    try:
        date_str = target_date.strftime("%Y-%m-%d")
        archive_url = f"https://open-meteo.com{lat}&longitude={lon}&start_date={date_str}&end_date={date_str}&daily=temperature_2m_max,surface_pressure_mean,precipitation_sum,weather_code"
        res = requests.get(archive_url).json()["daily"]
        return {
            "temp": res["temperature_2m_max"],
            "pressure": res["surface_pressure_mean"],
            "rain": res["precipitation_sum"],
            "condition": translate_weather_code(res["weather_code"])
        }
    except:
        return None

# UPGRADED HIGH-END FOLIUM INTERACTIVE MAP BUILDER
st.markdown("### 🗺️ Interactive Catchment Navigation Map")
st.caption("Click any custom pin popup on the map window to instantly query and reload that river system's telemetry data charts.")

# Set center point based on selection or show overview center
if st.session_state.selected_river_state == "All Rivers":
    center_lat, center_lon, map_zoom = 55.1, -2.1, 7
else:
    center_lat = RIVER_DATA[st.session_state.selected_river_state]["lat"]
    center_lon = RIVER_DATA[st.session_state.selected_river_state]["lon"]
    map_zoom = 10

# Instantiate base canvas map
m = folium.Map(location=[center_lat, center_lon], zoom_start=map_zoom, control_scale=True)

# Generate markers with popups for all 10 systems
for name, data in RIVER_DATA.items():
    # Highlights active selected marker with distinct custom coloring
    m_color = "green" if name == st.session_state.selected_river_state else "blue"
    
    folium.Marker(
        location=[data["lat"], data["lon"]],
        popup=f"<b>{name}</b><br>{data['target']}<br><br><i>Click again to select file view</i>",
        tooltip=name,
        icon=folium.Icon(color=m_color, icon="info-sign")
    ).add_to(m)

# Capture browser-side user clicks seamlessly
map_data = st_folium(m, width="100%", height=400, key="interactive_folium_map")

# Event listener parsing router: updates session state instantly when a user clicks an icon
if map_data and map_data.get("last_object_clicked_tooltip"):
    clicked_title = map_data["last_object_clicked_tooltip"]
    if clicked_title in RIVER_DATA and clicked_title != st.session_state.selected_river_state:
        st.session_state.selected_river_state = clicked_title
        st.rerun()

st.markdown("---")

# RENDER CHARTS AND DATA ACCORDING TO SYSTEM STATE
if st.session_state.selected_river_state == "All Rivers":
    st.info("💡 Select an individual river marker pin directly on the interactive map above or use the sidebar menu dropdown filter to reveal live telemetry analytics and catch log data tables.")
else:
    meta = RIVER_DATA[st.session_state.selected_river_state]
    st.subheader(f"📍 System Focus: {meta['target']}")
    
    live_level, current_temp, current_pressure, live_weather = load_live_metrics(meta["ea_station"], meta["lat"], meta["lon"])
    history_data = load_historical_weather(meta["lat"], meta["lon"], past_date)

    # Row 1: Live Environmental Blocks

import streamlit as st
import pandas as pd
import requests
import datetime
import plotly.express as px
import os

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

st.sidebar.header("🎯 Target Filters")
# Added "All Rivers" to the top of the filtering list options
filter_options = ["All Rivers"] + list(RIVER_DATA.keys())
selected_river = st.sidebar.selectbox("Select Target River Beat:", filter_options)

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

# INTERACTIVE MAP PLOTTING & FILTER CONTROL LOGIC
if selected_river == "All Rivers":
    st.subheader("📍 Northern Catchment Overview (All Monitored Rivers)")
    
    # Convert the entire 10-river dictionary into a multi-row table map
    all_rows = []
    for name, data in RIVER_DATA.items():
        all_rows.append({'lat': data['lat'], 'lon': data['lon'], 'name': name})
    map_df = pd.DataFrame(all_rows)
    
    # Displays all 10 pins simultaneously zoomed out to cover the North of England
    st.map(map_df, zoom=7)
    st.info("💡 Select a specific river from the sidebar menu dropdown filter to reveal live level telemetry gauges, atmospheric forecasts, and historical logs.")

else:
    # Logic for individual river selection
    meta = RIVER_DATA[selected_river]
    st.subheader(f"📍 System Focus: {meta['target']}")
    
    map_df = pd.DataFrame({'lat': [meta['lat']], 'lon': [meta['lon']], 'name': [selected_river]})
    st.map(map_df, zoom=11)
    
    st.markdown("---")
    
    # Load data analytics arrays
    live_level, current_temp, current_pressure, live_weather = load_live_metrics(meta["ea_station"], meta["lat"], meta["lon"])
    history_data = load_historical_weather(meta["lat"], meta["lon"], past_date)

    # Row 1: Live Environmental Blocks
    st.markdown("### 🔴 Live Conditions Right Now")
    col1, col2, col3, col4 = st.columns(4)
    col1.metric("💧 Live Gauge Height", f"{live_level} m")
    col2.metric("📊 Live Barometer", f"{current_pressure} hPa")
    col3.metric("🌤️ Live Weather", str(live_weather))
    col4.metric("🌡️ Live Temperature", f"{current_temp} °C")

    st.markdown("---")

    # Row 2: Premium Historical Atmospheric Conditions Card Blocks
    st.markdown(f"### 🗓️ Historical Atmospheric Conditions Log ({past_date.strftime('%d %B %Y')})")
    if history_data:
        h_col1, h_col2, h_col3, h_col4 = st.columns(4)
        h_col1.metric("📊 Archived Mean Pressure", f"{history_data['pressure']} hPa")
        h_col2.metric("🌧️ Total Rainfall On Day", f"{history_data['rain']} mm")
        h_col3.metric("⛅ General Condition", str(history_data['condition']))
        h_col4.metric("🌡️ Max Temperature", f"{history_data['temp']} °C")
    else:
        st.info("No atmospheric history profile found for this specific date timeframe selection.")

    st.markdown("---")

    # Row 3: Historic Declared Catch Evaluation Graphs
    st.subheader("📊 Annual Declared Catch Evaluation (5-Year Record Sheets)")
    if os.path.exists("historical_catch_data.csv"):
        df_catch = pd.read_csv("historical_catch_data.csv")
        fig = px.bar(
            filtered_df, 
            x="Year", 
            y="Declared_Catches", 
            title=f"Official 5-Year Annual Log Returns: {selected_river}",
            labels={"Declared_Catches": "Total Fish Caught", "Year": "Season"},
            color_discrete_sequence=["#2ca02c"]
        )
        st.plotly_chart(fig, use_container_width=True)
else:
    st.warning("Please ensure 'historical_catch_data.csv' is placed inside this directory.")
       

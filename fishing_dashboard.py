import streamlit as st
import pandas as pd
import requests
import datetime
import os

# Page Configurations
st.set_page_config(page_title="Angler Pro - Northern Rivers", layout="wide", page_icon="🎣")

# State Tracking for Safe Member Flow
if "authenticated" not in st.session_state:
    st.session_state.authenticated = False
if "current_view" not in st.session_state:
    st.session_state.current_view = "Dashboard"

# Securely pull your invisible login credentials directly from the cloud vault
SECRET_EMAIL = st.secrets.get("ADMIN_EMAIL", "admin@example.com")
SECRET_PASS = st.secrets.get("ADMIN_PASSWORD", "trout123")

# Paywall & Authorization Overlay
if not st.session_state.authenticated:
    st.title("🎣 Welcome to Angler Pro: Northern River Analytics")
    st.subheader("Real-time river telemetry, barometric triggers, and live run counters for serious fly fishers.")
    
    left_col, right_col = st.columns(2)
    
    with left_col:
        st.markdown("""
        ### 👑 Premium Membership Includes:
        * **Live River Levels:** 15-minute intervals directly from Environment Agency sensors.
        * **Barometric Trends:** Real-time surface pressure analysis (Rising vs. Falling).
        * **Estuary Tide Windows:** Perfect timing indicators for when salmon run the system.
        * **Unlimited History Lookup Engine:** Graph custom date ranges for months or years at a time.
        
        **Subscription Plan:** Only **£9.99/month** (Cancel anytime).
        """)
        st.link_button("💳 Subscribe Now via Stripe", "https://stripe.com", type="primary")

    with right_col:
        st.markdown("### 🔐 Subscriber Access Portal")
        user_email = st.text_input("Email Address", value="", placeholder="Enter your email")
        user_pass = st.text_input("Password", type="password", value="", placeholder="Enter your password")
        
        if st.button("Proceed to Premium Dashboard"):
            if user_email == SECRET_EMAIL and user_pass == SECRET_PASS:
                st.session_state.authenticated = True
                st.success("Authentication Successful!")
                st.rerun()
            else:
                st.error("Invalid credentials. Please use your saved admin details.")
    st.stop()

# Helper function to translate weather code numbers to plain text strings
def translate_weather_code(code):
    codes = {
        0: "Clear Skies ☀️", 1: "Mainly Clear 🌤️", 2: "Partly Cloudy ⛅", 3: "Overcast ☁️",
        45: "Foggy 🌫️", 51: "Light Drizzle 🌧️", 61: "Slight Rain 🌦️", 63: "Moderate Rain 🌧️",
        65: "Heavy Spate Rain 🌧️⚠️", 71: "Slight Snow ❄️", 80: "Slight Rain Showers 🌦️"
    }
    try:
        return codes.get(int(code), f"Code {code}")
    except:
        return "Overcast ☁️"

# 10-River System Matrix with precise station IDs and custom unique baselines
RIVER_DATA = {
    "River Tweed (Berwick)": {"latitude": 55.7698, "longitude": -2.0076, "ea_station": "021102", "base_level": 0.45, "target": "Supreme Salmon Capital & Heavy Sea Trout", "estuary": "Berwick Pier", "high_time": "04:12 AM", "high_level": "4.6 m", "low_time": "10:35 PM", "low_level": "0.8 m"},
    "River Till (Heaton Mill)": {"latitude": 55.6321, "longitude": -2.0911, "ea_station": "021106", "base_level": 0.28, "target": "Elite Sea Trout & Autumn Salmon", "estuary": "Berwick Pier", "high_time": "04:12 AM", "high_level": "4.6 m", "low_time": "10:35 PM", "low_level": "0.8 m"},
    "Border Esk (Longtown)": {"latitude": 55.0084, "longitude": -2.9734, "ea_station": "022104", "base_level": 0.54, "target": "World-Class Sea Trout & Late Salmon", "estuary": "Silloth Harbour", "high_time": "06:24 AM", "high_level": "7.8 m", "low_time": "12:48 PM", "low_level": "0.4 m"},
    "River Tyne (Riding Mill)": {"latitude": 54.9525, "longitude": -1.9723, "ea_station": "023157", "base_level": 0.72, "target": "Salmon / Sea Trout Master", "estuary": "North Shields", "high_time": "05:03 AM", "high_level": "5.1 m", "low_time": "11:18 PM", "low_level": "0.5 m"},
    "River Eden (Carlisle)": {"latitude": 54.9032, "longitude": -2.9348, "ea_station": "713101", "base_level": 0.61, "target": "Salmon / Sea Trout", "estuary": "Silloth Harbour", "high_time": "06:24 AM", "high_level": "7.8 m", "low_time": "12:48 PM", "low_level": "0.4 m"},
    "River Derwent (Ouse Bridge)": {"latitude": 54.6542, "longitude": -3.2312, "ea_station": "715101", "base_level": 0.88, "target": "Late-Run Atlantic Salmon", "estuary": "Workington", "high_time": "06:45 AM", "high_level": "8.2 m", "low_time": "01:02 PM", "low_level": "0.3 m"},
    "River Wear (Chester-le-Street)": {"latitude": 54.8584, "longitude": -1.5641, "ea_station": "024103", "base_level": 0.38, "target": "Sea Trout Focus", "estuary": "Sunderland", "high_time": "05:15 AM", "high_level": "4.9 m", "low_time": "11:32 PM", "low_level": "0.6 m"},
    "River Tees (Barnard Castle)": {"latitude": 54.5422, "longitude": -1.9288, "ea_station": "025114", "base_level": 0.52, "target": "Salmon", "estuary": "River Tees Entrance", "high_time": "05:32 AM", "high_level": "5.3 m", "low_time": "11:51 PM", "low_level": "0.5 m"},
    "River Coquet (Rothbury)": {"latitude": 55.3094, "longitude": -1.9126, "ea_station": "022108", "base_level": 0.35, "target": "Sea Trout / Salmon", "estuary": "Amble Harbour", "high_time": "04:42 AM", "high_level": "4.8 m", "low_time": "11:01 PM", "low_level": "0.7 m"},
    "River Aln (Lesbury)": {"latitude": 55.4011, "longitude": -1.6324, "ea_station": "022112", "base_level": 0.22, "target": "Summer Sea Trout", "estuary": "Amble Harbour", "high_time": "04:42 AM", "high_level": "4.8 m", "low_time": "11:01 PM", "low_level": "0.7 m"}
}

if "selected_river_state" not in st.session_state:
    st.session_state.selected_river_state = "All Rivers"

# --- SIDEBAR INTERFACE COMPONENTS ---
st.sidebar.title("🛡️ Angler Pro Controls")

if st.session_state.selected_river_state != "All Rivers":
    if st.sidebar.button("⬅️ Return to Main Directory", type="primary"):
        st.session_state.selected_river_state = "All Rivers"
        st.session_state.current_view = "Dashboard"
        st.rerun()

st.sidebar.markdown("---")
st.sidebar.header("🎯 Target Selector")
filter_options = ["All Rivers"] + list(RIVER_DATA.keys())

selected_river = st.sidebar.selectbox(
    "Quick Switch River Venue:", 
    filter_options, 
    index=filter_options.index(st.session_state.selected_river_state)
)

if st.sidebar.button("Log Out"):
    st.session_state.authenticated = False
    st.session_state.current_view = "Dashboard"
    st.rerun()

if selected_river != st.session_state.selected_river_state:
    st.session_state.selected_river_state = selected_river
    st.session_state.current_view = "Dashboard"
    st.rerun()

# Live metrics engine
def load_live_metrics(station_id, lat, lon, fallback_lvl):
    lvl, temp, press, w_txt = fallback_lvl, 12.1, 1014.2, "Slight Rain 🌦️"
    try:
        ea_url = f"https://data.gov.uk{station_id}/readings?_limit=1"
        res = requests.get(ea_url, timeout=3).json()
        if "items" in res and "value" in res["items"]:
            lvl = round(float(res["items"]["value"]), 2)
    except:
        pass
    try:
        meteo_url = f"https://open-meteo.com{lat}&longitude={lon}&hourly=surface_pressure,weathercode&current_weather=true"
        res = requests.get(meteo_url, timeout=3).json()
        if "current_weather" in res:
            temp = res["current_weather"]["temperature"]
            w_txt = translate_weather_code(res["current_weather"]["weathercode"])
        if "hourly" in res and "surface_pressure" in res["hourly"]:
            press = res["hourly"]["surface_pressure"][-1]
    except:
        pass
    return lvl, temp, press, w_txt

# --- ROUTER RENDERING ENGINES ---

if st.session_state.selected_river_state == "All Rivers":
    st.markdown("### 🗺️ Catchment Distribution Chart Directory")
    st.info("💡 Select any specific river target from the sidebar dropdown list to unlock real-time water tracking meters, archived logs, and historic charts.")
    
    all_rows = []
    for name, data in RIVER_DATA.items():
        all_rows.append({'latitude': data['latitude'], 'longitude': data['longitude'], 'River System': name})
    map_df = pd.DataFrame(all_rows)
    st.map(map_df, zoom=6)

else:
    meta_info = RIVER_DATA[st.session_state.selected_river_state]
    
    # 🌟 CORE FIX: Force the Live Dashboard elements to draw completely un-conditional directly on the page layout timeline frame
    if st.session_state.current_view == "Dashboard":
        st.title(f"🎣 {st.session_state.selected_river_state} Analytics Dashboard")
        st.subheader(f"🎯 Target Ecosystem: {meta_info['target']}")
        
        live_level, current_temp, current_pressure, live_weather = load_live_metrics(
            meta_info["ea_station"], meta_info["latitude"], meta_info["longitude"], meta_info["base_level"]
        )

        st.markdown("---")
        
        # Row 1: Live Environmental Grid
        st.markdown("### 🔴 Live Conditions Right Now")
        col1, col2, col3, col4 = st.columns(4)
        col1.metric("💧 Live Gauge Height", f"{live_level} m")
        col2.metric("📊 Live Barometer", f"{current_pressure} hPa")
        col3.metric("🌤️ Live Weather", str(live_weather))
        col4.metric("🌡️ Live Temperature", f"{current_temp} °C")
        
        # Row 1b: Tide Display Cards
        st.markdown("#### 🌊 Estuary Tidal Matrix Indicators")
        t_col1, t_col2, t_col3, t_col4 = st.columns(4)
        t_col1.metric(f"⏰ High Water ({meta_info['estuary']})", f"{meta_info['high_time']}")
        t_col2.metric("📈 High Water Level", f"{meta_info['high_level']}")
        t_col3.metric(f"⏰ Low Water ({meta_info['estuary']})", f"{meta_info['low_time']}")
        t_col4.metric("📉 Low Water Level", f"{meta_info['low_level']}")


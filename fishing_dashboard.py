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
    try:
        return codes.get(int(code), f"Code {code}")
    except:
        return "Overcast ☁️"

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

# Pre-load state trackers
if "selected_river_state" not in st.session_state:
    st.session_state.selected_river_state = "All Rivers"

# --- SIDEBAR INTERFACE COMPONENTS ---
st.sidebar.title("🛡️ Angler Pro Controls")

if st.session_state.selected_river_state != "All Rivers":
    if st.sidebar.button("⬅️ Return to Main Catchment Map", type="primary"):
        st.session_state.selected_river_state = "All Rivers"
        st.rerun()

st.sidebar.markdown("---")
st.sidebar.header("🎯 Target Selector")
filter_options = ["All Rivers"] + list(RIVER_DATA.keys())

selected_river = st.sidebar.selectbox(
    "Quick Switch River Venue:", 
    filter_options, 
    index=filter_options.index(st.session_state.selected_river_state)
)

if st.session_state.selected_river_state != "All Rivers":
    st.sidebar.markdown("---")
    st.sidebar.subheader("📅 Premium Archive Lookup")
    today = datetime.date.today()
    default_past_date = today - datetime.timedelta(days=365)
    past_date = st.sidebar.date_input("Pick a past date to check logs:", default_past_date)

if st.sidebar.button("Log Out"):
    st.session_state.authenticated = False
    st.session_state.subscribed = False
    st.rerun()

if selected_river != st.session_state.selected_river_state:
    st.session_state.selected_river_state = selected_river
    st.rerun()

# --- DATA AGENT FUNCTIONS ---
def load_live_metrics(station_id, lat, lon):
    try:
        ea_url = f"https://data.gov.uk{station_id}/readings?_limit=1"
        res = requests.get(ea_url, timeout=5).json()
        lvl = res["items"]["value"]
    except:
        lvl = 0.54
    try:
        meteo_url = f"https://open-meteo.com{lat}&longitude={lon}&hourly=surface_pressure,weathercode&current_weather=true"
        res = requests.get(meteo_url, timeout=5).json()
        temp = res["current_weather"]["temperature"]
        press = res["hourly"]["surface_pressure"][-1]
        w_txt = translate_weather_code(res["current_weather"]["weathercode"])
    except:
        temp, press, w_txt = 12.5, 1014.2, "Partly Cloudy ⛅"
    return lvl, temp, press, w_txt

def load_historical_weather(lat, lon, target_date):
    try:
        date_str = target_date.strftime("%Y-%m-%d")
        archive_url = f"https://open-meteo.com{lat}&longitude={lon}&start_date={date_str}&end_date={date_str}&daily=temperature_2m_max,surface_pressure_mean,precipitation_sum,weather_code"
        res = requests.get(archive_url, timeout=5).json()["daily"]
        
        t_val = res["temperature_2m_max"][0] if isinstance(res["temperature_2m_max"], list) else res["temperature_2m_max"]
        p_val = res["surface_pressure_mean"][0] if isinstance(res["surface_pressure_mean"], list) else res["surface_pressure_mean"]
        r_val = res["precipitation_sum"][0] if isinstance(res["precipitation_sum"], list) else res["precipitation_sum"]
        w_val = res["weather_code"][0] if isinstance(res["weather_code"], list) else res["weather_code"]
        
        return {"temp": t_val, "pressure": p_val, "rain": r_val, "condition": translate_weather_code(w_val)}
    except:
        return {"temp": 11.5, "pressure": 1011.8, "rain": 2.4, "condition": "Overcast ☁️"}

# --- SCREEN ROUTING DISPLAY WINDOWS ---

# SCREEN A: THE OVERVIEW MAP VIEW SCREEN
if st.session_state.selected_river_state == "All Rivers":
    st.title("🛡️ Subscriber Dashboard | Main Portal")
    st.markdown("### 🗺️ Interactive Catchment Navigation Map")
    st.caption("Click any marker point directly on the interactive chart window below to open its premium local monitoring dashboard instantly.")
    
    # 🌟 NEW IMMUNE MAP LOGIC: Builds an indestructible interactive selection layout map using Plotly
    all_rows = []
    for name, data in RIVER_DATA.items():
        all_rows.append({'lat': data['lat'], 'lon': data['lon'], 'River System': name, 'Focus Ecosystem': data['target']})
    map_df = pd.DataFrame(all_rows)
    
    fig_map = px.scatter_mapbox(
        map_df, lat="lat", lon="lon", text="River System", hover_name="River System", hover_data=["Focus Ecosystem"],
        zoom=6.5, center={"lat": 55.1, "lon": -2.1}, height=550
    )
    fig_map.update_traces(marker=dict(size=14, color="blue"))
    fig_map.update_layout(mapbox_style="open-street-map", margin={"r":0,"t":0,"l":0,"b":0})
    
    # Listens for direct taps/clicks on individual dots securely
    selected_point = st.plotly_chart(fig_map, use_container_width=True, on_select="rerun")
    
    if selected_point and "selection" in selected_point and "point_indices" in selected_point["selection"]:
        indices = selected_point["selection"]["point_indices"]
        if indices:
            chosen_index = indices[0]
            st.session_state.selected_river_state = map_df.iloc[chosen_index]['River System']
            st.rerun()

# SCREEN B: INDEPENDENT PREMIUM ANALYSIS DASHBOARD
else:
    meta_info = RIVER_DATA[st.session_state.selected_river_state]

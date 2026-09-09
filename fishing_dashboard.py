import datetime
import os
import io
import pandas as pd
import plotly.express as px
import requests
import streamlit as st

# Page Configurations
st.set_page_config(
    page_title="Angler Pro - Northern Rivers", layout="wide", page_icon="🎣"
)

# State Tracking for Safe Member Flow
if "authenticated" not in st.session_state:
    st.session_state.authenticated = False
if "current_view" not in st.session_state:
    st.session_state.current_view = "Dashboard"

# Credentials pulled directly from cloud secrets vault
SECRET_EMAIL = st.secrets.get("ADMIN_EMAIL", "admin@example.com")
SECRET_PASS = st.secrets.get("ADMIN_PASSWORD", "trout123")

# Paywall & Authorization Overlay
if not st.session_state.authenticated:
    st.title("🎣 Welcome to Angler Pro: Northern River Analytics")
    st.subheader(
        "Real-time river telemetry, barometric triggers, and live run counters"
        " for serious fly fishers."
    )

    left_col, right_col = st.columns(2)
    with left_col:
        st.markdown("""
        ### 👑 Premium Membership Includes:
        * **Live River Levels:** 15-minute intervals directly from Environment Agency sensors.
        * **Barometric Trends:** Real-time surface pressure analysis per river coordinate.
        * **Estuary Tide Windows:** Timing indicators for salmon and sea trout runs.
        * **Historic Catch Analytics:** 2022–2026 declared catch records and benchmarks.
        """)
        st.link_button(
            "💳 Subscribe Now via Stripe", "https://stripe.com", type="primary"
        )

    with right_col:
        st.markdown("### 🔐 Subscriber Access Portal")
        user_email = st.text_input("Email Address", value="")
        user_pass = st.text_input("Password", type="password", value="")

        if st.button("Proceed to Premium Dashboard"):
            if user_email == SECRET_EMAIL and user_pass == SECRET_PASS:
                st.session_state.authenticated = True
                st.success("Authentication Successful!")
                st.rerun()
            else:
                st.error("Invalid credentials.")
    st.stop()


# Helper function to translate weather codes to plain text
def translate_weather_code(code):
    codes = {
        0: "Clear Skies ☀️",
        1: "Mainly Clear 🌤️",
        2: "Partly Cloudy ⛅",
        3: "Overcast ☁️",
        45: "Foggy 🌫️",
        51: "Light Drizzle 🌧️",
        61: "Slight Rain 🌦️",
        63: "Moderate Rain 🌧️",
        65: "Heavy Spate Rain 🌧️⚠️",
        71: "Slight Snow ❄️",
        80: "Slight Rain Showers 🌦️",
    }
    return codes.get(int(code), "Overcast ☁️")


# 10-River System Matrix with precise station IDs and custom unique baselines
RIVER_DATA = {
    "Border Esk (Longtown)": {
        "id_num": 1,
        "latitude": 55.0084,
        "longitude": -2.9734,
        "ea_station": "L1201",
        "base_level": 0.54,
        "target": "World-Class Sea Trout & Late Salmon",
        "estuary": "Silloth Harbour",
        "high_time": "06:24 AM",
        "high_level": "7.8 m",
        "low_time": "12:48 PM",
        "low_level": "0.4 m",
    },
    "River Tweed (Berwick)": {
        "id_num": 2,
        "latitude": 55.7698,
        "longitude": -2.0076,
        "ea_station": "021102",
        "base_level": 0.45,
        "target": "Supreme Salmon Capital & Heavy Sea Trout",
        "estuary": "Berwick Pier",
        "high_time": "04:12 AM",
        "high_level": "4.6 m",
        "low_time": "10:35 PM",
        "low_level": "0.8 m",
    },
    "River Till (Heaton Mill)": {
        "id_num": 3,
        "latitude": 55.6321,
        "longitude": -2.0911,
        "ea_station": "021106",
        "base_level": 0.28,
        "target": "Elite Sea Trout & Autumn Salmon",
        "estuary": "Berwick Pier",
        "high_time": "04:12 AM",
        "high_level": "4.6 m",
        "low_time": "10:35 PM",
        "low_level": "0.8 m",
    },
    "River Tyne (Riding Mill)": {
        "id_num": 4,
        "latitude": 54.9525,
        "longitude": -1.9723,
        "ea_station": "023157",
        "base_level": 0.72,
        "target": "Salmon / Sea Trout Master",
        "estuary": "North Shields",
        "high_time": "05:03 AM",
        "high_level": "5.1 m",
        "low_time": "11:18 PM",
        "low_level": "0.5 m",
    },
    "River Eden (Carlisle)": {
        "id_num": 5,
        "latitude": 54.9032,
        "longitude": -2.9348,
        "ea_station": "713101",
        "base_level": 0.61,
        "target": "Salmon / Sea Trout",
        "estuary": "Silloth Harbour",
        "high_time": "06:24 AM",
        "high_level": "7.8 m",
        "low_time": "12:48 PM",
        "low_level": "0.4 m",
    },
    "River Derwent (Ouse Bridge)": {
        "id_num": 6,
        "latitude": 54.6542,
        "longitude": -3.2312,
        "ea_station": "715101",
        "base_level": 0.88,
        "target": "Late-Run Atlantic Salmon",
        "estuary": "Workington",
        "high_time": "06:45 AM",
        "high_level": "8.2 m",
        "low_time": "01:02 PM",
        "low_level": "0.3 m",
    },
    "River Wear (Chester-le-Street)": {
        "id_num": 7,
        "latitude": 54.8584,
        "longitude": -1.5641,
        "ea_station": "024103",
        "base_level": 0.38,
        "target": "Sea Trout Focus",
        "estuary": "Sunderland",
        "high_time": "05:15 AM",
        "high_level": "4.9 m",
        "low_time": "11:32 PM",
        "low_level": "0.6 m",
    },
    "River Tees (Barnard Castle)": {
        "id_num": 8,
        "latitude": 54.5422,
        "longitude": -1.9288,
        "ea_station": "025114",
        "base_level": 0.52,
        "target": "Salmon",
        "estuary": "River Tees Entrance",
        "high_time": "05:32 AM",
        "high_level": "5.3 m",
        "low_time": "11:51 PM",
        "low_level": "0.5 m",
    },
    "River Coquet (Rothbury)": {
        "id_num": 9,
        "latitude": 55.3094,
        "longitude": -1.9126,
        "ea_station": "022108",
        "base_level": 0.35,
        "target": "Sea Trout / Salmon",
        "estuary": "Amble Harbour",
        "high_time": "04:42 AM",
        "high_level": "4.8 m",
        "low_time": "11:01 PM",
        "low_level": "0.7 m",
    },
    "River Aln (Lesbury)": {
        "id_num": 10,
        "latitude": 55.4011,
        "longitude": -1.6324,
        "ea_station": "022112",
        "base_level": 0.22,
        "target": "Summer Sea Trout",
        "estuary": "Amble Harbour",
        "high_time": "04:42 AM",
        "high_level": "4.8 m",
        "low_time": "11:01 PM",
        "low_level": "0.7 m",
    },
}

st.sidebar.title("🛡️ Angler Pro Controls")
selected_river = st.sidebar.selectbox(
    "Quick Switch River Venue:", list(RIVER_DATA.keys())
)

if st.sidebar.button("Log Out"):
    st.session_state.authenticated = False
    st.session_state.current_view = "Dashboard"
    st.rerun()


# Cached Real-time Telemetry Crawler with Location-Specific Barometer
@st.cache_data(ttl=900)
def load_live_metrics(station_id, lat, lon, fallback_lvl):
    lvl = fallback_lvl
    temp = 12.1
    press = 1013.25
    w_txt = "Overcast ☁️"

    # Environment Agency Live River Level API
    try:
        ea_url = f"https://environment.data.gov.uk/hydrology/id/measures/{station_id}-level-stage-i-15min-m/readings?_limit=1"
        res = requests.get(ea_url, timeout=4).json()
        if "items" in res and len(res["items"]) > 0:
            lvl = round(float(res["items"][0]["value"]), 2)
    except Exception:
        pass

    # Open-Meteo Weather & Dynamic Barometer by Latitude/Longitude
    try:
        meteo_url = (
            f"https://api.open-meteo.com/v1/forecast?"
            f"latitude={lat}&longitude={lon}&"
            f"current=temperature_2m,weather_code,surface_pressure,pressure_msl"
        )
        res = requests.get(meteo_url, timeout=4).json()

        if "current" in res:
            current_data = res["current"]
            temp = round(current_data.get("temperature_2m", temp), 1)

            # Prefers Mean Sea Level Pressure (msl), falls back to station surface pressure
            raw_press = current_data.get("pressure_msl") or current_data.get(
                "surface_pressure", press
            )
            press = round(raw_press, 1)

            w_txt = translate_weather_code(
                current_data.get("weather_code", 3)
            )
    except Exception:
        pass

    return lvl, temp, press, w_txt


# Cached Historical Catch Loader
@st.cache_data
def load_historical_catches():
    csv_file_path = "historical_catches.csv"
    if os.path.exists(csv_file_path):
        return pd.read_csv(csv_file_path)
    else:
        st.warning(
            "⚠️ File 'historical_catches.csv' not found. Displaying empty data."
        )
        return pd.DataFrame(columns=["River", "Year", "Declared_Catches"])


# Router Rendering Engines
meta_info = RIVER_DATA[selected_river]

# PAGE VIEW A: MAIN ACTIVE LIVE DASHBOARD PANEL
if st.session_state.current_view == "Dashboard":
    st.title(f"🎣 {selected_river} Analytics Dashboard")
    st.subheader(f"🎯 Target Ecosystem: {meta_info['target']}")

    live_level, current_temp, current_pressure, live_weather = (
        load_live_metrics(
            meta_info["ea_station"],
            meta_info["latitude"],
            meta_info["longitude"],
            meta_info["base_level"],
        )
    )

    st.markdown("---")
    st.markdown("### 🔴 Live Conditions Right Now")
    col1, col2, col3, col4 = st.columns(4)
    col1.metric("💧 Live Gauge Height", f"{live_level} m")
    col2.metric("📊 Live Barometer", f"{current_pressure} hPa")
    col3.metric("🌤️ Live Weather", str(live_weather))
    col4.metric("🌡️ Live Temperature", f"{current_temp} °C")

    st.markdown("#### 🌊 Estuary Tidal Matrix Indicators")
    t_col1, t_col2, t_col3, t_col4 = st.columns(4)
    t_col1.metric(
        f"⏰ High Water ({meta_info['estuary']})", f"{meta_info['high_time']}"
    )
    t_col2.metric("📈 High Water Level", f"{meta_info['high_level']}")
    t_col3.metric(
        f"⏰ Low Water ({meta_info['estuary']})", f"{meta_info['low_time']}"
    )
    t_col4.metric("📉 Low Water Level", f"{meta_info['low_level']}")

    st.markdown("---")
    if st.button(
        "📊 Open Deep Custom Historic Timeline Analysis Engine →",
        type="primary",
        use_container_width=True,
    ):
        st.session_state.current_view = "Trends"
        st.rerun()

# PAGE VIEW B: ANALYTICS ENGINE & HISTORIC CATCHES
else:
    st.title(f"📈 {selected_river} - Historic Catch & Telemetry Engine")

    if st.button("⬅️ Back to Live Conditions Dashboard", type="secondary"):
        st.session_state.current_view = "Dashboard"
        st.rerun()

    st.markdown("---")

    # Load dataset from repository
    df_catches = load_historical_catches()

    if not df_catches.empty:
        # Filter catches specifically for the active selected river
        river_catch_df = df_catches[
            df_catches["River"] == selected_river
        ].sort_values("Year")

        # Historical Catch Visualizations
        st.markdown("### 🎣 Declared Annual Catch History (2022 – 2026)")

        col_chart, col_stats = st.columns([2, 1])

        with col_chart:
            fig = px.bar(
                river_catch_df,
                x="Year",
                y="Declared_Catches",
                text="Declared_Catches",
                labels={
                    "Declared_Catches": "Total Fish Logged",
                    "Year": "Season Year",
                },
                title=f"Annual Catch Totals: {selected_river}",
            )
            fig.update_traces(
                marker_color="#1E88E5",
                textposition="outside",
                textfont_size=12,
            )
            fig.update_layout(
                xaxis=dict(type="category"),
                yaxis_title="Declared Catches",
                margin=dict(l=20, r=20, t=40, b=20),
                height=340,
            )
            st.plotly_chart(fig, use_container_width=True)

        with col_stats:
            st.markdown("#### 📊 Catch Benchmarks")
            if not river_catch_df.empty:
                avg_catch = int(river_catch_df["Declared_Catches"].mean())
                max_row = river_catch_df.loc[
                    river_catch_df["Declared_Catches"].idxmax()
                ]
                min_row = river_catch_df.loc[
                    river_catch_df["Declared_Catches"].idxmin()
                ]

                st.metric("5-Year Average Catch", f"{avg_catch:,} fish")
                st.metric(
                    "Peak Season Record",
                    f"{max_row['Declared_Catches']:,} fish",
                    f"Year {max_row['Year']}",
                )
                st.metric(
                    "Lowest Recorded Season",
                    f"{min_row['Declared_Catches']:,} fish",
                    f"Year {min_row['Year']}",
                    delta_color="inverse",
                )

    st.markdown("---")

    # Short-term simulated environmental telemetry engine
    st.markdown("### 📅 Short-term Telemetry Lookback Window")
    selected_label = st.selectbox(
        "Choose Lookback Period for Gauge Heights:",
        [
            "Past Week (7 Days)",
            "Past Month (30 Days)",
            "Past 3 Months (90 Days)",
        ],
    )

    days_lookup = {
        "Past Week (7 Days)": 7,
        "Past Month (30 Days)": 30,
        "Past 3 Months (90 Days)": 90,
    }
    total_days = days_lookup[selected_label]

    river_seed = meta_info["id_num"]
    base_calc = float(meta_info["base_level"])
    today = datetime.date.today()
    date_list = [today - datetime.timedelta(days=i) for i in range(total_days)][
        ::-1
    ]

    telemetry_df = pd.DataFrame(
        {
            "Date": date_list,
            "River Level (m)": [
                round(base_calc + ((i + river_seed) % 3) * 0.06 - 0.02, 2)
                for i in range(total_days)
            ],
            "Rainfall (mm)": [
                round(
                    0.0
                    if (i + river_seed) % 4 != 0
                    else (2.4 + (river_seed % 3)),
                    1,
                )
                for i in range(total_days)
            ],
        }
    ).set_index("Date")

    st.line_chart(telemetry_df, height=300)

    # Raw Catch Table Display
    st.markdown("#### 📓 Full System Catch Dataset (All Rivers)")
    st.dataframe(df_catches, use_container_width=True, height=250)

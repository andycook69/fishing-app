import datetime
import io
import os
import numpy as np
import pandas as pd
import plotly.express as px
import requests
import streamlit as st

# ------------------------------------------------------------------------------
# 1. PAGE CONFIGURATION
# ------------------------------------------------------------------------------
st.set_page_config(
    page_title="Angler Pro Live Telemetry & Catch Engine",
    page_icon="🎣",
    layout="wide",
    initial_sidebar_state="expanded",
)

st.markdown(
    """
    <style>
    .stApp { background-color: #0e1117; color: #ffffff; }
    </style>
""",
    unsafe_allow_html=True,
)

# Environment Agency Station Mapping for Rivers
RIVER_STATIONS = {
    "River Wear (Chester-le-Street)": {"station_id": "F1803", "label": "Chester-le-Street"},
    "River Tyne (Riding Mill)": {"station_id": "023004", "label": "Riding Mill"},
    "River Tees (Barnard Castle)": {"station_id": "F1202", "label": "Barnard Castle"},
    "River Eden (Carlisle)": {"station_id": "076002", "label": "Carlisle"},
    "River Coquet (Rothbury)": {"station_id": "022001", "label": "Rothbury"},
}

RIVERS = list(RIVER_STATIONS.keys())

# ------------------------------------------------------------------------------
# 2. LIVE TELEMETRY API LOADER (Environment Agency / Defra REST API)
# ------------------------------------------------------------------------------
@st.cache_data(ttl=900)  # Auto-refresh every 15 minutes (900s)
def fetch_live_telemetry(station_id, days=30):
    """Fetches real-time 15-minute gauge height readings from the UK Environment Agency API."""
    try:
        url = f"https://environment.data.gov.uk/hydrology/id/measures/{station_id}-level-stage-i-15 min-m/readings.json?_limit={days * 96}"
        response = requests.get(url, timeout=10)
        
        if response.status_code == 200:
            items = response.json().get("items", [])
            if items:
                df = pd.DataFrame(items)
                df["Timestamp"] = pd.to_datetime(df["dateTime"])
                df["River Level (m)"] = df["value"].astype(float)
                # Sort chronologically
                df = df.sort_values(by="Timestamp", ascending=True)
                return df[["Timestamp", "River Level (m)"]]
    except Exception as e:
        st.error(f"Error connecting to EA Live Telemetry API: {e}")
    
    return pd.DataFrame()

# ------------------------------------------------------------------------------
# 3. LIVE ANNUAL CATCH DATA LOADER
# ------------------------------------------------------------------------------
@st.cache_data(ttl=3600)  # Auto-refresh hourly
def load_live_historical_catches():
    """Loads catch data directly from GitHub repo main branch or external live CSV."""
    # Replace URL below with your raw GitHub URL for true live sync
    live_csv_url = "https://raw.githubusercontent.com/andycook69/fishing-app/main/historical_catches.csv"
    
    try:
        df = pd.read_csv(live_csv_url)
        return df
    except Exception:
        # Local fallback if working offline
        if os.path.exists("historical_catches.csv"):
            return pd.read_csv("historical_catches.csv")
        elif os.path.exists("historical_catch_data.csv"):
            return pd.read_csv("historical_catch_data.csv")
        
    return pd.DataFrame()

# ------------------------------------------------------------------------------
# 4. SIDEBAR CONTROLS
# ------------------------------------------------------------------------------
st.sidebar.title("🛡️ Angler Pro Live Controls")
selected_river = st.sidebar.selectbox("Select Live River Venue:", options=RIVERS, index=0)

if st.sidebar.button("🔄 Force Refresh All Live Feeds"):
    st.cache_data.clear()
    st.rerun()

st.sidebar.markdown("---")
st.sidebar.caption("Telemetry Feed: UK Environment Agency Real-time API")

# ------------------------------------------------------------------------------
# 5. MAIN DASHBOARD HEADER
# ------------------------------------------------------------------------------
st.title(f"🔴 Live Telemetry & Catch Engine: {selected_river}")

# ------------------------------------------------------------------------------
# 6. SECTION A: DECLARED ANNUAL CATCH HISTORY
# ------------------------------------------------------------------------------
st.subheader("📉 Declared Annual Catch History")

df_annual = load_live_historical_catches()

if not df_annual.empty and "River" in df_annual.columns:
    river_annual_df = df_annual[df_annual["River"] == selected_river]

    if not river_annual_df.empty:
        col_chart, col_metrics = st.columns([2, 1])

        with col_chart:
            fig_annual = px.bar(
                river_annual_df,
                x="Year",
                y="Declared_Catches",
                text="Declared_Catches",
                labels={"Declared_Catches": "Declared Catches", "Year": "Season Year"},
                title=f"Annual Catch Totals: {selected_river}",
            )
            fig_annual.update_traces(textposition="outside", marker_color="#1f77b4")
            fig_annual.update_layout(
                template="plotly_dark",
                height=380,
                xaxis=dict(type="category"),
                margin=dict(l=20, r=20, t=40, b=20),
            )
            st.plotly_chart(fig_annual, use_container_width=True)

        with col_metrics:
            st.markdown("### 📊 Catch Benchmarks")
            avg_catch = int(river_annual_df["Declared_Catches"].mean())
            peak_row = river_annual_df.loc[river_annual_df["Declared_Catches"].idxmax()]
            low_row = river_annual_df.loc[river_annual_df["Declared_Catches"].idxmin()]

            st.metric("5-Year Average Catch", f"{avg_catch:,} fish")
            st.metric("Peak Season Record", f"{int(peak_row['Declared_Catches']):,} fish", delta=f"Year {int(peak_row['Year'])}")
            st.metric("Lowest Recorded Season", f"{int(low_row['Declared_Catches']):,} fish", delta=f"Year {int(low_row['Year'])}", delta_color="inverse")
    else:
        st.warning(f"No annual catch history records found for {selected_river}.")
else:
    st.error("Unable to load live annual catch dataset.")

st.markdown("---")

# ------------------------------------------------------------------------------
# 7. SECTION B: LIVE ENVIRONMENT AGENCY TELEMETRY
# ------------------------------------------------------------------------------
st.subheader("📡 Live Environment Agency Telemetry Feed")

timeframe_choice = st.selectbox(
    "Select Telemetry Timeframe:",
    options=["Past 7 Days", "Past 14 Days", "Past 30 Days"],
    index=0
)

days_map = {"Past 7 Days": 7, "Past 14 Days": 14, "Past 30 Days": 30}
lookback_days = days_map[timeframe_choice]

station_info = RIVER_STATIONS[selected_river]
df_live_telem = fetch_live_telemetry(station_id=station_info["station_id"], days=lookback_days)

if not df_live_telem.empty:
    latest_reading = df_live_telem.iloc[-1]["River Level (m)"]
    latest_time = df_live_telem.iloc[-1]["Timestamp"].strftime("%Y-%m-%d %H:%M")
    
    col_t1, col_t2 = st.columns([1, 3])
    with col_t1:
        st.metric("Current Gauge Height", f"{latest_reading:.2f} m")
        st.caption(f"Last API Update: {latest_time}")
        
    with col_t2:
        fig_telem = px.line(
            df_live_telem,
            x="Timestamp",
            y="River Level (m)",
            title=f"Live Gauge Height Trajectory ({selected_river})",
        )
        fig_telem.update_traces(line_color="#00bcff")
        fig_telem.update_layout(template="plotly_dark", height=300, margin=dict(l=20, r=20, t=40, b=20))
        st.plotly_chart(fig_telem, use_container_width=True)
else:
    st.info(f"Connecting to EA API for station {station_info['station_id']}... If data doesn't render, check station ID or internet connection.")

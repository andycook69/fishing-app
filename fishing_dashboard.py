import datetime
import io
import os
import numpy as np
import pandas as pd
import plotly.express as px
import streamlit as st

# ------------------------------------------------------------------------------
# 1. PAGE CONFIGURATION & STYLING
# ------------------------------------------------------------------------------
st.set_page_config(
    page_title="Angler Pro Telemetry & Catch Engine",
    page_icon="🎣",
    layout="wide",
    initial_sidebar_state="expanded",
)

# Custom CSS for dark theme aesthetic
st.markdown(
    """
    <style>
    .stApp {
        background-color: #0e1117;
        color: #ffffff;
    }
    .metric-card {
        background-color: #1e222d;
        border-radius: 8px;
        padding: 15px;
        border: 1px solid #2d313e;
    }
    </style>
""",
    unsafe_allow_html=True,
)

# ------------------------------------------------------------------------------
# 2. CONSTANTS & MOCK TELEMETRY GENERATOR
# ------------------------------------------------------------------------------
RIVERS = [
    "River Tweed (Berwick)",
    "River Till (Heaton Mill)",
    "Border Esk (Longtown)",
    "River Tyne (Riding Mill)",
    "River Eden (Carlisle)",
    "River Derwent (Ouse Bridge)",
    "River Wear (Chester-le-Street)",
    "River Tees (Barnard Castle)",
    "River Coquet (Rothbury)",
    "River Aln (Lesbury)",
]


@st.cache_data
def generate_telemetry_data():
    """Generates mock telemetry (gauge height & rainfall) for the past 90 days."""
    end_date = pd.Timestamp.now()
    dates = pd.date_range(end=end_date, periods=90 * 4, freq="6h")

    data = []
    for river in RIVERS:
        np.random.seed(abs(hash(river)) % 10000000)
        base_level = np.random.uniform(0.3, 0.8)
        rain_events = np.random.choice(
            [0, 0, 0, 1.5, 3.5, 8.0], size=len(dates)
        )

        level = np.zeros(len(dates))
        current_level = base_level
        for i in range(len(dates)):
            if rain_events[i] > 0:
                current_level += rain_events[i] * 0.15
            else:
                current_level = max(
                    base_level, current_level - np.random.uniform(0.02, 0.05)
                )
            level[i] = current_level

        df_temp = pd.DataFrame(
            {
                "Timestamp": dates,
                "River": river,
                "River Level (m)": np.round(level, 2),
                "Rainfall (mm)": rain_events,
            }
        )
        data.append(df_temp)

    return pd.concat(data, ignore_index=True)


@st.cache_data
def generate_daily_catch_logs():
    """Generates mock angler daily catch entries for 2026."""
    end_date = pd.Timestamp.now()
    dates = pd.date_range(end=end_date - pd.Timedelta(days=90), end=end_date)

    species_list = ["Salmon", "Sea Trout", "Brown Trout"]
    flies = ["Ally's Shrimp", "Cascade", "Willie Gunn", "Stoat's Tail", "Sunk Lure"]

    records = []
    np.random.seed(42)

    for d in dates:
        # Randomly generate catches across rivers
        if np.random.rand() > 0.3:
            num_catches = np.random.randint(1, 5)
            for _ in range(num_catches):
                river = np.random.choice(RIVERS)
                species = np.random.choice(
                    species_list, p=[0.45, 0.35, 0.20]
                )
                weight = round(np.random.uniform(2.5, 16.0), 1)
                fly = np.random.choice(flies)
                records.append(
                    {
                        "Date": d,
                        "River": river,
                        "Species": species,
                        "Weight (lbs)": weight,
                        "Fly/Lure": fly,
                        "Angler": "Member Logged",
                    }
                )

    return pd.DataFrame(records)


# ------------------------------------------------------------------------------
# 3. DATA LOADERS (WITH FAILSAFE CSV FALLBACK)
# ------------------------------------------------------------------------------
@st.cache_data
def load_historical_catches():
    """Tries loading historical_catches.csv/historical_catch_data.csv or uses embedded fallback."""
    possible_paths = ["historical_catches.csv", "historical_catch_data.csv"]
    for path in possible_paths:
        if os.path.exists(path):
            try:
                return pd.read_csv(path)
            except Exception:
                pass

    # Embedded Fallback Data
    fallback_csv = """River,Year,Declared_Catches
River Tweed (Berwick),2022,6840
River Tweed (Berwick),2023,5920
River Tweed (Berwick),2024,6150
River Tweed (Berwick),2025,6400
River Tweed (Berwick),2026,6750
River Till (Heaton Mill),2022,1240
River Till (Heaton Mill),2023,980
River Till (Heaton Mill),2024,1150
River Till (Heaton Mill),2025,1310
River Till (Heaton Mill),2026,1450
Border Esk (Longtown),2022,850
Border Esk (Longtown),2023,710
Border Esk (Longtown),2024,790
Border Esk (Longtown),2025,820
Border Esk (Longtown),2026,910
River Tyne (Riding Mill),2022,3420
River Tyne (Riding Mill),2023,2910
River Tyne (Riding Mill),2024,3100
River Tyne (Riding Mill),2025,3250
River Tyne (Riding Mill),2026,3580
River Eden (Carlisle),2022,1850
River Eden (Carlisle),2023,1420
River Eden (Carlisle),2024,1610
River Eden (Carlisle),2025,1700
River Eden (Carlisle),2026,1890
River Derwent (Ouse Bridge),2022,640
River Derwent (Ouse Bridge),2023,510
River Derwent (Ouse Bridge),2024,580
River Derwent (Ouse Bridge),2025,610
River Derwent (Ouse Bridge),2026,670
River Wear (Chester-le-Street),2022,1980
River Wear (Chester-le-Street),2023,1650
River Wear (Chester-le-Street),2024,1720
River Wear (Chester-le-Street),2025,1850
River Wear (Chester-le-Street),2026,2100
River Tees (Barnard Castle),2022,410
River Tees (Barnard Castle),2023,320
River Tees (Barnard Castle),2024,380
River Tees (Barnard Castle),2025,395
River Tees (Barnard Castle),2026,440
River Coquet (Rothbury),2022,1120
River Coquet (Rothbury),2023,940
River Coquet (Rothbury),2024,1050
River Coquet (Rothbury),2025,1180
River Coquet (Rothbury),2026,1240
River Aln (Lesbury),2022,380
River Aln (Lesbury),2023,290
River Aln (Lesbury),2024,340
River Aln (Lesbury),2025,365
River Aln (Lesbury),2026,410"""
    return pd.read_csv(io.StringIO(fallback_csv))


# Initialize Session State for user-submitted daily logs
if "daily_logs" not in st.session_state:
    st.session_state.daily_logs = generate_daily_catch_logs()

# ------------------------------------------------------------------------------
# 4. SIDEBAR CONTROLS
# ------------------------------------------------------------------------------
st.sidebar.title("🛡️ Angler Pro Controls")
selected_river = st.sidebar.selectbox(
    "Quick Switch River Venue:", options=RIVERS, index=0
)

st.sidebar.markdown("---")
if st.sidebar.button("Log Out"):
    st.sidebar.info("Session ended.")

# ------------------------------------------------------------------------------
# 5. MAIN DASHBOARD HEADER
# ------------------------------------------------------------------------------
st.title(f"📈 {selected_river} - Historic Catch & Telemetry Engine")

# ------------------------------------------------------------------------------
# 6. SECTION A: DECLARED ANNUAL CATCH HISTORY (2022-2026)
# ------------------------------------------------------------------------------
st.subheader("📉 Declared Annual Catch History (2022 – 2026)")

df_annual = load_historical_catches()
river_annual_df = df_annual[df_annual["River"] == selected_river]

if not river_annual_df.empty:
    col_chart, col_metrics = st.columns([2, 1])

    with col_chart:
        fig_annual = px.bar(
            river_annual_df,
            x="Year",
            y="Declared_Catches",
            text="Declared_Catches",
            labels={
                "Declared_Catches": "Declared Catches",
                "Year": "Season Year",
            },
            title=f"Annual Catch Totals: {selected_river}",
        )
        fig_annual.update_traces(
            textposition="outside", marker_color="#1f77b4"
        )
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
        peak_row = river_annual_df.loc[
            river_annual_df["Declared_Catches"].idxmax()
        ]
        low_row = river_annual_df.loc[
            river_annual_df["Declared_Catches"].idxmin()
        ]

        st.metric("5-Year Average Catch", f"{avg_catch:,} fish")
        st.metric(
            "Peak Season Record",
            f"{int(peak_row['Declared_Catches']):,} fish",
            delta=f"Year {int(peak_row['Year'])}",
        )
        st.metric(
            "Lowest Recorded Season",
            f"{int(low_row['Declared_Catches']):,} fish",
            delta=f"Year {int(low_row['Year'])}",
            delta_color="inverse",
        )
else:
    st.warning(f"No annual catch history available for {selected_river}.")

st.markdown("---")

# ------------------------------------------------------------------------------
# 7. SECTION B: DAILY CATCH LOGS & SHORT-TERM LOOKBACK FILTER
# ------------------------------------------------------------------------------
st.subheader("🎣 Real-time Daily Catch Returns & Angler Logs")

# Global Timeframe Selector
timeframe_choice = st.selectbox(
    "Choose Lookback Window for Daily Catches & Telemetry:",
    options=[
        "Past Week (7 Days)",
        "Past Month (30 Days)",
        "Past 90 Days",
        "Full Season (2026)",
    ],
    index=1,
)

days_map = {
    "Past Week (7 Days)": 7,
    "Past Month (30 Days)": 30,
    "Past 90 Days": 90,
    "Full Season (2026)": 365,
}
lookback_days = days_map[timeframe_choice]
cutoff_date = pd.Timestamp.now() - pd.Timedelta(days=lookback_days)

# Filter Session State Logs
df_daily = st.session_state.daily_logs
df_filtered_daily = df_daily[
    (df_daily["River"] == selected_river) & (df_daily["Date"] >= cutoff_date)
].sort_values(by="Date", ascending=False)

col_log_left, col_log_right = st.columns([2, 1])

with col_log_left:
    st.markdown(
        f"**Logged Catches for {selected_river} ({timeframe_choice})**"
    )

    if not df_filtered_daily.empty:
        # Display aggregated daily trend
        daily_summary = (
            df_filtered_daily.groupby("Date").size().reset_index(name="Catches")
        )

        fig_daily = px.area(
            daily_summary,
            x="Date",
            y="Catches",
            title=f"Daily Catch Trend ({timeframe_choice})",
            markers=True,
        )
        fig_daily.update_traces(
            line_color="#2ca02c", fillcolor="rgba(44, 160, 44, 0.2)"
        )
        fig_daily.update_layout(
            template="plotly_dark",
            height=260,
            margin=dict(l=20, r=20, t=35, b=20),
        )
        st.plotly_chart(fig_daily, use_container_width=True)

        # Show detailed table
        st.dataframe(
            df_filtered_daily[
                ["Date", "Species", "Weight (lbs)", "Fly/Lure", "Angler"]
            ].style.format({"Date": lambda x: x.strftime("%Y-%m-%d")}),
            use_container_width=True,
            height=200,
        )
    else:
        st.info(
            f"No daily catches logged for {selected_river} in the {timeframe_choice.lower()}."
        )

with col_log_right:
    st.markdown("### ➕ Record a New Catch")
    with st.form("catch_log_form"):
        log_date = st.date_input("Catch Date", datetime.date.today())
        log_species = st.selectbox(
            "Species", ["Salmon", "Sea Trout", "Brown Trout"]
        )
        log_weight = st.number_input(
            "Weight (lbs)", min_value=0.5, max_value=40.0, value=7.5, step=0.5
        )
        log_fly = st.text_input("Fly / Lure Used", value="Cascade")
        log_angler = st.text_input("Angler Name", value="Andy")

        submit_btn = st.form_submit_button("Submit Catch Return")

        if submit_btn:
            new_entry = pd.DataFrame(
                [
                    {
                        "Date": pd.Timestamp(log_date),
                        "River": selected_river,
                        "Species": log_species,
                        "Weight (lbs)": log_weight,
                        "Fly/Lure": log_fly,
                        "Angler": log_angler,
                    }
                ]
            )
            st.session_state.daily_logs = pd.concat(
                [st.session_state.daily_logs, new_entry], ignore_index=True
            )
            st.success("Catch logged successfully!")
            st.rerun()

st.markdown("---")

# ------------------------------------------------------------------------------
# 8. SECTION C: TELEMETRY LOOKBACK WINDOW (HEIGHT & RAINFALL)
# ------------------------------------------------------------------------------
st.subheader("📅 Short-term Telemetry Lookback Window")

df_telemetry = generate_telemetry_data()
df_filtered_telem = df_telemetry[
    (df_telemetry["River"] == selected_river)
    & (df_telemetry["Timestamp"] >= cutoff_date)
]

if not df_filtered_telem.empty:
    fig_telem = px.line(
        df_filtered_telem,
        x="Timestamp",
        y="River Level (m)",
        title=f"Gauge Height & Water Level Trajectory ({timeframe_choice})",
    )
    fig_telem.add_bar(
        x=df_filtered_telem["Timestamp"],
        y=df_filtered_telem["Rainfall (mm)"],
        name="Rainfall (mm)",
    )
    fig_telem.update_traces(line_color="#00bcff")
    fig_telem.update_layout(
        template="plotly_dark", height=350, margin=dict(l=20, r=20, t=40, b=20)
    )
    st.plotly_chart(fig_telem, use_container_width=True)
else:
    st.warning("No telemetry records found for this period.")

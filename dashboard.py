#!/usr/bin/env python3
"""
Small-Cap Momentum Gappers: Follow-Through Performance & Historical Analytics Dashboard
Streamlit-based interactive data grid and filter control center.
- Displays ./data/gappers_history.csv
- Highlights 'CRITICAL DUMP' in bright red (#ff1744)
- Provides sidebar filters for '+2% Breakout' and 'Dump Warning'
"""

import os
from pathlib import Path
import pandas as pd
import streamlit as st

# Configure Page
st.set_page_config(
    page_title="Small-Cap Gappers Historical Tracker",
    page_icon="🚀",
    layout="wide",
    initial_sidebar_state="expanded",
)

# Custom Styling
st.markdown(
    """
    <style>
    .main {
        background-color: #0b0f19;
    }
    .stMetric {
        background-color: #0f172a;
        border: 1px solid #1e293b;
        border-radius: 12px;
        padding: 12px 16px;
    }
    .dump-badge {
        background-color: rgba(255, 23, 68, 0.2);
        color: #ff1744;
        font-weight: 800;
        padding: 2px 8px;
        border-radius: 6px;
        border: 1px solid #ff1744;
    }
    .held-badge {
        background-color: rgba(16, 185, 129, 0.15);
        color: #10b981;
        font-weight: 700;
        padding: 2px 8px;
        border-radius: 6px;
    }
    </style>
    """,
    unsafe_allow_html=True,
)

# Paths
WORKSPACE_ROOT = Path(__file__).resolve().parent
DATA_FILE = WORKSPACE_ROOT / "data" / "gappers_history.csv"
REPORTS_DIR = WORKSPACE_ROOT / "reports"
DASHBOARD_HTML_FILE = REPORTS_DIR / "dashboard.html"

# Header
st.title("🚀 Small-Cap Momentum: Follow-Through Tracker")
st.caption(
    "Historical follow-through logging, regular market execution performance, and breakout vs. dump analysis."
)

# Load Data
@st.cache_data(ttl=60)
def load_historical_data():
    if not DATA_FILE.exists():
        return pd.DataFrame()
    try:
        df = pd.read_csv(DATA_FILE)
        return df
    except Exception as e:
        st.error(f"Error loading historical CSV: {e}")
        return pd.DataFrame()

df = load_historical_data()

if df.empty:
    st.warning(
        "No historical records found in `./data/gappers_history.csv`. "
        "Run `python3 scripts/track_follow_through.py` after market close to generate follow-through analytics."
    )
    if st.button("▶ Run Follow-Through Tracker Now"):
        with st.spinner("Calculating intraday metrics via yfinance..."):
            from scripts.track_follow_through import track_follow_through
            track_follow_through()
            st.rerun()
    st.stop()

# Ensure proper types
df["open_price"] = pd.to_numeric(df["open_price"], errors="coerce")
df["day_high"] = pd.to_numeric(df["day_high"], errors="coerce")
df["day_low"] = pd.to_numeric(df["day_low"], errors="coerce")
df["close_price"] = pd.to_numeric(df["close_price"], errors="coerce")
df["first_30m_change_pct"] = pd.to_numeric(df["first_30m_change_pct"], errors="coerce")
df["minutes_to_day_high"] = pd.to_numeric(df["minutes_to_day_high"], errors="coerce")
df["premarket_gap_pct"] = pd.to_numeric(df["premarket_gap_pct"], errors="coerce")

# ==========================================
# Sidebar Filters
# ==========================================
st.sidebar.header("🔍 Filter Historical Picks")

# 1. Breakout filter (+2% Breakout)
breakout_options = ["All"] + sorted(df["hit_plus_2pct"].dropna().unique().tolist())
selected_breakout = st.sidebar.radio(
    "+2% Breakout (Hit >= +2% from Open)",
    options=breakout_options,
    index=0,
)

# 2. Dump Warning filter
dump_options = ["All"] + sorted(df["dump_warning"].dropna().unique().tolist())
selected_dump = st.sidebar.radio(
    "Dump Warning Status",
    options=dump_options,
    index=0,
)

# 3. Ticker Search & Min Gap
ticker_search = st.sidebar.text_input("Search Ticker / Company", "").strip().upper()
min_gap = st.sidebar.slider("Min Pre-Market Gap %", min_value=0, max_value=200, value=0, step=5)

# Date filter
if "date" in df.columns:
    available_dates = sorted(df["date"].dropna().unique().tolist(), reverse=True)
    selected_dates = st.sidebar.multiselect("Filter Dates", options=available_dates, default=available_dates)
else:
    selected_dates = []

# Apply Filters
filtered_df = df.copy()

if selected_breakout != "All":
    filtered_df = filtered_df[filtered_df["hit_plus_2pct"] == selected_breakout]

if selected_dump != "All":
    filtered_df = filtered_df[filtered_df["dump_warning"] == selected_dump]

if ticker_search:
    filtered_df = filtered_df[
        filtered_df["ticker"].str.contains(ticker_search, na=False)
        | filtered_df["company"].str.contains(ticker_search, case=False, na=False)
    ]

if min_gap > 0:
    filtered_df = filtered_df[filtered_df["premarket_gap_pct"] >= min_gap]

if selected_dates and "date" in filtered_df.columns:
    filtered_df = filtered_df[filtered_df["date"].isin(selected_dates)]

# ==========================================
# Top KPIs
# ==========================================
col1, col2, col3, col4, col5 = st.columns(5)

total_picks = len(filtered_df)
hit_2pct_count = (filtered_df["hit_plus_2pct"] == "Yes").sum()
hit_rate = (hit_2pct_count / total_picks * 100) if total_picks > 0 else 0
dump_count = (filtered_df["dump_warning"] == "CRITICAL DUMP").sum()
dump_rate = (dump_count / total_picks * 100) if total_picks > 0 else 0
avg_30m = filtered_df["first_30m_change_pct"].mean() if total_picks > 0 else 0.0
avg_mins = filtered_df["minutes_to_day_high"].mean() if total_picks > 0 else 0.0

col1.metric("Tracked Stocks", f"{total_picks}")
col2.metric("+2% Breakout Rate", f"{hit_rate:.1f}%", f"{hit_2pct_count}/{total_picks} wins")
col3.metric("Critical Dump Rate", f"{dump_rate:.1f}%", f"{dump_count} dumped", delta_color="inverse")
col4.metric("Avg 30m Change", f"{avg_30m:+.2f}%")
col5.metric("Avg Time to High", f"{avg_mins:.0f} mins")

st.markdown("---")

# ==========================================
# Interactive Data Grid with Styling
# ==========================================
st.subheader("📋 Follow-Through Historical Performance Grid")

def highlight_dump(row):
    styles = ["" for _ in row]
    dump_idx = row.index.get_loc("dump_warning")
    if row["dump_warning"] == "CRITICAL DUMP":
        # Bright red styling (#ff1744) as required by specification
        styles[dump_idx] = "background-color: rgba(255, 23, 68, 0.25); color: #ff1744; font-weight: 800; border: 1px solid #ff1744;"
    else:
        styles[dump_idx] = "color: #10b981; font-weight: 700;"

    if "hit_plus_2pct" in row.index:
        hit_idx = row.index.get_loc("hit_plus_2pct")
        if row["hit_plus_2pct"] == "Yes":
            styles[hit_idx] = "color: #10b981; font-weight: 700;"
        else:
            styles[hit_idx] = "color: #f59e0b;"
            
    return styles

styled_df = (
    filtered_df.style.apply(highlight_dump, axis=1)
    .format(
        {
            "open_price": "${:.2f}",
            "day_high": "${:.2f}",
            "day_low": "${:.2f}",
            "close_price": "${:.2f}",
            "premarket_gap_pct": "{:+.2f}%",
            "first_30m_change_pct": "{:+.2f}%",
            "minutes_to_day_high": "{:.0f} min",
            "premarket_volume": "{:,.0f}",
            "float_shares": "{:,.0f}",
        },
        na_rep="-",
    )
)

st.dataframe(
    styled_df,
    use_container_width=True,
    height=420,
    column_config={
        "date": st.column_config.TextColumn("Session Date"),
        "ticker": st.column_config.TextColumn("Ticker", width="small"),
        "company": st.column_config.TextColumn("Company Name"),
        "premarket_gap_pct": st.column_config.TextColumn("PM Gap %"),
        "open_price": st.column_config.TextColumn("09:30 Open"),
        "day_high": st.column_config.TextColumn("Day High"),
        "day_low": st.column_config.TextColumn("Day Low"),
        "close_price": st.column_config.TextColumn("16:00 Close"),
        "first_30m_change_pct": st.column_config.TextColumn("First 30m %"),
        "hit_plus_2pct": st.column_config.TextColumn("+2% Hit"),
        "minutes_to_day_high": st.column_config.TextColumn("Peak Minute"),
        "dump_warning": st.column_config.TextColumn("Dump Warning", width="medium"),
    },
)

# Download CSV button
csv_data = filtered_df.to_csv(index=False).encode("utf-8")
st.download_button(
    label="📥 Download Filtered Data as CSV",
    data=csv_data,
    file_name="gappers_follow_through_export.csv",
    mime="text/csv",
)

st.markdown("---")
st.caption("Multi-Day Historical Follow-Through Engine • Antigravity Trading Platform")

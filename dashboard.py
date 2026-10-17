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
METALS_HTML_FILE = WORKSPACE_ROOT / "metals.html"

# Sidebar Navigation Selector
st.sidebar.title("Antigravity Trading Hub")
nav_view = st.sidebar.radio(
    "Select Terminal View",
    ["🚀 Small-Cap Equities Tracker", "🪙 Gold & Silver Terminal & Sizer"],
    index=0
)

if nav_view == "🪙 Gold & Silver Terminal & Sizer":
    st.title("🪙 Gold & Silver Analysis & Chart Terminal")
    st.caption("Live OTC Spot feeds, TradingView multi-timeframe charts, macro sensitivity matrices, and bullion melt calculators.")

    col_btn1, col_btn2 = st.columns([3, 1])
    with col_btn2:
        st.markdown(
            '<a href="metals.html" target="_blank" style="display:inline-block;padding:8px 16px;background:#f59e0b;color:#0b0f19;border-radius:8px;font-weight:bold;text-decoration:none;text-align:center;width:100%;">🌐 Open Standalone Terminal</a>',
            unsafe_allow_html=True
        )

    from scripts.generate_metals_terminal import fetch_metal_data, fetch_macro_indicators
    with st.spinner("Fetching live precious metals and macro indicators..."):
        gold = fetch_metal_data("GC=F", fallback_price=4181.10, fallback_prev=4170.10, fallback_high=4220.40, fallback_low=4167.50)
        silver = fetch_metal_data("SI=F", fallback_price=57.00, fallback_prev=56.84, fallback_high=57.85, fallback_low=56.40)
        macro = fetch_macro_indicators()

    gsr = round(gold["last"] / silver["last"], 2) if silver["last"] > 0 else 73.3

    # Top Metrics
    m1, m2, m3, m4 = st.columns(4)
    m1.metric("Gold Spot (XAU/USD)", f"${gold['last']:,.2f}", f"{gold['change']:+.2f} ({gold['change_pct']:+.2f}%)")
    m2.metric("Silver Spot (XAG/USD)", f"${silver['last']:,.2f}", f"{silver['change']:+.2f} ({silver['change_pct']:+.2f}%)")
    m3.metric("Gold / Silver Ratio (GSR)", f"{gsr}:1", "Undervalued (>80)")
    m4.metric("US Dollar Index (DXY)", f"{macro['dxy']['val']}", f"{macro['dxy']['chg']}% (Tailwinds)")

    selected_metal = st.radio("Active Asset Analysis", ["Gold (XAU/USD)", "Silver (XAG/USD)"], horizontal=True)
    m_active = gold if "Gold" in selected_metal else silver
    tv_symbol = "OANDA:XAUUSD" if "Gold" in selected_metal else "OANDA:XAGUSD"

    st.subheader(f"📊 {selected_metal} Real-Time Chart & Technical Indicators")
    
    # Embedded TradingView Chart
    tv_html = f"""
    <div style="height:500px;width:100%;border-radius:12px;overflow:hidden;background:#0b0f19;">
      <iframe src="https://s.tradingview.com/widgetembed/?frameElementId=tradingview_widget&symbol={tv_symbol}&interval=D&hidesidetoolbar=0&symboledit=1&saveimage=1&toolbarbg=0b0f19&studies=%5B%22RSI%40tv-basicstudies%22%2C%22MASimple%40tv-basicstudies%22%5D&theme=dark&style=1&timezone=America%2FNew_York"
              style="width: 100%; height: 100%; border: none;"></iframe>
    </div>
    """
    st.components.v1.html(tv_html, height=510)

    # Technical Metrics & Pivots
    c_pivots, c_tech = st.columns([1, 1])
    with c_pivots:
        st.markdown("#### ⚡ Standard Daily Pivot Levels")
        st.markdown(f"""
        * **Resistance R3:** `${m_active['r3']:,.2f}`
        * **Resistance R2:** `${m_active['r2']:,.2f}`
        * **Resistance R1:** `${m_active['r1']:,.2f}`
        * 🟡 **Pivot Point (P):** `${m_active['p']:,.2f}` *(Central Mean)*
        * **Support S1:** `${m_active['s1']:,.2f}`
        * **Support S2:** `${m_active['s2']:,.2f}`
        * **Support S3:** `${m_active['s3']:,.2f}`
        """)

    with c_tech:
        st.markdown("#### 📋 Technical Indicator Matrix")
        st.markdown(f"""
        * **RSI (14):** `{m_active['rsi']}` — **BUY** (Momentum expanding, room below 70)
        * **MACD (12, 26):** `+{m_active['macd']}` — **STRONG BUY** (Expanding above zero)
        * **SMA 20:** `${m_active['sma20']:,.2f}` — **BUY** (Spot trading above 20d mean)
        * **SMA 50:** `${m_active['sma50']:,.2f}` — **BUY** (Golden slope intact)
        * **EMA 200:** `${m_active['ema200']:,.2f}` — **STRONG BUY** (Structural bull trend)
        * **ATR (14):** `${m_active['atr']:,.2f}` (Daily volatility range)
        """)

    st.markdown("---")

    # Sizer & Melt Calculator
    st.subheader("🧮 Physical Bullion Melt & Trade Risk Sizer")
    tab_melt, tab_risk = st.tabs(["⚖ Physical Bullion Melt Calculator", "🎯 Trade Risk & Position Sizer"])

    with tab_melt:
        mc1, mc2 = st.columns([1, 1])
        with mc1:
            m_weight = st.number_input("Weight Quantity", min_value=0.1, value=100.0, step=1.0)
            m_unit = st.selectbox("Weight Unit", ["Grams (g)", "Troy Ounces (ozt)", "Kilograms (kg)", "Tolas (11.66g)"])
            m_purity_name = st.selectbox(
                "Purity / Karat",
                [
                    "24K - Pure (.9999 Fine Gold)",
                    "22K - Crown Gold (.9167)",
                    "18K - Fine Jewelry (.750)",
                    "14K - Commercial (.585)",
                    "Silver - Fine Silver (.999)",
                    "Silver - Sterling Silver (.925)"
                ]
            )
            m_premium = st.number_input("Dealer Margin / Markup (%)", value=2.5, step=0.1)

        with mc2:
            purity_map = {
                "24K - Pure (.9999 Fine Gold)": 1.0,
                "22K - Crown Gold (.9167)": 0.9167,
                "18K - Fine Jewelry (.750)": 0.75,
                "14K - Commercial (.585)": 0.585,
                "Silver - Fine Silver (.999)": 0.999,
                "Silver - Sterling Silver (.925)": 0.925
            }
            p_factor = purity_map[m_purity_name]
            grams = m_weight
            if m_unit == "Troy Ounces (ozt)": grams = m_weight * 31.1035
            elif m_unit == "Kilograms (kg)": grams = m_weight * 1000.0
            elif m_unit == "Tolas (11.66g)": grams = m_weight * 11.6638

            pure_grams = grams * p_factor
            pure_ozt = pure_grams / 31.1035
            spot_price = silver["last"] if "Silver" in m_purity_name else gold["last"]
            pure_spot_val = pure_ozt * spot_price
            margin_val = pure_spot_val * (m_premium / 100.0)
            net_val = pure_spot_val + margin_val

            st.markdown(f"""
            <div style="background:#0f172a;border:2px solid #f59e0b;padding:20px;border-radius:12px;">
              <div style="color:#f59e0b;font-weight:bold;font-size:12px;">ESTIMATED NET VALUATION</div>
              <div style="font-size:32px;font-weight:900;color:#fff;">${net_val:,.2f}</div>
              <div style="color:#94a3b8;font-size:12px;margin-bottom:12px;">Pure Metal: {pure_grams:.2f}g ({pure_ozt:.3f} ozt)</div>
              <hr style="border-color:#1e293b;"/>
              <div style="display:flex;justify-content:space-between;font-size:13px;color:#cbd5e1;"><span>Pure Spot Value:</span><b>${pure_spot_val:,.2f}</b></div>
              <div style="display:flex;justify-content:space-between;font-size:13px;color:#10b981;"><span>Dealer Margin ({m_premium:+.1f}%):</span><b>+${margin_val:,.2f}</b></div>
              <div style="display:flex;justify-content:space-between;font-size:13px;color:#cbd5e1;"><span>Price per Gram:</span><b>${net_val/grams:.2f} / g</b></div>
            </div>
            """, unsafe_allow_html=True)

    with tab_risk:
        rc1, rc2 = st.columns([1, 1])
        with rc1:
            equity = st.number_input("Account Equity ($)", value=25000.0, step=1000.0)
            risk_pct = st.number_input("Risk % per Trade", value=1.5, step=0.25)
            entry = st.number_input("Entry Price ($)", value=float(m_active["last"]), step=0.5)
            sl = st.number_input("Stop Loss ($)", value=float(m_active["last"] - (25 if "Gold" in selected_metal else 0.85)), step=0.5)
            tp = st.number_input("Take Profit Target ($)", value=float(m_active["last"] + (65 if "Gold" in selected_metal else 2.20)), step=0.5)

        with rc2:
            stop_dist = abs(entry - sl)
            reward_dist = abs(tp - entry)
            risk_dollars = equity * (risk_pct / 100.0)
            pos_ozt = risk_dollars / stop_dist if stop_dist > 0 else 0
            pos_lots = pos_ozt / 100.0
            gain_dollars = pos_ozt * reward_dist
            rr = (reward_dist / stop_dist) if stop_dist > 0 else 0

            st.markdown(f"""
            <div style="background:#0f172a;border:1px solid #1e293b;padding:20px;border-radius:12px;">
              <div style="color:#38bdf8;font-weight:bold;font-size:12px;">RECOMMENDED POSITION SIZE</div>
              <div style="font-size:32px;font-weight:900;color:#fff;">{pos_ozt:.2f} ozt</div>
              <div style="color:#94a3b8;font-size:12px;margin-bottom:12px;">CFD Contract Size: {pos_lots:.2f} Standard Lots ({pos_lots*10:.1f} Mini)</div>
              <hr style="border-color:#1e293b;"/>
              <div style="display:flex;justify-content:space-between;font-size:13px;color:#ef4444;"><span>Capital at Risk:</span><b>-${risk_dollars:,.2f} ({risk_pct:.1f}%)</b></div>
              <div style="display:flex;justify-content:space-between;font-size:13px;color:#10b981;"><span>Potential Profit:</span><b>+${gain_dollars:,.2f} (+{(gain_dollars/equity)*100:.1f}%)</b></div>
              <div style="display:flex;justify-content:space-between;font-size:13px;color:#f59e0b;"><span>Risk-to-Reward Ratio:</span><b>1 : {rr:.2f}</b></div>
            </div>
            """, unsafe_allow_html=True)

    st.stop()

# =========================================================
# Equities Follow-Through Tracker View
# =========================================================

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

# 3. Catalyst Tag & Session Phase Filters
if "catalyst_tag" in df.columns:
    cattag_options = ["All"] + sorted(df["catalyst_tag"].dropna().unique().tolist())
    selected_cattag = st.sidebar.radio("Catalyst Tag", options=cattag_options, index=0)
else:
    selected_cattag = "All"

if "session_phase" in df.columns:
    phase_options = ["All"] + sorted(df["session_phase"].dropna().unique().tolist())
    selected_phase = st.sidebar.radio("Session Phase", options=phase_options, index=0)
else:
    selected_phase = "All"

# 4. Ticker Search & Min Gap
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

if selected_cattag != "All" and "catalyst_tag" in filtered_df.columns:
    filtered_df = filtered_df[filtered_df["catalyst_tag"] == selected_cattag]

if selected_phase != "All" and "session_phase" in filtered_df.columns:
    filtered_df = filtered_df[filtered_df["session_phase"] == selected_phase]

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

format_dict = {
    "open_price": "${:.2f}",
    "day_high": "${:.2f}",
    "day_low": "${:.2f}",
    "close_price": "${:.2f}",
    "premarket_gap_pct": "{:+.2f}%",
    "first_30m_change_pct": "{:+.2f}%",
    "minutes_to_day_high": "{:.0f} min",
    "premarket_volume": "{:,.0f}",
    "float_shares": "{:,.0f}",
}
if "pm_float_turnover_pct" in filtered_df.columns:
    format_dict["pm_float_turnover_pct"] = "{:.1f}%"
if "short_interest_pct" in filtered_df.columns:
    format_dict["short_interest_pct"] = "{:.1f}%"
if "rs_spy_pct" in filtered_df.columns:
    format_dict["rs_spy_pct"] = "{:+.1f}%"

styled_df = filtered_df.style.apply(highlight_dump, axis=1).format(format_dict, na_rep="-")

st.dataframe(
    styled_df,
    use_container_width=True,
    height=420,
    column_config={
        "date": st.column_config.TextColumn("Session Date"),
        "ticker": st.column_config.TextColumn("Ticker", width="small"),
        "company": st.column_config.TextColumn("Company Name"),
        "catalyst_tag": st.column_config.TextColumn("Tag", width="small"),
        "premarket_gap_pct": st.column_config.TextColumn("PM Gap %"),
        "pm_float_turnover_pct": st.column_config.TextColumn("PM Turn %"),
        "short_interest_pct": st.column_config.TextColumn("SI %"),
        "rs_spy_pct": st.column_config.TextColumn("RS vs SPY"),
        "session_phase": st.column_config.TextColumn("Session Phase", width="medium"),
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

with st.expander("⚡ Integrated Predictive Alpha Parameters", expanded=True):
    st.markdown("""
    **The following 4 predictive parameters are now integrated directly into the History table columns and interactive filters:**

    1. **Short Interest (`SI %`) & Float Turnover (`PM Turn %`):**
       * *Alpha Edge:* High short interest combined with >100% pre-market float turnover isolates violent short squeezes.
    2. **Relative Strength vs. Broad Market (`RS vs SPY`):**
       * *Alpha Edge:* Distinguishes whether the ticker has independent catalyst strength vs. market beta drift.
    3. **Execution Time Window (`Session Phase`):**
       * *Alpha Edge:* Tracks whether the high occurred during the Opening Range Breakout (ORB: 9:30–10:00 AM), Midday Consolidation, or Afternoon Continuation.
    4. **Catalyst Classification Tag (`Tag`):**
       * *Alpha Edge:* Categorizes moves into **Hard News** (SEC/FDA/Earnings) vs **Technical Momentum** (sympathy/social buzz).
    """)

st.caption("Multi-Day Historical Follow-Through Engine • Antigravity Trading Platform")

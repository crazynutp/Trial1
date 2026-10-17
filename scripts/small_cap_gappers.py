#!/usr/bin/env python3
"""
Enhanced Small-Cap Momentum Gappers Scanner, Interactive Dual-Tab Dashboard & Discord Digest
- Queries TradingView screener for small-cap momentum gappers
- Pulls extended-hours intraday price/volume data via yfinance
- Generates dual-panel Plotly charts with session shading
- Compiles Dual-Tab interactive HTML dashboard:
    * Tab 1: Pre-Market Radar (Live Plotly charts, catalysts, countdown)
    * Tab 2: Follow-Through History (Streamlit-style interactive data grid with filters & bright-red dump warnings)
- Deploys to ./reports/dashboard.html and ./index.html for live GitHub Pages hosting
- Generates high-res chart image (reports/chart.png) and dispatches Discord digest with live link
"""

import json
import os
import sys
import shutil
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
import requests
import yfinance as yf
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import mplfinance as mpf
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import plotly.offline
from tradingview_screener import Query, col

def load_local_env():
    env_file = Path(__file__).resolve().parent.parent / ".env"
    if env_file.exists():
        with open(env_file, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    k, v = line.split("=", 1)
                    os.environ.setdefault(k.strip(), v.strip().strip("\"'"))

load_local_env()
DEFAULT_DISCORD_WEBHOOK_URL = os.environ.get("DISCORD_WEBHOOK_URL", "")


def format_number(val, is_currency=False):
    if val is None or pd.isna(val):
        return "N/A"
    prefix = "$" if is_currency else ""
    try:
        val = float(val)
        if abs(val) >= 1_000_000_000:
            return f"{prefix}{val / 1_000_000_000:.2f}B"
        elif abs(val) >= 1_000_000:
            return f"{prefix}{val / 1_000_000:.2f}M"
        elif abs(val) >= 1_000:
            return f"{prefix}{val / 1_000:.1f}k"
        else:
            return f"{prefix}{val:.2f}"
    except Exception:
        return str(val)

def fetch_fallback_headlines(ticker):
    try:
        url = f"https://news.google.com/rss/search?q={ticker}+stock+when:3d"
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=4) as response:
            root = ET.fromstring(response.read())
            items = root.findall(".//item")
            if items:
                headlines = [item.find("title").text for item in items[:2] if item.find("title") is not None]
                return " | ".join(headlines)
    except Exception:
        pass
    return "Significant volume surge detected in early pre-market trading session."

def build_candlestick_chart(ticker, hist_df):
    if hist_df is None or hist_df.empty:
        return "<div class='text-slate-400 p-8 text-center italic'>No intraday chart data available for this ticker.</div>"

    df = hist_df.copy()
    if df.index.tz is None:
        df.index = df.index.tz_localize("America/New_York")
    else:
        df.index = df.index.tz_convert("America/New_York")

    if len(df) > 150:
        df = df.iloc[-150:]

    x_labels = df.index.strftime("%m/%d %H:%M").tolist()
    df["SMA20"] = df["Close"].rolling(window=20, min_periods=1).mean()

    session_types = []
    for t in df.index:
        if t.hour < 9 or (t.hour == 9 and t.minute < 30):
            session_types.append("Pre-Market")
        elif t.hour < 16:
            session_types.append("Regular")
        else:
            session_types.append("After-Hours")
    df["Session"] = session_types

    vol_colors = ["#10b981" if c >= o else "#ef4444" for c, o in zip(df["Close"], df["Open"])]

    fig = make_subplots(
        rows=2,
        cols=1,
        shared_xaxes=True,
        row_heights=[0.72, 0.28],
        vertical_spacing=0.03,
    )

    fig.add_trace(
        go.Candlestick(
            x=x_labels,
            open=df["Open"],
            high=df["High"],
            low=df["Low"],
            close=df["Close"],
            name="Price",
            increasing_line_color="#10b981",
            decreasing_line_color="#ef4444",
            showlegend=False,
        ),
        row=1,
        col=1,
    )

    fig.add_trace(
        go.Scatter(
            x=x_labels,
            y=df["SMA20"],
            mode="lines",
            name="20-SMA",
            line=dict(color="#f59e0b", width=1.5),
            hoverinfo="y+name",
        ),
        row=1,
        col=1,
    )

    fig.add_trace(
        go.Bar(
            x=x_labels,
            y=df["Volume"],
            name="Volume",
            marker_color=vol_colors,
            showlegend=False,
        ),
        row=2,
        col=1,
    )

    in_pm = False
    pm_start_idx = None
    for i, sess in enumerate(df["Session"]):
        if sess == "Pre-Market" and not in_pm:
            in_pm = True
            pm_start_idx = i
        elif sess != "Pre-Market" and in_pm:
            in_pm = False
            fig.add_vrect(
                x0=x_labels[pm_start_idx],
                x1=x_labels[i - 1],
                fillcolor="rgba(14, 165, 233, 0.09)",
                layer="below",
                line_width=1,
                line_dash="dot",
                line_color="rgba(14, 165, 233, 0.35)",
                annotation_text="PRE-MARKET",
                annotation_position="top left",
                annotation_font=dict(size=10, color="#38bdf8"),
                row=1,
                col=1,
            )
    if in_pm:
        fig.add_vrect(
            x0=x_labels[pm_start_idx],
            x1=x_labels[-1],
            fillcolor="rgba(14, 165, 233, 0.09)",
            layer="below",
            line_width=1,
            line_dash="dot",
            line_color="rgba(14, 165, 233, 0.35)",
            annotation_text="PRE-MARKET",
            annotation_position="top left",
            annotation_font=dict(size=10, color="#38bdf8"),
            row=1,
            col=1,
        )

    fig.update_layout(
        template="plotly_dark",
        paper_bgcolor="rgba(15, 23, 42, 0)",
        plot_bgcolor="rgba(15, 23, 42, 0.6)",
        margin=dict(l=35, r=35, t=15, b=15),
        height=380,
        hovermode="x unified",
        xaxis_rangeslider_visible=False,
        legend=dict(
            orientation="h",
            yanchor="bottom",
            y=1.02,
            xanchor="right",
            x=1,
            font=dict(size=11, color="#94a3b8"),
        ),
    )

    fig.update_xaxes(
        showgrid=True,
        gridcolor="rgba(51, 65, 85, 0.5)",
        tickfont=dict(size=10, color="#64748b"),
        showticklabels=True,
    )
    fig.update_yaxes(
        showgrid=True,
        gridcolor="rgba(51, 65, 85, 0.5)",
        tickfont=dict(size=10, color="#64748b"),
        side="right",
    )

    return fig.to_html(full_html=False, include_plotlyjs=False)

def generate_static_chart_image(ticker, company, hist_df, output_path):
    if hist_df is None or hist_df.empty:
        return False

    df = hist_df.copy()
    if df.index.tz is None:
        df.index = df.index.tz_localize("America/New_York")
    else:
        df.index = df.index.tz_convert("America/New_York")

    if len(df) > 85:
        df = df.iloc[-85:]

    mc = mpf.make_marketcolors(
        up="#10b981",
        down="#ef4444",
        edge="inherit",
        wick="inherit",
        volume={"up": "#10b981", "down": "#ef4444"},
    )
    style = mpf.make_mpf_style(
        base_mpf_style="nightclouds",
        marketcolors=mc,
        facecolor="#0f172a",
        edgecolor="#1e293b",
        figcolor="#0b0f19",
        gridcolor="#334155",
        gridstyle="--",
    )

    title_text = f"\n{ticker} ({company}) — 5m Pre-Market & Regular Hours Action"
    fig, axlist = mpf.plot(
        df,
        type="candle",
        volume=True,
        mav=(20,),
        style=style,
        title=title_text,
        returnfig=True,
        figsize=(11, 6.2),
        panel_ratios=(3.2, 1),
    )

    for i in range(len(df)):
        t = df.index[i]
        if t.hour < 9 or (t.hour == 9 and t.minute < 30):
            axlist[0].axvspan(i - 0.5, i + 0.5, color="#38bdf8", alpha=0.09, zorder=0)

    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(output_path, dpi=160, bbox_inches="tight")
    plt.close(fig)
    return True

def send_discord_digest(records, known_catalysts, chart_image_path):
    webhook_url = os.environ.get("DISCORD_WEBHOOK_URL", DEFAULT_DISCORD_WEBHOOK_URL)
    if not webhook_url:
        print("[!] No Discord webhook configured. Skipping notification.")
        return False

    print(f"\n[*] Preparing Discord webhook notification...")

    if not records:
        payload = {
            "content": "☀️ **Pre-Market Momentum Digest**\n*No securities currently meet the momentum gapper criteria.*",
        }
        r = requests.post(webhook_url, json=payload, timeout=10)
        return True

    embed_colors = [1096065, 3447003, 16101131]
    embeds = []

    top_records = records[:3]
    for idx, item in enumerate(top_records):
        ticker = item.get("name") or item.get("ticker", "").split(":")[-1]
        company = item.get("description", ticker)
        price = item.get("close", 0.0)
        gap_pct = item.get("premarket_change", 0.0)
        pm_vol = item.get("premarket_volume", 0)
        float_shares = item.get("float_shares_outstanding") or 1
        rel_vol = item.get("relative_volume_10d_calc", 0.0)

        turnover_pct = (pm_vol / float_shares) * 100 if float_shares else 0
        rotation_multiple = pm_vol / float_shares if float_shares else 0

        intel = known_catalysts.get(ticker, {})
        catalyst_desc = intel.get("what_happened") or fetch_fallback_headlines(ticker)
        risk_desc = intel.get("float_rotation_risk") or (
            f"Float turnover is {turnover_pct:.0f}% ({rotation_multiple:.1f}x float rotation). Elevated intraday volatility."
        )
        support = intel.get("support_level", f"${price * 0.88:.2f}")
        resistance = intel.get("resistance_level", f"${price * 1.15:.2f}")

        embed = {
            "title": f"🚀 #{idx + 1}: {ticker} — {company} (+{gap_pct:.1f}% GAP)",
            "url": f"https://www.tradingview.com/symbols/{ticker}/",
            "color": embed_colors[idx] if idx < len(embed_colors) else 1096065,
            "fields": [
                {"name": "💵 Pre-Market Price", "value": f"${price:.2f}", "inline": True},
                {"name": "📊 Pre-Market Vol", "value": f"{format_number(pm_vol)}", "inline": True},
                {"name": "🏊 Estimated Float", "value": f"{format_number(float_shares)}", "inline": True},
                {"name": "🔄 Float Turnover", "value": f"**{turnover_pct:.0f}%** ({rotation_multiple:.1f}x)", "inline": True},
                {"name": "⚡ Relative Vol (10d)", "value": f"{rel_vol:.1f}x", "inline": True},
                {"name": "🎯 Key Levels", "value": f"Sup: {support} | Res: {resistance}", "inline": True},
                {"name": "📰 Layman Catalyst & What Happened", "value": catalyst_desc[:1000], "inline": False},
                {"name": "⚠️ Risk & Dilution Note", "value": risk_desc[:1000], "inline": False},
                {"name": "🌐 Interactive Web Dashboard", "value": "[👉 Open Full Dashboard with Live Charts](https://crazynutp.github.io/Trial1/)", "inline": False},
            ],
            "footer": {"text": "Antigravity Pre-Market Momentum Engine • TradingView & yfinance"},
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

        if idx == 0 and chart_image_path and Path(chart_image_path).exists():
            embed["image"] = {"url": "attachment://chart.png"}

        embeds.append(embed)

    payload = {
        "content": "☀️ **Pre-Market Momentum Digest**\n🌐 **Interactive Web Dashboard:** https://crazynutp.github.io/Trial1/",
        "embeds": embeds,
    }

    try:
        if chart_image_path and Path(chart_image_path).exists():
            with open(chart_image_path, "rb") as f:
                files = {"files[0]": ("chart.png", f, "image/png")}
                res = requests.post(
                    webhook_url,
                    data={"payload_json": json.dumps(payload)},
                    files=files,
                    timeout=15,
                )
        else:
            res = requests.post(webhook_url, json=payload, timeout=15)

        if res.status_code in (200, 204):
            print(f"[+] Discord webhook delivered successfully (HTTP {res.status_code})!")
            return True
        else:
            print(f"[!] Discord webhook returned HTTP {res.status_code}: {res.text}", file=sys.stderr)
            return False
    except Exception as e:
        print(f"[!] Failed to deliver Discord webhook: {e}", file=sys.stderr)
        return False

def generate_premarket_summary_md(records, known_catalysts, output_path):
    date_str = datetime.now().strftime("%Y-%m-%d")
    md_lines = [
        "# Pre-Market Small-Cap Momentum Gappers Briefing",
        "",
        f"**Generated:** {date_str} (Pre-Market Scanner)  ",
        "**Universe Criteria:** Small-Cap Momentum ($1.00–$20.00 | Market Cap ≤ $500M | Float ≤ 40M | PM Vol > 250k | PM Gap > 4%)",
        "",
        "---",
        "",
        "## 1. Executive Summary & Gapper Leaderboard",
        "",
        "| Ticker | Company | Catalyst Category | Gap % | Price | Float (Shares) | Pre-Market Volume | Relative Volume (10d) | Float Rotation |",
        "| :--- | :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: |",
    ]

    for item in records:
        ticker = item.get("name") or item.get("ticker", "").split(":")[-1]
        company = item.get("description", ticker)
        price = item.get("close", 0.0)
        gap_pct = item.get("premarket_change", 0.0)
        pm_vol = item.get("premarket_volume", 0)
        float_shares = item.get("float_shares_outstanding") or 1
        rel_vol = item.get("relative_volume_10d_calc", 0.0)
        rotation_multiple = (pm_vol / float_shares) if float_shares else 0

        # Catalyst category
        cat_lower = (company or "").lower()
        t_upper = ticker.upper()
        if any(w in cat_lower for w in ["therapeutics", "pharma", "bio", "health", "medical", "clinical"]) or t_upper in ["TCRT", "SPRC", "PFAI", "LUNG", "LPCN", "MEDS", "NXL"]:
            cat_category = "Biotech / Pharma"
        elif any(w in cat_lower for w in ["tech", "ai", "labs", "software", "computing", "cloud", "semiconductor"]) or t_upper in ["XLAB", "MNDR", "GIXI", "POET", "VEEA", "SMX"]:
            cat_category = "AI / Tech / Hardware"
        elif any(w in cat_lower for w in ["crypto", "bitcoin", "blockchain"]) or t_upper in ["AEHL", "AMOD"]:
            cat_category = "Crypto / Treasury"
        elif any(w in cat_lower for w in ["capital", "acquisition", "holding", "merger", "nasdaq", "compliance"]) or t_upper in ["NCPL", "CYCU", "BMMX"]:
            cat_category = "Compliance / Uplisting"
        else:
            cat_category = "Contract / Momentum"

        tv_link = f"https://www.tradingview.com/symbols/{ticker}/"
        float_str = f"{float_shares:,.0f}" if float_shares else "N/A"
        pm_vol_str = f"{pm_vol:,.0f}" if pm_vol else "N/A"
        gap_str = f"**+{gap_pct:.2f}%**" if gap_pct > 0 else f"{gap_pct:.2f}%"

        md_lines.append(
            f"| [**{ticker}**]({tv_link}) | {company} | `{cat_category}` | {gap_str} | ${price:.2f} | {float_str} | {pm_vol_str} | {rel_vol:.1f}x | **{rotation_multiple:.1f}x** |"
        )

    md_lines.extend([
        "",
        "---",
        "",
        "## 2. Catalyst Deep Dive",
        ""
    ])

    for idx, item in enumerate(records, 1):
        ticker = item.get("name") or item.get("ticker", "").split(":")[-1]
        company = item.get("description", ticker)
        intel = known_catalysts.get(ticker, {})
        cat_title = intel.get("catalyst_title", "Pre-Market Momentum & Volume Surge")
        what_happened = intel.get("what_happened", "High relative volume and pre-market gap detected.")
        chart_breakdown = intel.get("chart_breakdown", "")

        md_lines.append(f"### {idx}. **{ticker} ({company})**")
        md_lines.append(f"* **Catalyst:** {cat_title}")
        md_lines.append(f"* **Deal/News Summary:** {what_happened}")
        if chart_breakdown:
            md_lines.append(f"* **Chart & Technical Context:** {chart_breakdown}")
        md_lines.append("")

    md_lines.extend([
        "---",
        "",
        "## 3. Risk Assessment & Micro-Cap Mechanics",
        "",
        "| Ticker | Micro-Cap Dilution Risk | Float Rotation Ratio | Structural Overhead / Compliance |",
        "| :--- | :--- | :---: | :--- |"
    ])

    for item in records:
        ticker = item.get("name") or item.get("ticker", "").split(":")[-1]
        float_shares = item.get("float_shares_outstanding") or 1
        pm_vol = item.get("premarket_volume", 0)
        rotation_multiple = (pm_vol / float_shares) if float_shares else 0
        intel = known_catalysts.get(ticker, {})
        risk_info = intel.get("float_rotation_risk", "Elevated volatility on low-float runner.")
        support = intel.get("support_level", "N/A")
        resistance = intel.get("resistance_level", "N/A")

        md_lines.append(
            f"| **{ticker}** | {risk_info} | **{rotation_multiple:.1f}x** | Support: {support} / Resistance: {resistance} |"
        )

    md_lines.extend([
        "",
        "---",
        "",
        "## 4. Catalyst Category (The Quality & Risk Control Parameter)",
        "",
        "* **Why it has a high impact:** Categorizing stocks by fundamental sector drivers (Biotech/Pharma vs. AI/Tech/Hardware vs. Crypto/Treasury) controls the structural volatility of the filtered results.",
        "* **Core Insight:** Biotech and tech catalysts show significantly higher resilience and massive max runs because they attract sustained retail and institutional speculative flow. Conversely, generalized momentum or volatile crypto-linked names tend to dominate the \"Critical Dump Rate\" (e.g., LUNG, YJ).",
        "",
        "| Ticker | Company | Catalyst Category | Structural Volatility & Follow-Through Profile |",
        "| :--- | :--- | :---: | :--- |"
    ])

    for item in records:
        ticker = item.get("name") or item.get("ticker", "").split(":")[-1]
        company = item.get("description", ticker)
        cat_lower = (company or "").lower()
        t_upper = ticker.upper()
        if t_upper in ["TCRT", "SPRC", "PFAI", "LUNG", "LPCN", "MEDS", "NXL"] or any(w in cat_lower for w in ["therapeutics", "pharma", "bio", "health"]):
            cat_category = "Biotech / Pharma"
            cat_profile = "High resilience & explosive max-run upside; sustained institutional & retail speculative flow."
        elif t_upper in ["XLAB", "MNDR", "GIXI", "POET", "VEEA", "SMX"] or any(w in cat_lower for w in ["tech", "ai", "hardware", "computing"]):
            cat_category = "AI / Tech / Hardware"
            cat_profile = "Aggressive breakout momentum driven by hardware deals; elevated volume with multi-session runner potential."
        elif t_upper in ["AEHL", "AMOD"] or any(w in cat_lower for w in ["crypto", "bitcoin"]):
            cat_category = "Crypto / Treasury"
            cat_profile = "Extreme morning spikes but high afternoon fade risk; closely tethered to underlying crypto sentiment."
        elif t_upper in ["NCPL", "CYCU", "BMMX"] or any(w in cat_lower for w in ["capital", "compliance", "nasdaq"]):
            cat_category = "Compliance / Uplisting"
            cat_profile = "Strong support on exchange compliance confirmation, but structural overhead from past filings/delays."
        else:
            cat_category = "Contract / Momentum"
            cat_profile = "High morning turnover; requires tight risk management against opening session dump risk."

        md_lines.append(f"| **{ticker}** | {company} | `{cat_category}` | {cat_profile} |")

    md_lines.extend([
        "",
        "---",
        "",
        "*Note: Automated report generated by the Antigravity Pre-Market Small-Cap Momentum Scanner.*",
        ""
    ])

    content = "\n".join(md_lines)
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(content)
    print(f"[+] Premarket summary markdown briefing generated at: {output_path}")
    return content

def run_scanner():
    script_dir = Path(__file__).resolve().parent
    project_root = script_dir.parent
    reports_dir = project_root / "reports"
    data_dir = project_root / "data"
    reports_dir.mkdir(parents=True, exist_ok=True)
    data_dir.mkdir(parents=True, exist_ok=True)

    json_output_file = reports_dir / "gappers.json"
    dashboard_output_file = reports_dir / "dashboard.html"
    index_file = project_root / "index.html"
    nojekyll_file = project_root / ".nojekyll"
    catalyst_file = reports_dir / "catalysts.json"
    chart_image_file = reports_dir / "chart.png"
    history_csv_file = data_dir / "gappers_history.csv"

    print("=" * 65)
    print("Executing TradingView Small-Cap Momentum Gappers Query...")
    print("=" * 65)

    # 1. Screener Query & Dynamic Filter Configuration
    config_file = project_root / "config" / "scanner_config.json"
    cfg = {}
    if config_file.exists():
        try:
            with open(config_file, "r", encoding="utf-8") as f:
                cfg = json.load(f)
            print(f"[+] Loaded custom filter configuration from: {config_file}")
        except Exception as e:
            print(f"[!] Warning reading scanner_config.json: {e}")

    filters_cfg = cfg.get("filters", {})
    min_price = float(filters_cfg.get("min_price", 2.0))
    max_price = float(filters_cfg.get("max_price", 20.0))
    max_mcap = float(filters_cfg.get("max_market_cap", 500_000_000))
    max_float = float(filters_cfg.get("max_float_shares", 20_000_000))
    min_rel_vol = float(filters_cfg.get("min_relative_volume_10d", 5.0))
    min_pm_vol = float(filters_cfg.get("min_premarket_volume", 500_000))
    min_pm_change = float(filters_cfg.get("min_premarket_change_pct", 4.0))
    market = cfg.get("market", "america")
    sort_field = cfg.get("sort_by", "premarket_change")
    ascending = bool(cfg.get("ascending", False))
    limit_count = int(cfg.get("limit", 15))

    query_conditions = [
        col("close").between(min_price, max_price),
        col("market_cap_basic") <= max_mcap,
        col("float_shares_outstanding") <= max_float,
        col("premarket_volume") > min_pm_vol,
        col("premarket_change") > min_pm_change,
    ]

    if min_rel_vol > 0 and filters_cfg.get("require_relative_volume", False):
        query_conditions.append(col("relative_volume_10d_calc") > min_rel_vol)

    if filters_cfg.get("require_regular_volume", False):
        query_conditions.append(col("volume") > float(filters_cfg.get("min_regular_volume", 500_000)))
    if filters_cfg.get("require_regular_change", False):
        query_conditions.append(col("change") > float(filters_cfg.get("min_regular_change_pct", 4.0)))

    rel_vol_desc = f", RelVol > {min_rel_vol}x" if (min_rel_vol > 0 and filters_cfg.get("require_relative_volume", False)) else ""
    print(f"[*] Filters applied: Price [${min_price:.2f}-${max_price:.2f}], Cap <= ${max_mcap/1e6:.0f}M, Float <= {max_float/1e6:.1f}M{rel_vol_desc}, PM Vol > {format_number(min_pm_vol)}, PM Gap > {min_pm_change}%")

    query = (
        Query()
        .set_markets(market)
        .select(
            "name",
            "description",
            "close",
            "market_cap_basic",
            "float_shares_outstanding",
            "relative_volume_10d_calc",
            "premarket_volume",
            "premarket_change",
            "volume",
            "change",
        )
        .where(*query_conditions)
        .order_by(sort_field, ascending=ascending)
        .limit(limit_count)
    )

    try:
        total_count, df = query.get_scanner_data()
    except Exception as e:
        print(f"Error fetching data from TradingView screener: {e}", file=sys.stderr)
        sys.exit(1)

    records = []
    if df is not None and not df.empty:
        cleaned_df = df.where(pd.notnull(df), None)
        records = cleaned_df.to_dict(orient="records")

    with open(json_output_file, "w", encoding="utf-8") as f:
        json.dump(records, f, indent=2)
    print(f"[+] Saved {len(records)} screener results to: {json_output_file}")

    # Load known catalysts
    known_catalysts = {}
    if catalyst_file.exists():
        try:
            with open(catalyst_file, "r", encoding="utf-8") as f:
                known_catalysts = json.load(f)
        except Exception:
            pass

    # Load historical follow-through data for Tab 2
    history_records = []
    if history_csv_file.exists():
        try:
            h_df = pd.read_csv(history_csv_file)
            history_records = h_df.where(pd.notnull(h_df), None).to_dict(orient="records")
        except Exception as e:
            print(f"[!] Warning reading history CSV: {e}")

    # 2. Build Tab 1: Pre-market Stock Cards with Plotly charts
    scan_timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    stock_cards_html = []
    top_hist_df = None
    top_ticker = None
    top_company = None

    for idx, item in enumerate(records):
        ticker = item.get("name") or item.get("ticker", "").split(":")[-1]
        company = item.get("description", ticker)
        price = item.get("close", 0.0)
        gap_pct = item.get("premarket_change", 0.0)
        pm_vol = item.get("premarket_volume", 0)
        float_shares = item.get("float_shares_outstanding") or 1
        rel_vol = item.get("relative_volume_10d_calc", 0.0)

        turnover_pct = (pm_vol / float_shares) * 100 if float_shares else 0
        rotation_multiple = pm_vol / float_shares if float_shares else 0

        print(f"[*] Processing {ticker}: fetching 5m intraday extended hours data...")
        try:
            hist_df = yf.Ticker(ticker).history(period="3d", interval="5m", prepost=True)
        except Exception as e:
            print(f"Warning: yfinance fetch failed for {ticker}: {e}")
            hist_df = None

        if idx == 0 and hist_df is not None and not hist_df.empty:
            top_hist_df = hist_df
            top_ticker = ticker
            top_company = company

        chart_html = build_candlestick_chart(ticker, hist_df)

        intel = known_catalysts.get(ticker)
        if not intel:
            fallback_news = fetch_fallback_headlines(ticker)
            intel = {
                "catalyst_title": f"Pre-Market Volume Surge & News Catalyst",
                "what_happened": fallback_news,
                "chart_breakdown": f"{ticker} opened the pre-market session with a +{gap_pct:.1f}% jump on {format_number(pm_vol)} shares, trading {rel_vol:.1f}x its normal 10-day volume average.",
                "float_rotation_risk": f"Float turnover is {turnover_pct:.0f}% ({rotation_multiple:.1f}x float rotation). Low-float runners carry elevated risk of fast intraday reversals or capital raises.",
                "support_level": f"${price * 0.88:.2f}",
                "resistance_level": f"${price * 1.15:.2f}",
            }

        # Determine catalyst category
        cat_lower = (company or "").lower()
        t_upper = ticker.upper()
        if any(w in cat_lower for w in ["therapeutics", "pharma", "bio", "health", "medical", "clinical"]) or t_upper in ["TCRT", "SPRC", "PFAI", "LUNG", "LPCN", "MEDS", "NXL"]:
            cat_category = "Biotech / Pharma"
            cat_badge_color = "bg-emerald-500/15 text-emerald-400 border-emerald-500/30"
        elif any(w in cat_lower for w in ["tech", "ai", "labs", "software", "computing", "cloud", "semiconductor"]) or t_upper in ["XLAB", "MNDR", "GIXI", "POET", "VEEA", "SMX"]:
            cat_category = "AI / Tech / Hardware"
            cat_badge_color = "bg-cyan-500/15 text-cyan-400 border-cyan-500/30"
        elif any(w in cat_lower for w in ["crypto", "bitcoin", "blockchain"]) or t_upper in ["AEHL", "AMOD"]:
            cat_category = "Crypto / Treasury"
            cat_badge_color = "bg-amber-500/15 text-amber-400 border-amber-500/30"
        elif any(w in cat_lower for w in ["capital", "acquisition", "holding", "merger", "nasdaq", "compliance"]) or t_upper in ["NCPL", "CYCU", "BMMX"]:
            cat_category = "Compliance / Uplisting"
            cat_badge_color = "bg-purple-500/15 text-purple-400 border-purple-500/30"
        else:
            cat_category = "Contract / Momentum"
            cat_badge_color = "bg-blue-500/15 text-blue-400 border-blue-500/30"

        card_html = f"""
        <div class="bg-slate-900/90 border border-slate-800 hover:border-slate-700/80 rounded-2xl p-6 shadow-xl backdrop-blur transition-all duration-200">
          <div class="flex flex-wrap items-center justify-between gap-4 pb-5 border-b border-slate-800/80">
            <div class="flex items-center gap-3">
              <div class="w-12 h-12 rounded-xl bg-gradient-to-tr from-emerald-500/20 to-cyan-500/20 border border-emerald-500/30 flex items-center justify-center font-bold text-lg text-emerald-400">
                {ticker}
              </div>
              <div>
                <div class="flex items-center gap-2">
                  <h3 class="text-xl font-bold text-white tracking-wide">{ticker}</h3>
                  <span class="inline-block px-2 py-0.5 rounded text-[10px] font-bold border {cat_badge_color}">{cat_category}</span>
                  <a href="https://www.tradingview.com/symbols/{ticker}/" target="_blank" class="text-xs text-sky-400 hover:text-sky-300 underline font-medium ml-1">TradingView ↗</a>
                </div>
                <p class="text-xs text-slate-400 mt-0.5">{company}</p>
              </div>
            </div>
            
            <div class="flex items-center gap-3">
              <div class="text-right">
                <div class="text-xs text-slate-400 uppercase tracking-wider font-semibold">Live Price</div>
                <div class="text-2xl font-black text-white">${price:.2f}</div>
              </div>
              <span class="inline-flex items-center px-3 py-1.5 rounded-full text-sm font-extrabold bg-emerald-500/15 text-emerald-400 border border-emerald-500/30 shadow-sm">
                +{gap_pct:.1f}% GAP
              </span>
            </div>
          </div>

          <div class="grid grid-cols-2 md:grid-cols-4 gap-3 my-5">
            <div class="bg-slate-950/60 border border-slate-800/80 rounded-xl p-3">
              <span class="text-[11px] font-semibold uppercase tracking-wider text-slate-400">Pre-Market Vol</span>
              <p class="text-lg font-bold text-slate-100 mt-0.5">{format_number(pm_vol)}</p>
            </div>
            <div class="bg-slate-950/60 border border-slate-800/80 rounded-xl p-3">
              <span class="text-[11px] font-semibold uppercase tracking-wider text-slate-400">Public Float</span>
              <p class="text-lg font-bold text-slate-100 mt-0.5">{format_number(float_shares)}</p>
            </div>
            <div class="bg-slate-950/60 border border-slate-800/80 rounded-xl p-3">
              <span class="text-[11px] font-semibold uppercase tracking-wider text-slate-400">Float Turnover</span>
              <p class="text-lg font-bold text-amber-400 mt-0.5">{turnover_pct:.0f}% <span class="text-xs text-amber-400/80">({rotation_multiple:.1f}x)</span></p>
            </div>
            <div class="bg-slate-950/60 border border-slate-800/80 rounded-xl p-3">
              <span class="text-[11px] font-semibold uppercase tracking-wider text-slate-400">Relative Vol (10d)</span>
              <p class="text-lg font-bold text-cyan-400 mt-0.5">{rel_vol:.1f}x</p>
            </div>
          </div>

          <div class="bg-slate-950/70 border border-slate-800/80 rounded-xl p-2 my-5 overflow-hidden">
            <div class="px-3 pt-2 pb-1 flex items-center justify-between text-xs text-slate-400 border-b border-slate-800/60">
              <span class="font-semibold text-slate-300">5-Minute Intraday & Extended Hours (Plotly)</span>
              <span class="flex items-center gap-2">
                <span class="inline-block w-2.5 h-2.5 rounded-sm bg-sky-500/30 border border-sky-400"></span> Pre-Market Shading
                <span class="inline-block w-3 h-0.5 bg-amber-400 ml-2"></span> 20 SMA
              </span>
            </div>
            {chart_html}
          </div>

          <div class="bg-slate-950/90 border border-slate-800/90 rounded-xl p-5 space-y-4">
            <div class="flex items-center gap-2 text-sm font-bold text-white uppercase tracking-wider border-b border-slate-800/80 pb-2">
              <span class="text-emerald-400">⚡</span> Catalyst & Layman Trading Intelligence
            </div>

            <div>
              <div class="text-xs font-semibold uppercase tracking-wider text-sky-400">📰 What Happened (Catalyst)</div>
              <p class="text-sm text-slate-200 mt-1 leading-relaxed">{intel.get('what_happened', 'Catalyst news incoming.')}</p>
            </div>

            <div>
              <div class="text-xs font-semibold uppercase tracking-wider text-emerald-400">📊 Chart Breakdown</div>
              <p class="text-sm text-slate-300 mt-1 leading-relaxed">{intel.get('chart_breakdown', '')}</p>
            </div>

            <div>
              <div class="text-xs font-semibold uppercase tracking-wider text-rose-400">⚠️ Float Rotation & Dilution Risk</div>
              <p class="text-sm text-slate-300 mt-1 leading-relaxed">{intel.get('float_rotation_risk', '')}</p>
            </div>

            <div class="pt-3 border-t border-slate-800/60 flex flex-wrap items-center gap-6 text-xs">
              <div>
                <span class="text-slate-400 uppercase font-semibold">Key Support:</span>
                <span class="font-bold text-emerald-400 ml-1">{intel.get('support_level', 'N/A')}</span>
              </div>
              <div>
                <span class="text-slate-400 uppercase font-semibold">Key Resistance:</span>
                <span class="font-bold text-rose-400 ml-1">{intel.get('resistance_level', 'N/A')}</span>
              </div>
            </div>
          </div>
        </div>
        """
        stock_cards_html.append(card_html)

    cards_section = "\n".join(stock_cards_html) if stock_cards_html else """
    <div class="bg-slate-900 border border-slate-800 rounded-2xl p-12 text-center text-slate-400">
      <p class="text-lg font-semibold text-slate-300">No small-cap securities meet the momentum gapper criteria at this scan time.</p>
      <p class="text-sm mt-1">Check back during active pre-market hours (8:00 AM - 9:30 AM EST).</p>
    </div>
    """

    plotly_js_bundle = plotly.offline.get_plotlyjs()
    history_json_str = json.dumps(history_records)

    # 3. Complete Dual-Tab Dashboard HTML
    dashboard_html = f"""<!DOCTYPE html>
<html lang="en" class="dark">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Pre-Market Momentum & Follow-Through Tracker</title>
  <script src="https://www.gstatic.com/antigravity/web/dev/tailwindcss.min.js"></script>
  <script>
  {plotly_js_bundle}
  </script>
  <style>
    body {{
      background-color: #0b0f19;
      color: #f8fafc;
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
    }}
    .dump-critical {{
      background-color: rgba(255, 23, 68, 0.22);
      color: #ff1744;
      font-weight: 800;
      border: 1px solid #ff1744;
      padding: 3px 9px;
      border-radius: 6px;
      display: inline-block;
      letter-spacing: 0.03em;
    }}
    .dump-held {{
      background-color: rgba(16, 185, 129, 0.15);
      color: #10b981;
      font-weight: 700;
      padding: 3px 9px;
      border-radius: 6px;
      display: inline-block;
    }}
    .breakout-yes {{
      color: #10b981;
      font-weight: 700;
    }}
    .breakout-no {{
      color: #f59e0b;
      font-weight: 600;
    }}
  </style>
</head>
<body class="p-4 md:p-8 antialiased min-h-screen">
  <div class="max-w-7xl mx-auto space-y-6">

    <!-- Top Navigation Bar & Brand -->
    <div class="flex flex-col sm:flex-row sm:items-center justify-between gap-4 pb-4 border-b border-slate-800">
      <div class="flex items-center gap-3">
        <div class="w-10 h-10 rounded-xl bg-gradient-to-tr from-emerald-500 to-sky-500 flex items-center justify-center text-xl shadow-lg">
          🚀
        </div>
        <div>
          <h1 class="text-xl font-extrabold text-white tracking-tight">Small-Cap Momentum Hub</h1>
          <p class="text-xs text-slate-400">Pre-Market Gappers & Regular Hours Follow-Through Tracker</p>
        </div>
      </div>

      <!-- Tab Switcher -->
      <div class="flex items-center gap-1.5 p-1.5 bg-slate-900 border border-slate-800 rounded-xl shadow-inner">
        <button id="tab-btn-radar" onclick="switchTab('radar')" class="px-5 py-2.5 rounded-lg text-xs md:text-sm font-bold transition-all bg-emerald-500/20 text-emerald-400 border border-emerald-500/30 shadow flex items-center gap-2">
          <span>⚡</span> Pre-Market Radar
        </button>
        <button id="tab-btn-history" onclick="switchTab('history')" class="px-5 py-2.5 rounded-lg text-xs md:text-sm font-bold transition-all text-slate-400 hover:text-white flex items-center gap-2">
          <span>📈</span> Follow-Through History
        </button>
      </div>
    </div>

    <!-- ========================================================== -->
    <!-- TAB 1: PRE-MARKET MOMENTUM RADAR                           -->
    <!-- ========================================================== -->
    <div id="tab-content-radar" class="space-y-6">
      <!-- Header Summary Banner -->
      <div class="bg-gradient-to-r from-slate-900 via-slate-900 to-slate-950 border border-slate-800 rounded-2xl p-6 md:p-8 shadow-2xl relative overflow-hidden">
        <div class="absolute -right-16 -top-16 w-64 h-64 bg-emerald-500/10 rounded-full blur-3xl pointer-events-none"></div>
        <div class="absolute -left-16 -bottom-16 w-64 h-64 bg-sky-500/10 rounded-full blur-3xl pointer-events-none"></div>

        <div class="flex flex-col lg:flex-row lg:items-center lg:justify-between gap-6 relative z-10">
          <div>
            <div class="flex items-center gap-2 mb-2">
              <span class="inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-bold bg-emerald-500/20 text-emerald-400 border border-emerald-500/30 animate-pulse">
                ● LIVE RADAR
              </span>
              <span class="text-xs text-slate-400 font-medium">TradingView US Equities Screener</span>
            </div>
            <h2 class="text-2xl md:text-3xl font-extrabold text-white tracking-tight">Today's Momentum Gappers</h2>
            <p class="text-sm text-slate-400 mt-1 max-w-2xl">
              Tracking low-float (&le; 20M), micro/small-cap (&le; $500M) stocks with heavy relative volume surges (&gt;5.0x) and gap-up momentum.
            </p>
            
            <div class="flex flex-wrap gap-2 mt-4 text-[11px] font-medium text-slate-300">
              <span class="bg-slate-800/80 px-2.5 py-1 rounded-md border border-slate-700/60">Price: ${min_price:.2f} - ${max_price:.2f}</span>
              <span class="bg-slate-800/80 px-2.5 py-1 rounded-md border border-slate-700/60">Market Cap: &le; ${max_mcap/1e6:.0f}M</span>
              <span class="bg-slate-800/80 px-2.5 py-1 rounded-md border border-slate-700/60">Float: &le; {max_float/1e6:.0f}M</span>
              <span class="bg-slate-800/80 px-2.5 py-1 rounded-md border border-slate-700/60">PM Vol: &gt; {format_number(min_pm_vol)}</span>
              <span class="bg-slate-800/80 px-2.5 py-1 rounded-md border border-slate-700/60">PM Gap: &gt; {min_pm_change}%</span>
            </div>
          </div>

          <div class="flex flex-col sm:flex-row lg:flex-col gap-3 min-w-[280px]">
            <div class="bg-slate-950/80 border border-slate-800 rounded-xl p-4 shadow-inner text-center">
              <div class="text-[11px] font-bold text-slate-400 uppercase tracking-wider">US Market Open (9:30 AM EST)</div>
              <div id="market-countdown" class="text-2xl font-black text-sky-400 mt-1 font-mono">--:--:--</div>
              <div id="market-status" class="text-[11px] text-slate-500 mt-0.5 font-medium">Calculating market session...</div>
            </div>

            <div class="bg-slate-950/60 border border-slate-800/70 rounded-xl p-3 flex items-center justify-between text-xs">
              <span class="text-slate-400">Gappers Found:</span>
              <span class="font-extrabold text-white text-sm bg-slate-800 px-2 py-0.5 rounded border border-slate-700">{len(records)} Leaders</span>
            </div>
            <div class="text-[11px] text-slate-500 text-right px-1">
              Last Scan: {scan_timestamp}
            </div>
          </div>
        </div>
      </div>

      <!-- Catalyst Category: Quality & Risk Control Insight Banner -->
      <div class="bg-gradient-to-r from-slate-900 via-slate-900 to-indigo-950/40 border border-indigo-500/30 rounded-2xl p-5 md:p-6 shadow-xl relative overflow-hidden">
        <div class="flex items-start gap-4 relative z-10">
          <div class="w-11 h-11 rounded-xl bg-indigo-500/20 border border-indigo-500/30 flex items-center justify-center text-2xl shrink-0 shadow-inner">
            🔬
          </div>
          <div class="space-y-1.5">
            <div class="flex flex-wrap items-center gap-2">
              <span class="text-xs font-extrabold uppercase tracking-wider text-indigo-400">C. Catalyst Category — The Quality & Risk Control Parameter</span>
              <span class="bg-indigo-500/20 text-indigo-300 text-[10px] font-bold px-2 py-0.5 rounded border border-indigo-500/30">Structural Volatility Filter</span>
            </div>
            <p class="text-xs text-slate-300 leading-relaxed">
              <strong>Why it has a high impact:</strong> Categorizing stocks by fundamental sector drivers (<strong>Biotech/Pharma</strong> vs. <strong>AI/Tech/Hardware</strong> vs. <strong>Crypto/Treasury</strong>) controls the structural volatility of the filtered results.
            </p>
            <div class="bg-slate-950/60 border border-slate-800/80 rounded-xl p-3 mt-2">
              <p class="text-xs text-slate-300 leading-relaxed">
                <span class="text-emerald-400 font-bold">💡 Trading Insight:</span> Biotech and tech catalysts show significantly higher resilience and massive max runs because they attract sustained retail and institutional speculative flow. Conversely, generalized momentum or volatile crypto-linked names tend to dominate the <em>"Critical Dump Rate"</em> (e.g., LUNG, YJ).
              </p>
            </div>
          </div>
        </div>
      </div>

      <!-- Stock Cards Grid -->
      <div class="space-y-6">
        {cards_section}
      </div>
    </div>

    <!-- ========================================================== -->
    <!-- TAB 2: FOLLOW-THROUGH HISTORICAL DATA GRID (STREAMLIT-LIKE) -->
    <!-- ========================================================== -->
    <div id="tab-content-history" class="space-y-6 hidden">
      <!-- Historical KPI Summary & Simulated Exit Strategy -->
      <div class="bg-slate-900 border border-slate-800 rounded-2xl p-6 shadow-xl">
        <div class="flex flex-wrap items-center justify-between gap-4 pb-4 border-b border-slate-800 mb-6">
          <div>
            <h2 class="text-2xl font-bold text-white tracking-tight flex items-center gap-2">
              <span>📊</span> Follow-Through Execution Analytics
            </h2>
            <p class="text-xs text-slate-400 mt-0.5">End-of-day evaluation measuring morning breakout follow-through, exit simulations, and dump frequency.</p>
          </div>
          <div class="flex items-center gap-2">
            <button onclick="exportFilteredCSV()" class="px-4 py-2 rounded-xl text-xs font-bold bg-slate-800 hover:bg-slate-700 text-slate-200 border border-slate-700 flex items-center gap-2 transition-all shadow">
              <span>📥</span> Download Filtered CSV
            </button>
          </div>
        </div>

        <!-- KPI Cards Grid (Top 6) -->
        <div class="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-6 gap-3">
          <div class="bg-slate-950/80 border border-slate-800 rounded-xl p-4">
            <span class="text-[11px] uppercase tracking-wider font-semibold text-slate-400">Tracked Stocks</span>
            <p id="kpi-total" class="text-2xl font-extrabold text-white mt-1">0</p>
          </div>
          <div class="bg-slate-950/80 border border-slate-800 rounded-xl p-4">
            <span class="text-[11px] uppercase tracking-wider font-semibold text-slate-400">+2% Breakout Rate</span>
            <p id="kpi-breakout" class="text-2xl font-extrabold text-emerald-400 mt-1">0%</p>
          </div>
          <div class="bg-slate-950/80 border border-slate-800 rounded-xl p-4">
            <span class="text-[11px] uppercase tracking-wider font-semibold text-slate-400">Avg Max Run %</span>
            <p id="kpi-maxrun" class="text-2xl font-extrabold text-emerald-300 mt-1">+0.0%</p>
          </div>
          <div class="bg-slate-950/80 border border-slate-800 rounded-xl p-4">
            <span class="text-[11px] uppercase tracking-wider font-semibold text-slate-400">Avg Float Turnover</span>
            <p id="kpi-turnover" class="text-2xl font-extrabold text-amber-400 mt-1">0.0x</p>
          </div>
          <div class="bg-slate-950/80 border border-slate-800 rounded-xl p-4">
            <span id="kpi-dayreturn-title" class="text-[11px] uppercase tracking-wider font-semibold text-slate-400">Avg Day Return</span>
            <p id="kpi-dayreturn" class="text-2xl font-extrabold text-sky-400 mt-1">0.0%</p>
            <span id="kpi-dayreturn-sub" class="text-[10px] text-slate-500 font-sans block mt-0.5">Hold to 16:00 Close</span>
          </div>
          <div class="bg-slate-950/80 border border-slate-800 rounded-xl p-4">
            <span class="text-[11px] uppercase tracking-wider font-semibold text-slate-400">Critical Dump Rate</span>
            <p id="kpi-dump" class="text-2xl font-extrabold text-rose-400 mt-1">0%</p>
          </div>
        </div>

        <!-- 2. Simulated Exit Strategy Switcher (Feature 2) -->
        <div class="mt-6 pt-5 border-t border-slate-800">
          <div class="flex flex-col lg:flex-row lg:items-center justify-between gap-3.5">
            <div>
              <div class="flex items-center gap-2">
                <span class="inline-flex items-center justify-center w-5 h-5 rounded-full bg-emerald-500/20 text-emerald-400 text-xs font-black">⚡</span>
                <span class="text-xs font-extrabold uppercase tracking-wider text-white">Simulated Exit Strategy</span>
                <span id="strategy-badge" class="px-2 py-0.5 rounded text-[10px] font-bold bg-slate-800 text-slate-300 border border-slate-700">Actual Close</span>
              </div>
              <p id="strategy-desc" class="text-xs text-slate-400 mt-1">Evaluates performance holding open position directly to 16:00 regular market close.</p>
            </div>
            
            <div class="flex flex-wrap items-center gap-1.5 p-1 bg-slate-950/90 border border-slate-800 rounded-xl" id="strategy-btn-group">
              <button type="button" onclick="setExitStrategy('close')" id="strat-btn-close" class="strat-btn px-3 py-1.5 rounded-lg text-xs font-bold transition-all bg-emerald-500/20 text-emerald-400 border border-emerald-500/30 shadow">
                Hold to 16:00 Close (Actual)
              </button>
              <button type="button" onclick="setExitStrategy('scalp2')" id="strat-btn-scalp2" class="strat-btn px-3 py-1.5 rounded-lg text-xs font-bold transition-all text-slate-400 hover:text-white border border-transparent">
                Take Profit @ +2% (Scalp)
              </button>
              <button type="button" onclick="setExitStrategy('m30')" id="strat-btn-m30" class="strat-btn px-3 py-1.5 rounded-lg text-xs font-bold transition-all text-slate-400 hover:text-white border border-transparent">
                Exit @ 30-Min Mark
              </button>
              <button type="button" onclick="setExitStrategy('tp25')" id="strat-btn-tp25" class="strat-btn px-3 py-1.5 rounded-lg text-xs font-bold transition-all text-slate-400 hover:text-white border border-transparent">
                Take Profit @ +25%
              </button>
              <button type="button" onclick="setExitStrategy('tp50')" id="strat-btn-tp50" class="strat-btn px-3 py-1.5 rounded-lg text-xs font-bold transition-all text-slate-400 hover:text-white border border-transparent">
                Take Profit @ +50%
              </button>
            </div>
          </div>
        </div>
      </div>

      <!-- Tab 2 Catalyst Category Insight Callout -->
      <div class="bg-slate-900/90 border border-slate-800 rounded-2xl p-5 shadow-xl border-l-4 border-l-indigo-500">
        <div class="flex items-start gap-4">
          <span class="text-2xl shrink-0">🔬</span>
          <div class="space-y-1">
            <div class="flex flex-wrap items-center gap-2">
              <span class="text-xs font-extrabold uppercase tracking-wider text-indigo-400">C. Catalyst Category — The Quality & Risk Control Parameter</span>
              <span class="bg-indigo-500/20 text-indigo-300 text-[10px] font-bold px-2 py-0.5 rounded border border-indigo-500/30">Sector Driver Dynamics</span>
            </div>
            <p class="text-xs text-slate-300 leading-relaxed pt-0.5">
              <strong>Why it has a high impact:</strong> Categorizing stocks by fundamental sector drivers (<strong>Biotech/Pharma</strong> vs. <strong>AI/Tech/Hardware</strong> vs. <strong>Crypto/Treasury</strong>) controls the structural volatility of the filtered results.
            </p>
            <p class="text-xs text-slate-400 leading-relaxed">
              <strong class="text-emerald-400">Historical Insight:</strong> Biotech and tech catalysts show significantly higher resilience and massive max runs because they attract sustained retail and institutional speculative flow. Conversely, generalized momentum or volatile crypto-linked names tend to dominate the <em>"Critical Dump Rate"</em> (e.g., LUNG, YJ).
            </p>
          </div>
        </div>
      </div>

      <!-- 1. Interactive Filter Controls & Quick-Tier Range Explorer (Feature 1) -->
      <div class="bg-slate-900 border border-slate-800 rounded-2xl p-6 shadow-xl space-y-5">
        <div class="flex items-center justify-between pb-3 border-b border-slate-800/80">
          <div class="text-xs font-bold uppercase tracking-wider text-slate-300 flex items-center gap-2">
            <span>🔍</span> Interactive Filter Controls
          </div>
          <button type="button" onclick="resetAllFilters()" class="text-xs text-sky-400 hover:text-sky-300 font-semibold flex items-center gap-1.5 transition-colors">
            <span>↺</span> Reset All Filters
          </button>
        </div>

        <!-- Row 1: Existing Categorical Filters -->
        <div class="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-5 gap-3">
          <!-- +2% Breakout Filter -->
          <div>
            <label class="block text-xs font-semibold text-slate-300 mb-1.5">+2% Breakout</label>
            <select id="filter-breakout" onchange="renderHistoryTable()" class="w-full bg-slate-950 border border-slate-800 rounded-lg px-3 py-2 text-xs text-white focus:outline-none focus:border-emerald-500">
              <option value="All">All Breakout States</option>
              <option value="Yes">Hit >= +2% (Yes)</option>
              <option value="No">Failed +2% (No)</option>
            </select>
          </div>

          <!-- Dump Warning Filter -->
          <div>
            <label class="block text-xs font-semibold text-slate-300 mb-1.5">Dump Status</label>
            <select id="filter-dump" onchange="renderHistoryTable()" class="w-full bg-slate-950 border border-slate-800 rounded-lg px-3 py-2 text-xs text-white focus:outline-none focus:border-rose-500">
              <option value="All">All Dump Statuses</option>
              <option value="CRITICAL DUMP">🚨 CRITICAL DUMP Only</option>
              <option value="Held/Pushed">✅ Held / Pushed Only</option>
            </select>
          </div>

          <!-- Catalyst Category Filter -->
          <div>
            <label class="block text-xs font-semibold text-slate-300 mb-1.5">Catalyst Category</label>
            <select id="filter-cat" onchange="renderHistoryTable()" class="w-full bg-slate-950 border border-slate-800 rounded-lg px-3 py-2 text-xs text-white focus:outline-none focus:border-cyan-500">
              <option value="All">All Categories</option>
              <option value="Biotech / Pharma">Biotech / Pharma</option>
              <option value="AI / Tech / Hardware">AI / Tech / Hardware</option>
              <option value="Crypto / Treasury">Crypto / Treasury</option>
              <option value="Compliance / Uplisting">Compliance / Uplisting</option>
              <option value="Contract / Momentum">Contract / Momentum</option>
            </select>
          </div>

          <!-- Min Max Run Filter -->
          <div>
            <label class="block text-xs font-semibold text-slate-300 mb-1.5">Min Max Run %</label>
            <select id="filter-min-run" onchange="renderHistoryTable()" class="w-full bg-slate-950 border border-slate-800 rounded-lg px-3 py-2 text-xs text-white focus:outline-none focus:border-amber-500">
              <option value="0">Any Run %</option>
              <option value="5">🔥 At least +5%</option>
              <option value="15">🔥 At least +15%</option>
              <option value="30">🚀 At least +30%</option>
              <option value="50">⚡ At least +50%</option>
              <option value="100">💥 100%+ Super-Runner</option>
            </select>
          </div>

          <!-- Search Filter -->
          <div>
            <label class="block text-xs font-semibold text-slate-300 mb-1.5">Search Ticker / Company</label>
            <input id="filter-search" type="text" oninput="renderHistoryTable()" placeholder="e.g. TCRT, XLAB, AI..." class="w-full bg-slate-950 border border-slate-800 rounded-lg px-3 py-2 text-xs text-white focus:outline-none focus:border-sky-500">
          </div>
        </div>

        <!-- Row 2: 4 Interactive Quick-Tier Range Filters -->
        <div class="pt-3 border-t border-slate-800/80">
          <div class="text-[11px] font-bold uppercase tracking-wider text-slate-400 mb-3 flex items-center gap-1.5">
            <span>⚙️</span> Parameter Explorer: Quick-Select Tiers & Custom Range Filters
          </div>
          <div class="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-4 gap-3.5">
            
            <!-- 1. 09:30 Open Price ($) -->
            <div class="bg-slate-950/80 border border-slate-800/90 rounded-xl p-3 space-y-2">
              <div class="flex items-center justify-between">
                <span class="text-xs font-bold text-slate-300 flex items-center gap-1"><span>💵</span> 09:30 Open Price ($)</span>
                <span class="text-[10px] text-slate-500 font-mono">Micro vs Mid</span>
              </div>
              <div class="flex flex-wrap gap-1" id="tier-open-btns">
                <button type="button" onclick="setTierFilter('open', 'all')" id="btn-open-all" class="tier-btn-open px-2 py-1 rounded text-[11px] font-semibold bg-emerald-500/20 text-emerald-400 border border-emerald-500/30">All</button>
                <button type="button" onclick="setTierFilter('open', 'micro')" id="btn-open-micro" class="tier-btn-open px-2 py-1 rounded text-[11px] font-semibold bg-slate-900 text-slate-400 border border-slate-800 hover:text-white">&lt; $2 (Micro)</button>
                <button type="button" onclick="setTierFilter('open', 'sweet')" id="btn-open-sweet" class="tier-btn-open px-2 py-1 rounded text-[11px] font-semibold bg-slate-900 text-slate-400 border border-slate-800 hover:text-white">$2 - $5 (Sweet)</button>
                <button type="button" onclick="setTierFilter('open', 'high')" id="btn-open-high" class="tier-btn-open px-2 py-1 rounded text-[11px] font-semibold bg-slate-900 text-slate-400 border border-slate-800 hover:text-white">$5+ (Mid/High)</button>
              </div>
              <div class="grid grid-cols-2 gap-1.5 pt-1">
                <input id="input-open-min" type="number" step="0.1" placeholder="Min $" oninput="onCustomRangeInput('open')" class="w-full bg-slate-900 border border-slate-800 rounded px-2 py-1 text-xs text-white focus:outline-none focus:border-emerald-500">
                <input id="input-open-max" type="number" step="0.1" placeholder="Max $" oninput="onCustomRangeInput('open')" class="w-full bg-slate-900 border border-slate-800 rounded px-2 py-1 text-xs text-white focus:outline-none focus:border-emerald-500">
              </div>
            </div>

            <!-- 2. Pre-Market Gap % -->
            <div class="bg-slate-950/80 border border-slate-800/90 rounded-xl p-3 space-y-2">
              <div class="flex items-center justify-between">
                <span class="text-xs font-bold text-slate-300 flex items-center gap-1"><span>🚀</span> PM Gap %</span>
                <span class="text-[10px] text-slate-500 font-mono">Moderate vs Extreme</span>
              </div>
              <div class="flex flex-wrap gap-1" id="tier-gap-btns">
                <button type="button" onclick="setTierFilter('gap', 'all')" id="btn-gap-all" class="tier-btn-gap px-2 py-1 rounded text-[11px] font-semibold bg-emerald-500/20 text-emerald-400 border border-emerald-500/30">All</button>
                <button type="button" onclick="setTierFilter('gap', 'mod')" id="btn-gap-mod" class="tier-btn-gap px-2 py-1 rounded text-[11px] font-semibold bg-slate-900 text-slate-400 border border-slate-800 hover:text-white">10% - 50%</button>
                <button type="button" onclick="setTierFilter('gap', 'strong')" id="btn-gap-strong" class="tier-btn-gap px-2 py-1 rounded text-[11px] font-semibold bg-slate-900 text-slate-400 border border-slate-800 hover:text-white">50% - 100%</button>
                <button type="button" onclick="setTierFilter('gap', 'extreme')" id="btn-gap-extreme" class="tier-btn-gap px-2 py-1 rounded text-[11px] font-semibold bg-slate-900 text-slate-400 border border-slate-800 hover:text-white">&gt; 100%</button>
              </div>
              <div class="grid grid-cols-2 gap-1.5 pt-1">
                <input id="input-gap-min" type="number" step="1" placeholder="Min %" oninput="onCustomRangeInput('gap')" class="w-full bg-slate-900 border border-slate-800 rounded px-2 py-1 text-xs text-white focus:outline-none focus:border-emerald-500">
                <input id="input-gap-max" type="number" step="1" placeholder="Max %" oninput="onCustomRangeInput('gap')" class="w-full bg-slate-900 border border-slate-800 rounded px-2 py-1 text-xs text-white focus:outline-none focus:border-emerald-500">
              </div>
            </div>

            <!-- 3. Float Turnover (x) -->
            <div class="bg-slate-950/80 border border-slate-800/90 rounded-xl p-3 space-y-2">
              <div class="flex items-center justify-between">
                <span class="text-xs font-bold text-slate-300 flex items-center gap-1"><span>🔄</span> Float Turnover</span>
                <span class="text-[10px] text-slate-500 font-mono">Velocity</span>
              </div>
              <div class="flex flex-wrap gap-1" id="tier-turn-btns">
                <button type="button" onclick="setTierFilter('turn', 'all')" id="btn-turn-all" class="tier-btn-turn px-2 py-1 rounded text-[11px] font-semibold bg-emerald-500/20 text-emerald-400 border border-emerald-500/30">All</button>
                <button type="button" onclick="setTierFilter('turn', 'low')" id="btn-turn-low" class="tier-btn-turn px-2 py-1 rounded text-[11px] font-semibold bg-slate-900 text-slate-400 border border-slate-800 hover:text-white">&lt; 20x</button>
                <button type="button" onclick="setTierFilter('turn', 'mid')" id="btn-turn-mid" class="tier-btn-turn px-2 py-1 rounded text-[11px] font-semibold bg-slate-900 text-slate-400 border border-slate-800 hover:text-white">20x - 100x</button>
                <button type="button" onclick="setTierFilter('turn', 'high')" id="btn-turn-high" class="tier-btn-turn px-2 py-1 rounded text-[11px] font-semibold bg-slate-900 text-slate-400 border border-slate-800 hover:text-white">&gt; 100x</button>
              </div>
              <div class="grid grid-cols-2 gap-1.5 pt-1">
                <input id="input-turn-min" type="number" step="1" placeholder="Min x" oninput="onCustomRangeInput('turn')" class="w-full bg-slate-900 border border-slate-800 rounded px-2 py-1 text-xs text-white focus:outline-none focus:border-emerald-500">
                <input id="input-turn-max" type="number" step="1" placeholder="Max x" oninput="onCustomRangeInput('turn')" class="w-full bg-slate-900 border border-slate-800 rounded px-2 py-1 text-xs text-white focus:outline-none focus:border-emerald-500">
              </div>
            </div>

            <!-- 4. Day Volume (M) -->
            <div class="bg-slate-950/80 border border-slate-800/90 rounded-xl p-3 space-y-2">
              <div class="flex items-center justify-between">
                <span class="text-xs font-bold text-slate-300 flex items-center gap-1"><span>📈</span> Day Volume (M)</span>
                <span class="text-[10px] text-slate-500 font-mono">Participation</span>
              </div>
              <div class="flex flex-wrap gap-1" id="tier-vol-btns">
                <button type="button" onclick="setTierFilter('vol', 'all')" id="btn-vol-all" class="tier-btn-vol px-2 py-1 rounded text-[11px] font-semibold bg-emerald-500/20 text-emerald-400 border border-emerald-500/30">All</button>
                <button type="button" onclick="setTierFilter('vol', 'low')" id="btn-vol-low" class="tier-btn-vol px-2 py-1 rounded text-[11px] font-semibold bg-slate-900 text-slate-400 border border-slate-800 hover:text-white">&lt; 25M</button>
                <button type="button" onclick="setTierFilter('vol', 'mid')" id="btn-vol-mid" class="tier-btn-vol px-2 py-1 rounded text-[11px] font-semibold bg-slate-900 text-slate-400 border border-slate-800 hover:text-white">25M - 100M</button>
                <button type="button" onclick="setTierFilter('vol', 'high')" id="btn-vol-high" class="tier-btn-vol px-2 py-1 rounded text-[11px] font-semibold bg-slate-900 text-slate-400 border border-slate-800 hover:text-white">&gt; 100M</button>
              </div>
              <div class="grid grid-cols-2 gap-1.5 pt-1">
                <input id="input-vol-min" type="number" step="5" placeholder="Min M" oninput="onCustomRangeInput('vol')" class="w-full bg-slate-900 border border-slate-800 rounded px-2 py-1 text-xs text-white focus:outline-none focus:border-emerald-500">
                <input id="input-vol-max" type="number" step="5" placeholder="Max M" oninput="onCustomRangeInput('vol')" class="w-full bg-slate-900 border border-slate-800 rounded px-2 py-1 text-xs text-white focus:outline-none focus:border-emerald-500">
              </div>
            </div>

          </div>
        </div>
      </div>

      <!-- 3. Dynamic Multidimensional Pivot Table & 4. Interactive Scatter Explorer (Features 3 & 4) -->
      <div class="grid grid-cols-1 xl:grid-cols-12 gap-6">
        
        <!-- Left 7 Cols: Parameter Impact Pivot Table -->
        <div class="xl:col-span-7 bg-slate-900 border border-slate-800 rounded-2xl p-5 shadow-xl flex flex-col justify-between space-y-4">
          <div>
            <div class="flex flex-wrap items-center justify-between gap-3 pb-3 border-b border-slate-800">
              <div>
                <h3 class="text-sm font-extrabold text-white flex items-center gap-2">
                  <span>📊</span> Parameter Impact Pivot Table
                </h3>
                <p class="text-xs text-slate-400 mt-0.5">Statistical breakdown of breakout rates, turnover, runs, and simulated realized returns.</p>
              </div>
              <span id="pivot-total-badge" class="px-2 py-0.5 rounded text-[10px] font-bold bg-slate-950 text-slate-300 border border-slate-800">29 Stocks</span>
            </div>

            <!-- Group By Dimension Selector -->
            <div class="mt-3.5">
              <label class="block text-[11px] font-bold uppercase tracking-wider text-slate-400 mb-2">Group By Dimension:</label>
              <div class="flex flex-wrap gap-1.5" id="pivot-dimension-btns">
                <button type="button" onclick="setPivotDimension('price')" id="pdim-price" class="pdim-btn px-2.5 py-1.5 rounded-lg text-xs font-bold transition-all bg-emerald-500/20 text-emerald-400 border border-emerald-500/30">
                  Share Price Tiers
                </button>
                <button type="button" onclick="setPivotDimension('gap')" id="pdim-gap" class="pdim-btn px-2.5 py-1.5 rounded-lg text-xs font-bold transition-all text-slate-400 hover:text-white border border-slate-800 bg-slate-950">
                  Pre-Market Gap Tiers
                </button>
                <button type="button" onclick="setPivotDimension('turnover')" id="pdim-turnover" class="pdim-btn px-2.5 py-1.5 rounded-lg text-xs font-bold transition-all text-slate-400 hover:text-white border border-slate-800 bg-slate-950">
                  Float Turnover Tiers
                </button>
                <button type="button" onclick="setPivotDimension('volume')" id="pdim-volume" class="pdim-btn px-2.5 py-1.5 rounded-lg text-xs font-bold transition-all text-slate-400 hover:text-white border border-slate-800 bg-slate-950">
                  Day Volume Tiers
                </button>
                <button type="button" onclick="setPivotDimension('catalyst')" id="pdim-catalyst" class="pdim-btn px-2.5 py-1.5 rounded-lg text-xs font-bold transition-all text-slate-400 hover:text-white border border-slate-800 bg-slate-950">
                  Catalyst Category
                </button>
                <button type="button" onclick="setPivotDimension('timing')" id="pdim-timing" class="pdim-btn px-2.5 py-1.5 rounded-lg text-xs font-bold transition-all text-slate-400 hover:text-white border border-slate-800 bg-slate-950">
                  Peak Timing Window
                </button>
              </div>
            </div>

            <!-- Pivot Data Grid Table -->
            <div class="overflow-x-auto mt-4 rounded-xl border border-slate-800/80">
              <table class="w-full text-left text-xs">
                <thead class="bg-slate-950/90 text-slate-400 text-[10px] font-bold uppercase tracking-wider border-b border-slate-800">
                  <tr>
                    <th class="py-2.5 px-3">Segment Bucket</th>
                    <th class="py-2.5 px-2 text-center">Count</th>
                    <th class="py-2.5 px-2 text-right">+2% Rate</th>
                    <th class="py-2.5 px-2 text-right">Avg PM Gap</th>
                    <th class="py-2.5 px-2 text-right">Avg Vol / Rot</th>
                    <th class="py-2.5 px-2 text-right">Avg Max Run</th>
                    <th class="py-2.5 px-2 text-right">Day Return</th>
                    <th class="py-2.5 px-2 text-right text-emerald-400">Sim Exit %</th>
                    <th class="py-2.5 px-2 text-right">Avg Fade</th>
                    <th class="py-2.5 px-2 text-center">Dump Rate</th>
                    <th class="py-2.5 px-2 text-center">Action</th>
                  </tr>
                </thead>
                <tbody id="pivot-table-body" class="divide-y divide-slate-800/60 font-mono text-slate-300 text-[11px]">
                  <!-- Rendered dynamically -->
                </tbody>
              </table>
            </div>
          </div>
          <div class="text-[11px] text-slate-500 pt-2 flex items-center justify-between border-t border-slate-800/60">
            <span>Click <strong>"🎯 Isolate"</strong> on any row to instantly filter the main stock table to that bucket.</span>
            <span id="pivot-footer-strat" class="text-emerald-400 font-mono font-semibold">Strategy: Hold Close</span>
          </div>
        </div>

        <!-- Right 5 Cols: Interactive Scatter Explorer -->
        <div class="xl:col-span-5 bg-slate-900 border border-slate-800 rounded-2xl p-5 shadow-xl flex flex-col justify-between space-y-3">
          <div>
            <div class="flex flex-wrap items-center justify-between gap-2 pb-3 border-b border-slate-800">
              <div>
                <h3 class="text-sm font-extrabold text-white flex items-center gap-2">
                  <span>📈</span> Interactive Scatter Explorer
                </h3>
                <p class="text-xs text-slate-400 mt-0.5">Explore multi-parameter relationships with reactive exit strategy simulations.</p>
              </div>
            </div>

            <!-- Axis Selectors -->
            <div class="grid grid-cols-2 gap-3 mt-3.5">
              <div>
                <label class="block text-[11px] font-bold uppercase tracking-wider text-slate-400 mb-1">X-Axis Parameter:</label>
                <select id="scatter-x" onchange="renderScatterChart()" class="w-full bg-slate-950 border border-slate-800 rounded-lg px-2.5 py-1.5 text-xs text-white focus:outline-none focus:border-sky-500">
                  <option value="open_price">09:30 Open Price ($)</option>
                  <option value="premarket_gap_pct">PM Gap %</option>
                  <option value="float_turnover_x">Float Turnover (x)</option>
                  <option value="day_volume">Day Volume (M)</option>
                  <option value="minutes_to_day_high">Peak Min</option>
                </select>
              </div>
              <div>
                <label class="block text-[11px] font-bold uppercase tracking-wider text-slate-400 mb-1">Y-Axis Outcome:</label>
                <select id="scatter-y" onchange="renderScatterChart()" class="w-full bg-slate-950 border border-slate-800 rounded-lg px-2.5 py-1.5 text-xs text-white focus:outline-none focus:border-emerald-500">
                  <option value="max_gain_pct">Max Run %</option>
                  <option value="day_return_pct">Actual Day Return %</option>
                  <option value="sim_exit_return_pct">Simulated Exit Return %</option>
                  <option value="first_30m_change_pct">30M %</option>
                  <option value="fade_from_high_pct">Fade %</option>
                </select>
              </div>
            </div>

            <!-- Plotly Container -->
            <div id="scatter-chart-container" class="w-full h-[320px] mt-2 rounded-xl overflow-hidden border border-slate-800/60 bg-slate-950/60">
              <!-- Plotly Scatter Graph -->
            </div>
          </div>
          <div class="text-[10px] text-slate-500 pt-1 flex items-center justify-between border-t border-slate-800/60">
            <span>Points: <span class="text-emerald-400 font-bold">● Hit >= +2%</span> vs <span class="text-rose-400 font-bold">◆ Failed +2%</span></span>
            <span class="text-slate-400">Hover dot for full metrics</span>
          </div>
        </div>

      </div>

      <!-- Main Data Grid Table -->
      <div class="bg-slate-900 border border-slate-800 rounded-2xl p-4 shadow-xl overflow-hidden">
        <div class="overflow-x-auto">
          <table class="w-full text-left text-xs text-slate-300">
            <thead class="bg-slate-950/80 text-slate-400 uppercase tracking-wider text-[11px] border-b border-slate-800">
              <tr>
                <th class="py-3 px-3 font-bold cursor-pointer whitespace-nowrap" onclick="sortTable('date')">Date ↕</th>
                <th class="py-3 px-3 font-bold cursor-pointer whitespace-nowrap" onclick="sortTable('ticker')">Ticker ↕</th>
                <th class="py-3 px-3 font-bold cursor-pointer whitespace-nowrap" onclick="sortTable('catalyst_category')">Company & Catalyst ↕</th>
                <th class="py-3 px-3 font-bold text-right cursor-pointer whitespace-nowrap" onclick="sortTable('premarket_gap_pct')">PM Gap ↕</th>
                <th class="py-3 px-3 font-bold text-right cursor-pointer whitespace-nowrap" onclick="sortTable('open_price')">09:30 Open ↕</th>
                <th class="py-3 px-3 font-bold text-right cursor-pointer whitespace-nowrap" onclick="sortTable('day_high')">Day High ↕</th>
                <th class="py-3 px-3 font-bold text-right cursor-pointer whitespace-nowrap" onclick="sortTable('max_gain_pct')">Max Run % ↕</th>
                <th class="py-3 px-3 font-bold text-right cursor-pointer whitespace-nowrap" onclick="sortTable('close_price')">16:00 Close ↕</th>
                <th class="py-3 px-3 font-bold text-right cursor-pointer whitespace-nowrap" onclick="sortTable('day_return_pct')">Day Return ↕</th>
                <th class="py-3 px-3 font-bold text-right cursor-pointer whitespace-nowrap text-emerald-400" onclick="sortTable('sim_exit_return_pct')">Sim Exit % ↕</th>
                <th class="py-3 px-3 font-bold text-right cursor-pointer whitespace-nowrap" onclick="sortTable('fade_from_high_pct')">Fade % ↕</th>
                <th class="py-3 px-3 font-bold text-right cursor-pointer whitespace-nowrap" onclick="sortTable('day_volume')">Day Volume ↕</th>
                <th class="py-3 px-3 font-bold text-right cursor-pointer whitespace-nowrap" onclick="sortTable('float_turnover_x')">Float Turnover ↕</th>
                <th class="py-3 px-3 font-bold text-right cursor-pointer whitespace-nowrap" onclick="sortTable('first_30m_change_pct')">30m % ↕</th>
                <th class="py-3 px-3 font-bold text-right cursor-pointer whitespace-nowrap" onclick="sortTable('minutes_to_day_high')">Peak Min ↕</th>
                <th class="py-3 px-3 font-bold text-center cursor-pointer whitespace-nowrap" onclick="sortTable('dump_warning')">Status ↕</th>
              </tr>
            </thead>
            <tbody id="history-table-body" class="divide-y divide-slate-800/60 font-mono">
              <!-- Dynamically populated -->
            </tbody>
          </table>
        </div>
      </div>
    </div>

    <!-- Footer Note -->
    <div class="text-center text-xs text-slate-500 pt-6 pb-8 border-t border-slate-800/60">
      Antigravity Automated Pre-Market Momentum Engine &bull; Generated from TradingView & yfinance APIs &bull; Educational & Research Purposes Only
    </div>
  </div>

  <!-- Historical Data & Application Logic -->
  <script>
    const RAW_HISTORY = {history_json_str};
    let currentSortCol = 'date';
    let sortAsc = false;
    let currentExitStrategy = 'close'; // 'close', 'scalp2', 'm30', 'tp25', 'tp50'
    let currentPivotDim = 'price'; // 'price', 'gap', 'turnover', 'volume', 'catalyst', 'timing'
    let timingFilterFn = null;

    const tierFilters = {{
      open: {{ min: null, max: null, preset: 'all' }},
      gap: {{ min: null, max: null, preset: 'all' }},
      turn: {{ min: null, max: null, preset: 'all' }},
      vol: {{ min: null, max: null, preset: 'all' }}
    }};

    function switchTab(tab) {{
      const radarBtn = document.getElementById("tab-btn-radar");
      const historyBtn = document.getElementById("tab-btn-history");
      const radarContent = document.getElementById("tab-content-radar");
      const historyContent = document.getElementById("tab-content-history");

      if (tab === 'radar') {{
        radarBtn.className = "px-5 py-2.5 rounded-lg text-xs md:text-sm font-bold transition-all bg-emerald-500/20 text-emerald-400 border border-emerald-500/30 shadow flex items-center gap-2";
        historyBtn.className = "px-5 py-2.5 rounded-lg text-xs md:text-sm font-bold transition-all text-slate-400 hover:text-white flex items-center gap-2";
        radarContent.classList.remove("hidden");
        historyContent.classList.add("hidden");
      }} else {{
        historyBtn.className = "px-5 py-2.5 rounded-lg text-xs md:text-sm font-bold transition-all bg-emerald-500/20 text-emerald-400 border border-emerald-500/30 shadow flex items-center gap-2";
        radarBtn.className = "px-5 py-2.5 rounded-lg text-xs md:text-sm font-bold transition-all text-slate-400 hover:text-white flex items-center gap-2";
        historyContent.classList.remove("hidden");
        radarContent.classList.add("hidden");
        renderHistoryTable();
        setTimeout(() => {{
          if (typeof Plotly !== 'undefined') {{
            Plotly.Plots.resize('scatter-chart-container');
          }}
        }}, 50);
      }}
    }}

    function getSimExitReturn(row, strategy) {{
      const strat = strategy || currentExitStrategy;
      const actualDayRet = (row.day_return_pct !== null && row.day_return_pct !== undefined) 
        ? row.day_return_pct 
        : ((row.close_price - row.open_price) / row.open_price * 100);
      const mg = (row.max_gain_pct !== null && row.max_gain_pct !== undefined) 
        ? row.max_gain_pct 
        : ((row.day_high - row.open_price) / row.open_price * 100);

      if (strat === 'scalp2') {{
        return mg >= 2.0 ? 2.0 : actualDayRet;
      }}
      if (strat === 'm30') {{
        return (row.first_30m_change_pct !== null && row.first_30m_change_pct !== undefined) 
          ? row.first_30m_change_pct 
          : actualDayRet;
      }}
      if (strat === 'tp25') {{
        return mg >= 25.0 ? 25.0 : actualDayRet;
      }}
      if (strat === 'tp50') {{
        return mg >= 50.0 ? 50.0 : actualDayRet;
      }}
      return actualDayRet; // 'close'
    }}

    function setExitStrategy(strat) {{
      currentExitStrategy = strat;
      
      const badgeEl = document.getElementById("strategy-badge");
      const descEl = document.getElementById("strategy-desc");
      const btnGroup = document.querySelectorAll(".strat-btn");

      btnGroup.forEach(btn => {{
        btn.className = "strat-btn px-3 py-1.5 rounded-lg text-xs font-bold transition-all text-slate-400 hover:text-white border border-transparent";
      }});

      const activeBtn = document.getElementById("strat-btn-" + strat);
      if (activeBtn) {{
        activeBtn.className = "strat-btn px-3 py-1.5 rounded-lg text-xs font-bold transition-all bg-emerald-500/20 text-emerald-400 border border-emerald-500/30 shadow";
      }}

      if (strat === 'close') {{
        if (badgeEl) badgeEl.innerText = "Actual Close";
        if (descEl) descEl.innerText = "Evaluates performance holding open position directly to 16:00 regular market close.";
      }} else if (strat === 'scalp2') {{
        if (badgeEl) badgeEl.innerText = "+2% Scalp Target";
        if (descEl) descEl.innerText = "Directly tests our 86.2% breakout rate: Realizes +2.0% if Max Run >= +2.0%, otherwise falls back to 16:00 close.";
      }} else if (strat === 'm30') {{
        if (badgeEl) badgeEl.innerText = "30-Min Exit";
        if (descEl) descEl.innerText = "Realizes return at the 10:00 AM mark (30M % column), locking in the initial morning push.";
      }} else if (strat === 'tp25') {{
        if (badgeEl) badgeEl.innerText = "Take Profit @ +25%";
        if (descEl) descEl.innerText = "Locks in +25.0% return on strong runners, otherwise falls back to 16:00 close.";
      }} else if (strat === 'tp50') {{
        if (badgeEl) badgeEl.innerText = "Take Profit @ +50%";
        if (descEl) descEl.innerText = "Locks in +50.0% return on super-runners, otherwise falls back to 16:00 close.";
      }}

      renderHistoryTable();
    }}

    function setTierFilter(type, preset) {{
      tierFilters[type].preset = preset;

      if (type === 'open') {{
        if (preset === 'all') {{ tierFilters.open.min = null; tierFilters.open.max = null; }}
        else if (preset === 'micro') {{ tierFilters.open.min = null; tierFilters.open.max = 2.0; }}
        else if (preset === 'sweet') {{ tierFilters.open.min = 2.0; tierFilters.open.max = 5.0; }}
        else if (preset === 'high') {{ tierFilters.open.min = 5.0; tierFilters.open.max = null; }}
        document.getElementById("input-open-min").value = tierFilters.open.min !== null ? tierFilters.open.min : "";
        document.getElementById("input-open-max").value = tierFilters.open.max !== null ? tierFilters.open.max : "";
      }} else if (type === 'gap') {{
        if (preset === 'all') {{ tierFilters.gap.min = null; tierFilters.gap.max = null; }}
        else if (preset === 'mod') {{ tierFilters.gap.min = 10.0; tierFilters.gap.max = 50.0; }}
        else if (preset === 'strong') {{ tierFilters.gap.min = 50.0; tierFilters.gap.max = 100.0; }}
        else if (preset === 'extreme') {{ tierFilters.gap.min = 100.0; tierFilters.gap.max = null; }}
        document.getElementById("input-gap-min").value = tierFilters.gap.min !== null ? tierFilters.gap.min : "";
        document.getElementById("input-gap-max").value = tierFilters.gap.max !== null ? tierFilters.gap.max : "";
      }} else if (type === 'turn') {{
        if (preset === 'all') {{ tierFilters.turn.min = null; tierFilters.turn.max = null; }}
        else if (preset === 'low') {{ tierFilters.turn.min = null; tierFilters.turn.max = 20.0; }}
        else if (preset === 'mid') {{ tierFilters.turn.min = 20.0; tierFilters.turn.max = 100.0; }}
        else if (preset === 'high') {{ tierFilters.turn.min = 100.0; tierFilters.turn.max = null; }}
        document.getElementById("input-turn-min").value = tierFilters.turn.min !== null ? tierFilters.turn.min : "";
        document.getElementById("input-turn-max").value = tierFilters.turn.max !== null ? tierFilters.turn.max : "";
      }} else if (type === 'vol') {{
        if (preset === 'all') {{ tierFilters.vol.min = null; tierFilters.vol.max = null; }}
        else if (preset === 'low') {{ tierFilters.vol.min = null; tierFilters.vol.max = 25.0; }}
        else if (preset === 'mid') {{ tierFilters.vol.min = 25.0; tierFilters.vol.max = 100.0; }}
        else if (preset === 'high') {{ tierFilters.vol.min = 100.0; tierFilters.vol.max = null; }}
        document.getElementById("input-vol-min").value = tierFilters.vol.min !== null ? tierFilters.vol.min : "";
        document.getElementById("input-vol-max").value = tierFilters.vol.max !== null ? tierFilters.vol.max : "";
      }}

      updateTierBtnsUI(type, preset);
      renderHistoryTable();
    }}

    function onCustomRangeInput(type) {{
      tierFilters[type].preset = 'custom';
      const minVal = parseFloat(document.getElementById(`input-${{type}}-min`).value);
      const maxVal = parseFloat(document.getElementById(`input-${{type}}-max`).value);

      tierFilters[type].min = !isNaN(minVal) ? minVal : null;
      tierFilters[type].max = !isNaN(maxVal) ? maxVal : null;

      updateTierBtnsUI(type, null);
      renderHistoryTable();
    }}

    function updateTierBtnsUI(type, activePreset) {{
      const btns = document.querySelectorAll(`.tier-btn-${{type}}`);
      btns.forEach(btn => {{
        btn.className = `tier-btn-${{type}} px-2 py-1 rounded text-[11px] font-semibold bg-slate-900 text-slate-400 border border-slate-800 hover:text-white`;
      }});

      if (activePreset) {{
        const activeBtn = document.getElementById(`btn-${{type}}-${{activePreset}}`);
        if (activeBtn) {{
          activeBtn.className = `tier-btn-${{type}} px-2 py-1 rounded text-[11px] font-semibold bg-emerald-500/20 text-emerald-400 border border-emerald-500/30`;
        }}
      }}
    }}

    function resetAllFilters() {{
      document.getElementById("filter-breakout").value = "All";
      document.getElementById("filter-dump").value = "All";
      if (document.getElementById("filter-cat")) document.getElementById("filter-cat").value = "All";
      if (document.getElementById("filter-min-run")) document.getElementById("filter-min-run").value = "0";
      document.getElementById("filter-search").value = "";
      timingFilterFn = null;

      ['open', 'gap', 'turn', 'vol'].forEach(t => {{
        tierFilters[t] = {{ min: null, max: null, preset: 'all' }};
        const minEl = document.getElementById(`input-${{t}}-min`);
        const maxEl = document.getElementById(`input-${{t}}-max`);
        if (minEl) minEl.value = "";
        if (maxEl) maxEl.value = "";
        updateTierBtnsUI(t, 'all');
      }});

      renderHistoryTable();
    }}

    function setPivotDimension(dim) {{
      currentPivotDim = dim;
      const btns = document.querySelectorAll(".pdim-btn");
      btns.forEach(b => {{
        b.className = "pdim-btn px-2.5 py-1.5 rounded-lg text-xs font-bold transition-all text-slate-400 hover:text-white border border-slate-800 bg-slate-950";
      }});
      const activeBtn = document.getElementById("pdim-" + dim);
      if (activeBtn) {{
        activeBtn.className = "pdim-btn px-2.5 py-1.5 rounded-lg text-xs font-bold transition-all bg-emerald-500/20 text-emerald-400 border border-emerald-500/30";
      }}
      renderPivotTable(getFilteredRecords());
    }}

    function getFilteredRecords() {{
      const breakoutFilter = document.getElementById("filter-breakout").value;
      const dumpFilter = document.getElementById("filter-dump").value;
      const catFilter = document.getElementById("filter-cat") ? document.getElementById("filter-cat").value : "All";
      const minRunFilter = document.getElementById("filter-min-run") ? parseFloat(document.getElementById("filter-min-run").value) : 0;
      const search = (document.getElementById("filter-search").value || "").trim().toLowerCase();

      return RAW_HISTORY.filter(row => {{
        if (breakoutFilter !== "All" && row.hit_plus_2pct !== breakoutFilter) return false;
        if (dumpFilter !== "All" && row.dump_warning !== dumpFilter) return false;
        if (catFilter !== "All" && row.catalyst_category !== catFilter) return false;
        
        const mg = row.max_gain_pct !== null && row.max_gain_pct !== undefined ? row.max_gain_pct : ((row.day_high - row.open_price) / row.open_price * 100);
        if (minRunFilter > 0 && mg < minRunFilter) return false;

        // Open Price
        if (tierFilters.open.min !== null && (row.open_price === null || row.open_price < tierFilters.open.min)) return false;
        if (tierFilters.open.max !== null && (row.open_price !== null && row.open_price > tierFilters.open.max)) return false;

        // Gap %
        if (tierFilters.gap.min !== null && (row.premarket_gap_pct === null || row.premarket_gap_pct < tierFilters.gap.min)) return false;
        if (tierFilters.gap.max !== null && (row.premarket_gap_pct !== null && row.premarket_gap_pct > tierFilters.gap.max)) return false;

        // Turnover
        if (tierFilters.turn.min !== null && (row.float_turnover_x === null || row.float_turnover_x < tierFilters.turn.min)) return false;
        if (tierFilters.turn.max !== null && (row.float_turnover_x !== null && row.float_turnover_x > tierFilters.turn.max)) return false;

        // Volume
        const volM = (row.day_volume || 0) / 1e6;
        if (tierFilters.vol.min !== null && volM < tierFilters.vol.min) return false;
        if (tierFilters.vol.max !== null && volM > tierFilters.vol.max) return false;

        // Timing Filter if active
        if (timingFilterFn && !timingFilterFn(row)) return false;

        if (search) {{
          const t = (row.ticker || "").toLowerCase();
          const c = (row.company || "").toLowerCase();
          const cat = (row.catalyst_category || "").toLowerCase();
          if (!t.includes(search) && !c.includes(search) && !cat.includes(search)) return false;
        }}
        return true;
      }});
    }}

    function renderHistoryTable() {{
      const filtered = getFilteredRecords();

      // Sort
      filtered.sort((a, b) => {{
        let v1, v2;
        if (currentSortCol === 'sim_exit_return_pct') {{
          v1 = getSimExitReturn(a);
          v2 = getSimExitReturn(b);
        }} else {{
          v1 = a[currentSortCol];
          v2 = b[currentSortCol];
        }}

        if (v1 === null || v1 === undefined) v1 = 0;
        if (v2 === null || v2 === undefined) v2 = 0;
        if (typeof v1 === 'string') {{
          return sortAsc ? v1.localeCompare(v2) : v2.localeCompare(v1);
        }}
        if (v1 < v2) return sortAsc ? -1 : 1;
        if (v1 > v2) return sortAsc ? 1 : -1;
        return 0;
      }});

      // Update Top KPIs
      const total = filtered.length;
      const winCount = filtered.filter(r => r.hit_plus_2pct === "Yes").length;
      const dumpCount = filtered.filter(r => r.dump_warning === "CRITICAL DUMP").length;
      const winRate = total > 0 ? (winCount / total * 100).toFixed(1) : "0.0";
      const dumpRate = total > 0 ? (dumpCount / total * 100).toFixed(1) : "0.0";
      
      const sumMaxRun = filtered.reduce((acc, r) => acc + (r.max_gain_pct !== null && r.max_gain_pct !== undefined ? r.max_gain_pct : ((r.day_high - r.open_price) / r.open_price * 100)), 0);
      const avgMaxRun = total > 0 ? (sumMaxRun / total).toFixed(1) : "0.0";

      const turnoverRows = filtered.filter(r => r.float_turnover_x !== null && r.float_turnover_x !== undefined);
      const sumTurnover = turnoverRows.reduce((acc, r) => acc + r.float_turnover_x, 0);
      const avgTurnover = turnoverRows.length > 0 ? (sumTurnover / turnoverRows.length).toFixed(1) : "0.0";

      const sumActualRet = filtered.reduce((acc, r) => acc + (r.day_return_pct !== null && r.day_return_pct !== undefined ? r.day_return_pct : ((r.close_price - r.open_price) / r.open_price * 100)), 0);
      const avgActualRet = total > 0 ? (sumActualRet / total).toFixed(1) : "0.0";

      const sumSimRet = filtered.reduce((acc, r) => acc + getSimExitReturn(r), 0);
      const avgSimRet = total > 0 ? (sumSimRet / total).toFixed(1) : "0.0";

      document.getElementById("kpi-total").innerText = total;
      document.getElementById("kpi-breakout").innerText = winRate + "% (" + winCount + "/" + total + ")";
      if (document.getElementById("kpi-maxrun")) document.getElementById("kpi-maxrun").innerText = (avgMaxRun > 0 ? "+" : "") + avgMaxRun + "%";
      if (document.getElementById("kpi-turnover")) document.getElementById("kpi-turnover").innerText = avgTurnover + "x";

      if (currentExitStrategy === 'close') {{
        document.getElementById("kpi-dayreturn-title").innerText = "Avg Day Return";
        document.getElementById("kpi-dayreturn").innerText = (avgActualRet > 0 ? "+" : "") + avgActualRet + "%";
        document.getElementById("kpi-dayreturn-sub").innerText = "Hold to 16:00 Close";
      }} else {{
        const stratMap = {{ scalp2: "+2% Scalp", m30: "30-Min Exit", tp25: "+25% TP", tp50: "+50% TP" }};
        document.getElementById("kpi-dayreturn-title").innerText = "Avg Sim Realized %";
        document.getElementById("kpi-dayreturn").innerText = (avgSimRet > 0 ? "+" : "") + avgSimRet + "%";
        document.getElementById("kpi-dayreturn-sub").innerText = "vs Close: " + (avgActualRet > 0 ? "+" : "") + avgActualRet + "% (" + stratMap[currentExitStrategy] + ")";
      }}
      document.getElementById("kpi-dump").innerText = dumpRate + "% (" + dumpCount + ")";

      // Render Rows
      const tbody = document.getElementById("history-table-body");
      if (filtered.length === 0) {{
        tbody.innerHTML = '<tr><td colspan="16" class="py-8 text-center text-slate-500 italic font-sans">No historical gapper records match your selected parameters.</td></tr>';
      }} else {{
        tbody.innerHTML = filtered.map(r => {{
          const isDump = r.dump_warning === "CRITICAL DUMP";
          const dumpBadge = isDump 
            ? '<span class="dump-critical">🚨 DUMP</span>'
            : '<span class="dump-held">Held</span>';

          const mg = r.max_gain_pct !== null && r.max_gain_pct !== undefined ? r.max_gain_pct : ((r.day_high - r.open_price) / r.open_price * 100);
          const dayRet = r.day_return_pct !== null && r.day_return_pct !== undefined ? r.day_return_pct : ((r.close_price - r.open_price) / r.open_price * 100);
          const fade = r.fade_from_high_pct !== null && r.fade_from_high_pct !== undefined ? r.fade_from_high_pct : ((r.close_price - r.day_high) / r.day_high * 100);
          
          const m30 = r.first_30m_change_pct !== null ? (r.first_30m_change_pct > 0 ? "+" : "") + r.first_30m_change_pct.toFixed(1) + "%" : "-";
          const gap = r.premarket_gap_pct !== null ? "+" + r.premarket_gap_pct.toFixed(1) + "%" : "-";

          let dayVolStr = '-';
          if (r.day_volume) {{
            dayVolStr = r.day_volume >= 1e6 ? (r.day_volume / 1e6).toFixed(1) + 'M' : (r.day_volume / 1e3).toFixed(0) + 'k';
          }}
          const rotStr = r.float_turnover_x ? r.float_turnover_x + 'x' : '-';

          // Catalyst badge styling
          let catColor = 'bg-slate-800 text-slate-300 border-slate-700';
          if (r.catalyst_category === 'Biotech / Pharma') catColor = 'bg-emerald-500/15 text-emerald-400 border-emerald-500/30';
          else if (r.catalyst_category === 'AI / Tech / Hardware') catColor = 'bg-cyan-500/15 text-cyan-400 border-cyan-500/30';
          else if (r.catalyst_category === 'Crypto / Treasury') catColor = 'bg-amber-500/15 text-amber-400 border-amber-500/30';
          else if (r.catalyst_category === 'Compliance / Uplisting') catColor = 'bg-purple-500/15 text-purple-400 border-purple-500/30';
          else if (r.catalyst_category === 'Contract / Momentum') catColor = 'bg-blue-500/15 text-blue-400 border-blue-500/30';

          const maxRunClass = mg >= 50 
            ? 'text-emerald-300 font-black bg-emerald-500/20 px-1.5 py-0.5 rounded border border-emerald-500/40' 
            : (mg >= 15 ? 'text-emerald-400 font-bold' : (mg >= 2 ? 'text-emerald-500' : 'text-slate-400'));

          const dayRetClass = dayRet >= 0 ? 'text-emerald-400' : 'text-rose-400';
          const fadeClass = fade <= -40 ? 'text-rose-400 font-bold' : (fade <= -20 ? 'text-amber-400' : 'text-slate-300');

          // Simulated Exit Indicator
          const simRet = getSimExitReturn(r);
          let simBadge = '';
          if (currentExitStrategy === 'scalp2') {{
            if (mg >= 2.0) {{
              simBadge = '<span class="bg-emerald-500/20 text-emerald-300 font-black px-1.5 py-0.5 rounded border border-emerald-500/40 text-[11px]">🎯 +2.0%</span>';
            }} else {{
              simBadge = `<span class="${{dayRetClass}} font-medium">${{dayRet >= 0 ? '+' : ''}}${{dayRet.toFixed(1)}}%</span>`;
            }}
          }} else if (currentExitStrategy === 'm30') {{
            const m30Val = r.first_30m_change_pct !== null ? r.first_30m_change_pct : dayRet;
            const m30Class = m30Val >= 0 ? 'text-emerald-400 font-bold' : 'text-rose-400 font-bold';
            simBadge = `<span class="${{m30Class}} text-[11px]">⏱️ ${{m30Val >= 0 ? '+' : ''}}${{m30Val.toFixed(1)}}%</span>`;
          }} else if (currentExitStrategy === 'tp25') {{
            if (mg >= 25.0) {{
              simBadge = '<span class="bg-emerald-500/20 text-emerald-300 font-black px-1.5 py-0.5 rounded border border-emerald-500/40 text-[11px]">🎯 +25.0%</span>';
            }} else {{
              simBadge = `<span class="${{dayRetClass}} font-medium">${{dayRet >= 0 ? '+' : ''}}${{dayRet.toFixed(1)}}%</span>`;
            }}
          }} else if (currentExitStrategy === 'tp50') {{
            if (mg >= 50.0) {{
              simBadge = '<span class="bg-emerald-500/20 text-emerald-300 font-black px-1.5 py-0.5 rounded border border-emerald-500/40 text-[11px]">🎯 +50.0%</span>';
            }} else {{
              simBadge = `<span class="${{dayRetClass}} font-medium">${{dayRet >= 0 ? '+' : ''}}${{dayRet.toFixed(1)}}%</span>`;
            }}
          }} else {{
            simBadge = `<span class="${{dayRetClass}} font-medium">${{dayRet >= 0 ? '+' : ''}}${{dayRet.toFixed(1)}}%</span>`;
          }}

          return `
            <tr class="hover:bg-slate-800/40 transition-colors">
              <td class="py-2.5 px-3 text-slate-400 font-sans whitespace-nowrap">${{r.date || '-'}}</td>
              <td class="py-2.5 px-3 font-bold text-white font-sans">
                <a href="https://www.tradingview.com/symbols/${{r.ticker}}/" target="_blank" class="hover:text-sky-400 underline decoration-slate-600 underline-offset-2">${{r.ticker}}</a>
              </td>
              <td class="py-2.5 px-3 font-sans truncate max-w-[200px]">
                <div class="text-white truncate">${{r.company || '-'}}</div>
                <span class="inline-block px-1.5 py-0.2 rounded text-[10px] font-semibold border ${{catColor}} mt-0.5">${{r.catalyst_category || 'Momentum'}}</span>
              </td>
              <td class="py-2.5 px-3 text-right font-bold text-emerald-400 whitespace-nowrap">${{gap}}</td>
              <td class="py-2.5 px-3 text-right text-slate-200 whitespace-nowrap">${{r.open_price ? '$' + r.open_price.toFixed(2) : '-'}}</td>
              <td class="py-2.5 px-3 text-right font-bold text-white whitespace-nowrap">${{r.day_high ? '$' + r.day_high.toFixed(2) : '-'}}</td>
              <td class="py-2.5 px-3 text-right whitespace-nowrap font-mono">
                <span class="${{maxRunClass}}">+${{mg.toFixed(1)}}%${{mg >= 50 ? ' 🔥' : ''}}</span>
              </td>
              <td class="py-2.5 px-3 text-right text-slate-300 whitespace-nowrap">${{r.close_price ? '$' + r.close_price.toFixed(2) : '-'}}</td>
              <td class="py-2.5 px-3 text-right font-semibold whitespace-nowrap ${{dayRetClass}}">${{dayRet >= 0 ? '+' : ''}}${{dayRet.toFixed(1)}}%</td>
              <td class="py-2.5 px-3 text-right font-semibold whitespace-nowrap font-mono">${{simBadge}}</td>
              <td class="py-2.5 px-3 text-right whitespace-nowrap ${{fadeClass}}">${{fade.toFixed(1)}}%</td>
              <td class="py-2.5 px-3 text-right whitespace-nowrap font-sans font-bold text-white">${{dayVolStr}}</td>
              <td class="py-2.5 px-3 text-right whitespace-nowrap font-mono font-bold text-amber-400">${{rotStr}}</td>
              <td class="py-2.5 px-3 text-right font-semibold whitespace-nowrap ${{r.first_30m_change_pct >= 0 ? 'text-emerald-400' : 'text-rose-400'}}">${{m30}}</td>
              <td class="py-2.5 px-3 text-right text-slate-300 whitespace-nowrap">${{r.minutes_to_day_high !== null ? r.minutes_to_day_high + 'm' : '-'}}</td>
              <td class="py-2.5 px-3 text-center whitespace-nowrap">${{dumpBadge}}</td>
            </tr>
          `;
        }}).join("");
      }}

      // Refresh Pivot Table & Scatter Explorer
      renderPivotTable(filtered);
      renderScatterChart(filtered);
    }}

    function sortTable(col) {{
      if (currentSortCol === col) {{
        sortAsc = !sortAsc;
      }} else {{
        currentSortCol = col;
        sortAsc = false;
      }}
      renderHistoryTable();
    }}

    function renderPivotTable(filtered) {{
      let buckets = [];
      const total = filtered.length;

      if (currentPivotDim === 'price') {{
        buckets = [
          {{ name: "< $2.00 (Micro)", key: 'micro', filterFn: r => r.open_price < 2.0 }},
          {{ name: "$2.00 - $5.00 (Sweet Spot)", key: 'sweet', filterFn: r => r.open_price >= 2.0 && r.open_price <= 5.0 }},
          {{ name: "> $5.00 (Mid/High)", key: 'high', filterFn: r => r.open_price > 5.0 }}
        ];
      }} else if (currentPivotDim === 'gap') {{
        buckets = [
          {{ name: "+10% to +50% (Moderate)", key: 'mod', filterFn: r => r.premarket_gap_pct >= 10.0 && r.premarket_gap_pct <= 50.0 }},
          {{ name: "+50% to +100% (Strong)", key: 'strong', filterFn: r => r.premarket_gap_pct > 50.0 && r.premarket_gap_pct <= 100.0 }},
          {{ name: "> +100% (Extreme)", key: 'extreme', filterFn: r => r.premarket_gap_pct > 100.0 }}
        ];
      }} else if (currentPivotDim === 'turnover') {{
        buckets = [
          {{ name: "< 20x", key: 'low', filterFn: r => r.float_turnover_x < 20.0 }},
          {{ name: "20x - 50x", key: 't20_50', filterFn: r => r.float_turnover_x >= 20.0 && r.float_turnover_x <= 50.0 }},
          {{ name: "50x - 100x", key: 't50_100', filterFn: r => r.float_turnover_x > 50.0 && r.float_turnover_x <= 100.0 }},
          {{ name: "> 100x", key: 'high', filterFn: r => r.float_turnover_x > 100.0 }}
        ];
      }} else if (currentPivotDim === 'volume') {{
        buckets = [
          {{ name: "< 25M", key: 'low', filterFn: r => (r.day_volume / 1e6) < 25.0 }},
          {{ name: "25M - 100M", key: 'mid', filterFn: r => (r.day_volume / 1e6) >= 25.0 && (r.day_volume / 1e6) <= 100.0 }},
          {{ name: "> 100M", key: 'high', filterFn: r => (r.day_volume / 1e6) > 100.0 }}
        ];
      }} else if (currentPivotDim === 'catalyst') {{
        const cats = ["Biotech / Pharma", "AI / Tech / Hardware", "Contract / Momentum", "Crypto / Treasury", "Compliance / Uplisting"];
        buckets = cats.map(c => ({{
          name: c,
          key: c,
          filterFn: r => (r.catalyst_category || "") === c
        }}));
      }} else if (currentPivotDim === 'timing') {{
        buckets = [
          {{ name: "0 - 15m (Opening Spike)", key: 'spike', filterFn: r => r.minutes_to_day_high !== null && r.minutes_to_day_high <= 15 }},
          {{ name: "16 - 60m (Morning Session)", key: 'morning', filterFn: r => r.minutes_to_day_high > 15 && r.minutes_to_day_high <= 60 }},
          {{ name: "> 60m (Mid-Day / Late)", key: 'late', filterFn: r => r.minutes_to_day_high > 60 }}
        ];
      }}

      const tbody = document.getElementById("pivot-table-body");
      if (!tbody) return;

      tbody.innerHTML = buckets.map(b => {{
        const bRows = filtered.filter(b.filterFn);
        const n = bRows.length;
        if (n === 0) {{
          return `
            <tr class="hover:bg-slate-800/30 transition-colors opacity-40">
              <td class="py-2.5 px-3 font-semibold text-slate-400 whitespace-nowrap">${{b.name}}</td>
              <td class="py-2.5 px-2 text-center text-slate-500">0 (0.0%)</td>
              <td class="py-2.5 px-2 text-right text-slate-500">-</td>
              <td class="py-2.5 px-2 text-right text-slate-500">-</td>
              <td class="py-2.5 px-2 text-right text-slate-500">-</td>
              <td class="py-2.5 px-2 text-right text-slate-500">-</td>
              <td class="py-2.5 px-2 text-right text-slate-500">-</td>
              <td class="py-2.5 px-2 text-right text-slate-500">-</td>
              <td class="py-2.5 px-2 text-right text-slate-500">-</td>
              <td class="py-2.5 px-2 text-center text-slate-500">-</td>
              <td class="py-2.5 px-2 text-center text-slate-600">-</td>
            </tr>
          `;
        }}

        const share = total > 0 ? (n / total * 100).toFixed(1) : "0.0";
        const winCount = bRows.filter(r => r.hit_plus_2pct === "Yes").length;
        const winRate = (winCount / n * 100).toFixed(1);
        const dumpCount = bRows.filter(r => r.dump_warning === "CRITICAL DUMP").length;
        const dumpRate = (dumpCount / n * 100).toFixed(1);

        const avgGap = (bRows.reduce((acc, r) => acc + (r.premarket_gap_pct || 0), 0) / n).toFixed(1);
        const avgVolM = (bRows.reduce((acc, r) => acc + ((r.day_volume || 0) / 1e6), 0) / n).toFixed(1);
        const avgTurn = (bRows.reduce((acc, r) => acc + (r.float_turnover_x || 0), 0) / n).toFixed(1);
        const avgRun = (bRows.reduce((acc, r) => acc + (r.max_gain_pct || 0), 0) / n).toFixed(1);
        const avgRet = (bRows.reduce((acc, r) => acc + (r.day_return_pct || 0), 0) / n).toFixed(1);
        const avgSim = (bRows.reduce((acc, r) => acc + getSimExitReturn(r), 0) / n).toFixed(1);
        const avgFade = (bRows.reduce((acc, r) => acc + (r.fade_from_high_pct || 0), 0) / n).toFixed(1);

        const winClass = winRate >= 80 ? "text-emerald-400 font-bold" : (winRate >= 50 ? "text-emerald-500" : "text-amber-400");
        const retClass = avgRet >= 0 ? "text-emerald-400" : "text-rose-400";
        const simClass = avgSim >= 0 ? "text-emerald-300 font-bold" : "text-rose-400 font-bold";
        const dumpClass = dumpRate >= 30 ? "text-rose-400 font-bold" : (dumpRate > 0 ? "text-amber-400" : "text-emerald-400");

        return `
          <tr class="hover:bg-slate-800/40 transition-colors">
            <td class="py-2.5 px-3 font-semibold text-white whitespace-nowrap">${{b.name}}</td>
            <td class="py-2.5 px-2 text-center text-slate-300">${{n}} <span class="text-[10px] text-slate-500">(${{share}}%)</span></td>
            <td class="py-2.5 px-2 text-right ${{winClass}}">${{winRate}}%</td>
            <td class="py-2.5 px-2 text-right text-emerald-400">+${{avgGap}}%</td>
            <td class="py-2.5 px-2 text-right text-slate-300">${{avgVolM}}M / <span class="text-amber-400 font-bold">${{avgTurn}}x</span></td>
            <td class="py-2.5 px-2 text-right text-emerald-400 font-bold">+${{avgRun}}%</td>
            <td class="py-2.5 px-2 text-right ${{retClass}}">${{avgRet >= 0 ? '+' : ''}}${{avgRet}}%</td>
            <td class="py-2.5 px-2 text-right ${{simClass}}">${{avgSim >= 0 ? '+' : ''}}${{avgSim}}%</td>
            <td class="py-2.5 px-2 text-right text-slate-400">${{avgFade}}%</td>
            <td class="py-2.5 px-2 text-center ${{dumpClass}}">${{dumpRate}}%</td>
            <td class="py-2.5 px-2 text-center">
              <button type="button" onclick="isolateBucket('${{currentPivotDim}}', '${{b.key}}')" class="px-2 py-0.5 rounded text-[10px] font-bold bg-slate-800 hover:bg-emerald-500/20 text-slate-300 hover:text-emerald-400 border border-slate-700 hover:border-emerald-500/30 transition-all">
                🎯 Isolate
              </button>
            </td>
          </tr>
        `;
      }}).join("");

      document.getElementById("pivot-total-badge").innerText = total + " Stocks";
      const stratLabels = {{ close: "Hold Close", scalp2: "+2% Scalp", m30: "30-Min Exit", tp25: "+25% TP", tp50: "+50% TP" }};
      document.getElementById("pivot-footer-strat").innerText = "Strategy: " + stratLabels[currentExitStrategy];
    }}

    function isolateBucket(dim, key) {{
      if (dim === 'price') {{
        setTierFilter('open', key);
      }} else if (dim === 'gap') {{
        setTierFilter('gap', key);
      }} else if (dim === 'turnover') {{
        if (key === 't20_50') {{
          tierFilters.turn = {{ min: 20.0, max: 50.0, preset: 'custom' }};
          document.getElementById("input-turn-min").value = 20;
          document.getElementById("input-turn-max").value = 50;
          updateTierBtnsUI('turn', null);
          renderHistoryTable();
        }} else if (key === 't50_100') {{
          tierFilters.turn = {{ min: 50.0, max: 100.0, preset: 'custom' }};
          document.getElementById("input-turn-min").value = 50;
          document.getElementById("input-turn-max").value = 100;
          updateTierBtnsUI('turn', null);
          renderHistoryTable();
        }} else {{
          setTierFilter('turn', key);
        }}
      }} else if (dim === 'volume') {{
        setTierFilter('vol', key);
      }} else if (dim === 'catalyst') {{
        document.getElementById("filter-cat").value = key;
        renderHistoryTable();
      }} else if (dim === 'timing') {{
        if (key === 'spike') {{
          timingFilterFn = r => r.minutes_to_day_high !== null && r.minutes_to_day_high <= 15;
        }} else if (key === 'morning') {{
          timingFilterFn = r => r.minutes_to_day_high > 15 && r.minutes_to_day_high <= 60;
        }} else if (key === 'late') {{
          timingFilterFn = r => r.minutes_to_day_high > 60;
        }}
        renderHistoryTable();
      }}

      const tableEl = document.getElementById("history-table-body");
      if (tableEl) {{
        tableEl.scrollIntoView({{ behavior: 'smooth', block: 'center' }});
      }}
    }}

    function renderScatterChart(filteredData) {{
      const container = document.getElementById("scatter-chart-container");
      if (!container || typeof Plotly === 'undefined') return;

      const filtered = filteredData || getFilteredRecords();
      const xKey = document.getElementById("scatter-x").value;
      const yKey = document.getElementById("scatter-y").value;

      const xLabels = {{
        open_price: "09:30 Open Price ($)",
        premarket_gap_pct: "Pre-Market Gap %",
        float_turnover_x: "Float Turnover (x)",
        day_volume: "Day Volume (Millions)",
        minutes_to_day_high: "Peak Minute"
      }};

      const yLabels = {{
        max_gain_pct: "Max Run %",
        day_return_pct: "Actual Day Return %",
        sim_exit_return_pct: "Simulated Exit Return %",
        first_30m_change_pct: "30-Min Return %",
        fade_from_high_pct: "Fade from High %"
      }};

      function getXVal(r) {{
        if (xKey === 'day_volume') return (r.day_volume || 0) / 1e6;
        return r[xKey] !== null && r[xKey] !== undefined ? r[xKey] : 0;
      }}

      function getYVal(r) {{
        if (yKey === 'sim_exit_return_pct') return getSimExitReturn(r);
        return r[yKey] !== null && r[yKey] !== undefined ? r[yKey] : 0;
      }}

      const winRows = filtered.filter(r => r.hit_plus_2pct === "Yes");
      const loseRows = filtered.filter(r => r.hit_plus_2pct !== "Yes");

      function makeHover(rows) {{
        return rows.map(r => {{
          const xVal = getXVal(r);
          const yVal = getYVal(r);
          const simRet = getSimExitReturn(r);
          const xStr = typeof xVal === 'number' ? xVal.toFixed(2) : xVal;
          const yStr = typeof yVal === 'number' ? yVal.toFixed(1) : yVal;
          return `<b>${{r.ticker}}</b> (${{r.date}})<br>${{r.company || ''}}<br>Category: ${{r.catalyst_category || 'Momentum'}}<br>${{xLabels[xKey]}}: ${{xStr}}<br>${{yLabels[yKey]}}: ${{yStr}}%<br>Max Run: +${{(r.max_gain_pct||0).toFixed(1)}}% | Close Ret: ${{(r.day_return_pct||0).toFixed(1)}}%<br>Sim Realized (${{currentExitStrategy}}): ${{simRet >= 0 ? '+' : ''}}${{simRet.toFixed(1)}}%`;
        }});
      }}

      const traces = [
        {{
          name: '+2% Breakout (Yes)',
          x: winRows.map(getXVal),
          y: winRows.map(getYVal),
          text: makeHover(winRows),
          mode: 'markers',
          type: 'scatter',
          hoverinfo: 'text',
          marker: {{
            color: '#10b981',
            size: 9,
            line: {{ color: '#059669', width: 1.5 }},
            symbol: 'circle'
          }}
        }},
        {{
          name: 'Failed Breakout (No)',
          x: loseRows.map(getXVal),
          y: loseRows.map(getYVal),
          text: makeHover(loseRows),
          mode: 'markers',
          type: 'scatter',
          hoverinfo: 'text',
          marker: {{
            color: '#f43f5e',
            size: 9,
            line: {{ color: '#e11d48', width: 1.5 }},
            symbol: 'diamond'
          }}
        }}
      ];

      const layout = {{
        template: 'plotly_dark',
        paper_bgcolor: 'rgba(15, 23, 42, 0)',
        plot_bgcolor: 'rgba(15, 23, 42, 0.6)',
        margin: {{ l: 45, r: 20, t: 25, b: 45 }},
        xaxis: {{
          title: {{ text: xLabels[xKey], font: {{ color: '#94a3b8', size: 10 }} }},
          gridcolor: '#1e293b',
          tickfont: {{ color: '#94a3b8', size: 9 }},
          zerolinecolor: '#334155'
        }},
        yaxis: {{
          title: {{ text: yLabels[yKey], font: {{ color: '#94a3b8', size: 10 }} }},
          gridcolor: '#1e293b',
          tickfont: {{ color: '#94a3b8', size: 9 }},
          zerolinecolor: '#334155'
        }},
        legend: {{
          orientation: 'h',
          y: 1.15,
          x: 0,
          font: {{ color: '#cbd5e1', size: 10 }}
        }},
        hoverlabel: {{
          bgcolor: '#0f172a',
          bordercolor: '#334155',
          font: {{ family: 'ui-sans-serif, system-ui', size: 11, color: '#f8fafc' }}
        }}
      }};

      Plotly.react('scatter-chart-container', traces, layout, {{ responsive: true, displayModeBar: false }});
    }}

    function exportFilteredCSV() {{
      const filtered = getFilteredRecords();
      if (filtered.length === 0) return;

      const keys = Object.keys(filtered[0]);
      let csv = keys.join(",") + ",sim_exit_return_pct,exit_strategy_used\n";
      filtered.forEach(row => {{
        const simRet = getSimExitReturn(row);
        let line = keys.map(k => JSON.stringify(row[k] !== null ? row[k] : "")).join(",");
        line += `,${{simRet.toFixed(2)}},"${{currentExitStrategy}}"\n`;
        csv += line;
      }});

      const blob = new Blob([csv], {{ type: 'text/csv' }});
      const url = window.URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.setAttribute('href', url);
      a.setAttribute('download', `filtered_gappers_${{currentExitStrategy}}.csv`);
      a.click();
    }}

    function updateCountdown() {{
      const countdownEl = document.getElementById("market-countdown");
      const statusEl = document.getElementById("market-status");
      
      const now = new Date();
      const nyTimeStr = now.toLocaleString("en-US", {{ timeZone: "America/New_York" }});
      const nyNow = new Date(nyTimeStr);

      const day = nyNow.getDay();
      const nyYear = nyNow.getFullYear();
      const nyMonth = nyNow.getMonth();
      const nyDate = nyNow.getDate();

      const openTime = new Date(nyYear, nyMonth, nyDate, 9, 30, 0);
      const closeTime = new Date(nyYear, nyMonth, nyDate, 16, 0, 0);

      if (day === 0 || day === 6) {{
        countdownEl.innerText = "WEEKEND";
        statusEl.innerText = "Markets closed for the weekend";
        return;
      }}

      if (nyNow < openTime) {{
        const diff = openTime - nyNow;
        const hours = Math.floor(diff / (1000 * 60 * 60));
        const minutes = Math.floor((diff % (1000 * 60 * 60)) / (1000 * 60));
        const seconds = Math.floor((diff % (1000 * 60)) / 1000);
        countdownEl.innerText = 
          String(hours).padStart(2, '0') + ":" + 
          String(minutes).padStart(2, '0') + ":" + 
          String(seconds).padStart(2, '0');
        statusEl.innerText = "Pre-Market Session Active";
      }} else if (nyNow >= openTime && nyNow < closeTime) {{
        countdownEl.innerText = "OPEN";
        statusEl.innerText = "Regular Market Hours Active";
        countdownEl.className = "text-2xl font-black text-emerald-400 mt-1 font-mono";
      }} else {{
        countdownEl.innerText = "CLOSED";
        statusEl.innerText = "After-Hours Session Active";
        countdownEl.className = "text-2xl font-black text-slate-400 mt-1 font-mono";
      }}
    }}
    updateCountdown();
    setInterval(updateCountdown, 1000);
  </script>
</body>
</html>
"""

    with open(dashboard_output_file, "w", encoding="utf-8") as f:
        f.write(dashboard_html)
    print(f"[+] Enhanced HTML Dashboard generated successfully at: {dashboard_output_file}")

    index_file = project_root / "index.html"
    with open(index_file, "w", encoding="utf-8") as f:
        f.write(dashboard_html)
    nojekyll_file = project_root / ".nojekyll"
    if not nojekyll_file.exists():
        nojekyll_file.touch()
    print(f"[+] Synchronized dual-tab index.html for GitHub Pages at: {index_file}")

    # Generate premarket_summary.md briefing
    summary_md_file = reports_dir / "premarket_summary.md"
    generate_premarket_summary_md(records, known_catalysts, summary_md_file)

    if top_hist_df is not None and top_ticker:
        print(f"\n[*] Generating multi-session chart image for top leader #{top_ticker}...")
        generate_static_chart_image(top_ticker, top_company, top_hist_df, chart_image_file)
        print(f"[+] Saved chart image to: {chart_image_file}")

    # Sync to brain directory for artifact viewing if present
    gemini_brain = Path.home() / ".gemini" / "antigravity" / "brain"
    if gemini_brain.exists():
        subdirs = [d for d in gemini_brain.iterdir() if d.is_dir() and not d.name.startswith(".")]
        if subdirs:
            # Sort by modification time descending to target recent active sessions
            subdirs.sort(key=lambda d: d.stat().st_mtime, reverse=True)
            for target_brain in subdirs[:3]:
                try:
                    shutil.copyfile(dashboard_output_file, target_brain / "dashboard.html")
                    shutil.copyfile(summary_md_file, target_brain / "premarket_summary.md")
                    if chart_image_file.exists():
                        shutil.copyfile(chart_image_file, target_brain / "chart.png")
                except Exception:
                    pass

    send_discord_digest(records, known_catalysts, chart_image_file)

    return records

if __name__ == "__main__":
    run_scanner()

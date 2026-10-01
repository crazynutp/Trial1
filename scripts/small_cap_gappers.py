#!/usr/bin/env python3
"""
Small-Cap Momentum Gappers Pre-Market Scanner, Interactive Dashboard & Discord Digest
- Queries TradingView screener for small-cap momentum gappers
- Pulls extended-hours intraday price/volume data via yfinance
- Generates dual-panel Plotly charts with session shading for ./reports/dashboard.html
- Generates high-resolution multi-session candlestick chart image (reports/chart.png)
- Dispatches rich Discord notification digest with embedded chart via multipart upload
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
matplotlib.use("Agg")  # Non-interactive backend
import matplotlib.pyplot as plt
import mplfinance as mpf
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import plotly.offline
from tradingview_screener import Query, col

# Default Discord Webhook URL (can be overridden via DISCORD_WEBHOOK_URL env var)
DEFAULT_DISCORD_WEBHOOK_URL = (
    "https://discord.com/api/webhooks/1555320088775626822/j-BYtUyCo535BXEg5hjxZjH7U_yePC9sxv249KR8vTxgKa52sqdKz7ywN93BHYcLB_qE"
)

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
    """Fetches recent news headlines via Google News RSS as an automated fallback."""
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
    """
    Constructs an interactive Plotly chart for the HTML dashboard:
    - Top panel: Candlesticks, 20 SMA, Pre-Market visual session shading
    - Bottom panel: Volume bars colored green/red matching candle direction
    """
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
    """
    Renders a high-resolution dark-theme candlestick + volume PNG chart
    with 20 SMA and pre-market session visual shading for Discord attachment.
    """
    if hist_df is None or hist_df.empty:
        return False

    df = hist_df.copy()
    if df.index.tz is None:
        df.index = df.index.tz_localize("America/New_York")
    else:
        df.index = df.index.tz_convert("America/New_York")

    # Retain the last 85 bars for crisp mobile & desktop readability
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

    # Add pre-market session shading
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
    """
    Dispatches the pre-market momentum digest to the configured Discord webhook:
    - Content header: ☀️ **Pre-Market Momentum Digest**
    - Embeds for top detected gappers (up to 3)
    - Full multi-session candlestick + volume chart attached via multipart upload
    """
    webhook_url = os.environ.get("DISCORD_WEBHOOK_URL", DEFAULT_DISCORD_WEBHOOK_URL)
    if not webhook_url:
        print("[!] No Discord webhook configured. Skipping notification.")
        return False

    print(f"\n[*] Preparing Discord webhook notification to: {webhook_url[:55]}...")

    if not records:
        payload = {
            "content": "☀️ **Pre-Market Momentum Digest**\n*No securities currently meet the momentum gapper criteria.*",
        }
        r = requests.post(webhook_url, json=payload, timeout=10)
        print(f"[+] Discord ping sent (status {r.status_code})")
        return True

    # Color palette for ranks: #1 Emerald, #2 Sky Blue, #3 Amber
    embed_colors = [1096065, 3447003, 16101131]
    embeds = []

    # Process up to 3 gappers
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
            ],
            "footer": {"text": "Antigravity Pre-Market Momentum Engine • TradingView & yfinance"},
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

        # Attach chart image to the #1 leader embed
        if idx == 0 and chart_image_path and Path(chart_image_path).exists():
            embed["image"] = {"url": "attachment://chart.png"}

        embeds.append(embed)

    payload = {
        "content": "☀️ **Pre-Market Momentum Digest**",
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

def run_scanner():
    script_dir = Path(__file__).resolve().parent
    project_root = script_dir.parent
    reports_dir = project_root / "reports"
    reports_dir.mkdir(parents=True, exist_ok=True)
    json_output_file = reports_dir / "gappers.json"
    dashboard_output_file = reports_dir / "dashboard.html"
    catalyst_file = reports_dir / "catalysts.json"
    chart_image_file = reports_dir / "chart.png"

    print("=" * 65)
    print("Executing TradingView Small-Cap Momentum Gappers Query...")
    print("=" * 65)

    # 1. Execute Screener Query
    query = (
        Query()
        .set_markets("america")
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
        .where(
            col("close").between(2.0, 20.0),
            col("market_cap_basic") <= 500_000_000,
            col("float_shares_outstanding") <= 20_000_000,
            col("relative_volume_10d_calc") > 5.0,
            col("premarket_volume") > 500_000,
            col("premarket_change") > 4.0,
            col("volume") > 500_000,
            col("change") > 4.0,
        )
        .order_by("premarket_change", ascending=False)
        .limit(5)
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

    # 2. Process each ticker, fetch yfinance intraday, build charts & intel
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

        # Build Plotly Chart for dashboard
        chart_html = build_candlestick_chart(ticker, hist_df)

        # Get or generate Catalyst Intelligence
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

        # Build Stock Card HTML
        card_html = f"""
        <div class="bg-slate-900/90 border border-slate-800 hover:border-slate-700/80 rounded-2xl p-6 shadow-xl backdrop-blur transition-all duration-200">
          <!-- Card Header -->
          <div class="flex flex-wrap items-center justify-between gap-4 pb-5 border-b border-slate-800/80">
            <div class="flex items-center gap-3">
              <div class="w-12 h-12 rounded-xl bg-gradient-to-tr from-emerald-500/20 to-cyan-500/20 border border-emerald-500/30 flex items-center justify-center font-bold text-lg text-emerald-400">
                {ticker}
              </div>
              <div>
                <div class="flex items-center gap-2">
                  <h3 class="text-xl font-bold text-white tracking-wide">{ticker}</h3>
                  <a href="https://www.tradingview.com/symbols/{ticker}/" target="_blank" class="text-xs text-sky-400 hover:text-sky-300 underline font-medium">TradingView ↗</a>
                </div>
                <p class="text-xs text-slate-400">{company}</p>
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

          <!-- Key Stats Grid -->
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

          <!-- Candlestick + Volume Chart -->
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

          <!-- Layman Trading Intelligence Box -->
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

    # 3. Assemble Complete Dashboard HTML
    cards_section = "\n".join(stock_cards_html) if stock_cards_html else """
    <div class="bg-slate-900 border border-slate-800 rounded-2xl p-12 text-center text-slate-400">
      <p class="text-lg font-semibold text-slate-300">No small-cap securities meet the momentum gapper criteria at this scan time.</p>
      <p class="text-sm mt-1">Check back during active pre-market hours (8:00 AM - 9:30 AM EST).</p>
    </div>
    """

    plotly_js_bundle = plotly.offline.get_plotlyjs()

    dashboard_html = f"""<!DOCTYPE html>
<html lang="en" class="dark">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Pre-Market Momentum Gappers Radar</title>
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
  </style>
</head>
<body class="p-4 md:p-8 antialiased min-h-screen">
  <div class="max-w-7xl mx-auto space-y-6">

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
          <h1 class="text-2xl md:text-3xl font-extrabold text-white tracking-tight">Small-Cap Momentum Gappers</h1>
          <p class="text-sm text-slate-400 mt-1 max-w-2xl">
            Pre-market screener tracking low-float (&le; 20M), micro/small-cap (&le; $500M) stocks with heavy relative volume surges (&gt;5.0x) and gap-up momentum.
          </p>
          
          <!-- Filter Criteria Chips -->
          <div class="flex flex-wrap gap-2 mt-4 text-[11px] font-medium text-slate-300">
            <span class="bg-slate-800/80 px-2.5 py-1 rounded-md border border-slate-700/60">Price: $2.00 - $20.00</span>
            <span class="bg-slate-800/80 px-2.5 py-1 rounded-md border border-slate-700/60">Market Cap: &le; $500M</span>
            <span class="bg-slate-800/80 px-2.5 py-1 rounded-md border border-slate-700/60">Float: &le; 20M</span>
            <span class="bg-slate-800/80 px-2.5 py-1 rounded-md border border-slate-700/60">RelVol: &gt; 5.0x</span>
            <span class="bg-slate-800/80 px-2.5 py-1 rounded-md border border-slate-700/60">PM Vol: &gt; 500k</span>
            <span class="bg-slate-800/80 px-2.5 py-1 rounded-md border border-slate-700/60">PM Gap: &gt; 4.0%</span>
          </div>
        </div>

        <!-- Scan Meta & Market Countdown -->
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

    <!-- Stock Cards Grid -->
    <div class="space-y-6">
      {cards_section}
    </div>

    <div class="text-center text-xs text-slate-500 pt-6 pb-8 border-t border-slate-800/60">
      Antigravity Automated Pre-Market Momentum Engine &bull; Generated from TradingView & yfinance APIs &bull; Educational & Research Purposes Only
    </div>
  </div>

  <script>
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

    # Sync to brain directory for artifact viewing
    brain_dir = Path(r"C:\Users\jagat\.gemini\antigravity\brain\ab5aab7e-cf1f-479d-824d-3c479f2e3d66")
    if brain_dir.exists():
        try:
            shutil.copyfile(dashboard_output_file, brain_dir / "dashboard.html")
        except Exception:
            pass

    # 4. Generate high-res chart image for the top gapper
    if top_hist_df is not None and top_ticker:
        print(f"\n[*] Generating multi-session chart image for top leader #{top_ticker}...")
        generate_static_chart_image(top_ticker, top_company, top_hist_df, chart_image_file)
        print(f"[+] Saved chart image to: {chart_image_file}")

    # 5. Send Discord Webhook Digest with attached chart
    send_discord_digest(records, known_catalysts, chart_image_file)

    return records

if __name__ == "__main__":
    run_scanner()

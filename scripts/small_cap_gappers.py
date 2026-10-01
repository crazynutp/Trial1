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

    # 1. Screener Query
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
              <span class="bg-slate-800/80 px-2.5 py-1 rounded-md border border-slate-700/60">Price: $2.00 - $20.00</span>
              <span class="bg-slate-800/80 px-2.5 py-1 rounded-md border border-slate-700/60">Market Cap: &le; $500M</span>
              <span class="bg-slate-800/80 px-2.5 py-1 rounded-md border border-slate-700/60">Float: &le; 20M</span>
              <span class="bg-slate-800/80 px-2.5 py-1 rounded-md border border-slate-700/60">RelVol: &gt; 5.0x</span>
              <span class="bg-slate-800/80 px-2.5 py-1 rounded-md border border-slate-700/60">PM Vol: &gt; 500k</span>
              <span class="bg-slate-800/80 px-2.5 py-1 rounded-md border border-slate-700/60">PM Gap: &gt; 4.0%</span>
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

      <!-- Stock Cards Grid -->
      <div class="space-y-6">
        {cards_section}
      </div>
    </div>

    <!-- ========================================================== -->
    <!-- TAB 2: FOLLOW-THROUGH HISTORICAL DATA GRID (STREAMLIT-LIKE) -->
    <!-- ========================================================== -->
    <div id="tab-content-history" class="space-y-6 hidden">
      <!-- Historical KPI Summary -->
      <div class="bg-slate-900 border border-slate-800 rounded-2xl p-6 shadow-xl">
        <div class="flex flex-wrap items-center justify-between gap-4 pb-4 border-b border-slate-800 mb-6">
          <div>
            <h2 class="text-2xl font-bold text-white tracking-tight">Follow-Through Execution Analytics</h2>
            <p class="text-xs text-slate-400 mt-0.5">End-of-day evaluation measuring morning breakout follow-through and dump frequency.</p>
          </div>
          <button onclick="exportFilteredCSV()" class="px-4 py-2 rounded-xl text-xs font-bold bg-slate-800 hover:bg-slate-700 text-slate-200 border border-slate-700 flex items-center gap-2 transition-all">
            <span>📥</span> Download Filtered CSV
          </button>
        </div>

        <div class="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-5 gap-3">
          <div class="bg-slate-950/80 border border-slate-800 rounded-xl p-4">
            <span class="text-[11px] uppercase tracking-wider font-semibold text-slate-400">Tracked Stocks</span>
            <p id="kpi-total" class="text-2xl font-extrabold text-white mt-1">0</p>
          </div>
          <div class="bg-slate-950/80 border border-slate-800 rounded-xl p-4">
            <span class="text-[11px] uppercase tracking-wider font-semibold text-slate-400">+2% Breakout Rate</span>
            <p id="kpi-breakout" class="text-2xl font-extrabold text-emerald-400 mt-1">0%</p>
          </div>
          <div class="bg-slate-950/80 border border-slate-800 rounded-xl p-4">
            <span class="text-[11px] uppercase tracking-wider font-semibold text-slate-400">Critical Dump Rate</span>
            <p id="kpi-dump" class="text-2xl font-extrabold text-rose-400 mt-1">0%</p>
          </div>
          <div class="bg-slate-950/80 border border-slate-800 rounded-xl p-4">
            <span class="text-[11px] uppercase tracking-wider font-semibold text-slate-400">Avg 30m Change</span>
            <p id="kpi-30m" class="text-2xl font-extrabold text-sky-400 mt-1">0.00%</p>
          </div>
          <div class="bg-slate-950/80 border border-slate-800 rounded-xl p-4">
            <span class="text-[11px] uppercase tracking-wider font-semibold text-slate-400">Avg Time to High</span>
            <p id="kpi-time" class="text-2xl font-extrabold text-amber-400 mt-1">0m</p>
          </div>
        </div>
      </div>

      <!-- Filter Controls (Streamlit-style) -->
      <div class="bg-slate-900 border border-slate-800 rounded-2xl p-6 shadow-xl space-y-4">
        <div class="text-xs font-bold uppercase tracking-wider text-slate-400 flex items-center gap-2">
          <span>🔍</span> Interactive Filter Controls
        </div>
        <div class="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
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
            <label class="block text-xs font-semibold text-slate-300 mb-1.5">Dump Warning Status</label>
            <select id="filter-dump" onchange="renderHistoryTable()" class="w-full bg-slate-950 border border-slate-800 rounded-lg px-3 py-2 text-xs text-white focus:outline-none focus:border-rose-500">
              <option value="All">All Dump Statuses</option>
              <option value="CRITICAL DUMP">🚨 CRITICAL DUMP Only</option>
              <option value="Held/Pushed">✅ Held / Pushed Only</option>
            </select>
          </div>

          <!-- Search Filter -->
          <div>
            <label class="block text-xs font-semibold text-slate-300 mb-1.5">Search Ticker / Company</label>
            <input id="filter-search" type="text" oninput="renderHistoryTable()" placeholder="e.g. NXL, VEEA..." class="w-full bg-slate-950 border border-slate-800 rounded-lg px-3 py-2 text-xs text-white focus:outline-none focus:border-sky-500">
          </div>

          <!-- Min Gap Slider -->
          <div>
            <div class="flex justify-between items-center mb-1.5">
              <label class="text-xs font-semibold text-slate-300">Min Pre-Market Gap %</label>
              <span id="gap-val" class="text-xs font-mono font-bold text-sky-400">0%</span>
            </div>
            <input id="filter-gap" type="range" min="0" max="150" value="0" step="5" oninput="document.getElementById('gap-val').innerText = this.value + '%'; renderHistoryTable()" class="w-full accent-sky-500">
          </div>
        </div>
      </div>

      <!-- Data Grid Table -->
      <div class="bg-slate-900 border border-slate-800 rounded-2xl p-4 shadow-xl overflow-hidden">
        <div class="overflow-x-auto">
          <table class="w-full text-left text-xs text-slate-300">
            <thead class="bg-slate-950/80 text-slate-400 uppercase tracking-wider text-[11px] border-b border-slate-800">
              <tr>
                <th class="py-3 px-4 font-bold cursor-pointer" onclick="sortTable('date')">Date ↕</th>
                <th class="py-3 px-4 font-bold cursor-pointer" onclick="sortTable('ticker')">Ticker ↕</th>
                <th class="py-3 px-4 font-bold">Company</th>
                <th class="py-3 px-4 font-bold text-right cursor-pointer" onclick="sortTable('premarket_gap_pct')">PM Gap ↕</th>
                <th class="py-3 px-4 font-bold text-right">09:30 Open</th>
                <th class="py-3 px-4 font-bold text-right cursor-pointer" onclick="sortTable('day_high')">Day High ↕</th>
                <th class="py-3 px-4 font-bold text-right">16:00 Close</th>
                <th class="py-3 px-4 font-bold text-right cursor-pointer" onclick="sortTable('first_30m_change_pct')">30m % ↕</th>
                <th class="py-3 px-4 font-bold text-center cursor-pointer" onclick="sortTable('hit_plus_2pct')">+2% Hit ↕</th>
                <th class="py-3 px-4 font-bold text-right cursor-pointer" onclick="sortTable('minutes_to_day_high')">Peak Min ↕</th>
                <th class="py-3 px-4 font-bold text-center">Dump Warning</th>
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
      }}
    }}

    function renderHistoryTable() {{
      const breakoutFilter = document.getElementById("filter-breakout").value;
      const dumpFilter = document.getElementById("filter-dump").value;
      const search = (document.getElementById("filter-search").value || "").trim().toLowerCase();
      const minGap = parseFloat(document.getElementById("filter-gap").value) || 0;

      let filtered = RAW_HISTORY.filter(row => {{
        if (breakoutFilter !== "All" && row.hit_plus_2pct !== breakoutFilter) return false;
        if (dumpFilter !== "All" && row.dump_warning !== dumpFilter) return false;
        if (minGap > 0 && (row.premarket_gap_pct || 0) < minGap) return false;
        if (search) {{
          const t = (row.ticker || "").toLowerCase();
          const c = (row.company || "").toLowerCase();
          if (!t.includes(search) && !c.includes(search)) return false;
        }}
        return true;
      }});

      // Sort
      filtered.sort((a, b) => {{
        let v1 = a[currentSortCol];
        let v2 = b[currentSortCol];
        if (v1 === null || v1 === undefined) v1 = 0;
        if (v2 === null || v2 === undefined) v2 = 0;
        if (v1 < v2) return sortAsc ? -1 : 1;
        if (v1 > v2) return sortAsc ? 1 : -1;
        return 0;
      }});

      // Update KPIs
      const total = filtered.length;
      const winCount = filtered.filter(r => r.hit_plus_2pct === "Yes").length;
      const dumpCount = filtered.filter(r => r.dump_warning === "CRITICAL DUMP").length;
      const winRate = total > 0 ? (winCount / total * 100).toFixed(1) : 0;
      const dumpRate = total > 0 ? (dumpCount / total * 100).toFixed(1) : 0;
      
      const sum30m = filtered.reduce((acc, r) => acc + (parseFloat(r.first_30m_change_pct) || 0), 0);
      const avg30m = total > 0 ? (sum30m / total).toFixed(2) : "0.00";

      const sumTime = filtered.reduce((acc, r) => acc + (parseFloat(r.minutes_to_day_high) || 0), 0);
      const avgTime = total > 0 ? Math.round(sumTime / total) : 0;

      document.getElementById("kpi-total").innerText = total;
      document.getElementById("kpi-breakout").innerText = winRate + "% (" + winCount + "/" + total + ")";
      document.getElementById("kpi-dump").innerText = dumpRate + "% (" + dumpCount + ")";
      document.getElementById("kpi-30m").innerText = (avg30m > 0 ? "+" : "") + avg30m + "%";
      document.getElementById("kpi-time").innerText = avgTime + "m";

      // Render Rows
      const tbody = document.getElementById("history-table-body");
      if (filtered.length === 0) {{
        tbody.innerHTML = '<tr><td colspan="11" class="py-8 text-center text-slate-500 italic font-sans">No historical gapper records match your selected filters.</td></tr>';
        return;
      }}

      tbody.innerHTML = filtered.map(r => {{
        const isDump = r.dump_warning === "CRITICAL DUMP";
        const dumpBadge = isDump 
          ? '<span class="dump-critical">🚨 CRITICAL DUMP</span>'
          : '<span class="dump-held">Held / Pushed</span>';

        const hitBadge = r.hit_plus_2pct === "Yes"
          ? '<span class="breakout-yes">Yes</span>'
          : '<span class="breakout-no">No</span>';

        const m30 = r.first_30m_change_pct !== null ? (r.first_30m_change_pct > 0 ? "+" : "") + r.first_30m_change_pct.toFixed(2) + "%" : "-";
        const gap = r.premarket_gap_pct !== null ? "+" + r.premarket_gap_pct.toFixed(1) + "%" : "-";

        return `
          <tr class="hover:bg-slate-800/40 transition-colors">
            <td class="py-3 px-4 text-slate-400 font-sans">${{r.date || '-'}}</td>
            <td class="py-3 px-4 font-bold text-white font-sans">${{r.ticker}}</td>
            <td class="py-3 px-4 text-slate-300 font-sans truncate max-w-[180px]">${{r.company || '-'}}</td>
            <td class="py-3 px-4 text-right font-bold text-emerald-400">${{gap}}</td>
            <td class="py-3 px-4 text-right text-slate-200">${{r.open_price ? '$' + r.open_price.toFixed(2) : '-'}}</td>
            <td class="py-3 px-4 text-right font-bold text-white">${{r.day_high ? '$' + r.day_high.toFixed(2) : '-'}}</td>
            <td class="py-3 px-4 text-right text-slate-300">${{r.close_price ? '$' + r.close_price.toFixed(2) : '-'}}</td>
            <td class="py-3 px-4 text-right font-semibold ${{r.first_30m_change_pct >= 0 ? 'text-emerald-400' : 'text-rose-400'}}">${{m30}}</td>
            <td class="py-3 px-4 text-center font-bold">${{hitBadge}}</td>
            <td class="py-3 px-4 text-right text-slate-300">${{r.minutes_to_day_high !== null ? r.minutes_to_day_high + 'm' : '-'}}</td>
            <td class="py-3 px-4 text-center">${{dumpBadge}}</td>
          </tr>
        `;
      }}).join("");
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

    function exportFilteredCSV() {{
      const breakoutFilter = document.getElementById("filter-breakout").value;
      const dumpFilter = document.getElementById("filter-dump").value;
      const search = (document.getElementById("filter-search").value || "").trim().toLowerCase();
      const minGap = parseFloat(document.getElementById("filter-gap").value) || 0;

      let filtered = RAW_HISTORY.filter(row => {{
        if (breakoutFilter !== "All" && row.hit_plus_2pct !== breakoutFilter) return false;
        if (dumpFilter !== "All" && row.dump_warning !== dumpFilter) return false;
        if (minGap > 0 && (row.premarket_gap_pct || 0) < minGap) return false;
        if (search) {{
          const t = (row.ticker || "").toLowerCase();
          const c = (row.company || "").toLowerCase();
          if (!t.includes(search) && !c.includes(search)) return false;
        }}
        return true;
      }});

      if (filtered.length === 0) return;
      const keys = Object.keys(filtered[0]);
      let csv = keys.join(",") + "\\n";
      filtered.forEach(row => {{
        csv += keys.map(k => JSON.stringify(row[k] !== null ? row[k] : "")).join(",") + "\\n";
      }});

      const blob = new Blob([csv], {{ type: 'text/csv' }});
      const url = window.URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.setAttribute('href', url);
      a.setAttribute('download', 'filtered_gappers_history.csv');
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

    brain_dir = Path(r"C:\Users\jagat\.gemini\antigravity\brain\ab5aab7e-cf1f-479d-824d-3c479f2e3d66")
    if brain_dir.exists():
        try:
            shutil.copyfile(dashboard_output_file, brain_dir / "dashboard.html")
        except Exception:
            pass

    if top_hist_df is not None and top_ticker:
        print(f"\n[*] Generating multi-session chart image for top leader #{top_ticker}...")
        generate_static_chart_image(top_ticker, top_company, top_hist_df, chart_image_file)
        print(f"[+] Saved chart image to: {chart_image_file}")

    send_discord_digest(records, known_catalysts, chart_image_file)

    return records

if __name__ == "__main__":
    run_scanner()

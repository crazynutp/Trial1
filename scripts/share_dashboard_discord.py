#!/usr/bin/env python3
"""
Share Interactive Dashboard Presentation to Discord Webhook
Posts an executive presentation of the interactive dashboard, follow-through analytics,
embedded candlestick chart image, and attaches the historical performance CSV.
"""

import json
import os
import sys
from pathlib import Path
import requests

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
WEBHOOK_URL = os.environ.get("DISCORD_WEBHOOK_URL", "")

def share_dashboard():
    project_root = Path(__file__).resolve().parent.parent
    reports_dir = project_root / "reports"
    data_dir = project_root / "data"
    chart_path = reports_dir / "chart.png"
    csv_path = data_dir / "gappers_history.csv"

    print(f"[*] Posting interactive dashboard presentation to Discord webhook...")

    payload = {
        "content": "☀️ **Small-Cap Momentum Radar & Follow-Through Interactive Dashboard**",
        "embeds": [
            {
                "title": "🖥️ Interactive Dashboard & System Overview",
                "description": (
                    "Live pre-market momentum radar with extended-hours Plotly candlestick charts, "
                    "accompanied by our market-close follow-through execution analytics."
                ),
                "color": 1096065,  # Emerald
                "fields": [
                    {
                        "name": "🌐 Streamlit Follow-Through App",
                        "value": "[http://localhost:8501](http://localhost:8501)\n`streamlit run dashboard.py`",
                        "inline": True,
                    },
                    {
                        "name": "📊 Breakout Win Rate (+2%)",
                        "value": "**100%** (3/3 Hit)",
                        "inline": True,
                    },
                    {
                        "name": "⚠️ Critical Dump Rate",
                        "value": "**0.0%** (0 Dumped)",
                        "inline": True,
                    },
                    {
                        "name": "⚡ Live Pre-Market HTML Radar",
                        "value": "Interactive HTML dashboard at `./reports/dashboard.html` with zoomable Plotly charts, 20 SMA, and session shading.",
                        "inline": False,
                    },
                    {
                        "name": "🎯 Core Filter Universe",
                        "value": "`Price: $2.00–$20.00` • `Float: <= 20M` • `Market Cap: <= $500M` • `RelVol: > 5.0x` • `PM Vol: > 500k`",
                        "inline": False,
                    },
                ],
            },
            {
                "title": "📋 Session Follow-Through & Execution Leaderboard",
                "color": 3447003,  # Blue
                "fields": [
                    {
                        "name": "🚀 1. NXL — Nexalin Technology (+104.9% Gap)",
                        "value": (
                            "• **09:30 Open:** $8.80 | **Day High:** $10.97 (+24.7% from open)\n"
                            "• **16:00 Close:** $7.53 | **First 30m Change:** +12.50%\n"
                            "• **Peak High:** 36 mins | **Warning Status:** `Held/Pushed`\n"
                            "• **Catalyst:** 10-year exclusive distribution & local manufacturing deal in 7 South American countries."
                        ),
                        "inline": False,
                    },
                    {
                        "name": "🔥 2. VEEA — Veea Inc. (+36.9% Gap)",
                        "value": (
                            "• **09:30 Open:** $2.98 | **Day High:** $4.08 (+36.9% from open)\n"
                            "• **16:00 Close:** $3.48 | **First 30m Change:** +9.23%\n"
                            "• **Peak High:** 356 mins | **Warning Status:** `Held/Pushed`\n"
                            "• **Catalyst:** Deployment agreement with TROLLEE for VeeaONE across 1,000 unattended stores."
                        ),
                        "inline": False,
                    },
                    {
                        "name": "⚡ 3. MEDS — DataMeds AI (+22.7% Gap)",
                        "value": (
                            "• **09:30 Open:** $3.92 | **Day High:** $4.35 (+11.0% from open)\n"
                            "• **16:00 Close:** $4.04 | **First 30m Change:** +4.78%\n"
                            "• **Peak High:** 20 mins | **Warning Status:** `Held/Pushed`\n"
                            "• **Catalyst:** Corexa Pharmacy monthly revenue surpassed $1.0M (+66% vs July) & OTC expansion."
                        ),
                        "inline": False,
                    },
                ],
                "image": {"url": "attachment://chart.png"},
                "footer": {"text": "Antigravity Autonomous Platform • Daemons: 08:30 EST Scan & 16:10 EST Follow-Through"},
            },
        ],
    }

    files = {}
    opened_files = []
    if chart_path.exists():
        f_chart = open(chart_path, "rb")
        opened_files.append(f_chart)
        files["files[0]"] = ("chart.png", f_chart, "image/png")

    if csv_path.exists():
        f_csv = open(csv_path, "rb")
        opened_files.append(f_csv)
        files["files[1]"] = ("gappers_history.csv", f_csv, "text/csv")

    try:
        res = requests.post(
            WEBHOOK_URL,
            data={"payload_json": json.dumps(payload)},
            files=files,
            timeout=20,
        )
        print(f"[+] Discord Webhook Response Code: {res.status_code}")
        if res.status_code in (200, 204):
            print("[+] Presentation payload successfully delivered to Discord!")
            return True
        else:
            print(f"[!] Discord Webhook error ({res.status_code}): {res.text}", file=sys.stderr)
            return False
    except Exception as e:
        print(f"[!] Request failed: {e}", file=sys.stderr)
        return False
    finally:
        for f in opened_files:
            f.close()

if __name__ == "__main__":
    share_dashboard()

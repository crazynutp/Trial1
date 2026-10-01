#!/usr/bin/env python3
"""
Multi-Day Historical Follow-Through Tracker
Runs after market close (16:10 EST) to evaluate the trading performance of morning gappers.
- Reads picks from ./reports/gappers.json
- Downloads 1-minute intraday data via yfinance across regular market hours (09:30 - 16:00 EST)
- Computes: open_price, first_30m_change_pct, hit_plus_2pct, minutes_to_day_high, dump_warning
- Appends historical performance metrics to ./data/gappers_history.csv
"""

import datetime
import json
import os
import sys
from pathlib import Path
import pandas as pd
import yfinance as yf

def track_follow_through():
    script_dir = Path(__file__).resolve().parent
    project_root = script_dir.parent
    reports_dir = project_root / "reports"
    data_dir = project_root / "data"
    data_dir.mkdir(parents=True, exist_ok=True)

    gappers_json_file = reports_dir / "gappers.json"
    history_csv_file = data_dir / "gappers_history.csv"

    print("=" * 65)
    print("Executing Small-Cap Follow-Through Performance Tracker...")
    print("=" * 65)

    if not gappers_json_file.exists():
        print(f"[!] Gappers file not found: {gappers_json_file}")
        sys.exit(0)

    with open(gappers_json_file, "r", encoding="utf-8") as f:
        gappers = json.load(f)

    if not gappers:
        print("[*] No gappers found in gappers.json. Nothing to track.")
        return

    print(f"[*] Analyzing follow-through for {len(gappers)} stock(s)...")

    new_rows = []

    for item in gappers:
        ticker = item.get("name") or item.get("ticker", "").split(":")[-1]
        company = item.get("description", ticker)
        pm_gap_pct = item.get("premarket_change", 0.0)
        pm_vol = item.get("premarket_volume", 0)
        float_shares = item.get("float_shares_outstanding")

        print(f"\n[*] Fetching 1-minute regular hours data for {ticker}...")
        try:
            # Fetch 1-minute intraday data without prepost to focus on regular hours
            hist = yf.Ticker(ticker).history(period="1d", interval="1m", prepost=False)
            if hist.empty:
                # Fallback to period='5d' and take the most recent day
                hist = yf.Ticker(ticker).history(period="5d", interval="1m", prepost=False)
        except Exception as e:
            print(f"[!] yfinance query failed for {ticker}: {e}")
            continue

        if hist.empty:
            print(f"[!] No intraday 1m data available for {ticker}. Skipping.")
            continue

        # Ensure index has timezone and convert to America/New_York
        if hist.index.tz is None:
            hist.index = hist.index.tz_localize("America/New_York")
        else:
            hist.index = hist.index.tz_convert("America/New_York")

        # Focus on regular market hours: 09:30 to 16:00
        most_recent_date = hist.index[-1].date()
        day_df = hist[
            (hist.index.date == most_recent_date)
            & (hist.index.time >= datetime.time(9, 30))
            & (hist.index.time <= datetime.time(16, 0))
        ].copy()

        if day_df.empty:
            day_df = hist[hist.index.date == most_recent_date].copy()

        if day_df.empty:
            print(f"[!] Could not isolate market session bars for {ticker}. Skipping.")
            continue

        # 1. 09:30 regular session open price
        open_price = float(day_df.iloc[0]["Open"])
        day_high = float(day_df["High"].max())
        day_low = float(day_df["Low"].min())
        close_price = float(day_df.iloc[-1]["Close"])
        session_date_str = most_recent_date.strftime("%Y-%m-%d")

        # 2. first_30m_change_pct (% change from 09:30 open to 10:00 close)
        first_30m_df = day_df[day_df.index.time <= datetime.time(10, 0)]
        if not first_30m_df.empty:
            close_1000 = float(first_30m_df.iloc[-1]["Close"])
        else:
            close_1000 = float(day_df.iloc[min(29, len(day_df) - 1)]["Close"])
        first_30m_change_pct = round(((close_1000 - open_price) / open_price) * 100, 2)

        # 3. hit_plus_2pct ("Yes" if high of the day was >= +2% above open price, otherwise "No")
        hit_plus_2pct = "Yes" if day_high >= (open_price * 1.02) else "No"

        # 4. minutes_to_day_high (minutes from 09:30 open until the peak high was printed)
        high_timestamp = day_df["High"].idxmax()
        open_timestamp = day_df.index[0]
        minutes_to_day_high = max(0, int((high_timestamp - open_timestamp).total_seconds() / 60))

        # 5. dump_warning ("CRITICAL DUMP" if stock never exceeded open price (+0.2% buffer), otherwise "Held/Pushed")
        dump_warning = "CRITICAL DUMP" if day_high <= (open_price * 1.002) else "Held/Pushed"

        row = {
            "date": session_date_str,
            "ticker": ticker,
            "company": company,
            "premarket_gap_pct": round(float(pm_gap_pct), 2),
            "premarket_volume": int(pm_vol) if pm_vol else None,
            "float_shares": int(float_shares) if float_shares else None,
            "open_price": round(open_price, 4),
            "day_high": round(day_high, 4),
            "day_low": round(day_low, 4),
            "close_price": round(close_price, 4),
            "first_30m_change_pct": first_30m_change_pct,
            "hit_plus_2pct": hit_plus_2pct,
            "minutes_to_day_high": minutes_to_day_high,
            "dump_warning": dump_warning,
        }
        new_rows.append(row)

        print(f"  -> {ticker}: Open=${open_price:.2f} | High=${day_high:.2f} | Close=${close_price:.2f}")
        print(f"     30m Change: {first_30m_change_pct:+.2f}% | +2% Breakout: {hit_plus_2pct} | Time to High: {minutes_to_day_high}m | Warning: {dump_warning}")

    if not new_rows:
        print("[!] No new follow-through records computed.")
        return

    new_df = pd.DataFrame(new_rows)

    # Append to existing history without duplicating (date, ticker)
    if history_csv_file.exists():
        existing_df = pd.read_csv(history_csv_file)
        # Drop previous record for the same date & ticker if re-run on the same day
        combined_df = pd.concat([existing_df, new_df], ignore_index=True)
        combined_df.drop_duplicates(subset=["date", "ticker"], keep="last", inplace=True)
    else:
        combined_df = new_df

    combined_df.sort_values(by=["date", "premarket_gap_pct"], ascending=[False, False], inplace=True)
    combined_df.to_csv(history_csv_file, index=False)
    print(f"\n[+] Successfully saved follow-through records to: {history_csv_file}")
    print(f"[+] Total historical records logged: {len(combined_df)}")

    # Send End-of-Day Follow-Through Summary to Discord
    webhook_url = os.environ.get(
        "DISCORD_WEBHOOK_URL",
        "https://discord.com/api/webhooks/1555320088775626822/j-BYtUyCo535BXEg5hjxZjH7U_yePC9sxv249KR8vTxgKa52sqdKz7ywN93BHYcLB_qE",
    )
    if webhook_url:
        try:
            import requests
            win_count = (new_df["hit_plus_2pct"] == "Yes").sum()
            dump_count = (new_df["dump_warning"] == "CRITICAL DUMP").sum()
            fields = []
            for _, r in new_df.iterrows():
                dump_icon = "🚨" if r["dump_warning"] == "CRITICAL DUMP" else "✅"
                hit_icon = "🎯" if r["hit_plus_2pct"] == "Yes" else "❌"
                fields.append(
                    {
                        "name": f"{r['ticker']} — {r['company']}",
                        "value": (
                            f"• Open: **${r['open_price']:.2f}** | Day High: **${r['day_high']:.2f}** | Close: **${r['close_price']:.2f}**\n"
                            f"• 30m Change: **{r['first_30m_change_pct']:+.2f}%** | Peak High: **{r['minutes_to_day_high']:.0f}m**\n"
                            f"• {hit_icon} +2% Breakout: **{r['hit_plus_2pct']}** | {dump_icon} Status: `{r['dump_warning']}`"
                        ),
                        "inline": False,
                    }
                )
            discord_payload = {
                "content": "🔔 **Market-Close Momentum Follow-Through Scorecard**",
                "embeds": [
                    {
                        "title": f"📊 Session Results ({most_recent_date.strftime('%Y-%m-%d')})",
                        "description": f"**Win Rate (+2% Breakout):** {win_count}/{len(new_df)} ({win_count/len(new_df)*100:.0f}%)\n**Critical Dumps:** {dump_count}/{len(new_df)}",
                        "color": 1096065 if dump_count == 0 else 16717380,
                        "fields": fields,
                        "footer": {"text": "Antigravity End-of-Day Follow-Through Engine"},
                    }
                ],
            }
            requests.post(webhook_url, json=discord_payload, timeout=10)
            print("[+] Dispatched follow-through scorecard to Discord webhook.")
        except Exception as e:
            print(f"[!] Warning: Failed to send Discord scorecard: {e}")

    return combined_df

if __name__ == "__main__":
    track_follow_through()

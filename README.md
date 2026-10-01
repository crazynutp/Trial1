# Small-Cap Momentum Gappers Scanner & Follow-Through Tracker

An automated trading intelligence system designed for low-float small-cap equities. It combines pre-market momentum scanning, 5-minute extended-hours Plotly candlestick charts, AI catalyst intelligence, automated Discord webhook alerts with chart attachments, and regular market follow-through performance tracking.

---

## 📁 Repository Structure

```text
├── .antigravity/schedules/            # Automated daemon schedule configurations
│   ├── premarket_gappers.json         # 08:30 EST Morning Scanner
│   └── follow_through_tracker.json    # 16:10 EST Market-Close Tracker
├── data/
│   └── gappers_history.csv            # Multi-day performance & breakout database
├── reports/
│   ├── catalysts.json                 # Catalyst & layman intelligence notes
│   └── premarket_summary.md           # Markdown briefing template
├── scripts/
│   ├── small_cap_gappers.py           # Core scanner, chart engine & Discord notifier
│   ├── track_follow_through.py        # Post-market 1m intraday breakout & dump analyzer
│   └── share_dashboard_discord.py     # On-demand Discord presentation dispatcher
├── dashboard.py                       # Interactive Streamlit follow-through UI
├── requirements.txt                   # Minimal Python dependencies
├── .env.example                       # Environment secrets template
└── .gitignore                         # Excludes ephemeral caches & heavy runtime files
```

---

## ⚡ Quick Start

### 1. Install Dependencies
```bash
pip install -r requirements.txt
```

### 2. Configure Environment (Optional)
Copy `.env.example` to `.env` and set your Discord webhook URL:
```bash
cp .env.example .env
```
*(Or export `DISCORD_WEBHOOK_URL` in your shell).*

---

## 🚀 Execution Commands

* **Run Pre-Market Momentum Scanner:**
  ```bash
  python scripts/small_cap_gappers.py
  ```
  *Queries TradingView, generates `./reports/dashboard.html` and `./reports/chart.png`, and delivers the Discord digest.*

* **Run Market-Close Follow-Through Tracker:**
  ```bash
  python scripts/track_follow_through.py
  ```
  *Evaluates the day's open-to-high performance, detects +2% breakouts and critical dumps, updates `data/gappers_history.csv`, and sends the market-close scorecard.*

* **Launch Interactive Streamlit Dashboard:**
  ```bash
  streamlit run dashboard.py
  ```
  *Opens the interactive historical data grid with bright-red dump warnings and sidebar filters at `http://localhost:8501`.*

---

## 🌐 Cloud Hosting (GitHub Actions + GitHub Pages)

* **Free 24/7 Automation:** You can add a GitHub Actions workflow (`.github/workflows/scanner.yml`) to run the scanner on GitHub's cloud runners Mon–Fri at 8:30 AM EST and 4:10 PM EST.
* **Open Dashboard from Discord:** By publishing `./reports/dashboard.html` to **GitHub Pages**, your Discord alerts can include a live public URL (e.g., `https://<username>.github.io/<repo>/`) that opens on any phone or desktop with one click.

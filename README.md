# StockScan — daily swing-trade scanner

A conservative technical-analysis advisory tool. Scans the Nifty 500 (India) and
S&P 500 (US) on daily charts, detects breakout patterns, and produces a report
with complete trade plans: entry, stop loss, target, support/resistance,
risk-reward and a confidence score.

Built with Claude (Cowork), August 2026. **Personal study tool — not investment
advice, not SEBI-registered research.**

## What's in here

```
engine/          pattern-detection + signal engine (pure pandas)
scan.py          run a scan:      python3 scan.py --market india
                 one stock:       python3 scan.py --market india --symbol RELIANCE
report.py        build the HTML report from scan results
pipeline/        nightly data updater (runs free on GitHub Actions)
.github/         the Actions schedule that runs the updater
data/            stock universe lists (auto-refreshed by the pipeline)
output/          scan results, reports, signals_log.csv (trade suggestion history)
```

## Data sources (all free)

- **India prices**: official NSE bhavcopy history mirrored daily at
  github.com/BennyThadikaran/eod2_data (cloned on demand, not stored here)
- **US prices**: written into `us_daily/` by the GitHub Actions pipeline every
  night after US close (Yahoo Finance via yfinance, 2-year rolling window)
- **Universe lists**: S&P 500 constituents + official NSE Nifty 500 list,
  refreshed by the same pipeline

## ONE-TIME SETUP (about 10 minutes)

This repo powers the automated daily scans. To activate:

1. Create a GitHub account at github.com if you don't have one (free).
2. Create a new **public** repository named `stockscan`
   (+ icon, top right → "New repository" → Public → Create).
3. Upload everything in this folder:
   - Easiest: install GitHub Desktop, clone your empty repo, copy these files
     in, commit, push. Or on the command line:
     `git init && git add -A && git commit -m init && git push <your-repo-url> main`
   - Web alternative: "Add file → Upload files" and drag the folder contents in
     (make sure the `.github` folder is included — enable hidden files).
4. On the repo page: Actions tab → enable workflows → open "Update market data"
   → "Run workflow" to do the first US data fill (takes ~10 min).
5. Tell Claude your repo URL (e.g. `github.com/yourname/stockscan`). Claude will
   switch the scheduled daily scans to boot from your repo — after that the whole
   system runs unattended: GitHub refreshes data nightly, Claude scans every
   morning and sends the report.

## How to act on a report

Every idea is conditional — nothing is a buy at market. Place a trigger/GTT
order at the entry price with the stop-loss attached in Groww / your broker.
If the entry doesn't trigger within 3 sessions, cancel it. Risk no more than
1-2% of capital on any single position.

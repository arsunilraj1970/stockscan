#!/usr/bin/env python3
"""Nightly data updater — runs on GitHub Actions (full internet access there).

Writes/refreshes:
  us_daily/<SYMBOL>.csv        2-year rolling daily OHLCV for every S&P 500 stock
  data/sp500_symbols.txt       current S&P 500 constituents
  data/nifty500_symbols.txt    current Nifty 500 constituents (official NSE list)
"""
import io
import os
import time
import urllib.request

import pandas as pd
import yfinance as yf

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
US_DIR = os.path.join(ROOT, "us_daily")
DATA = os.path.join(ROOT, "data")
os.makedirs(US_DIR, exist_ok=True)
os.makedirs(DATA, exist_ok=True)

UA = {"User-Agent": "Mozilla/5.0 (data updater for personal research)"}


def fetch(url):
    req = urllib.request.Request(url, headers=UA)
    return urllib.request.urlopen(req, timeout=30).read()


def refresh_sp500():
    csv = fetch("https://raw.githubusercontent.com/datasets/s-and-p-500-companies/main/data/constituents.csv")
    df = pd.read_csv(io.BytesIO(csv))
    syms = sorted(s.strip() for s in df["Symbol"].dropna())
    with open(os.path.join(DATA, "sp500_symbols.txt"), "w") as f:
        f.write("\n".join(syms))
    print(f"S&P 500 list: {len(syms)} symbols")
    return syms


def refresh_nifty500():
    try:
        csv = fetch("https://archives.nseindia.com/content/indices/ind_nifty500list.csv")
        df = pd.read_csv(io.BytesIO(csv))
        syms = sorted(s.strip() for s in df["Symbol"].dropna())
        if len(syms) > 400:
            with open(os.path.join(DATA, "nifty500_symbols.txt"), "w") as f:
                f.write("\n".join(syms))
            print(f"Nifty 500 list: {len(syms)} symbols")
    except Exception as e:  # NSE sometimes blocks non-browser clients; keep old list
        print("Nifty 500 refresh skipped:", e)


def update_us_prices(symbols):
    ok = fail = 0
    for i in range(0, len(symbols), 50):
        batch = symbols[i : i + 50]
        ytickers = [s.replace(".", "-") for s in batch]  # BRK.B -> BRK-B
        data = yf.download(ytickers, period="2y", interval="1d", auto_adjust=True,
                           group_by="ticker", progress=False, threads=True)
        for sym, yt in zip(batch, ytickers):
            try:
                df = data[yt].dropna() if len(batch) > 1 else data.dropna()
                if len(df) < 100:
                    fail += 1
                    continue
                out = df[["Open", "High", "Low", "Close", "Volume"]].round(4)
                out.index.name = "Date"
                out.to_csv(os.path.join(US_DIR, sym + ".csv"))
                ok += 1
            except Exception:
                fail += 1
        time.sleep(1)
    print(f"US prices: {ok} updated, {fail} failed")


if __name__ == "__main__":
    syms = refresh_sp500()
    refresh_nifty500()
    update_us_prices(syms)

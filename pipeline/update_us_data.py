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
import yfinance as yf  # noqa: F401

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


def _existing_last_date(sym):
    p = os.path.join(US_DIR, sym + ".csv")
    if not os.path.exists(p):
        return ""
    return open(p).read().rstrip("\n").split("\n")[-1].split(",")[0]


def _write_if_fresher(sym, df):
    """Never regress a file to older data."""
    if df is None or len(df) < 100:
        return False
    last_new = str(df.index[-1].date()) if hasattr(df.index[-1], "date") else str(df.index[-1])[:10]
    if last_new <= _existing_last_date(sym):
        return False
    out = df[["Open", "High", "Low", "Close", "Volume"]].round(4)
    out.index.name = "Date"
    out.to_csv(os.path.join(US_DIR, sym + ".csv"))
    return True


def _stooq_bulk_append(symbols):
    """Third fallback: stooq's single-file daily database (one request for the
    whole US market — immune to per-symbol rate limits). Appends the sessions
    it contains to files that lack them. Returns count of files freshened."""
    import zipfile
    try:
        blob = fetch("https://stooq.com/db/d/?b=d_us_txt")
        zf = zipfile.ZipFile(io.BytesIO(blob))
        rows = {}
        for name in zf.namelist():
            if not name.lower().endswith(".txt"):
                continue
            for line in zf.read(name).decode(errors="replace").splitlines():
                p = line.split(",")
                if len(p) < 9 or not p[0].upper().endswith(".US"):
                    continue
                tick = p[0].upper()[:-3].replace("-", ".")
                try:
                    d = f"{p[2][:4]}-{p[2][4:6]}-{p[2][6:8]}"
                    rows.setdefault(tick, []).append(
                        (d, float(p[4]), float(p[5]), float(p[6]), float(p[7]), int(float(p[8]))))
                except Exception:
                    continue
        touched = 0
        for sym in symbols:
            if sym not in rows:
                continue
            p = os.path.join(US_DIR, sym + ".csv")
            if not os.path.exists(p):
                continue
            txt = open(p).read().rstrip("\n")
            last = txt.split("\n")[-1].split(",")[0]
            add = sorted(r for r in rows[sym] if r[0] > last)
            if not add:
                continue
            with open(p, "a") as f:
                for d, o, h, l, c, v in add:
                    f.write(f"{d},{o},{h},{l},{c},{v}\n")
            touched += 1
        return touched
    except Exception as exc:
        print("stooq bulk fallback failed:", exc)
        return 0


def _stooq(sym):
    """Fallback source: stooq.com free daily CSV."""
    try:
        url = f"https://stooq.com/q/d/l/?s={sym.replace('.', '-').lower()}.us&i=d"
        df = pd.read_csv(io.BytesIO(fetch(url)), parse_dates=["Date"]).set_index("Date").tail(510)
        return df if {"Open", "High", "Low", "Close", "Volume"} <= set(df.columns) else None
    except Exception:
        return None


def update_us_prices(symbols):
    ok = fail = via_fallback = 0
    failed = []
    for i in range(0, len(symbols), 50):
        batch = symbols[i : i + 50]
        ytickers = [s.replace(".", "-") for s in batch]  # BRK.B -> BRK-B
        data = None
        for attempt in range(3):  # Yahoo rate-limits datacenter IPs sometimes
            try:
                data = yf.download(ytickers, period="2y", interval="1d", auto_adjust=True,
                                   group_by="ticker", progress=False, threads=True)
                if data is not None and len(data):
                    break
            except Exception:
                pass
            time.sleep(20 * (attempt + 1))
        for sym, yt in zip(batch, ytickers):
            try:
                df = data[yt].dropna() if (data is not None and len(batch) > 1) else (
                    data.dropna() if data is not None else None)
                if _write_if_fresher(sym, df):
                    ok += 1
                else:
                    failed.append(sym)
            except Exception:
                failed.append(sym)
        time.sleep(2)
    # fallback passes for anything Yahoo didn't freshen
    today = str(pd.Timestamp.utcnow().date())
    still = [s for s in failed if _existing_last_date(s) < today]
    bulk = _stooq_bulk_append(still) if len(still) > 25 else 0
    for sym in still[:40]:  # per-symbol fallback only for a few (rate-limited)
        if _existing_last_date(sym) >= today:
            continue
        if _write_if_fresher(sym, _stooq(sym)):
            via_fallback += 1
        time.sleep(0.5)
    fail = sum(1 for s in symbols if _existing_last_date(s) < today)
    print(f"US prices: {ok} via yahoo, bulk-appended {bulk}, {via_fallback} via per-symbol "
          f"fallback, {fail} not fresh today (may be fine if market hasn't closed)")


if __name__ == "__main__":
    syms = refresh_sp500()
    refresh_nifty500()
    update_us_prices(syms)

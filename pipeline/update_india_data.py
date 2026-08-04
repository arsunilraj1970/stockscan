#!/usr/bin/env python3
"""Daily India EOD updater — runs on GitHub Actions (full internet there).

Maintains in_daily/<SYMBOL>.csv (Date,Open,High,Low,Close,Volume, ~700 sessions)
for the Nifty universe so the scanner always has data through the last NSE close.

- First run / every Saturday: full rebuild from eod2_data (official NSE data,
  split/bonus adjusted, updated weekly).
- Every run: append any missing sessions from the official NSE bhavcopy —
  tried directly from NSE archives, else from a daily-committed mirror.
  Raw bhavcopy rows are unadjusted; the weekly rebuild re-adjusts everything,
  and the engine's quality gates flag suspect jumps in between.
"""
import csv
import datetime as dt
import io
import os
import time
import urllib.parse
import urllib.request

import pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
IN_DIR = os.path.join(ROOT, "in_daily")
DATA = os.path.join(ROOT, "data")
os.makedirs(IN_DIR, exist_ok=True)
UA = {"User-Agent": "Mozilla/5.0 (personal research data updater)"}


def fetch(url, timeout=45):
    req = urllib.request.Request(url, headers=UA)
    return urllib.request.urlopen(req, timeout=timeout).read()


def universe():
    with open(os.path.join(DATA, "nifty500_symbols.txt")) as f:
        return [s.strip() for s in f if s.strip()]


def full_rebuild(syms):
    ok = 0
    for s in syms:
        try:
            url = ("https://raw.githubusercontent.com/BennyThadikaran/eod2_data/"
                   "main/daily/" + urllib.parse.quote(s.lower()) + ".csv")
            df = pd.read_csv(io.BytesIO(fetch(url)))
            df = df[["Date", "Open", "High", "Low", "Close", "Volume"]].tail(700)
            df.to_csv(os.path.join(IN_DIR, s + ".csv"), index=False)
            ok += 1
        except Exception:
            pass
        time.sleep(0.03)
    print(f"full rebuild: {ok}/{len(syms)} symbols")


def latest_date():
    dates = []
    for s in ("RELIANCE", "TCS", "HDFCBANK", "INFY"):
        p = os.path.join(IN_DIR, s + ".csv")
        if os.path.exists(p):
            last = open(p).read().rstrip("\n").split("\n")[-1]
            dates.append(last.split(",")[0])
    return max(dates) if dates else None


def bhavcopy(day):
    d = day.strftime("%d%m%Y")
    urls = [
        f"https://nsearchives.nseindia.com/products/content/sec_bhavdata_full_{d}.csv",
        f"https://archives.nseindia.com/products/content/sec_bhavdata_full_{d}.csv",
        f"https://raw.githubusercontent.com/tilak999/NSE-Data-bank/master/data/sec_bhavdata_full_{d}.csv",
    ]
    for u in urls:
        try:
            raw = fetch(u).decode(errors="replace")
            if "SYMBOL" in raw[:300]:
                return raw
        except Exception:
            continue
    return None


def incremental(syms):
    ld = latest_date()
    if not ld:
        return
    day = dt.date.fromisoformat(ld) + dt.timedelta(days=1)
    today = dt.date.today()
    sset = set(syms)
    while day <= today:
        if day.weekday() < 5:
            raw = bhavcopy(day)
            if raw is None:
                print(day, "bhavcopy not available yet")
            else:
                rows = list(csv.reader(io.StringIO(raw)))
                ix = {h.strip(): i for i, h in enumerate(rows[0])}
                cnt = 0
                for r in rows[1:]:
                    try:
                        sym = r[ix["SYMBOL"]].strip()
                        if sym not in sset or r[ix["SERIES"]].strip() != "EQ":
                            continue
                        p = os.path.join(IN_DIR, sym + ".csv")
                        if not os.path.exists(p):
                            continue
                        txt = open(p).read().rstrip("\n")
                        if txt.split("\n")[-1].split(",")[0] >= day.isoformat():
                            continue
                        o, h, l, c = (float(r[ix[k]].strip()) for k in
                                      ("OPEN_PRICE", "HIGH_PRICE", "LOW_PRICE", "CLOSE_PRICE"))
                        v = int(r[ix["TTL_TRD_QNTY"]].strip())
                        with open(p, "w") as f:
                            f.write(txt + f"\n{day.isoformat()},{o},{h},{l},{c},{v}\n")
                        cnt += 1
                    except Exception:
                        pass
                print(day, "appended", cnt, "symbols")
        day += dt.timedelta(days=1)


if __name__ == "__main__":
    syms = universe()
    if not os.path.isdir(IN_DIR) or not os.listdir(IN_DIR) or dt.date.today().weekday() == 5:
        full_rebuild(syms)
    incremental(syms)

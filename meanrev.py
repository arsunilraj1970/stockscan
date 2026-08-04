#!/usr/bin/env python3
"""Mean-reversion (dip-buy) book — validated 2026-08-04 sweep, adopted variant:
base filter + 2% target + 2.5-ATR protective stop + 7-session time exit
(71.4% historical win rate, 74.5% in the recent window, costs included).

Rules
-----
Setup (on yesterday's close): stock above its 200-SMA with a rising 50-SMA,
short-term washout (RSI(3) < 15 or 4 straight down closes), liquid.
Entry: BUY AT NEXT SESSION'S OPEN (market order near the open).
Exit: +2% target from fill, protective stop 2.5*ATR below fill, or close of
the 7th session — whichever comes first.
Position sizing: risk-normalised — size so the stop equals your usual 1R.

Usage:
  python3 meanrev.py --market india --scan  [--date YYYY-MM-DD]
  python3 meanrev.py --market india --paper --since 2026-07-31
"""
import argparse
import json
import os
import sys
from datetime import date

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from engine import data, indicators  # noqa: E402

ROOT = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(ROOT, "output")
os.makedirs(OUT, exist_ok=True)

TGT = 0.02
STOP_ATR = 2.5
TMAX = 7
COST = 0.002
MIN_TURNOVER = {"india": 5e7, "us": 5e6}


def enrich_mr(df):
    e = indicators.enrich(df)
    d = e["Close"].diff()
    up = d.clip(lower=0).ewm(alpha=1 / 3, adjust=False).mean()
    dn = (-d.clip(upper=0)).ewm(alpha=1 / 3, adjust=False).mean()
    e["RSI3"] = 100 - 100 / (1 + up / dn.replace(0, np.nan))
    e["DOWN4"] = (e["Close"].diff() < 0).rolling(4).sum()
    return e


def setup_row(e, i):
    row = e.iloc[i]
    if pd.isna(row["SMA200"]) or pd.isna(row["ATR14"]):
        return False
    return bool(
        row["Close"] > row["SMA200"]
        and e["SMA50"].iloc[i] > e["SMA50"].iloc[i - 10]
        and (row["RSI3"] < 15 or row["DOWN4"] >= 4)
    )


def liquid(e, i, market):
    med_vol = e["Volume"].iloc[max(0, i - 20):i].median()
    return float(e["Close"].iloc[i] * med_vol) >= MIN_TURNOVER[market]


def make_signal(sym, market, e):
    row = e.iloc[-1]
    close, atr = float(row["Close"]), float(row["ATR14"])
    stop_ref = round(close - STOP_ATR * atr, 2)
    cur = "₹" if market == "india" else "$"
    conf = int(min(85, 50 + max(0.0, 15 - float(row["RSI3"])) * 2))
    return {
        "symbol": sym, "market": market, "date": str(e.index[-1].date()),
        "pattern": "oversold dip (buy next open)", "watch": False,
        "close": round(close, 2),
        "entry": round(close, 2),          # reference — actual fill = next open
        "stop_loss": stop_ref, "stop_pct": round((close - stop_ref) / close * 100, 1),
        "target": round(close * (1 + TGT), 2), "target_pct": round(TGT * 100, 1),
        "breakeven_trigger": None,
        "risk_reward": round(TGT / ((close - stop_ref) / close), 2),
        "support": None, "support_strength": None, "resistance": None,
        "vol_ratio": None, "rsi": round(float(row["RSI3"]), 1),
        "pct_from_52w_high": round((float(row["HI52"]) - close) / float(row["HI52"]) * 100, 1),
        "confidence": conf, "currency": cur,
        "note": (f"DIP-BUY: buy at next session's OPEN (prices here reference the last close; "
                 f"recompute from your fill). Sell at +2% from fill, protective stop "
                 f"{STOP_ATR}x ATR (~{round((close-stop_ref)/close*100,1)}%) below fill, or exit at the "
                 f"close of the 7th session. Size the position so the stop equals your normal 1R risk."),
    }


def scan(market, day, top=8):
    sigs = []
    for sym in data.load_universe(market):
        df = data.load_history(market, sym)
        if df is None or len(df) < 320:
            continue
        q = data.quality_check(df, MIN_TURNOVER[market], day)
        if not q.ok:
            continue
        e = enrich_mr(df)
        if setup_row(e, len(e) - 1) and liquid(e, len(e) - 1, market):
            sigs.append(make_signal(sym, market, e))
    sigs.sort(key=lambda s: -s["confidence"])
    result = {"market": market, "scan_date": day, "profile": "meanrev",
              "universe_size": len(data.load_universe(market)),
              "signals": sigs[:top], "additional_signals_count": max(0, len(sigs) - top),
              "data_quality_skips": {}}
    with open(os.path.join(OUT, f"scan_{market}_{day}_meanrev.json"), "w") as f:
        json.dump(result, f, indent=2)
    return result


def paper(market, since):
    pending, open_pos, closed = [], [], []
    for sym in data.load_universe(market):
        df = data.load_history(market, sym)
        if df is None or len(df) < 320:
            continue
        e = enrich_mr(df)
        n = len(e)
        i = max(262, n - 120)
        while i < n:
            if e.index[i] < pd.Timestamp(since) or not setup_row(e, i) or not liquid(e, i, market):
                i += 1
                continue
            cur = "₹" if market == "india" else "$"
            base = {"symbol": sym, "pattern": "oversold dip", "signal_date": str(e.index[i].date()),
                    "confidence": int(min(85, 50 + max(0.0, 15 - float(e["RSI3"].iloc[i])) * 2)),
                    "currency": cur}
            if i == n - 1:
                pending.append({**base, "entry": round(float(e['Close'].iloc[i]), 2),
                                "stop_loss": round(float(e['Close'].iloc[i] - STOP_ATR * e['ATR14'].iloc[i]), 2),
                                "target": round(float(e['Close'].iloc[i]) * (1 + TGT), 2),
                                "status": "buy at next open", "sessions_left": 1})
                break
            entry = float(e["Open"].iloc[i + 1])
            atr = float(e["ATR14"].iloc[i])
            stop, target = entry - STOP_ATR * atr, entry * (1 + TGT)
            fwd = e.iloc[i + 1:i + 1 + TMAX + 3]
            exit_px = kind = days = None
            for j in range(len(fwd)):
                bar = fwd.iloc[j]
                if bar["Low"] <= stop:
                    exit_px, kind, days = stop, "stopped", j + 1
                    break
                if bar["High"] >= target:
                    exit_px, kind, days = target, "target hit", j + 1
                    break
                if j + 1 >= TMAX:
                    exit_px, kind, days = float(bar["Close"]), "time exit", j + 1
                    break
            risk = entry - stop
            if exit_px is None:  # still open
                curp = float(e["Close"].iloc[-1])
                open_pos.append({**base, "entered": str(fwd.index[0].date()), "entry": round(entry, 2),
                                 "stop_loss": round(stop, 2), "target": round(target, 2),
                                 "current": round(curp, 2), "sessions_held": len(fwd),
                                 "unrealized_r": round((curp - entry) / risk, 2),
                                 "unrealized_pct": round(((curp - entry) / entry - COST) * 100, 2)})
                i += 5
                continue
            ret = (exit_px - entry) / entry - COST
            closed.append({**base, "entered": str(fwd.index[0].date()),
                           "exit_date": str(fwd.index[days - 1].date()), "exit": round(exit_px, 2),
                           "entry": round(entry, 2), "result": kind, "sessions_held": days,
                           "r_multiple": round((exit_px - entry) / risk, 2),
                           "pnl_pct": round(ret * 100, 2)})
            i += 5
    rets = [c["pnl_pct"] for c in closed]
    wins = [r for r in rets if r > 0]
    stats = {"trades": len(closed)}
    if closed:
        stats.update(wins=len(wins), scratches=0,
                     win_rate=round(len(wins) / len(closed), 2),
                     success_rate=round(len(wins) / len(closed), 2),
                     avg_r=round(float(np.mean([c["r_multiple"] for c in closed])), 2),
                     total_r=round(float(np.sum([c["r_multiple"] for c in closed])), 2),
                     avg_pnl_pct=round(float(np.mean(rets)), 2),
                     best_r=max(c["r_multiple"] for c in closed),
                     worst_r=min(c["r_multiple"] for c in closed))
    book = {"market": market, "since": since, "profile": "meanrev",
            "pending": pending, "open": open_pos, "closed": closed,
            "expired_untriggered": 0, "stats": stats}
    with open(os.path.join(OUT, f"paper_book_{market}_meanrev.json"), "w") as f:
        json.dump(book, f, indent=2)
    return book


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--market", required=True, choices=["india", "us"])
    ap.add_argument("--scan", action="store_true")
    ap.add_argument("--paper", action="store_true")
    ap.add_argument("--date", default=str(date.today()))
    ap.add_argument("--since", default="2026-08-04")
    args = ap.parse_args()
    if args.scan:
        r = scan(args.market, args.date)
        print(json.dumps({"signals": [(s["symbol"], s["close"], s["confidence"]) for s in r["signals"]],
                          "more": r["additional_signals_count"]}, indent=2))
    if args.paper:
        b = paper(args.market, args.since)
        print(json.dumps({"pending": len(b["pending"]), "open": len(b["open"]),
                          "closed": len(b["closed"]), "stats": b["stats"]}, indent=2))

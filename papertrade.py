#!/usr/bin/env python3
"""Paper-trading book: replay engine signals from a start date, simulate the
standard trade rules, and report the current book. Deterministic — needs no
stored state, so it survives fresh sessions.

Usage: python3 papertrade.py --market india --since 2026-07-31
"""
import argparse
import json
import os
import sys

import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from engine import data, indicators, patterns, signals  # noqa: E402

ROOT = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(ROOT, "output")
os.makedirs(OUT, exist_ok=True)

TRIG_WINDOW = 3   # sessions the entry order stays live
FWD_STALE = 40    # sessions before a stale position is closed at market


def summarize(closed):
    if not closed:
        return {"trades": 0}
    rs = [c["r_multiple"] for c in closed]
    wins = [r for r in rs if r > 0.05]
    scratches = [c for c in closed if c["result"] == "breakeven exit"]
    return {
        "trades": len(closed),
        "wins": len(wins),
        "scratches": len(scratches),
        "win_rate": round(len(wins) / len(closed), 2),
        "success_rate": round((len(wins) + len(scratches)) / len(closed), 2),
        "avg_r": round(sum(rs) / len(rs), 2),
        "total_r": round(sum(rs), 2),
        "best_r": max(rs),
        "worst_r": min(rs),
    }


def run(market, since, profile="conservative"):
    universe = data.load_universe(market)
    pending, open_pos, closed, expired = [], [], [], 0
    for sym in universe:
        df = data.load_history(market, sym)
        if df is None or len(df) < 320:
            continue
        try:
            e = indicators.enrich(df)
        except Exception:
            continue
        n = len(e)
        last_sig = -99
        for i in range(262, n):
            if e.index[i] < pd.Timestamp(since) or i - last_sig < 10:
                continue
            row = e.iloc[i]
            if not (row["Close"] > row["SMA50"] > row["SMA200"]):
                continue
            window = e.iloc[: i + 1]
            hit = patterns.detect(window)
            if not hit:
                continue
            sig = signals.build_signal(sym, market, window, hit)
            if not sig:
                continue
            last_sig = i
            entry, stop, target = sig["entry"], sig["stop_loss"], sig["target"]
            risk = entry - stop
            base = {
                "symbol": sym, "pattern": sig["pattern"], "signal_date": sig["date"],
                "entry": entry, "stop_loss": stop, "target": target,
                "confidence": sig["confidence"], "currency": sig["currency"],
            }
            fwd = e.iloc[i + 1 :]
            t_at = None
            for j in range(min(TRIG_WINDOW, len(fwd))):
                if fwd["High"].iloc[j] >= entry:
                    t_at = j
                    break
            if t_at is None:
                if len(fwd) < TRIG_WINDOW:
                    pending.append({**base, "status": "awaiting entry",
                                    "sessions_left": TRIG_WINDOW - len(fwd)})
                else:
                    expired += 1
                continue
            trig_date = str(fwd.index[t_at].date())
            outcome = None
            be_level = sig.get("breakeven_trigger")
            be_armed = False
            eff_stop = stop
            for j in range(t_at, len(fwd)):
                bar = fwd.iloc[j]
                d = j - t_at + 1
                if bar["Low"] <= eff_stop:
                    kind = "breakeven exit" if be_armed else "stopped"
                    outcome = (kind, eff_stop, d, str(fwd.index[j].date()))
                    break
                if bar["High"] >= target:
                    outcome = ("target hit", target, d, str(fwd.index[j].date()))
                    break
                if be_level and not be_armed and bar["High"] >= be_level:
                    be_armed = True      # from the next session the stop sits at entry
                    eff_stop = entry
                if d >= FWD_STALE:
                    outcome = ("stale exit", float(bar["Close"]), d, str(fwd.index[j].date()))
                    break
            if outcome:
                kind, px, days, dt = outcome
                closed.append({**base, "entered": trig_date, "exit_date": dt,
                               "exit": round(px, 2), "result": kind,
                               "sessions_held": days,
                               "r_multiple": round((px - entry) / risk, 2),
                               "pnl_pct": round((px - entry) / entry * 100, 2)})
            else:
                cur = float(e["Close"].iloc[-1])
                open_pos.append({**base, "entered": trig_date,
                                 "current": round(cur, 2),
                                 "sessions_held": len(fwd) - t_at,
                                 "unrealized_r": round((cur - entry) / risk, 2),
                                 "unrealized_pct": round((cur - entry) / entry * 100, 2)})
    book = {
        "market": market, "since": since, "profile": profile,
        "pending": pending, "open": open_pos, "closed": closed,
        "expired_untriggered": expired, "stats": summarize(closed),
    }
    suffix = "" if profile == "conservative" else f"_{profile}"
    path = os.path.join(OUT, f"paper_book_{market}{suffix}.json")
    with open(path, "w") as f:
        json.dump(book, f, indent=2)
    return book


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--market", required=True, choices=["india", "us"])
    ap.add_argument("--since", default="2026-07-31")
    ap.add_argument("--profile", default="conservative", choices=["conservative", "balanced"])
    args = ap.parse_args()
    patterns.set_profile(args.profile)
    signals.set_profile(args.profile)
    book = run(args.market, args.since, args.profile)
    print(json.dumps(book, indent=2))

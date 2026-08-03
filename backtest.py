#!/usr/bin/env python3
"""Backtest the engine's own patterns to measure time-to-target statistics.

For every historical signal the detectors would have fired, simulate:
  - entry triggers only if price crosses the entry level within 3 sessions
  - then walk forward (max 90 sessions): stop hit? 70%-of-move reached? target?
Aggregate per pattern: trigger rate, win rate, median sessions to milestones.
"""
import json
import os
import sys
import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from engine import data, indicators, patterns, signals

MARKET = sys.argv[1] if len(sys.argv) > 1 else "india"
LOOKBACK_DAYS = 500          # how far back to hunt for historical signals
FWD = 90                     # max sessions to track an open trade
results = []

universe = data.load_universe(MARKET)
for k, sym in enumerate(universe):
    df = data.load_history(MARKET, sym)
    if df is None or len(df) < 320:
        continue
    e = indicators.enrich(df)
    closes = e["Close"].values
    n = len(e)
    start = max(262, n - LOOKBACK_DAYS - FWD)
    last_sig_i = -99
    i = start
    while i < n - FWD:
        # cheap pre-filter before running detectors
        row = e.iloc[i]
        if not (row["Close"] > row["SMA50"] > row["SMA200"]) or i - last_sig_i < 10:
            i += 1
            continue
        window = e.iloc[: i + 1]
        hit = patterns.detect(window)
        if not hit:
            i += 1
            continue
        sig = signals.build_signal(sym, MARKET, window, hit)
        if not sig:
            i += 1
            continue
        last_sig_i = i
        entry, stop, target = sig["entry"], sig["stop_loss"], sig["target"]
        m70 = entry + 0.7 * (target - entry)
        fwd = e.iloc[i + 1 : i + 1 + FWD]
        # does the entry trigger within 3 sessions?
        trig_at = None
        for j in range(min(3, len(fwd))):
            if fwd["High"].iloc[j] >= entry:
                trig_at = j
                break
        rec = {"symbol": sym, "pattern": sig["pattern"].split(" (")[0],
               "date": str(e.index[i].date()), "triggered": trig_at is not None}
        if trig_at is not None:
            days_stop = days_70 = days_tgt = None
            for j in range(trig_at, len(fwd)):
                bar = fwd.iloc[j]
                d = j - trig_at + 1
                if days_stop is None and bar["Low"] <= stop:
                    days_stop = d
                    break  # conservative: stop ends the trade
                if days_70 is None and bar["High"] >= m70:
                    days_70 = d
                if days_tgt is None and bar["High"] >= target:
                    days_tgt = d
                    break
            rec.update({"days_stop": days_stop, "days_70": days_70, "days_tgt": days_tgt})
        results.append(rec)
        i += 1

df = pd.DataFrame(results)
out = {"market": MARKET, "n_signals": len(df)}
if len(df):
    # normalise pattern families
    fam = df["pattern"].str.replace(r"\d+-session base breakout", "base breakout", regex=True)
    fam = fam.replace({"55-day-high breakout": "55d/52w-high breakout",
                       "52-week-high breakout": "55d/52w-high breakout"})
    df["family"] = fam
    stats = {}
    for f, g in df.groupby("family"):
        t = g[g["triggered"]]
        won = t["days_tgt"].notna()
        stopped = t["days_stop"].notna() & ~won
        r70 = t["days_70"].notna() | won
        stats[f] = {
            "signals": int(len(g)),
            "trigger_rate": round(len(t) / len(g), 2),
            "reached_target_rate": round(won.mean(), 2) if len(t) else None,
            "stopped_rate": round(stopped.mean(), 2) if len(t) else None,
            "reached_70pct_rate": round(r70.mean(), 2) if len(t) else None,
            "median_sessions_to_70pct": float(t.loc[r70, "days_70"].fillna(t["days_tgt"]).median()) if r70.any() else None,
            "median_sessions_to_target": float(t.loc[won, "days_tgt"].median()) if won.any() else None,
            "p75_sessions_to_target": float(t.loc[won, "days_tgt"].quantile(0.75)) if won.any() else None,
        }
    out["by_pattern"] = stats
with open(os.path.join("data", f"backtest_stats_{MARKET}.json"), "w") as f:
    json.dump(out, f, indent=2)
print(json.dumps(out, indent=2))

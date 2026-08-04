#!/usr/bin/env python3
"""Mean-reversion parameter sweep: which filter+exit combo clears 70%+ win
rate while keeping positive net expectancy? Costs 0.1%/side included."""
import json
import os
import sys
from datetime import date
from itertools import product

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from engine import data, indicators  # noqa: E402

LOOKBACK = 300
COST = 0.002

FILTERS = {
    "base": dict(rsi_max=15, near_high=None),
    "deep": dict(rsi_max=10, near_high=None),
    "leader": dict(rsi_max=15, near_high=0.15),
    "deep_leader": dict(rsi_max=10, near_high=0.15),
}
EXITS = {
    "ema5": dict(mode="ema5", stop_atr=2.5, tmax=7),
    "tgt2": dict(mode="target", tgt=0.02, stop_atr=2.5, tmax=7),
    "tgt2_nostop": dict(mode="target", tgt=0.02, stop_atr=None, tmax=7),
    "tgt15_nostop": dict(mode="target", tgt=0.015, stop_atr=None, tmax=7),
}


def rsi(series, n):
    d = series.diff()
    up = d.clip(lower=0).ewm(alpha=1 / n, adjust=False).mean()
    dn = (-d.clip(upper=0)).ewm(alpha=1 / n, adjust=False).mean()
    return 100 - 100 / (1 + up / dn.replace(0, np.nan))


def main():
    frames = []
    for market in ("india", "us"):
        for sym in data.load_universe(market):
            df = data.load_history(market, sym)
            if df is None or len(df) < 320:
                continue
            e = indicators.enrich(df)
            e["RSI3"] = rsi(e["Close"], 3)
            e["EMA5"] = e["Close"].ewm(span=5, adjust=False).mean()
            frames.append((market, sym, e))

    results = []
    for fname, exname in product(FILTERS, EXITS):
        F, X = FILTERS[fname], EXITS[exname]
        rets, dates_all, stopped = [], [], 0
        for market, sym, e in frames:
            c = e["Close"]
            down_run = (c.diff() < 0).rolling(4).sum()
            cond = (c > e["SMA200"]) & (e["SMA50"] > e["SMA50"].shift(10)) & \
                   ((e["RSI3"] < F["rsi_max"]) | (down_run >= 4 + (1 if F["rsi_max"] < 15 else 0)))
            if F["near_high"] is not None:
                cond &= c >= (1 - F["near_high"]) * e["HI52"]
            n = len(e)
            i = max(262, n - LOOKBACK)
            while i < n - 12:
                if not cond.iloc[i]:
                    i += 1
                    continue
                turn = float(c.iloc[i] * e["Volume"].iloc[i - 20:i].median())
                if turn < (5e7 if market == "india" else 5e6):
                    i += 1
                    continue
                entry = float(e["Open"].iloc[i + 1])
                atr = float(e["ATR14"].iloc[i])
                stop = entry - X["stop_atr"] * atr if X["stop_atr"] else None
                fwd = e.iloc[i + 1:i + 1 + X["tmax"] + 3]
                exit_px = None
                for j in range(len(fwd)):
                    bar = fwd.iloc[j]
                    if stop and bar["Low"] <= stop:
                        exit_px = stop
                        stopped += 1
                        break
                    if X["mode"] == "ema5":
                        if j > 0 and bar["Close"] > bar["EMA5"]:
                            exit_px = float(bar["Close"])
                            break
                    else:
                        if bar["High"] >= entry * (1 + X["tgt"]):
                            exit_px = entry * (1 + X["tgt"])
                            break
                    if j + 1 >= X["tmax"]:
                        exit_px = float(bar["Close"])
                        break
                if exit_px is None:
                    exit_px = float(fwd["Close"].iloc[-1])
                rets.append((exit_px - entry) / entry - COST)
                dates_all.append(str(e.index[i].date()))
                i += 5
        if len(rets) < 100:
            continue
        rets = np.array(rets)
        wins = rets > 0
        # recent 90-signal-date window
        ds = sorted(set(dates_all))
        wcut = ds[-90] if len(ds) > 90 else ds[0]
        recent = np.array([r for r, d in zip(rets, dates_all) if d >= wcut])
        pf = rets[wins].sum() / abs(rets[~wins].sum()) if (~wins).any() else 99
        results.append({
            "filter": fname, "exit": exname, "n": int(len(rets)),
            "win_rate": round(float(wins.mean()), 3),
            "avg_ret_pct": round(float(rets.mean() * 100), 3),
            "profit_factor": round(float(pf), 2),
            "avg_win_pct": round(float(rets[wins].mean() * 100), 2),
            "avg_loss_pct": round(float(rets[~wins].mean() * 100), 2) if (~wins).any() else 0,
            "recent_n": int(len(recent)),
            "recent_win_rate": round(float((recent > 0).mean()), 3) if len(recent) else None,
            "recent_avg_ret_pct": round(float(recent.mean() * 100), 3) if len(recent) else None,
        })
    results.sort(key=lambda r: (-r["win_rate"]))
    json.dump({"generated": str(date.today()), "results": results},
              open("output/mr_sweep.json", "w"), indent=2)
    for r in results:
        print(f"{r['filter']:<12} {r['exit']:<13} n={r['n']:<5} WR={r['win_rate']:.1%} "
              f"avg={r['avg_ret_pct']:+.3f}% PF={r['profit_factor']:.2f} "
              f"| recent: WR={r['recent_win_rate']:.1%} avg={r['recent_avg_ret_pct']:+.3f}%")


if __name__ == "__main__":
    main()

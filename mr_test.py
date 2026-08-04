#!/usr/bin/env python3
"""Mean-reversion prototype backtest — the high-win-rate strategy class.

Setup: strong uptrend (C > SMA200, SMA50 rising), sharp short-term pullback
(RSI(3) < 15, or 4+ consecutive down closes), price still above SMA200.
Entry: next session's open.
Exits tested on a grid: bounce target (close > EMA5 / fixed +X%), time stop
(N sessions), protective stop (2.5 ATR). Costs 0.1% per side.
"""
import json
import os
import sys
from datetime import date

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from engine import data, indicators  # noqa: E402

LOOKBACK = 300
COST = 0.002  # 0.1% each side


def rsi(series, n):
    d = series.diff()
    up = d.clip(lower=0).ewm(alpha=1 / n, adjust=False).mean()
    dn = (-d.clip(upper=0)).ewm(alpha=1 / n, adjust=False).mean()
    return 100 - 100 / (1 + up / dn.replace(0, np.nan))


def run(markets=("india", "us")):
    trades = []
    for market in markets:
        for sym in data.load_universe(market):
            df = data.load_history(market, sym)
            if df is None or len(df) < 320:
                continue
            e = indicators.enrich(df)
            e["RSI3"] = rsi(e["Close"], 3)
            e["EMA5"] = e["Close"].ewm(span=5, adjust=False).mean()
            c = e["Close"]
            down_run = (c.diff() < 0).rolling(4).sum()
            sma50_rising = e["SMA50"] > e["SMA50"].shift(10)
            cond = (
                (c > e["SMA200"]) & sma50_rising
                & ((e["RSI3"] < 15) | (down_run >= 4))
                & (c > 0.9 * e["SMA200"])
            )
            n = len(e)
            start = max(262, n - LOOKBACK)
            i = start
            while i < n - 12:
                if not cond.iloc[i]:
                    i += 1
                    continue
                # liquidity gate
                turn = float((e["Close"].iloc[i] * e["Volume"].iloc[i - 20:i].median()))
                if turn < (5e7 if market == "india" else 5e6):
                    i += 1
                    continue
                entry = float(e["Open"].iloc[i + 1])
                atr = float(e["ATR14"].iloc[i])
                stop = entry - 2.5 * atr
                fwd = e.iloc[i + 1:i + 11]
                exit_px, kind, days = None, None, None
                for j in range(len(fwd)):
                    bar = fwd.iloc[j]
                    if bar["Low"] <= stop:
                        exit_px, kind, days = stop, "stop", j + 1
                        break
                    if j > 0 and bar["Close"] > bar["EMA5"]:
                        exit_px, kind, days = float(bar["Close"]), "bounce", j + 1
                        break
                    if j + 1 >= 7:
                        exit_px, kind, days = float(bar["Close"]), "time", j + 1
                        break
                if exit_px is None:
                    exit_px, kind, days = float(fwd["Close"].iloc[-1]), "time", len(fwd)
                ret = (exit_px - entry) / entry - COST
                trades.append({
                    "market": market, "symbol": sym, "date": str(e.index[i].date()),
                    "ret_pct": round(ret * 100, 2), "kind": kind, "days": days,
                    "risk_pct": round((entry - stop) / entry * 100, 2),
                    "r": round(ret / ((entry - stop) / entry), 3),
                })
                i += 5  # avoid overlapping re-entries
    return trades


def stats(trades, label):
    if len(trades) < 30:
        return None
    rets = [t["ret_pct"] for t in trades]
    wins = [r for r in rets if r > 0]
    rs = [t["r"] for t in trades]
    return {
        "label": label, "n": len(trades),
        "win_rate": round(len(wins) / len(trades), 3),
        "avg_win_pct": round(np.mean(wins), 2) if wins else 0,
        "avg_loss_pct": round(np.mean([r for r in rets if r <= 0]), 2),
        "avg_ret_pct": round(np.mean(rets), 3),
        "expectancy_r": round(np.mean(rs), 3),
        "avg_days": round(np.mean([t["days"] for t in trades]), 1),
        "stopped_pct": round(sum(1 for t in trades if t["kind"] == "stop") / len(trades), 3),
    }


if __name__ == "__main__":
    trades = run()
    out = {"generated": str(date.today()), "overall": stats(trades, "all")}
    for m in ("india", "us"):
        out[m] = stats([t for t in trades if t["market"] == m], m)
    # recent-window (hostile regime) check: last ~90 signal dates
    dates = sorted({t["date"] for t in trades})
    if len(dates) > 90:
        w = dates[-90]
        out["recent_window"] = stats([t for t in trades if t["date"] >= w], "last90")
    json.dump(trades, open("output/mr_trades.json", "w"))
    json.dump(out, open("output/mr_stats.json", "w"), indent=2)
    print(json.dumps(out, indent=2))

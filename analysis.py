#!/usr/bin/env python3
"""Replay + miss analysis.

1. Replays the engine's signals over recent history for BOTH risk profiles and
   BOTH markets, recording every simulated trade with its entry-day features.
2. Miss analysis (conservative book): compares stopped trades against winners
   across features, tests candidate filter rules, and VALIDATES each rule by
   measuring its effect on total R — a finding is only 'validated' when the
   filtered book keeps enough trades AND meaningfully improves total R.

Outputs: output/replay_stats.json, output/miss_analysis.json
Usage: python3 analysis.py [--if-stale-days 7] [--lookback 300]
"""
import argparse
import json
import os
import sys
from datetime import date, datetime

import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from engine import data, indicators, patterns, signals  # noqa: E402

ROOT = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(ROOT, "output")
os.makedirs(OUT, exist_ok=True)
FWD = 90
TRIG_WINDOW = 3


def family(name):
    if "base breakout" in name:
        return "base breakout"
    if "-high breakout" in name:
        return "high breakout"
    if "bull-flag" in name:
        return "bull-flag"
    if "forming" in name:
        return "forming (watch)"
    return "other"


def replay(profile, market, lookback):
    patterns.set_profile(profile)
    signals.set_profile(profile)
    trades = []
    for sym in data.load_universe(market):
        df = data.load_history(market, sym)
        if df is None or len(df) < 320:
            continue
        e = indicators.enrich(df)
        n = len(e)
        start = max(262, n - lookback - FWD)
        last_sig = -99
        for i in range(start, n - FWD):
            row = e.iloc[i]
            if i - last_sig < 10 or not (row["Close"] > row["SMA50"] > row["SMA200"]):
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
            atr = float(row["ATR14"])
            feat = {
                "symbol": sym, "market": market, "date": sig["date"],
                "family": family(sig["pattern"]), "watch": sig.get("watch", False),
                "rsi": sig["rsi"], "vol_ratio": sig.get("vol_ratio") or 0,
                "ext_atr": round((float(row["Close"]) - float(row["EMA20"])) / atr, 2) if atr else 0,
                "stop_pct": sig["stop_pct"], "confidence": sig["confidence"],
                "pct_from_52w_high": sig["pct_from_52w_high"],
            }
            fwd = e.iloc[i + 1 :]
            t_at = None
            for j in range(min(TRIG_WINDOW, len(fwd))):
                if fwd["High"].iloc[j] >= entry:
                    t_at = j
                    break
            if t_at is None:
                trades.append({**feat, "result": "expired", "r": None})
                continue
            result, r = "open", None
            for j in range(t_at, min(t_at + FWD, len(fwd))):
                bar = fwd.iloc[j]
                if bar["Low"] <= stop:
                    result, r = "stopped", round((stop - entry) / risk, 2)
                    break
                if bar["High"] >= target:
                    result, r = "target", round((target - entry) / risk, 2)
                    break
                if j - t_at + 1 >= 40:
                    result, r = "stale", round((float(bar["Close"]) - entry) / risk, 2)
                    break
            trades.append({**feat, "result": result, "r": r})
    return trades


def agg(trades):
    closed = [t for t in trades if t["r"] is not None]
    if not trades:
        return {}
    out = {
        "signals": len(trades),
        "expired": sum(1 for t in trades if t["result"] == "expired"),
        "closed": len(closed),
        "outcomes": {k: sum(1 for t in closed if t["result"] == k) for k in ("target", "stopped", "stale")},
    }
    if closed:
        rs = [t["r"] for t in closed]
        wins = [r for r in rs if r > 0]
        out.update(win_rate=round(len(wins) / len(closed), 3),
                   total_r=round(sum(rs), 1), avg_r=round(sum(rs) / len(rs), 3))
    return out


def bucket_stats(closed, key, edges, labels):
    res = []
    for lo, hi, lab in zip(edges[:-1], edges[1:], labels):
        grp = [t for t in closed if lo <= t[key] < hi]
        if len(grp) >= 8:
            wins = sum(1 for t in grp if t["r"] > 0)
            res.append({"bucket": lab, "n": len(grp),
                        "win_rate": round(wins / len(grp), 3),
                        "avg_r": round(sum(t["r"] for t in grp) / len(grp), 2)})
    return res


def rule_test(closed, name, desc, keep_fn):
    base_r = sum(t["r"] for t in closed)
    kept = [t for t in closed if keep_fn(t)]
    if not kept:
        return None
    kept_r = sum(t["r"] for t in kept)
    kept_wins = sum(1 for t in kept if t["r"] > 0)
    improvement = kept_r - base_r
    validated = (
        len(kept) >= 20
        and len(kept) >= 0.25 * len(closed)
        and (kept_r >= base_r + max(1.5, abs(base_r) * 0.15) or (base_r <= 0 < kept_r))
    )
    return {
        "rule": name, "description": desc,
        "baseline": {"trades": len(closed), "total_r": round(base_r, 1),
                     "win_rate": round(sum(1 for t in closed if t["r"] > 0) / len(closed), 3)},
        "filtered": {"trades": len(kept), "total_r": round(kept_r, 1),
                     "win_rate": round(kept_wins / len(kept), 3)},
        "r_improvement": round(improvement, 1),
        "validated": bool(validated),
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--lookback", type=int, default=300)
    ap.add_argument("--if-stale-days", type=int, default=0)
    args = ap.parse_args()

    mpath = os.path.join(OUT, "miss_analysis.json")
    fallback = os.path.join(ROOT, "data", "miss_analysis.json")
    if args.if_stale_days:
        for p in (mpath, fallback):
            if os.path.exists(p):
                prev = json.load(open(p))
                age = (date.today() - date.fromisoformat(prev["generated"])).days
                if age <= args.if_stale_days:
                    if p == fallback:  # copy repo cache into output for dashboard
                        json.dump(prev, open(mpath, "w"), indent=2)
                    prev2 = os.path.join(ROOT, "data", "replay_stats.json")
                    rpath = os.path.join(OUT, "replay_stats.json")
                    if not os.path.exists(rpath) and os.path.exists(prev2):
                        json.dump(json.load(open(prev2)), open(rpath, "w"), indent=2)
                    print(f"analysis fresh ({age}d old) — skipped")
                    return

    stats, all_trades = {}, {}
    for profile in ("conservative", "balanced"):
        trades = []
        for market in ("india", "us"):
            try:
                trades += replay(profile, market, args.lookback)
            except Exception as exc:
                print(f"replay {profile}/{market} failed: {exc}")
        all_trades[profile] = trades
        tradeable = [t for t in trades if not t["watch"]] if profile == "balanced" else trades
        stats[profile] = agg(tradeable)
        stats[profile]["by_family"] = {
            f: agg([t for t in tradeable if t["family"] == f])
            for f in sorted({t["family"] for t in tradeable})
        }
    json.dump({"generated": str(date.today()), "lookback_sessions": args.lookback,
               "profiles": stats}, open(os.path.join(OUT, "replay_stats.json"), "w"), indent=2)

    # ---- miss analysis on the conservative (traded) book ----
    closed = [t for t in all_trades["conservative"] if t["r"] is not None]
    misses = [t for t in closed if t["result"] == "stopped"]
    winners = [t for t in closed if t["result"] == "target"]

    def mean(lst, k):
        return round(sum(t[k] for t in lst) / len(lst), 2) if lst else None

    factor_compare = {
        k: {"missed": mean(misses, k), "won": mean(winners, k)}
        for k in ("rsi", "vol_ratio", "ext_atr", "stop_pct", "confidence", "pct_from_52w_high")
    }
    buckets = {
        "rsi": bucket_stats(closed, "rsi", [0, 60, 70, 100], ["RSI < 60", "RSI 60-70", "RSI > 70"]),
        "ext_atr": bucket_stats(closed, "ext_atr", [-9, 1, 2, 99], ["< 1 ATR above EMA20", "1-2 ATR", "> 2 ATR (extended)"]),
        "vol_ratio": bucket_stats(closed, "vol_ratio", [0, 1.8, 2.5, 99], ["vol 1.4-1.8x", "1.8-2.5x", "> 2.5x"]),
        "confidence": bucket_stats(closed, "confidence", [0, 72, 80, 101], ["conf < 72", "72-80", "> 80"]),
    }
    rules = [r for r in (
        rule_test(closed, "rsi_cap_72", "Skip signals with RSI above 72 (late, over-heated entries)", lambda t: t["rsi"] <= 72),
        rule_test(closed, "not_extended", "Skip signals more than 2 ATR above the 20-EMA (chasing extended moves)", lambda t: t["ext_atr"] <= 2.0),
        rule_test(closed, "strong_volume", "Require breakout volume at least 2x average (weak-volume breakouts fail more)", lambda t: t["vol_ratio"] >= 2.0),
        rule_test(closed, "tight_stop", "Only take setups whose natural stop is within 5% (structure is nearby)", lambda t: t["stop_pct"] <= 5.0),
        rule_test(closed, "high_confidence", "Only trade confidence 75+ signals", lambda t: t["confidence"] >= 75),
        rule_test(closed, "drop_base_breakout", "Drop the base-breakout pattern family entirely (weakest backtest performer)", lambda t: t["family"] != "base breakout"),
    ) if r]
    rules.sort(key=lambda r: -r["r_improvement"])

    result = {
        "generated": str(date.today()),
        "lookback_sessions": args.lookback,
        "sample": {"closed": len(closed), "stopped": len(misses), "target": len(winners),
                   "stale": sum(1 for t in closed if t["result"] == "stale")},
        "factor_compare": factor_compare,
        "buckets": buckets,
        "rules": rules,
        "validated_feedback": [r for r in rules if r["validated"]],
    }
    json.dump(result, open(mpath, "w"), indent=2)
    print(json.dumps({"sample": result["sample"],
                      "validated": [r["rule"] for r in result["validated_feedback"]],
                      "top_rules": [(r["rule"], r["r_improvement"]) for r in rules[:3]]}, indent=2))


if __name__ == "__main__":
    main()

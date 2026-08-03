#!/usr/bin/env python3
"""90-session walk-forward study + exit engineering.

Phase 1: replay conservative signals (both markets) over the last ~300
sessions, tracking every triggered trade's full forward path summary:
  - which R-multiples were reached before the stop
  - breakeven-stop variants (move stop to entry once +1R / +0.5R is reached)
  - market breadth (fraction of universe above its 50-SMA) on signal day
Phase 2: consolidate the last 90 sessions day by day (walk-forward view).
Phase 3: evaluate exit/filters grid -> which combinations clear 60% success
         and what each costs in expectancy.

Output: output/study.json
"""
import json
import os
import sys
from collections import defaultdict
from datetime import date

import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from engine import data, indicators, patterns, signals  # noqa: E402

ROOT = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(ROOT, "output")
LOOKBACK = 300      # full sample for statistics
WINDOW = 90         # walk-forward reporting window
K_GRID = [0.5, 0.75, 1.0, 1.25, 1.5, 2.0, 2.5]

patterns.set_profile("conservative")
signals.set_profile("conservative")


def family(name):
    if "base breakout" in name:
        return "base breakout"
    if "-high breakout" in name:
        return "high breakout"
    return "bull-flag"


def collect():
    """Pass A: enrich all stocks, compute per-date breadth. Pass B: replay."""
    frames = {}
    above = defaultdict(int)
    total = defaultdict(int)
    for market in ("india", "us"):
        for sym in data.load_universe(market):
            df = data.load_history(market, sym)
            if df is None or len(df) < 320:
                continue
            e = indicators.enrich(df)
            frames[(market, sym)] = e
            tail = e.tail(LOOKBACK + 100)
            ok = tail["Close"] > tail["SMA50"]
            for d, v in ok.items():
                total[d] += 1
                if v:
                    above[d] += 1
    breadth = {d: above[d] / total[d] for d in total if total[d] >= 200}

    trades = []
    for (market, sym), e in frames.items():
        n = len(e)
        start = max(262, n - LOOKBACK)
        last_sig = -99
        for i in range(start, n - 1):
            row = e.iloc[i]
            if i - last_sig < 10 or not (row["Close"] > row["SMA50"] > row["SMA200"]):
                continue
            hit = patterns.detect(e.iloc[: i + 1])
            if not hit:
                continue
            sig = signals.build_signal(sym, market, e.iloc[: i + 1], hit)
            if not sig:
                continue
            last_sig = i
            entry, stop = sig["entry"], sig["stop_loss"]
            risk = entry - stop
            fwd = e.iloc[i + 1 :]
            t_at = None
            for j in range(min(3, len(fwd))):
                if fwd["High"].iloc[j] >= entry:
                    t_at = j
                    break
            rec = {
                "symbol": sym, "market": market, "date": sig["date"],
                "family": family(sig["pattern"]), "confidence": sig["confidence"],
                "breadth": round(breadth.get(e.index[i], 0.5), 3),
                "triggered": t_at is not None,
            }
            if t_at is None:
                trades.append(rec)
                continue
            # forward walk
            k_hit = {k: None for k in K_GRID}      # session index when k*R reached
            stop_day = None
            mfe = 0.0
            path = fwd.iloc[t_at : t_at + 90]
            for j in range(len(path)):
                bar = path.iloc[j]
                if bar["Low"] <= stop:
                    stop_day = j
                    break
                up_r = (float(bar["High"]) - entry) / risk
                mfe = max(mfe, up_r)
                for k in K_GRID:
                    if k_hit[k] is None and up_r >= k:
                        k_hit[k] = j
            # breakeven variants: once +be_at R reached, stop moves to entry
            def be_result(be_at, target):
                t_day = k_hit.get(target)
                b_day = k_hit.get(be_at)
                if b_day is None:               # never reached BE trigger
                    return "loss" if stop_day is not None else "open_or_stale"
                if t_day is not None and (stop_day is None or t_day <= stop_day):
                    return "win"
                # BE armed; did price come back to entry after b_day?
                for j in range(b_day + 1, len(path)):
                    if t_day is not None and j >= t_day:
                        return "win"
                    if path["Low"].iloc[j] <= entry:
                        return "scratch"
                return "open_or_stale"
            rec.update({
                "entered": str(path.index[0].date()) if len(path) else None,
                "stop_day": stop_day,
                "k_hit": {str(k): k_hit[k] for k in K_GRID},
                "mfe": round(mfe, 2),
                "resolved": stop_day is not None or k_hit[2.5] is not None or len(path) >= 40,
                "exit_date": str(path.index[stop_day].date()) if stop_day is not None else (
                    str(path.index[k_hit[2.5]].date()) if k_hit[2.5] is not None else None),
                "be_1.0_t2.5": be_result(1.0, 2.5),
                "be_0.5_t1.5": be_result(0.5, 1.5),
                "be_1.0_t1.5": be_result(1.0, 1.5),
            })
            trades.append(rec)
    return trades


def strat_eval(trades, target, be_at=None, flt=None, cost_r=0.04):
    """Evaluate: fixed stop, fixed target k, optional breakeven move, filter."""
    sel = [t for t in trades if t["triggered"] and (flt is None or flt(t))]
    wins = scr = loss = unres = 0
    for t in sel:
        kh = t["k_hit"].get(str(target))
        sd = t["stop_day"]
        if be_at is None:
            if kh is not None and (sd is None or kh <= sd):
                wins += 1
            elif sd is not None:
                loss += 1
            else:
                unres += 1
        else:
            key = f"be_{be_at}_t{target}"
            r = t.get(key, "open_or_stale")
            if r == "win":
                wins += 1
            elif r == "scratch":
                scr += 1
            elif r == "loss":
                loss += 1
            else:
                unres += 1
    resolved = wins + scr + loss
    if resolved < 25:
        return None
    win_rate = wins / resolved
    success = (wins + scr) / resolved          # capital-preserved rate
    exp = (wins * target - loss * 1.0 - resolved * cost_r) / resolved
    return {"n": resolved, "wins": wins, "scratch": scr, "loss": loss,
            "unresolved": unres, "win_rate": round(win_rate, 3),
            "success_rate": round(success, 3), "expectancy_r": round(exp, 3)}


def main():
    trades = collect()
    trig = [t for t in trades if t["triggered"]]

    # ---- walk-forward: last 90 distinct signal dates ----
    dates = sorted({t["date"] for t in trades})[-WINDOW:]
    win_start = dates[0]
    wf = []
    for d in dates:
        day = [t for t in trades if t["date"] == d]
        dt = [t for t in day if t["triggered"]]
        res = [t for t in dt if t.get("stop_day") is not None or t["k_hit"].get("2.5") is not None]
        wins = sum(1 for t in res if t["k_hit"].get("2.5") is not None and
                   (t["stop_day"] is None or t["k_hit"]["2.5"] <= t["stop_day"]))
        r = sum(2.5 if (t["k_hit"].get("2.5") is not None and (t["stop_day"] is None or t["k_hit"]["2.5"] <= t["stop_day"]))
                else -1.0 for t in res)
        wf.append({"date": d, "signals": len(day), "triggered": len(dt),
                   "resolved": len(res), "wins": wins, "r": round(r, 1)})
    # equity curve by exit date (window trades only)
    eq = defaultdict(float)
    for t in trig:
        if t["date"] < win_start or not t.get("exit_date"):
            continue
        won = t["k_hit"].get("2.5") is not None and (t["stop_day"] is None or t["k_hit"]["2.5"] <= t["stop_day"])
        eq[t["exit_date"]] += 2.5 if won else -1.0
    curve, cum = [], 0.0
    for d in sorted(eq):
        cum += eq[d]
        curve.append({"date": d, "cum_r": round(cum, 1)})

    # ---- window summary + misses ----
    wtr = [t for t in trig if t["date"] >= win_start]
    wsum = strat_eval(wtr, 2.5)
    miss_by_family = {}
    for f in sorted({t["family"] for t in wtr}):
        s = strat_eval(wtr, 2.5, flt=lambda t, f=f: t["family"] == f)
        if s:
            miss_by_family[f] = s

    # ---- exit engineering on full sample ----
    curve_k = []
    for k in K_GRID:
        base = strat_eval(trig, k)
        if base:
            curve_k.append({"target": k, **base})
    med_breadth = sorted(t["breadth"] for t in trig)[len(trig) // 2]
    filters = {
        "all": None,
        "no_base_breakout": lambda t: t["family"] != "base breakout",
        "no_base+breadth": lambda t: t["family"] != "base breakout" and t["breadth"] >= med_breadth,
    }
    variants = []
    for fname, flt in filters.items():
        for target, be in [(2.5, None), (1.5, None), (1.25, None), (1.0, None),
                           (2.5, 1.0), (1.5, 0.5), (1.5, 1.0)]:
            s = strat_eval(trig, target, be_at=be, flt=flt)
            if s:
                variants.append({"filter": fname, "target": target,
                                 "breakeven_at": be, **s})
    variants.sort(key=lambda v: (-v["success_rate"], -v["expectancy_r"]))

    # recommended-variant check inside the recent window itself
    window_variants = []
    for target, be, fname, flt in [
        (2.5, None, "all", None),
        (1.5, 0.5, "all", None),
        (1.5, 0.5, "no_base_breakout", lambda t: t["family"] != "base breakout"),
    ]:
        s = strat_eval(wtr, target, be_at=be, flt=flt)
        if s:
            window_variants.append({"filter": fname, "target": target, "breakeven_at": be, **s})

    json.dump(trades, open(os.path.join(OUT, "study_trades.json"), "w"))
    out = {
        "generated": str(date.today()),
        "window_start": win_start, "window_end": dates[-1],
        "window_variants": window_variants,
        "full_sample": {"signals": len(trades), "triggered": len(trig),
                        "median_breadth": round(med_breadth, 2)},
        "window_summary": wsum,
        "window_by_family": miss_by_family,
        "walkforward_daily": wf,
        "equity_curve": curve,
        "target_curve": curve_k,
        "variants": variants,
        "note_costs": "expectancy includes 0.04R/trade friction estimate (brokerage+slippage)",
    }
    json.dump(out, open(os.path.join(OUT, "study.json"), "w"), indent=2)
    print(json.dumps({"window": wsum, "best_variants": variants[:6],
                      "target_curve": [(c["target"], c["win_rate"], c["expectancy_r"]) for c in curve_k]}, indent=2))


if __name__ == "__main__":
    main()

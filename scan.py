#!/usr/bin/env python3
"""Daily conservative swing scan.

Usage:  python3 scan.py --market india [--top 10] [--date YYYY-MM-DD]
        python3 scan.py --market india --symbol RELIANCE   (on-demand analysis)
"""
import argparse
import csv
import json
import os
import sys
from datetime import date

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from engine import data, indicators, patterns, signals  # noqa: E402

ROOT = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(ROOT, "output")
os.makedirs(OUT, exist_ok=True)

MIN_TURNOVER = {"india": 5e7, "us": 5e6}  # ₹5 cr / $5M median daily


def analyze_symbol(market, symbol, today):
    df = data.load_history(market, symbol)
    q = data.quality_check(df, MIN_TURNOVER[market], today)
    if not q.ok:
        return None, q.reason
    edf = indicators.enrich(df)
    hit = patterns.detect(edf)
    if not hit:
        return None, "no conservative setup on latest bar"
    sig = signals.build_signal(symbol, market, edf, hit)
    if not sig:
        return None, "pattern found but risk/reward below threshold"
    return sig, None


def run_scan(market, today, top=10):
    universe = data.load_universe(market)
    results, skipped = [], {}
    for sym in universe:
        try:
            sig, reason = analyze_symbol(market, sym, today)
            if sig:
                results.append(sig)
            elif reason and "no conservative setup" not in reason:
                skipped[reason] = skipped.get(reason, 0) + 1
        except Exception as e:
            skipped[f"error: {type(e).__name__}"] = skipped.get(f"error: {type(e).__name__}", 0) + 1
    results.sort(key=lambda s: -s["confidence"])
    return results[:top], results[top:], skipped, len(universe)


def append_log(sigs):
    path = os.path.join(OUT, "signals_log.csv")
    fields = ["date", "market", "symbol", "pattern", "close", "entry", "stop_loss",
              "target", "risk_reward", "confidence", "status"]
    exists = os.path.exists(path)
    with open(path, "a", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        if not exists:
            w.writeheader()
        for s in sigs:
            w.writerow({**s, "status": "suggested"})


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--market", required=True, choices=["india", "us"])
    ap.add_argument("--top", type=int, default=10)
    ap.add_argument("--date", default=str(date.today()))
    ap.add_argument("--symbol")
    ap.add_argument("--no-log", action="store_true")
    ap.add_argument("--profile", default="conservative", choices=["conservative", "balanced"])
    args = ap.parse_args()
    patterns.set_profile(args.profile)
    signals.set_profile(args.profile)
    if args.profile != "conservative":
        args.no_log = True  # only the conservative book feeds the signals log

    if args.symbol:
        sig, reason = analyze_symbol(args.market, args.symbol.upper(), args.date)
        print(json.dumps(sig or {"symbol": args.symbol, "verdict": reason}, indent=2))
        return

    top, rest, skipped, n = run_scan(args.market, args.date, args.top)
    result = {
        "market": args.market,
        "scan_date": args.date,
        "profile": args.profile,
        "universe_size": n,
        "signals": top,
        "additional_signals_count": len(rest),
        "data_quality_skips": skipped,
    }
    suffix = "" if args.profile == "conservative" else f"_{args.profile}"
    out_path = os.path.join(OUT, f"scan_{args.market}_{args.date}{suffix}.json")
    with open(out_path, "w") as f:
        json.dump(result, f, indent=2)
    if not args.no_log:
        append_log(top)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()

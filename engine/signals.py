"""Turn a detected pattern into a complete, conservative trade plan."""
import pandas as pd
import numpy as np
from . import indicators


MIN_RR = 2.0
MIN_STOP_PCT = 0.025
MAX_STOP_PCT = 0.065


def set_profile(name: str = "conservative"):
    global MIN_RR, MAX_STOP_PCT
    if name == "balanced":
        MIN_RR, MAX_STOP_PCT = 1.5, 0.085
    else:
        MIN_RR, MAX_STOP_PCT = 2.0, 0.065


def build_signal(symbol: str, market: str, df: pd.DataFrame, hit: dict):
    last = df.iloc[-1]
    close = float(last["Close"])
    atr = float(last["ATR14"])

    # Entry: a touch above the signal bar's high (confirmation on follow-through),
    # unless the pattern supplies its own level (forming/watch setups).
    entry = hit.get("entry_override") or round(float(last["High"]) * 1.002, 2)

    # Stop: below max(recent swing low, entry - 2*ATR), whichever is nearer but
    # within the conservative band.
    recent_low = float(df["Low"].iloc[-10:].min())
    stop = max(recent_low * 0.995, entry - 2.2 * atr)
    stop_pct = (entry - stop) / entry
    if stop_pct < MIN_STOP_PCT:
        stop = entry * (1 - MIN_STOP_PCT)
        stop_pct = MIN_STOP_PCT
    if stop_pct > MAX_STOP_PCT:
        return None  # too loose for a conservative book
    stop = round(stop, 2)

    levels = indicators.pivot_levels(df)
    sup, res = indicators.nearest_levels(levels, entry)

    risk = entry - stop
    # Target: next meaningful resistance if it's far enough, else RR-based
    target = None
    resistances = [l for l, n in levels if l > entry * 1.02]
    for r in resistances:
        if (r - entry) / risk >= MIN_RR:
            target = r
            break
    if target is None:
        if resistances and (max(resistances) - entry) / risk < MIN_RR:
            return None  # capped upside below required RR -> skip
        target = entry + 2.5 * risk  # blue-sky: RR-based target
    target = round(float(target), 2)

    rr = round((target - entry) / risk, 2)
    if rr < MIN_RR:
        return None

    # confidence score 0-100
    score = 50.0
    score += min(15, (hit.get("vol_ratio", 1.0) - 1.4) * 10)  # volume punch
    hi52 = float(df["HI52"].iloc[-1])
    score += 10 * max(0.0, 1 - (hi52 - close) / (0.15 * hi52))  # near 52w high
    rsi = float(last["RSI14"])
    score += 5 if 55 <= rsi <= 70 else 0
    ext = (close - float(last["EMA20"])) / atr if atr > 0 else 0
    score += 5 if ext < 2.5 else -5  # not over-extended above EMA20
    score += min(10, (rr - MIN_RR) * 5)
    score = int(max(0, min(100, round(score))))

    cur = "₹" if market == "india" else "$"
    watch = bool(hit.get("watch"))
    return {
        "symbol": symbol,
        "market": market,
        "date": str(df.index[-1].date()),
        "watch": watch,
        "pattern": hit["pattern"],
        "close": round(close, 2),
        "entry": entry,
        "stop_loss": stop,
        "stop_pct": round(stop_pct * 100, 1),
        "target": target,
        "target_pct": round((target - entry) / entry * 100, 1),
        "risk_reward": rr,
        "support": sup[0] if sup else None,
        "support_strength": sup[1] if sup else None,
        "resistance": res[0] if res else None,
        "vol_ratio": hit.get("vol_ratio"),
        "rsi": round(rsi, 1),
        "pct_from_52w_high": round((hi52 - close) / hi52 * 100, 1),
        "confidence": score,
        "currency": cur,
        "note": (
            f"Watchlist only — no breakout yet. Becomes a buy ONLY if price crosses "
            f"{cur}{entry}; until then it is not a trade."
            if watch else
            f"Buy only if price crosses {cur}{entry} (use a trigger/GTT order). "
            f"If not triggered within 3 sessions, cancel — the setup is stale."
        ),
    }

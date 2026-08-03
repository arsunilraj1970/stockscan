"""Conservative swing-trade pattern detection.

Every detector works on an indicator-enriched dataframe (see indicators.enrich)
and returns None or a dict describing the setup on the LAST bar."""
import numpy as np
import pandas as pd


def _uptrend(row) -> bool:
    return (
        not pd.isna(row["SMA200"])
        and row["Close"] > row["SMA50"] > row["SMA200"]
    )


def _sma200_rising(df) -> bool:
    s = df["SMA200"].dropna()
    return len(s) > 21 and s.iloc[-1] > s.iloc[-21]


def breakout_55d(df: pd.DataFrame):
    """Close breaks above the prior 55-session high on strong volume."""
    if len(df) < 260:
        return None
    last = df.iloc[-1]
    prior_high = df["High"].iloc[-56:-1].max()
    if not _uptrend(last) or not _sma200_rising(df):
        return None
    if last["Close"] <= prior_high:
        return None
    if last["Volume"] < 1.5 * last["VOL50"] or pd.isna(last["VOL50"]):
        return None
    rng = last["High"] - last["Low"]
    if rng > 0 and (last["Close"] - last["Low"]) / rng < 0.5:
        return None  # weak close
    if last["RSI14"] > 78:
        return None  # over-extended
    is_52w = last["Close"] >= df["HI52"].iloc[-2] * 0.999
    return {
        "pattern": "52-week-high breakout" if is_52w else "55-day-high breakout",
        "breakout_level": round(float(prior_high), 2),
        "vol_ratio": round(float(last["Volume"] / last["VOL50"]), 2),
    }


def base_breakout(df: pd.DataFrame):
    """Tight consolidation base (<=10% depth, >=15 sessions) broken on volume."""
    if len(df) < 260:
        return None
    last = df.iloc[-1]
    if not _uptrend(last) or not _sma200_rising(df):
        return None
    for n in (40, 30, 20, 15):
        base = df.iloc[-(n + 1) : -1]
        hi, lo = base["High"].max(), base["Low"].min()
        depth = (hi - lo) / lo
        if depth <= 0.10 and last["Close"] > hi and last["Volume"] >= 1.4 * last["VOL50"]:
            if last["RSI14"] > 78:
                return None
            return {
                "pattern": f"{n}-session base breakout",
                "breakout_level": round(float(hi), 2),
                "base_low": round(float(lo), 2),
                "base_depth_pct": round(float(depth * 100), 1),
                "vol_ratio": round(float(last["Volume"] / last["VOL50"]), 2),
            }
    return None


def flag_continuation(df: pd.DataFrame):
    """Uptrend, 3-8 session orderly pullback toward EMA20, resumption bar."""
    if len(df) < 260:
        return None
    last = df.iloc[-1]
    if not _uptrend(last) or not _sma200_rising(df):
        return None
    # near its 52-week high (strong stock)
    if last["Close"] < 0.85 * df["HI52"].iloc[-1]:
        return None
    # find pullback: previous 3-8 bars with lower highs, low near EMA20
    for n in (3, 4, 5, 6, 7, 8):
        pull = df.iloc[-(n + 1) : -1]
        if len(pull) < n:
            continue
        lower_highs = (pull["High"].diff().dropna() < 0).mean() >= 0.6
        touched = (pull["Low"] - pull["EMA20"]).abs().min() <= 1.5 * last["ATR14"]
        shallow = (pull["High"].max() - pull["Low"].min()) / pull["Low"].min() < 0.08
        if lower_highs and touched and shallow:
            # resumption: close above previous bar high on decent volume
            if last["Close"] > pull["High"].iloc[-1] and last["Volume"] >= 1.2 * last["VOL50"]:
                if last["RSI14"] > 75:
                    return None
                return {
                    "pattern": f"bull-flag pullback ({n} sessions)",
                    "breakout_level": round(float(pull["High"].iloc[-1]), 2),
                    "vol_ratio": round(float(last["Volume"] / last["VOL50"]), 2),
                }
    return None


DETECTORS = [breakout_55d, base_breakout, flag_continuation]


def detect(df: pd.DataFrame):
    """Run all detectors, return first (strongest-priority) hit."""
    for det in DETECTORS:
        hit = det(df)
        if hit:
            return hit
    return None

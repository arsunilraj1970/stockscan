"""Conservative swing-trade pattern detection.

Every detector works on an indicator-enriched dataframe (see indicators.enrich)
and returns None or a dict describing the setup on the LAST bar."""
import numpy as np
import pandas as pd

# Risk-profile parameters. Defaults = conservative; set_profile() switches.
PARAMS = {}


def set_profile(name: str = "conservative"):
    global PARAMS
    if name == "balanced":
        PARAMS = dict(vol_breakout=1.25, vol_base=1.2, vol_flag=1.1, rsi_cap=82,
                      base_depth=0.13, sma200_rising=False, strong_close=False,
                      include_forming=True, include_base=True)
    else:
        # base breakouts dropped from the conservative book per the validated
        # 2026-08-03 miss-analysis finding (negative expectancy in every test)
        PARAMS = dict(vol_breakout=1.5, vol_base=1.4, vol_flag=1.2, rsi_cap=78,
                      base_depth=0.10, sma200_rising=True, strong_close=True,
                      include_forming=False, include_base=False)


set_profile()


def _uptrend(row) -> bool:
    return (
        not pd.isna(row["SMA200"])
        and row["Close"] > row["SMA50"] > row["SMA200"]
    )


def _sma200_rising(df) -> bool:
    if not PARAMS["sma200_rising"]:
        return True
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
    if last["Volume"] < PARAMS["vol_breakout"] * last["VOL50"] or pd.isna(last["VOL50"]):
        return None
    rng = last["High"] - last["Low"]
    if PARAMS["strong_close"] and rng > 0 and (last["Close"] - last["Low"]) / rng < 0.5:
        return None  # weak close
    if last["RSI14"] > PARAMS["rsi_cap"]:
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
        if depth <= PARAMS["base_depth"] and last["Close"] > hi and last["Volume"] >= PARAMS["vol_base"] * last["VOL50"]:
            if last["RSI14"] > PARAMS["rsi_cap"]:
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
            if last["Close"] > pull["High"].iloc[-1] and last["Volume"] >= PARAMS["vol_flag"] * last["VOL50"]:
                if last["RSI14"] > min(75, PARAMS["rsi_cap"]):
                    return None
                return {
                    "pattern": f"bull-flag pullback ({n} sessions)",
                    "breakout_level": round(float(pull["High"].iloc[-1]), 2),
                    "vol_ratio": round(float(last["Volume"] / last["VOL50"]), 2),
                }
    return None


def forming_breakout(df: pd.DataFrame):
    """Balanced-profile only: price coiled just BELOW a breakout level — a
    watchlist candidate, not yet a buy."""
    if len(df) < 260:
        return None
    last = df.iloc[-1]
    if not _uptrend(last):
        return None
    prior_high = df["High"].iloc[-56:-1].max()
    c = float(last["Close"])
    if c > prior_high:
        return None  # already broke out
    if (prior_high - c) / prior_high > 0.025:
        return None  # not close enough
    if last["RSI14"] > PARAMS["rsi_cap"]:
        return None
    v5 = df["Volume"].iloc[-5:].mean()
    if pd.isna(last["VOL50"]) or v5 < 1.0 * last["VOL50"]:
        return None  # volume not building
    return {
        "pattern": "forming breakout (watch)",
        "breakout_level": round(float(prior_high), 2),
        "vol_ratio": round(float(v5 / last["VOL50"]), 2),
        "watch": True,
        "entry_override": round(float(prior_high) * 1.002, 2),
    }


DETECTORS = [breakout_55d, base_breakout, flag_continuation]


def detect(df: pd.DataFrame):
    """Run all detectors, return first (strongest-priority) hit."""
    for det in DETECTORS:
        if det is base_breakout and not PARAMS.get("include_base", True):
            continue
        hit = det(df)
        if hit:
            return hit
    if PARAMS.get("include_forming"):
        return forming_breakout(df)
    return None

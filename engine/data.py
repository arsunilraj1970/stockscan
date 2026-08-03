"""Data loading + quality gates for the swing scanner."""
import os
import pandas as pd
import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(ROOT, "data")


def load_universe(market: str) -> list:
    fn = "nifty500_symbols.txt" if market == "india" else "sp500_symbols.txt"
    with open(os.path.join(DATA, fn)) as f:
        return [s.strip() for s in f if s.strip()]


def load_history(market: str, symbol: str) -> pd.DataFrame | None:
    """Return OHLCV dataframe indexed by date, or None if unavailable."""
    if market == "india":
        path = os.path.join(DATA, "eod2_data", "daily", symbol.lower() + ".csv")
    else:
        # us_daily may sit at repo root (pipeline output) or under data/
        path = os.path.join(ROOT, "us_daily", symbol.upper() + ".csv")
        if not os.path.exists(path):
            path = os.path.join(DATA, "us_daily", symbol.upper() + ".csv")
    if not os.path.exists(path):
        return None
    try:
        df = pd.read_csv(path, parse_dates=["Date"])
    except Exception:
        return None
    cols = {c.lower(): c for c in df.columns}
    need = ["date", "open", "high", "low", "close", "volume"]
    if any(c not in cols for c in need):
        return None
    df = df[[cols[c] for c in need]].copy()
    df.columns = ["Date", "Open", "High", "Low", "Close", "Volume"]
    df = df.dropna().sort_values("Date").set_index("Date")
    df = df[~df.index.duplicated(keep="last")]
    if market == "us" and len(df):
        # Never analyze a partial bar: drop today's row unless the US session
        # has closed (>= 21:00 UTC covers both EDT and EST closes).
        now = pd.Timestamp.utcnow()
        if df.index[-1].date() == now.date() and now.hour < 21:
            df = df.iloc[:-1]
    return df.tail(700)  # ~2.5 years is plenty


class QualityReport:
    def __init__(self, ok: bool, reason: str = ""):
        self.ok = ok
        self.reason = reason


def quality_check(df: pd.DataFrame, min_turnover: float, today) -> QualityReport:
    """Gate out stocks whose data (or liquidity) can't be trusted for signals."""
    if df is None or len(df) < 220:
        return QualityReport(False, "insufficient history")
    last = df.index[-1]
    if (pd.Timestamp(today) - last).days > 7:
        return QualityReport(False, f"stale data (last {last.date()})")
    recent = df.tail(120)
    # suspicious single-day moves -> possible unadjusted split/bonus
    chg = recent["Close"].pct_change().abs()
    if (chg > 0.35).any():
        return QualityReport(False, "suspicious >35% daily move (possible unadjusted corp action)")
    if (recent[["Open", "High", "Low", "Close"]] <= 0).any().any():
        return QualityReport(False, "non-positive prices")
    # sanity: high >= low etc.
    bad = (recent["High"] < recent["Low"]).sum()
    if bad > 0:
        return QualityReport(False, "corrupt OHLC rows")
    # liquidity: median daily turnover over last 60 sessions
    turnover = (recent["Close"] * recent["Volume"]).tail(60).median()
    if turnover < min_turnover:
        return QualityReport(False, "insufficient liquidity")
    # missing-data density: last 60 calendar weekdays should mostly exist
    expected = pd.bdate_range(recent.index[-1] - pd.Timedelta(days=84), recent.index[-1])
    have = recent.index[recent.index >= expected[0]]
    if len(have) < 0.75 * len(expected):
        return QualityReport(False, "too many missing sessions")
    return QualityReport(True)

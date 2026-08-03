"""Technical indicators (plain pandas, no external TA lib)."""
import pandas as pd
import numpy as np


def enrich(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    c = out["Close"]
    out["SMA50"] = c.rolling(50).mean()
    out["SMA200"] = c.rolling(200).mean()
    out["EMA20"] = c.ewm(span=20, adjust=False).mean()
    # RSI-14 (Wilder)
    delta = c.diff()
    gain = delta.clip(lower=0).ewm(alpha=1 / 14, adjust=False).mean()
    loss = (-delta.clip(upper=0)).ewm(alpha=1 / 14, adjust=False).mean()
    rs = gain / loss.replace(0, np.nan)
    out["RSI14"] = 100 - 100 / (1 + rs)
    # ATR-14 (Wilder)
    tr = pd.concat(
        [
            out["High"] - out["Low"],
            (out["High"] - c.shift()).abs(),
            (out["Low"] - c.shift()).abs(),
        ],
        axis=1,
    ).max(axis=1)
    out["ATR14"] = tr.ewm(alpha=1 / 14, adjust=False).mean()
    out["VOL50"] = out["Volume"].rolling(50).mean()
    out["HI52"] = out["High"].rolling(250, min_periods=100).max()
    out["LO52"] = out["Low"].rolling(250, min_periods=100).min()
    return out


def pivot_levels(df: pd.DataFrame, lookback: int = 240, window: int = 5, tol: float = 0.015):
    """Cluster swing highs/lows into support/resistance levels.

    Returns list of (level, strength) sorted ascending."""
    d = df.tail(lookback)
    highs, lows = d["High"], d["Low"]
    piv = []
    for i in range(window, len(d) - window):
        h = highs.iloc[i]
        if h == highs.iloc[i - window : i + window + 1].max():
            piv.append(h)
        l = lows.iloc[i]
        if l == lows.iloc[i - window : i + window + 1].min():
            piv.append(l)
    piv.sort()
    levels = []
    for p in piv:
        if levels and abs(p - levels[-1][0]) / levels[-1][0] < tol:
            lvl, n = levels[-1]
            levels[-1] = ((lvl * n + p) / (n + 1), n + 1)
        else:
            levels.append((p, 1))
    return [(round(l, 2), n) for l, n in levels]


def nearest_levels(levels, price):
    supports = [l for l in levels if l[0] < price]
    resistances = [l for l in levels if l[0] > price]
    sup = max(supports, key=lambda x: x[0]) if supports else None
    res = min(resistances, key=lambda x: x[0]) if resistances else None
    return sup, res

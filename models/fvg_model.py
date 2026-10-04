"""
fvg_model.py — Fair Value Gap (FVG / Imbalance) detection.

Bullish FVG : Low[i]  > High[i-2]   (gap between candle i-2 top and candle i bottom)
Bearish FVG : High[i] < Low[i-2]    (gap between candle i-2 bottom and candle i top)
"""

from dataclasses import dataclass
from typing import Optional

import pandas as pd

from config.settings import FVG_MIN_GAP_POINTS
from utils.logger import get_logger

log = get_logger(__name__)


@dataclass
class FVG:
    kind:       str        # "bullish" | "bearish"
    top:        float      # upper edge of the gap
    bottom:     float      # lower edge of the gap
    mid:        float      # midpoint (50% of gap)
    bar_index:  int        # index of the third candle (i)
    bar_time:   pd.Timestamp = None
    mitigated:  bool = False
    mitigation_bar: int = None


def detect_fvgs(df: pd.DataFrame,
                min_gap_points: int = FVG_MIN_GAP_POINTS,
                point_size: float = 0.01) -> list[FVG]:
    """
    Scan all bars and return a list of unmitigated FVGs.

    min_gap_points: minimum gap size expressed in points.
    point_size    : pip/point size for the instrument (e.g. 0.01 for XAUUSDm).
    """
    highs  = df["High"].values
    lows   = df["Low"].values
    times  = df.index
    fvgs: list[FVG] = []
    min_gap = min_gap_points * point_size

    for i in range(2, len(df)):
        # Bullish FVG: Low[i] > High[i-2]
        if lows[i] > highs[i - 2]:
            gap = lows[i] - highs[i - 2]
            if gap >= min_gap:
                fvgs.append(FVG(
                    kind="bullish",
                    top=lows[i],
                    bottom=highs[i - 2],
                    mid=(lows[i] + highs[i - 2]) / 2,
                    bar_index=i,
                    bar_time=times[i],
                ))

        # Bearish FVG: High[i] < Low[i-2]
        elif highs[i] < lows[i - 2]:
            gap = lows[i - 2] - highs[i]
            if gap >= min_gap:
                fvgs.append(FVG(
                    kind="bearish",
                    top=lows[i - 2],
                    bottom=highs[i],
                    mid=(lows[i - 2] + highs[i]) / 2,
                    bar_index=i,
                    bar_time=times[i],
                ))

    # Mark mitigated FVGs (price closed inside the gap)
    closes = df["Close"].values
    for fvg in fvgs:
        for j in range(fvg.bar_index + 1, len(df)):
            c = closes[j]
            if fvg.bottom <= c <= fvg.top:
                fvg.mitigated    = True
                fvg.mitigation_bar = j
                break

    return fvgs


def active_fvgs(fvgs: list[FVG]) -> list[FVG]:
    """Return only unmitigated FVGs."""
    return [f for f in fvgs if not f.mitigated]


def nearest_fvg(fvgs: list[FVG], price: float,
                direction: str) -> Optional[FVG]:
    """
    Find the closest active FVG in the trade direction.
    direction: "bullish" → look for bullish FVG below price
               "bearish" → look for bearish FVG above price
    """
    candidates = [
        f for f in active_fvgs(fvgs)
        if f.kind == direction
        and (f.top < price if direction == "bullish" else f.bottom > price)
    ]
    if not candidates:
        return None
    # Closest by mid-point distance
    return min(candidates, key=lambda f: abs(f.mid - price))

"""
structure_model.py — Swing high/low detection, market structure
(HH, HL, LH, LL), BOS, and CHoCH identification.
"""

from dataclasses import dataclass, field
from enum import Enum
from typing import Optional

import pandas as pd
import numpy as np

from config.settings import SWING_LOOKBACK
from utils.logger import get_logger

log = get_logger(__name__)


class StructureType(str, Enum):
    HH = "HH"
    HL = "HL"
    LH = "LH"
    LL = "LL"


class BreakType(str, Enum):
    BOS  = "BOS"
    CHOCH = "CHoCH"


@dataclass
class SwingPoint:
    index: int
    price: float
    kind:  str        # "high" | "low"
    bar_time: pd.Timestamp = None


@dataclass
class StructureLabel:
    index: int
    kind:  StructureType
    price: float
    bar_time: pd.Timestamp = None


@dataclass
class StructureBreak:
    bar_index:  int
    kind:       BreakType
    direction:  str          # "bullish" | "bearish"
    break_price: float
    bar_time:   pd.Timestamp = None


# ─── Swing detection ──────────────────────────────────────────────────────────

def find_swings(df: pd.DataFrame, n: int = SWING_LOOKBACK) -> list[SwingPoint]:
    """
    Classic pivot-point swing detection.
    High[i] > High[i-n:i] AND High[i] > High[i+1:i+n+1]
    Low[i]  < Low[i-n:i]  AND Low[i]  < Low[i+1:i+n+1]
    """
    swings: list[SwingPoint] = []
    highs = df["High"].values
    lows  = df["Low"].values
    times = df.index

    for i in range(n, len(df) - n):
        # Swing High
        if (highs[i] == max(highs[i - n: i + n + 1]) and
                highs[i] > highs[i - 1] and highs[i] > highs[i + 1]):
            swings.append(SwingPoint(i, highs[i], "high", times[i]))

        # Swing Low
        if (lows[i] == min(lows[i - n: i + n + 1]) and
                lows[i] < lows[i - 1] and lows[i] < lows[i + 1]):
            swings.append(SwingPoint(i, lows[i], "low", times[i]))

    return sorted(swings, key=lambda s: s.index)


# ─── Market structure labelling ───────────────────────────────────────────────

def label_structure(swings: list[SwingPoint]) -> list[StructureLabel]:
    """
    Walk through swing points and label HH/HL/LH/LL.
    """
    if len(swings) < 2:
        return []

    labels: list[StructureLabel] = []
    prev_high: Optional[SwingPoint] = None
    prev_low:  Optional[SwingPoint] = None

    for sw in swings:
        if sw.kind == "high":
            if prev_high is not None:
                kind = StructureType.HH if sw.price > prev_high.price else StructureType.LH
                labels.append(StructureLabel(sw.index, kind, sw.price, sw.bar_time))
            prev_high = sw
        else:
            if prev_low is not None:
                kind = StructureType.HL if sw.price > prev_low.price else StructureType.LL
                labels.append(StructureLabel(sw.index, kind, sw.price, sw.bar_time))
            prev_low = sw

    return labels


# ─── BOS / CHoCH detection ────────────────────────────────────────────────────

def detect_breaks(df: pd.DataFrame,
                  swings: list[SwingPoint]) -> list[StructureBreak]:
    """
    BOS  : candle closes beyond the last confirmed swing in the SAME direction.
    CHoCH: candle closes beyond a swing in the OPPOSITE direction (trend flip).
    """
    if len(swings) < 2:
        return []

    closes = df["Close"].values
    times  = df.index
    breaks: list[StructureBreak] = []

    last_high = next((s for s in reversed(swings) if s.kind == "high"), None)
    last_low  = next((s for s in reversed(swings) if s.kind == "low"),  None)

    # Determine prevailing trend from structure labels
    labels = label_structure(swings)
    bullish_bias = _last_bias(labels)   # True=bull, False=bear, None=undefined

    for i in range(1, len(df)):
        close = closes[i]

        # BOS Bullish: close > last swing high (continuation)
        if last_high and close > last_high.price and bullish_bias is True:
            breaks.append(StructureBreak(
                i, BreakType.BOS, "bullish", last_high.price, times[i]
            ))
            # update last_high to this bar's high conceptually
            last_high = SwingPoint(i, df["High"].values[i], "high", times[i])

        # BOS Bearish: close < last swing low
        elif last_low and close < last_low.price and bullish_bias is False:
            breaks.append(StructureBreak(
                i, BreakType.BOS, "bearish", last_low.price, times[i]
            ))
            last_low = SwingPoint(i, df["Low"].values[i], "low", times[i])

        # CHoCH: trend flip
        elif last_high and close > last_high.price and bullish_bias is False:
            breaks.append(StructureBreak(
                i, BreakType.CHOCH, "bullish", last_high.price, times[i]
            ))
            bullish_bias = True
            last_high = SwingPoint(i, df["High"].values[i], "high", times[i])

        elif last_low and close < last_low.price and bullish_bias is True:
            breaks.append(StructureBreak(
                i, BreakType.CHOCH, "bearish", last_low.price, times[i]
            ))
            bullish_bias = False
            last_low = SwingPoint(i, df["Low"].values[i], "low", times[i])

    return breaks


def _last_bias(labels: list[StructureLabel]) -> Optional[bool]:
    """Derive bullish/bearish from most recent HH/HL/LH/LL labels."""
    if not labels:
        return None
    last = labels[-1]
    if last.kind in (StructureType.HH, StructureType.HL):
        return True
    if last.kind in (StructureType.LH, StructureType.LL):
        return False
    return None


def get_market_bias(df: pd.DataFrame) -> Optional[str]:
    """
    High-level helper used by bias_engine.
    Returns 'bullish', 'bearish', or None.
    """
    swings = find_swings(df)
    labels = label_structure(swings)
    bias   = _last_bias(labels)
    if bias is True:
        return "bullish"
    if bias is False:
        return "bearish"
    return None

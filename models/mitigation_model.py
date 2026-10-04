"""
mitigation_model.py — Mitigation Block detection.

A Mitigation Block differs from a full OB:
  - Price PARTIALLY reacted to an OB (wick touched, did NOT close through).
  - The structure then shifted MILDLY (mini-BOS on a lower timeframe).
  - The zone retains relevance but with reduced strength vs a clean OB.

We identify these as OBs where:
  1. A wick entered the OB zone but the close remained outside.
  2. A short-term structure shift followed within N bars.
"""

from dataclasses import dataclass
from typing import Optional

import pandas as pd

from models.ob_model import OrderBlock, detect_order_blocks
from utils.logger import get_logger

log = get_logger(__name__)

WICK_ENTRY_BARS = 10   # look forward N bars for a wick entry


@dataclass
class MitigationBlock:
    kind:        str       # "bullish" | "bearish"
    top:         float
    bottom:      float
    mid:         float
    origin_ob:   OrderBlock
    wick_bar:    int       # bar where wick entered
    wick_time:   pd.Timestamp = None
    structure_shifted: bool = False
    mitigated:   bool = False


def detect_mitigations(df: pd.DataFrame) -> list[MitigationBlock]:
    """
    Detect mitigation blocks — partial OB reactions.
    """
    obs     = detect_order_blocks(df)
    highs   = df["High"].values
    lows    = df["Low"].values
    closes  = df["Close"].values
    times   = df.index
    results: list[MitigationBlock] = []

    for ob in obs:
        start = (ob.displaced_bar or ob.bar_index) + 1

        for i in range(start, min(start + WICK_ENTRY_BARS, len(df))):
            wick_entered = False

            if ob.kind == "bullish":
                # Wick dips into OB zone but closes above OB bottom
                if lows[i] <= ob.top and lows[i] >= ob.bottom and closes[i] > ob.bottom:
                    wick_entered = True
            else:
                # Wick pokes into OB zone but closes below OB top
                if highs[i] >= ob.bottom and highs[i] <= ob.top and closes[i] < ob.top:
                    wick_entered = True

            if not wick_entered:
                continue

            # Check for mini structure shift: a subsequent close beyond a recent high/low
            shifted = _mini_structure_shift(df, i, ob.kind)

            mb = MitigationBlock(
                kind=ob.kind,
                top=ob.top,
                bottom=ob.bottom,
                mid=ob.mid,
                origin_ob=ob,
                wick_bar=i,
                wick_time=times[i],
                structure_shifted=shifted,
            )
            results.append(mb)
            break   # one mitigation per OB

    # Mark mitigated (price closed through the zone)
    for mb in results:
        for j in range(mb.wick_bar + 1, len(df)):
            c = closes[j]
            if mb.bottom <= c <= mb.top:
                mb.mitigated = True
                break

    return results


def _mini_structure_shift(df: pd.DataFrame, from_bar: int,
                           direction: str, lookback: int = 5) -> bool:
    """
    True if within 'lookback' bars after from_bar there is a close that
    breaks the high (bullish) or low (bearish) of the prior lookback candles.
    """
    closes = df["Close"].values
    highs  = df["High"].values
    lows   = df["Low"].values

    if from_bar < lookback:
        return False

    ref_high = max(highs[from_bar - lookback: from_bar])
    ref_low  = min(lows[from_bar  - lookback: from_bar])

    for j in range(from_bar + 1, min(from_bar + lookback + 1, len(df))):
        if direction == "bullish" and closes[j] > ref_high:
            return True
        if direction == "bearish" and closes[j] < ref_low:
            return True
    return False


def active_mitigations(mbs: list[MitigationBlock]) -> list[MitigationBlock]:
    return [m for m in mbs if not m.mitigated]


def nearest_mitigation(mbs: list[MitigationBlock], price: float,
                        direction: str) -> Optional[MitigationBlock]:
    candidates = [
        m for m in active_mitigations(mbs)
        if m.kind == direction
        and (m.top < price if direction == "bullish" else m.bottom > price)
    ]
    if not candidates:
        return None
    return min(candidates, key=lambda m: abs(m.mid - price))

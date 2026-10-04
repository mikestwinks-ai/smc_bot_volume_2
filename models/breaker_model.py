"""
breaker_model.py — Breaker Block detection.

A Breaker Block is a FAILED Order Block:
  1. Price tapped an OB (mitigated it).
  2. Structure then flipped AGAINST the OB direction (it "failed").
  3. On the return, the old OB zone now acts as resistance/support in reverse.

Bullish Breaker: a bearish OB that was mitigated + price broke above → now acts as support.
Bearish Breaker: a bullish OB that was mitigated + price broke below → now acts as resistance.
"""

from dataclasses import dataclass
from typing import Optional

import pandas as pd

from models.ob_model import OrderBlock, detect_order_blocks, active_obs
from models.structure_model import find_swings, detect_breaks, BreakType
from utils.logger import get_logger

log = get_logger(__name__)


@dataclass
class BreakerBlock:
    kind:       str      # "bullish" | "bearish"
    top:        float
    bottom:     float
    mid:        float
    origin_ob:  OrderBlock
    flip_bar:   int      # bar where the structure flip confirmed it
    flip_time:  pd.Timestamp = None
    mitigated:  bool = False


def detect_breakers(df: pd.DataFrame) -> list[BreakerBlock]:
    """
    Detect breaker blocks by finding OBs that were mitigated
    followed by a CHoCH/BOS in the opposite direction.
    """
    obs    = detect_order_blocks(df)
    swings = find_swings(df)
    breaks = detect_breaks(df, swings)

    # Index breaks by bar for quick lookup
    break_map: dict[int, list] = {}
    for b in breaks:
        break_map.setdefault(b.bar_index, []).append(b)

    closes = df["Close"].values
    times  = df.index
    breakers: list[BreakerBlock] = []

    for ob in obs:
        if not ob.mitigated or ob.mitigation_bar is None:
            continue

        # Look for a structure break AFTER the OB mitigation that goes AGAINST the OB
        for bar_idx in range(ob.mitigation_bar + 1, len(df)):
            day_breaks = break_map.get(bar_idx, [])
            for br in day_breaks:
                if ob.kind == "bullish" and br.direction == "bearish":
                    # Bullish OB failed (price broke below) → becomes bearish breaker
                    breakers.append(BreakerBlock(
                        kind="bearish",
                        top=ob.top,
                        bottom=ob.bottom,
                        mid=ob.mid,
                        origin_ob=ob,
                        flip_bar=bar_idx,
                        flip_time=times[bar_idx],
                    ))
                    break

                elif ob.kind == "bearish" and br.direction == "bullish":
                    # Bearish OB failed → becomes bullish breaker
                    breakers.append(BreakerBlock(
                        kind="bullish",
                        top=ob.top,
                        bottom=ob.bottom,
                        mid=ob.mid,
                        origin_ob=ob,
                        flip_bar=bar_idx,
                        flip_time=times[bar_idx],
                    ))
                    break

    # Mark mitigated breakers (price re-enters the zone after flip)
    for bb in breakers:
        for j in range(bb.flip_bar + 1, len(df)):
            c = closes[j]
            if bb.bottom <= c <= bb.top:
                bb.mitigated = True
                break

    return breakers


def active_breakers(breakers: list[BreakerBlock]) -> list[BreakerBlock]:
    return [b for b in breakers if not b.mitigated]


def nearest_breaker(breakers: list[BreakerBlock], price: float,
                    direction: str) -> Optional[BreakerBlock]:
    candidates = [
        b for b in active_breakers(breakers)
        if b.kind == direction
        and (b.top < price if direction == "bullish" else b.bottom > price)
    ]
    if not candidates:
        return None
    return min(candidates, key=lambda b: abs(b.mid - price))

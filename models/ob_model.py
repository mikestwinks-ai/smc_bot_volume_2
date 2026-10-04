"""
ob_model.py — Order Block (OB) identification.

Definition (strict ICT):
  An Order Block is the LAST OPPOSITE-COLOUR candle immediately before
  a displacement candle that causes a BOS/CHoCH.

  Bullish OB → last bearish candle before a bullish displacement + BOS
  Bearish OB → last bullish candle before a bearish displacement + BOS
"""

from dataclasses import dataclass
from typing import Optional

import pandas as pd
import numpy as np

from config.settings import DISPLACEMENT_MULTIPLIER, DISPLACEMENT_LOOKBACK
from utils.logger import get_logger

log = get_logger(__name__)


@dataclass
class OrderBlock:
    kind:       str        # "bullish" | "bearish"
    top:        float
    bottom:     float
    mid:        float
    bar_index:  int
    bar_time:   pd.Timestamp = None
    displaced_bar: int = None   # the displacement candle that created it
    mitigated:  bool = False
    mitigation_bar: int = None


# ─── Displacement helper ──────────────────────────────────────────────────────

def _is_displacement(df: pd.DataFrame, i: int,
                     multiplier: float = DISPLACEMENT_MULTIPLIER,
                     lookback: int = DISPLACEMENT_LOOKBACK) -> bool:
    """
    Return True if candle i body >= multiplier × average body of prior lookback bars.
    """
    if i < lookback + 1:
        return False
    opens  = df["Open"].values
    closes = df["Close"].values
    body_i = abs(closes[i] - opens[i])
    avg_body = np.mean([
        abs(closes[j] - opens[j])
        for j in range(i - lookback, i)
    ])
    return avg_body > 0 and body_i >= multiplier * avg_body


# ─── OB detection ─────────────────────────────────────────────────────────────

def detect_order_blocks(df: pd.DataFrame,
                        swing_highs: list = None,
                        swing_lows:  list = None) -> list[OrderBlock]:
    """
    Scan bars for order blocks.
    We look for:
      1. A displacement candle (body ≥ 1.5× avg).
      2. Price closing beyond a recent swing (BOS signal within this function).
      3. The last opposite-colour candle BEFORE that displacement candle → OB.
    """
    opens  = df["Open"].values
    closes = df["Close"].values
    highs  = df["High"].values
    lows   = df["Low"].values
    times  = df.index
    obs: list[OrderBlock] = []

    for i in range(DISPLACEMENT_LOOKBACK + 2, len(df)):
        if not _is_displacement(df, i):
            continue

        bullish_disp = closes[i] > opens[i]   # bullish displacement candle

        if bullish_disp:
            # Look back for the last bearish candle → bullish OB
            for j in range(i - 1, max(i - 15, 0), -1):
                if closes[j] < opens[j]:   # bearish candle
                    obs.append(OrderBlock(
                        kind="bullish",
                        top=opens[j],
                        bottom=lows[j],
                        mid=(opens[j] + lows[j]) / 2,
                        bar_index=j,
                        bar_time=times[j],
                        displaced_bar=i,
                    ))
                    break
        else:
            # Bearish displacement → bearish OB is last bullish candle before it
            for j in range(i - 1, max(i - 15, 0), -1):
                if closes[j] > opens[j]:   # bullish candle
                    obs.append(OrderBlock(
                        kind="bearish",
                        top=highs[j],
                        bottom=opens[j],
                        mid=(highs[j] + opens[j]) / 2,
                        bar_index=j,
                        bar_time=times[j],
                        displaced_bar=i,
                    ))
                    break

    # Mark mitigated OBs (price closed inside the OB zone)
    for ob in obs:
        for j in range(ob.displaced_bar + 1 if ob.displaced_bar else ob.bar_index + 1,
                       len(df)):
            c = closes[j]
            if ob.bottom <= c <= ob.top:
                ob.mitigated    = True
                ob.mitigation_bar = j
                break

    return obs


def active_obs(obs: list[OrderBlock]) -> list[OrderBlock]:
    return [o for o in obs if not o.mitigated]


def nearest_ob(obs: list[OrderBlock], price: float,
               direction: str) -> Optional[OrderBlock]:
    """Closest active OB in the given direction relative to current price."""
    candidates = [
        o for o in active_obs(obs)
        if o.kind == direction
        and (o.top < price if direction == "bullish" else o.bottom > price)
    ]
    if not candidates:
        return None
    return min(candidates, key=lambda o: abs(o.mid - price))

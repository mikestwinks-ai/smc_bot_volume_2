"""
liquidity_model.py — Equal highs/lows (liquidity pools) and liquidity sweep detection.
"""

from dataclasses import dataclass
from typing import Optional

import pandas as pd
import numpy as np

from config.settings import LIQUIDITY_TOLERANCE_PCT
from models.structure_model import SwingPoint, find_swings
from utils.logger import get_logger

log = get_logger(__name__)


@dataclass
class LiquidityPool:
    kind:        str      # "buy_side" (equal highs) | "sell_side" (equal lows)
    price:       float    # average level of the pool
    bar_indices: list[int] = None
    swept:       bool = False
    sweep_bar:   int  = None
    sweep_time:  pd.Timestamp = None


@dataclass
class LiquiditySweep:
    kind:       str       # "buy_side_sweep" | "sell_side_sweep"
    pool_price: float
    sweep_bar:  int
    wick_low:   float = None   # for sell-side sweep
    wick_high:  float = None   # for buy-side sweep
    close:      float = None
    bar_time:   pd.Timestamp = None


# ─── Pool identification ──────────────────────────────────────────────────────

def find_liquidity_pools(df: pd.DataFrame,
                         tolerance: float = LIQUIDITY_TOLERANCE_PCT
                         ) -> list[LiquidityPool]:
    """
    Find equal highs (buy-side liquidity) and equal lows (sell-side liquidity).
    Two swing points are "equal" when |p1 - p2| / avg < tolerance.
    """
    swings = find_swings(df)
    highs  = [s for s in swings if s.kind == "high"]
    lows   = [s for s in swings if s.kind == "low"]

    pools: list[LiquidityPool] = []

    # Equal highs → buy-side liquidity (stops sitting above)
    for i in range(len(highs)):
        for j in range(i + 1, len(highs)):
            avg = (highs[i].price + highs[j].price) / 2
            if avg == 0:
                continue
            diff_pct = abs(highs[i].price - highs[j].price) / avg
            if diff_pct <= tolerance:
                pools.append(LiquidityPool(
                    kind="buy_side",
                    price=avg,
                    bar_indices=[highs[i].index, highs[j].index],
                ))

    # Equal lows → sell-side liquidity (stops sitting below)
    for i in range(len(lows)):
        for j in range(i + 1, len(lows)):
            avg = (lows[i].price + lows[j].price) / 2
            if avg == 0:
                continue
            diff_pct = abs(lows[i].price - lows[j].price) / avg
            if diff_pct <= tolerance:
                pools.append(LiquidityPool(
                    kind="sell_side",
                    price=avg,
                    bar_indices=[lows[i].index, lows[j].index],
                ))

    return pools


# ─── Sweep detection ──────────────────────────────────────────────────────────

def detect_sweeps(df: pd.DataFrame,
                  pools: list[LiquidityPool] = None) -> list[LiquiditySweep]:
    """
    A sweep is confirmed when:
      - The wick breaches the pool level
      - The candle CLOSES back on the other side (the "trap")
    """
    if pools is None:
        pools = find_liquidity_pools(df)

    highs  = df["High"].values
    lows   = df["Low"].values
    closes = df["Close"].values
    times  = df.index
    sweeps: list[LiquiditySweep] = []

    for pool in pools:
        max_bar = max(pool.bar_indices) if pool.bar_indices else 0

        for i in range(max_bar + 1, len(df)):
            if pool.kind == "buy_side":
                # Wick breaks ABOVE the pool but close is BELOW
                if highs[i] > pool.price and closes[i] < pool.price:
                    pool.swept       = True
                    pool.sweep_bar   = i
                    pool.sweep_time  = times[i]
                    sweeps.append(LiquiditySweep(
                        kind="buy_side_sweep",
                        pool_price=pool.price,
                        sweep_bar=i,
                        wick_high=highs[i],
                        close=closes[i],
                        bar_time=times[i],
                    ))
                    break   # one sweep per pool

            else:  # sell_side
                # Wick breaks BELOW the pool but close is ABOVE
                if lows[i] < pool.price and closes[i] > pool.price:
                    pool.swept       = True
                    pool.sweep_bar   = i
                    pool.sweep_time  = times[i]
                    sweeps.append(LiquiditySweep(
                        kind="sell_side_sweep",
                        pool_price=pool.price,
                        sweep_bar=i,
                        wick_low=lows[i],
                        close=closes[i],
                        bar_time=times[i],
                    ))
                    break

    return sweeps


def latest_sweep(sweeps: list[LiquiditySweep]) -> Optional[LiquiditySweep]:
    return sweeps[-1] if sweeps else None

"""
bias_engine.py — H4 directional bias determination.

Combines market structure, liquidity sweeps, BOS/CHoCH on H4
to produce a single "bullish" or "bearish" bias with a confidence score.
"""

from dataclasses import dataclass
from typing import Optional

import pandas as pd

from models.structure_model import (
    find_swings, label_structure, detect_breaks,
    StructureType, BreakType, get_market_bias
)
from models.liquidity_model import find_liquidity_pools, detect_sweeps
from config import settings
from utils.logger import get_logger

log = get_logger(__name__)


@dataclass
class BiasResult:
    direction: Optional[str]    # "bullish" | "bearish" | None
    score:     float            # 0–10
    reasons:   list[str]


def compute_h4_bias(df_h4: pd.DataFrame) -> BiasResult:
    """
    Analyse the H4 chart and return directional bias + confidence.

    Scoring:
      +3  Last CHoCH direction
      +2  Last BOS direction
      +1  Overall swing structure (HH/HL vs LH/LL)
      +2  Liquidity sweep supports direction
      Total max: 8 (normalised to 0–10)
    """
    from execution.startup_gate import is_trading_ready

    if not is_trading_ready():
        return BiasResult(direction=None, score=0.0, reasons=["MT5 reconciliation not complete"])

    reasons: list[str] = []
    votes: dict[str, float] = {"bullish": 0.0, "bearish": 0.0}

    # ── 1. Market structure ───────────────────────────────────────────
    structure_bias = get_market_bias(df_h4)
    if structure_bias:
        votes[structure_bias] += 1
        reasons.append(f"Structure bias: {structure_bias}")
    else:
        reasons.append("Structure bias: undefined")

    # ── 2. BOS / CHoCH ───────────────────────────────────────────────
    swings = find_swings(df_h4)
    breaks = detect_breaks(df_h4, swings)

    if breaks:
        last_break = breaks[-1]
        if last_break.kind == BreakType.CHOCH:
            votes[last_break.direction] += 3
            reasons.append(
                f"CHoCH {last_break.direction} @ {last_break.break_price:.2f} "
                f"(bar {last_break.bar_index})"
            )
        elif last_break.kind == BreakType.BOS:
            votes[last_break.direction] += 2
            reasons.append(
                f"BOS {last_break.direction} @ {last_break.break_price:.2f}"
            )
    else:
        reasons.append("No BOS/CHoCH detected on H4")

    # ── 3. Liquidity sweep alignment ─────────────────────────────────
    pools  = find_liquidity_pools(df_h4)
    sweeps = detect_sweeps(df_h4, pools)

    if sweeps:
        last_sweep = sweeps[-1]
        # A buy-side sweep (stops hunted above) is bearish after sweep
        # A sell-side sweep (stops hunted below) is bullish after sweep
        sweep_dir = (
            "bullish" if last_sweep.kind == "sell_side_sweep"
            else "bearish"
        )
        votes[sweep_dir] += 2
        reasons.append(
            f"Liquidity sweep: {last_sweep.kind} @ {last_sweep.pool_price:.2f} "
            f"→ bias {sweep_dir}"
        )
    else:
        reasons.append("No liquidity sweep on H4")

    # ── Determine winner ─────────────────────────────────────────────
    bull_score = votes["bullish"]
    bear_score = votes["bearish"]
    total      = bull_score + bear_score

    if total == 0:
        log.debug("H4 bias: no signal")
        return BiasResult(None, 0.0, reasons)

    if bull_score > bear_score:
        direction = "bullish"
        confidence = round((bull_score / total) * 10, 1)
    elif bear_score > bull_score:
        direction = "bearish"
        confidence = round((bear_score / total) * 10, 1)
    else:
        # Tie — no clear bias
        direction = None
        confidence = 5.0
        reasons.append("Tied bias — no clear direction")

    log.info(
        f"H4 Bias: {direction} | Confidence: {confidence}/10 | "
        + " | ".join(reasons)
    )
    return BiasResult(direction, confidence, reasons)

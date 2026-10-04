"""
confluence_engine.py — Scoring system for trade signals.

Aggregates evidence from all models and sessions into a single score.
A trade is only considered when score meets the threshold.

Score table:
  HTF Bias      → +2
  Liquidity Sweep → +2
  Displacement    → +2
  OB              → +1
  FVG             → +1
  Breaker         → +2
  CHoCH           → +1
  ─────────────────────
  Maximum          11

Thresholds (from settings):
  ≥ 6           → always trade
  = 5           → only during NY Overlap (16:00–19:00 EAT)
  < 5           → no trade
"""

from dataclasses import dataclass, field
from typing import Optional

import pandas as pd

from models.ob_model import detect_order_blocks, nearest_ob, OrderBlock
from models.fvg_model import detect_fvgs, nearest_fvg, FVG
from models.breaker_model import detect_breakers, nearest_breaker, BreakerBlock
from models.mitigation_model import detect_mitigations, nearest_mitigation
from models.structure_model import find_swings, detect_breaks, BreakType
from models.liquidity_model import find_liquidity_pools, detect_sweeps, LiquiditySweep
from models.ob_model import _is_displacement
from strategy.bias_engine import BiasResult
from config.sessions import is_ny_overlap
from config import settings
from utils.logger import get_logger, log_no_trade, log_trade_signal

log = get_logger(__name__)


@dataclass
class ConfluenceResult:
    trade:      bool = False
    direction:  Optional[str] = None
    score:      float = 0.0
    breakdown:  dict  = field(default_factory=dict)
    poi_type:   str   = ""          # "OB" | "FVG" | "Breaker" | "Mitigation"
    poi_top:    float = 0.0
    poi_bottom: float = 0.0
    poi_mid:    float = 0.0
    sweep:      Optional[LiquiditySweep] = None
    displacement_ratio: float = 0.0
    session:    str = ""
    reason_no_trade: str = ""


def score_confluence(
    df_m15: pd.DataFrame,
    df_m5:  pd.DataFrame,
    bias:   BiasResult,
    session: str,
    df_h4: pd.DataFrame = None,
) -> ConfluenceResult:
    """
    Full scoring pipeline on M15/M5 given an H4 bias.
    Includes market context adjustment (premium/discount awareness).
    Returns a ConfluenceResult.
    
    Args:
        df_m15: M15 candle data
        df_m5: M5 candle data
        bias: H4 bias result
        session: current session name
        df_h4: H4 candle data (for market context calculation)
    """
    from execution.startup_gate import is_trading_ready

    if not is_trading_ready():
        return ConfluenceResult(
            session=session,
            reason_no_trade="MT5 reconciliation not complete",
        )

    result = ConfluenceResult(session=session)
    breakdown: dict[str, float] = {}
    direction = bias.direction

    # No bias → no trade
    if direction is None:
        result.reason_no_trade = "No H4 bias"
        log_no_trade(log, result.reason_no_trade, score=0)
        return result

    # ── Market Context (premium/discount) ────────────────────────────
    # Get current price for market context
    market_context = {'zone': 'unknown'}
    try:
        current_price = df_m5.iloc[-1]['Close']
        
        # Use H4 data if provided, fallback to M15
        h4_data = df_h4 if df_h4 is not None else df_m15
        if h4_data is None or len(h4_data) < 3:
            log.warning(
                f"MARKET CONTEXT | Insufficient H4 data (len={len(h4_data) if h4_data is not None else 0}) | "
                f"Cannot classify zone"
            )
            market_context = {'zone': 'unknown'}
        else:
            market_context = calculate_market_context(current_price, h4_data)
            
            # If still unknown, add diagnostic logging
            if market_context.get('zone') == 'unknown':
                log.warning(
                    f"MARKET CONTEXT | Classification failed | Current price: {current_price:.2f} | "
                    f"H4 data length: {len(h4_data)} | Verify Asian session extraction"
                )
    except Exception as e:
        log.error(f"MARKET CONTEXT | Calculation error: {e} | Defaulting to unknown")
        market_context = {'zone': 'unknown'}

    # ── 1. HTF Bias ──────────────────────────────────────────────────
    breakdown["HTF_Bias"] = 2.0
    result.score += 2.0

    # ── 2. Liquidity sweep (M15) ──────────────────────────────────────
    pools_m15  = find_liquidity_pools(df_m15)
    sweeps_m15 = detect_sweeps(df_m15, pools_m15)
    valid_sweeps = [
        s for s in sweeps_m15
        if (direction == "bullish" and s.kind == "sell_side_sweep")
        or (direction == "bearish" and s.kind == "buy_side_sweep")
    ]
    if valid_sweeps:
        result.sweep = valid_sweeps[-1]
        breakdown["Liquidity_Sweep"] = 2.0
        result.score += 2.0
    else:
        breakdown["Liquidity_Sweep"] = 0.0

    # ── 3. Displacement (M5) ─────────────────────────────────────────
    disp_ratio = _latest_displacement_ratio(df_m5, direction)
    result.displacement_ratio = disp_ratio
    if disp_ratio >= settings.DISPLACEMENT_MULTIPLIER:
        breakdown["Displacement"] = 2.0
        result.score += 2.0
    else:
        breakdown["Displacement"] = 0.0

    # ── 4. Order Block (M15) ─────────────────────────────────────────
    obs_m15  = detect_order_blocks(df_m15)
    tick     = df_m15["Close"].iloc[-1]
    best_ob  = nearest_ob(obs_m15, tick, direction)
    if best_ob:
        breakdown["OB"] = 1.0
        result.score   += 1.0
        _set_poi(result, "OB", best_ob.top, best_ob.bottom, best_ob.mid)

    # ── 5. FVG (M15) ─────────────────────────────────────────────────
    fvgs_m15 = detect_fvgs(df_m15)
    best_fvg = nearest_fvg(fvgs_m15, tick, direction)
    if best_fvg:
        breakdown["FVG"] = 1.0
        result.score   += 1.0
        if not best_ob:   # prefer OB as POI; use FVG only if no OB
            _set_poi(result, "FVG", best_fvg.top, best_fvg.bottom, best_fvg.mid)

    # ── 6. Breaker Block (M15) ───────────────────────────────────────
    breakers_m15 = detect_breakers(df_m15)
    best_bb      = nearest_breaker(breakers_m15, tick, direction)
    if best_bb:
        breakdown["Breaker"] = 2.0
        result.score        += 2.0
        if result.poi_type == "":
            _set_poi(result, "Breaker", best_bb.top, best_bb.bottom, best_bb.mid)

    # ── 7. CHoCH (M5) ────────────────────────────────────────────────
    swings_m5 = find_swings(df_m5)
    breaks_m5 = detect_breaks(df_m5, swings_m5)
    choch_m5  = [
        b for b in breaks_m5
        if b.kind == BreakType.CHOCH and b.direction == direction
    ]
    if choch_m5:
        breakdown["CHoCH"] = 1.0
        result.score      += 1.0
    else:
        breakdown["CHoCH"] = 0.0

    result.breakdown  = breakdown
    result.direction  = direction

    # ── Decision ─────────────────────────────────────────────────────
    threshold = settings.MIN_SCORE_ALWAYS
    if result.poi_type == "":
        result.reason_no_trade = "No valid POI found (OB/FVG/Breaker)"
        log_no_trade(log, result.reason_no_trade, result.score, breakdown)
        return result

    if result.score >= threshold:
        result.trade = True
    elif result.score == settings.MIN_SCORE_NY_ONLY and is_ny_overlap():
        result.trade = True
        log.info("Score=5 accepted due to NY Overlap session")
    else:
        result.reason_no_trade = (
            f"Score {result.score} below threshold {threshold} "
            f"(NY Overlap: {is_ny_overlap()})"
        )
        log_no_trade(log, result.reason_no_trade, result.score, breakdown)

    if result.trade:
        # Add market context to signal logging
        context_str = f"Zone: {market_context.get('zone', 'unknown')}"
        if market_context.get('zone') != 'unknown':
            context_str += f" | Range: [{market_context.get('asian_low', 0):.2f}–{market_context.get('asian_high', 0):.2f}]"
        
        log_trade_signal(
            log,
            direction=direction,
            score=result.score,
            breakdown=breakdown,
            poi=f"{result.poi_type} [{result.poi_bottom:.2f}–{result.poi_top:.2f}]",
            session=session,
            sweep=str(result.sweep.kind) if result.sweep else "None",
            displacement=disp_ratio,
        )
        log.info(f"MARKET CONTEXT | {context_str}")

    return result


# ─── Helpers ─────────────────────────────────────────────────────────────────

def _latest_displacement_ratio(df: pd.DataFrame, direction: str) -> float:
    """
    Find the displacement ratio of the most recent qualifying displacement
    candle in the given direction on df.
    Returns 0.0 if none found in last 10 bars.
    """
    import numpy as np
    opens  = df["Open"].values
    closes = df["Close"].values
    n      = settings.DISPLACEMENT_LOOKBACK

    for i in range(len(df) - 1, n, -1):
        body = abs(closes[i] - opens[i])
        avg  = float(np.mean([abs(closes[j] - opens[j]) for j in range(i - n, i)]))
        if avg == 0:
            continue
        ratio = body / avg
        # Direction filter
        if direction == "bullish" and closes[i] > opens[i] and ratio >= settings.DISPLACEMENT_MULTIPLIER:
            return ratio
        if direction == "bearish" and closes[i] < opens[i] and ratio >= settings.DISPLACEMENT_MULTIPLIER:
            return ratio
    return 0.0


def _set_poi(result: ConfluenceResult, poi_type: str,
             top: float, bottom: float, mid: float) -> None:
    result.poi_type   = poi_type
    result.poi_top    = top
    result.poi_bottom = bottom
    result.poi_mid    = mid


def calculate_market_context(current_price: float, df_h4: pd.DataFrame) -> dict:
    """
    Calculate market positioning context (premium/discount).
    Uses Asian session high/low as equilibrium range.
    
    Returns dict with keys:
      - 'zone': 'premium' | 'discount' | 'equilibrium'
      - 'asian_high': H4 session high
      - 'asian_low': H4 session low
      - 'midpoint': session midpoint
      - 'distance_from_midpoint': price distance to midpoint
    """
    from config.sessions import get_asian_session_context
    
    context = get_asian_session_context(df_h4)
    if not context:
        return {'zone': 'unknown'}
    
    asian_high = context['asian_high']
    asian_low = context['asian_low']
    midpoint = context['asian_midpoint']
    range_size = context['asian_range']
    
    # Classify position relative to Asian range
    if current_price > asian_high:
        zone = 'premium'
    elif current_price < asian_low:
        zone = 'discount'
    else:
        zone = 'equilibrium'
    
    distance_from_midpoint = current_price - midpoint
    
    return {
        'zone': zone,
        'asian_high': asian_high,
        'asian_low': asian_low,
        'midpoint': midpoint,
        'distance_from_midpoint': distance_from_midpoint,
        'range_size': range_size,
    }

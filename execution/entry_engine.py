"""
entry_engine.py — Trade entry construction and order submission.

Entry conditions (M5):
  1. Price taps POI
  2. Mini BOS on M5 confirms direction
  3. Displacement candle confirms entry

TRADE CONTROL LAYER:
  - Prevents duplicate trades on same symbol+direction
  - Tracks active open positions per symbol
  - Enforces cooldown period between entries (optional)
"""

from dataclasses import dataclass
from typing import Optional
import time

import MetaTrader5 as mt5
import pandas as pd

from config import settings
from strategy.confluence_engine import ConfluenceResult
from models.structure_model import find_swings, detect_breaks, BreakType
from models.ob_model import _is_displacement
from execution.risk_manager import calculate_lot_size, increment_trade_count
from utils import mt5_connector as conn
from utils.logger import get_logger, log_trade_open

log = get_logger(__name__)

# SL buffer in points beyond POI edge
SL_BUFFER_POINTS = 30

# Trade control: cooldown trackers
_LAST_ENTRY_TIME = {}  # symbol_direction -> entry timestamp
_LAST_EXIT_TIME = {}   # symbol_direction -> (exit_timestamp, exit_reason, cooldown_seconds)

# Cooldown durations by exit reason (in seconds)
EXIT_COOLDOWN_DURATIONS = {
    "TP": 600,           # 10 minutes after TP hit
    "SL": 900,           # 15 minutes after SL hit  
    "BE": 900,           # 15 minutes after BE stop hit
    "TIME_RULE": 900,    # 15 minutes after time-based close
    "FORCE_CLOSE": 900,  # 15 minutes after force close
}

ENTRY_COOLDOWN_SECONDS = 300  # 5-minute cooldown after opening a trade (legacy, will be deprecated)


def initialize_cooldown_from_persistence() -> None:
    """
    Called on bot startup to restore active cooldowns from persistence.
    Prevents restart from bypassing revenge-trading cooldown.
    """
    global _LAST_EXIT_TIME
    from execution.state_persistence import load_cooldown_state
    
    restored = load_cooldown_state()
    if restored:
        _LAST_EXIT_TIME.update(restored)
        log.info(f"COOLDOWN INITIALIZATION | Restored {len(restored)} active cooldown(s) from persistence")
    else:
        log.info("COOLDOWN INITIALIZATION | No active cooldowns to restore")


@dataclass
class EntryResult:
    executed:  bool  = False
    blocked:   bool  = False  # True if trade was blocked (not rejected)
    ticket:    int   = 0
    direction: str   = ""
    entry:     float = 0.0
    sl:        float = 0.0
    tp:        float = 0.0
    lots:      float = 0.0
    sl_points: float = 0.0
    reason:    str   = ""


# ─── Trade Control Layer ──────────────────────────────────────────────────

def _calculate_atr(df: pd.DataFrame, period: int = 14) -> float:
    """
    Calculate Average True Range (ATR) for volatility assessment.
    
    Returns ATR in price units (not points).
    Used for dynamic entry buffer sizing.
    """
    # Validation: Check data integrity
    if df is None or len(df) < period + 1:
        return 0.0
    
    required_cols = {"High", "Low", "Close"}
    if not required_cols.issubset(df.columns):
        return 0.0
    
    try:
        # Calculate True Range using fully vectorized operations (no row-wise apply)
        prev_close = df["Close"].shift(1)
        tr1 = df["High"] - df["Low"]
        tr2 = abs(df["High"] - prev_close)
        tr3 = abs(df["Low"] - prev_close)
        
        # Element-wise max across the three TR components
        true_range = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
        
        # Calculate ATR as rolling average of True Range
        atr_series = true_range.rolling(window=period).mean()
        
        # Return latest ATR value (skip NaN values from rolling window)
        atr_value = atr_series.iloc[-1]
        
        # Return 0.0 if NaN or invalid
        return float(atr_value) if not pd.isna(atr_value) else 0.0
        
    except Exception as e:
        # Graceful fallback: log warning and return 0.0 (triggers static buffer fallback)
        return 0.0


def _calculate_dynamic_entry_buffer(
    df_m5: pd.DataFrame,
    disp_ratio: float,
    point: float,
    direction: str
) -> tuple[float, str]:
    """
    Calculate dynamic entry buffer based on ATR volatility.
    
    Returns: (buffer_in_price_units, buffer_label)
    
    Logic:
    - Low displacement + low volatility → tight buffer (0.1-0.3 ATR)
    - Medium displacement + medium volatility → moderate buffer (0.2-0.5 ATR)
    - High displacement + high volatility → loose buffer (0.5-0.8 ATR)
    """
    atr = _calculate_atr(df_m5, period=14)
    if atr <= 0:
        # Fallback to displacement-based buffer if ATR unavailable
        if disp_ratio >= 2.5:
            return 0.12, "VERY_STRONG"  # 120 pts equivalent
        elif disp_ratio >= 2.0:
            return 0.08, "STRONG"  # 80 pts equivalent
        elif disp_ratio >= 1.5:
            return 0.06, "MEDIUM"  # 60 pts equivalent
        else:
            return 0.04, "WEAK"  # 40 pts equivalent
    
    # ATR-based buffer calculation
    # Stronger displacement = higher ATR multiplier
    if disp_ratio >= 2.5:
        atr_multiplier = 0.65  # HIGH volatility tolerance
        label = "VERY_STRONG"
    elif disp_ratio >= 2.0:
        atr_multiplier = 0.50  # MEDIUM-HIGH tolerance
        label = "STRONG"
    elif disp_ratio >= 1.5:
        atr_multiplier = 0.35  # MEDIUM tolerance
        label = "MEDIUM"
    else:
        atr_multiplier = 0.20  # LOW tolerance (preserve precision)
        label = "WEAK"
    
    buffer = atr * atr_multiplier
    
    log.debug(
        f"ATR Buffer | ATR: {atr:.4f} | Displacement: {disp_ratio:.2f}x | "
        f"Multiplier: {atr_multiplier} | Buffer: {buffer:.4f} ({buffer/point:.0f} pts) | "
        f"Label: {label}"
    )
    
    return buffer, label


# ─── Trade Control Layer ──────────────────────────────────────────────────

def _format_trade_duration(time_msc: float) -> str:
    """
    Convert MT5 time_msc (milliseconds since epoch) to human-readable duration.
    Shows "Open For: XXm YYs" format.
    
    Args:
        time_msc: MT5 position.time_msc value (milliseconds since epoch)
    
    Returns:
        Formatted string like "Open For: 5m 32s" or "Open Since: 2026-05-25 13:04 UTC"
    """
    import time as time_module
    from datetime import datetime, timezone
    
    try:
        # time_msc is in milliseconds, convert to seconds
        time_sec = time_msc / 1000.0
        
        # Calculate duration (current time - open time)
        current_time = time_module.time()
        duration_sec = max(0, current_time - time_sec)
        
        # Format as "Open For: XXm YYs"
        minutes = int(duration_sec // 60)
        seconds = int(duration_sec % 60)
        
        if minutes > 0:
            return f"For {minutes}m {seconds}s"
        else:
            return f"For {seconds}s"
    except:
        # Fallback: show raw value on error
        return f"{time_msc} ms"


def _check_active_position(symbol: str, direction: str) -> tuple[bool, str]:
    """
    Check if there's already an open position for this symbol in the same direction.
    
    Returns: (has_active_position, reason_if_blocked)
      - (True, "TRADE BLOCKED | ...") if position exists
      - (False, "") if no position or can proceed
    """
    try:
        # Get all open positions for this symbol with our magic number
        positions = conn.get_open_positions(symbol=symbol, magic=settings.MAGIC)
        
        if not positions:
            # No active position at all
            return False, ""
        
        # Check if ANY position matches our direction
        for pos in positions:
            pos_direction = "bullish" if pos.type == mt5.ORDER_TYPE_BUY else "bearish"
            
            if pos_direction == direction:
                # Found active position in same direction
                open_duration = _format_trade_duration(pos.time_msc)
                reason = (
                    f"TRADE BLOCKED | Existing position in same direction | "
                    f"Symbol: {symbol} | Direction: {direction.upper()} | "
                    f"Ticket: {pos.ticket} | Entry: {pos.price_open:.2f} | "
                    f"Open: {open_duration}"
                )
                log.warning(reason)
                return True, reason
        
        # Positions exist but in opposite direction (could be hedging, etc.)
        return False, ""
        
    except Exception as e:
        log.error(f"Error checking active positions for {symbol}: {e}", exc_info=True)
        # On error, allow entry to proceed (fail open, not closed)
        return False, ""


def _check_cooldown(symbol: str, direction: str) -> tuple[bool, str]:
    """
    Cooldown check using LAST EXIT TIME as primary source (with reason-based durations),
    falls back to ENTRY TIME only if no prior exit exists.
    
    Returns: (is_in_cooldown, reason_if_blocked)
      - (True, "reason...") if cooldown active
      - (False, "") if cooldown expired or no prior trade
    """
    key = f"{symbol}_{direction}"
    
    # Check LAST EXIT TIME first (primary cooldown source)
    if key in _LAST_EXIT_TIME:
        exit_time, exit_reason, cooldown_secs = _LAST_EXIT_TIME[key]
        elapsed = time.time() - exit_time
        remaining = cooldown_secs - elapsed
        
        if elapsed < cooldown_secs:
            reason = (
                f"TRADE BLOCKED | Exit cooldown active | Symbol: {symbol} | Direction: {direction.upper()} | "
                f"Exit reason: {exit_reason} | Remaining: {remaining:.1f}s / {cooldown_secs}s"
            )
            log.warning(reason)
            return True, reason
        else:
            # Cooldown expired, clean up old entry
            _LAST_EXIT_TIME.pop(key, None)
            _LAST_ENTRY_TIME.pop(key, None)
            return False, ""
    
    # Fallback to ENTRY TIME only if no prior exit exists
    if key in _LAST_ENTRY_TIME:
        last_entry = _LAST_ENTRY_TIME[key]
        elapsed = time.time() - last_entry
        remaining = ENTRY_COOLDOWN_SECONDS - elapsed
        
        if elapsed < ENTRY_COOLDOWN_SECONDS:
            reason = (
                f"TRADE BLOCKED | Entry cooldown active | Symbol: {symbol} | Direction: {direction.upper()} | "
                f"Remaining: {remaining:.1f}s / {ENTRY_COOLDOWN_SECONDS}s"
            )
            log.warning(reason)
            return True, reason
    
    return False, ""


def register_trade_exit(symbol: str, direction: str, exit_reason: str) -> None:
    """
    CALLBACK from trade_manager: Register a trade exit with reason-based cooldown.
    Called when trade closes (TP, SL, BE, time rule, force close, etc).
    
    Args:
        symbol: Trading symbol (e.g. "XAUUSDm")
        direction: "bullish" or "bearish"
        exit_reason: Reason for exit (TP, SL, BE, TIME_RULE, FORCE_CLOSE, etc)
    
    Updates _LAST_EXIT_TIME with exit timestamp and reason-based cooldown duration.
    PERSISTS cooldown state so restart cannot bypass protection.
    """
    key = f"{symbol}_{direction}"
    
    # Get cooldown duration for this exit reason
    cooldown_secs = EXIT_COOLDOWN_DURATIONS.get(exit_reason, 900)  # Default 15 min
    
    # Register exit with timestamp, reason, and cooldown duration
    _LAST_EXIT_TIME[key] = (time.time(), exit_reason, cooldown_secs)
    
    # Remove stale entry time since we now track exits
    _LAST_ENTRY_TIME.pop(key, None)
    
    # ── PERSIST COOLDOWN STATE ───────────────────────────────────────────
    from execution.state_persistence import save_cooldown_state
    save_cooldown_state(_LAST_EXIT_TIME)
    
    # ── EXPLICIT EXIT COOLDOWN LOGGING ────────────────────────────────────
    log.warning(
        f"EXIT REGISTERED | Symbol: {symbol} | Direction: {direction.upper()} | "
        f"Reason: {exit_reason} | Cooldown: {cooldown_secs}s ({cooldown_secs//60}m) | "
        f"Next entry available at: +{cooldown_secs}s"
    )


def attempt_entry(
    confluence: ConfluenceResult,
    df_m5: pd.DataFrame,
    symbol: str = settings.SYMBOL,
) -> EntryResult:
    """
    Trade entry with displacement-based confirmation hierarchy.

    Entry confirmation is CONDITIONAL on displacement strength:

    1. STRONG_DISPLACEMENT (≥2.0):
       → Entry allowed WITHOUT M5 confirmation
       → Requires: liquidity sweep confirmed + HTF bias aligned
       → Skip: mini BOS and M5 displacement checks
       → Log: "TRADE EXECUTED | Type: STRONG_DISPLACEMENT | M5 confirmation skipped"

    2. MEDIUM SETUP (1.5 ≤ displacement < 2.0):
       → Require at least ONE: mini BOS OR M5 displacement
       → Logs: "BOS_CONFIRMED" or "M5_DISPLACEMENT_CONFIRMED"

    3. WEAK SETUP (displacement < 1.5):
       → NO TRADE

    After confirmation passes, POI tolerance rules apply.

    Returns EntryResult with executed=True if order sent successfully.
    """
    from execution.startup_gate import is_trading_ready

    result = EntryResult(direction=confluence.direction)

    if not is_trading_ready():
        result.reason = "MT5 reconciliation not complete"
        result.blocked = True
        return result

    # ── TRADE CONTROL LAYER: Check for active position (FIRST THING) ──────
    has_active, block_reason = _check_active_position(symbol, confluence.direction)
    if has_active:
        result.reason = block_reason
        result.blocked = True  # Mark as blocked, not rejected
        return result
    
    # ── TRADE CONTROL LAYER: Check cooldown (prevents revenge trading) ──
    is_in_cooldown, cooldown_reason = _check_cooldown(symbol, confluence.direction)
    if is_in_cooldown:
        result.reason = cooldown_reason
        result.blocked = True  # Mark as blocked (control layer, not setup rejection)
        return result

    tick = conn.get_tick(symbol)
    if tick is None:
        result.reason = "Could not get current tick"
        return result

    current_price = tick.ask if confluence.direction == "bullish" else tick.bid
    sym_info      = conn.get_symbol_info(symbol)
    if sym_info is None:
        result.reason = "Symbol info unavailable"
        return result

    # Use internal trading point, not raw MT5 value (which may be incorrect for XAUUSDm)
    point = conn.get_trading_point(symbol)

    # ── STEP 1: Determine displacement tier (STRONG / MEDIUM / WEAK) ────
    disp_ratio = confluence.displacement_ratio
    
    # Get M5 displacement and mini BOS status for conditional checking
    disp_candle_present = _recent_displacement(df_m5, confluence.direction)
    swings = find_swings(df_m5, n=3)
    breaks = detect_breaks(df_m5, swings)
    bos_confirmed = any(
        b.direction == confluence.direction
        and b.bar_index >= len(df_m5) - 10
        for b in breaks
    )

    # ── STEP 2: Tiered confirmation (M5 confirmation is CONDITIONAL) ────
    confirmation_valid, confirmation_type = _tiered_confirmation(
        displacement_ratio=disp_ratio,
        has_disp_candle=disp_candle_present,
        has_bos=bos_confirmed,
        has_sweep=confluence.sweep is not None,
        direction=confluence.direction,
    )
    
    if not confirmation_valid:
        result.reason = confirmation_type  # contains rejection reason
        log.debug(result.reason)
        return result

    # ── STEP 3: ADAPTIVE POI CHECK ─────────────────────────────────────
    # Try 4 entry conditions in order of preference (strict → adaptive):
    
    entry_valid, entry_method = _check_poi_entry_conditions(
        current_price, confluence, point, df_m5, confluence.direction
    )
    if not entry_valid:
        result.reason = entry_method  # contains the rejection reason
        log.debug(result.reason)
        return result
    
    # ── POI VALIDATION PASSED: Now log actual trade execution ─────────────
    log.info(
        f"✓ TRADE EXECUTED | Confirmation: {confirmation_type} | Entry type: {entry_method} | "
        f"Price: {current_price:.2f} | Displacement: {confluence.displacement_ratio:.2f}x | Score: {confluence.score:.0f}"
    )

    # ── Build SL / TP ────────────────────────────────────────────────
    sl, tp, sl_points = _calculate_sl_tp(
        confluence, current_price, point, sym_info
    )
    if sl == 0 or tp == 0:
        result.reason = "Could not calculate valid SL/TP"
        return result

    # ── Lot size ─────────────────────────────────────────────────────
    lots = calculate_lot_size(sl_points, symbol)
    if lots <= 0:
        result.reason = "Lot size calculation returned 0"
        return result

    # ── Check spread ──────────────────────────────────────────────────
    spread = conn.get_spread_points(symbol)
    if spread > settings.HIGH_SPREAD_POINTS * 2:
        result.reason = f"Spread too high: {spread} points"
        log.warning(result.reason)
        return result

    # ── Send order ────────────────────────────────────────────────────
    order_type = mt5.ORDER_TYPE_BUY if confluence.direction == "bullish" else mt5.ORDER_TYPE_SELL
    price      = tick.ask            if confluence.direction == "bullish" else tick.bid

    request = {
        "action":       mt5.TRADE_ACTION_DEAL,
        "symbol":       symbol,
        "volume":       lots,
        "type":         order_type,
        "price":        price,
        "sl":           sl,
        "tp":           tp,
        "deviation":    settings.DEVIATION,
        "magic":        settings.MAGIC,
        "comment":      f"SMC_{confluence.poi_type}_S{int(confluence.score)}_{entry_method}",
        "type_time":    mt5.ORDER_TIME_GTC,
        "type_filling": mt5.ORDER_FILLING_IOC,
    }

    order_result = conn.send_order(request)
    if order_result is None or order_result.retcode != mt5.TRADE_RETCODE_DONE:
        code   = order_result.retcode if order_result else "N/A"
        result.reason = f"Order failed | retcode={code}"
        log.error(
            f"MT5 ORDER FAILED | Symbol: {symbol} | Type: {confluence.direction.upper()} | "
            f"Price: {price:.2f} | SL: {sl:.2f} | TP: {tp:.2f} | Retcode: {code} | "
            f"Comment: {order_result.comment if order_result else 'N/A'}"
        )
        return result

    increment_trade_count()
    result.executed  = True
    result.ticket    = order_result.order
    result.entry     = price
    result.sl        = sl
    result.tp        = tp
    result.lots      = lots
    result.sl_points = sl_points

    # ── Update cooldown tracker for trade control layer ─────────────────────
    key = f"{symbol}_{confluence.direction}"
    _LAST_ENTRY_TIME[key] = time.time()
    log.debug(
        f"Entry time registered for {key} | "
        f"Will be used as cooldown fallback if trade closes without exit reason"
    )

    log.info(
        f"MT5 ORDER CONFIRMED | Ticket: {order_result.order} | "
        f"Retcode: {order_result.retcode} | Deal: {order_result.deal}"
    )
    
    log_trade_open(
        log, result.ticket, confluence.direction, symbol,
        lots, price, sl, tp, confluence.score
    )
    return result


# ─── Helpers ─────────────────────────────────────────────────────────────────

def _tiered_confirmation(
    displacement_ratio: float,
    has_disp_candle: bool,
    has_bos: bool,
    has_sweep: bool,
    direction: str,
) -> tuple[bool, str]:
    """
    Displacement-based confirmation hierarchy.
    
    TIER 1 - STRONG_DISPLACEMENT (≥ 2.0):
      Requires:  liquidity sweep confirmed
      Requires:  HTF bias aligned (already checked)
      Skips:     mini BOS requirement
      Skips:     M5 displacement candle requirement
      Return:    (True, "STRONG_DISPLACEMENT")
    
    TIER 2 - MEDIUM (1.5 ≤ displacement < 2.0):
      Requires:  mini BOS OR M5 displacement candle
      Return:    (True, "BOS_CONFIRMED" | "M5_DISPLACEMENT_CONFIRMED")
      Or return: (False, reason) if neither present
    
    TIER 3 - WEAK (displacement < 1.5):
      Return:    (False, reason)
    
    Returns: (is_valid, confirmation_type_or_reason)
    """
    
    # ── TIER 1: STRONG_DISPLACEMENT (≥ 2.0) ────────────────────────
    if displacement_ratio >= settings.STRONG_DISPLACEMENT_THRESHOLD:
        if has_sweep:
            log.debug(
                f"✓ Confirmation PASSED | Type: STRONG_DISPLACEMENT | "
                f"Displacement: {displacement_ratio:.2f}x (>= {settings.STRONG_DISPLACEMENT_THRESHOLD}) | "
                f"Liquidity sweep: confirmed | Proceeding to POI check..."
            )
            return True, "STRONG_DISPLACEMENT"
        else:
            reason = (
                f"STRONG_DISPLACEMENT detected ({displacement_ratio:.2f}x) "
                f"but liquidity sweep missing — trade rejected"
            )
            log.debug(reason)
            return False, reason
    
    # ── TIER 2: MEDIUM (1.5 ≤ displacement < 2.0) ────────────────────
    if displacement_ratio >= settings.MEDIUM_DISPLACEMENT_THRESHOLD:
        # For MEDIUM tier, accept if EITHER BOS or M5 displacement is present
        if has_bos:
            log.debug(
                f"✓ Confirmation PASSED | Type: BOS_CONFIRMED | "
                f"Displacement: {displacement_ratio:.2f}x (>= {settings.MEDIUM_DISPLACEMENT_THRESHOLD}) | "
                f"Mini BOS: confirmed | Proceeding to POI check..."
            )
            return True, "BOS_CONFIRMED"
        elif has_disp_candle:
            log.debug(
                f"✓ Confirmation PASSED | Type: M5_DISPLACEMENT_CONFIRMED | "
                f"Displacement: {displacement_ratio:.2f}x (>= {settings.MEDIUM_DISPLACEMENT_THRESHOLD}) | "
                f"M5 displacement candle: confirmed | Proceeding to POI check..."
            )
            return True, "M5_DISPLACEMENT_CONFIRMED"
        else:
            reason = (
                f"Medium displacement ({displacement_ratio:.2f}x) requires "
                f"mini BOS or M5 displacement candle — neither found"
            )
            log.debug(reason)
            return False, reason
    
    # ── TIER 3: WEAK (displacement < 1.5) ───────────────────────────
    reason = (
        f"Weak displacement ({displacement_ratio:.2f}x < {settings.MEDIUM_DISPLACEMENT_THRESHOLD}) "
        f"— trade rejected"
    )
    log.debug(reason)
    return False, reason


def _recent_displacement(df: pd.DataFrame, direction: str,
                          lookback: int = 5) -> bool:
    """True if a displacement candle in the correct direction exists in last N bars."""
    opens  = df["Open"].values
    closes = df["Close"].values

    for i in range(len(df) - 1, max(len(df) - lookback - 1, 0), -1):
        bullish_candle = closes[i] > opens[i]
        if direction == "bullish" and not bullish_candle:
            continue
        if direction == "bearish" and bullish_candle:
            continue
        if _is_displacement(df, i):
            return True
    return False


def _check_poi_entry_conditions(
    current_price: float,
    confluence: ConfluenceResult,
    point: float,
    df_m5: pd.DataFrame,
    direction: str,
) -> tuple[bool, str]:
    """
    Check price against POI with ADAPTIVE TOLERANCE based on displacement strength.
    
    Hierarchy of entry conditions (tries from strict to adaptive):
      1. STRICT POI: Price inside POI zone (strictest)
      2. ADAPTIVE POI: Price within displacement-scaled buffer (moderate)
      3. MOMENTUM ENTRY: Strong trend + sweep confirmed, any price in M5 range
      4. FVG-BASED: Use FVG as alternative POI if score supports it
    
    Returns (is_valid, entry_method_or_reason)
    """
    poi_bottom = confluence.poi_bottom
    poi_top    = confluence.poi_top
    poi_type   = confluence.poi_type
    score      = confluence.score
    disp_ratio = confluence.displacement_ratio
    sweep      = confluence.sweep

    # ── 1. STRICT POI CHECK (original logic) ────────────────────────
    if poi_bottom <= current_price <= poi_top:
        log.info(
            f"✓ POI_ENTRY (STRICT) | Price {current_price:.2f} inside "
            f"{poi_type} [{poi_bottom:.2f}–{poi_top:.2f}]"
        )
        return True, "POI_ENTRY"

    # ── 2. CALCULATE ADAPTIVE BUFFER BASED ON ATR VOLATILITY ────────────────
    # ATR-based dynamic tolerance adapts to market volatility
    # High displacement + high volatility → wider buffer
    # Low displacement + low volatility → tighter buffer
    buffer, buffer_label = _calculate_dynamic_entry_buffer(
        df_m5, disp_ratio, point, direction
    )
    
    buffer_pts = buffer / point  # Convert to points for logging
    
    # ── 3. ADAPTIVE NEAR-POI ENTRY ────────────────────────────────
    lower_bound = poi_bottom - buffer
    upper_bound = poi_top + buffer
    
    if lower_bound <= current_price <= upper_bound:
        log.info(
            f"✓ NEAR_POI_ENTRY ({buffer_label} displacement) | Price {current_price:.2f} within adaptive tolerance | "
            f"{poi_type}: [{poi_bottom:.2f}–{poi_top:.2f}] | "
            f"Buffer: {buffer:.2f} price units ({buffer_pts:.0f} pts, {buffer_label}) | "
            f"Displacement: {disp_ratio:.2f}x | Entry bounds: [{lower_bound:.2f}–{upper_bound:.2f}]"
        )
        return True, f"NEAR_POI_ENTRY"

    # ── 4. MOMENTUM ENTRY (STRONG signal + trend, any reasonable price) ──
    # Allow entry on VERY strong setups even if not near POI
    # Conditions:
    #   - Displacement >= 2.3 (very strong)
    #   - Sweep confirmed (trend is real)
    #   - Price is within current M5 candle range (reasonable entry)
    # This allows entry when trend is undeniable but price moved beyond POI
    
    if disp_ratio >= 2.3 and sweep is not None:
        # Get current M5 candle range
        if len(df_m5) > 0:
            current_bar = df_m5.iloc[-1]
            m5_low = current_bar["Low"]
            m5_high = current_bar["High"]
            
            log.debug(
                f"MOMENTUM_ENTRY check | Price: {current_price:.2f} | M5 range: [{m5_low:.2f}–{m5_high:.2f}] | "
                f"Displacement: {disp_ratio:.2f}x | Sweep: {sweep}"
            )
            
            # Allow entry if price is within current candle
            if m5_low <= current_price <= m5_high:
                log.info(
                    f"✓ MOMENTUM_ENTRY | VERY_STRONG trend | Price {current_price:.2f} in M5 range "
                    f"[{m5_low:.2f}–{m5_high:.2f}] | Displacement: {disp_ratio:.2f}x (>= 2.3) | "
                    f"Sweep: confirmed | POI: {poi_type} [{poi_bottom:.2f}–{poi_top:.2f}]"
                )
                return True, "MOMENTUM_ENTRY"
            else:
                log.debug(
                    f"MOMENTUM_ENTRY rejected | Price {current_price:.2f} outside M5 range "
                    f"[{m5_low:.2f}–{m5_high:.2f}] | Displacement: {disp_ratio:.2f}x"
                )

    # ── 5. FVG-BASED ENTRY (alternative POI if score is high enough) ─
    # FVG is often closer than deep OBs, especially in strong moves
    if score >= settings.MIN_SCORE_ALWAYS and poi_type != "FVG":
        # Check if there's a nearby FVG that price could use
        from models.fvg_model import detect_fvgs, active_fvgs, nearest_fvg
        fvgs = detect_fvgs(df_m5)
        near_fvg = nearest_fvg(fvgs, current_price, direction)
        
        if near_fvg:
            fvg_lower = near_fvg.bottom
            fvg_upper = near_fvg.top
            fvg_buffer = settings.FVG_ENTRY_TOLERANCE_POINTS * point
            fvg_lower_bound = fvg_lower - fvg_buffer
            fvg_upper_bound = fvg_upper + fvg_buffer
            
            if fvg_lower_bound <= current_price <= fvg_upper_bound:
                log.info(
                    f"✓ FVG_ENTRY | Price {current_price:.2f} within "
                    f"FVG [{fvg_lower:.2f}–{fvg_upper:.2f}] "
                    f"(tolerance: {fvg_buffer/point:.0f} pts) | Score {score:.0f}"
                )
                return True, "FVG_ENTRY"

    # ── All entry conditions failed ─────────────────────────────────
    # Calculate distance in PRICE UNITS first, then convert to POINTS for logging
    dist_price_units = min(
        abs(current_price - poi_bottom),
        abs(current_price - poi_top)
    )
    dist_points = dist_price_units / point if point != 0 else 0
    
    reason = (
        f"ENTRY ZONE VALIDATION FAILED | Stage: POI_CHECK | "
        f"Price: {current_price:.2f} | {poi_type}: [{poi_bottom:.2f}–{poi_top:.2f}] | "
        f"Distance: {dist_price_units:.2f} price units ({dist_points:.0f} pts) | "
        f"Adaptive buffer ({buffer_label}): {buffer:.2f} price units ({buffer_pts:.0f} pts) | "
        f"Entry bounds: [{lower_bound:.2f}–{upper_bound:.2f}] | "
        f"Displacement: {disp_ratio:.2f}x | Score: {score:.0f}"
    )
    log.debug(reason)
    return False, reason



def _calculate_sl_tp(
    confluence: ConfluenceResult,
    price:      float,
    point:      float,
    sym_info,
) -> tuple[float, float, float]:
    """
    SL: beyond the POI edge + buffer.
    TP: 2R (distance from entry to SL, projected in profit direction).
    Returns (sl, tp, sl_points).
    """
    buf = SL_BUFFER_POINTS * point
    direction = confluence.direction

    if direction == "bullish":
        sl        = confluence.poi_bottom - buf
        sl_points = (price - sl) / point
        tp        = price + (price - sl) * 2   # 2R
    else:
        sl        = confluence.poi_top + buf
        sl_points = (sl - price) / point
        tp        = price - (sl - price) * 2   # 2R

    # Sanity check
    min_stop = sym_info.trade_stops_level * point
    if abs(price - sl) < min_stop:
        log.warning(
            f"SL too close to price ({abs(price-sl)/point:.0f} pts < "
            f"{sym_info.trade_stops_level} pts min). Widening."
        )
        if direction == "bullish":
            sl = price - min_stop - buf
            tp = price + (price - sl) * 2
        else:
            sl = price + min_stop + buf
            tp = price - (sl - price) * 2
        sl_points = abs(price - sl) / point

    # Normalise to symbol tick
    digits = sym_info.digits
    sl = round(sl, digits)
    tp = round(tp, digits)

    return sl, tp, sl_points

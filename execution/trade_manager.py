"""
trade_manager.py — Active trade management with state machine and detailed lifecycle logging.

Runs on every bot iteration (even after 23:00 entry lock).

TRADE LIFECYCLE STATES:
  ENTRY_ACTIVE     → Position opened, initial risk management
  RISK_ACTIVE      → Price moving favorably, standard management
  BREAK_EVEN_ACTIVE→ SL moved to break-even (1R achieved)
  STRUCTURE_TRAIL  → SL trailing based on market structure
  TP_HUNTING       → Price near TP, monitoring for close
  EXIT_COMPLETE    → Trade closed

Responsibilities:
  1. Lifecycle logging → track RR, floating profit, state transitions
  2. Break-even activation → move SL to entry at ≥1.5R
  3. Structure trailing → move SL based on market structure (higher lows, OBs)
  4. Profit protection → lock gains at institutional levels
  5. Time-based rules → close old trades
  6. Session management → force close on Friday/weekend
"""

from datetime import datetime, timezone
from dataclasses import dataclass
from typing import Optional

import MetaTrader5 as mt5
import pandas as pd

from config import settings
from utils import mt5_connector as conn
from utils.logger import get_logger, log_sl_move, log_trade_close
from execution.risk_manager import record_trade_result
from execution.state_persistence import save_trade_states
from execution.entry_engine import register_trade_exit
from execution.lifecycle_coordinator import (
    check_position_count_change,
    engage_stabilization_lock,
    is_stabilization_lock_active,
    mark_startup_complete,
    process_trade_closure,
)
from execution.broker_state_manager import (
    TerminalTradeState,
    get_broker_open_positions,
)
from execution.broker_first_closure_processor import (
    process_all_closed_positions,
    archive_closed_positions,
)

log = get_logger(__name__)

# Trade state tracking (ticket -> state) - Using TerminalTradeState for broker-first
_TRADE_STATES = {}


def get_active_trade_state_count() -> int:
    return len(_TRADE_STATES)

# ── LIFECYCLE LOCK: Prevent signal engine during closure processing ───────────
_TRADE_LIFECYCLE_LOCK_ACTIVE = False

def set_lifecycle_lock(active: bool) -> None:
    """Set the trade lifecycle lock to prevent signal execution during closure."""
    global _TRADE_LIFECYCLE_LOCK_ACTIVE
    _TRADE_LIFECYCLE_LOCK_ACTIVE = active
    if active:
        log.debug("LIFECYCLE LOCK ENGAGED | Exit processing in progress")
    else:
        log.debug("LIFECYCLE LOCK RELEASED | Stabilization check will follow")

def is_lifecycle_lock_active() -> bool:
    """Check if trade lifecycle lock is active."""
    return _TRADE_LIFECYCLE_LOCK_ACTIVE



# Time tracking
import time


def detect_and_process_closed_positions(symbol: str = settings.SYMBOL) -> None:
    """
    BROKER-FIRST CLOSURE DETECTION: Check for positions that disappeared from broker.
    
    Uses broker state as authoritative source of truth.
    All closures verified forensically in deal history.
    Implements exactly-once closure semantics.
    
    Process:
    1. Compare memory states to broker open positions
    2. For each disappeared position:
       - Forensically verify closure in deal history
       - Extract verified PnL, RR, closure reason
       - Emit TRADE_CLOSED event (exactly-once)
       - Record accounting (exactly-once)
       - Register cooldown (exactly-once)
       - Transition to CLOSED_RECORDED state
    3. Archive fully processed closures
    
    GUARANTEES: 
    - No position closure is silent
    - No duplicate closure events
    - Complete accounting accuracy
    - Terminal states are irreversible
    """
    if not _TRADE_STATES:
        return
    
    # ── BROKER-FIRST PROCESSING ──────────────────────────────────────────
    processed, skipped, failed = process_all_closed_positions(_TRADE_STATES, symbol)
    
    if processed > 0 or failed > 0:
        # ── ARCHIVE FULLY PROCESSED CLOSURES ──────────────────────────────
        archived = archive_closed_positions(_TRADE_STATES)
        
        # ── PERSIST STATE ─────────────────────────────────────────────────
        save_trade_states(_TRADE_STATES)
        
        log.warning(
            f"CLOSURE CYCLE COMPLETE | Processed: {processed} | Archived: {archived} | "
            f"Skipped: {skipped} | Failed: {failed}"
        )


def _find_closure_deal(ticket: int, symbol: str) -> Optional[dict]:
    """
    Query MT5 deal history to find the closure deal for a position.
    
    Returns dict with: profit, comment (reason), time
    Returns None if deal not found.
    """
    try:
        # Query last 24 hours of deals for this symbol
        deals = conn.get_deal_history(symbol=symbol, magic=settings.MAGIC, lookback_hours=24)
        
        if not deals or deals.get('deal_count', 0) == 0:
            return None
        
        from execution.broker_state_manager import deal_closes_position

        for deal in deals.get('deals', []):
            if deal_closes_position(deal, ticket):
                return {
                    'profit': deal.get('profit', 0.0),
                    'reason': deal.get('comment', 'Unknown'),
                    'time': deal.get('time_str', ''),
                    'commission': deal.get('commission', 0.0),
                    'swap': deal.get('swap', 0.0),
                }
        
        return None
    
    except Exception as e:
        log.error(f"DEAL HISTORY QUERY FAILED | Ticket: {ticket} | Error: {e}")
        return None


def _parse_close_reason(comment: str) -> str:
    """
    Parse MT5 deal comment to determine close reason.
    
    Maps "tp" or "TP" → "TP"
    Maps "sl" or "SL" → "SL"
    Maps "Be" → "BE"
    Default → "FORCE_CLOSE"
    """
    comment_upper = comment.upper()
    
    if "TP" in comment_upper:
        return "TP"
    elif "SL" in comment_upper:
        return "SL"
    elif "BE" in comment_upper or "BREAK" in comment_upper:
        return "BE"
    else:
        return "FORCE_CLOSE"

@dataclass
class TradeState:
    """
    DEPRECATED: Use TerminalTradeState from broker_state_manager instead.
    
    This class is kept for backward compatibility with position management.
    For lifecycle management, use TerminalTradeState.
    """
    ticket: int
    direction: str
    entry: float
    initial_sl: float
    initial_tp: float
    state: str = "ENTRY_ACTIVE"  # Current state
    be_activated: bool = False  # Whether break-even was hit
    rr_achieved: float = 0.0  # Last recorded R/R
    last_sl: float = 0.0  # Last known SL
    last_logged: float = 0.0  # Last price at which we logged
    partial_close_attempted: bool = False  # Tracks if partial close was already tried
    force_close_attempted: bool = False  # Tracks if force close was already tried
    
    def update_state(self, new_state: str):
        """Transition to new state with logging."""
        if new_state != self.state:
            log.info(
                f"STATE TRANSITION | Ticket: {self.ticket} | "
                f"{self.state} -> {new_state}"
            )
            self.state = new_state


def _trade_state_from_persisted(ticket: int, state_dict: dict) -> TradeState:
    return TradeState(
        ticket=int(ticket),
        direction=state_dict.get("direction", "bullish"),
        entry=float(state_dict.get("entry", 0.0)),
        initial_sl=float(state_dict.get("initial_sl", 0.0)),
        initial_tp=float(state_dict.get("initial_tp", 0.0)),
        state=state_dict.get("state", "ENTRY_ACTIVE"),
        be_activated=state_dict.get("be_activated", False),
        rr_achieved=float(state_dict.get("rr_achieved", 0.0)),
        last_sl=float(state_dict.get("last_sl", 0.0)),
        last_logged=float(state_dict.get("last_logged", 0.0)),
        partial_close_attempted=state_dict.get("partial_close_attempted", False),
        force_close_attempted=state_dict.get("force_close_attempted", False),
    )


def _finalize_orphan_ticket(ticket: int, state: TradeState, symbol: str) -> bool:
    """Try to close out a persisted ticket using MT5 deal history."""
    from execution.broker_first_closure_processor import (
        verify_and_extract_closure,
        finalize_single_closure,
        get_lifecycle_state,
    )

    if get_lifecycle_state(state) in ("CLOSED_RECORDED", "ARCHIVED"):
        return True

    closure_details = verify_and_extract_closure(ticket, state, symbol)
    if not closure_details:
        return False
    return bool(finalize_single_closure(state, closure_details, symbol))


def _resolve_orphan_tickets(
    orphan_tickets: list,
    persisted_states: dict,
    symbol: str,
) -> tuple[list, list]:
    """Returns (finalized_tickets, unresolved_tickets)."""
    finalized = []
    unresolved = []

    for ticket in orphan_tickets:
        state_dict = persisted_states.get(ticket) or persisted_states.get(str(ticket))
        if not state_dict:
            unresolved.append(int(ticket))
            continue

        state = _trade_state_from_persisted(int(ticket), state_dict)
        if _finalize_orphan_ticket(int(ticket), state, symbol):
            finalized.append(int(ticket))
            log.info(f"STARTUP CLOSURE RECOVERED | Ticket: {ticket}")
        else:
            unresolved.append(int(ticket))
            log.warning(
                f"STARTUP ORPHAN UNRESOLVED | Ticket: {ticket} | "
                f"No broker exit deal or finalize incomplete"
            )

    return finalized, unresolved


def cleanup_trade_state(ticket: int) -> None:
    """
    Clean up trade state after closure processed.
    
    Called from lifecycle_coordinator after process_trade_closure() completes.
    Removes ticket from memory and persists updated state.
    """
    if ticket in _TRADE_STATES:
        removed_state = _TRADE_STATES.pop(ticket)
        log.debug(f"TRADE STATE CLEANUP | Ticket: {ticket} | Removed from memory")
    
    # Persist updated state
    save_trade_states(_TRADE_STATES)


def manage_open_trades(symbol: str = settings.SYMBOL) -> None:
    """
    Called every main loop iteration.
    
    CRITICAL SEQUENCE:
    1. Set lifecycle lock (prevents signal engine from executing)
    2. Detect and process closed positions
    3. Manage remaining open positions
    4. Check if position count changed (requires stabilization)
    5. Release lifecycle lock (but stabilization may still hold signal engine)
    
    Iterates all open positions for this bot and applies management rules.
    """
    from execution.startup_gate import is_trading_ready, log_trading_blocked

    if not is_trading_ready():
        log_trading_blocked()
        return

    # ── STEP 1: Engage lifecycle lock to prevent signal execution ────────────
    set_lifecycle_lock(True)
    
    try:
        # ── STEP 2: CRITICAL - Detect closed positions FIRST ─────────────────
        # This MUST run before manage_remaining_positions() to catch natural closures
        detect_and_process_closed_positions(symbol)
        
        # ── STEP 3: Manage remaining open positions ──────────────────────────
        positions = conn.get_open_positions(symbol=symbol, magic=settings.MAGIC)
        current_position_count = len(positions) if positions else 0

        if not positions:
            log.debug(f"MANAGE CYCLE | No open positions | current_count={current_position_count}")
        else:
            spread = conn.get_spread_points(symbol)
            high_spread = spread > settings.HIGH_SPREAD_POINTS

            sym_info = conn.get_symbol_info(symbol)
            if sym_info is None:
                log.error("Cannot get symbol info, skipping position management")
                return
            
            # Use internal trading point, not raw MT5 value (which may be incorrect for XAUUSDm)
            point = conn.get_trading_point(symbol)

            for pos in positions:
                try:
                    _manage_position(pos, symbol, point, high_spread)
                except Exception as e:
                    log.error(f"Error managing position {pos.ticket}: {e}", exc_info=True)
        
        # ── STEP 4: CRITICAL - Check if position count changed DURING RUNTIME ───────────────
        # This detects live closures and engages stabilization lock (NOT during startup)
        position_count_changed = check_position_count_change(current_position_count)
        if position_count_changed:
            # Closure detected → engage stabilization lock (only if not startup phase)
            engage_stabilization_lock(
                f"Position count changed to {current_position_count}",
                current_position_count
            )
        
        # ── STEP 5: Persist state after all management updates ────────────────
        save_trade_states(_TRADE_STATES)
        
        log.info(
            f"MANAGE CYCLE COMPLETE | Positions: {current_position_count} | "
            f"Count_changed={position_count_changed} | Stabilization_active={is_stabilization_lock_active()}"
        )
    
    finally:
        # ── ALWAYS release lifecycle lock on exit ────────────────────────────
        set_lifecycle_lock(False)
        log.debug("Trade position management completed, lifecycle lock released")


def _manage_position(pos, symbol: str, point: float,
                     high_spread: bool) -> None:
    ticket    = pos.ticket
    direction = "bullish" if pos.type == mt5.ORDER_TYPE_BUY else "bearish"
    entry     = pos.price_open
    sl        = pos.sl
    tp        = pos.tp
    volume    = pos.volume

    tick = conn.get_tick(symbol)
    if tick is None:
        return
    current = tick.bid if direction == "bullish" else tick.ask

    # ── Get or initialize trade state ──────────────────────────────────
    if ticket not in _TRADE_STATES:
        _TRADE_STATES[ticket] = TradeState(
            ticket=ticket,
            direction=direction,
            entry=entry,
            initial_sl=sl,
            initial_tp=tp
        )
        log.info(
            f"NEW TRADE TRACKED | Ticket: {ticket} | Direction: {direction.upper()} | "
            f"Entry: {entry:.2f} | SL: {sl:.2f} | TP: {tp:.2f}"
        )
    
    trade_state = _TRADE_STATES[ticket]

    # ── Compute R achieved ────────────────────────────────────────────
    if sl == 0:
        log.debug(f"Ticket {ticket}: no SL set, skipping management")
        return

    initial_risk = abs(entry - sl)   # in price units
    if initial_risk == 0:
        return

    current_profit_units = (
        (current - entry) if direction == "bullish"
        else (entry - current)
    )
    current_profit_price = (
        (current - entry) if direction == "bullish"
        else (entry - current)
    )
    r_achieved = current_profit_units / initial_risk
    
    # Distance to TP
    dist_to_tp = abs(current - tp)
    
    trade_state.rr_achieved = r_achieved
    trade_state.last_sl = sl

    # ── TRADE STATE LOGGING (every 5-10 pts movement) ──────────────────
    price_moved = abs(current - trade_state.last_logged)
    if price_moved >= 5 * point or trade_state.last_logged == 0:
        log.info(
            f"TRADE STATE | Ticket: {ticket} | Entry: {entry:.2f} | Current: {current:.2f} | "
            f"RR: {r_achieved:.2f}R | Floating: {current_profit_price:+.2f} | "
            f"SL: {sl:.2f} | TP: {tp:.2f} | Distance to TP: {dist_to_tp:.2f} | "
            f"State: {trade_state.state}"
        )
        trade_state.last_logged = current

    # ── 1. BREAK-EVEN ACTIVATION (at 1.5R) ──────────────────────────────
    be_threshold = 1.5  # Move SL to BE at 1.5R
    if r_achieved >= be_threshold and not trade_state.be_activated and not high_spread:
        be_sl = round(entry, 5)
        
        should_move = (
            (direction == "bullish" and be_sl > sl) or
            (direction == "bearish" and be_sl < sl)
        )
        
        if should_move:
            ok = conn.modify_sl(ticket, symbol, be_sl)
            if ok:
                trade_state.be_activated = True
                trade_state.update_state("BREAK_EVEN_ACTIVE")
                log.warning(
                    f"BREAK EVEN ACTIVATED | Ticket: {ticket} | "
                    f"Old SL: {sl:.2f} | New SL: {be_sl:.2f} | "
                    f"RR Achieved: {r_achieved:.2f}R | "
                    f"Reason: Risk protected at break-even"
                )
                log_sl_move(log, ticket, sl, be_sl, f"Break-even at {r_achieved:.2f}R")

    # ── 2. PROFIT PROTECTION (at 2.5R) ────────────────────────────────
    profit_lock_threshold = 2.5
    if r_achieved >= profit_lock_threshold and not high_spread:
        # Move SL to entry + 0.5R (lock partial profit)
        new_sl = (
            entry + 0.5 * initial_risk if direction == "bullish"
            else entry - 0.5 * initial_risk
        )
        sym_info = conn.get_symbol_info(symbol)
        if sym_info:
            new_sl = round(new_sl, sym_info.digits)

        # Only move if better than current SL
        should_move = (
            (direction == "bullish" and new_sl > sl) or
            (direction == "bearish" and new_sl < sl)
        )
        if should_move:
            ok = conn.modify_sl(ticket, symbol, new_sl)
            if ok:
                trade_state.update_state("RISK_ACTIVE")
                log.warning(
                    f"PROFIT LOCK | Ticket: {ticket} | "
                    f"Old SL: {sl:.2f} | New SL: {new_sl:.2f} | "
                    f"RR Achieved: {r_achieved:.2f}R"
                )
                log_sl_move(log, ticket, sl, new_sl, f"Profit lock at {r_achieved:.2f}R")

    # ── 3. TIME-BASED RULE (> 8 hours) ────────────────────────────────
    open_time   = datetime.fromtimestamp(pos.time, tz=timezone.utc)
    hours_open  = (datetime.now(tz=timezone.utc) - open_time).total_seconds() / 3600

    if hours_open >= settings.MAX_TRADE_HOURS:
        if r_achieved > 0 and not high_spread and not trade_state.partial_close_attempted:
            # Partial close 50% and tighten SL to entry
            log.warning(
                f"TIME RULE | Ticket: {ticket}: open {hours_open:.1f}h ≥ {settings.MAX_TRADE_HOURS}h "
                f"| RR: {r_achieved:.2f}R | Attempting partial close ({settings.PARTIAL_CLOSE_PCT*100:.0f}%)"
            )
            
            # Attempt partial close
            ok, msg = conn.partial_close(pos, settings.PARTIAL_CLOSE_PCT)
            trade_state.partial_close_attempted = True
            
            if ok:
                # Partial close succeeded - move SL to entry to lock remaining profit
                new_sl = pos.sl if pos.type == mt5.ORDER_TYPE_BUY else pos.sl
                # For now, accept the trade state. SL will be adjusted next iteration if needed
                trade_state.update_state("PARTIAL_SECURED")
                log.warning(f"TIME RULE PARTIAL CLOSE | ticket={ticket} | {msg}")
            else:
                log.info(f"TIME RULE PARTIAL CLOSE INVALID | ticket={ticket} | {msg}")
                
        elif r_achieved <= -0.8 and not high_spread and not trade_state.force_close_attempted:
            # Close loser that has been open too long (avoid large overnight loss)
            log.warning(
                f"TIME RULE LOSS CLOSE | Ticket {ticket}: open {hours_open:.1f}h with R={r_achieved:.2f} "
                f"-- closing to limit time-based loss"
            )
            trade_state.force_close_attempted = True
            _force_close(pos, symbol, "Time limit with loss")
            _TRADE_STATES.pop(ticket, None)
            return


def force_close_all(symbol: str = settings.SYMBOL,
                    reason: str = "Session rule") -> None:
    """
    Close ALL open positions for this bot immediately.
    Used for Friday 18:00 and weekend protection.
    """
    positions = conn.get_open_positions(symbol=symbol, magic=settings.MAGIC)
    if not positions:
        log.info(f"force_close_all: no open positions ({reason})")
        return

    log.warning(
        f"Force-closing {len(positions)} position(s) | Reason: {reason}"
    )
    for pos in positions:
        _force_close(pos, symbol, reason)
        _TRADE_STATES.pop(pos.ticket, None)  # Clear state tracking


def _force_close(pos, symbol: str, reason: str) -> None:
    """
    Force close a position with broker verification and retry logic.
    
    Args:
        pos: MT5 position object
        symbol: Trading symbol
        reason: Close reason (TP, SL, BE, TIME_RULE, FORCE_CLOSE, etc)
    
    ENSURES: Position is actually removed from broker before updating state.
    """
    ticket = pos.ticket
    pnl = pos.profit
    max_retries = 3
    retry_count = 0
    
    while retry_count < max_retries:
        # ── ATTEMPT CLOSE ────────────────────────────────────────────────
        ok = conn.close_position(pos)
        if not ok:
            log.error(f"FORCED CLOSE FAILED | Ticket: {ticket} | Retcode failure")
            retry_count += 1
            if retry_count < max_retries:
                log.warning(f"FORCED CLOSE RETRY | Ticket: {ticket} | Attempt {retry_count + 1}/{max_retries}")
                import time
                time.sleep(1)  # Wait 1 second before retry
                continue
            else:
                # Max retries exhausted
                log.critical(
                    f"EMERGENCY CLOSE FAILURE | Ticket: {ticket} | "
                    f"Max retries ({max_retries}) exhausted | Position may remain open"
                )
                break
        
        # ── VERIFY BROKER CLOSURE ────────────────────────────────────────
        # Check that position is actually gone from MT5
        import time
        time.sleep(0.5)  # Brief delay to allow MT5 to process
        
        updated_pos = conn.get_open_positions(symbol=symbol, magic=settings.MAGIC)
        position_still_exists = any(p.ticket == ticket for p in (updated_pos or []))
        
        if position_still_exists:
            log.warning(
                f"FORCED CLOSE VERIFICATION FAILED | Ticket: {ticket} | "
                f"Position still exists on broker after close attempt"
            )
            retry_count += 1
            if retry_count < max_retries:
                log.warning(f"FORCED CLOSE RETRY | Ticket: {ticket} | Attempt {retry_count + 1}/{max_retries}")
                continue
            else:
                log.critical(
                    f"EMERGENCY CLOSE FAILURE | Ticket: {ticket} | "
                    f"Position verification failed after {max_retries} retries"
                )
                break
        
        # ── CLOSE VERIFIED: Position is gone from broker ──────────────────
        log.warning(
            f"FORCED CLOSE VERIFIED | Ticket: {ticket} | "
            f"Position confirmed closed on broker | PnL: {pnl:.2f}"
        )
        
        # Record the result and update state
        log_trade_close(log, ticket, reason, pnl)
        record_trade_result(pnl, ticket=ticket)
        _TRADE_STATES.pop(ticket, None)
        
        # ── Register exit cooldown with entry engine ──────────────────────
        exit_reason = reason.upper()
        if "TIME" in exit_reason:
            exit_reason = "TIME_RULE"
        elif reason not in ["TP", "SL", "BE", "FORCE_CLOSE"]:
            if "take" in reason.lower() or "profit" in reason.lower():
                exit_reason = "TP"
            elif "stop" in reason.lower() or "loss" in reason.lower():
                exit_reason = "SL"
            else:
                exit_reason = "FORCE_CLOSE"
        
        direction = "bullish" if pos.type == mt5.ORDER_TYPE_BUY else "bearish"
        register_trade_exit(symbol, direction, exit_reason)
        
        # Persist updated state
        save_trade_states(_TRADE_STATES)
        return  # Success
    
    # If we get here, close failed after all retries
    log.critical(
        f"POSITION CLOSE UNVERIFIED | Ticket: {ticket} | "
        f"May be open on broker - MANUAL INTERVENTION REQUIRED"
    )
    _TRADE_STATES.pop(ticket, None)  # Remove from tracking but log issue


def sync_active_positions_from_mt5(symbol: str = settings.SYMBOL) -> None:
    """
    Rebuild in-memory active trade state from MT5 open positions only.
    Used for lightweight recovery (no strict orphan gate).
    """
    from execution.state_persistence import load_trade_states, save_trade_states

    persisted_states = load_trade_states() or {}
    _TRADE_STATES.clear()
    positions = conn.get_open_positions(symbol=symbol, magic=settings.MAGIC) or []

    for pos in positions:
        if not hasattr(pos, "ticket") or not hasattr(pos, "type"):
            continue
        ticket = pos.ticket
        direction = "bullish" if pos.type == mt5.ORDER_TYPE_BUY else "bearish"
        entry = getattr(pos, "price_open", None)
        if entry is None:
            continue
        sl = getattr(pos, "sl", 0.0)
        tp = getattr(pos, "tp", 0.0)
        persisted = persisted_states.get(ticket) or persisted_states.get(str(ticket))
        if persisted:
            state = _trade_state_from_persisted(ticket, persisted)
            state.entry = float(entry)
            state.initial_sl = float(sl)
            state.initial_tp = float(tp)
            state.last_sl = float(sl)
            state.direction = direction
        else:
            state = TradeState(
                ticket=ticket,
                direction=direction,
                entry=float(entry),
                initial_sl=float(sl),
                initial_tp=float(tp),
                state="ENTRY_ACTIVE",
                last_sl=float(sl),
                last_logged=float(entry),
            )
        _TRADE_STATES[ticket] = state

    save_trade_states(_TRADE_STATES)
    log.info(
        f"POSITION SYNC | MT5 open={len(positions)} | "
        f"memory states={len(_TRADE_STATES)}"
    )


def reconcile_positions_on_startup(
    symbol: str = settings.SYMBOL,
) -> tuple[bool, list[int]]:
    """
    MT5-first startup reconciliation. Does not enable trading — caller sets trading_ready.

    1. Rebuild active trade state from MT5 open positions (broker authority)
    2. Finalize persisted tickets closed on MT5 (position_id deal mapping)
    3. Persist authoritative active state only

    Returns (success, unresolved_ticket_ids).
    """
    from execution.state_persistence import (
        load_trade_states,
        save_trade_states,
        clear_trades_state_file,
    )

    unresolved: list[int] = []

    try:
        persisted_states = load_trade_states() or {}

        # ── MT5-FIRST: active state only from broker open positions ─────────
        _TRADE_STATES.clear()
        positions = conn.get_open_positions(symbol=symbol, magic=settings.MAGIC) or []

        if not positions:
            log.info("RECONCILIATION | No open positions on MT5")
        else:
            log.info(f"RECONCILIATION | Syncing {len(positions)} open MT5 position(s)")
        
        # ── STEP 3: For each position, restore or recreate state ────────────
        for pos in positions:
            try:
                # Defensive validation: check required attributes exist
                if not hasattr(pos, 'ticket') or not hasattr(pos, 'type'):
                    log.warning(f"RECONCILIATION | Position missing required attributes, skipping")
                    continue
                
                # Safely extract position fields with proper attribute names
                ticket = pos.ticket
                is_buy = pos.type == mt5.ORDER_TYPE_BUY
                direction = "bullish" if is_buy else "bearish"
                
                # Use correct MT5 attribute: price_open (NOT open_price)
                entry = getattr(pos, 'price_open', None)
                sl = getattr(pos, 'sl', 0.0)
                tp = getattr(pos, 'tp', 0.0)
                
                # Validation: price_open is critical
                if entry is None:
                    log.warning(
                        f"RECONCILIATION | Ticket {ticket}: price_open not available. "
                        f"Available attributes: {dir(pos)}"
                    )
                    continue
                
                persisted = (
                    persisted_states.get(ticket)
                    or persisted_states.get(str(ticket))
                )
                if persisted:
                    state = _trade_state_from_persisted(ticket, persisted)
                    state.entry = float(entry)
                    state.initial_sl = float(sl)
                    state.initial_tp = float(tp)
                    state.last_sl = float(sl)
                    state.direction = direction
                else:
                    state = TradeState(
                        ticket=ticket,
                        direction=direction,
                        entry=float(entry),
                        initial_sl=float(sl),
                        initial_tp=float(tp),
                        state="ENTRY_ACTIVE",
                        last_sl=float(sl),
                        last_logged=float(entry),
                    )
                _TRADE_STATES[ticket] = state

                from datetime import datetime
                import pytz
                EAT = pytz.timezone("Africa/Nairobi")
                open_time_eat = datetime.fromtimestamp(pos.time, tz=EAT)
                today_date = datetime.now(EAT).date()
                is_same_day = open_time_eat.date() == today_date

                if is_same_day:
                    log.info(
                        f"SAME-DAY POSITION RESTORED | Ticket: {ticket} | Dir: {direction} | "
                        f"Opened: {open_time_eat.strftime('%H:%M:%S')} | "
                        f"RR: {state.rr_achieved:.2f}R | Entry: {entry:.5f}"
                    )
                else:
                    log.warning(
                        f"OVERNIGHT POSITION DETECTED | Ticket: {ticket} | Dir: {direction} | "
                        f"Opened: {open_time_eat.strftime('%Y-%m-%d %H:%M:%S')} | "
                        f"Duration: {(datetime.now(EAT) - open_time_eat).total_seconds() / 3600:.1f}h | "
                        f"RR: {state.rr_achieved:.2f}R | Entry: {entry:.5f} | INTRADAY VIOLATION"
                    )
            
            except Exception as e:
                log.warning(
                    f"RECONCILIATION | Failed to process ticket (possibly {pos.ticket if hasattr(pos, 'ticket') else 'unknown'}): {e}",
                    exc_info=False
                )
                continue
        
        broker_tickets = {
            pos.ticket for pos in positions if hasattr(pos, "ticket")
        }
        persisted_ticket_ids = {int(k) for k in persisted_states.keys()}
        orphan_tickets = list(persisted_ticket_ids - broker_tickets)

        if orphan_tickets:
            log.warning(
                f"STARTUP RECONCILIATION | {len(orphan_tickets)} persisted ticket(s) "
                f"closed on MT5 (not open): {orphan_tickets}"
            )
            _, unresolved = _resolve_orphan_tickets(
                orphan_tickets, persisted_states, symbol
            )

        if _TRADE_STATES:
            save_trade_states(_TRADE_STATES)
        else:
            clear_trades_state_file()
            log.info(
                "RECONCILIATION | No active trades | trades state cleared | "
                "risk_state preserved for broker rebuild"
            )

        broker_count = len(broker_tickets)
        memory_count = len(_TRADE_STATES)
        if broker_count == memory_count:
            log.info(
                f"RECONCILIATION VERIFIED | Broker open: {broker_count} | "
                f"Memory active: {memory_count}"
            )
        else:
            log.error(
                f"RECONCILIATION MISMATCH | Broker open: {broker_count} | "
                f"Memory active: {memory_count}"
            )
            return False, list(_TRADE_STATES.keys())

        if unresolved:
            return False, unresolved

        return True, []

    except Exception as e:
        log.error(f"RECONCILIATION | Failed: {e}", exc_info=True)
        return False, unresolved


def log_reconciliation_summary() -> None:
    """
    Log a comprehensive summary of reconciliation results.
    Called after reconcile_positions_on_startup() to provide complete observability.
    """
    active_count = len(_TRADE_STATES)
    log.info("=" * 70)
    log.info("RECONCILIATION COMPLETE")
    log.info("=" * 70)
    log.info(f"Active trade states in memory: {active_count}")
    
    if active_count > 0:
        log.info("Active trades:")
        for ticket, state in _TRADE_STATES.items():
            log.info(
                f"  Ticket {ticket:6d} | {state.direction.upper():8s} | "
                f"State: {state.state:15s} | RR: {state.rr_achieved:+.2f}R | "
                f"Entry: {state.entry:.2f}"
            )
    
    log.info("=" * 70)

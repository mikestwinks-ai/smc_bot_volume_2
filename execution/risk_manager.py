"""
risk_manager.py - Position sizing, drawdown protection, and daily loss limits.
"""

from dataclasses import dataclass
from datetime import date
from typing import Optional

try:
    import MetaTrader5 as mt5
except ImportError:
    mt5 = None

from config import settings
from utils.logger import get_logger, log_drawdown_event
from utils import mt5_connector as conn
from execution.state_persistence import save_risk_state, load_risk_state
from forensic_closure_auditor import audit_log

log = get_logger(__name__)


@dataclass
class RiskState:
    day:                date   = None
    trades_today:       int    = 0
    closed_trades_today: int   = 0
    daily_pnl:          float  = 0.0
    consecutive_losses: int    = 0
    peak_balance:       float  = 0.0
    peak_equity:        float  = 0.0
    active_risk_pct:    float  = settings.RISK_PERCENT
    bot_halted:         bool   = False


# Module-level state (persists across main loop iterations)
_state = RiskState()


def update_intraday_peaks(balance: float) -> None:
    """Update peak balance/equity intraday without resetting trade counters."""
    updated = False
    if balance > _state.peak_balance:
        _state.peak_balance = balance
        updated = True

    current_equity = compute_equity()
    selected_peak_equity = max(_state.peak_equity, balance, current_equity)
    if selected_peak_equity > _state.peak_equity:
        _state.peak_equity = selected_peak_equity
        updated = True

    if updated:
        save_risk_state(_state)


def reset_daily_state(balance: float) -> None:
    """
    Per-loop daily maintenance. On calendar change, delegates to day_transition
    (MT5-backed). Same-day calls only update peak anchors.
    """
    from execution.startup_gate import is_trading_ready
    from execution.day_transition import (
        handle_day_transition_if_needed,
        is_day_transition_locked,
    )

    if not is_trading_ready() or is_day_transition_locked():
        return

    if handle_day_transition_if_needed(settings.SYMBOL, balance):
        return

    today = date.today()
    if _state.day is None:
        _state.day = today
    update_intraday_peaks(balance)


def restore_daily_state() -> bool:
    """
    Called during bot startup to restore daily state from persistent storage.
    Returns True if state was restored, False if not available or outdated.
    
    Behavior:
    - If persisted state exists AND is from today: restore it
    - If persisted state is from yesterday or older: skip (day change will reset)
    - If no persisted state: try broker history reconstruction, else use defaults
    """
    global _state

    try:
        persisted_data = load_risk_state()
        if not persisted_data:
            log.info("RISK RESTORATION | No persisted risk state available | Attempting broker history reconstruction...")
            # Try to reconstruct from broker deal history
            reconstructed = reconstruct_daily_state_from_broker()
            if reconstructed:
                _seed_accounted_closure_tickets_from_broker()
            return reconstructed
        
        # Check if persisted state is from today
        persisted_day_str = persisted_data.get("day")
        today_str = date.today().isoformat()
        
        if persisted_day_str != today_str:
            log.info(
                f"RISK RESTORATION | Persisted state from {persisted_day_str}, "
                f"current day {today_str} - not restoring (day mismatch) | Attempting broker history reconstruction..."
            )
            # Try to reconstruct from broker as fallback
            reconstructed = reconstruct_daily_state_from_broker()
            if reconstructed:
                _seed_accounted_closure_tickets_from_broker()
            return reconstructed
        
        # Restore state from persisted data
        restored_state = RiskState(
            day=date.fromisoformat(persisted_data.get("day", date.today().isoformat())),
            trades_today=int(persisted_data.get("trades_today", 0)),
            closed_trades_today=int(persisted_data.get("closed_trades_today", 0)),
            daily_pnl=float(persisted_data.get("daily_pnl", 0.0)),
            consecutive_losses=int(persisted_data.get("consecutive_losses", 0)),
            peak_balance=float(persisted_data.get("peak_balance", 0.0)),
            peak_equity=float(persisted_data.get("peak_equity", 0.0)),
            active_risk_pct=float(persisted_data.get("active_risk_pct", settings.RISK_PERCENT)),
            bot_halted=bool(persisted_data.get("bot_halted", False)),
        )
        
        # ── CRITICAL: If peak_balance is corrupted (0 or too low), initialize to current balance ──
        current_balance = _get_balance()
        if restored_state.peak_balance == 0 or restored_state.peak_balance < current_balance:
            restored_state.peak_balance = current_balance
        
        # ── CRITICAL: Initialize peak_equity to MAXIMUM of:
        # persisted peak_equity, current balance, current equity
        # This ensures peak_equity anchor never drops below available balance ──
        current_equity = current_balance + compute_floating_pnl()
        persisted_peak_eq = restored_state.peak_equity
        
        # Peak equity must be anchored to the highest known reference
        # (never lower than balance, never lower than persisted peak)
        selected_peak_equity = max(persisted_peak_eq, current_balance, current_equity)
        
        log.debug(
            f"PEAK EQUITY FORENSICS (RESTORE) | "
            f"PersistedPeakEquity={persisted_peak_eq:.2f} | "
            f"CurrentBalance={current_balance:.2f} | "
            f"CurrentEquity={current_equity:.2f} | "
            f"SelectedPeakEquity={selected_peak_equity:.2f} | "
            f"Reason=max(persisted, balance, equity)"
        )
        
        restored_state.peak_equity = selected_peak_equity
        
        if persisted_peak_eq != selected_peak_equity and persisted_peak_eq > 0:
            log.warning(
                f"PEAK EQUITY CORRECTED | Was: {persisted_peak_eq:.2f} | "
                f"Now: {selected_peak_equity:.2f} | "
                f"Reason: Anchored to max(persisted, balance, equity)"
            )
        elif persisted_peak_eq == 0:
            log.info(
                f"PEAK EQUITY INITIALIZED | {selected_peak_equity:.2f} | "
                f"Anchored to balance {current_balance:.2f}"
            )
        
        _state = restored_state
        _seed_accounted_closure_tickets_from_broker()

        log.info(
            f"RISK RESTORATION | State restored from persistence | "
            f"trades_today={_state.trades_today} | daily_pnl={_state.daily_pnl:.2f} | "
            f"consecutive_losses={_state.consecutive_losses} | halted={_state.bot_halted}"
        )
        
        # Forensic: Log peak balance restoration
        audit_log("PEAK_BALANCE_UPDATED", {
            "source": "restore_daily_state",
            "peak_balance": _state.peak_balance,
            "peak_equity": _state.peak_equity,
            "current_balance": current_balance,
            "corrected": _state.peak_balance != float(persisted_data.get("peak_balance", 0.0)),
        })
        
        # ── CRITICAL: Verify trades_today against actual broker data ───────
        # Always verify by querying broker to catch persisted count corruption
        open_positions = conn.get_open_positions(settings.SYMBOL, settings.MAGIC) or []
        history = conn.get_deal_history(symbol=settings.SYMBOL, magic=settings.MAGIC, lookback_hours=24)
        
        log.debug(f"MISMATCH CHECK | Querying broker data | open_positions={len(open_positions)} | history_error={'error' in history}")
        
        closed_deals_count = 0
        if "error" not in history:
            deals = history.get("deals", [])
            log.debug(f"MISMATCH CHECK | Got {len(deals)} deals from history")
            # Count only CLOSED deals
            for deal in deals:
                if deal.get("entry_time") == mt5.DEAL_ENTRY_OUT:
                    closed_deals_count += 1
            log.debug(f"MISMATCH CHECK | Counted {closed_deals_count} closed deals")
        else:
            log.warning(f"MISMATCH CHECK | History query error: {history.get('error')}")
        
        actual_trades_count = len(open_positions) + closed_deals_count
        log.debug(f"MISMATCH CHECK | actual_trades_count = {len(open_positions)} open + {closed_deals_count} closed = {actual_trades_count} vs persisted {_state.trades_today}")
        
        if actual_trades_count != _state.trades_today:
            log.warning(
                f"TRADES_TODAY MISMATCH | Persisted: {_state.trades_today} | "
                f"Actual (open {len(open_positions)} + closed {closed_deals_count}): {actual_trades_count} | "
                f"Rebuilding from broker history..."
            )
            # Rebuild accounting from broker history with correct count
            reconstructed = reconstruct_daily_state_from_broker()
            if reconstructed:
                log.warning(
                    f"TRADES_TODAY REBUILT | Now: {_state.trades_today} | "
                    f"Daily PnL: {_state.daily_pnl:.2f} | Consecutive losses: {_state.consecutive_losses}"
                )
            return reconstructed
        
        return True
        
    except Exception as e:
        log.warning(f"RISK RESTORATION | Failed to restore: {e} | Attempting broker history reconstruction...")
        # Try broker reconstruction as final fallback
        reconstructed = reconstruct_daily_state_from_broker()
        return reconstructed


def update_peak(balance: float) -> None:
    """Update peak balance and peak equity, persist immediately if new high achieved.
    
    CRITICAL: peak_equity is anchored to max(persisted, balance, equity)
    This ensures peak_equity reference never drops even during floating losses.
    """
    balance_updated = False
    equity_updated = False
    
    current_equity = compute_equity()
    current_floating = compute_floating_pnl()
    
    # Forensic log BEFORE updates
    log.debug(
        f"PEAK EQUITY FORENSICS (BEFORE UPDATE) | "
        f"CurrentBalance={balance:.2f} | "
        f"CurrentEquity={current_equity:.2f} | "
        f"CurrentFloating={current_floating:.2f} | "
        f"CurrentPeakBalance={_state.peak_balance:.2f} | "
        f"CurrentPeakEquity={_state.peak_equity:.2f}"
    )
    
    if balance > _state.peak_balance:
        old_peak = _state.peak_balance
        _state.peak_balance = balance
        balance_updated = True
        log.info(
            f"PEAK BALANCE UPDATED | Old: {old_peak:.2f} | New: {balance:.2f} | "
            f"Change: +{balance - old_peak:.2f}"
        )
    
    # Update peak equity to MAXIMUM of current state and current equity
    # This anchors peak_equity to the highest reference (balance preferred when no floating loss)
    new_peak_equity = max(_state.peak_equity, balance, current_equity)
    
    if new_peak_equity > _state.peak_equity:
        old_peak_equity = _state.peak_equity
        _state.peak_equity = new_peak_equity
        equity_updated = True
        
        update_reason = ""
        if new_peak_equity == balance:
            update_reason = "Balance update"
        elif new_peak_equity == current_equity:
            update_reason = "Equity improvement"
        else:
            update_reason = "State recovery"
        
        log.info(
            f"PEAK EQUITY UPDATED | Old: {old_peak_equity:.2f} | New: {new_peak_equity:.2f} | "
            f"Change: +{new_peak_equity - old_peak_equity:.2f} | Reason: {update_reason}"
        )
    
    # Forensic log AFTER updates
    if balance_updated or equity_updated:
        log.debug(
            f"PEAK EQUITY FORENSICS (AFTER UPDATE) | "
            f"CurrentBalance={balance:.2f} | "
            f"CurrentEquity={current_equity:.2f} | "
            f"PeakEquity={_state.peak_equity:.2f} | "
            f"PeakBalance={_state.peak_balance:.2f} | "
            f"Updated={balance_updated or equity_updated} | "
            f"Consistency=PeakEquity>=PeakBalance:{_state.peak_equity >= _state.peak_balance}"
        )
        save_risk_state(_state)  # CRITICAL: Persist immediately on peak update
    
    # CRITICAL: Verify peak_equity is not lower than peak_balance
    # (This should never happen after the max() logic, but safety check)
    if _state.peak_equity < _state.peak_balance:
        log.critical(
            f"PEAK EQUITY CONSISTENCY ERROR | PeakEquity={_state.peak_equity:.2f} < "
            f"PeakBalance={_state.peak_balance:.2f} | CORRECTING to {_state.peak_balance:.2f}"
        )
        _state.peak_equity = _state.peak_balance
        save_risk_state(_state)


_accounted_closure_tickets: set = set()


def _seed_accounted_closure_tickets_from_broker() -> None:
    """Mark today's closed position tickets so runtime finalize cannot double-count."""
    global _accounted_closure_tickets
    try:
        from utils import mt5_connector as broker_conn
        from datetime import datetime, date as date_type
        from execution.broker_state_manager import resolve_deal_position_id, DEAL_ENTRY_OUT

        history = broker_conn.get_deal_history(
            symbol=settings.SYMBOL,
            magic=settings.MAGIC,
            lookback_hours=24,
        )
        if "error" in history:
            return

        seeded = set()
        for deal in history.get("deals", []):
            if deal.get("entry") != DEAL_ENTRY_OUT:
                continue
            deal_time = deal.get("time") or 0
            try:
                deal_time_dt = (
                    datetime.fromtimestamp(float(deal_time)) if deal_time else None
                )
            except (TypeError, ValueError, OSError):
                deal_time_dt = None
            if not deal_time_dt or deal_time_dt.date() != date_type.today():
                continue
            position_id = resolve_deal_position_id(deal)
            if position_id:
                seeded.add(int(position_id))

        global _accounted_closure_tickets
        _accounted_closure_tickets = seeded
        if seeded:
            log.debug(
                f"CLOSURE TICKET GUARD SEEDED | Tickets: {sorted(seeded)}"
            )
    except Exception as e:
        log.warning(f"CLOSURE TICKET GUARD SEED FAILED | {e}")


def record_trade_result(pnl: float, ticket: int = None) -> None:
    """
    Call after each trade closes.
    Records P&L and trade count, then persists state to file.
    
    CRITICAL: This is called ONCE per trade closure.
    trades_today is already incremented when trade OPENS (increment_trade_count).
    closed_trades_today is incremented here when trade CLOSES.
    """
    if ticket is not None:
        if ticket in _accounted_closure_tickets:
            log.warning(
                f"TRADE RESULT ALREADY RECORDED | Ticket: {ticket} | "
                f"Skipping duplicate accounting"
            )
            return
        _accounted_closure_tickets.add(ticket)

    # ── DO NOT increment trades_today here ──────────────────────────────
    # It was already counted when the trade opened (increment_trade_count)
    
    # ── Increment closed trades counter when position closes ──────────────
    _state.closed_trades_today += 1
    
    _state.daily_pnl += pnl
    
    # Forensic: Log accounting update
    audit_log("TRADE_RESULT_RECORDED", {
        "pnl": pnl,
        "daily_pnl": _state.daily_pnl,
        "closed_trades_today": _state.closed_trades_today,
        "consecutive_losses": _state.consecutive_losses,
    })
    
    if pnl < 0:
        _state.consecutive_losses += 1
        log.warning(
            f"TRADE CLOSED | Loss | PnL: {pnl:.2f} | consecutive_losses={_state.consecutive_losses} | "
            f"daily_pnl={_state.daily_pnl:.2f} | closed_trades_today={_state.closed_trades_today}"
        )
    else:
        _state.consecutive_losses = 0
        log.info(
            f"TRADE CLOSED | Win | PnL: {pnl:.2f} | "
            f"daily_pnl={_state.daily_pnl:.2f} | closed_trades_today={_state.closed_trades_today}"
        )

    balance = _get_balance()
    update_peak(balance)
    _check_drawdown()
    
    # Forensic: Log peak balance after update
    audit_log("PEAK_BALANCE_UPDATED", {
        "current_balance": balance,
        "peak_balance": _state.peak_balance,
        "daily_pnl": _state.daily_pnl,
        "reason": "post_trade_result",
    })
    
    # ── CRITICAL: Persist risk state after every update ──────────────────
    save_risk_state(_state)


def _get_balance() -> float:
    info = conn.get_account_info()
    return info.balance if info else 0.0


def _check_drawdown() -> None:
    balance = _get_balance()
    if _state.peak_balance == 0:
        return
    dd_pct = ((_state.peak_balance - balance) / _state.peak_balance) * 100

    if dd_pct >= settings.DRAWDOWN_STOP_PCT:
        _state.bot_halted = True
        _state.active_risk_pct = 0.0
        log_drawdown_event(log, "STOP", dd_pct)
        log.critical(
            f"BOT HALTED - Drawdown {dd_pct:.2f}% >= {settings.DRAWDOWN_STOP_PCT}%"
        )
    elif dd_pct >= settings.DRAWDOWN_REDUCE_PCT:
        _state.active_risk_pct = settings.REDUCED_RISK_PERCENT
        log_drawdown_event(log, "REDUCE", dd_pct)


def compute_floating_pnl() -> float:
    """
    Calculate floating P&L from ALL currently open positions.
    LIVE from MT5 broker - never persisted, always recomputed.
    """
    open_positions = conn.get_open_positions(settings.SYMBOL, settings.MAGIC) or []
    total_floating = 0.0
    
    for pos in open_positions:
        # MT5 profit field is LIVE profit from entry price to current price
        pos_profit = pos.profit if hasattr(pos, 'profit') else 0.0
        total_floating += pos_profit
    
    return total_floating


def compute_equity() -> float:
    """
    Calculate current equity:
    equity = balance + floating_pnl
    """
    balance = _get_balance()
    floating = compute_floating_pnl()
    return balance + floating


def get_net_equity_pnl() -> float:
    """
    Net equity P&L:
    realized_pnl (from closed trades) + floating_pnl (from open positions)
    """
    floating = compute_floating_pnl()
    return _state.daily_pnl + floating


def compute_equity_drawdown() -> float:
    """
    Calculate equity-based drawdown (includes floating losses).
    
    FORENSIC FORMULA:
    equity_dd = ((peak_equity - current_equity) / peak_equity) * 100
    
    Example with floating loss:
    - peak_equity = 464.16 (anchored to balance at startup)
    - current_equity = 463.08 (balance 464.16 + floating -1.08)
    - equity_dd = ((464.16 - 463.08) / 464.16) * 100 = 0.23%
    """
    if _state.peak_equity == 0:
        return 0.0
    
    current_equity = compute_equity()
    dd = ((_state.peak_equity - current_equity) / _state.peak_equity) * 100
    
    # Log detailed forensic info on drawdown calculation
    log.debug(
        f"EQUITY DRAWDOWN FORENSICS | "
        f"Formula: ((PeakEquity - CurrentEquity) / PeakEquity) * 100 | "
        f"PeakEquity={_state.peak_equity:.2f} | "
        f"CurrentEquity={current_equity:.2f} | "
        f"Numerator(peak-current)={(_state.peak_equity - current_equity):.2f} | "
        f"Drawdown={dd:.2f}%"
    )
    
    return dd


def check_equity_drawdown() -> None:
    """
    Monitor equity drawdown and halt if breach - this includes floating losses.
    CRITICAL: Prevents overnight gap losses from being missed.
    """
    equity_dd = compute_equity_drawdown()
    
    log.debug(
        f"EQUITY FORENSICS | Balance={_get_balance():.2f} | "
        f"Floating={compute_floating_pnl():.2f} | "
        f"Equity={compute_equity():.2f} | "
        f"PeakEquity={_state.peak_equity:.2f} | "
        f"DD={equity_dd:.2f}%"
    )
    
    if equity_dd >= settings.DRAWDOWN_STOP_PCT:
        _state.bot_halted = True
        _state.active_risk_pct = 0.0
        log.critical(
            f"BOT HALTED - EQUITY Drawdown {equity_dd:.2f}% >= {settings.DRAWDOWN_STOP_PCT}% | "
            f"(Includes floating losses)"
        )
    elif equity_dd >= settings.DRAWDOWN_REDUCE_PCT:
        _state.active_risk_pct = settings.REDUCED_RISK_PERCENT
        log.warning(
            f"BOT REDUCED RISK - EQUITY Drawdown {equity_dd:.2f}% >= {settings.DRAWDOWN_REDUCE_PCT}%"
        )


def can_take_trade() -> tuple[bool, str]:
    """
    Return (allowed, reason).
    Checks: halt, daily trade limit, daily loss, consecutive losses.
    """
    from execution.startup_gate import is_trading_ready

    if not is_trading_ready():
        return False, "MT5 reconciliation not complete"

    if _state.bot_halted:
        return False, "Bot halted due to drawdown"

    if _state.trades_today >= settings.MAX_DAILY_TRADES:
        return False, f"Daily trade limit reached ({settings.MAX_DAILY_TRADES})"

    balance = _get_balance()
    if balance > 0:
        daily_loss_pct = abs(min(0, _state.daily_pnl)) / balance * 100
        if daily_loss_pct >= settings.MAX_DAILY_LOSS_PERCENT:
            return False, (
                f"Daily loss limit {settings.MAX_DAILY_LOSS_PERCENT}% reached "
                f"(current: {daily_loss_pct:.2f}%)"
            )

    if _state.consecutive_losses >= settings.CONSECUTIVE_LOSS_LIMIT:
        return False, (
            f"{_state.consecutive_losses} consecutive losses - trading paused"
        )

    return True, "Risk checks passed"


def increment_trade_count() -> None:
    """
    Call when a new trade order is sent (before it fills).
    Increments trade count and PERSISTS immediately to ensure crash safety.
    """
    _state.trades_today += 1
    # ── CRITICAL: Persist immediately to prevent loss on crash ──────────────
    save_risk_state(_state)
    log.info(f"Trade count incremented | trades_today={_state.trades_today} | Persisted to disk")


def calculate_lot_size(sl_points: float, symbol: str) -> float:
    """
    lot = (balance × risk_pct) / (sl_points × tick_value)

    tick_value : value of 1 point movement for 1 lot (instrument-specific).
    """
    info    = conn.get_account_info()
    sym     = conn.get_symbol_info(symbol)
    if info is None or sym is None:
        log.error("Cannot calculate lot size - account or symbol info unavailable")
        return 0.0

    balance    = info.balance
    risk_pct   = _state.active_risk_pct / 100.0
    risk_money = balance * risk_pct

    # tick_value = value of 1 point for 1 lot in account currency
    tick_value = sym.trade_tick_value   # in account currency per tick
    tick_size  = sym.trade_tick_size    # size of 1 tick in price units
    # Use internal trading point, not raw MT5 value (which may be incorrect for XAUUSDm)
    point      = conn.get_trading_point(symbol)

    if tick_value == 0 or sl_points == 0:
        log.error("tick_value or sl_points is zero - cannot size position")
        return 0.0

    # Convert sl_points (in points) to ticks
    sl_ticks = sl_points * (point / tick_size)
    lot = risk_money / (sl_ticks * tick_value)

    # Clamp to broker's min/max
    lot = max(sym.volume_min, min(sym.volume_max, lot))
    # Round to broker's step
    step = sym.volume_step
    lot  = round(round(lot / step) * step, 8)

    log.info(
        f"Lot size: {lot} | Balance: {balance:.2f} | Risk: {risk_pct*100:.2f}% "
        f"| SL pts: {sl_points} | tick_val: {tick_value}"
    )
    return lot


def get_state() -> RiskState:
    return _state


def reconstruct_daily_state_from_broker() -> bool:
    """
    Reconstruct daily risk state from MT5 broker data.
    PHASE 4 CORRECTED: Count ONE trade per position lifecycle, not per deal.
    
    Returns True if reconstruction was successful and state was updated.
    """
    global _state, _accounted_closure_tickets
    
    try:
        from utils import mt5_connector as broker_conn
        from datetime import datetime, date as date_type
        from collections import defaultdict
        from execution.broker_state_manager import (
            resolve_deal_position_id,
            DEAL_ENTRY_OUT,
        )
        
        # ─── TIME FORENSICS ───────────────────────────────────────────────
        today_start = datetime.combine(date_type.today(), datetime.min.time())
        today_end = datetime.combine(date_type.today(), datetime.max.time())
        now = datetime.now()
        
        log.info(
            f"TIME FORENSICS | today_start={today_start.isoformat()} | "
            f"today_end={today_end.isoformat()} | now={now.isoformat()}"
        )
        
        # Get current open positions - these are TODAY's ACTIVE trades
        open_positions = broker_conn.get_open_positions(settings.SYMBOL, settings.MAGIC) or []
        open_position_count = len(open_positions)
        
        log.info(f"OPEN POSITIONS TODAY | Count: {open_position_count}")
        for pos in open_positions:
            log.debug(
                f"  - Position ticket={pos.ticket} | symbol={pos.symbol} | "
                f"magic={pos.magic} | type={'BUY' if pos.type == mt5.ORDER_TYPE_BUY else 'SELL'} | "
                f"price_open={pos.price_open} | time_open={pos.time}"
            )
        
        # ─── QUERY DEAL HISTORY ───────────────────────────────────────────
        # Use narrow time window: TODAY ONLY (not 24 hours)
        history = broker_conn.get_deal_history(
            symbol=settings.SYMBOL, 
            magic=settings.MAGIC, 
            lookback_hours=24  # Still use 24h for API, but filter strictly to TODAY
        )
        
        # ─── GROUP DEALS BY POSITION ID ───────────────────────────────────
        # CRITICAL: Multiple deals can belong to same position (entry + exit + fees)
        # We must group by position_id and only count completed positions
        position_deals = defaultdict(list)
        all_deals_log = []
        
        if "error" not in history:
            deals = history.get("deals", [])
            
            log.info(f"FORENSIC ANALYSIS | Total deals returned: {len(deals)}")
            
            for i, deal in enumerate(deals):
                position_id = resolve_deal_position_id(deal)
                deal_time = deal.get("time") or 0
                try:
                    deal_time_dt = (
                        datetime.fromtimestamp(float(deal_time)) if deal_time else None
                    )
                except (TypeError, ValueError, OSError):
                    deal_time_dt = None

                # ─── STRICT TIME FILTERING: TODAY ONLY ─────────────────────
                is_today = bool(
                    deal_time_dt and deal_time_dt.date() == date_type.today()
                )

                log.debug(
                    f"DEAL FORENSICS | #{i} | ticket={deal.get('ticket')} | "
                    f"position_id={position_id} | entry={deal.get('entry')} | "
                    f"symbol={deal.get('symbol')} | magic={deal.get('magic')} | "
                    f"type={deal.get('type')} | volume={deal.get('volume')} | "
                    f"profit={deal.get('profit', 0):.2f} | "
                    f"time={deal_time_dt.isoformat() if deal_time_dt else 'unknown'} | "
                    f"is_today={is_today}"
                )

                if not position_id:
                    log.debug("  - REJECTED: Could not resolve position id")
                    continue

                # CRITICAL: Only count deals from TODAY
                if not is_today:
                    if deal_time_dt:
                        log.debug(
                            f"  - REJECTED: Deal from {deal_time_dt.date()}, not today"
                        )
                    continue

                # Only count exit legs (DEAL_ENTRY_OUT) for realized P&L
                if deal.get("entry") != DEAL_ENTRY_OUT:
                    log.debug(
                        f"  - REJECTED: Not a closing deal (entry={deal.get('entry')})"
                    )
                    continue

                log.debug("  - ACCEPTED: TODAY closing deal")
                position_deals[position_id].append(deal)
                all_deals_log.append({
                    "position_id": position_id,
                    "ticket": deal.get("ticket"),
                    "profit": deal.get("profit"),
                    "is_today": is_today,
                    "accepted": True
                })
        
        # ─── COUNT COMPLETED POSITION LIFECYCLES ──────────────────────────
        # Only count positions that had closing deals TODAY
        completed_positions = []
        realized_pnl = 0.0
        wins = 0
        losses = 0
        
        for position_id, deals_list in position_deals.items():
            # Sum profit from all deals for this position
            position_profit = sum(d.get("profit", 0.0) for d in deals_list)
            realized_pnl += position_profit
            
            if position_profit > 0:
                wins += 1
                log.info(
                    f"COMPLETED POSITION | position_id={position_id} | "
                    f"deals={len(deals_list)} | profit={position_profit:.2f} | WIN"
                )
            elif position_profit < 0:
                losses += 1
                log.warning(
                    f"COMPLETED POSITION | position_id={position_id} | "
                    f"deals={len(deals_list)} | profit={position_profit:.2f} | LOSS"
                )
            else:
                log.info(
                    f"COMPLETED POSITION | position_id={position_id} | "
                    f"deals={len(deals_list)} | profit=0.00 | BREAKEVEN"
                )
            
            completed_positions.append(position_id)
        
        closed_position_count = len(completed_positions)
        
        # ─── TOTAL TRADES = OPEN + CLOSED TODAY ───────────────────────────
        # CRITICAL: We only count positions closed TODAY, not all deals
        total_trades_today = open_position_count + closed_position_count
        consecutive_losses = losses  # Conservative: assume last loss is most recent
        
        # Update state
        _state.trades_today = total_trades_today
        _state.closed_trades_today = closed_position_count
        _state.daily_pnl = realized_pnl
        _state.consecutive_losses = consecutive_losses
        _state.day = date_type.today()
        
        # ── CRITICAL: Re-anchor peak_equity to maximum known reference ──────────────────────
        # This ensures peak_equity is never left below available balance after reconstruction
        current_balance = _get_balance()
        current_floating = compute_floating_pnl()
        current_equity = current_balance + current_floating
        
        # Peak equity must be max of: persisted, current balance, current equity
        # This prevents DD from resetting if peak_equity was corrupted during broker reconstruction
        selected_peak_equity = max(_state.peak_equity, current_balance, current_equity)
        
        log.debug(
            f"PEAK EQUITY FORENSICS (BROKER RECONSTRUCTION) | "
            f"PersistedPeakEquity={_state.peak_equity:.2f} | "
            f"CurrentBalance={current_balance:.2f} | "
            f"CurrentEquity={current_equity:.2f} | "
            f"CurrentFloating={current_floating:.2f} | "
            f"SelectedPeakEquity={selected_peak_equity:.2f} | "
            f"Reason=max(persisted, balance, equity)"
        )
        
        if selected_peak_equity > _state.peak_equity:
            log.warning(
                f"PEAK EQUITY CORRECTED (BROKER RECONSTRUCTION) | "
                f"Was: {_state.peak_equity:.2f} | Now: {selected_peak_equity:.2f} | "
                f"Change: +{selected_peak_equity - _state.peak_equity:.2f}"
            )
            _state.peak_equity = selected_peak_equity
        
        # Persist reconstructed state
        save_risk_state(_state)

        _accounted_closure_tickets.clear()
        _accounted_closure_tickets.update(
            int(pid) for pid in completed_positions if pid
        )

        log.info(
            f"BROKER RECONSTRUCTION VERIFIED | "
            f"Open today: {open_position_count} | "
            f"Closed today: {closed_position_count} | "
            f"Total: {total_trades_today} | "
            f"Daily PnL: {realized_pnl:.2f} | "
            f"Wins: {wins} | Losses: {losses}"
        )
        return True
        
    except Exception as e:
        log.warning(f"BROKER RECONSTRUCTION | Failed: {e}", exc_info=True)
        return False

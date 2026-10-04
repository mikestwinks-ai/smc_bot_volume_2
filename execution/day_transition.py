"""
day_transition.py — Safe calendar-day transition with MT5 authority.

Replaces naive counter wipe at midnight with broker-backed reconciliation.
"""

from __future__ import annotations

from datetime import date

from config import settings
from utils import mt5_connector as conn
from utils.logger import get_logger
from execution.startup_gate import set_trading_ready, is_trading_ready

log = get_logger(__name__)

_tracked_calendar_date: date | None = None
_transition_in_progress: bool = False


def is_day_transition_locked() -> bool:
    return _transition_in_progress


def handle_day_transition_if_needed(
    symbol: str = settings.SYMBOL,
    balance: float = 0.0,
) -> bool:
    """
    On calendar date change while bot is running:
      1. Brief trading freeze
      2. Process broker closures / pending finalizations
      3. Rebuild today's counters from MT5 (no blind zero wipe)
      4. Restore trading_ready if MT5 healthy

    Returns True if a transition was executed this call.
    """
    global _tracked_calendar_date, _transition_in_progress

    today = date.today()
    if _tracked_calendar_date is None:
        from execution.risk_manager import get_state

        state_day = get_state().day
        _tracked_calendar_date = state_day if state_day else today
        if _tracked_calendar_date == today:
            return False

    if _tracked_calendar_date == today:
        return False

    old_date = _tracked_calendar_date
    was_ready = is_trading_ready()
    _transition_in_progress = True
    set_trading_ready(False)

    log.warning(
        f"DAY TRANSITION START | {old_date.isoformat()} -> {today.isoformat()} | "
        f"Trading frozen for broker reconciliation"
    )

    try:
        if not conn.is_connected():
            log.error("DAY TRANSITION | MT5 not connected — counters not reset")
            return False

        # Finalize any closures still pending (position disappeared on broker)
        try:
            from execution.trade_manager import detect_and_process_closed_positions

            detect_and_process_closed_positions(symbol)
        except Exception as e:
            log.error(f"DAY TRANSITION | Closure sweep failed: {e}", exc_info=True)

        # Reconcile previous-day persisted orphans against broker history
        _reconcile_previous_day_orphans(symbol, old_date)

        # Rebuild TODAY from MT5 (authoritative — not zero wipe)
        from execution.risk_manager import (
            reconstruct_daily_state_from_broker,
            _seed_accounted_closure_tickets_from_broker,
            update_intraday_peaks,
        )

        if not reconstruct_daily_state_from_broker():
            log.error("DAY TRANSITION | Broker counter rebuild failed")
            return False

        _seed_accounted_closure_tickets_from_broker()

        if balance > 0:
            update_intraday_peaks(balance)

        _tracked_calendar_date = today

        log.info(
            f"DAY TRANSITION COMPLETE | Date: {old_date.isoformat()} -> {today.isoformat()}"
        )
        return True

    except Exception as e:
        log.error(f"DAY TRANSITION FAILED | {e}", exc_info=True)
        return False

    finally:
        _transition_in_progress = False
        if was_ready and conn.is_connected():
            from execution.mt5_resilience import verify_mt5_terminal_health

            if verify_mt5_terminal_health(symbol):
                set_trading_ready(True)
            else:
                log.warning(
                    "DAY TRANSITION | MT5 health check failed — trading remains disabled"
                )


def _reconcile_previous_day_orphans(symbol: str, old_date: date) -> None:
    """Finalize persisted tickets that closed on the previous calendar day."""
    from execution.state_persistence import load_trade_states
    from execution.trade_manager import (
        _resolve_orphan_tickets,
        get_active_trade_state_count,
    )

    persisted = load_trade_states() or {}
    if not persisted:
        return

    open_positions = conn.get_open_positions(symbol, settings.MAGIC) or []
    broker_open = {
        p.ticket for p in open_positions if hasattr(p, "ticket")
    }
    candidate_tickets = [
        int(t) for t in persisted.keys() if int(t) not in broker_open
    ]
    if not candidate_tickets:
        return

    log.info(
        f"DAY TRANSITION | Reconciling {len(candidate_tickets)} persisted ticket(s) "
        f"from prior day {old_date.isoformat()}"
    )
    finalized, unresolved = _resolve_orphan_tickets(
        candidate_tickets, persisted, symbol
    )
    if finalized:
        log.info(f"DAY TRANSITION | Prior-day closures finalized: {finalized}")
    if unresolved:
        log.warning(
            f"DAY TRANSITION | Prior-day orphans unresolved (non-fatal): {unresolved}"
        )

    _ = get_active_trade_state_count()

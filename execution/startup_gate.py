"""
startup_gate.py — Blocking MT5 reconciliation gate before any trading logic runs.

trading_ready is False until full broker reconciliation completes successfully.
"""

from __future__ import annotations

from config import settings
from utils import mt5_connector as conn
from utils.logger import get_logger

log = get_logger(__name__)

_trading_ready: bool = False

BLOCKED_MSG = "[INFO] Trading blocked — MT5 reconciliation not complete"
READY_MSG = "[INFO] MT5 RECONCILIATION COMPLETE | Trading system is now READY"
FAILED_MSG = "[ERROR] MT5 RECONCILIATION FAILED | Trading disabled"


def is_trading_ready() -> bool:
    return _trading_ready


def set_trading_ready(ready: bool) -> None:
    global _trading_ready
    _trading_ready = ready


def log_trading_blocked() -> None:
    log.info(BLOCKED_MSG)


def run_blocking_mt5_reconciliation(
    symbol: str = settings.SYMBOL,
) -> bool:
    """
    Blocking startup reconciliation — MT5 is the sole authority.

    Order:
      1. Verify MT5 connection
      2. Sync open positions / active trade state from MT5
      3. Finalize broker-closed positions (position_id mapping)
      4. Reconstruct daily risk counters from MT5 deal history
      5. Validate no unresolved orphans or position count mismatch
    """
    set_trading_ready(False)
    log.info("MT5 STARTUP RECONCILIATION | Blocking gate — trading disabled")

    if not conn.is_connected():
        log.error(f"{FAILED_MSG} | MT5 not connected")
        return False

    try:
        from execution.trade_manager import (
            reconcile_positions_on_startup,
            get_active_trade_state_count,
        )
        from execution.risk_manager import (
            reconstruct_daily_state_from_broker,
            _seed_accounted_closure_tickets_from_broker,
        )

        positions_ok, unresolved = reconcile_positions_on_startup(symbol)
        if not positions_ok:
            log.error(
                f"{FAILED_MSG} | Position/trade state reconciliation failed | "
                f"Unresolved: {unresolved or 'see logs'}"
            )
            return False

        if unresolved:
            log.error(
                f"{FAILED_MSG} | Unresolved orphan ticket(s): {unresolved}"
            )
            return False

        if not reconstruct_daily_state_from_broker():
            log.error(
                f"{FAILED_MSG} | Daily risk counters could not be rebuilt from MT5"
            )
            return False

        _seed_accounted_closure_tickets_from_broker()

        open_positions = conn.get_open_positions(symbol, settings.MAGIC) or []
        broker_count = len(open_positions)
        memory_count = get_active_trade_state_count()

        if broker_count != memory_count:
            log.error(
                f"{FAILED_MSG} | Position count mismatch | "
                f"MT5 open={broker_count} | memory={memory_count}"
            )
            return False

        if not conn.is_connected():
            log.error(f"{FAILED_MSG} | MT5 connection lost during reconciliation")
            return False

        log.info(READY_MSG)
        return True

    except Exception as e:
        log.error(f"{FAILED_MSG} | {e}", exc_info=True)
        return False


def run_lightweight_mt5_reconciliation(
    symbol: str = settings.SYMBOL,
) -> bool:
    """
    Post-reconnect reconciliation: open positions + today's MT5 counters.
    Does not fail on historical orphan tickets (non-blocking for recovery).
    """
    log.info("MT5 LIGHTWEIGHT RECONCILIATION | Starting...")
    set_trading_ready(False)

    if not conn.is_connected():
        log.error(f"{FAILED_MSG} | MT5 not connected")
        return False

    try:
        from execution.mt5_resilience import verify_mt5_terminal_health
        from execution.trade_manager import (
            sync_active_positions_from_mt5,
            get_active_trade_state_count,
        )
        from execution.risk_manager import (
            reconstruct_daily_state_from_broker,
            _seed_accounted_closure_tickets_from_broker,
        )

        if not verify_mt5_terminal_health(symbol):
            log.error(f"{FAILED_MSG} | Terminal health check failed")
            return False

        sync_active_positions_from_mt5(symbol)

        if not reconstruct_daily_state_from_broker():
            log.error(f"{FAILED_MSG} | Daily counter rebuild failed")
            return False

        _seed_accounted_closure_tickets_from_broker()

        open_positions = conn.get_open_positions(symbol, settings.MAGIC) or []
        if len(open_positions) != get_active_trade_state_count():
            log.warning(
                f"MT5 LIGHTWEIGHT RECONCILIATION | Position count mismatch | "
                f"MT5={len(open_positions)} | memory={get_active_trade_state_count()}"
            )

        set_trading_ready(True)
        log.info("MT5 LIGHTWEIGHT RECONCILIATION | Complete | trading_ready=True")
        return True

    except Exception as e:
        log.error(f"{FAILED_MSG} | Lightweight: {e}", exc_info=True)
        return False

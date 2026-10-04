"""
mt5_resilience.py — MT5 connection health, reconnect, and recovery reconciliation.
"""

from __future__ import annotations

import time

from config import settings
from utils import mt5_connector as conn
from utils.logger import get_logger
from execution.startup_gate import (
    set_trading_ready,
    is_trading_ready,
    run_blocking_mt5_reconciliation,
    run_lightweight_mt5_reconciliation,
)

log = get_logger(__name__)

_last_recovery_attempt: float = 0.0
RECOVERY_COOLDOWN_SECONDS = 120.0


def verify_mt5_terminal_health(symbol: str = settings.SYMBOL) -> bool:
    """Verify terminal connection, account, and symbol are reachable."""
    if not conn.is_connected():
        return False
    account = conn.get_account_info()
    if account is None:
        return False
    sym = conn.get_symbol_info(symbol)
    if sym is None:
        return False
    return True


def is_mt5_stale() -> bool:
    """True when terminal reports disconnected."""
    return not conn.is_connected()


def attempt_mt5_recovery(
    symbol: str = settings.SYMBOL,
    *,
    lightweight: bool = True,
    max_retries: int = 5,
    retry_delay: float = 10.0,
) -> bool:
    """
    Reconnect MT5 and re-sync state. Disables trading_ready until safe.
    """
    global _last_recovery_attempt

    now = time.time()
    if now - _last_recovery_attempt < RECOVERY_COOLDOWN_SECONDS:
        log.debug("MT5 RECOVERY | Cooldown active — skipping duplicate recovery")
        return is_trading_ready()

    _last_recovery_attempt = now
    was_ready = is_trading_ready()
    set_trading_ready(False)

    log.warning(
        f"MT5 RECOVERY START | lightweight={lightweight} | "
        f"max_retries={max_retries}"
    )

    if conn.is_connected() and verify_mt5_terminal_health(symbol):
        reconcile_ok = (
            run_lightweight_mt5_reconciliation(symbol)
            if lightweight
            else run_blocking_mt5_reconciliation(symbol)
        )
        if reconcile_ok:
            log.info("MT5 RECOVERY | Connection healthy — trading re-enabled")
            return True
        log.error("MT5 RECOVERY | Reconciliation failed after healthy connection")
        return False

    if not conn.reconnect(retries=max_retries, delay=retry_delay):
        log.error("MT5 RECOVERY | Reconnect failed — trading disabled")
        return False

    if not verify_mt5_terminal_health(symbol):
        log.error("MT5 RECOVERY | Post-reconnect health check failed")
        return False

    reconcile_ok = (
        run_lightweight_mt5_reconciliation(symbol)
        if lightweight
        else run_blocking_mt5_reconciliation(symbol)
    )

    if reconcile_ok:
        log.info("MT5 RECOVERY | Reconnect and reconciliation successful")
        return True

    log.error("MT5 RECOVERY | Reconciliation failed after reconnect")
    if was_ready:
        set_trading_ready(False)
    return False

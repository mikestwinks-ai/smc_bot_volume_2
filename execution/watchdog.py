"""
watchdog.py — Internal health monitor for 24/7 VPS operation.
"""

from __future__ import annotations

import time
from typing import Optional

from config import settings
from utils.logger import get_logger, check_logger_health, run_logger_health_maintenance
from execution.startup_gate import is_trading_ready, log_trading_blocked
from execution.mt5_resilience import (
    is_mt5_stale,
    verify_mt5_terminal_health,
    attempt_mt5_recovery,
)
from execution.day_transition import is_day_transition_locked

log = get_logger(__name__)

_last_successful_tick: float = time.time()
_last_iteration_end: float = time.time()
_consecutive_exceptions: int = 0
_recovery_attempts: int = 0
_last_logger_health_log: float = 0.0

LOGGER_HEALTH_INTERVAL = 300.0  # 5 minutes
FREEZE_MULTIPLIER = 5.0
MAX_CONSECUTIVE_EXCEPTIONS = 5
MAX_RECOVERY_ATTEMPTS_PER_HOUR = 12
_recovery_window_start: float = time.time()


def mark_loop_success() -> None:
    global _last_successful_tick, _consecutive_exceptions
    _last_successful_tick = time.time()
    _consecutive_exceptions = 0


def record_loop_exception() -> None:
    global _consecutive_exceptions
    _consecutive_exceptions += 1


def mark_iteration_end() -> None:
    global _last_iteration_end
    _last_iteration_end = time.time()


def _freeze_threshold_seconds() -> float:
    return float(settings.LOOP_SLEEP_SECONDS) * FREEZE_MULTIPLIER


def check_frozen_loop() -> bool:
    """True if the main loop has not completed an iteration in too long."""
    elapsed = time.time() - _last_iteration_end
    return elapsed > _freeze_threshold_seconds()


def check_repeated_exceptions() -> bool:
    return _consecutive_exceptions >= MAX_CONSECUTIVE_EXCEPTIONS


def run_logger_health_if_due(main_logger) -> None:
    global _last_logger_health_log
    now = time.time()
    if now - _last_logger_health_log < LOGGER_HEALTH_INTERVAL:
        return
    _last_logger_health_log = now
    run_logger_health_maintenance(main_logger)


def evaluate_and_recover(main_logger, symbol: str = settings.SYMBOL) -> None:
    """
    Run watchdog checks and attempt safe recovery without exiting the process.
    """
    global _recovery_attempts, _recovery_window_start

    if is_day_transition_locked():
        return

    now = time.time()
    if now - _recovery_window_start > 3600:
        _recovery_window_start = now
        _recovery_attempts = 0

    reasons: list[str] = []

    if check_frozen_loop():
        reasons.append(
            f"frozen loop ({time.time() - _last_iteration_end:.0f}s since last iteration)"
        )

    if check_repeated_exceptions():
        reasons.append(f"repeated exceptions ({_consecutive_exceptions})")

    if is_mt5_stale():
        reasons.append("MT5 disconnected")

    if not check_logger_health(main_logger):
        reasons.append("logger handler unhealthy")

    if not reasons:
        return

    if _recovery_attempts >= MAX_RECOVERY_ATTEMPTS_PER_HOUR:
        log.critical(
            f"WATCHDOG | Recovery limit reached ({MAX_RECOVERY_ATTEMPTS_PER_HOUR}/hr) | "
            f"Reasons: {reasons}"
        )
        return

    _recovery_attempts += 1
    reason_str = "; ".join(reasons)
    log.warning(f"WATCHDOG RECOVERY TRIGGERED | Reason: {reason_str}")

    run_logger_health_maintenance(main_logger)

    if is_mt5_stale() or not verify_mt5_terminal_health(symbol):
        attempt_mt5_recovery(symbol, lightweight=True)
    elif "logger" in reason_str:
        pass  # logger maintenance already ran
    elif check_repeated_exceptions() or check_frozen_loop():
        if is_trading_ready():
            attempt_mt5_recovery(symbol, lightweight=True)
        else:
            log_trading_blocked()
            attempt_mt5_recovery(symbol, lightweight=True)

    mark_loop_success()


def get_watchdog_status() -> dict:
    return {
        "last_successful_tick": _last_successful_tick,
        "seconds_since_tick": time.time() - _last_successful_tick,
        "consecutive_exceptions": _consecutive_exceptions,
        "recovery_attempts_hour": _recovery_attempts,
    }

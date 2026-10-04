"""
Production hardening stress tests (no MT5 / no live trading required).

Run: python -m pytest tests/test_production_stress.py -v
  or: python tests/test_production_stress.py
"""

from __future__ import annotations

import logging
import os
import sys
import time

_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)
import unittest
from datetime import date, timedelta
from unittest.mock import MagicMock, patch


class TestWatchdog(unittest.TestCase):
    def setUp(self):
        import execution.watchdog as wd

        wd._last_successful_tick = time.time()
        wd._last_iteration_end = time.time()
        wd._consecutive_exceptions = 0
        wd._recovery_attempts = 0

    def test_repeated_exceptions_detected(self):
        import execution.watchdog as wd

        for _ in range(wd.MAX_CONSECUTIVE_EXCEPTIONS):
            wd.record_loop_exception()
        self.assertTrue(wd.check_repeated_exceptions())

    def test_mark_loop_success_resets_exceptions(self):
        import execution.watchdog as wd

        wd.record_loop_exception()
        wd.mark_loop_success()
        self.assertEqual(wd._consecutive_exceptions, 0)


class TestDayTransition(unittest.TestCase):
    def test_no_transition_same_day(self):
        import execution.day_transition as dt

        dt._tracked_calendar_date = date.today()
        dt._transition_in_progress = False
        with patch("execution.startup_gate.is_trading_ready", return_value=True):
            result = dt.handle_day_transition_if_needed("XAUUSDm", 1000.0)
        self.assertFalse(result)

    def test_transition_invokes_broker_rebuild(self):
        import execution.day_transition as dt

        yesterday = date.today() - timedelta(days=1)
        dt._tracked_calendar_date = yesterday
        dt._transition_in_progress = False

        with patch("execution.startup_gate.is_trading_ready", return_value=True), patch(
            "execution.startup_gate.set_trading_ready"
        ), patch("utils.mt5_connector.is_connected", return_value=True), patch(
            "execution.trade_manager.detect_and_process_closed_positions"
        ), patch(
            "execution.day_transition._reconcile_previous_day_orphans"
        ), patch(
            "execution.risk_manager.reconstruct_daily_state_from_broker",
            return_value=True,
        ), patch(
            "execution.risk_manager._seed_accounted_closure_tickets_from_broker"
        ), patch(
            "execution.risk_manager.update_intraday_peaks"
        ), patch(
            "execution.mt5_resilience.verify_mt5_terminal_health",
            return_value=True,
        ):
            result = dt.handle_day_transition_if_needed("XAUUSDm", 1000.0)

        self.assertTrue(result)
        self.assertEqual(dt._tracked_calendar_date, date.today())


class TestLoggerSharedHandler(unittest.TestCase):
    def test_single_shared_file_handler(self):
        import utils.logger as logmod

        logmod._SHARED_FILE_HANDLER = None
        logmod._CONFIGURED_LOGGERS.clear()

        a = logmod.get_logger("test.a")
        b = logmod.get_logger("test.b")
        shared = logmod._get_shared_file_handler()

        self.assertTrue(any(h is shared for h in a.handlers))
        self.assertTrue(any(h is shared for h in b.handlers))
        file_handlers = [
            h for h in a.handlers + b.handlers
            if isinstance(h, logging.handlers.TimedRotatingFileHandler)
        ]
        self.assertEqual(len(file_handlers), 2)
        self.assertIs(file_handlers[0], file_handlers[1])

    def test_logger_health_check(self):
        import sys
        import utils.logger as logmod

        logmod._SHARED_FILE_HANDLER = None
        logmod._CONFIGURED_LOGGERS.clear()
        logger = logmod.get_logger("test.health")
        ch = logmod._get_console_stream_handler(logger)
        self.assertIsNotNone(ch)
        self.assertIs(ch.stream, sys.stdout)
        self.assertTrue(logmod.check_logger_health(logger))

    def test_rebuild_preserves_stdout_console(self):
        import sys
        import utils.logger as logmod

        logmod._SHARED_FILE_HANDLER = None
        logmod._CONFIGURED_LOGGERS.clear()
        logger = logmod.get_logger("test.rebuild")
        logmod._rebuild_shared_file_handler()
        ch = logmod._get_console_stream_handler(logger)
        self.assertIsNotNone(ch)
        self.assertIs(ch.stream, sys.stdout)


class TestMt5Resilience(unittest.TestCase):
    def test_recovery_disables_then_reenables_trading(self):
        import execution.mt5_resilience as res
        import execution.startup_gate as gate

        gate.set_trading_ready(True)
        with patch(
            "utils.mt5_connector.is_connected",
            side_effect=[False, True, True],
        ), patch(
            "utils.mt5_connector.reconnect", return_value=True
        ), patch(
            "execution.mt5_resilience.verify_mt5_terminal_health",
            return_value=True,
        ), patch(
            "execution.startup_gate.run_lightweight_mt5_reconciliation",
            return_value=True,
        ):
            res._last_recovery_attempt = 0.0
            ok = res.attempt_mt5_recovery("XAUUSDm", lightweight=True)
        self.assertTrue(ok)
        self.assertTrue(gate.is_trading_ready())


class TestLoopExceptionContinues(unittest.TestCase):
    """Simulate injected loop error — process must not assume crash."""

    def test_exception_counter_increments_without_exit(self):
        import execution.watchdog as wd

        wd._consecutive_exceptions = 0
        wd.record_loop_exception()
        self.assertEqual(wd._consecutive_exceptions, 1)


def run_tests():
    loader = unittest.TestLoader()
    suite = loader.loadTestsFromModule(sys.modules[__name__])
    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)
    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    sys.exit(run_tests())

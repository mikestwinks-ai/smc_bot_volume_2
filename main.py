"""
main.py - SMC Trading Bot Entry Point

Execution loop:
  1. Connect to MT5
  2. Blocking MT5 reconciliation (trading_ready gate)
  3. Every LOOP_SLEEP_SECONDS (watchdog + recovery always; trading if ready):
     a. Check session & Friday/weekend rules
     b. Manage open trades
     c. If entry allowed -> compute H4 bias -> M15/M5 confluence -> attempt entry
  4. Graceful shutdown on KeyboardInterrupt / fatal error
"""

import time
import signal
import sys
import traceback

from config import settings
from config.sessions import (
    can_open_trade, must_close_all, current_session,
    get_daily_intraday_phase, should_log_phase_transition,
    is_hard_flatten_window, is_emergency_cutoff_active
)
from strategy.bias_engine import compute_h4_bias
from strategy.confluence_engine import score_confluence
from execution.entry_engine import attempt_entry
from execution.trade_manager import manage_open_trades, force_close_all, is_lifecycle_lock_active
from execution.lifecycle_coordinator import is_stabilization_lock_active, mark_startup_complete
from execution.risk_manager import reset_daily_state, can_take_trade, get_state
from execution.startup_gate import (
    is_trading_ready,
    run_blocking_mt5_reconciliation,
    set_trading_ready,
    log_trading_blocked,
)
from execution.watchdog import (
    mark_loop_success,
    record_loop_exception,
    mark_iteration_end,
    evaluate_and_recover,
    run_logger_health_if_due,
)
from execution.mt5_resilience import (
    is_mt5_stale,
    verify_mt5_terminal_health,
    attempt_mt5_recovery,
)
from execution.day_transition import is_day_transition_locked
from utils import mt5_connector as conn
from utils.logger import get_logger, log_no_trade, flush_all_handlers, log_heartbeat

log = get_logger("smc_bot.main")

_running = True
_loop_iteration = 0
_recovery_tick = 0


def _shutdown(signum, frame):
    global _running
    log.info(f"Signal {signum} received - shutting down gracefully.")
    _running = False


def _fetch_all_data() -> tuple:
    df_h4 = conn.get_bars(settings.SYMBOL, settings.TF_H4, settings.H4_BARS)
    df_m15 = conn.get_bars(settings.SYMBOL, settings.TF_M15, settings.M15_BARS)
    df_m5 = conn.get_bars(settings.SYMBOL, settings.TF_M5, settings.M5_BARS)
    return df_h4, df_m15, df_m5


def _ensure_mt5_connected() -> bool:
    """Keep terminal connected; disable trading if recovery fails."""
    if verify_mt5_terminal_health(settings.SYMBOL):
        return True

    if is_mt5_stale():
        log.warning("MT5 connection lost - attempting reconnect...")

    if attempt_mt5_recovery(settings.SYMBOL, lightweight=True):
        return True

    set_trading_ready(False)
    log.critical("Cannot restore MT5 — trading disabled until recovery succeeds")
    return False


def _main_loop() -> None:
    global _running, _loop_iteration, _recovery_tick

    while _running:
        try:
            run_logger_health_if_due(log)
            evaluate_and_recover(log, settings.SYMBOL)

            if not _ensure_mt5_connected():
                mark_iteration_end()
                time.sleep(min(60, settings.LOOP_SLEEP_SECONDS))
                continue

            if not is_trading_ready():
                _recovery_tick += 1
                if _recovery_tick % 5 == 0:
                    log_trading_blocked()
                    attempt_mt5_recovery(settings.SYMBOL, lightweight=True)
                mark_iteration_end()
                time.sleep(settings.LOOP_SLEEP_SECONDS)
                continue

            _loop_iteration += 1
            mark_loop_success()

            if _loop_iteration % 6 == 0:
                positions = len(conn.get_open_positions(settings.SYMBOL, settings.MAGIC)) or 0
                log_heartbeat(log, {
                    "positions": positions,
                    "trades_today": get_state().trades_today,
                    "logger_health": "ok",
                })
                flush_all_handlers(log)

            account = conn.get_account_info()
            if account is None:
                log.error("Cannot fetch account info - skipping iteration")
                attempt_mt5_recovery(settings.SYMBOL, lightweight=True)
                mark_iteration_end()
                time.sleep(settings.LOOP_SLEEP_SECONDS)
                continue

            balance = account.balance
            session = current_session()

            if not is_day_transition_locked():
                reset_daily_state(balance)

            log.debug(
                f"Loop tick | Session: {session} | Balance: {balance:.2f} | "
                f"Trades today: {get_state().trades_today}"
            )

            from config.sessions import check_market_close_approaching
            check_market_close_approaching(log)

            daily_phase, phase_desc = get_daily_intraday_phase()
            if should_log_phase_transition():
                log.warning(f"SESSION STATE CHANGE: {daily_phase} | {phase_desc}")

            close_all, close_reason = must_close_all()
            if close_all:
                force_close_all(settings.SYMBOL, close_reason)
                log.info(f"Sleeping after force-close: {close_reason}")
                mark_iteration_end()
                time.sleep(settings.LOOP_SLEEP_SECONDS)
                continue

            hard_flatten_active = is_hard_flatten_window()
            if hard_flatten_active:
                positions_before = len(conn.get_open_positions(settings.SYMBOL, settings.MAGIC) or [])
                log.critical(
                    f"HARD FLATTEN ACTIVE | Window 22:45-22:55 | "
                    f"Positions before close: {positions_before}"
                )
                force_close_all(settings.SYMBOL, "Daily hard flatten window (22:45-22:55)")
                mark_iteration_end()
                time.sleep(settings.LOOP_SLEEP_SECONDS)
                continue

            emergency_cutoff_active = is_emergency_cutoff_active()
            if emergency_cutoff_active:
                positions = conn.get_open_positions(settings.SYMBOL, settings.MAGIC) or []
                log.critical(f"EMERGENCY CUTOFF ACTIVE | Time 23:05+ | Positions: {len(positions)}")
                if positions:
                    force_close_all(settings.SYMBOL, "Daily emergency cutoff (23:05+)")
                mark_iteration_end()
                time.sleep(settings.LOOP_SLEEP_SECONDS)
                continue

            manage_open_trades(settings.SYMBOL)
            flush_all_handlers(log)

            if is_lifecycle_lock_active():
                log.warning(
                    "SIGNAL ENGINE BLOCKED | Trade lifecycle processing in progress"
                )
                mark_iteration_end()
                time.sleep(settings.LOOP_SLEEP_SECONDS)
                continue

            if is_stabilization_lock_active():
                log.warning(
                    "SIGNAL ENGINE BLOCKED | Technical stabilization in progress"
                )
                mark_iteration_end()
                time.sleep(settings.LOOP_SLEEP_SECONDS)
                continue

            entry_ok, entry_reason = can_open_trade()
            if not entry_ok:
                log_no_trade(log, entry_reason, details={"session": session})
                mark_iteration_end()
                time.sleep(settings.LOOP_SLEEP_SECONDS)
                continue

            risk_ok, risk_reason = can_take_trade()
            if not risk_ok:
                log_no_trade(log, risk_reason, details={"session": session})
                mark_iteration_end()
                time.sleep(settings.LOOP_SLEEP_SECONDS)
                continue

            from execution.risk_manager import check_equity_drawdown
            check_equity_drawdown()

            df_h4, df_m15, df_m5 = _fetch_all_data()
            if any(df is None for df in (df_h4, df_m15, df_m5)):
                log.error("Data fetch failed - skipping this iteration")
                mark_iteration_end()
                time.sleep(settings.LOOP_SLEEP_SECONDS)
                continue

            bias = compute_h4_bias(df_h4)
            if bias.direction is None:
                log_no_trade(log, "No H4 bias", details={"session": session})
                mark_iteration_end()
                time.sleep(settings.LOOP_SLEEP_SECONDS)
                continue

            confluence = score_confluence(df_m15, df_m5, bias, session, df_h4)
            if not confluence.trade:
                mark_iteration_end()
                time.sleep(settings.LOOP_SLEEP_SECONDS)
                continue

            entry = attempt_entry(confluence, df_m5, settings.SYMBOL)
            if not entry.executed and not entry.blocked:
                log_no_trade(
                    log,
                    f"Entry conditions not met: {entry.reason}",
                    score=confluence.score,
                    details={"session": session, "direction": confluence.direction},
                )

            flush_all_handlers(log)

        except KeyboardInterrupt:
            log.info("KeyboardInterrupt - stopping bot.")
            _running = False

        except Exception as exc:
            record_loop_exception()
            log.error(
                f"Unhandled exception in main loop: {exc}\n"
                + traceback.format_exc()
            )
            evaluate_and_recover(log, settings.SYMBOL)

        finally:
            mark_iteration_end()
            time.sleep(settings.LOOP_SLEEP_SECONDS)


def main() -> None:
    signal.signal(signal.SIGINT, _shutdown)
    signal.signal(signal.SIGTERM, _shutdown)

    log.info("=" * 60)
    log.info("   SMC Trading Bot - Initialising")
    log.info(f"   Symbol : {settings.SYMBOL}")
    log.info(f"   Server : {settings.MT5_SERVER}")

    log.info("=" * 60)
    log.info("   CODE VERSION VALIDATION")
    log.info(f"   STRONG_DISPLACEMENT_THRESHOLD: {settings.STRONG_DISPLACEMENT_THRESHOLD}")
    log.info(f"   MEDIUM_DISPLACEMENT_THRESHOLD: {settings.MEDIUM_DISPLACEMENT_THRESHOLD}")

    from execution.entry_engine import _tiered_confirmation
    import inspect
    source_lines = inspect.getsource(_tiered_confirmation)
    has_tiered = "TIER 1" in source_lines

    if not has_tiered:
        log.error(
            "CRITICAL: Old code still loaded! Delete __pycache__/ and .pyc files,"
            " or run: python -Bc main.py"
        )
        return

    log.info("   New tiered confirmation code loaded successfully")
    log.info(f"   Risk   : {settings.RISK_PERCENT}% per trade")
    log.info("=" * 60)

    log.info("Connecting to MT5...")
    _mt5_ok = conn.connect()
    if not _mt5_ok:
        log.critical("Failed to connect to MT5. Exiting.")
        sys.exit(1)

    log.info("=" * 60)
    log.info("   MT5 BLOCKING RECONCILIATION (startup gate)")
    reconciliation_ok = run_blocking_mt5_reconciliation(settings.SYMBOL)
    from execution.trade_manager import log_reconciliation_summary
    log_reconciliation_summary()
    log.info("=" * 60)

    if not reconciliation_ok:
        log.critical(
            "Trading remains DISABLED until MT5 reconciliation succeeds. "
            "Fix broker/state issues — watchdog will retry recovery in loop."
        )
        set_trading_ready(False)
    else:
        set_trading_ready(True)
        mark_startup_complete()
        log.info("STARTUP COMPLETE | Runtime stabilization lock now ACTIVE")

    log.info("=" * 60)
    log.info("   COOLDOWN STATE RESTORATION")
    from execution.entry_engine import initialize_cooldown_from_persistence
    initialize_cooldown_from_persistence()
    log.info("=" * 60)

    log.info("=" * 70)
    log.info("   DAILY ACCOUNTING TELEMETRY")
    log.info("=" * 70)
    risk_state = get_state()
    open_positions = conn.get_open_positions(settings.SYMBOL, settings.MAGIC) or []

    from execution.risk_manager import (
        compute_floating_pnl, compute_equity, get_net_equity_pnl,
        compute_equity_drawdown, _get_balance,
    )

    balance = _get_balance()
    floating_pnl = compute_floating_pnl()
    equity = compute_equity()
    net_equity_pnl = get_net_equity_pnl()
    equity_dd = compute_equity_drawdown()
    balance_dd = (
        (risk_state.peak_balance - balance) / risk_state.peak_balance * 100
        if risk_state.peak_balance > 0 else 0.0
    )

    log.info(
        f"LIFECYCLE | Trades Initiated Today: {risk_state.trades_today} | "
        f"Closed Trades Today: {risk_state.closed_trades_today} | "
        f"Open Positions: {len(open_positions)}"
    )
    log.info(
        f"ACCOUNTING | Realized Daily PnL: {risk_state.daily_pnl:+.2f} | "
        f"Floating PnL: {floating_pnl:+.2f} | Net Equity PnL: {net_equity_pnl:+.2f}"
    )
    log.info(
        f"EQUITY | Balance: {balance:.2f} | Equity: {equity:.2f} | "
        f"Peak Balance: {risk_state.peak_balance:.2f} | Peak Equity: {risk_state.peak_equity:.2f}"
    )
    log.info(f"DRAWDOWN | Balance DD: {balance_dd:.2f}% | Equity DD: {equity_dd:.2f}%")
    log.info(
        f"CONTROL | Consecutive Losses: {risk_state.consecutive_losses} | "
        f"Bot Halted: {risk_state.bot_halted}"
    )
    log.info("=" * 70)

    try:
        _main_loop()
    finally:
        log.info("Shutting down - closing all positions...")
        if is_trading_ready():
            force_close_all(settings.SYMBOL, "Bot shutdown")
        conn.disconnect()
        log.info("Bot stopped cleanly.")


if __name__ == "__main__":
    main()

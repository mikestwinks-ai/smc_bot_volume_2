"""
logger.py — Centralised logging for the SMC bot.
Shared file handler (one per process) + per-logger console handlers (stdout).
"""

import logging
import os
import sys
from datetime import date
from logging.handlers import TimedRotatingFileHandler

LOG_DIR = os.path.join(os.path.dirname(__file__), "..", "logs")
os.makedirs(LOG_DIR, exist_ok=True)

_CURRENT_DAY = date.today()
_CONFIGURED_LOGGERS: set[str] = set()
_HANDLER_RECOVERY_ATTEMPTS: dict[str, int] = {}
_SHARED_FILE_HANDLER: TimedRotatingFileHandler | None = None


def _sanitize_for_console(message: str) -> str:
    replacements = {
        '—': '-', '–': '-', '→': '->', '▶': '>', '✔': '*', '✓': '*',
        '⚠': '!', '█': '#', '├': '|', '└': '|', '─': '-', '│': '|',
        '»': '>>', '«': '<<',
    }
    for char, replacement in replacements.items():
        message = message.replace(char, replacement)
    return message


class ColouredFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        return _sanitize_for_console(super().format(record))


def _log_file_path(for_day: date | None = None) -> str:
    day = for_day or date.today()
    return os.path.join(LOG_DIR, f"smc_bot_{day.isoformat()}.log")


def _create_file_handler() -> TimedRotatingFileHandler:
    """Single rotating file handler for the whole process."""
    fh = TimedRotatingFileHandler(
        _log_file_path(),
        when="midnight",
        interval=1,
        backupCount=30,
        encoding="utf-8",
        utc=False,
    )
    fh.setLevel(logging.DEBUG)
    fh.setFormatter(logging.Formatter(
        fmt="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    ))
    fh.suffix = "%Y-%m-%d"
    return fh


def _get_shared_file_handler() -> TimedRotatingFileHandler:
    global _SHARED_FILE_HANDLER
    if _SHARED_FILE_HANDLER is None:
        _SHARED_FILE_HANDLER = _create_file_handler()
    return _SHARED_FILE_HANDLER


def _has_handler_type(logger: logging.Logger, handler_type: type) -> bool:
    return any(isinstance(h, handler_type) for h in logger.handlers)


def _get_console_stream_handler(logger: logging.Logger) -> logging.StreamHandler | None:
    for h in logger.handlers:
        if isinstance(h, logging.StreamHandler) and not isinstance(
            h, logging.FileHandler
        ):
            return h
    return None


def _create_console_handler() -> logging.StreamHandler:
    """Console handler on stdout (matches print() / CMD window)."""
    ch = logging.StreamHandler(sys.stdout)
    ch.setLevel(logging.INFO)
    ch.setFormatter(ColouredFormatter(
        fmt="%(asctime)s | %(levelname)s | %(message)s",
        datefmt="%H:%M:%S",
    ))
    return ch


def _ensure_console_handler(logger: logging.Logger) -> logging.StreamHandler:
    existing = _get_console_stream_handler(logger)
    if existing is not None:
        if existing.stream is not sys.stdout:
            existing.setStream(sys.stdout)
        return existing
    ch = _create_console_handler()
    logger.addHandler(ch)
    return ch


def _ensure_file_handler(logger: logging.Logger) -> TimedRotatingFileHandler:
    shared_fh = _get_shared_file_handler()
    if not any(h is shared_fh for h in logger.handlers):
        logger.addHandler(shared_fh)
    return shared_fh


def describe_handlers(logger: logging.Logger | None = None) -> dict:
    """Return handler audit snapshot for root and/or a named logger."""
    def _handler_info(h: logging.Handler) -> dict:
        stream = getattr(h, "stream", None)
        return {
            "type": type(h).__name__,
            "level": logging.getLevelName(h.level),
            "stream": (
                "stdout"
                if stream is sys.stdout
                else "stderr"
                if stream is sys.stderr
                else repr(stream)
            ),
        }

    root = logging.getLogger()
    target = logger or logging.getLogger("smc_bot.main")
    return {
        "root": {
            "level": logging.getLevelName(root.level),
            "handlers": [_handler_info(h) for h in root.handlers],
            "count": len(root.handlers),
        },
        "logger_name": target.name,
        "logger": {
            "level": logging.getLevelName(target.level),
            "propagate": target.propagate,
            "handlers": [_handler_info(h) for h in target.handlers],
            "count": len(target.handlers),
            "has_file": _has_handler_type(
                target, TimedRotatingFileHandler
            ),
            "has_console": _get_console_stream_handler(target) is not None,
        },
    }


def _test_handler_write(handler: logging.Handler, logger_name: str) -> bool:
    try:
        test_record = logging.LogRecord(
            name=logger_name,
            level=logging.DEBUG,
            pathname="",
            lineno=0,
            msg="[LOGGER WRITE TEST - VERIFICATION]",
            args=(),
            exc_info=None,
        )
        handler.emit(test_record)
        return True
    except Exception:
        return False


def check_logger_health(logger: logging.Logger) -> bool:
    """Return True if file + console handlers are present and writable."""
    try:
        fh = _get_shared_file_handler()
        if not any(h is fh for h in logger.handlers):
            return False
        if isinstance(fh, TimedRotatingFileHandler):
            if not fh.stream:
                return False
            if hasattr(fh.stream, "writable") and not fh.stream.writable():
                return False

        ch = _get_console_stream_handler(logger)
        if ch is None:
            return False
        if ch.stream is not sys.stdout:
            return False
        if not _test_handler_write(ch, logger.name):
            return False
        return _test_handler_write(fh, logger.name)
    except Exception:
        return False


def _rebuild_shared_file_handler() -> bool:
    global _SHARED_FILE_HANDLER
    log_recovery = logging.getLogger("_recovery")
    log_recovery.warning("LOGGER RECOVERY INITIATED")

    try:
        if _SHARED_FILE_HANDLER is not None:
            try:
                _SHARED_FILE_HANDLER.close()
            except Exception:
                pass

        _SHARED_FILE_HANDLER = _create_file_handler()

        for name in list(_CONFIGURED_LOGGERS):
            logger = logging.getLogger(name)
            for h in logger.handlers[:]:
                if isinstance(h, TimedRotatingFileHandler):
                    logger.removeHandler(h)
            _ensure_file_handler(logger)
            _ensure_console_handler(logger)

        if _test_handler_write(_SHARED_FILE_HANDLER, "shared"):
            log_recovery.warning("LOGGER RECOVERY | Shared file handler rebuilt")
            return True
        log_recovery.error("LOGGER RECOVERY | Write test failed after rebuild")
        return False
    except Exception as e:
        log_recovery.error(f"LOGGER RECOVERY FAILED | {e}")
        return False


def run_logger_health_maintenance(logger: logging.Logger, logger_name: str = "smc_bot.main") -> None:
    """Rotate on day change, recover broken handlers, log periodic health."""
    global _CURRENT_DAY

    today = date.today()
    _ensure_file_handler(logger)
    _ensure_console_handler(logger)

    if not check_logger_health(logger):
        attempts = _HANDLER_RECOVERY_ATTEMPTS.get(logger_name, 0)
        if attempts < 3:
            _rebuild_shared_file_handler()
            _ensure_console_handler(logger)
            _HANDLER_RECOVERY_ATTEMPTS[logger_name] = attempts + 1
    else:
        _HANDLER_RECOVERY_ATTEMPTS[logger_name] = 0

    if today != _CURRENT_DAY:
        _CURRENT_DAY = today
        logging.getLogger("_recovery").info(
            f"LOGGER ROTATION | Day change — rolling shared handler"
        )
        try:
            fh = _get_shared_file_handler()
            fh.doRollover()
            if not _test_handler_write(fh, logger_name):
                _rebuild_shared_file_handler()
        except Exception:
            _rebuild_shared_file_handler()

    file_n = sum(
        1 for h in logger.handlers if isinstance(h, TimedRotatingFileHandler)
    )
    console_n = 1 if _get_console_stream_handler(logger) else 0
    logging.getLogger(logger_name).info(
        f"LOGGER HEALTH OK | handlers={len(logger.handlers)} | "
        f"file={file_n} | console={console_n} | console_stream=stdout"
    )


def _verify_and_rotate_handlers(logger: logging.Logger, logger_name: str = "smc_bot") -> None:
    """Backward-compatible alias used by main loop."""
    run_logger_health_maintenance(logger, logger_name)


def get_logger(name: str = "smc_bot") -> logging.Logger:
    """
    Return a logger with shared file handler (one per process) + stdout console handler.
    """
    logger = logging.getLogger(name)

    if name in _CONFIGURED_LOGGERS:
        _ensure_file_handler(logger)
        _ensure_console_handler(logger)
        return logger

    logger.setLevel(logging.DEBUG)
    logger.propagate = False

    _ensure_file_handler(logger)
    _ensure_console_handler(logger)

    _CONFIGURED_LOGGERS.add(name)
    return logger


def log_no_trade(logger: logging.Logger, reason: str, score: float = None,
                 details: dict = None) -> None:
    parts = [f"NO TRADE | Reason: {reason}"]
    if score is not None:
        parts.append(f"Score: {score}")
    if details:
        for k, v in details.items():
            parts.append(f"{k}: {v}")
    logger.info(" | ".join(parts))


def log_trade_signal(logger: logging.Logger, direction: str, score: float,
                     breakdown: dict, poi: str, session: str,
                     sweep: str, displacement: float) -> None:
    logger.info(
        f"SIGNAL | {direction.upper()} | Session: {session} | Score: {score} | "
        f"POI: {poi} | Sweep: {sweep} | Displacement: {displacement:.2f}x avg | "
        f"Breakdown: {breakdown}"
    )


def log_trade_open(logger: logging.Logger, ticket: int, direction: str,
                   symbol: str, lots: float, entry: float,
                   sl: float, tp: float, score: float) -> None:
    logger.info(
        f"TRADE OPENED | Ticket: {ticket} | {direction.upper()} {symbol} "
        f"| Lots: {lots} | Entry: {entry} | SL: {sl} | TP: {tp} | Score: {score}"
    )


def log_trade_close(logger: logging.Logger, ticket: int, reason: str,
                    pnl: float) -> None:
    logger.info(
        f"TRADE CLOSED | Ticket: {ticket} | Reason: {reason} | PnL: {pnl:.2f}"
    )


def log_sl_move(logger: logging.Logger, ticket: int, old_sl: float,
                new_sl: float, reason: str) -> None:
    logger.info(
        f"SL MOVED | Ticket: {ticket} | {old_sl} -> {new_sl} | Reason: {reason}"
    )


def log_drawdown_event(logger: logging.Logger, level: str,
                       drawdown_pct: float) -> None:
    logger.warning(
        f"DRAWDOWN EVENT [{level}] | Current drawdown: {drawdown_pct:.2f}%"
    )


def flush_all_handlers(logger: logging.Logger) -> bool:
    all_ok = True
    try:
        for handler in logger.handlers:
            try:
                handler.flush()
            except Exception:
                all_ok = False
        shared = _SHARED_FILE_HANDLER
        if shared and shared not in logger.handlers:
            try:
                shared.flush()
            except Exception:
                all_ok = False
    except Exception:
        all_ok = False
    return all_ok


def log_heartbeat(logger: logging.Logger, bot_status: dict) -> None:
    positions = bot_status.get("positions", 0)
    trades_today = bot_status.get("trades_today", 0)
    logger_health = bot_status.get("logger_health", "unknown")
    logger.info(
        f"HEARTBEAT | Status: alive | Positions: {positions} | "
        f"Trades today: {trades_today} | Logger: {logger_health}"
    )

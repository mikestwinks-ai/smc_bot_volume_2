"""
Read-only startup trace — does not start main() or MT5 connect.
Run: python tools/startup_trace_diagnostic.py
"""
import sys
import time
import os

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, ROOT)

STEPS = [
    ("launcher_python_reached", lambda: None),
    ("import_config_settings", lambda: __import__("config.settings")),
    ("import_utils_logger", lambda: __import__("utils.logger")),
    ("import_utils_mt5_connector", lambda: __import__("utils.mt5_connector")),
    ("import_execution_startup_gate", lambda: __import__("execution.startup_gate")),
    ("import_execution_watchdog", lambda: __import__("execution.watchdog")),
    ("import_execution_mt5_resilience", lambda: __import__("execution.mt5_resilience")),
    ("import_execution_day_transition", lambda: __import__("execution.day_transition")),
    ("import_execution_risk_manager", lambda: __import__("execution.risk_manager")),
    ("import_execution_trade_manager", lambda: __import__("execution.trade_manager")),
    ("import_main_module", lambda: __import__("main")),
]


def main():
    print("[STARTUP TRACE] diagnostic script started", flush=True)
    for name, fn in STEPS:
        t0 = time.perf_counter()
        print(f"[STARTUP TRACE] {name} reached", flush=True)
        try:
            fn()
            dt = time.perf_counter() - t0
            print(f"[STARTUP TRACE] {name} OK ({dt:.2f}s)", flush=True)
        except Exception as e:
            print(f"[STARTUP TRACE] {name} FAILED: {e}", flush=True)
            raise
    print("[STARTUP TRACE] all import steps complete", flush=True)


if __name__ == "__main__":
    main()

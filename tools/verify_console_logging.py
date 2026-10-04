"""Verify smc_bot.main logs to stdout and log file after startup steps."""
import io
import json
import sys
from contextlib import redirect_stdout

# project root on path when run as script
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from utils.logger import get_logger, describe_handlers, run_logger_health_maintenance
from config import settings
from utils import mt5_connector as conn
from execution.startup_gate import run_blocking_mt5_reconciliation

buf = io.StringIO()
with redirect_stdout(buf):
    log = get_logger("smc_bot.main")
    audit_before = describe_handlers(log)
    log.info("VERIFY_CONSOLE | before MT5 connect")
    conn.connect()
    log.info("VERIFY_CONSOLE | after MT5 connect")
    run_blocking_mt5_reconciliation(settings.SYMBOL)
    log.info("VERIFY_CONSOLE | after startup gate")
    run_logger_health_maintenance(log, "smc_bot.main")
    log.info("VERIFY_CONSOLE | after logger health maintenance")

stdout_text = buf.getvalue()
audit_after = describe_handlers(log)

print("=== HANDLER AUDIT (JSON) ===")
print(json.dumps(audit_after, indent=2))
print("=== STDOUT CAPTURE (redirect_stdout) ===")
print(stdout_text)
markers = [
    "VERIFY_CONSOLE | before MT5 connect",
    "VERIFY_CONSOLE | after MT5 connect",
    "VERIFY_CONSOLE | after startup gate",
    "VERIFY_CONSOLE | after logger health maintenance",
]
missing = [m for m in markers if m not in stdout_text]
if missing:
    print("FAIL missing on stdout:", missing)
    sys.exit(1)
print("PASS all markers on stdout")

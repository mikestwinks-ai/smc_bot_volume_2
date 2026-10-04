"""Diagnostic: time each main() step after MT5 connect (no trading logic changes)."""
import sys
import time

def ts(msg: str) -> None:
    print(f"[PROFILE {time.perf_counter():.3f}] {msg}", flush=True)

t0 = time.perf_counter()
ts("import main begin")
from config import settings
from utils import mt5_connector as conn
from execution.startup_gate import run_blocking_mt5_reconciliation, set_trading_ready
from execution.risk_manager import get_state
from execution.lifecycle_coordinator import mark_startup_complete

ts("connect MT5")
t = time.perf_counter()
ok = conn.connect()
ts(f"connect done ok={ok} dt={time.perf_counter()-t:.3f}s")
if not ok:
    sys.exit(1)

ts("BEFORE startup gate / run_blocking_mt5_reconciliation")
t = time.perf_counter()
reconciliation_ok = run_blocking_mt5_reconciliation(settings.SYMBOL)
ts(f"AFTER startup gate ok={reconciliation_ok} dt={time.perf_counter()-t:.3f}s")

ts("BEFORE log_reconciliation_summary")
t = time.perf_counter()
from execution.trade_manager import log_reconciliation_summary
log_reconciliation_summary()
ts(f"AFTER log_reconciliation_summary dt={time.perf_counter()-t:.3f}s")

ts("BEFORE trading_ready / mark_startup_complete")
t = time.perf_counter()
if reconciliation_ok:
    set_trading_ready(True)
    mark_startup_complete()
    ts("trading_ready=True STARTUP COMPLETE equivalent")
else:
    set_trading_ready(False)
    ts("trading_ready=False")
ts(f"AFTER trading_ready dt={time.perf_counter()-t:.3f}s")

ts("BEFORE cooldown restoration")
t = time.perf_counter()
from execution.entry_engine import initialize_cooldown_from_persistence
initialize_cooldown_from_persistence()
ts(f"AFTER cooldown restoration dt={time.perf_counter()-t:.3f}s")

ts("BEFORE telemetry block")
t = time.perf_counter()
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
ts(
    f"AFTER telemetry dt={time.perf_counter()-t:.3f}s | "
    f"trades_today={risk_state.trades_today} closed={risk_state.closed_trades_today} "
    f"pnl={risk_state.daily_pnl} open={len(open_positions)} bal={balance:.2f}"
)

ts(f"TOTAL post-connect dt={time.perf_counter()-t0:.3f}s")
ts("PROFILER COMPLETE — would enter _main_loop next in main.py")

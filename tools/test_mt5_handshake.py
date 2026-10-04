"""Isolated MT5 handshake test with timeout (diagnostic only)."""
import sys
import time
import os

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, ROOT)

print("[TRACE] test_mt5_handshake started", flush=True)

from config import settings

print(f"[TRACE] settings loaded | server={settings.MT5_SERVER} login={settings.MT5_LOGIN}", flush=True)

try:
    import MetaTrader5 as mt5
except ImportError as e:
    print(f"[TRACE] MetaTrader5 import failed: {e}", flush=True)
    sys.exit(2)

print("[TRACE] MetaTrader5 imported", flush=True)
t0 = time.perf_counter()
print("[TRACE] mt5.initialize() calling...", flush=True)
ok = mt5.initialize()
dt = time.perf_counter() - t0
print(f"[TRACE] mt5.initialize() returned {ok} in {dt:.2f}s | error={mt5.last_error()}", flush=True)

if not ok:
    sys.exit(1)

t1 = time.perf_counter()
print("[TRACE] mt5.login() calling...", flush=True)
logged = mt5.login(
    login=settings.MT5_LOGIN,
    password=settings.MT5_PASSWORD,
    server=settings.MT5_SERVER,
)
dt2 = time.perf_counter() - t1
print(f"[TRACE] mt5.login() returned {logged} in {dt2:.2f}s | error={mt5.last_error()}", flush=True)

ti = mt5.terminal_info()
ai = mt5.account_info()
print(f"[TRACE] terminal_info={ti}", flush=True)
print(f"[TRACE] account_info login={getattr(ai, 'login', None)} balance={getattr(ai, 'balance', None)}", flush=True)
mt5.shutdown()
print("[TRACE] test_mt5_handshake complete", flush=True)

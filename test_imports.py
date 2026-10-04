#!/usr/bin/env python
"""Quick import test to verify all modifications work."""

import sys
import traceback

print("=" * 60)
print("TESTING MODULE IMPORTS")
print("=" * 60)

tests = [
    ("config.settings", lambda: __import__('config.settings', fromlist=['settings'])),
    ("config.sessions with get_asian_session_context", lambda: __import__('config.sessions', fromlist=['get_asian_session_context'])),
    ("utils.logger with _verify_and_rotate_handlers", lambda: __import__('utils.logger', fromlist=['_verify_and_rotate_handlers'])),
    ("execution.state_persistence", lambda: __import__('execution.state_persistence', fromlist=['save_trade_states'])),
    ("execution.trade_manager with reconcile", lambda: __import__('execution.trade_manager', fromlist=['reconcile_positions_on_startup'])),
    ("strategy.confluence_engine with market context", lambda: __import__('strategy.confluence_engine', fromlist=['calculate_market_context'])),
]

passed = 0
failed = 0

for name, import_fn in tests:
    try:
        import_fn()
        print(f"✓ {name}")
        passed += 1
    except Exception as e:
        print(f"✗ {name}")
        print(f"  Error: {e}")
        traceback.print_exc()
        failed += 1

print("=" * 60)
print(f"Results: {passed} passed, {failed} failed")
print("=" * 60)

sys.exit(0 if failed == 0 else 1)

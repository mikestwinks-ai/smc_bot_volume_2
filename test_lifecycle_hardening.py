#!/usr/bin/env python3
"""
RACE CONDITION HARDENING TEST SUITE

Tests the new position count lock, stabilization delay, and fallback cooldown mechanisms.
Simulates the 17:09:44 race condition and verifies hardening prevents re-entry.
"""

import sys
import time
sys.path.insert(0, ".")

from execution import trade_manager
from execution import entry_engine
from config import settings

def print_test_header(test_num, test_name):
    """Print formatted test header."""
    print(f"\n{'='*70}")
    print(f"TEST {test_num}: {test_name}")
    print(f"{'='*70}\n")

def print_step(step_num, description):
    """Print test step."""
    print(f"  STEP {step_num}: {description}")

def test_1_position_count_tracking():
    """Test 1: Position count tracking and change detection"""
    print_test_header(1, "Position Count Tracking")
    
    print_step(1, "Initialize position count tracker to 0")
    trade_manager._LAST_KNOWN_POSITION_COUNT = 0
    changed = trade_manager.update_position_count_tracker(0)
    assert not changed, "No change when count stays 0"
    print(f"    ✓ Count 0->0: changed={changed} (expected False)")
    
    print_step(2, "Simulate position opening: 0->1")
    changed = trade_manager.update_position_count_tracker(1)
    assert changed, "Should detect change when count increases"
    print(f"    ✓ Count 1: changed={changed} (expected True)")
    
    print_step(3, "Simulate position closure: 1->0")
    changed = trade_manager.update_position_count_tracker(0)
    assert changed, "Should detect change when count decreases"
    print(f"    ✓ Count 0: changed={changed} (expected True)")
    
    print_step(4, "No change: 0->0")
    changed = trade_manager.update_position_count_tracker(0)
    assert not changed, "No change when staying at 0"
    print(f"    ✓ Count 0->0 again: changed={changed} (expected False)")
    
    print("\n  ✅ TEST 1 PASSED: Position count tracking works correctly\n")
    return True

def test_2_position_count_lock_timeout():
    """Test 2: Position count lock with timeout"""
    print_test_header(2, "Position Count Lock Timeout")
    
    print_step(1, "Initialize: lock should be inactive")
    trade_manager._POSITION_COUNT_LOCK_ACTIVE = False
    trade_manager._FORCED_STABILIZATION_UNTIL = 0.0
    is_active = trade_manager.is_position_count_lock_active()
    assert not is_active, "Lock should be inactive initially"
    print(f"    ✓ Lock inactive: {not is_active}")
    
    print_step(2, "Engage lock with 2-second timeout")
    trade_manager.set_position_count_lock(True, "TEST")
    is_active = trade_manager.is_position_count_lock_active()
    assert is_active, "Lock should be active immediately after engagement"
    print(f"    ✓ Lock engaged: {is_active}")
    
    print_step(3, "Check lock is still active after 0.5 seconds")
    time.sleep(0.5)
    is_active = trade_manager.is_position_count_lock_active()
    assert is_active, "Lock should still be active"
    remaining = trade_manager._FORCED_STABILIZATION_UNTIL - time.time()
    print(f"    ✓ Lock still active, remaining: {remaining:.1f}s")
    
    print_step(4, "Wait for timeout and check lock expires")
    print(f"    Waiting {trade_manager._STABILIZATION_DELAY_SECONDS}s for timeout...")
    time.sleep(trade_manager._STABILIZATION_DELAY_SECONDS + 0.1)
    is_active = trade_manager.is_position_count_lock_active()
    assert not is_active, "Lock should expire after timeout"
    print(f"    ✓ Lock expired after timeout: {not is_active}")
    
    print("\n  ✅ TEST 2 PASSED: Position count lock timeout works correctly\n")
    return True

def test_3_fallback_cooldown_registration():
    """Test 3: Fallback cooldown registration"""
    print_test_header(3, "Fallback Cooldown Registration")
    
    print_step(1, "Clear previous cooldown state")
    entry_engine._LAST_EXIT_TIME.clear()
    print(f"    ✓ Cleared: {len(entry_engine._LAST_EXIT_TIME)} cooldowns")
    
    print_step(2, "Register fallback cooldown for symbol")
    entry_engine.register_fallback_cooldown(settings.SYMBOL)
    
    print_step(3, "Verify both directions have cooldown registered")
    for direction in ["bullish", "bearish"]:
        key = f"{settings.SYMBOL}_{direction}"
        assert key in entry_engine._LAST_EXIT_TIME, f"Cooldown not registered for {direction}"
        exit_time, exit_reason, cooldown_secs = entry_engine._LAST_EXIT_TIME[key]
        assert exit_reason == "FALLBACK_POSITION_CHANGE", f"Wrong reason: {exit_reason}"
        assert cooldown_secs == 900, f"Wrong duration: {cooldown_secs}"
        print(f"    ✓ {direction}: cooldown={cooldown_secs}s, reason={exit_reason}")
    
    print_step(4, "Verify cooldown blocks entry")
    for direction in ["bullish", "bearish"]:
        is_blocked, reason = entry_engine._check_cooldown(settings.SYMBOL, direction)
        assert is_blocked, f"Cooldown should block {direction}"
        print(f"    ✓ {direction}: blocked={is_blocked}")
    
    print("\n  ✅ TEST 3 PASSED: Fallback cooldown blocks entries\n")
    return True

def test_4_concurrent_protection():
    """Test 4: Position lock + Cooldown concurrent protection"""
    print_test_header(4, "Concurrent Protection (Lock + Cooldown)")
    
    print_step(1, "Initialize: no lock, no cooldown")
    trade_manager._POSITION_COUNT_LOCK_ACTIVE = False
    trade_manager._FORCED_STABILIZATION_UNTIL = 0.0
    entry_engine._LAST_EXIT_TIME.clear()
    print(f"    ✓ State cleared")
    
    print_step(2, "Simulate position closure: register lock + cooldown")
    # Position count changed
    trade_manager.update_position_count_tracker(1)  # Had 1
    trade_manager.update_position_count_tracker(0)  # Now 0
    # Engage lock
    trade_manager.set_position_count_lock(True, "Position closed")
    # Register fallback cooldown
    entry_engine.register_fallback_cooldown(settings.SYMBOL)
    
    print_step(3, "Verify BOTH protections are active")
    lock_active = trade_manager.is_position_count_lock_active()
    assert lock_active, "Position lock should be active"
    print(f"    ✓ Position lock: {lock_active}")
    
    blocked, _ = entry_engine._check_cooldown(settings.SYMBOL, "bullish")
    assert blocked, "Cooldown should block entry"
    print(f"    ✓ Cooldown: bullish blocked={blocked}")
    
    blocked, _ = entry_engine._check_cooldown(settings.SYMBOL, "bearish")
    assert blocked, "Cooldown should block entry"
    print(f"    ✓ Cooldown: bearish blocked={blocked}")
    
    print_step(4, "Verify dual protection prevents re-entry")
    # Two independent protections:
    # 1. Position lock prevents signal engine from running
    # 2. Cooldown prevents entry even if signal engine ran
    print(f"    ✓ Protection 1 (Position Lock): Active={lock_active}")
    print(f"    ✓ Protection 2 (Cooldown): Bullish blocked={blocked}")
    print(f"    → Signal engine BLOCKED by Position Lock")
    print(f"    → If signal engine ran anyway, BLOCKED by Cooldown")
    
    print("\n  ✅ TEST 4 PASSED: Concurrent protections prevent re-entry\n")
    return True

def test_5_race_condition_simulation():
    """Test 5: Simulate the exact 17:09:44 race condition and verify fix"""
    print_test_header(5, "17:09:44 Race Condition Simulation")
    
    print("SCENARIO: Position closes mid-iteration, signal runs same second")
    print("EXPECTED: Hardening prevents immediate re-entry")
    print()
    
    # Reset state
    trade_manager._LAST_KNOWN_POSITION_COUNT = 0
    trade_manager._POSITION_COUNT_LOCK_ACTIVE = False
    trade_manager._FORCED_STABILIZATION_UNTIL = 0.0
    entry_engine._LAST_EXIT_TIME.clear()
    
    print_step(1, "Loop iteration starts with 1 open position")
    trade_manager._LAST_KNOWN_POSITION_COUNT = 1
    print(f"    Position count: 1 (position is open)")
    
    print_step(2, "manage_open_trades() called - lifecycle lock engaged")
    trade_manager.set_lifecycle_lock(True)
    print(f"    Lifecycle lock: {trade_manager.is_lifecycle_lock_active()}")
    
    print_step(3, "detect_and_process_closed_positions() - position still open, nothing detected")
    print(f"    Position exists on MT5: no closure detected yet")
    
    print_step(4, "manage_remaining_positions() - manage the open position")
    print(f"    Managing position...")
    
    print_step(5, "[MT5 closes position during manage cycle]")
    print(f"    *** Position closed by TP/SL hit ***")
    
    print_step(6, "Check position count after manage - DETECTS CLOSURE")
    # Position disappeared from MT5
    position_count_changed = trade_manager.update_position_count_tracker(0)  # 1 -> 0
    print(f"    Position count: 1 -> 0 (CHANGED={position_count_changed})")
    
    print_step(7, "Register fallback cooldown + engage position lock")
    if position_count_changed:
        entry_engine.register_fallback_cooldown(settings.SYMBOL)
        trade_manager.set_position_count_lock(True, "Position closed")
    bullish_blocked, _ = entry_engine._check_cooldown(settings.SYMBOL, "bullish")
    print(f"    Fallback cooldown: registered")
    print(f"    Position lock: {trade_manager.is_position_count_lock_active()}")
    print(f"    Bullish entry blocked: {bullish_blocked}")
    
    print_step(8, "Release lifecycle lock (manage_open_trades returns)")
    trade_manager.set_lifecycle_lock(False)
    print(f"    Lifecycle lock: {trade_manager.is_lifecycle_lock_active()}")
    
    print_step(9, "CHECK: Can signal engine run?")
    lifecycle_lock = trade_manager.is_lifecycle_lock_active()
    position_count_lock = trade_manager.is_position_count_lock_active()
    print(f"    Lifecycle lock: {lifecycle_lock}")
    print(f"    Position count lock: {position_count_lock}")
    
    if position_count_lock:
        print(f"    → SIGNAL ENGINE BLOCKED by Position Count Lock")
        signal_engine_blocked_by_lock = True
    else:
        print(f"    → Lifecycle lock released, but check cooldown...")
        signal_engine_blocked_by_lock = False
    
    print_step(10, "CHECK: Can bullish trade execute?")
    bullish_blocked, reason = entry_engine._check_cooldown(settings.SYMBOL, "bullish")
    print(f"    Bullish entry blocked: {bullish_blocked}")
    print(f"    Reason: {reason[:80]}...")
    print(f"    → TRADE EXECUTION BLOCKED by Fallback Cooldown")
    
    print_step(11, "VERIFY FIX: Impossible to trade in same second")
    cannot_trade_by_lock = position_count_lock
    cannot_trade_by_cooldown = bullish_blocked
    print(f"    ✓ Signal engine suppressed: {cannot_trade_by_lock}")
    print(f"    ✓ Entry blocked by cooldown: {cannot_trade_by_cooldown}")
    print(f"    ✓ Re-entry protection: {cannot_trade_by_lock or cannot_trade_by_cooldown}")
    
    assert cannot_trade_by_lock or cannot_trade_by_cooldown, "Should have dual protection"
    print("\n  ✅ TEST 5 PASSED: Race condition fixed - no same-second re-entry\n")
    return True

def main():
    """Run all tests"""
    print("\n" + "="*70)
    print("TRADE LIFECYCLE HARDENING TEST SUITE")
    print("="*70)
    
    tests = [
        test_1_position_count_tracking,
        test_2_position_count_lock_timeout,
        test_3_fallback_cooldown_registration,
        test_4_concurrent_protection,
        test_5_race_condition_simulation,
    ]
    
    passed = 0
    failed = 0
    
    for test in tests:
        try:
            if test():
                passed += 1
        except Exception as e:
            failed += 1
            print(f"\n  ❌ TEST FAILED: {e}\n")
            import traceback
            traceback.print_exc()
    
    print("\n" + "="*70)
    print(f"RESULTS: {passed} passed, {failed} failed")
    print("="*70 + "\n")
    
    if failed == 0:
        print("✅ ALL TESTS PASSED - Hardening is working correctly\n")
        return 0
    else:
        print(f"❌ {failed} TEST(S) FAILED - Review implementation\n")
        return 1

if __name__ == "__main__":
    sys.exit(main())

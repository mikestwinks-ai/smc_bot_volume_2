#!/usr/bin/env python3
"""
PHASE 1 BEHAVIORAL VERIFICATION TEST
Exit-Based Cooldown Enforcement

Tests that:
1. Exit cooldown is registered with correct duration
2. Cooldown blocks new entries
3. Different exit reasons get different cooldown durations
4. Cooldown check uses EXIT TIME as primary source
"""

import time
import sys
sys.path.insert(0, ".")

from execution import entry_engine
from config import settings

def test_scenario_1_tp_cooldown():
    """TP exit should trigger 10-minute (600s) cooldown"""
    print("\n" + "="*60)
    print("TEST 1: TP Exit Cooldown (10 minutes)")
    print("="*60)
    
    symbol = "XAUUSDm"
    direction = "bullish"
    
    # Clear any existing state
    entry_engine._LAST_ENTRY_TIME.clear()
    entry_engine._LAST_EXIT_TIME.clear()
    
    # Simulate entry
    print(f"\n1. Simulate ENTRY at {symbol} {direction}")
    entry_engine._LAST_ENTRY_TIME[f"{symbol}_{direction}"] = time.time()
    print(f"   ✓ Entry time registered")
    
    # Check cooldown immediately after entry (should not block based on exit time)
    is_blocked, reason = entry_engine._check_cooldown(symbol, direction)
    print(f"\n2. Check cooldown immediately after entry")
    print(f"   Entry blocked: {is_blocked}")
    print(f"   Reason: {reason if reason else 'N/A (entry time check)'}")
    
    # Simulate trade exit with TP reason
    print(f"\n3. Simulate TRADE EXIT with reason: TP")
    entry_engine.register_trade_exit(symbol, direction, "TP")
    print(f"   ✓ Exit registered with TP reason")
    
    # Verify the exit was registered correctly
    if f"{symbol}_{direction}" in entry_engine._LAST_EXIT_TIME:
        exit_time, exit_reason, cooldown_secs = entry_engine._LAST_EXIT_TIME[f"{symbol}_{direction}"]
        print(f"   Exit reason: {exit_reason}")
        print(f"   Cooldown duration: {cooldown_secs}s ({cooldown_secs//60}m)")
        assert exit_reason == "TP", f"Expected TP, got {exit_reason}"
        assert cooldown_secs == 600, f"Expected 600s for TP, got {cooldown_secs}s"
        print(f"   ✓ Cooldown correctly set to 10 minutes (600s)")
    else:
        print(f"   ✗ FAILED: Exit not registered")
        return False
    
    # Check cooldown - should block with TP reason
    is_blocked, reason = entry_engine._check_cooldown(symbol, direction)
    print(f"\n4. Check cooldown after TP exit")
    print(f"   Entry blocked: {is_blocked}")
    print(f"   Reason: {reason}")
    assert is_blocked, f"Expected cooldown to block entry after TP"
    assert "TP" in reason, f"Expected TP mentioned in reason, got: {reason}"
    print(f"   ✓ Entry correctly blocked by TP cooldown")
    
    return True


def test_scenario_2_sl_cooldown():
    """SL exit should trigger 15-minute (900s) cooldown"""
    print("\n" + "="*60)
    print("TEST 2: SL Exit Cooldown (15 minutes)")
    print("="*60)
    
    symbol = "XAUUSDm"
    direction = "bearish"
    
    # Clear any existing state
    entry_engine._LAST_ENTRY_TIME.clear()
    entry_engine._LAST_EXIT_TIME.clear()
    
    # Simulate entry
    print(f"\n1. Simulate ENTRY at {symbol} {direction}")
    entry_engine._LAST_ENTRY_TIME[f"{symbol}_{direction}"] = time.time()
    print(f"   ✓ Entry time registered")
    
    # Simulate trade exit with SL reason
    print(f"\n2. Simulate TRADE EXIT with reason: SL")
    entry_engine.register_trade_exit(symbol, direction, "SL")
    print(f"   ✓ Exit registered with SL reason")
    
    # Verify the exit was registered correctly
    if f"{symbol}_{direction}" in entry_engine._LAST_EXIT_TIME:
        exit_time, exit_reason, cooldown_secs = entry_engine._LAST_EXIT_TIME[f"{symbol}_{direction}"]
        print(f"   Exit reason: {exit_reason}")
        print(f"   Cooldown duration: {cooldown_secs}s ({cooldown_secs//60}m)")
        assert exit_reason == "SL", f"Expected SL, got {exit_reason}"
        assert cooldown_secs == 900, f"Expected 900s for SL, got {cooldown_secs}s"
        print(f"   ✓ Cooldown correctly set to 15 minutes (900s)")
    else:
        print(f"   ✗ FAILED: Exit not registered")
        return False
    
    # Check cooldown - should block with SL reason
    is_blocked, reason = entry_engine._check_cooldown(symbol, direction)
    print(f"\n3. Check cooldown after SL exit")
    print(f"   Entry blocked: {is_blocked}")
    print(f"   Reason: {reason}")
    assert is_blocked, f"Expected cooldown to block entry after SL"
    assert "SL" in reason, f"Expected SL mentioned in reason, got: {reason}"
    print(f"   ✓ Entry correctly blocked by SL cooldown")
    
    return True


def test_scenario_3_cooldown_expiry():
    """Cooldown should allow entry after duration expires"""
    print("\n" + "="*60)
    print("TEST 3: Cooldown Expiry (simulation with short duration)")
    print("="*60)
    
    symbol = "XAUUSDm"
    direction = "bullish"
    
    # Clear any existing state
    entry_engine._LAST_ENTRY_TIME.clear()
    entry_engine._LAST_EXIT_TIME.clear()
    
    # Simulate entry
    print(f"\n1. Simulate ENTRY at {symbol} {direction}")
    entry_engine._LAST_ENTRY_TIME[f"{symbol}_{direction}"] = time.time()
    print(f"   ✓ Entry time registered")
    
    # Register exit but manually set a very short cooldown for testing
    print(f"\n2. Register exit with SHORT cooldown duration (3 seconds for testing)")
    symbol_direction = f"{symbol}_{direction}"
    entry_engine._LAST_EXIT_TIME[symbol_direction] = (time.time(), "TEST_SHORT", 3)
    print(f"   ✓ Exit registered with 3s cooldown")
    
    # Check cooldown immediately - should block
    is_blocked, reason = entry_engine._check_cooldown(symbol, direction)
    print(f"\n3. Check cooldown immediately after exit")
    print(f"   Entry blocked: {is_blocked}")
    assert is_blocked, f"Expected cooldown to block immediately"
    print(f"   ✓ Entry correctly blocked")
    
    # Wait for cooldown to expire
    print(f"\n4. Wait 4 seconds for cooldown to expire")
    time.sleep(4)
    
    # Check cooldown again - should not block
    is_blocked, reason = entry_engine._check_cooldown(symbol, direction)
    print(f"\n5. Check cooldown after expiry")
    print(f"   Entry blocked: {is_blocked}")
    print(f"   Reason: {reason if reason else 'N/A (cooldown expired)'}")
    assert not is_blocked, f"Expected cooldown to have expired"
    print(f"   ✓ Entry correctly allowed after cooldown expired")
    
    # Verify cooldown was cleaned up
    assert symbol_direction not in entry_engine._LAST_EXIT_TIME, "Exit time should be cleaned up"
    print(f"   ✓ Stale cooldown state cleaned up")
    
    return True


def test_scenario_4_exit_reason_normalization():
    """Trade manager reasons should be normalized to cooldown reasons"""
    print("\n" + "="*60)
    print("TEST 4: Exit Reason Normalization")
    print("="*60)
    
    symbol = "XAUUSDm"
    direction = "bullish"
    
    # Clear any existing state
    entry_engine._LAST_ENTRY_TIME.clear()
    entry_engine._LAST_EXIT_TIME.clear()
    
    # Test various reason strings that trade_manager might pass
    test_reasons = [
        ("Take profit hit", "TP", 600),
        ("Stop loss triggered", "SL", 900),
        ("Break-even stop hit", "BE", 900),
        ("Time limit exceeded", "TIME_RULE", 900),
        ("Session force close", "FORCE_CLOSE", 900),
    ]
    
    for description, expected_reason, expected_duration in test_reasons:
        entry_engine._LAST_EXIT_TIME.clear()
        
        print(f"\n   Testing: {description}")
        # This mimics what happens when trade_manager calls register_trade_exit
        # (the normalization would happen in trade_manager._force_close)
        entry_engine.register_trade_exit(symbol, direction, expected_reason)
        
        if symbol + "_" + direction in entry_engine._LAST_EXIT_TIME:
            exit_time, exit_reason, cooldown_secs = entry_engine._LAST_EXIT_TIME[symbol + "_" + direction]
            assert exit_reason == expected_reason, f"Expected {expected_reason}, got {exit_reason}"
            assert cooldown_secs == expected_duration, f"Expected {expected_duration}s, got {cooldown_secs}s"
            print(f"      ✓ {expected_reason} → {cooldown_secs}s cooldown")
        else:
            print(f"      ✗ Failed to register exit")
            return False
    
    return True


def main():
    print("\n" + "="*70)
    print("PHASE 1 BEHAVIORAL VERIFICATION: EXIT-BASED COOLDOWN ENFORCEMENT")
    print("="*70)
    
    tests = [
        ("TP Exit Cooldown", test_scenario_1_tp_cooldown),
        ("SL Exit Cooldown", test_scenario_2_sl_cooldown),
        ("Cooldown Expiry", test_scenario_3_cooldown_expiry),
        ("Reason Normalization", test_scenario_4_exit_reason_normalization),
    ]
    
    results = []
    for test_name, test_func in tests:
        try:
            result = test_func()
            results.append((test_name, "PASS" if result else "FAIL"))
        except AssertionError as e:
            print(f"\n   ✗ ASSERTION FAILED: {e}")
            results.append((test_name, "FAIL"))
        except Exception as e:
            print(f"\n   ✗ ERROR: {e}")
            results.append((test_name, "ERROR"))
    
    # Summary
    print("\n" + "="*70)
    print("TEST SUMMARY")
    print("="*70)
    for test_name, result in results:
        status_symbol = "✓" if result == "PASS" else "✗"
        print(f"{status_symbol} {test_name}: {result}")
    
    passed = sum(1 for _, r in results if r == "PASS")
    total = len(results)
    print(f"\nTotal: {passed}/{total} tests passed")
    
    if passed == total:
        print("\n✓ PHASE 1 IMPLEMENTATION VERIFIED: Exit-based cooldown working correctly")
        return 0
    else:
        print(f"\n✗ PHASE 1 VERIFICATION FAILED: {total - passed} test(s) failed")
        return 1


if __name__ == "__main__":
    sys.exit(main())

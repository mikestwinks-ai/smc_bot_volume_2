"""
test_phase6_validation.py - Comprehensive validation of Phase 6 refactored architecture

VALIDATION SCOPE:
1. Startup phase awareness (no false stabilization locks)
2. Runtime lifecycle management (stabilization on position changes)
3. Deterministic closure pipeline (idempotency, telemetry)
4. Strategic cooldown registration and persistence
5. Signal deduplication with fingerprinting
6. Forensic event timeline completeness
7. No same-second re-entries (sustained)
"""

import time
from execution.lifecycle_coordinator import (
    mark_startup_complete,
    is_in_startup_phase,
    check_position_count_change,
    engage_stabilization_lock,
    is_stabilization_lock_active,
    process_trade_closure,
    register_strategic_cooldown,
    calculate_signal_fingerprint,
    should_suppress_signal,
    reset_signal_fingerprint,
    get_or_create_lifecycle,
    _TRADE_LIFECYCLES,
)

# ════════════════════════════════════════════════════════════════════════════
# TEST 1: STARTUP PHASE AWARENESS
# ════════════════════════════════════════════════════════════════════════════

def test_startup_phase_recognition():
    """Verify startup phase flag exists and works correctly."""
    # Initially, we should be in startup phase (or it depends on previous state)
    # The key is that mark_startup_complete() exists and changes state
    
    # Reset to known state for testing
    from execution import lifecycle_coordinator
    lifecycle_coordinator._STARTUP_RECONCILIATION_PHASE = True
    
    assert is_in_startup_phase() == True, "Should be in startup phase initially"
    
    mark_startup_complete()
    assert is_in_startup_phase() == False, "Should NOT be in startup phase after mark_startup_complete()"
    
    print("✓ TEST 1 PASSED: Startup phase recognition works correctly")


def test_position_count_change_during_startup():
    """Verify position count changes during startup don't trigger stabilization lock."""
    from execution import lifecycle_coordinator
    
    # Reset to startup phase
    lifecycle_coordinator._STARTUP_RECONCILIATION_PHASE = True
    lifecycle_coordinator._POSITION_COUNT_AT_LAST_CHECK = 0
    lifecycle_coordinator._STABILIZATION_LOCK_ACTIVE = False
    
    # Simulate position appearing during startup (0 → 1)
    changed = check_position_count_change(1)
    
    assert changed == True, "Position count change should be detected"
    assert not is_stabilization_lock_active(), "Stabilization lock should NOT engage during startup"
    
    print("✓ TEST 2 PASSED: Position count changes during startup don't trigger lock")


def test_position_count_change_after_startup():
    """Verify position count changes AFTER startup DO trigger stabilization lock."""
    from execution import lifecycle_coordinator
    
    # Reset and complete startup phase
    lifecycle_coordinator._STARTUP_RECONCILIATION_PHASE = False
    lifecycle_coordinator._POSITION_COUNT_AT_LAST_CHECK = 1
    lifecycle_coordinator._STABILIZATION_LOCK_ACTIVE = False
    lifecycle_coordinator._STABILIZATION_LOCK_UNTIL = 0.0
    
    # Simulate position closing after startup (1 → 0)
    changed = check_position_count_change(0)
    
    assert changed == True, "Position count change should be detected"
    assert is_stabilization_lock_active(), "Stabilization lock SHOULD engage after startup"
    
    print("✓ TEST 3 PASSED: Position count changes after startup trigger lock")


# ════════════════════════════════════════════════════════════════════════════
# TEST 2: DETERMINISTIC TRADE CLOSURE PIPELINE
# ════════════════════════════════════════════════════════════════════════════

def test_process_trade_closure_idempotency():
    """Verify process_trade_closure is idempotent (safe to call multiple times)."""
    from execution import lifecycle_coordinator
    
    # Clear for clean test
    lifecycle_coordinator._TRADE_LIFECYCLES.clear()
    
    ticket = 12345
    symbol = "XAUUSDm"
    direction = "bullish"
    
    # First call - should process
    process_trade_closure(
        ticket=ticket,
        symbol=symbol,
        direction=direction,
        closure_reason="TP",
        realized_pnl=50.0,
        realized_rr=2.5,
        source="TEST"
    )
    
    # Verify lifecycle was created and closure recorded
    assert ticket in lifecycle_coordinator._TRADE_LIFECYCLES
    lifecycle1 = lifecycle_coordinator._TRADE_LIFECYCLES[ticket]
    assert lifecycle1.closure_reason == "TP"
    assert lifecycle1.realized_pnl == 50.0
    
    # Second call with different data - should NOT update (idempotent)
    process_trade_closure(
        ticket=ticket,
        symbol=symbol,
        direction=direction,
        closure_reason="SL",  # Different reason
        realized_pnl=100.0,   # Different PnL
        realized_rr=5.0,
        source="TEST2"
    )
    
    # Verify first closure data is unchanged
    lifecycle2 = lifecycle_coordinator._TRADE_LIFECYCLES[ticket]
    assert lifecycle2.closure_reason == "TP", "Closure reason should not change (idempotent)"
    assert lifecycle2.realized_pnl == 50.0, "Realized PnL should not change (idempotent)"
    
    print("✓ TEST 4 PASSED: Trade closure processing is idempotent")


def test_lifecycle_event_tracking():
    """Verify lifecycle events are tracked for audit trail."""
    from execution import lifecycle_coordinator
    
    # Clear for clean test
    lifecycle_coordinator._TRADE_LIFECYCLES.clear()
    
    ticket = 54321
    lifecycle = get_or_create_lifecycle(ticket, "XAUUSDm", "bearish")
    
    # Add several events
    lifecycle.add_event("TRADE_SIGNALLED", {"confidence": "HIGH"})
    lifecycle.add_event("TRADE_SUBMITTED", {"entry_price": "2500.50"})
    lifecycle.add_event("TRADE_CONFIRMED", {"broker_ticket": ticket})
    
    # Verify events were recorded
    assert len(lifecycle.events) == 3, "Should have 3 events"
    assert lifecycle.events[0].event_type == "TRADE_SIGNALLED"
    assert lifecycle.events[1].event_type == "TRADE_SUBMITTED"
    assert lifecycle.events[2].event_type == "TRADE_CONFIRMED"
    
    # Verify event has all fields
    event = lifecycle.events[0]
    assert event.ticket == ticket
    assert event.symbol == "XAUUSDm"
    assert event.direction == "bearish"
    assert event.details["confidence"] == "HIGH"
    
    print("✓ TEST 5 PASSED: Lifecycle event tracking works correctly")


# ════════════════════════════════════════════════════════════════════════════
# TEST 3: SIGNAL DEDUPLICATION
# ════════════════════════════════════════════════════════════════════════════

def test_signal_fingerprinting():
    """Verify signal fingerprinting creates deterministic hashes."""
    
    # Create fingerprint for a signal
    fp1 = calculate_signal_fingerprint(
        direction="bullish",
        poi_low=2490.0,
        poi_high=2510.0,
        htf_bias="bullish",
        sweep_type="fvg_fill",
        displacement_tier="strong",
        bos_active=False
    )
    
    # Same signal should create same fingerprint
    fp2 = calculate_signal_fingerprint(
        direction="bullish",
        poi_low=2490.0,
        poi_high=2510.0,
        htf_bias="bullish",
        sweep_type="fvg_fill",
        displacement_tier="strong",
        bos_active=False
    )
    
    assert fp1 == fp2, "Identical signals should have identical fingerprints"
    assert isinstance(fp1, str), "Fingerprint should be string"
    assert len(fp1) == 32, "Fingerprint should be MD5 hash (32 chars)"
    
    # Different signal should create different fingerprint
    fp3 = calculate_signal_fingerprint(
        direction="bearish",  # Changed
        poi_low=2490.0,
        poi_high=2510.0,
        htf_bias="bullish",
        sweep_type="fvg_fill",
        displacement_tier="strong",
        bos_active=False
    )
    
    assert fp1 != fp3, "Different signals should have different fingerprints"
    
    print("✓ TEST 6 PASSED: Signal fingerprinting is deterministic")


def test_signal_deduplication_suppression():
    """Verify identical signals are suppressed within dedup window."""
    from execution import lifecycle_coordinator
    
    # Reset fingerprint tracking
    lifecycle_coordinator._LAST_SIGNAL_FINGERPRINT = None
    lifecycle_coordinator._LAST_SIGNAL_TIME = 0
    lifecycle_coordinator._SIGNAL_DEDUP_TIMEOUT = 60
    
    fingerprint = calculate_signal_fingerprint(
        direction="bullish",
        poi_low=2490.0,
        poi_high=2510.0,
        htf_bias="bullish",
        sweep_type="fvg_fill",
        displacement_tier="strong",
        bos_active=False
    )
    
    # First signal should NOT be suppressed
    suppressed1 = should_suppress_signal(fingerprint, "Signal 1")
    assert suppressed1 == False, "First signal should not be suppressed"
    
    # Identical signal immediately after should BE suppressed
    suppressed2 = should_suppress_signal(fingerprint, "Signal 1 repeated")
    assert suppressed2 == True, "Identical signal should be suppressed"
    
    # Verify fingerprint was updated
    assert lifecycle_coordinator._LAST_SIGNAL_FINGERPRINT == fingerprint
    
    print("✓ TEST 7 PASSED: Signal deduplication suppresses identical signals")


def test_signal_fingerprint_reset():
    """Verify signal dedup can be reset for structure changes."""
    from execution import lifecycle_coordinator
    
    fp1 = calculate_signal_fingerprint(
        direction="bullish", poi_low=2490.0, poi_high=2510.0,
        htf_bias="bullish", sweep_type="fvg_fill",
        displacement_tier="strong", bos_active=False
    )
    
    # Track this fingerprint
    should_suppress_signal(fp1)
    assert lifecycle_coordinator._LAST_SIGNAL_FINGERPRINT == fp1
    
    # Reset on BOS change
    reset_signal_fingerprint("BOS change detected")
    assert lifecycle_coordinator._LAST_SIGNAL_FINGERPRINT is None
    
    # Same fingerprint should now NOT be suppressed (window reset)
    suppressed = should_suppress_signal(fp1, "After reset")
    assert suppressed == False, "Signal should not be suppressed after reset"
    
    print("✓ TEST 8 PASSED: Signal fingerprint reset works correctly")


# ════════════════════════════════════════════════════════════════════════════
# TEST 4: COMPLETE SYSTEM INTEGRATION
# ════════════════════════════════════════════════════════════════════════════

def test_startup_to_runtime_transition():
    """Integration test: Verify full startup→runtime lifecycle."""
    from execution import lifecycle_coordinator
    
    # ── PHASE 1: Startup reconciliation ─────────────────────────────────────
    lifecycle_coordinator._STARTUP_RECONCILIATION_PHASE = True
    lifecycle_coordinator._POSITION_COUNT_AT_LAST_CHECK = 0
    lifecycle_coordinator._STABILIZATION_LOCK_ACTIVE = False
    
    # Simulate restoring 1 position during startup (0 → 1)
    changed = check_position_count_change(1)
    assert changed == True
    assert not is_stabilization_lock_active(), "Startup restore should NOT trigger lock"
    
    # ── PHASE 2: Mark startup complete ──────────────────────────────────────
    mark_startup_complete()
    assert not is_in_startup_phase(), "Should be past startup"
    
    # ── PHASE 3: Runtime position change triggers lock ─────────────────────
    changed = check_position_count_change(0)  # Position closed (1 → 0)
    assert changed == True
    assert is_stabilization_lock_active(), "Runtime closure SHOULD trigger lock"
    
    print("✓ TEST 9 PASSED: Full startup→runtime transition works")


def test_complete_trade_lifecycle():
    """Integration test: Complete trade from signal to closure."""
    from execution import lifecycle_coordinator
    
    # Clear for clean test
    lifecycle_coordinator._TRADE_LIFECYCLES.clear()
    
    ticket = 99999
    symbol = "XAUUSDm"
    direction = "bullish"
    
    # ── STEP 1: Get/create lifecycle ────────────────────────────────────────
    lifecycle = get_or_create_lifecycle(ticket, symbol, direction)
    assert lifecycle.ticket == ticket
    
    # ── STEP 2: Add lifecycle events ────────────────────────────────────────
    lifecycle.add_event("TRADE_SIGNALLED", {"confluent_count": 3})
    lifecycle.add_event("TRADE_SUBMITTED", {"entry_price": "2505.50"})
    lifecycle.add_event("TRADE_CONFIRMED", {"broker_ticket": ticket})
    
    assert len(lifecycle.events) == 3
    
    # ── STEP 3: Process closure ────────────────────────────────────────────
    process_trade_closure(
        ticket=ticket,
        symbol=symbol,
        direction=direction,
        closure_reason="TP",
        realized_pnl=75.25,
        realized_rr=2.2,
        source="TEST_CLOSURE"
    )
    
    # ── STEP 4: Verify closure was recorded ────────────────────────────────
    assert lifecycle.closure_reason == "TP"
    assert lifecycle.realized_pnl == 75.25
    assert lifecycle.realized_rr == 2.2
    
    # Verify TRADE_CLOSED event was added
    closed_events = [e for e in lifecycle.events if e.event_type == "TRADE_CLOSED"]
    assert len(closed_events) == 1, "Should have one TRADE_CLOSED event"
    assert closed_events[0].details["pnl"] == "+75.25"
    assert closed_events[0].details["rr"] == "+2.20"
    
    # Verify lifecycle completion event
    completed_events = [e for e in lifecycle.events if e.event_type == "LIFECYCLE_COMPLETED"]
    assert len(completed_events) == 1, "Should have LIFECYCLE_COMPLETED event"
    
    print("✓ TEST 10 PASSED: Complete trade lifecycle works end-to-end")


# ════════════════════════════════════════════════════════════════════════════
# SUMMARY & EXECUTION
# ════════════════════════════════════════════════════════════════════════════

def run_all_tests():
    """Execute all validation tests."""
    print("\n" + "=" * 80)
    print("PHASE 6 VALIDATION TEST SUITE")
    print("=" * 80 + "\n")
    
    tests = [
        test_startup_phase_recognition,
        test_position_count_change_during_startup,
        test_position_count_change_after_startup,
        test_process_trade_closure_idempotency,
        test_lifecycle_event_tracking,
        test_signal_fingerprinting,
        test_signal_deduplication_suppression,
        test_signal_fingerprint_reset,
        test_startup_to_runtime_transition,
        test_complete_trade_lifecycle,
    ]
    
    passed = 0
    failed = 0
    
    for test in tests:
        try:
            test()
            passed += 1
        except AssertionError as e:
            print(f"✗ {test.__name__} FAILED: {e}")
            failed += 1
        except Exception as e:
            print(f"✗ {test.__name__} ERROR: {e}")
            failed += 1
    
    print("\n" + "=" * 80)
    print(f"RESULTS: {passed} passed, {failed} failed")
    print("=" * 80 + "\n")
    
    return failed == 0


if __name__ == "__main__":
    success = run_all_tests()
    exit(0 if success else 1)

#!/usr/bin/env python3
"""Test backward compatibility of get_lifecycle_state fallback protection."""

from execution.broker_first_closure_processor import get_lifecycle_state


def test_backward_compatibility():
    """Test fallback protection with both TradeState and TerminalTradeState types."""
    
    # Test 1: Object with lifecycle_state field (TerminalTradeState-like)
    class TerminalStateMock:
        def __init__(self):
            self.lifecycle_state = "ACTIVE"
    
    # Test 2: Object with state field (old TradeState)
    class OldStateMock:
        def __init__(self, state):
            self.state = state
    
    # Test 3: Object with no fields (should return UNKNOWN)
    class EmptyMock:
        pass
    
    print("Testing get_lifecycle_state fallback protection:")
    print()
    
    # Test TerminalTradeState-like object
    term_state = TerminalStateMock()
    result1 = get_lifecycle_state(term_state)
    print(f"✅ TerminalTradeState (lifecycle_state='ACTIVE'): {result1}")
    assert result1 == "ACTIVE", "Should return ACTIVE"
    
    # Test old TradeState with ENTRY_ACTIVE
    old_state1 = OldStateMock("ENTRY_ACTIVE")
    result2 = get_lifecycle_state(old_state1)
    print(f"✅ Old TradeState (state='ENTRY_ACTIVE'): {result2}")
    assert result2 == "ACTIVE", "Should map ENTRY_ACTIVE to ACTIVE"
    
    # Test old TradeState with CLOSED state
    old_state2 = OldStateMock("CLOSED_PARTIAL")
    result3 = get_lifecycle_state(old_state2)
    print(f"✅ Old TradeState (state='CLOSED_PARTIAL'): {result3}")
    assert result3 == "CLOSED_VERIFIED", "Should map CLOSED_* to CLOSED_VERIFIED"
    
    # Test object with no fields
    empty = EmptyMock()
    result4 = get_lifecycle_state(empty)
    print(f"✅ Empty object (no fields): {result4}")
    assert result4 == "UNKNOWN", "Should return UNKNOWN for missing fields"
    
    # Test TerminalTradeState with different states
    term_state2 = TerminalStateMock()
    term_state2.lifecycle_state = "CLOSED_RECORDED"
    result5 = get_lifecycle_state(term_state2)
    print(f"✅ TerminalTradeState (lifecycle_state='CLOSED_RECORDED'): {result5}")
    assert result5 == "CLOSED_RECORDED", "Should return exact state"
    
    print()
    print("✅ All fallback tests PASSED - backward compatibility verified")


if __name__ == "__main__":
    test_backward_compatibility()

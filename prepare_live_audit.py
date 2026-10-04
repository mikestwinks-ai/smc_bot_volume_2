"""
prepare_live_audit.py - Prepare environment for live trade closure audit

This script:
1. Clears the forensic audit log
2. Creates fresh state for auditing
3. Provides instructions for running the bot
4. Shows how to analyze results
"""

import os
import json
from datetime import datetime


def clear_forensic_log():
    """Clear the forensic audit log."""
    filepath = "logs/forensic_closure_audit.jsonl"
    try:
        if os.path.exists(filepath):
            os.remove(filepath)
            print(f"✅ Cleared forensic log: {filepath}")
        else:
            print(f"ℹ️  Forensic log doesn't exist yet: {filepath}")
    except Exception as e:
        print(f"❌ Error clearing forensic log: {e}")


def verify_environment():
    """Verify that forensic logging modules exist."""
    print("\nVerifying forensic audit environment...")
    
    required_files = [
        "forensic_closure_auditor.py",
        "closure_timeline_analyzer.py",
        "logs/state/trades_state.json",
        "logs/state/risk_state.json",
        "logs/state/cooldown_state.json",
    ]
    
    for filepath in required_files:
        if os.path.exists(filepath):
            print(f"  ✅ {filepath}")
        else:
            print(f"  ⚠️  {filepath} - MISSING")


def show_instructions():
    """Show instructions for running the audit."""
    print("\n" + "=" * 80)
    print("LIVE TRADE CLOSURE AUDIT INSTRUCTIONS")
    print("=" * 80)
    
    instructions = """
STEP 1: START THE BOT
  python main.py
  
  The bot will start normally and:
  - Run reconciliation on startup
  - Track any live trades
  - When a trade closes, forensic events will be logged to logs/forensic_closure_audit.jsonl
  
STEP 2: WAIT FOR TRADE CLOSURE
  Monitor the console for "TRADE CLOSED" messages
  Look for warnings like:
  - "POSITIONS DISAPPEARED | Tickets: ..."
  - "CLOSURE DETAILS EXTRACTED | Ticket: ..."
  - "TRADE CLOSED | Direction: ... | PnL: ..."
  
STEP 3: STOP THE BOT (After trade closure)
  Press Ctrl+C to gracefully shutdown
  
STEP 4: ANALYZE THE CLOSURE
  python closure_timeline_analyzer.py
  
  This will produce:
  - Complete event timeline for the closed ticket
  - Stage-by-stage trace of the closure pipeline
  - PnL verification
  - State transitions
  - Peak balance changes

EXPECTED PIPELINE (for each closed trade):
  1. POSITION_QUERY              - Check broker for open positions
  2. DISAPPEARED_LIST_CREATED    - Identify tickets no longer on broker
  3. FORENSIC_LOOKUP_START       - Begin deal history search
  4. DEAL_FOUND or DEAL_NOT_FOUND - Locate deal in history
  5. DEAL_PARSED                 - Extract closure details
  6. CLOSURE_VERIFICATION_START  - Verify closure
  7. TRADE_CLOSED_EVENT          - Emit closure event (ONCE ONLY)
  8. ACCOUNTING_START            - Begin accounting
  9. DAILY_PNL_UPDATED           - Record PnL
  10. COOLDOWN_START             - Register cooldown
  11. COOLDOWN_REGISTERED        - Cooldown active
  12. STATE_TRANSITION_START     - Begin state machine
  13. STATE_RECORDED_TO_ARCHIVED - Transition to CLOSED_RECORDED
  14. ARCHIVE_START              - Move to ARCHIVED
  15. ARCHIVE_COMPLETE           - Archive finished
  16. CLOSURE_COMPLETE           - All processing done

KEY METRICS TO VERIFY:
  ✅ Event counts: Each trade should have exactly 1 TRADE_CLOSED_EVENT
  ✅ PnL: entry_price, close_price, realized_pnl should match broker
  ✅ State transitions: Should follow ACTIVE → CLOSED_VERIFIED → CLOSED_RECORDED → ARCHIVED
  ✅ Peak balance: Should update after trade closes
  ✅ Timing: All stages should complete within seconds

PEAK BALANCE INVESTIGATION:
  Watch these stages for peak balance restoration:
  - "PEAK_BALANCE_UPDATED" events with source="restore_daily_state"
  - Check if peak_balance is correctly initialized on startup
  - Compare peak_balance vs current_balance at each update
  - Look for any 0.00 values (indicates reset or error)
"""
    
    print(instructions)


def save_audit_config():
    """Save audit configuration for reference."""
    config = {
        "audit_name": "Live Trade Closure Forensic Audit",
        "created": datetime.now().isoformat(),
        "forensic_log": "logs/forensic_closure_audit.jsonl",
        "analyzer": "closure_timeline_analyzer.py",
        "bot_entry": "python main.py",
        "expected_stages": 16,
        "critical_events": [
            "DISAPPEARED_LIST_CREATED",
            "DEAL_FOUND",
            "DEAL_PARSED",
            "TRADE_CLOSED_EVENT",
            "DAILY_PNL_UPDATED",
            "COOLDOWN_REGISTERED",
            "CLOSURE_COMPLETE",
        ],
    }
    
    with open("audit_config.json", "w") as f:
        json.dump(config, f, indent=2)
    
    print("\n✅ Saved audit configuration: audit_config.json")


if __name__ == "__main__":
    print("\n" + "=" * 80)
    print("PREPARING LIVE TRADE CLOSURE AUDIT")
    print("=" * 80)
    
    clear_forensic_log()
    verify_environment()
    show_instructions()
    save_audit_config()
    
    print("\n" + "=" * 80)
    print("READY FOR LIVE AUDIT")
    print("=" * 80)

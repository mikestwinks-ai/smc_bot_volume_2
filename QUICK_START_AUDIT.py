#!/usr/bin/env python3
"""
QUICK START - Live Trade Closure Forensic Audit

Run this file to get started with the forensic audit system.
"""

import os
import sys
from datetime import datetime

def print_header(title):
    """Print formatted header."""
    print(f"\n{'═' * 80}")
    print(f"  {title}")
    print(f"{'═' * 80}\n")

def main():
    print_header("FORENSIC CLOSURE AUDIT - QUICK START")
    
    print("📋 WHAT'S NEW")
    print("  ✅ 19 instrumented stages in closure pipeline")
    print("  ✅ Complete event timeline generation")
    print("  ✅ Peak balance restoration tracking")
    print("  ✅ PnL verification system")
    print("  ✅ Zero impact on trading logic")
    
    print("\n📂 NEW FILES CREATED")
    files = {
        "forensic_closure_auditor.py": "Central logging hub",
        "closure_timeline_analyzer.py": "Timeline generator",
        "prepare_live_audit.py": "Environment setup",
        "FORENSIC_AUDIT_GUIDE.md": "Complete documentation",
        "FORENSIC_AUDIT_README.md": "User guide",
    }
    for fname, desc in files.items():
        path = fname
        exists = "✅" if os.path.exists(path) else "❌"
        print(f"  {exists} {fname:40s} - {desc}")
    
    print("\n🔧 MODIFIED FILES")
    mods = {
        "broker_first_closure_processor.py": "Added 100 lines of logging",
        "risk_manager.py": "Added 50 lines of logging",
    }
    for fname, desc in mods.items():
        exists = "✅" if os.path.exists(fname) else "❌"
        print(f"  {exists} {fname:40s} - {desc}")
    
    print_header("RUNNING THE AUDIT")
    
    print("STEP 1️⃣  PREPARE ENVIRONMENT")
    print("  Command: python prepare_live_audit.py")
    print("  Does: Verifies infrastructure, clears old logs, shows instructions")
    print()
    
    print("STEP 2️⃣  START THE BOT")
    print("  Command: python main.py")
    print("  Does: Normal bot operation with forensic logging enabled")
    print("  Watch: For 'TRADE CLOSED' messages in console")
    print("  Stop: Press Ctrl+C after trade closes")
    print()
    
    print("STEP 3️⃣  ANALYZE THE CLOSURE")
    print("  Command: python closure_timeline_analyzer.py")
    print("  Does: Reads logs/forensic_closure_audit.jsonl")
    print("  Output: Complete event timeline with stage-by-stage trace")
    print()
    
    print_header("WHAT YOU'LL SEE")
    
    print("From prepare_live_audit.py:")
    print("  ✅ Environment verification status")
    print("  ✅ Detailed audit instructions")
    print("  ✅ Expected pipeline stages (19 total)")
    print("  ✅ Verification checklist")
    print()
    
    print("From main.py with forensic logging:")
    print("  ✅ Normal trading console output")
    print("  ✅ Events logged to logs/forensic_closure_audit.jsonl")
    print("  ✅ Example messages:")
    print("     - 'POSITIONS DISAPPEARED | Tickets: ...'")
    print("     - 'CLOSURE DETAILS EXTRACTED | Ticket: ...'")
    print("     - 'TRADE CLOSED | Direction: ... | PnL: ...'")
    print()
    
    print("From closure_timeline_analyzer.py:")
    print("  ✅ Event timeline for each closed ticket")
    print("  ✅ Stage-by-stage execution trace")
    print("  ✅ PnL verification")
    print("  ✅ State transition summary")
    print("  ✅ Peak balance updates")
    print("  ✅ Anomaly detection report")
    print()
    
    print_header("EXAMPLE AUDIT OUTPUT")
    
    example = """
╔════════════════════════════════════════════════════════════════════════════╗
║             CLOSURE TIMELINE | TICKET: 2794340178                         ║
╚════════════════════════════════════════════════════════════════════════════╝

Duration: 0.847 seconds
Stages: 18
Start: 2026-06-01T09:40:29.752450
End: 2026-06-01T09:40:30.599875

────────────────────────────────────────────────────────────────────────────
STAGE-BY-STAGE TRACE
────────────────────────────────────────────────────────────────────────────

[ 1] T+0.000s | POSITION_QUERY
     └─ symbol: XAUUSDm
     └─ memory_states: 1

[ 2] T+0.001s | DISAPPEARED_LIST_CREATED
     └─ disappeared_count: 1
     └─ tickets: [2794340178]

[ 3] T+0.002s | FORENSIC_LOOKUP_START
[ 4] T+0.045s | DEAL_FOUND
     └─ Deal Ticket: 54321987
     └─ Close Price: 4550.25
     └─ PnL: +75.50

[ 5] T+0.046s | DEAL_PARSED
     └─ Entry: 4535.68
     └─ Close: 4550.25
     └─ PnL: +75.50 (+1.50R)
     └─ Swap: -2.50, Commission: -1.25

...14 more stages...

────────────────────────────────────────────────────────────────────────────
CLOSURE SUMMARY
────────────────────────────────────────────────────────────────────────────
✅ Deal Found: Ticket 54321987 | PnL +75.50
✅ PnL Extracted: +75.50 (+1.50R)
✅ State Transitions: 4 transitions
✅ Peak Balance Updated: 625.00
"""
    print(example)
    
    print_header("PEAK BALANCE INVESTIGATION")
    
    print("To investigate why Peak Balance restores as 0.00:")
    print()
    print("1. Look for PEAK_BALANCE_UPDATED events with source='restore_daily_state'")
    print("2. Check if peak_balance field is 0.00 (indicates error)")
    print("3. Compare peak_balance vs current_balance at each update")
    print("4. Check 'corrected' flag (true = value was fixed)")
    print()
    print("Expected output:")
    print("""
{
  "stage": "PEAK_BALANCE_UPDATED",
  "data": {
    "source": "restore_daily_state",
    "peak_balance": 625.00,      ← Should NOT be 0.00
    "peak_equity": 625.00,
    "current_balance": 625.00,
    "corrected": false
  }
}
""")
    
    print_header("VERIFICATION CHECKLIST")
    
    checklist = [
        ("Position Detection", "POSITION_QUERY logged"),
        ("Forensic Verification", "DEAL_FOUND shows correct deal_ticket"),
        ("Event Emission", "TRADE_CLOSED_EVENT appears exactly once"),
        ("Accounting", "TRADE_RESULT_RECORDED matches DEAL_PARSED PnL"),
        ("State Transitions", "Correct sequence: ACTIVE → CLOSED_VERIFIED → CLOSED_RECORDED → ARCHIVED"),
        ("Peak Balance", "peak_balance >= current_balance (always)"),
        ("Cooldown", "COOLDOWN_REGISTERED appears exactly once"),
        ("Archive", "Final state is ARCHIVED"),
    ]
    
    for i, (category, check) in enumerate(checklist, 1):
        print(f"  [{i}] {category:20s} - {check}")
    
    print_header("QUICK REFERENCE")
    
    print("🔍 Key Commands")
    print("  python prepare_live_audit.py          - Prepare audit environment")
    print("  python main.py                        - Run bot with forensic logging")
    print("  python closure_timeline_analyzer.py   - Analyze results")
    print()
    
    print("📊 Log Files")
    print("  logs/forensic_closure_audit.jsonl     - Event log (JSONL format)")
    print("  logs/smc_bot_*.log                    - Bot console log")
    print("  logs/state/trades_state.json          - Trade states")
    print("  logs/state/risk_state.json            - Risk tracking")
    print()
    
    print("📖 Documentation")
    print("  FORENSIC_AUDIT_GUIDE.md               - Complete guide (500 lines)")
    print("  FORENSIC_AUDIT_README.md              - User guide")
    print("  audit_config.json                     - Audit configuration")
    print()
    
    print_header("IMPORTANT NOTES")
    
    print("✅ All forensic logging is TEMPORARY")
    print("   - Can be disabled: FORENSIC_ENABLED = False in forensic_closure_auditor.py")
    print("   - Can be removed: Delete the 4 new files")
    print()
    
    print("✅ ZERO IMPACT ON TRADING LOGIC")
    print("   - Logging only, no behavior changes")
    print("   - No state modifications")
    print("   - No performance impact")
    print()
    
    print("✅ COMPLETE TRACEABILITY")
    print("   - Every decision logged")
    print("   - Every data point captured")
    print("   - Full audit trail preserved")
    print()
    
    print_header("READY TO AUDIT")
    
    print(f"Timestamp: {datetime.now().isoformat()}")
    print()
    print("Next action: Run 'python prepare_live_audit.py'")
    print()

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n\n[Interrupted by user]")
        sys.exit(0)

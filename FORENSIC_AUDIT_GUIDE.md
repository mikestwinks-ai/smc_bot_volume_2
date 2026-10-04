"""
FORENSIC CLOSURE AUDIT - COMPLETE GUIDE

This document explains the complete forensic instrumentation of the trade closure
pipeline for Phase 3 validation.
"""

FORENSIC_AUDIT_GUIDE = """
╔════════════════════════════════════════════════════════════════════════════╗
║ FORENSIC CLOSURE AUDIT - COMPLETE GUIDE ║
║ ║
║ A comprehensive system to trace every stage of the trade closure pipeline ║
║ from broker position disappearance to final persistence update. ║
╚════════════════════════════════════════════════════════════════════════════╝

═══════════════════════════════════════════════════════════════════════════════
OVERVIEW
═══════════════════════════════════════════════════════════════════════════════

The forensic audit system instruments the complete trade closure pipeline with
fine-grained event logging at every critical stage:

    Position Disappears
         ↓
    Forensic Lookup in Deal History
         ↓
    Closure Verification
         ↓
    PnL Extraction
         ↓
    Event Emission (ONCE ONLY)
         ↓
    Accounting Update (ONCE ONLY)
         ↓
    Cooldown Registration (ONCE ONLY)
         ↓
    State Transition
         ↓
    Persistence Update
         ↓
    Archive

═══════════════════════════════════════════════════════════════════════════════
INSTRUMENTED MODULES
═══════════════════════════════════════════════════════════════════════════════

1. forensic_closure_auditor.py (NEW)
   Purpose: Central logging hub for forensic events
   Exports:
   - audit_log(stage, data, ticket) : Log a forensic event
   - get_auditor() : Get global auditor instance
   - report_closure(ticket) : Get closure timeline for a ticket
     Features:
   - JSONL format (line-delimited JSON) for easy parsing
   - Automatic persistence to logs/forensic_closure_audit.jsonl
   - Per-ticket tracking with timestamps
   - Zero impact on trading logic

2. closure_timeline_analyzer.py (NEW)
   Purpose: Parse and analyze forensic logs
   Exports:
   - load_forensic_log() : Load all events from audit file
   - group_by_ticket() : Group events by ticket
   - generate_closure_timeline() : Generate timeline for one ticket
   - analyze_all_closures() : Analyze all closures
   - print_closure_timeline() : Pretty-print timeline
     Usage:
     python closure_timeline_analyzer.py

3. broker_first_closure_processor.py (MODIFIED)
   Added forensic logging at:
   - detect_broker_closed_positions(): POSITION_QUERY, DISAPPEARED_LIST_CREATED
   - verify_and_extract_closure(): FORENSIC_LOOKUP_START, DEAL_FOUND/DEAL_NOT_FOUND, DEAL_PARSED
   - finalize*single_closure(): TRADE_CLOSED_EVENT, ACCOUNTING*_, COOLDOWN\__, STATE\_\*
   - archive*closed_positions(): ARCHIVE*\*

4. risk_manager.py (MODIFIED)
   Added forensic logging at:
   - restore_daily_state(): PEAK_BALANCE_UPDATED (with correction tracking)
   - record_trade_result(): TRADE_RESULT_RECORDED, PEAK_BALANCE_UPDATED

═══════════════════════════════════════════════════════════════════════════════
FORENSIC EVENT STAGES (16 total)
═══════════════════════════════════════════════════════════════════════════════

DETECTION PHASE:

1. POSITION_QUERY
   What: Querying broker for open positions
   Data: { symbol, memory_states }
   When: Start of closure detection

2. DISAPPEARED_LIST_CREATED
   What: List of disappeared tickets identified
   Data: { disappeared_count, tickets, broker_open, memory_states }
   When: After broker position comparison

FORENSIC LOOKUP PHASE: 3. FORENSIC_LOOKUP_START
What: Beginning forensic deal history lookup
Data: { ticket, symbol, state }
When: Before deal history search

4. DEAL_FOUND
   What: Matching deal found in broker history
   Data: { ticket, deal_ticket, close_price, realized_pnl, close_reason, close_time }
   When: Deal located in history

5. DEAL_NOT_FOUND
   What: Position missing and no deal in history (orphan)
   Data: { ticket, reason: "Position missing, no deal in history" }
   When: Closure verification fails

6. DEAL_PARSED
   What: Deal data extracted and parsed
   Data: { ticket, deal_ticket, entry_price, closure_price, realized_pnl, realized_rr, swap, commission }
   When: Closure details finalized

CLOSURE VERIFICATION PHASE: 7. CLOSURE_VERIFICATION_START
What: Beginning closure verification
Data: { ticket, state, entry_price, closure_price }
When: Before finalization

CLOSURE EVENT EMISSION PHASE: 8. TRADE_CLOSED_EVENT
What: TRADE_CLOSED event emitted (exactly-once)
Data: { ticket, direction, entry_price, closure_price, realized_pnl, realized_rr, reason, status }
When: After verification, only on first entry

ACCOUNTING PHASE: 9. ACCOUNTING_START
What: Beginning accounting update
Data: { ticket, pnl }
When: Before PnL recording

10. TRADE_RESULT_RECORDED
    What: Trade result recorded to ledger
    Data: { pnl, daily_pnl, closed_trades_today, consecutive_losses }
    When: After PnL added to daily total

11. DAILY_PNL_UPDATED
    What: Daily PnL updated
    Data: { ticket, pnl, status: "recorded" }
    When: After accounting recorded

COOLDOWN PHASE: 12. COOLDOWN_START
What: Beginning cooldown registration
Data: { ticket, reason }
When: Before cooldown registered

13. COOLDOWN_REGISTERED
    What: Cooldown registered for direction/bias
    Data: { ticket, direction, reason, status: "registered" }
    When: After cooldown set

STATE TRANSITION PHASE: 14. STATE_TRANSITION_START
What: Beginning state machine transition
Data: { ticket, from_state, to_state }
When: Before transition

15. STATE_RECORDED_TO_ARCHIVED
    What: Transition to CLOSED_RECORDED complete
    Data: { ticket, new_state, deal_ticket, closure_reason }
    When: After state update

ARCHIVE & COMPLETION PHASE: 16. ARCHIVE_START
What: Beginning archive of closed trade
Data: { ticket, state }
When: Before archive transition

17. ARCHIVE_COMPLETE
    What: Archive complete
    Data: { ticket, final_state: "ARCHIVED" }
    When: After archive state reached

18. CLOSURE_COMPLETE
    What: Complete trade closure pipeline finished
    Data: { ticket, state, pnl, rr }
    When: After all processing complete

PEAK BALANCE TRACKING: 19. PEAK_BALANCE_UPDATED
What: Peak balance updated during trading
Data: { source, peak_balance, peak_equity, current_balance, corrected }
When: On startup restore and after each trade

═══════════════════════════════════════════════════════════════════════════════
FORENSIC LOG FORMAT
═══════════════════════════════════════════════════════════════════════════════

Location: logs/forensic_closure_audit.jsonl

Format: JSONL (one JSON object per line)

Example Event:
{
"timestamp": 1748918429.7524502,
"timestamp_iso": "2026-06-01T09:40:29.752450",
"stage": "DEAL_PARSED",
"ticket": 12345678,
"data": {
"ticket": 12345678,
"deal_ticket": 54321987,
"entry_price": 4535.68,
"closure_price": 4550.25,
"realized_pnl": 75.50,
"realized_rr": 1.50,
"swap": -2.50,
"commission": -1.25
}
}

═══════════════════════════════════════════════════════════════════════════════
ANALYSIS WORKFLOW
═══════════════════════════════════════════════════════════════════════════════

STEP 1: PREPARE ENVIRONMENT
python prepare_live_audit.py

- Clears previous forensic log
- Verifies audit infrastructure
- Shows detailed instructions
- Saves audit configuration

STEP 2: RUN BOT
python main.py

- Bot starts normally
- Forensic logging happens invisibly
- Events written to logs/forensic_closure_audit.jsonl
- Stop after trade closure (Ctrl+C)

STEP 3: ANALYZE RESULTS
python closure_timeline_analyzer.py

Produces: - Chronological event timeline - Stage-by-stage trace - PnL verification - State transition validation - Peak balance tracking - Anomaly detection

═══════════════════════════════════════════════════════════════════════════════
VERIFICATION CHECKLIST
═══════════════════════════════════════════════════════════════════════════════

For each closed trade, verify:

✅ POSITION DETECTION
□ POSITION_QUERY logged at start
□ DISAPPEARED_LIST_CREATED shows correct tickets
□ Broker position count matches reality

✅ FORENSIC VERIFICATION
□ FORENSIC_LOOKUP_START before deal search
□ DEAL_FOUND or DEAL_NOT_FOUND logged
□ deal_ticket matches expected value
□ close_price matches broker
□ DEAL_PARSED with complete data

✅ EXACTLY-ONCE SEMANTICS
□ TRADE_CLOSED_EVENT appears exactly once (status: "emitted")
□ TRADE_RESULT_RECORDED appears exactly once
□ COOLDOWN_REGISTERED appears exactly once
□ No duplicate event logs

✅ ACCOUNTING ACCURACY
□ ACCOUNTING_START precedes recording
□ TRADE_RESULT_RECORDED pnl matches DEAL_PARSED
□ daily_pnl accumulates correctly
□ closed_trades_today increments by 1

✅ STATE TRANSITIONS
□ STATE_TRANSITION_START before transition
□ From_state and to_state correct
□ STATE_RECORDED_TO_ARCHIVED after completion
□ Final state is ARCHIVED

✅ PEAK BALANCE
□ PEAK_BALANCE_UPDATED events logged
□ peak_balance >= current_balance (always)
□ No 0.00 values (indicates error)
□ Updates after trade close

✅ TIMING
□ All stages complete within 1-2 seconds total
□ Forensic lookup < 100ms
□ State transitions instant
□ Persistence write < 50ms

═══════════════════════════════════════════════════════════════════════════════
TROUBLESHOOTING
═══════════════════════════════════════════════════════════════════════════════

ISSUE: Forensic log file not created

Cause: Bot didn't complete any closures
Fix: Wait for a trade to close on live broker
Check: Look for "POSITIONS DISAPPEARED" in bot console output

ISSUE: Missing stages in timeline

Cause: Trade closure incomplete or partial failure
Fix: Look at the last logged stage to identify where it failed
Check: Bot should show an ERROR message in console

ISSUE: TRADE_CLOSED_EVENT appears multiple times

Cause: Idempotent guard failed (critical defect)
Fix: Check if close_event_emitted flag is persisting
Alert: This indicates a serious bug in exactly-once semantics

ISSUE: PnL values don't match broker

Cause: Deal not found or wrong deal matched
Fix: Check DEAL_FOUND event has correct deal_ticket
Check: Compare deal_ticket against broker MT5 terminal

ISSUE: Peak balance = 0.00

Cause: Restoration issue or persistence corruption
Fix: Check PEAK_BALANCE_UPDATED source="restore_daily_state"
Alert: May indicate peak_balance not initialized correctly on startup

═══════════════════════════════════════════════════════════════════════════════
FORENSIC LOG ANALYSIS EXAMPLES
═══════════════════════════════════════════════════════════════════════════════

EXAMPLE 1: Extract all PnL values for a trade

grep '"stage": "DEAL_PARSED"' logs/forensic_closure_audit.jsonl | \\
jq '.data.realized_pnl'

EXAMPLE 2: Count how many trades closed

grep '"stage": "TRADE_CLOSED_EVENT"' logs/forensic_closure_audit.jsonl | \\
wc -l

EXAMPLE 3: Find all duplicate event emissions (defect check)

jq '.ticket' logs/forensic_closure_audit.jsonl | sort | uniq -d

EXAMPLE 4: Extract state transitions for a ticket

jq 'select(.ticket == 12345678 and .stage | contains("STATE"))' \\
logs/forensic_closure_audit.jsonl

EXAMPLE 5: Timeline for a specific ticket

python -c "
from closure_timeline_analyzer import \*
events = load_forensic_log()
timeline = generate_closure_timeline(12345678, events)
print_closure_timeline(timeline)
"

═══════════════════════════════════════════════════════════════════════════════
PEAK BALANCE INVESTIGATION GUIDE
═══════════════════════════════════════════════════════════════════════════════

The user reported: "Peak Balance restores as 0.00 while Balance is non-zero"

To investigate, look for these events:

1. PEAK_BALANCE_UPDATED with source="restore_daily_state"
   Check: Is peak_balance being set to 0.00?
   Check: Is current_balance non-zero?
   Check: Is corrected=true?

2. Check persistence file content
   cat logs/state/risk_state.json
   Look for: peak_balance value
   Expected: peak_balance >= 0 and >= current balance

3. Trace the sequence:

   Bot starts
   ↓
   restore_daily_state() called
   ↓
   Load risk_state.json
   ↓
   Check: persisted peak_balance = ?
   ↓
   Compare: persisted peak_balance vs current balance
   ↓
   Corrected if: persisted == 0 or persisted < balance
   ↓
   Selected peak_balance = max(persisted, balance, equity)
   ↓
   Save to persistence
   ↓
   Log in PEAK_BALANCE_UPDATED

4. Look for this pattern in forensic log:

   {
   "stage": "PEAK_BALANCE_UPDATED",
   "data": {
   "source": "restore_daily_state",
   "peak_balance": 625.00, ← This should NOT be 0.00
   "peak_equity": 625.00,
   "current_balance": 625.00,
   "corrected": false ← true if value was fixed
   }
   }

═══════════════════════════════════════════════════════════════════════════════
CONCLUSION
═══════════════════════════════════════════════════════════════════════════════

This forensic audit system provides complete end-to-end traceability of the
trade closure pipeline without modifying any trading logic.

All forensic logging is temporary and can be disabled by:

1. Setting FORENSIC_ENABLED = False in forensic_closure_auditor.py
2. Removing import of audit_log from instrumented modules
3. Removing forensic_closure_auditor.py and closure_timeline_analyzer.py

The system is designed to:
✅ Trace every stage from position disappearance to persistence
✅ Verify exactly-once closure semantics
✅ Track peak balance restoration and updates
✅ Provide detailed timeline reports
✅ Detect anomalies and replay attempts
✅ Zero impact on trading logic
✅ No modification of state or behavior

Ready for live trade closure auditing.
"""

if **name** == "**main**":
print(FORENSIC_AUDIT_GUIDE)

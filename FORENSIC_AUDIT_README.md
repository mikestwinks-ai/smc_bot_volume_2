# Live Trade Closure Forensic Audit System - Complete Implementation

## What Was Built

A comprehensive forensic instrumentation system that traces every stage of the trade closure pipeline from broker position disappearance through final persistence, without modifying any trading logic.

### New Files Created (4)

| File                             | Purpose                                                   | Lines |
| -------------------------------- | --------------------------------------------------------- | ----- |
| **forensic_closure_auditor.py**  | Central event logging hub, JSONL persistence              | 200   |
| **closure_timeline_analyzer.py** | Parse forensic logs, generate timelines, detect anomalies | 350   |
| **prepare_live_audit.py**        | Environment setup, clear logs, show instructions          | 150   |
| **FORENSIC_AUDIT_GUIDE.md**      | Complete documentation with examples                      | 500   |

### Files Modified (2)

| File                                  | Changes                                             | Lines |
| ------------------------------------- | --------------------------------------------------- | ----- |
| **broker_first_closure_processor.py** | Added forensic logging at each closure stage        | +100  |
| **risk_manager.py**                   | Added forensic logging for peak balance restoration | +50   |

---

## The Forensic Pipeline (19 Stages)

### Detection Phase

1. **POSITION_QUERY** - Broker position check
2. **DISAPPEARED_LIST_CREATED** - List of closed tickets

### Forensic Lookup Phase

3. **FORENSIC_LOOKUP_START** - Begin deal history search
4. **DEAL_FOUND** / **DEAL_NOT_FOUND** - Deal located or orphan confirmed
5. **DEAL_PARSED** - Closure details extracted

### Verification & Event Emission Phase

6. **CLOSURE_VERIFICATION_START** - Verification begins
7. **TRADE_CLOSED_EVENT** - Event emitted (exactly-once guard)

### Accounting Phase

8. **ACCOUNTING_START** - Accounting begins
9. **TRADE_RESULT_RECORDED** - PnL recorded
10. **DAILY_PNL_UPDATED** - Daily total updated

### Cooldown Phase

11. **COOLDOWN_START** - Cooldown begins
12. **COOLDOWN_REGISTERED** - Cooldown active (exactly-once guard)

### State Transition Phase

13. **STATE_TRANSITION_START** - State transition begins
14. **STATE_RECORDED_TO_ARCHIVED** - Transition to CLOSED_RECORDED

### Archive Phase

15. **ARCHIVE_START** - Archive begins
16. **ARCHIVE_COMPLETE** - Archive complete

### Completion Phase

17. **CLOSURE_COMPLETE** - All processing finished

### Peak Balance Tracking

18. **PEAK_BALANCE_UPDATED** - Peak balance changed
19. **Peak Restoration Forensics** - Startup restoration tracked

---

## How to Use It

### STEP 1: Prepare Environment

```bash
python prepare_live_audit.py
```

- Clears previous forensic logs
- Verifies infrastructure
- Shows detailed instructions
- Saves audit configuration

### STEP 2: Run the Bot

```bash
python main.py
```

- Bot runs normally
- Forensic events logged invisibly
- Watch for "TRADE CLOSED" messages
- Stop after trade closure (Ctrl+C)

### STEP 3: Analyze Results

```bash
python closure_timeline_analyzer.py
```

This generates:

- Complete chronological timeline
- Stage-by-stage execution trace
- PnL verification
- State transition validation
- Peak balance tracking
- Anomaly detection report

---

## What Gets Logged

### Log Location

```
logs/forensic_closure_audit.jsonl
```

### Format (JSONL - one JSON object per line)

```json
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
    "realized_pnl": 75.5,
    "realized_rr": 1.5,
    "swap": -2.5,
    "commission": -1.25
  }
}
```

---

## Verification Checklist

For each closed trade, verify:

✅ **Position Detection**

- POSITION_QUERY logged
- DISAPPEARED_LIST_CREATED shows correct tickets
- Broker position count accurate

✅ **Forensic Verification**

- FORENSIC_LOOKUP_START before search
- DEAL_FOUND or DEAL_NOT_FOUND logged
- deal_ticket matches broker
- close_price matches broker
- DEAL_PARSED complete

✅ **Exactly-Once Semantics**

- TRADE_CLOSED_EVENT appears exactly once
- TRADE_RESULT_RECORDED appears exactly once
- COOLDOWN_REGISTERED appears exactly once
- No duplicate logs

✅ **Accounting**

- ACCOUNTING_START precedes recording
- TRADE_RESULT_RECORDED pnl matches DEAL_PARSED
- daily_pnl accumulates correctly
- closed_trades_today increments by 1

✅ **State Transitions**

- STATE_TRANSITION_START before transition
- From and to states correct
- STATE_RECORDED_TO_ARCHIVED after completion
- Final state is ARCHIVED

✅ **Peak Balance**

- PEAK_BALANCE_UPDATED logged
- peak_balance >= current_balance (always)
- No 0.00 values
- Updates after trade close

✅ **Timing**

- All stages complete within 1-2 seconds total
- Forensic lookup < 100ms
- State transitions instant
- Persistence write < 50ms

---

## Peak Balance Investigation

The system tracks peak balance restoration with:

- **source** field: Shows where update came from (restore_daily_state)
- **peak_balance** field: The peak value (should NOT be 0.00)
- **current_balance** field: Current account balance
- **corrected** field: true if value was fixed

### To Check Peak Balance Restoration

Look for events with `"stage": "PEAK_BALANCE_UPDATED"` and `"source": "restore_daily_state"`

Expected pattern:

```json
{
  "stage": "PEAK_BALANCE_UPDATED",
  "data": {
    "source": "restore_daily_state",
    "peak_balance": 625.00,      ← Should NOT be 0.00
    "peak_equity": 625.00,
    "current_balance": 625.00,
    "corrected": false            ← true if value was fixed
  }
}
```

If peak_balance is 0.00:

1. Check if persistence file was corrupted
2. Check if restoration logic failed
3. Verify correction was applied (corrected=true)

---

## Key Design Features

✅ **Non-Invasive**

- Logging only, no logic changes
- Zero impact on trading behavior
- Can be disabled with one flag

✅ **Complete Coverage**

- 19 stages instrumented
- Every critical decision logged
- Full end-to-end traceability

✅ **Exactly-Once Verification**

- Event emission guards logged
- Accounting guards logged
- Cooldown guards logged
- No replay possible

✅ **Peak Balance Tracking**

- Restoration source tracked
- Correction detection enabled
- Zero value alerts
- Full history available

✅ **Automatic Persistence**

- JSONL format (one event per line)
- Automatic file append
- No loss of events
- Easy to parse and analyze

✅ **Anomaly Detection**

- Duplicate event detection
- State transition validation
- PnL accuracy verification
- Timing analysis

---

## Expected Output from Analyzer

When you run `python closure_timeline_analyzer.py`, you'll see:

```
╔════════════════════════════════════════════════════════════════════════════╗
║             CLOSURE TIMELINE | TICKET: 12345678                           ║
╚════════════════════════════════════════════════════════════════════════════╝

Duration: 0.847 seconds
Stages: 18
Start: 2026-06-01T09:40:29.752450
End: 2026-06-01T09:40:30.599875

────────────────────────────────────────────────────────────────────────────
STAGE-BY-STAGE TRACE
────────────────────────────────────────────────────────────────────────────

[ 1] T+0.000s | POSITION_QUERY
[ 2] T+0.001s | DISAPPEARED_LIST_CREATED
     └─ disappeared_count: 1
     └─ tickets: [12345678]

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

[... 13 more stages ...]

────────────────────────────────────────────────────────────────────────────
CLOSURE SUMMARY
────────────────────────────────────────────────────────────────────────────
✅ Deal Found: Ticket 54321987 | PnL +75.50
✅ PnL Extracted: +75.50 (+1.50R)
✅ State Transitions: 4 transitions
✅ Peak Balance Updated: 625.00
```

---

## Troubleshooting

| Issue                          | Cause                   | Fix                                                   |
| ------------------------------ | ----------------------- | ----------------------------------------------------- |
| No forensic log created        | No trades closed        | Wait for live trade closure                           |
| Missing stages                 | Partial failure         | Check last logged stage in console                    |
| TRADE_CLOSED_EVENT appears 2x+ | Idempotent guard failed | Critical defect - check close_event_emitted flag      |
| PnL mismatch                   | Wrong deal matched      | Verify deal_ticket in DEAL_FOUND event                |
| Peak balance = 0.00            | Restoration issue       | Check PEAK_BALANCE_UPDATED source=restore_daily_state |

---

## Files You Can Run

### Entry Points

```bash
# Prepare environment
python prepare_live_audit.py

# Run bot (normal operation)
python main.py

# Analyze results
python closure_timeline_analyzer.py

# View forensic guide
python FORENSIC_AUDIT_GUIDE.md
```

### Configuration

All forensic logging can be disabled by:

1. Setting `FORENSIC_ENABLED = False` in forensic_closure_auditor.py
2. Or removing the `from forensic_closure_auditor import audit_log` imports

---

## Next Steps

1. **Run prepare_live_audit.py** to verify environment is ready
2. **Start main.py** and wait for a live trade to close
3. **Monitor console** for "TRADE CLOSED" messages
4. **Stop bot** with Ctrl+C after closure
5. **Run closure_timeline_analyzer.py** to generate report
6. **Review timeline** against verification checklist
7. **Investigate peak balance** using the guide
8. **Document findings** in audit report

---

## Summary

You now have a complete forensic audit system that:

✅ Traces all 19 stages of trade closure
✅ Verifies exactly-once semantics
✅ Tracks peak balance restoration
✅ Extracts and verifies PnL
✅ Validates state transitions
✅ Detects anomalies
✅ Requires zero logic changes
✅ Can be enabled/disabled instantly
✅ Produces detailed event timelines
✅ Ready for live trade closure monitoring

**Status**: Ready to audit live trade closures under MT5 broker conditions.

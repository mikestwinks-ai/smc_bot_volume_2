"""
PHASE 6 QUICK REFERENCE GUIDE

═════════════════════════════════════════════════════════════════════════════════
GETTING STARTED WITH PHASE 6 ARCHITECTURE
═════════════════════════════════════════════════════════════════════════════════

## When Bot Starts (Startup Phase)

1. main.py calls reconcile_positions_on_startup()
   ↓
2. trade_manager.py restores persisted positions (0 → 1)
   - Calls check_position_count_change(1)
   - Detects change but is_in_startup_phase() == True
   - NO stabilization lock engaged ✅
     ↓
3. reconciliation completes
   ↓
4. mark_startup_complete() called
   - Sets \_STARTUP_RECONCILIATION_PHASE = False
   - Runtime lifecycle monitoring now ACTIVE
     ↓
5. Bot loop starts
   - Position count tracking now live
   - Position changes WILL trigger stabilization lock

═════════════════════════════════════════════════════════════════════════════════
DURING BOT OPERATION
═════════════════════════════════════════════════════════════════════════════════

### Scenario 1: Position Closes Naturally (TP Hit)

main.py loop:
↓
manage_open_trades():
↓
detect_and_process_closed_positions():

- Find position missing from MT5
- Query deal history for closure deal
- Extract PnL, RR, closure reason ("TP")
  ↓
  process_trade_closure(
  ticket=12345,
  symbol="XAUUSDm",
  direction="bullish",
  closure_reason="TP",
  realized_pnl=50.00,
  realized_rr=2.5,
  source="DETECT_AND_PROCESS_CLOSED"
  )
  ├─ Create/get TradeLifecycleRecord
  ├─ Add TRADE_CLOSED event
  ├─ Register strategic cooldown: "bullish" blocked for 600s
  ├─ Record trade result (updates daily_pnl)
  ├─ Call cleanup_trade_state()
  └─ Mark lifecycle COMPLETED
  ↓
  Position count changes (1 → 0):
  check_position_count_change() → True
  engage_stabilization_lock() → ENGAGED
  Signal engine blocked for 120s
  ↓
  Entry blocked:
  is_strategic_cooldown_active("XAUUSDm", "bullish") → True
  Entry attempt rejected for 600s
  ↓
  After cooldown expires: Entry allowed again

### Scenario 2: Position Disappears (Broker Issue/Manual Close)

Same path as Scenario 1, with closure_reason="UNKNOWN" if deal not found

### Scenario 3: Duplicate Entry Attempt (Same Signal Repeated)

Before entry attempt:
calculate_signal_fingerprint(...) → hash123
should_suppress_signal(hash123) → True/False

If True: Skip entry entirely ✅

### Scenario 4: Structure Change (BOS/CHoCH)

When new structure detected:
reset_signal_fingerprint("BOS change detected")

Result: Signal dedup window reset, next identical fingerprint NOT suppressed

═════════════════════════════════════════════════════════════════════════════════
KEY FUNCTIONS & WHEN TO USE THEM
═════════════════════════════════════════════════════════════════════════════════

### From lifecycle_coordinator.py

**mark_startup_complete()**
When: Called AFTER reconciliation completes (in trade_manager.py)
Effect: Enables stabilization lock for runtime changes

**is_in_startup_phase()**
When: Internal check during startup
Returns: True if still reconciling, False if runtime

**check_position_count_change(current_count)**
When: Called every iteration in manage_open_trades()
Args: Current open position count from MT5
Returns: True if changed, False if same
Effect: Detects position changes, engages lock if runtime

**process_trade_closure(ticket, symbol, direction, closure_reason, pnl, rr, source)**
When: ALWAYS when position closes (only entry point)
Args:

- ticket: Position ticket
- symbol: Trading symbol
- direction: "bullish" or "bearish"
- closure_reason: "TP", "SL", "BE", "FORCE_CLOSE", etc.
- pnl: Realized profit/loss
- rr: Reward-to-risk achieved
- source: Where detected (for telemetry)
  Effect: Idempotent closure handler, registers cooldown, records telemetry

**calculate_signal_fingerprint(direction, poi_low, poi_high, htf_bias, sweep_type, displacement_tier, bos_active)**
When: Before attempting entry
Returns: MD5 hash of signal structure
Use: Input to should_suppress_signal()

**should_suppress_signal(fingerprint, signal_summary="")**
When: After calculating fingerprint
Returns: True if same signal within 60s, False otherwise
Effect: First time = allow, repeated within 60s = suppress

**reset_signal_fingerprint(reason)**
When: Structure change detected (BOS, CHoCH, POI change, etc.)
Effect: Clears dedup window, allows identical signal again

═════════════════════════════════════════════════════════════════════════════════
IMPLEMENTATION CHECKLIST FOR FUTURE PHASES
═════════════════════════════════════════════════════════════════════════════════

Phase 7: entry_engine.py Integration
☐ In confluence_engine.py:
☐ Calculate signal_fingerprint = calculate_signal_fingerprint(...)
☐ Check: if should_suppress_signal(signal_fingerprint): skip entry
☐ On structure change: reset_signal_fingerprint("reason")

☐ Verify:
☐ Identical signals suppressed for 60s
☐ Different signals allowed
☐ Structure changes reset dedup

Phase 8: Risk Manager Enhancement
☐ Track consecutive losses per signal fingerprint
☐ Extend cooldown on loss streaks
☐ Reset counter on wins

Phase 9: Forensic Reporting
☐ Daily lifecycle summary report
☐ Export trade timeline as JSON
☐ Signal clustering analysis

Phase 10: ML Integration
☐ Pattern recognition on event timelines
☐ Optimize cooldown durations per reason
☐ Validate entry signals vs. historical accuracy

═════════════════════════════════════════════════════════════════════════════════
COMMON PITFALLS & HOW TO AVOID THEM
═════════════════════════════════════════════════════════════════════════════════

❌ PITFALL 1: Calling process_trade_closure() twice for same ticket
✅ SOLUTION: Function is idempotent - safe to call, but avoid it
✅ Add guard: Check lifecycle.closure_reason before calling

❌ PITFALL 2: Registering cooldown outside process_trade_closure()
✅ SOLUTION: Cooldown registered automatically inside
✅ ALL cooldowns must come through process_trade_closure()

❌ PITFALL 3: Triggering stabilization lock during startup
✅ SOLUTION: Already handled - don't call check_position_count_change() before mark_startup_complete()
✅ reconcile_positions_on_startup() does this correctly

❌ PITFALL 4: Forgetting to reset signal fingerprint on structure change
✅ SOLUTION: Call reset_signal_fingerprint("reason") in strategy module
✅ Prevents false deduplication after BOS/CHoCH

❌ PITFALL 5: Not persisting cooldowns on restart
✅ SOLUTION: Already done - initialize_cooldown_from_persistence() in entry_engine
✅ Cooldowns survive bot restart

═════════════════════════════════════════════════════════════════════════════════
DEBUGGING TIPS
═════════════════════════════════════════════════════════════════════════════════

Check startup phase status:

```python
from execution.lifecycle_coordinator import is_in_startup_phase
print(is_in_startup_phase())  # True during startup, False after mark_startup_complete()
```

Check stabilization lock:

```python
from execution.lifecycle_coordinator import is_stabilization_lock_active
print(is_stabilization_lock_active())  # True while locked, False when expired
```

Get lifecycle timeline for ticket:

```python
from execution.lifecycle_coordinator import get_lifecycle_timeline
timeline = get_lifecycle_timeline(ticket=12345)
for event in timeline:
    print(f"{event.event_type}: {event.details}")
```

Check active cooldowns:

```python
from execution.lifecycle_coordinator import is_strategic_cooldown_active
is_active, reason = is_strategic_cooldown_active("XAUUSDm", "bullish")
print(f"Cooldown active: {is_active}, Reason: {reason}")
```

═════════════════════════════════════════════════════════════════════════════════
LOGS TO WATCH FOR
═════════════════════════════════════════════════════════════════════════════════

✅ GOOD LOG SEQUENCES:

[STARTUP]
"STARTUP RECONCILIATION COMPLETE | Stabilization lock now active for runtime events"

[POSITION CLOSES]
"POSITION COUNT CHANGE | Previous: 1 -> Current: 0 | (decreased by 1)"
"STABILIZATION LOCK ENGAGED | Technical sync required"
"TRADE CLOSED | Ticket: 12345 | PnL: +50.00 | RR: +2.50"
"STRATEGIC COOLDOWN REGISTERED | Direction: BULLISH | Reason: TP"
"LIFECYCLE FINALIZED | Ticket: 12345 | All processing complete"

[SIGNAL DEDUP]
"SIGNAL SUPPRESSED | Duplicate fingerprint | Remaining dedup window: 45.2s"
"SIGNAL FINGERPRINT RESET | Reason: BOS change detected"

❌ BAD LOG SEQUENCES:

"STABILIZATION LOCK ENGAGED" during startup (0 → 1)
→ Indicates is_in_startup_phase() not working

"TRADE CLOSED" called multiple times same ticket
→ Indicates duplicate closure detection

"SIGNAL SUPPRESSED" immediately after BOS
→ Indicates fingerprint not reset on BOS

═════════════════════════════════════════════════════════════════════════════════
"""

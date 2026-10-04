# TRADE LIFECYCLE FORENSIC AUDIT - RACE CONDITION ANALYSIS

**Timestamp**: 2026-05-28 17:09:44  
**Status**: CRITICAL RACE CONDITION CONFIRMED

## OBSERVED FAILURE SEQUENCE

```
17:09:44 | HEARTBEAT        | Positions: 0
17:09:44 | SIGNAL ▶ BULLISH | Score: 8.0
17:09:44 | TRADE EXECUTED   | Confirmation: STRONG_DISPLACEMENT
17:09:44 | TRADE OPENED     | Ticket: 2790347710

MISSING TELEMETRY:
- NO "TRADE CLOSED" log
- NO "PnL" result
- NO "Cooldown activated" log
- NO "Lifecycle complete" log
```

## ROOT CAUSE IDENTIFICATION

### Timeline Analysis

**Loop N**:

```
17:09:44 | manage_open_trades() called
         | - Set lifecycle lock (True)
         | - Call detect_and_process_closed_positions()
         | - manage_remaining_positions()
         | - Release lifecycle lock (False)
```

**CRITICAL GAP**: Between releasing lock and signal engine starting

**Loop N (continued, same iteration)**:

```
17:09:44 | Check lifecycle lock → FALSE (already released)
17:09:44 | Signal engine runs → BULLISH signal generated
17:09:44 | execute_trade() → New trade opened immediately
```

### What Went Wrong

1. **detect_and_process_closed_positions() ran but:**
   - Position 1 was OPEN at start of loop
   - Between manage_open_trades() call and signal engine start, position closed
   - detect_and_process_closed_positions() saw it was open and did nothing
   - Position closed AFTER detect_and_process_closed_positions() completed

2. **Lifecycle lock was too short:**
   - Lock released immediately after manage_open_trades() returns
   - No stabilization delay
   - No minimum post-close wait

3. **Signal engine ran before closure accounting:**
   - NO record_trade_result() called (daily_pnl not updated)
   - NO register_trade_exit() called (NO cooldown armed)
   - NO telemetry logged

4. **Cooldown registration missing:**
   - register_trade_exit() never called
   - No cooldown timestamp set
   - \_check_cooldown() cannot block re-entry

## INVARIANTS VIOLATED

```
INVARIANT 1: Lifecycle lock must remain active until:
  ✗ VIOLATED - Released immediately, signal engine can run same iteration

INVARIANT 2: No trade closure is silent:
  ✗ VIOLATED - No TRADE CLOSED log, no telemetry

INVARIANT 3: Every closure triggers record_trade_result():
  ✗ VIOLATED - Not called for position 1

INVARIANT 4: Every closure triggers register_trade_exit():
  ✗ VIOLATED - Not called, no cooldown registered

INVARIANT 5: Signal engine waits for lifecycle completion:
  ✗ VIOLATED - Same-second execution allowed

INVARIANT 6: Cooldown blocks same-direction re-entry:
  ✗ VIOLATED - No cooldown, immediate re-entry allowed
```

## THE VULNERABILITY

**Timing Window**:

```
manage_open_trades() START     → Lock engaged
detect_closed() runs           → Misses closure timing
manage_remaining() runs        → Finds no positions
Lock released                  → WINDOW OPENS
[MT5 processes exit here?]     → CLOSURE MAY HAPPEN HERE
Signal engine starts           → Position count changed, but:
                                 - No closure logged
                                 - No cooldown registered
                                 - Immediate re-entry allowed
```

**Why detect_and_process_closed_positions() Failed**:

1. Called at iteration N
2. Position was OPEN at that time
3. Closure deal not yet available in MT5 history
4. Between closure detection and trade execution, position closes

## REQUIRED FIXES

### PRIORITY 1: Mandatory Stabilization Delay

After manage_open_trades() completes, enforce minimum wait before signal engine:

- 60-180 seconds minimum
- Ensures deal history is populated
- Ensures MT5 has fully processed closure

### PRIORITY 2: Exit Lock With Persistence

Keep lifecycle lock active LONGER:

- After manage_open_trades() releases
- Extend lock duration based on previous closure
- Force stabilization delay even if manage thinks all clear

### PRIORITY 3: Signal Engine Suppression Override

Add override block even if lifecycle lock shows False:

- Track "last_position_count"
- If current_count != last_count, suppress signal engine 1 iteration
- Ensure one full manage cycle after position change

### PRIORITY 4: Forced Same-Direction Cooldown

Implement fallback cooldown even if register_trade_exit() fails:

- After ANY position closes, block same-direction entries for 300s minimum
- Use position count change as trigger
- Independent of register_trade_exit() callback

### PRIORITY 5: Forensic Logging

Log every lifecycle event:

- MANAGE CYCLE START / END
- POSITION CLOSURE DETECTION START / END
- EXIT PROCESSING (deal found / not found)
- RECORD TRADE RESULT (called / skipped)
- COOLDOWN REGISTERED (timestamp / reason)
- LIFECYCLE RELEASE (waiting / immediate)
- SIGNAL ENGINE SUPPRESSION (reason)

## EVIDENCE TRAIL

**Missing logs indicate**:

```
detect_and_process_closed_positions()
  → No output = Position was OPEN when called
  → Closure happened AFTER function returned
  → NO orphaned ticket cleanup
  → NO deal history query
  → NO record_trade_result()
  → NO register_trade_exit()
```

**This explains**:

- Positions: 0 telemetry (position closed before heartbeat)
- No TRADE CLOSED log (not called)
- No cooldown logs (register_trade_exit never called)
- Immediate re-entry (no cooldown registered)

## ARCHITECTURAL FIX REQUIRED

```
Main Loop Iteration N:
├─ manage_open_trades()
│  ├─ set_lifecycle_lock(True)
│  ├─ detect_and_process_closed_positions()
│  ├─ manage_remaining_positions()
│  └─ set_lifecycle_lock(False)
├─
├─ *** NEW: MANDATORY STABILIZATION BLOCK ***
├─ if position_count_changed_this_iteration:
│     ├─ log.warning("LIFECYCLE STABILIZATION | Awaiting closure processing")
│     ├─ sleep(STABILIZATION_DELAY_SECONDS)  ← 60-180 seconds
│     ├─ re_check_positions()
│     ├─ if still_closed:
│     │     └─ arm_fallback_cooldown()
│     └─ log.info("LIFECYCLE STABILIZED | Signal engine may now execute")
│
├─ Check lifecycle lock
├─ Check force_position_count_lock (new)
│
├─ Signal engine
   └─ execute_trade()
```

## IMPLEMENTATION CHECKLIST

- [ ] Add post-manage stabilization delay logic
- [ ] Add position count change detection
- [ ] Add force position count lock mechanism
- [ ] Add fallback cooldown registration
- [ ] Add forensic logging at every lifecycle event
- [ ] Add telemetry for lifecycle transitions
- [ ] Test timing window with manual position closure
- [ ] Verify no same-second re-entries
- [ ] Stress test with rapid signal generation

## DEPLOYMENT READINESS

**Current Status**: ❌ NOT READY - Race condition confirmed

**Required Fixes Before Deployment**:

1. Implement stabilization delay
2. Add forensic logging
3. Runtime test all closure scenarios
4. Verify cooldown blocks same-direction
5. Verify no same-second re-entries

**Risk Level**: 🔴 CRITICAL - Bot can re-enter immediately after closure

**Recommended Action**: HALT trading until fixes deployed

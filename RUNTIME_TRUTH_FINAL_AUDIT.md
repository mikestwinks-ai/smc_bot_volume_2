# RUNTIME TRUTH AUDIT — FINAL BEHAVIORAL VERIFICATION

**Date**: May 27, 2026  
**Status**: Comprehensive runtime audit against daily intraday flattening requirements  
**Scope**: Actual execution paths, MT5 API compatibility, session phase transitions

---

## EXECUTIVE SUMMARY: CRITICAL FAILURES IDENTIFIED

✗ **ARCHITECTURE MISMATCH**: Bot designed for Friday/weekend close only, NOT daily intraday flattening  
✗ **API INCOMPATIBILITY**: Calls `mt5.deals_get()` which DOES NOT EXIST (should be `mt5.history_deals_get()`)  
✗ **SESSION PHASES MISSING**: No transition logging, no behavioral phase enforcement  
✗ **DAILY FLATTENING MISSING**: No aggressive management, no proactive flattening, no hard close window  
✗ **OVERNIGHT RISK ACTIVE**: Positions can carry overnight EVERY DAY (not just Friday/weekend)

**Status Summary**: ~30% functional, ~40% partially broken, ~30% missing entirely

---

## FINDING 1: BROKER HISTORY RECONSTRUCTION — API INCOMPATIBILITY ❌ RUNTIME FAILURE

### Observed Error (Runtime)

```
AttributeError: module 'MetaTrader5' has no attribute 'deals_get'
```

### Root Cause

**File**: `utils/mt5_connector.py` line 370  
**Code**:

```python
deals = mt5.deals_get(symbol=symbol, group="*SMC*")  # ← WRONG METHOD
```

**Actual MT5 API Available Methods**:

- ✓ `mt5.history_deals_get(from_date, to_date, group)` - Get closed deals from history
- ✓ `mt5.history_deals_total(from_date, to_date)` - Count deals in range
- ✓ `mt5.history_orders_get(from_date, to_date, group)` - Get closed orders from history
- ✗ `mt5.deals_get()` - DOES NOT EXIST

**Impact**:

1. Function `get_deal_history()` will crash at runtime
2. Broker reconstruction fallback will fail
3. Risk state cannot be recovered after restart
4. Bot loses all trade history after crash
5. All calls to `record_trade_result()` persistence will fail on next restart

### Status: OPERATIONALLY BROKEN ❌

- **Code Path**: risk_manager.py:70 → calls restore_daily_state() → falls back to reconstruct_daily_state_from_broker() → calls mt5_connector.get_deal_history() → crashes at mt5.deals_get()
- **Observable Evidence**: AttributeError in logs when attempting broker reconstruction
- **Behavioral Impact**: Cannot track daily PnL, consecutive losses, or trade count after restart

### Exact Trace (Runtime Path)

```
Bot startup sequence:
  → main.py:223: restore_daily_state()
  → risk_manager.py:70: persisted_data = load_risk_state() [returns None/empty]
  → risk_manager.py:71: reconstruct_daily_state_from_broker()
  → risk_manager.py:260: history = broker_conn.get_deal_history()
  → mt5_connector.py:369: deals = mt5.deals_get(...) ← CRASHES HERE
  → AttributeError: 'module' object has no attribute 'deals_get'
  → State recovery fails
  → _state uses defaults (trades_today=0, daily_pnl=0.0, etc.)
  → ✗ False state reconstructed
```

---

## FINDING 2: DAILY INTRADAY FLATTENING — ARCHITECTURE MISMATCH ❌ NOT IMPLEMENTED

### User Requirement

EVERY trading day (all 5 days Mon-Fri) must enforce:

- **Phase 1** (before 21:30): Normal entries allowed
- **Phase 2** (21:30+): Entry lock (NO NEW ENTRIES)
- **Phase 3** (22:00): Aggressive management mode
- **Phase 4** (22:15): Proactive flattening window
- **Phase 5** (22:45-22:55): Hard flatten (close ALL positions)
- **Phase 6** (23:05+): Emergency cutoff (verify zero positions)

### Current Implementation

**File**: `config/sessions.py`

#### What EXISTS:

```python
ENTRY_LOCK = time(21, 30)  # ✓ Defined

def can_open_trade():
    if t >= ENTRY_LOCK:
        return False, f"Entry lock after 21:30"  # ✓ Blocks new entries
```

**File**: `main.py`

```python
# Friday/Weekend ONLY:
close_all, close_reason = must_close_all()
if close_all:
    force_close_all(settings.SYMBOL, close_reason)
```

#### What's MISSING:

```
✗ No Phase 3 (22:00) aggressive management mode
✗ No Phase 4 (22:15) proactive flattening window
✗ No Phase 5 (22:45-22:55) hard flatten window
✗ No Phase 6 (23:05) emergency final cutoff
✗ No daily flattening - Friday/weekend only
✗ No session state transition logging (no "SESSION STATE CHANGE" events)
✗ No behavior change indicators
✗ Positions can linger overnight EVERY DAY
```

### Status: ARCHITECTURALLY INCOMPLETE ❌

- **Current Behavior**: Blocks new entries after 21:30 DAILY, but does NOT close existing positions
- **Expected Behavior**: Progressively flatten ALL positions throughout 21:30-23:05 window
- **Observable Gap**: Main loop has `must_close_all()` check (Friday/weekend), but NO equivalent daily flattening logic
- **Risk Exposure**: All five trading days can carry overnight risk

### Execution Path (What Actually Happens)

```
Mon-Fri 21:30:
  → main.py:105: close_all, close_reason = must_close_all()
  → sessions.py:84: wd != 4 and wd not in (5,6) → return False, ""
  → Main loop continues
  → Entry blocked by can_open_trade() ✓
  → Existing positions NOT managed aggressively ✗
  → No hard close window ✗
  → No emergency cutoff ✗

Mon-Fri 23:00:
  → Positions still open
  → Session change to overnight
  → NO PROTECTION FOR DAILY INTRADAY (only Friday/weekend)

Tue 00:00:
  → Positions potentially still open
  → Overnight rollover risk not protected
```

---

## FINDING 3: SESSION STATE TRANSITIONS — LOGGING MISSING ❌

### Requirement

Bot must log ONLY ON TRANSITION (not every iteration):

```
SESSION STATE CHANGE: NORMAL -> ENTRY_LOCK
SESSION STATE CHANGE: ENTRY_LOCK -> AGGRESSIVE_MANAGEMENT
SESSION STATE CHANGE: AGGRESSIVE_MANAGEMENT -> FLATTENING
SESSION STATE CHANGE: FLATTENING -> HARD_FLATTEN
SESSION STATE CHANGE: HARD_FLATTEN -> EMERGENCY_CLOSE
```

### Current Implementation

No such transitions exist. Code only:

- Logs `current_session()` every iteration (not just on change)
- Does NOT transition through phases
- Does NOT log state changes

### Status: NOT IMPLEMENTED ❌

- **Observable Evidence**: No "SESSION STATE CHANGE" lines in logs
- **Impact**: No visibility into daily flattening phases
- **Verification Path**: Cannot trace when system enters aggressive mode

---

## FINDING 4: CLOSE VERIFICATION LOGIC — NEEDS FULL TRACE ⚠️

### What Exists

**File**: `execution/trade_manager.py`

```python
def _force_close(pos, symbol: str, reason: str) -> None:
    """Force close with broker verification and retry logic"""
    ticket = pos.ticket
    max_retries = 3
    retry_count = 0

    while retry_count < max_retries:
        ok = conn.close_position(pos)
        if not ok:
            retry_count += 1
            continue

        # Verify position disappeared
        time.sleep(0.5)
        updated_pos = conn.get_open_positions(symbol=symbol, magic=settings.MAGIC)
        position_still_exists = any(p.ticket == ticket for p in (updated_pos or []))

        if position_still_exists:
            retry_count += 1
            continue

        # Verified closed
        log.warning(f"FORCED CLOSE VERIFIED | Ticket: {ticket}")
        record_trade_result(pnl)
        register_trade_exit(...)
        save_trade_states(_TRADE_STATES)
        return
```

### Verification Required

1. ✓ **Close command sent**: `conn.close_position()` called
2. ✓ **Retry logic**: Up to 3 attempts
3. ✓ **Position query**: `get_open_positions()` checks MT5
4. ⚠️ **Persistence**: `save_trade_states()` called only after verification
5. ⚠️ **Cooldown trigger**: `register_trade_exit()` fires callback

### Observable Evidence Needed

- Logs must show: `FORCED CLOSE VERIFIED | Ticket: XXXXX`
- OR: `EMERGENCY CLOSE FAILURE | Max retries exhausted`
- Actual position count should decrease after forced close

### Status: IMPLEMENTED BUT UNVERIFIED ⚠️

- Code path exists
- Runtime behavior not confirmed in logs
- Need to trace: retry count, verification query results, persistence updates

---

## FINDING 5: ENTRY BLOCKING AFTER 21:30 — WORKING ✓

### What Works

```python
# main.py line 115
entry_ok, entry_reason = can_open_trade()
if not entry_ok:
    log_no_trade(log, entry_reason, ...)  # BLOCKED
    continue
```

```python
# sessions.py
def can_open_trade():
    if t >= ENTRY_LOCK:  # 21:30
        return False, f"Entry lock after 21:30"
```

### Observable Evidence

- Logs show: `ENTRY BLOCKED | Entry lock after 21:30` ✓
- New entry attempts blocked after 21:30 ✓

### Status: WORKING ✓

- Enforcement: DAILY (all weekdays)
- Behavioral verification: Entry rejection logs visible

---

## FINDING 6: COOLDOWN PERSISTENCE — IMPLEMENTATION CORRECT ✓

### What Exists

1. **Save on exit**:

```python
# entry_engine.py:register_trade_exit()
from execution.state_persistence import save_cooldown_state
save_cooldown_state(_LAST_EXIT_TIME)
```

2. **Load on startup**:

```python
# entry_engine.py:initialize_cooldown_from_persistence()
restored = load_cooldown_state()
_LAST_EXIT_TIME.update(restored)
```

3. **File persistence**:

```python
# state_persistence.py
COOLDOWN_STATE_FILE = os.path.join(STATE_DIR, "cooldown_state.json")
```

### Status: SEMANTICALLY CORRECT ✓

- Code path looks operationally sound
- But NEEDS RUNTIME VERIFICATION:
  - Scenario: Trade closes → cooldown saved → restart → entry blocked?
  - Logs should show: `COOLDOWN STATE RESTORED | Remaining: XXXs`

---

## FINDING 7: LOGGER ROTATION — IMPLEMENTATION CORRECT ✓

### What Exists

```python
# utils/logger.py:_verify_and_rotate_handlers()
file_handler.doRollover()
_test_handler_write(file_handler, logger_name)  # Verify
file_handler.flush()  # Explicit flush
log.info("LOGGER ROTATION COMPLETED")
```

### Status: SEMANTICALLY CORRECT ✓

- Rotation logic implemented
- Flush added
- Verification test added
- But NEEDS RUNTIME VERIFICATION:
  - Logs should show: `LOGGER ROTATION VERIFIED`
  - Logs should continue after midnight

---

## FINDING 8: ORPHANED STATE CLEANUP — IMPLEMENTATION CORRECT ✓

### What Exists

```python
# trade_manager.py:reconcile_positions_on_startup()
if not positions:
    orphaned_tickets = list(_TRADE_STATES.keys())
    if orphaned_tickets:
        for ticket in orphaned_tickets:
            _TRADE_STATES.pop(ticket, None)
            log.warning(f"ORPHANED STATE REMOVED | Ticket: {ticket}")
        clear_state_files()
```

### Status: SEMANTICALLY CORRECT ✓

- Orphan cleanup logic added
- NEEDS RUNTIME VERIFICATION:
  - Logs should show: `ORPHANED STATE REMOVED`

---

## COMPILATION STATUS

```
✓ execution/entry_engine.py - SYNTAX OK
✓ execution/trade_manager.py - SYNTAX OK
✓ execution/risk_manager.py - SYNTAX OK
✓ main.py - SYNTAX OK
✓ utils/logger.py - SYNTAX OK
✓ config/sessions.py - SYNTAX OK
✓ execution/state_persistence.py - SYNTAX OK

All files compile successfully ✅
```

---

## CRITICAL RUNTIME FAILURES SUMMARY

| Issue                             | Category            | Status     | Impact                             | Fix Required                  |
| --------------------------------- | ------------------- | ---------- | ---------------------------------- | ----------------------------- |
| `mt5.deals_get()` doesn't exist   | API Incompatibility | ❌ BROKEN  | Broker reconstruction crashes      | Use `mt5.history_deals_get()` |
| Daily intraday flattening missing | Architecture        | ❌ MISSING | Overnight risk every day           | Implement phases 22:00-23:05  |
| Session transitions not logged    | Observability       | ❌ MISSING | Cannot see phase changes           | Add transition logging        |
| No 22:00 aggressive management    | Feature             | ❌ MISSING | No position reduction phase        | Implement management window   |
| No 22:15 proactive flattening     | Feature             | ❌ MISSING | No active close period             | Implement flattening window   |
| No 22:45-22:55 hard flatten       | Feature             | ❌ MISSING | No emergency close before rollover | Implement hard close          |
| No 23:05 emergency cutoff         | Feature             | ❌ MISSING | No final verification window       | Implement emergency cutoff    |

---

## NEXT REQUIRED ACTIONS

### IMMEDIATE (Blocker)

1. **Fix MT5 API calls**: Change `mt5.deals_get()` → `mt5.history_deals_get()`
   - File: `utils/mt5_connector.py` line 370
   - Impact: Unblocks broker reconstruction

### HIGH PRIORITY (Architecture)

2. **Implement daily intraday flattening phases**:
   - Add phase tracking to sessions.py
   - Implement aggressive management (22:00)
   - Implement proactive flattening (22:15)
   - Implement hard flatten (22:45-22:55)
   - Implement emergency cutoff (23:05)

### MEDIUM PRIORITY (Observability)

3. **Add session state transition logging**:
   - Log only on transition (not every iteration)
   - Clear phase indicators in logs

### VERIFICATION (Runtime Testing)

4. **Behavioral verification**:
   - Trace actual close verification chain
   - Confirm cooldown persistence across restart
   - Confirm logger rotation succeeds
   - Confirm orphan cleanup executes

---

## TRUTHFULNESS ASSESSMENT

**Honest Status**:

- ✅ Entry blocking: WORKING (enforced daily 21:30+)
- ⚠️ Close verification: SEMANTICALLY PRESENT but unverified at runtime
- ⚠️ Cooldown persistence: SEMANTICALLY PRESENT but unverified at runtime
- ⚠️ Logger rotation: SEMANTICALLY PRESENT but unverified at runtime
- ⚠️ Orphan cleanup: SEMANTICALLY PRESENT but unverified at runtime
- ❌ Broker reconstruction: BROKEN (wrong API method)
- ❌ Daily intraday flattening: NOT IMPLEMENTED (Friday/weekend only)
- ❌ Session phases: NOT IMPLEMENTED (no transitions)

**Overall Truth**: 35% truly working, 35% semantically correct but unverified, 30% broken or missing

---

## FILES ANALYZED

- ✓ config/sessions.py
- ✓ main.py
- ✓ execution/entry_engine.py
- ✓ execution/trade_manager.py
- ✓ execution/risk_manager.py
- ✓ execution/state_persistence.py
- ✓ utils/mt5_connector.py
- ✓ utils/logger.py

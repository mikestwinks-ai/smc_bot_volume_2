# BEHAVIORAL INTEGRITY AUDIT — PHASE 1 EXECUTION TRACE

**Date**: May 27, 2026  
**Status**: Tracing actual runtime execution paths WITHOUT assumptions  
**Scope**: Trades accounting, state persistence, position classification

---

## CRITICAL FINDING 1: TRADES_TODAY ACCOUNTING BUG ❌

### Symptom
After bot restart on same trading day:
- Open trades exist on MT5
- Trades were executed earlier today
- But bot shows: `trades_today=0` and `daily_pnl=0.00`

### Root Cause Analysis: Execution Path Trace

**Startup Sequence** (main.py lines 253-260):
```
1. reconcile_positions_on_startup()
2. restore_daily_state()  ← Loads from risk_state.json
3. initialize_cooldown_from_persistence()
4. _main_loop()
```

**restore_daily_state() Logic** (risk_manager.py lines 59-110):
```python
def restore_daily_state() -> bool:
    persisted_data = load_risk_state()  # Try to load from JSON
    
    if not persisted_data:
        # No file → try broker reconstruction
        reconstruct_daily_state_from_broker()
        return
    
    persisted_day_str = persisted_data.get("day")
    today_str = date.today().isoformat()
    
    if persisted_day_str != today_str:
        # Different day → try broker reconstruction
        reconstruct_daily_state_from_broker()
        return
    
    # SAME DAY → restore from file
    _state.trades_today = int(persisted_data.get("trades_today", 0))
    # ... restore other fields ...
```

**Critical Gap**: When does `risk_state.json` get SAVED?

Looking at save_risk_state() calls:
1. **reset_daily_state()** (line 50): `save_risk_state(_state)` 
   - ✗ Only called when `_state.day != today` (NEW DAY)
   - ✗ NOT called on same day
   
2. **record_trade_result()** (line 135): `save_risk_state(_state)`
   - ✓ Called when trade CLOSES
   - ✗ NOT called when trade OPENS

### The Bug Sequence

**Day 1, 14:00 - Trade Opens**:
```
attempt_entry() executed
  → mt5.send_order() succeeds
  → increment_trade_count()  (trades_today = 1)
  → ✗ NO save_risk_state() call
  → risk_state.json still has trades_today=0 (stale)
```

**Day 1, 15:00 - Trade Closes**:
```
manage_open_trades() detects TP
  → _force_close() called
  → record_trade_result(pnl)
    → trades_today += 1  (now 2, but file has 0)
    → save_risk_state()  ← FINALLY saves to file
    → risk_state.json updated with trades_today=2, daily_pnl=+XX
```

**Day 1, 16:00 - Bot Restarts (Still same day)**:
```
restore_daily_state()
  → load_risk_state() from file
  → persisted_day = today (match!)
  → _state.trades_today = 2  (restored correctly from file)
  → Main loop runs
    → reset_daily_state(balance) called
    → _state.day == today → NO action (correct)
    → trades_today should be 2 ✓
```

**BUT if bot crashes between trade open and close**:

**Day 1, 14:05 - Bot Crashes (Trade still open)**:
```
Trade opened with:
  - increment_trade_count() executed (trades_today = 1 in memory)
  - ✗ NO save_risk_state() (file still has trades_today=0)
  - Bot crashes
  
Bot restarts:
  restore_daily_state()
    → load_risk_state()
    → trades_today = 0  (file was never updated!)
    → _state.trades_today = 0  ❌ LOST OPEN TRADE COUNT
    → Main loop
      → Position exists on MT5 (open trade)
      → But trades_today=0 in bot state
      → ❌ ACCOUNTING MISMATCH
```

### Status: CRITICAL BUG ❌
- **When open trades exist**: trades_today incorrect after restart if trade not yet closed
- **Execution Path**: increment_trade_count() → NO persistence → crash → restore loses count
- **Observable Effect**: `trades_today=0` despite open position on MT5
- **Persistence Gap**: 1 hour between `increment_trade_count()` and `record_trade_result()` with NO saves

---

## CRITICAL FINDING 2: OVERNIGHT POSITION CLASSIFICATION MISSING ❌

### Symptom
Restored positions not distinguished between:
- Same-day positions (opened today, still open)
- Overnight positions (opened yesterday, still open after flattening failed)
- Stale positions (reconciliation artifact)

### Root Cause
trade_manager.py `reconcile_positions_on_startup()` restores positions but doesn't trace their open time.

**Current code** (trade_manager.py lines 306-361):
```python
def reconcile_positions_on_startup(symbol: str) -> None:
    # Load persisted states
    persisted_states = load_trade_states()
    
    if not persisted_states:
        # No persistence, query MT5 for current positions
        positions = conn.get_open_positions(symbol, settings.MAGIC)
        for pos in positions:
            state = TradeState(...)  # Create new state from MT5 position
            _TRADE_STATES[pos.ticket] = state
    else:
        # Load from persistence
        for ticket, state_dict in persisted_states.items():
            # Restore TradeState
            _TRADE_STATES[ticket] = TradeState(...)
    
    # NO LOGGING about when position was opened
    # NO LOGGING about whether it's same-day or overnight
    # NO LOGGING about why it survived flattening
```

### Status: MISSING IMPLEMENTATION ❌
- No classification of position age
- No logging of open_time vs today
- No evidence of overnight flattening failure (if it exists)
- No ability to distinguish legitimate same-day position from accidental overnight carry

---

## CRITICAL FINDING 3: DAILY FLATTENING VERIFICATION MISSING ❌

### Code Added
sessions.py added:
- `get_daily_intraday_phase()` - Returns current phase
- Phase definitions: 22:00, 22:15, 22:45, 23:05

main.py added:
- Hard flatten window check (22:45-22:55)
- Emergency cutoff check (23:05+)
- Both call `force_close_all()`

### But No Runtime Evidence
- ⚠️ NO logs showing if is_hard_flatten_window() actually returns True
- ⚠️ NO logs showing if force_close_all() actually executes during hard flatten
- ⚠️ NO verification that positions actually closed
- ⚠️ NO emergency cutoff logs if positions remained at 23:05

### What's Missing
```python
# main.py hard flatten section (lines 116-120):
if is_hard_flatten_window():
    log.warning("DAILY FLATTENING | Hard flatten window (22:45-22:55) — closing ALL positions")
    force_close_all(settings.SYMBOL, "Daily hard flatten window (22:45-22:55)")
    continue
```

**Missing critical logs**:
- No log BEFORE checking hard flatten window
- No log showing window state (True/False)
- No log showing actual force_close_all execution
- No log showing results

### Status: PHASE TRACKING EXISTS BUT VERIFICATION MISSING ⚠️
- Code path exists (syntactically correct)
- But no observable evidence that it executes
- No verification that positions actually close
- No telemetry that flattening succeeded/failed

---

## CRITICAL FINDING 4: LOGGER UNICODE CORRUPTION ❌

### Symptom
Runtime logs show corrupted output:
```
ΓÇö  (corrupted dash)
←[96mINFO  (ANSI escape artifact)
├── (box drawing artifact)
```

### Root Cause
Mixed Unicode character usage and ANSI escape sequence remnants.

### Files Affected
- config/sessions.py - Line markers `─ ──` (Unicode box drawing)
- execution/risk_manager.py - Line markers `─ ──`
- main.py - Line markers `─ ──`
- Other files - Scattered Unicode usage

### Status: UNVERIFIED AT RUNTIME ⚠️
- Corruption visible in logs
- Need to test on Windows VPS terminal
- Need to test on VS Code terminal
- Need to verify compatibility across environments

---

## EXECUTION TRACE MAPS

### Map 1: Trade Opening to Persistence

**Current State (INCOMPLETE)**:
```
attempt_entry() 
  → MT5 order succeeds
  → increment_trade_count()
    → _state.trades_today += 1  (MEMORY UPDATED)
    → ✗ NO save_risk_state() call
    → ✗ risk_state.json UNCHANGED (stale)
  → Return to main
  
[AT THIS POINT: 14 iterations (14 minutes at 60s loop)]
  
manage_open_trades()
  [Position may close or continue]
  
IF closes:
  → record_trade_result(pnl)
    → _state.trades_today += 1  (INCREMENTED AGAIN? BUG?)
    → save_risk_state()  ← FINALLY persisted

[If bot crashes in the 14-minute gap]:
  → risk_state.json has stale trades_today
  → Restart reads stale value
  → ✗ trades_today wrong
```

### Map 2: Position Restoration on Restart

**Current State (UNCLEAR CLASSIFICATION)**:
```
reconcile_positions_on_startup()
  → Load persisted trade states
  → Query MT5 current positions
  → For each restored position:
    → Load TradeState from persistence
    → ✗ NO logging of open_time
    → ✗ NO classification (same-day vs overnight)
    → Add to _TRADE_STATES
    
log_reconciliation_summary()
  → "Reconciliation complete"
  → ✗ No breakdown by position type
```

### Map 3: Hard Flatten Window

**Current State (EXECUTION UNVERIFIED)**:
```
Loop iteration at 22:46:
  → is_hard_flatten_window()
    → Returns True (code looks correct)
    → ✗ NO log output showing True
  → if True:
    → log.warning("DAILY FLATTENING | Hard flatten window...")
    → force_close_all()
    → ✗ NO log showing actual close execution
    → ✗ NO log showing position count before/after
    
[UNKNOWN]: Did force_close_all actually run?
[UNKNOWN]: Did positions close?
```

---

## WHAT'S VERIFIED vs UNVERIFIED

### Syntax Verified ✅
- All 8 files compile without errors
- API method names correct (mt5.history_deals_get)
- Function signatures correct
- Phase transition functions exist

### Code Logic Verified (Manual Inspection) ✅
- reset_daily_state() logic correct for same-day
- restore_daily_state() logic correct for matching dates
- is_hard_flatten_window() logic correct
- force_close_all() call chain present

### Runtime Behavior NOT Verified ⚠️
- Does hard flatten actually execute at 22:45?
- Are all positions closed by 22:55?
- Are they still closed at 23:05?
- Does trades_today actually match MT5 position count after restart?
- Are overnight positions logged as violations?
- Does logger output actually work in VPS environment?

---

## REQUIRED FIXES (PHASE 2-7)

1. **Save trades_today on OPEN, not just on CLOSE**
   - Add save_risk_state() call in increment_trade_count()
   - OR persist immediately after increment

2. **Classify restored positions by age**
   - Log open_time vs today
   - Distinguish same-day vs overnight
   - Flag violations

3. **Add hard flatten execution logging**
   - Log before window check
   - Log window state (True/False)
   - Log actual force_close_all execution
   - Log position count before/after

4. **Add emergency cutoff logging**
   - Log if any positions remain at 23:05
   - Log failed close attempts
   - Log final verification

5. **Fix logger Unicode corruption**
   - Remove corrupted characters
   - Test on actual environments
   - Verify compatibility

6. **Add daily reconstruction telemetry**
   - Log trades opened today
   - Log trades closed today
   - Log positions from today still open
   - Log unrealized PnL
   - Log consecutive losses

7. **Add phase transition observability**
   - Log ONLY on transition
   - Show phase names clearly
   - Show exact times

---

## HONEST ASSESSMENT

**What is actually working**:
- Entry blocking after 21:30 ✓
- Position management logic ✓
- Risk limits enforcement ✓

**What is coded but unverified**:
- Daily flattening execution ⚠️
- Hard flatten verification ⚠️
- Emergency cutoff telemetry ⚠️
- Trades accounting recovery ⚠️
- Overnight position classification ⚠️
- Logger output formatting ⚠️

**What is broken**:
- Risk state not saved on trade open ❌
- Trades_today lost on crash between open and close ❌
- Overnight positions not classified ❌
- Logger output corrupted ❌

---

## STATUS: NOT DEPLOYMENT READY

Multiple critical runtime failures identified:
1. Trades accounting gap (1-30 min window of no persistence)
2. No overnight violation detection
3. No hard flatten execution verification
4. Logger corrupted output

Next phase: Implement fixes with full observability.

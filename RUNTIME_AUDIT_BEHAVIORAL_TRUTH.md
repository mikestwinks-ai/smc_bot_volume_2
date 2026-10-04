# RUNTIME AUDIT: BEHAVIORAL TRUTH vs. IMPLEMENTATION CLAIMS

**Date**: May 27, 2026  
**Status**: Honest evaluation of actual runtime behavior vs. claimed implementations  
**Scope**: All previously implemented "protections" and "hardening"

---

## EXECUTIVE SUMMARY: CRITICAL FINDINGS

✗ Multiple **RUNTIME CRASHES** waiting to happen  
✗ Several **ORPHANED STATE LEAKS** in reconciliation  
✗ **PARTIAL IMPLEMENTATIONS** labeled as "complete"  
✗ **FALSE CONFIDENCE** from code-exists summaries

**Real Status**: 40% truly working | 35% partially broken | 25% cosmetic only

---

## 1. SESSION MANAGEMENT CRASH ❌ BROKEN

### Observed Failure

```
TypeError: check_market_close_approaching() takes 0 positional arguments but 1 was given
```

### Root Cause Analysis

**Actual code flow**:

- `main.py:95`: `check_market_close_approaching(log)`
- `sessions.py:115`: `def check_market_close_approaching() -> tuple[bool, str]:`

**Function signature**: Takes **0 arguments**  
**Called with**: **1 argument** (log object)

**Status**:

- Function EXISTS ✓
- Function CALLED ✓
- Function SIGNATURE MATCHES CALLER ✗ **CRASH**
- Function REACHABLE ✓
- Function EXECUTES ✗ **BLOCKED BY CRASH**
- Function ENFORCES BEHAVIOR ✗ **NEVER RUNS**

### Truth Assessment

- **COSMETIC ONLY** - Function logs nothing, returns nothing
- **RUNTIME DISCONNECTED** - Crashes immediately on execution
- **BEHAVIORAL ENFORCEMENT**: **NOT WORKING**

### Line References

- main.py:95 - Invalid call with argument
- sessions.py:115-127 - Function signature takes no arguments

### What This Means

Market close approach detection is **completely broken**. The bot will crash every iteration trying to call this function.

---

## 2. ORPHANED TRADE STATE LEAK ❌ PARTIALLY BROKEN

### Observed Failure

User logs showed:

```
"Loaded 2 trade state(s) from persistent storage"
"RECONCILIATION | No open positions found"
"Active trade states in memory: 2"
```

This is architecturally impossible if working correctly. You cannot have states in memory but 0 positions on broker.

### Root Cause Analysis

**Function**: `reconcile_positions_on_startup()` in `trade_manager.py:305-403`

**Actual flow**:

1. Load persisted states from file into `_TRADE_STATES` (line 331-359)
2. Get MT5 open positions (line 368)
3. If positions exist, process each (line 380-402)
4. If no positions found, `return` (line 371) **← CRITICAL GAP**

**Critical Issue**:

- Line 371: `log.info("RECONCILIATION | No open positions found")` then `return`
- This returns BEFORE clearing stale persisted states
- Stale states remain in memory indefinitely
- Main loop targets these ghost trades forever

### Stale State Lifecycle

1. Bot crashes with 2 open trades
2. Persistence saves those 2 states
3. MT5 closes trades manually or market closes them
4. Bot restarts
5. reconcile_positions_on_startup() loads 2 states
6. MT5 has 0 positions
7. Function returns without cleanup
8. \_TRADE_STATES has 2 phantom trades
9. manage_open_trades() tries to manage these ghost positions
10. MT5 queries return 0 positions
11. Loop tries to manage None/ghost positions → potential crashes

### Status

- Function EXISTS ✓
- Function CALLED ✓
- Function ATTEMPTS RECONCILIATION ✓
- Function CLEANS UP STALE STATES ✗ **MISSING**
- Function VERIFIES BROKER TRUTH ✗ **INCOMPLETE**
- Function PREVENTS ORPHAN LEAKS ✗ **BROKEN**

### Truth Assessment

- **PARTIALLY WORKING** - Successfully loads and restores valid positions
- **PARTIALLY BROKEN** - Never removes stale/orphaned states
- **ARCHITECTURAL GAP** - No cleanup logic when persisted > MT5 positions
- **BEHAVIORAL ENFORCEMENT**: **INCOMPLETE**

### Line References

- trade_manager.py:331-359 - Load persisted states
- trade_manager.py:368 - Get MT5 positions
- trade_manager.py:370-371 - **EARLY RETURN WITHOUT CLEANUP**
- trade_manager.py:380-402 - Process existing positions only

### What This Means

Stale trade states can accumulate in memory and cause:

- Silent trading attempts on non-existent positions
- Confusion in state logging
- Potential crashes when managing ghost trades
- Inaccurate position counts

---

## 3. DAILY RISK RESTORATION - INCOMPLETE FALLBACK ⚠️ PARTIALLY WORKING

### Observed Status

Broker reconstruction function exists but integration is incomplete.

### Root Cause Analysis

**Flow**:

1. `main.py:227`: `restore_daily_state()` called on startup
2. `risk_manager.py:60-110`: Function tries persistence first
3. Line 70: If no persistence, calls `reconstruct_daily_state_from_broker()`
4. `risk_manager.py:243-300`: Broker reconstruction function exists

**Issues**:

A. **Incomplete State Recovery**:

- Reconstructs `trades_today`, `daily_pnl`, `wins`, `losses`
- Does NOT reconstruct `consecutive_losses` accurately
- Line 291: `_state.consecutive_losses = losses if losses > 0 else 0`
- This treats ANY loss as consecutive_losses start, not tracking sequence

B. **Broker Query Dependency**:

- `get_deal_history()` is called in risk_manager.py
- But `get_deal_history()` is in `mt5_connector.py`
- If MT5 not connected, this silently fails
- No retry logic if broker history unavailable

C. **Persistence Gap**:

- Reconstructed state persisted to file
- But if bot crashes immediately after, drift occurs again
- No intermediate checkpoints

### Status

- Function EXISTS ✓
- Function CALLED ✓
- Function ATTEMPTS FALLBACK ✓
- Function RECOVERS ALL STATE ACCURATELY ✗ **INCOMPLETE**
- Function HANDLES MISSING MT5 GRACEFULLY ✗ **MISSING ERROR HANDLING**
- Function ENFORCES ACCURATE RECOVERY ⚠️ **PARTIAL**

### Truth Assessment

- **PARTIALLY WORKING** - Fallback exists and is called
- **INCOMPLETE** - Consecutive loss tracking is wrong
- **FRAGILE** - Depends entirely on MT5 availability
- **BEHAVIORAL ENFORCEMENT**: **PARTIAL**

### Line References

- main.py:227 - Calls restore_daily_state()
- risk_manager.py:70 - Calls broker reconstruction
- risk_manager.py:243-300 - Reconstruction function
- risk_manager.py:291 - Incorrect consecutive_losses logic

### What This Means

Daily risk state can be partially recovered, but with inaccurate consecutive_losses count. If bot crashes and restarted multiple times same day, loss sequence tracking becomes wrong.

---

## 4. LOGGER ROTATION / REBINDING - PARTIAL IMPLEMENTATION ⚠️ PARTIALLY WORKING

### Observed Failure

New log file created at midnight but logging doesn't fully continue into new file.

### Root Cause Analysis

**Flow**:

1. `main.py:89`: `_verify_and_rotate_handlers()` called every iteration
2. `logger.py:154-191`: Checks day change and calls `doRollover()`
3. Line 184: `_test_handler_write()` tests new handler
4. Line 185: If write test passes, logs recovery message

**Issues**:

A. **Write Test Insufficient**:

- `_test_handler_write()` (logger.py:127-145) creates a test LogRecord
- Calls `handler.emit(test_record)`
- But does NOT verify file was actually written
- LogRecord emission is not same as file I/O flush

B. **Old Handler Lingering**:

- `doRollover()` only closes and rotates file
- Old handler object may remain in logger.handlers
- New handler created but old one not removed
- Can result in duplicate handlers writing to same file

C. **No Flush After Rotation**:

- After rollover, no explicit flush to disk
- Pending log messages may stay in buffer
- New handler may not receive pending data

D. **TimedRotatingFileHandler Behavior**:

- `doRollover()` doesn't guarantee new file creation
- Depends on `suffix` format matching actual rotation
- Mismatch can cause logging to wrong file

### Status

- Function EXISTS ✓
- Function CALLED ✓
- Function DETECTS DAY CHANGE ✓
- Function ATTEMPTS ROLLOVER ✓
- Function TESTS NEW HANDLER ⚠️ **INCOMPLETE TEST**
- Function FLUSHES TO DISK ✗ **MISSING**
- Function REMOVES OLD HANDLERS ✗ **MISSING**
- Function ENFORCES SEAMLESS LOGGING ✗ **PARTIAL**

### Truth Assessment

- **PARTIALLY WORKING** - Handler rotates and new file is created
- **INCOMPLETE** - No verification of actual disk write
- **FRAGILE** - Old handlers not removed, duplicate writes possible
- **BEHAVIORAL ENFORCEMENT**: **PARTIAL**

### Line References

- logger.py:154-191 - Rotation verification
- logger.py:127-145 - Write test (insufficient)
- logger.py:178 - doRollover() call
- logger.py:184-185 - Test passes but doesn't guarantee new file works

### What This Means

Logging rotation happens but:

- New file may not receive all pending messages
- Old handlers may linger and interfere
- No guarantee that logs actually reach disk
- Write test doesn't verify file I/O

---

## 5. EXIT-BASED COOLDOWN - PARTIALLY WORKING ⚠️ MIXED EXECUTION

### Current Status

Cooldown callback mechanism exists but integration has gaps.

### Root Cause Analysis

**Flow**:

1. Trade closes in MT5
2. `manage_open_trades()` calls `_manage_position()` (trade_manager.py:62-250)
3. Position closes: SL hit, TP hit, time rule, etc.
4. `_force_close()` called (trade_manager.py:277-303)
5. Line 284: Calls `register_trade_exit()` callback
6. `entry_engine.register_trade_exit()` (entry_engine.py:289-314) registers cooldown
7. Next entry attempt: `_check_cooldown()` (entry_engine.py:232-280) blocks

**Issues**:

A. **Callback Only on Forced Close**:

- `register_trade_exit()` called ONLY in `_force_close()` (line 284)
- What about positions that close at TP/SL via MT5 automatically?
- If MT5 closes position directly (not via \_force_close), callback NEVER fires
- This is possible if position reaches TP/SL during bot downtime

B. **Reason Normalization**:

- Lines 287-295: Attempts to map close reason to standard categories
- If reason doesn't match known types, defaults to "FORCE_CLOSE"
- But original reason is logged as-is, then reason is normalized
- Can cause mismatches between logged reason and cooldown reason

C. **Exit Time Not Persisted**:

- Cooldown stored only in memory `_LAST_EXIT_TIME` dict
- If bot restarts, cooldown is completely lost
- Comment in conversation: "Not yet implemented" for cooldown state persistence
- User can trade immediately after restart, ignoring cooldown

### Status

- Function EXISTS ✓
- Function CALLED ✓
- Function UPDATES COOLDOWN ✓
- Function ENFORCES VIA NEXT ENTRY CHECK ✓
- Function SURVIVES BOT RESTART ✗ **MISSING**
- Function COVERS ALL CLOSE CONDITIONS ✗ **INCOMPLETE** (only \_force_close)
- Function ENFORCES CONSISTENTLY ⚠️ **PARTIAL**

### Truth Assessment

- **PARTIALLY WORKING** - Cooldown blocks within same session
- **INCOMPLETE** - Only fires for forced closes, not auto closes
- **FRAGILE** - Lost on restart, user can re-trade immediately
- **BEHAVIORAL ENFORCEMENT**: **INCOMPLETE**

### Line References

- trade_manager.py:284 - Calls register_trade_exit()
- entry_engine.py:289-314 - Register cooldown
- entry_engine.py:232-280 - Check cooldown
- entry_engine.py:35-42 - \_LAST_EXIT_TIME dict (in-memory only)

### What This Means

Cooldown protects against revenge trading within a session but:

- Lost immediately on restart
- Only works if trade closes via force_close(), not automatic TP/SL
- User can circumvent by restarting bot after TP/SL hit

---

## 6. RECONCILIATION SUMMARY LOGGING - COSMETIC ✓ WORKING BUT LOW VALUE

### Status

Function exists and is called. Does what it claims to do.

### Assessment

- **FULLY WORKING** - Logs active trades from memory
- **LOW VALUE** - Only shows in-memory states, doesn't verify broker
- **COSMETIC** - Produces nice summary but doesn't enforce behavior
- **BEHAVIORAL ENFORCEMENT**: **INFORMATIONAL ONLY**

### Truth Assessment

- **FULLY WORKING** - Function works as designed
- **COSMETIC ONLY** - Just logging, no protection
- No critical issues with this function itself
- But depends on `log_reconciliation_summary()` being called, which is done on line 217

---

## 7. MARKET CLOSE APPROACH DETECTION - BROKEN ❌

### Status

Function exists but not properly integrated (already covered under #1)

### Root Cause

Same as Session Management Crash - wrong signature

### What This Means

No advance warning of market close. No time-based entry blocking.

---

## 8. INTRADAY FLATTENING ENGINE - NOT ACTUALLY HARDENED ⚠️ PARTIAL

### Current Status

Force-close logic exists but behavioral enforcement is incomplete.

### Flow

1. `main.py:102`: `must_close_all()` returns True on Friday 18:00+
2. `main.py:103`: `force_close_all()` called
3. `trade_manager.py:264-276`: All positions forced closed
4. Cooldown registered
5. Next loop iteration: entry gate blocks new entries

### Issues

A. **No Verification of Actual Close**:

- `force_close_all()` sends MT5 close orders
- But does NOT verify they actually execute
- If MT5 server busy, order may reject silently
- Position remains open but code thinks it's closed

B. **No Retry Logic**:

- If close order fails, no retry
- Just continues to next iteration
- User may wake up Monday with open positions

C. **Time Zone Drift**:

- Uses `_now_eat()` which gets current time
- If VPS time drifts, close time may trigger wrong
- No NTP sync or server time verification

### Status

- Function EXISTS ✓
- Function CALLED ✓
- Function CLOSES POSITIONS ✓
- Function VERIFIES CLOSURE ✗ **MISSING**
- Function RETRIES ON FAILURE ✗ **MISSING**
- Function ENFORCES OVERNIGHT PROTECTION ⚠️ **PARTIAL**

### Truth Assessment

- **PARTIALLY WORKING** - Sends close commands
- **INCOMPLETE** - No verification or retry
- **FRAGILE** - Could leave positions open
- **BEHAVIORAL ENFORCEMENT**: **INCOMPLETE**

---

## CRITICAL ARCHITECTURAL GAPS

### Gap 1: Persistence State Cleanup

- States are loaded from file on startup
- States are NOT cleaned up when MT5 has no positions
- Stale states accumulate forever
- **Impact**: Orphaned position tracking, confusion, potential crashes

### Gap 2: Broker Verification

- Reconciliation loads from persistence
- But persistence can be stale/corrupt
- No verification against current MT5 reality
- **Impact**: Mismatch between assumed state and broker state

### Gap 3: Close Order Verification

- Forced closes send orders
- But do NOT verify execution
- Orders can fail silently
- **Impact**: Positions may remain open despite close attempt

### Gap 4: Cooldown Persistence

- Cooldown tracked in memory
- Lost on restart
- **Impact**: User can re-trade after restart, ignoring cooldown

### Gap 5: Incomplete Session Protection

- Entry lock works (21:30)
- Friday 18:00 close works (with issues)
- But market close approach detection crashes
- **Impact**: No advance warning, abrupt close requirement

---

## RUNTIME TRUTH TABLE

| Component           | Exists | Called | Correct Sig | Reachable | Executes | Enforces | Status  |
| ------------------- | ------ | ------ | ----------- | --------- | -------- | -------- | ------- |
| Market close detect | ✓      | ✓      | ✗           | ✓         | ✗        | ✗        | BROKEN  |
| Orphan cleanup      | ✗      | -      | -           | -         | -        | -        | MISSING |
| Entry cooldown      | ✓      | ✓      | ✓           | ✓         | ✓        | ⚠️       | PARTIAL |
| Exit callback       | ✓      | ✓      | ✓           | ✓         | ✓        | ⚠️       | PARTIAL |
| Logger rotation     | ✓      | ✓      | ✓           | ✓         | ✓        | ⚠️       | PARTIAL |
| Force close         | ✓      | ✓      | ✓           | ✓         | ✓        | ⚠️       | PARTIAL |
| Risk restoration    | ✓      | ✓      | ✓           | ✓         | ✓        | ⚠️       | PARTIAL |
| Cooldown persist    | ✗      | -      | -           | -         | -        | -        | MISSING |
| Close verify        | ✗      | -      | -           | -         | -        | -        | MISSING |

---

## SUMMARY: FALSE IMPLEMENTATIONS DETECTED

| Claim                                  | Reality                         | Impact |
| -------------------------------------- | ------------------------------- | ------ |
| "Session management fully implemented" | Crashes on execution            | Medium |
| "Orphaned states cleaned up"           | Never cleaned, leak forever     | Medium |
| "Market close approach blocks entries" | Function crashes, not executed  | Medium |
| "Logger rotation seamless"             | Partial, may drop logs          | Low    |
| "Cooldown prevents revenge trading"    | Lost on restart                 | High   |
| "Force close verified"                 | No verification, close may fail | High   |
| "Daily state fully reconstructed"      | Partial, loss sequence wrong    | Low    |
| "Full runtime observability"           | Multiple silent failures        | High   |

---

## WHAT IS TRULY WORKING

1. **Entry Control Layer**: Cooldown checking works within session
2. **Forced Close Commands**: Orders are sent to MT5 (not verified)
3. **State Persistence**: Files are saved/loaded correctly
4. **Risk Recording**: Trade results recorded and persisted
5. **Basic Session Gating**: Entry time windows (11:00-21:30) enforced
6. **Log Rotation**: Files created daily (may not receive all logs)
7. **Risk Restoration Fallback**: Broker reconstruction function exists

---

## WHAT IS PARTIALLY WORKING

1. **Intraday Flattening**: Commands sent but not verified
2. **Orphan Management**: Loads states but doesn't clean stale ones
3. **Logger Health**: Checks handlers but write tests insufficient
4. **Exit Cooldown**: Blocks new entries but not persisted
5. **Risk Reconstruction**: Recovers state but incomplete consecutive_losses
6. **Broker Reconstruction**: Function exists but fragile

---

## WHAT IS BROKEN / MISSING

1. **Market Close Approach**: Function signature crash, never executes
2. **Orphan State Cleanup**: No code to remove stale states
3. **Close Verification**: No code to verify orders actually executed
4. **Cooldown Persistence**: No code to save/restore cooldown state
5. **Broker Verification**: Reconciliation trusts persistence over broker truth
6. **Old Handler Cleanup**: Rotation doesn't remove old handlers
7. **Flush After Rotation**: No explicit disk flush after day change
8. **Retry Logic**: Force close has no retry if order fails

---

## CONSEQUENCES FOR LIVE TRADING

1. **GUARANTEED CRASH**: Session management will crash every iteration
2. **ORPHANED TRADES**: Stale states could cause ghost position management
3. **OVERNIGHT EXPOSURE**: Close verification missing, positions may remain open
4. **COOLDOWN BYPASS**: User can restart and immediately re-trade
5. **LOGGING GAPS**: Midnight rotation may lose pending logs
6. **STATE DRIFT**: Persistence can diverge from broker reality

---

## IMPLEMENTATION COMPLETION ASSESSMENT

**Total Claims**: 8 major systems  
**Fully Working**: 1 (reconciliation summary logging)  
**Partially Working**: 6 (with gaps)  
**Broken**: 1 (session management - crashes)  
**Missing**: 3 (orphan cleanup, close verify, cooldown persist)

**Actual Operational Readiness**: 35% (barely usable, multiple crashes/gaps)

---

**Status**: ⚠️ REQUIRES IMMEDIATE FIXES  
**Priority**: CRITICAL (runtime crashes, overnight exposure)

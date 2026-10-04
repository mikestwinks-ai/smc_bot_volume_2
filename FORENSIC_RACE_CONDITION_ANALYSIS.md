# FORENSIC ANALYSIS: TRADE LIFECYCLE RACE CONDITION

## ROOT CAUSE IDENTIFIED

**The bot does NOT detect when positions close naturally (TP/SL hit).**

### The Race Condition Sequence

```
Loop N: manage_open_trades() runs
        position ticket 12345 is OPEN
        manage_open_trades() returns (position managed)

[Between iterations - MT5 closes the position automatically (SL or TP hit)]

Loop N+1: manage_open_trades() called
          conn.get_open_positions() queries MT5
          MT5 returns EMPTY LIST (position 12345 is GONE)
          
          if not positions:
              return  ← EARLY EXIT, NO CLOSURE LOGGING
          
          NO code runs:
          - No TRADE CLOSED log
          - No record_trade_result() call
          - No daily_pnl update
          - No register_trade_exit() call (NO COOLDOWN ARMED!)
          - No PnL telemetry
          
          Position disappears from _TRADE_STATES (no cleanup)

          Signal engine runs next
          can_open_trade() returns TRUE (no cooldown active)
          risk_ok returns TRUE
          New signal generated
          
          17:09:44 | HEARTBEAT | Positions: 0
          17:09:44 | TRADE EXECUTED | NEW ENTRY
          17:09:44 | TRADE OPENED
          
          ← ALL IN THE SAME SECOND, same direction!
```

### Why Previous Fixes Didn't Work

The previous forensic audits and consistency checks only verified:
- Peak equity >= balance
- Drawdown calculations
- State restoration on startup

But they did NOT detect:
- **Positions that disappeared between loop iterations**
- **Missing closure telemetry**
- **Orphaned deal records not processed**
- **Unregistered exit cooldowns**

### Current Code Flow (INCOMPLETE)

```
manage_open_trades()
  ├─ positions = conn.get_open_positions()  ← ONLY checks CURRENT positions
  ├─ if not positions: return               ← EARLY EXIT TRAP!
  ├─ for each position in positions:
  │   └─ _manage_position()                 ← Modifies SL, logs state
  └─ save_trade_states(_TRADE_STATES)       ← Persists position state
  
  [MISSING: Exit detection logic]
```

### What's Missing

The code does NOT:
1. Compare current MT5 positions with persisted _TRADE_STATES
2. Detect which tickets are in memory but NOT on MT5
3. Query deal history for orphaned positions
4. Process trade result (PnL) from closed positions
5. Register exit cooldowns
6. Log trade closure telemetry
7. Update daily accounting

## FORENSIC EVIDENCE

**From observed failure at 17:09:44:**
```
17:09:44 | HEARTBEAT | Positions: 0               ← Position just closed
17:09:44 | TRADE EXECUTED | Confirmation: STRONG  ← Signal executed
17:09:44 | TRADE OPENED                            ← New trade opened

MISSING BETWEEN THESE LINES:
- TRADE CLOSED logging
- PnL telemetry
- Cooldown logs
- Daily PnL update
```

This proves:
- Position closed on MT5
- manage_open_trades() returned early (detected no positions)
- Exit processing was never triggered
- Cooldown was never registered
- Signal engine executed immediately

## THE FIX: LIFECYCLE LOCK + EXIT DETECTION

### New Architecture

```
Main Loop:
├─ trade_lifecycle_lock.acquire()           ← LOCK
├─ manage_open_trades()
│  ├─ detect_closed_positions()             ← NEW: Check disappeared positions
│  ├─ process_closed_position(pnl)          ← NEW: Handle each closure
│  │  ├─ record_trade_result(pnl)
│  │  ├─ register_trade_exit()
│  │  └─ log closure telemetry
│  ├─ manage_remaining_positions()
│  └─ save_trade_states()
├─ check_equity_drawdown()
├─ trade_lifecycle_lock.release()           ← UNLOCK
├─ if can_open_trade() and not lifecycle_lock:  ← WAIT for lock
│   └─ execute signal engine
```

### Key Changes

1. **Exit Detection** - Identify disappeared positions
2. **Lifecycle Lock** - Prevent signal engine during closure processing
3. **Deal History Query** - Get actual realized PnL
4. **Cooldown Registration** - Call register_trade_exit() for EVERY closure
5. **Forensic Logging** - Log all lifecycle events
6. **Atomic Processing** - Trade closure MUST complete before re-entry allowed

## INVARIANTS TO ENFORCE

After the fix, ALL must be true before signal engine runs:

✅ All disappeared positions detected
✅ All closed positions have record_trade_result() called
✅ All closed positions have register_trade_exit() called
✅ All closed positions logged with TRADE CLOSED telemetry
✅ Daily accounting updated (daily_pnl, consecutive_losses)
✅ Peak equity updated
✅ Cooldown persisted to disk
✅ Trade state cleaned up
✅ NO orphaned positions in memory
✅ Lifecycle lock is released

If ANY of these are false, signal engine must NOT execute.

## TESTING STRATEGY

Simulate:
1. Trade hits TP naturally
2. Verify TRADE CLOSED logged
3. Verify record_trade_result() called
4. Verify register_trade_exit() called
5. Verify cooldown blocks re-entry
6. Verify same-second re-entry is PREVENTED

Verify:
- Floating loss scenario (position closes with loss)
- Floating profit scenario (position closes with profit)
- High-volatility re-entry suppression (strong signal immediately after)

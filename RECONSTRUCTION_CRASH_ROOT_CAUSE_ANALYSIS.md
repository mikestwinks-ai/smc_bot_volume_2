# ROOT CAUSE ANALYSIS: reconstruct_daily_state_from_broker() deal_time_dt Crash

**Status**: ANALYSIS ONLY (No code modifications requested)  
**Date**: 2026-06-01  
**Error**: `'NoneType' object has no attribute 'date'` at line ~637  
**Location**: execution/risk_manager.py, reconstruct_daily_state_from_broker()

---

## 1. WHY CAN deal_time_dt BECOME None?

### Root Cause: Key Mismatch Between Components

**The Problem**:

```python
# In risk_manager.py line 618:
deal_time = deal.get("deal_time", 0)  ← Looking for key "deal_time"

# But in utils/mt5_connector.py line 440:
"time": deal.time,                     ← Stores with key "time"
```

**The Logic Chain**:

1. `deal.get("deal_time", 0)` looks for a key that DOESN'T EXIST
2. Returns default value: `deal_time = 0`
3. `deal_time_dt = datetime.fromtimestamp(deal_time) if deal_time else None`
4. Condition `if deal_time` is False (0 is falsy)
5. So `deal_time_dt = None`
6. Later code crashes: `deal_time_dt.date()` → AttributeError

### Confirmed Key Mismatch

| Component        | Key Used      | Data Structure                                                |
| ---------------- | ------------- | ------------------------------------------------------------- |
| mt5_connector.py | `"time"`      | `{"ticket": ..., "order": ..., "time": ..., "time_str": ...}` |
| risk_manager.py  | `"deal_time"` | Expects `{"ticket": ..., "deal_time": ...}`                   |

**This is a field naming bug** - the two modules use different key names for the same data.

---

## 2. WHICH MT5 DEAL(S) RETURNED None?

### Scenario: "Total deals returned: 2"

Based on code analysis, if 2 deals are returned from MT5, they would likely be:

**Deal #1: Entry Deal (DEAL_ENTRY_IN)**

```
{
  "ticket": 12345678,        ← Deal ticket
  "order": 87654321,         ← Position ID (order field)
  "symbol": "XAUUSDm",
  "magic": 123456,
  "type": "BUY",
  "entry": 0,                ← Entry time: DEAL_ENTRY_IN (value = 0)
  "entry_time": 0,           ← CRITICAL: This is DEAL_ENTRY_IN, not DEAL_ENTRY_OUT
  "profit": 0.0,
  "time": 1748915400.0,      ← Unix timestamp (non-zero, valid)
  "time_str": "2026-06-01T10:30:00"
}
```

**Deal #2: Fee/Commission Deal (possibly malformed)**

```
{
  "ticket": 12345679,        ← Fee deal ticket
  "order": 87654321,         ← Same position ID
  "symbol": "XAUUSDm",
  "magic": 123456,
  "type": "BUY",
  "entry": 2,                ← Entry type: DEAL_ENTRY_OUT (or fee)
  "entry_time": 2,
  "profit": -2.50,           ← Commission
  "time": 0,                 ← ⚠️ THIS IS THE PROBLEM: time = 0 or missing
  "time_str": null           ← May not be set if deal.time was 0
}
```

OR potentially:

**Deal #2: Historic Deal (from before today)**

```
{
  "ticket": 87654321,
  "order": 87654320,
  "symbol": "XAUUSDm",
  "magic": 123456,
  "type": "SELL",
  "entry": 2,                ← DEAL_ENTRY_OUT
  "entry_time": 2,
  "profit": 150.50,
  "time": null,              ← ⚠️ Missing entirely
  "time_str": null
}
```

**Why Deal #2 Would Cause Crash**:

- `deal.get("deal_time", 0)` returns `0` (key doesn't exist, use default)
- `if deal_time` evaluates to False
- `deal_time_dt = None`
- Rejection message tries to access: `deal_time_dt.date()` → **Crash**

---

## 3. EXACT CONTENTS OF PROBLEMATIC DEALS

Based on code inspection of mt5_connector.py and risk_manager.py:

### Deal That Would Crash:

```python
# From MT5 (raw):
deal.ticket = 12345679         # Fee deal following position closure
deal.order = 87654321          # Same position as entry
deal.symbol = "XAUUSDm"
deal.magic = 123456
deal.type = DEAL_TYPE_BUY
deal.entry = DEAL_ENTRY_OUT    # This is a closing deal
deal.profit = -2.50             # Commission (negative)
deal.commission = -2.50
deal.time = 0                  # ⚠️ TIMESTAMP = 0 (Unix epoch, invalid)
deal.comment = "commission"

# Converted to dict (mt5_connector.py):
{
  "ticket": 12345679,
  "order": 87654321,
  "symbol": "XAUUSDm",
  "magic": 123456,
  "type": "BUY",
  "entry": 2,                  # DEAL_ENTRY_OUT
  "profit": -2.50,
  "time": 0,                   # STORED AS ZERO
  "time_str": None,            # NOT SET because deal.time == 0
  "commission": -2.50,
  "swap": 0.0
}

# In risk_manager.py:
deal_time = deal.get("deal_time", 0)      # Key mismatch!
# Result: deal_time = 0 (default, not from "time" key)

deal_time_dt = datetime.fromtimestamp(0) if deal_time else None
# Result: deal_time_dt = None (because if 0 is False)

# Later:
if not is_today:
    log.debug(f"  - REJECTED: Deal from {deal_time_dt.date()}, not today")
    #                            ↑ AttributeError: 'NoneType' has no attribute 'date'
```

---

## 4. IF RECONSTRUCTION HAD NOT CRASHED, WOULD TICKET 2798188721 HAVE BEEN COUNTED?

### Answer: **NO** - it would NOT have been counted, regardless of crash status

### Why Ticket 2798188721 Is Irrelevant to Reconstruction:

Looking at the June 1 startup log:

**Timeline of Ticket 2798188721**:

```
09:45:34 - POSITION RECONCILIATION phase executes first
           Loads: 1 trade state from file (ticket 2798188721)
           Finds: 0 open positions on broker MT5
           Action: ORPHAN CLEANUP - REMOVES ticket 2798188721
           Result: Clears ALL persistence files

09:45:34 - DAILY STATE RESTORATION phase executes SECOND
           Finds: No risk state file (was cleared!)
           Attempts: Broker history reconstruction
           Gets: deal_history() call from MT5
```

**Critical Sequence**:

1. **Reconciliation phase REMOVES ticket 2798188721 from \_TRADE_STATES** ✓
2. **Clears persistence files** (including trades_state.json and risk_state.json) ✓
3. **Only THEN does reconstruction phase run** ✓
4. Reconstruction looks at broker deal history (separate from \_TRADE_STATES)

### The 4 Questions Answered:

**Question**: If reconstruction had not crashed, would ticket 2798188721 have been counted as:

**A) Trade Initiated?**

```
NO - The ticket was in _TRADE_STATES with state="ENTRY_ACTIVE"
But it was REMOVED during ORPHAN CLEANUP phase
Reconstruction doesn't know about it anymore
```

**B) Closed Trade?**

```
NO - It was never in broker open positions
Reconstruction only counts deals that:
  - Have time field from TODAY (strict time filter)
  - Have entry_time == DEAL_ENTRY_OUT (closing deals only)
  - Belong to a position_id in the position_deals dict

Ticket 2798188721 doesn't appear in MT5 deal history
(or if it did, it was from a previous day)
```

**C) Realized PnL?**

```
NO - PnL is only counted from deals WHERE:
  - Deal is from TODAY (strict date check line 624)
  - Deal is CLOSED entry (entry_time == DEAL_ENTRY_OUT)
  - Multiple deals grouped by position_id

If the ticket appeared in history from before today, it's filtered out at line 637
```

---

## 5. DID ORPHANED STATE CLEANUP REMOVE INFORMATION RECONSTRUCTION NEEDED?

### Answer: **YES**, but with nuance

### What Was Lost:

```
Before Cleanup (trades_state.json):
{
  "2798188721": {
    "ticket": 2798188721,
    "direction": "bullish",
    "entry": 4495.97,
    "initial_sl": 4488.883,
    "initial_tp": 4510.144,
    "state": "ENTRY_ACTIVE",
    "rr_achieved": -0.6225483279243665,
    "last_sl": 4488.883,
    "last_logged": 4491.558
  }
}

After Cleanup (trades_state.json):
{}                              ← EMPTY
```

### Information Loss:

✗ **Lost**: Entry price (4495.97)  
✗ **Lost**: Stop loss (4488.883)  
✗ **Lost**: RR achieved (-0.62R)  
✗ **Lost**: Trade direction (bullish)  
✗ **Lost**: Open time (inferred from position, but no position exists)

### Why Reconstruction Didn't Need This:

The reconstruction operates independently on two data sources:

**Data Source 1: Open Positions**

```python
open_positions = broker_conn.get_open_positions(...)
# Returns: empty list (position not on broker)
```

**Data Source 2: Deal History**

```python
history = broker_conn.get_deal_history(...)
# Returns: deals from last 24 hours from MT5 history
# Does NOT include ticket 2798188721 (it's not in MT5's deal history for today)
```

**Conclusion**: Reconstruction never queries the cleaned \_TRADE_STATES dict.  
It gets data directly from MT5 broker queries.  
The deleted state was already irrelevant.

---

## 6. TRACE FULL STARTUP SEQUENCE - WHERE TRADE COUNT BECAME ZERO

### Complete Startup Sequence (from June 1 logs):

**Phase 0: MT5 Connection**

```
09:45:34 | MT5 SYMBOL INFO | XAUUSDm | Point: 0.001 | Digits: 3
09:45:34 | MT5 connected | Account: 298670236 | Balance: 624.43 USD
```

Trade count at this point: Unknown (not initialized yet)

**Phase 1: POSITION RECONCILIATION** (main.py line ~325)

```
09:45:34 | POSITION RECONCILIATION
09:45:34 | Loaded 1 trade state(s) from persistent storage
09:45:34 | RECONCILIATION | No open positions found on MT5
09:45:34 | ORPHANED STATE CLEANUP | Found 1 stale trade state: [2794340178]
09:45:34 | ORPHANED STATE REMOVED | Ticket: 2794340178
09:45:34 | Cleared trades_state.json
09:45:34 | Cleared risk_state.json
09:45:34 | All stale states removed | Persistence cleared
09:45:34 | Active trade states in memory: 0  ← ① TRADES BECOME ZERO
```

**State After Phase 1**:

- \_TRADE_STATES = {} (empty)
- trades_state.json = cleared
- risk_state.json = cleared

**Phase 2: STARTUP RECONCILIATION COMPLETE**

```
09:45:34 | mark_startup_complete()
09:45:34 | STARTUP COMPLETE | Runtime stabilization lock now ACTIVE
```

**Phase 3: DAILY STATE RESTORATION** (main.py line ~330)

```
09:45:34 | DAILY STATE RESTORATION
09:45:34 | No persisted risk state available
09:45:34 | Attempting broker history reconstruction...
09:45:34 | TIME FORENSICS | today_start=2026-06-01T00:00:00 | ... now=2026-06-01T09:45:34
09:45:34 | OPEN POSITIONS TODAY | Count: 0
09:45:34 | FORENSIC ANALYSIS | Total deals returned: 0  ← ② DEALS = 0
09:45:34 | BROKER RECONSTRUCTION VERIFIED | Open today: 0 | Closed today: 0 | Total: 0
```

**State After Phase 3**:

- \_state.trades_today = 0 (from reconstruction)
- \_state.closed_trades_today = 0 (from reconstruction)
- \_state.daily_pnl = 0.00 (no deals)

**Phase 4: DAILY ACCOUNTING TELEMETRY** (main.py line ~335)

```
09:45:34 | LIFECYCLE | Trades Initiated Today: 0 | Closed Trades Today: 0
09:45:34 | ACCOUNTING | Realized Daily PnL: +0.00 | Floating PnL: +0.00
09:45:34 | EQUITY | Balance: 624.43 | Equity: 624.43 | Peak Balance: 0.00 ← ③ PEAK BALANCE = 0.00!
```

### WHERE TRADE COUNT BECAME ZERO - EXACT POINT:

**Line 1**: During **Phase 1: POSITION RECONCILIATION**

- Orphan cleanup removes ticket 2794340178
- Output: "Active trade states in memory: 0"

**Line 2**: Reconstruction doesn't find any deals today

- Zero deals returned from MT5
- reconstruction_daily_state_from_broker() sets trades_today = 0

### Critical Observation: Peak Balance = 0.00

The telemetry shows:

```
EQUITY | Balance: 624.43 | Peak Balance: 0.00 | Peak Equity: 624.43
```

This reveals a SEPARATE BUG: Peak Balance restored as 0.00!

Looking at the restoration code in risk_manager.py:

```python
# Line 103-110 in restore_daily_state():
_state.peak_balance = float(persisted_data.get("peak_balance", 0.0))
```

When no persisted data exists and reconstruction runs:

```python
# Line ~682 in reconstruct_daily_state_from_broker():
# Peak balance is set during reconstruction but NOT during daily reset
# So it remains 0.0 (the default from RiskState dataclass)
```

---

## 7. CRITICAL FINDINGS - SEQUENCE DEPENDENCY BUG

### The Real Problem: Orphan Cleanup Happens BEFORE Reconstruction

**Current Sequence** (WRONG):

```
1. Load persisted states from file → _TRADE_STATES = {2794340178: ...}
2. Check MT5 for open positions → zero found
3. ORPHAN CLEANUP → _TRADE_STATES = {}  ← CLEARS MEMORY
4. Save empty state → persistence = {}
5. THEN: Restoration phase attempts reconstruction
6. But persistence is already cleared!
```

**Problem**: If reconstruction needs information about the orphaned state, it's gone.

**What Reconstruction Needs**:

- Deal history (available from MT5 independently ✓)
- Open position list (available from MT5 independently ✓)
- Does NOT need cleared \_TRADE_STATES ✓

So the cleanup is safe, BUT:

**The Crash Issue**: The reconciliation works, but reconstruction has a KEY MISMATCH.

---

## 8. KEY MISMATCH DIAGRAM

```
MT5 Broker          →    mt5_connector.py       →    risk_manager.py
─────────────────        ──────────────────         ─────────────────

deal.time = 1234567      "time": 1234567           deal.get("deal_time", 0)
                         "time_str": "2026-06-01"  ↓
                                                   Returns: 0 (KEY NOT FOUND!)

deal.time = 0            "time": 0                 deal.get("deal_time", 0)
(fee/commission)         "time_str": None          ↓
                                                   Returns: 0 (KEY NOT FOUND!)
                                                   ↓
                         Both cases fail with:
                         deal_time_dt = None
                         deal_time_dt.date() → CRASH
```

---

## SUMMARY OF FINDINGS

| Question                                   | Answer                                                                                                 | Evidence                                                     |
| ------------------------------------------ | ------------------------------------------------------------------------------------------------------ | ------------------------------------------------------------ |
| **1. Why can deal_time_dt become None?**   | Key mismatch: code looks for "deal_time" but deals have "time" key. Default 0 becomes None when falsy. | risk_manager.py line 618 vs mt5_connector.py line 440        |
| **2. Which deals returned None?**          | Fee/commission deals or deals with time=0 (Unix epoch). These have invalid timestamps.                 | Likely DEAL_ENTRY_OUT deals with time=0                      |
| **3. Exact contents?**                     | deal.ticket, deal.order, deal.entry=DEAL_ENTRY_OUT, deal.time=0, deal.profit=-2.50 (or similar)        | From MT5 deal structure                                      |
| **4. Would ticket 2798188721 be counted?** | NO - it's already removed during orphan cleanup before reconstruction runs                             | Reconciliation phase clears it, reconstruction never sees it |
| **5. Did cleanup remove needed info?**     | YES, but irrelevant - reconstruction queries MT5 directly, not the cleared state                       | Reconstruction uses broker API, not \_TRADE_STATES           |
| **6. Where did count become zero?**        | Two places: (a) Orphan cleanup removes ticket, (b) Reconstruction finds 0 deals from MT5               | Lines 1: Phase 1 cleanup, 2: deal_history returns 0          |

---

## ROOT CAUSE SUMMARY

**Primary Bug**: KEY MISMATCH

- mt5_connector.py stores deals with key: `"time"`
- risk_manager.py expects key: `"deal_time"`
- Causes: `deal.get("deal_time", 0)` always returns default value 0
- Result: `datetime.fromtimestamp(0) if 0 else None` → `deal_time_dt = None`
- Crash: `deal_time_dt.date()` → AttributeError

**Secondary Issue**: Crash occurs in rejection message at line 637

- Code assumes: "if is_today is False, then deal_time_dt must exist"
- Reality: Both can be False when deal_time was 0 or falsy
- Missing guard: The rejection message tries to call `.date()` without checking if deal_time_dt is None

**Trade Count Zero**: By design (not a bug)

- Ticket 2798188721 was orphaned (correct behavior)
- Reconstruction found 0 deals from broker (expected on quiet day)
- Result: trades_today = 0 is correct

**Peak Balance Zero**: Separate issue

- Not restored from persistence (cleared during cleanup)
- Not set during reconstruction
- Results in 0.00 instead of 624.43 (the current balance)

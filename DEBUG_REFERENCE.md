# SMC Bot Troubleshooting & Debug Reference

## Quick Fixes

### Problem: "Old code still loaded" error at startup

**Symptom**:

```
CRITICAL: Old code still loaded! Delete __pycache__/ and .pyc files
```

**Fix (choose one)**:

#### Option A: Use -Bc flag (RECOMMENDED)

```bash
python -Bc main.py
```

The `-B` flag bypasses bytecode cache entirely.

#### Option B: Delete cache manually (Windows)

```powershell
Get-ChildItem -Path . -Include '__pycache__' -Recurse -Force | Remove-Item -Recurse -Force
Get-ChildItem -Path . -Include '*.pyc' -Recurse -Force | Remove-Item -Force
python main.py
```

#### Option C: Delete cache manually (Linux/Mac)

```bash
find . -type d -name __pycache__ -exec rm -rf {} +
find . -name "*.pyc" -delete
python main.py
```

---

### Problem: "Symbol point value error" log appears repeatedly

**Symptom**:

```
[WARNING] XAUUSDm point value error detected: 0.001 vs correct 0.01 | CORRECTING for calculations...
```

**Meaning**: This is EXPECTED. It means:

- MT5 returned point=0.001 (incorrect for XAUUSDm)
- System auto-corrected to 0.01
- Calculations now use correct value

**What to do**: Nothing. This is normal and shows the fix is working.

**If it never appears**: Something is wrong with MT5 connection or symbol access.

---

### Problem: First signal shows no execution log

**Symptom**:

```
[DEBUG] Strong displacement (2.15x) but liquidity sweep missing
[INFO]  No trade logged
```

**Likely causes**:

1. Liquidity sweep not detected on M15 (legitimate rejection)
2. Confluence engine not detecting sweep correctly

**How to debug**:

```python
# Add this to confluence_engine.py for debugging:
log.debug(f"Sweep object: {sweep}")
log.debug(f"Sweep type: {type(sweep).__name__}")
log.debug(f"Has sweep: {sweep is not None}")
```

---

### Problem: POI check failing when displacement is strong

**Symptom**:

```
✓ Confirmation PASSED | Type: STRONG_DISPLACEMENT | ...
[Then immediately:]
ENTRY ZONE VALIDATION FAILED | Distance: 45.30 price units (4530 pts) | Tolerance: 1.00 price units (100 pts)
```

**Diagnosis**:

- Distance 45.30 units = 4530 pts (with correct 0.01 point value)
- Tolerance is 100 pts (1.00 units)
- Price is 45x too far from POI

**Likely cause**:

- POI bounds calculated incorrectly
- OR price hasn't reached POI zone yet
- This is NOT an error; legitimate rejection

**Check**:

```python
# In _check_poi_entry_conditions():
log.debug(f"POI type: {poi_type} | Bounds: [{poi_bottom:.2f}–{poi_top:.2f}]")
log.debug(f"Current price: {current_price:.2f} | Distance: {dist:.2f} units")
```

---

### Problem: "TRADE EXECUTED" log but no "TRADE OPENED" follows

**Symptom** (BAD):

```
✓ TRADE EXECUTED | Type: STRONG_DISPLACEMENT | ...
[No TRADE OPENED log appears]
```

**Root causes**:

1. Old bytecode still running (solution: clear cache)
2. MT5 order_send() failed silently (check MT5 logs)
3. Retcode check broken (review entry_engine.py lines 170-175)

**Quick test**:

```bash
# Clear cache and run with -Bc flag
python -Bc main.py

# If problem persists, check log for:
# "MT5 ORDER FAILED | retcode=..."
```

---

## Diagnostic Logs to Check

### At startup (first 5 lines):

```
SMC Trading Bot — Initialising
   CRITICAL CONSTANTS | STRONG_THRESHOLD: 2.0 | MEDIUM_THRESHOLD: 1.5
   CODE VALIDATION | Tiered confirmation loaded: True
   ✓ New tiered confirmation code loaded successfully
   MT5 SYMBOL INFO | XAUUSDm | Point: 0.01 | Digits: 2
```

**What to look for**:

- Point value shows `0.01` (NOT `0.001`)
- "Tiered confirmation loaded: True"
- "New tiered confirmation code loaded successfully"

### During signals:

```
✓ Confirmation PASSED | Type: STRONG_DISPLACEMENT | Displacement: 2.15x
✓ TRADE EXECUTED | Type: STRONG_DISPLACEMENT | Entry method: STRICT_POI
TRADE OPENED ✔ | Ticket: 12345678 | Entry: 2487.35
```

**What to look for**:

- Confirmation log appears BEFORE execution log
- Execution log appears BEFORE "TRADE OPENED"
- Ticket number is present in "TRADE OPENED"

### On rejection:

```
ENTRY ZONE VALIDATION FAILED | Stage: POI_CHECK | Distance: 10.36 price units (1036 pts) | Tolerance: 1.00 price units (100 pts)
```

**What to check**:

- Distance shown in BOTH price units AND points
- Tolerance clearly displayed
- Entry bounds shown

---

## Revert to Old Code (if needed)

If you made changes and want to restore the working version:

1. **Check git status**:

   ```bash
   git status
   ```

2. **Restore specific file**:

   ```bash
   git checkout execution/entry_engine.py
   git checkout utils/mt5_connector.py
   ```

3. **Clear bytecode**:
   ```bash
   python -Bc main.py
   ```

---

## Point Value Math Reference

For XAUUSDm (correct point=0.01):

| Price Units | Points | Notes             |
| ----------- | ------ | ----------------- |
| 0.01        | 1      | One pip           |
| 0.10        | 10     | Ten pips          |
| 1.00        | 100    | One hundred pips  |
| 10.00       | 1000   | One thousand pips |

**Example calculation**:

```
Distance = 10.36 price units
In points = 10.36 / 0.01 = 1036 points
Tolerance = 100 points = 1.00 price units
Status = 1036 pts >> 100 pts tolerance → REJECTED
```

If point value is wrong (0.001 instead of 0.01):

```
Distance = 10.36 price units
In points (WRONG) = 10.36 / 0.001 = 10360 points ← 10x too large!
Tolerance = 100 points = 10.00 price units (WRONG)
Status = Entry zone appears 100x too tight → Always rejected
```

---

## MT5 Connection Debug

### Check if MT5 is responding:

```python
import MetaTrader5 as mt5

# Try to connect
if mt5.initialize():
    info = mt5.symbol_info("XAUUSDm")
    if info:
        print(f"✓ Connected | Symbol: {info.name} | Point: {info.point}")
    else:
        print("✗ Symbol not found")
        print(f"  Available symbols: {mt5.symbols_total()}")
else:
    print(f"✗ MT5 init failed: {mt5.last_error()}")
```

### Check account access:

```python
account = mt5.account_info()
if account:
    print(f"✓ Account: {account.login} | Balance: {account.balance}")
else:
    print(f"✗ Account access failed: {mt5.last_error()}")
```

### Check order history:

```python
deals = mt5.history_deals_get(position_ticket=0)
print(f"Total deals in history: {len(deals)}")
for deal in deals[-5:]:  # Last 5 deals
    print(f"  Ticket: {deal.ticket} | Type: {deal.type} | Entry: {deal.entry}")
```

---

## Performance Tuning

### Reduce lag (shorten LOOP_SLEEP_SECONDS):

In `config/settings.py`:

```python
LOOP_SLEEP_SECONDS = 1  # Default: 5 seconds
                         # 1 = check every second (more CPU)
                         # 10 = check every 10 seconds (less CPU)
```

### Increase M5 bars for better confluence:

```python
M5_BARS = 50  # Default: 30
              # Higher = more history, better confluence detection
              # Lower = faster analysis, less history
```

### Adjust displacement thresholds:

```python
STRONG_DISPLACEMENT_THRESHOLD = 2.0  # Default
MEDIUM_DISPLACEMENT_THRESHOLD = 1.5  # Default

# More conservative: increase both (fewer trades)
# More aggressive: decrease both (more trades)
```

---

## Log Rotation (if logs grow too large)

The logger creates daily log files in `logs/` directory.

To clean old logs:

```bash
# Keep last 7 days of logs
cd logs
ls -t | tail -n +8 | xargs rm --

# Or manually delete
rm smc_bot_2024-01-01.log
```

---

## Emergency Shutdown

If the bot is misbehaving:

### Graceful shutdown (Ctrl+C):

```bash
python main.py
# Press Ctrl+C to stop
# Bot will close all open positions (if enabled)
```

### Force shutdown:

```bash
# Kill the process (Windows)
taskkill /IM python.exe /F

# Kill the process (Linux/Mac)
pkill -f "python.*main.py"
```

### Check for stuck trades:

```python
# Run this to see all open positions
import MetaTrader5 as mt5
mt5.initialize()
positions = mt5.positions_get(symbol="XAUUSDm")
for pos in positions:
    print(f"Position {pos.ticket}: {pos.symbol} | Open: {pos.open_price} | SL: {pos.sl}")
```

---

## Contact Support / Debug

When reporting issues, include:

1. **First 10 lines of log** (startup):

   ```
   [14:22:00] SMC Trading Bot — Initialising
   [14:22:00] ✓ Confirmation PASSED...
   ```

2. **Last 20 lines of log** (where problem occurred)

3. **Config values**:

   ```python
   SYMBOL
   MT5_SERVER
   STRONG_DISPLACEMENT_THRESHOLD
   MEDIUM_DISPLACEMENT_THRESHOLD
   ```

4. **Python version**:

   ```bash
   python --version
   ```

5. **MT5 version** and server name

6. **Exact error message** (copy-paste from logs)

---

## Code Changes Made This Session

- ✅ `utils/mt5_connector.py`: Added XAUUSDm point value validation
- ✅ `execution/entry_engine.py`: Fixed MT5 failure logging, enhanced POI rejection logs
- ✅ `main.py`: Added startup code validation checks
- ✅ Cleared Python bytecode cache (all .pyc files and **pycache** deleted)

All changes maintain backward compatibility. Revert any file with `git checkout <filename>`.

---

Last updated: [Current date]
Bot version: Stable (Tiered Confirmation + Point Fix)

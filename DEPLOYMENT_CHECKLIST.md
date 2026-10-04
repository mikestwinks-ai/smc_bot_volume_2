# Deployment Checklist

✅ **COMPLETED CHANGES**

## Code Changes

- [x] Modified `config/settings.py` — Added 5 new entry logic parameters
- [x] Refactored `execution/entry_engine.py` — Implemented 4-tier entry hierarchy
- [x] Created `_check_poi_entry_conditions()` function — Core adaptive logic
- [x] Updated trade comments with entry method tags
- [x] Enhanced logging for all entry attempts
- [x] Maintained backward compatibility with strict POI check

## Documentation Created

- [x] REFACTORING_SUMMARY.md — Complete technical documentation
- [x] BEFORE_AFTER_ANALYSIS.md — Real-world example (score 11.0 signal)
- [x] PARAMETER_TUNING_GUIDE.md — Instrument-specific settings
- [x] ENTRY_LOGIC_DIAGRAM.md — Decision tree and state machine
- [x] QUICK_REFERENCE.md — Developer quick start guide
- [x] This deployment checklist

## Validation

- [x] Python syntax verified (no errors)
- [x] No breaking changes to main.py
- [x] Risk management unchanged
- [x] Signal scoring system preserved
- [x] M5 confirmation gates maintained
- [x] Import statements validated

---

## 🚀 DEPLOYMENT STEPS

### Phase 1: Pre-Deployment Review (30 minutes)

- [ ] Read QUICK_REFERENCE.md (5 min)
- [ ] Review ENTRY_LOGIC_DIAGRAM.md for decision flow (10 min)
- [ ] Check default parameters in settings.py (5 min)
- [ ] Verify .env file has no conflicts (10 min)

### Phase 2: Dry-Run Configuration (15 minutes)

- [ ] Ensure bot can start without errors:

  ```bash
  python main.py &
  sleep 5
  # Should see "SMC Trading Bot — Initialising"
  kill %1
  ```

- [ ] Verify new parameters load correctly:
  ```python
  from config import settings
  print(f"POI_TOLERANCE_POINTS: {settings.POI_TOLERANCE_POINTS}")
  print(f"STRONG_TREND_DISPLACEMENT: {settings.STRONG_TREND_DISPLACEMENT}")
  # Should show 50, 2.0 (or your custom values)
  ```

### Phase 3: Extended Dry-Run (24+ hours)

**DO NOT trade with real money until this is complete**

- [ ] Run bot for 24+ hours in dry-run/sim mode
- [ ] Monitor logs for entry attempts
- [ ] Check entry method distribution:

  ```bash
  grep "STRICT_POI\|NEAR_POI\|FVG_ENTRY\|STRONG_TREND" logs/*.log | wc -l
  ```

- [ ] Verify no errors in execution flow:

  ```bash
  grep "ERROR\|CRITICAL" logs/*.log | grep -v "Order failed"
  # Should return nothing or only existing issues
  ```

- [ ] Check trade comments include entry method:
  ```
  Expected: SMC_OB_S11_NEAR_POI_OB
  NOT:      SMC_OB_S11
  ```

### Phase 4: Parameter Tuning (if needed)

- [ ] If more than 20% rejections despite score ≥ 8:

  ```env
  POI_TOLERANCE_POINTS=70  # Increase from 50
  ```

- [ ] If all entries are NEAR_POI (no STRICT_POI):

  ```env
  POI_TOLERANCE_POINTS=30  # Decrease from 50
  ```

- [ ] Run another 12 hours dry-run with new parameters
- [ ] Re-check entry distribution

### Phase 5: Production Deployment

- [ ] Backup current `.env` and log files:

  ```bash
  cp .env .env.backup
  mkdir logs_backup
  cp logs/* logs_backup/
  ```

- [ ] Deploy bot with new code
- [ ] Monitor first 2 hours carefully
- [ ] Check for any unexpected rejections
- [ ] Verify trade execution matches expected entry methods

- [ ] Continue monitoring for 7 days:
  - Win rate stable or improving
  - No excessive rejections
  - Entry methods are mixed (not all NEAR_POI)
  - Trade frequency increased by 1-2 trades/session

### Phase 6: Optimization (Week 2+)

- [ ] Analyze 100+ trades for entry method performance
- [ ] Fine-tune parameters based on results
- [ ] Document changes in project notes
- [ ] Consider per-session parameter adjustments if needed

---

## ⚠️ VERIFICATION CHECKPOINTS

### At Each Stage, Verify:

**Startup Check:**

```
✓ Bot starts without "ModuleNotFoundError"
✓ Settings load: "POI_TOLERANCE_POINTS: 50"
✓ No "NameError" in entry_engine.py
✓ MT5 connection successful
```

**Entry Attempt Check:**

```
✓ Logs show entry methods (STRICT_POI, NEAR_POI, etc.)
✓ Trade comments include method tag (SMC_OB_S11_NEAR_POI_OB)
✓ No infinite loops or hangs
✓ Rejection reasons include distance metrics
```

**Trade Execution Check:**

```
✓ Orders fill successfully (no order failures)
✓ SL properly set beyond POI edge
✓ TP at 2R from entry
✓ Lot size reasonable for risk
```

**Risk Management Check:**

```
✓ Max daily trades limit respected
✓ Drawdown protection working
✓ Consecutive loss limit applied
✓ Spread check prevents bad entries
```

---

## 🔧 QUICK TROUBLESHOOTING

### Issue: "ModuleNotFoundError: No module named 'fvg_model'"

**Cause:** Import issue in entry_engine.py  
**Fix:** Check entry_engine.py line ~200 for proper import:

```python
from models.fvg_model import detect_fvgs, active_fvgs, nearest_fvg
```

Should be inside `_check_poi_entry_conditions()` function.

---

### Issue: "All entries showing NEAR_POI, no STRICT_POI"

**Cause:** POI zones are naturally wider than price movement  
**Fix:**

- Check spread (may be too wide)
- Verify score threshold (may be too low)
- Consider instrument characteristics
- Try decreasing POI_TOLERANCE_POINTS by 20 pts

---

### Issue: "Still getting '100% rejection' on score 8+ signals"

**Cause:** Buffer not wide enough or M5 conditions failing  
**Fix:**

1. Check mini BOS on M5 (may need adjustment to lookback window)
2. Check displacement (may need lower threshold)
3. Increase POI_TOLERANCE_POINTS by 30 pts
4. Check spread (> 100 pts prevents entry)

---

### Issue: "Bot is entering too much (> 5 trades/session)"

**Cause:** Buffer too wide, catching false signals  
**Fix:**

1. Increase score threshold (but don't modify MIN_SCORE_ALWAYS)
2. Decrease POI_TOLERANCE_POINTS by 30 pts
3. Increase STRONG_TREND_DISPLACEMENT to 2.3

---

## 📊 MONITORING DASHBOARD

After 24+ hours dry-run, collect these metrics:

```
Entry Statistics:
  Total entry attempts:      ___
  STRICT_POI:                ___ (% of total)
  NEAR_POI:                  ___ (% of total)
  NEAR_POI (strong trend):   ___ (% of total)
  FVG_ENTRY:                 ___ (% of total)
  Total rejected:            ___ (% of total)

Trade Quality:
  Avg score on entered trades:  ___
  Avg score on rejected trades: ___
  Rejection % on score 9+:      ___ (should be < 5%)

Performance:
  Winning trades:            ___
  Win rate:                  ___%
  Avg profit per trade:      ___
  Profit factor:             __:1
```

---

## ✅ GO/NO-GO DECISION

### GO to production if:

- ✅ Bot starts and runs without errors
- ✅ Entry methods are being logged
- ✅ Mix of STRICT_POI and NEAR_POI entries (not 100% one type)
- ✅ High-score rejections reduced by 50%+
- ✅ Trade comments include entry method tags
- ✅ Win rate stable or improved from before
- ✅ Spread checks are preventing bad entries
- ✅ Risk management gates still function

### NO-GO (Hold and debug) if:

- ❌ Startup errors or import failures
- ❌ All entries same method (all STRICT_POI or all NEAR_POI)
- ❌ Excessive entries on low scores (< 6)
- ❌ Order failures increasing
- ❌ Win rate drops significantly
- ❌ Spread check not working (orders through at 200+ pts spread)
- ❌ SL/TP calculations off

---

## 🎯 SUCCESS METRICS (Post-Deployment)

After 7 days in production:

| Metric                 | Target         | Status |
| ---------------------- | -------------- | ------ |
| Entry attempts         | +40% vs before | ☐      |
| Rejections on score 8+ | -80%           | ☐      |
| Win rate               | Stable or ↑    | ☐      |
| Avg trades/session     | +1 to +2       | ☐      |
| Trade method mix       | Multiple types | ☐      |
| No breakage            | 0 errors       | ☐      |

---

## 📞 ROLLBACK PROCEDURE

If critical issues emerge:

1. **Immediate rollback:**

   ```bash
   # Stop bot
   git checkout HEAD~1 -- execution/entry_engine.py
   # Restart bot
   python main.py
   ```

   Bot will revert to strict POI check (conservative mode)

2. **Keep debugging:**
   - New settings.py is harmless (just unused parameters)
   - Logs are preserved for analysis
   - No data loss

3. **Post-incident:**
   - Document what went wrong
   - Review specific logs
   - Adjust parameters and retest
   - Deploy again with fixes

---

## 📋 SIGN-OFF

- [ ] Code changes reviewed: **\_** (date)
- [ ] Documentation read: **\_** (date)
- [ ] 24h dry-run complete: **\_** (date)
- [ ] Parameters tuned (if needed): **\_** (date)
- [ ] Deployment approved: **\_** (name/date)
- [ ] Production deployment: **\_** (date/time)
- [ ] First 7 days monitoring: **\_** (date)

---

## 📞 SUPPORT

For questions during deployment:

1. Check QUICK_REFERENCE.md
2. Review ENTRY_LOGIC_DIAGRAM.md for decision flow
3. Check PARAMETER_TUNING_GUIDE.md for your instrument
4. Review trade comments for entry method used
5. Analyze logs for specific entry condition details

---

**Remember:** This refactoring improves execution participation without changing signal quality. The bot's analysis is as good as before—now it can actually **trade** those signals. ✅

# Parameter Tuning Guide by Instrument

## Overview

The new entry logic uses 5 configurable parameters to adapt to different market conditions. This guide provides tested starting values for common instruments.

---

## Parameter Explanations

| Parameter                    | Purpose                                         | Range    | Default |
| ---------------------------- | ----------------------------------------------- | -------- | ------- |
| `POI_TOLERANCE_POINTS`       | Standard buffer around POI in normal conditions | 20–100   | 50      |
| `STRONG_TREND_DISPLACEMENT`  | Trigger threshold for strong trend detection    | 1.5–3.0x | 2.0     |
| `STRONG_TREND_BUFFER_POINTS` | Larger buffer when strong trend detected        | 50–150   | 80      |
| `FVG_ENTRY_TOLERANCE_POINTS` | Distance allowed from FVG boundaries            | 10–50    | 20      |
| `NEAR_POI_PROXIMITY_POINTS`  | Informational only (derived from tolerance)     | 20–60    | 30      |

---

## Instrument Profiles

### 🏆 Gold (XAUUSD / XAUUSDm) — **PRIMARY INSTRUMENT**

**Market Characteristics:**

- Wider spreads (30–100 points typical)
- Strong directional moves
- Lower volatility than majors
- Good for strong trend entries

**Recommended Settings:**

```env
POI_TOLERANCE_POINTS=50
STRONG_TREND_DISPLACEMENT=2.0
STRONG_TREND_BUFFER_POINTS=80
FVG_ENTRY_TOLERANCE_POINTS=20
NEAR_POI_PROXIMITY_POINTS=30
```

**Rationale:**

- Default settings are optimized for gold
- 50 pt tolerance matches typical daily volatility
- 80 pt strong trend buffer allows entries in 2+ displacement moves
- FVG entries catch quick mean-reversions

**Typical Entry Pattern:**

```
OB Zone:    4500–4520
Price:      4540 (20 pts above)
Entry:      ✓ Via NEAR_POI with 50 pt buffer

Strong Trend:
Disp:       2.5x
Price:      4580 (60 pts above)
Entry:      ✓ Via NEAR_POI with 80 pt strong trend buffer
```

---

### EUR/USD — Forex Major

**Market Characteristics:**

- Tight spreads (2–5 points)
- High liquidity
- Faster price movement
- More noise in entry zones

**Recommended Settings:**

```env
POI_TOLERANCE_POINTS=20
STRONG_TREND_DISPLACEMENT=1.8
STRONG_TREND_BUFFER_POINTS=40
FVG_ENTRY_TOLERANCE_POINTS=10
NEAR_POI_PROXIMITY_POINTS=15
```

**Rationale:**

- Smaller buffers due to tight spreads
- Lower displacement threshold (1.8x) due to volatility
- FVG tolerance lower (10 pts) for precision
- Faster pullbacks in forex

**Typical Entry Pattern:**

```
OB Zone:    1.0840–1.0850
Price:      1.0860 (10 pts above)
Entry:      ✓ Via NEAR_POI with 20 pt buffer
```

---

### GBP/USD — Forex Major

**Market Characteristics:**

- Slightly wider spreads than EUR (4–8 points)
- Higher volatility than EUR
- Stronger trends often develop
- Good for directional strategies

**Recommended Settings:**

```env
POI_TOLERANCE_POINTS=30
STRONG_TREND_DISPLACEMENT=1.9
STRONG_TREND_BUFFER_POINTS=60
FVG_ENTRY_TOLERANCE_POINTS=15
NEAR_POI_PROXIMITY_POINTS=20
```

**Rationale:**

- Middle ground between EUR and gold
- Slightly higher displacement threshold (1.9x) for strong trends
- Medium buffer reflecting volatility

---

### Crude Oil (XTIUSD / XBRUSD) — Commodities

**Market Characteristics:**

- Wider spreads (50–200 points)
- Strong intraday moves
- High volatility
- Trend-following friendly

**Recommended Settings:**

```env
POI_TOLERANCE_POINTS=80
STRONG_TREND_DISPLACEMENT=1.8
STRONG_TREND_BUFFER_POINTS=120
FVG_ENTRY_TOLERANCE_POINTS=40
NEAR_POI_PROXIMITY_POINTS=50
```

**Rationale:**

- Larger buffers required due to wide spreads
- Lower displacement threshold (1.8x) catches trends earlier
- Bigger strong trend buffer (120 pts) for fast moves
- FVG tolerance higher (40 pts) to handle volatility

**Typical Entry Pattern:**

```
OB Zone:    79.00–79.50
Price:      80.50 (100 pts above)
Entry:      ✓ Via NEAR_POI with 120 pt strong trend buffer
            (if displacement ≥ 1.8x)
```

---

### S&P 500 (ES, SPX) — Index Futures

**Market Characteristics:**

- Moderate spreads (5–20 points depending on broker)
- High correlation with overall market
- Fast overnight moves possible
- Good technical structure

**Recommended Settings:**

```env
POI_TOLERANCE_POINTS=25
STRONG_TREND_DISPLACEMENT=2.1
STRONG_TREND_BUFFER_POINTS=50
FVG_ENTRY_TOLERANCE_POINTS=15
NEAR_POI_PROXIMITY_POINTS=18
```

**Rationale:**

- Moderate tolerance (25 pts) for index stability
- Higher displacement threshold (2.1x) for reliable trends
- Futures need tighter entries than spot commodities

---

## Tuning Steps (New Instrument)

### Phase 1: Conservative Testing

1. Start with **XAUUSD default values** (safest base)
2. Run **7 days dry-run** with default
3. Note:
   - How often STRICT_POI entries occur
   - How many trades are NEAR_POI vs STRICT_POI
   - Any rejected trades with score ≥ 8

### Phase 2: Adjustment

If more than 30% of high-score signals rejected:

1. Increase `POI_TOLERANCE_POINTS` by +20 pts
2. Run 3 more days dry-run
3. Monitor entry frequency

If entries too frequent/loose:

1. Decrease `POI_TOLERANCE_POINTS` by -10 pts
2. Increase `STRONG_TREND_DISPLACEMENT` by +0.2

### Phase 3: Strong Trend Buffer

1. Check logs for `STRONG_TREND` entries
2. If 0 entries in 100 trades:
   - Lower `STRONG_TREND_DISPLACEMENT` by -0.2
3. If > 50% of entries use strong trend buffer:
   - Consider increasing `POI_TOLERANCE_POINTS` instead

### Phase 4: Production

1. Deploy with tuned values
2. Monitor first week
3. Adjust monthly if needed

---

## Diagnostic Log Patterns

### Entry Success Indicators ✓

**Healthy distribution (expected after 100 trades):**

```
STRICT_POI:   30%  (price lands in zone)
NEAR_POI:     50%  (within normal buffer)
STRONG_TREND: 15%  (big moves detected)
FVG_ENTRY:    5%   (alternative entries)
REJECTED:     10%  (price too far + low score)
```

### Problem Indicators ⚠️

**Too many rejections (>15% despite high scores):**

```
→ Increase POI_TOLERANCE_POINTS by +20
```

**Too many STRICT_POI entries (>60%):**

```
→ Consider decreasing tolerance
→ Market may have low volatility
```

**No STRONG_TREND entries ever:**

```
→ Decrease STRONG_TREND_DISPLACEMENT from 2.0 → 1.8
→ Your markets may have smaller displacements
```

**Too many FVG_ENTRY entries (>20%):**

```
→ Increase FVG_ENTRY_TOLERANCE_POINTS or
→ Decrease MIN_SCORE_ALWAYS requirement (but don't)
```

---

## Environment Variable Setup

### Quick Configuration Template

**For your .env file:**

```bash
# ──── Gold Trading (Default) ────
POI_TOLERANCE_POINTS=50
STRONG_TREND_DISPLACEMENT=2.0
STRONG_TREND_BUFFER_POINTS=80
FVG_ENTRY_TOLERANCE_POINTS=20

# ──── To switch to Forex ────
# Uncomment below and comment above:
# POI_TOLERANCE_POINTS=20
# STRONG_TREND_DISPLACEMENT=1.8
# STRONG_TREND_BUFFER_POINTS=40
# FVG_ENTRY_TOLERANCE_POINTS=10

# ──── To switch to Oil ────
# Uncomment below and comment above:
# POI_TOLERANCE_POINTS=80
# STRONG_TREND_DISPLACEMENT=1.8
# STRONG_TREND_BUFFER_POINTS=120
# FVG_ENTRY_TOLERANCE_POINTS=40
```

---

## Safety Constraints (DO NOT MODIFY)

These thresholds should **NOT** be changed:

```env
# ❌ DO NOT CHANGE:
MIN_SCORE_ALWAYS=6              # Entry quality gate
MIN_SCORE_NY_ONLY=5             # Session-based gate
DISPLACEMENT_MULTIPLIER=1.5     # Confirmation threshold
DISPLACEMENT_LOOKBACK=10        # Signal lookback

# ✅ SAFE TO CHANGE:
POI_TOLERANCE_POINTS
STRONG_TREND_DISPLACEMENT
STRONG_TREND_BUFFER_POINTS
FVG_ENTRY_TOLERANCE_POINTS
```

Changing the "DO NOT CHANGE" values will:

- Lower signal quality
- Increase false signals
- Break the existing strategy

---

## Troubleshooting

### "Too many false entries"

```
Possible causes:
1. POI_TOLERANCE_POINTS too high
2. STRONG_TREND_DISPLACEMENT too low
3. Score threshold settings changed

Solution:
→ Revert to default values
→ Verify MIN_SCORE_ALWAYS = 6
→ Check DISPLACEMENT_MULTIPLIER = 1.5
```

### "No entries despite high score signals"

```
Possible causes:
1. POI_TOLERANCE_POINTS too low
2. Spread is extremely high
3. M5 BOS or displacement missing

Solution:
→ Check current spread in logs
→ Increase POI_TOLERANCE_POINTS by +30
→ Verify M5 conditions (Mini BOS + Displacement)
```

### "Entries too far from POI"

```
Possible causes:
1. STRONG_TREND_BUFFER_POINTS excessive
2. STRONG_TREND_DISPLACEMENT threshold too low
3. Market in sustained trend

Solution:
→ Increase STRONG_TREND_DISPLACEMENT to 2.2
→ Decrease STRONG_TREND_BUFFER_POINTS to 60
→ Review trade profitability (might be fine!)
```

---

## Summary

**Best Practice:**

1. Start with your instrument's recommended profile
2. Run 7-day dry-run to baseline
3. Adjust only one parameter at a time
4. Wait 3 days between adjustments
5. Document changes and results
6. Never lower MIN_SCORE_ALWAYS

**Golden Rule:**
If in doubt, use **wider buffers** → more entries, slightly lower win rate  
vs **tighter buffers** → fewer entries, slightly higher win rate

Choose based on whether you prefer **volume** or **precision** for your capital.

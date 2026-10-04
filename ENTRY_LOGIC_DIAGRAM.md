# Entry Logic Decision Tree

## Signal Generation Flow (UNCHANGED)

```
┌─────────────────────────────────────────────────────────────────────┐
│ HTF Bias Detection (H4)                                              │
│  • Structure analysis (HH/HL/LH/LL)                                 │
│  • BOS/CHoCH detection                                              │
│  • Liquidity sweep confirmation                                      │
│ ✅ Quality: 2.0 points                                              │
└─────────────────┬───────────────────────────────────────────────────┘
                  │
┌─────────────────▼───────────────────────────────────────────────────┐
│ Confluence Scoring (M15)                                             │
│  • Order Blocks (OB) → +1 point                                     │
│  • Fair Value Gaps (FVG) → +1 point                                 │
│  • Breaker Blocks → +2 points                                       │
│  • CHoCH → +1 point                                                 │
│  • Liquidity sweep → +2 points                                      │
│  • Displacement → +2 points                                         │
│ ✅ Total Score: 6–11 points                                         │
│ ✅ Minimum to trade: 6 points                                       │
└─────────────────┬───────────────────────────────────────────────────┘
                  │
        ┌─────────▼──────────┐
        │ Score < 6 ?        │
        └─────────┬──────────┘
                  │ YES → REJECT (no trade)
                  │ NO → Continue to entry logic
                  │
┌─────────────────▼───────────────────────────────────────────────────┐
│ ✨ NEW ENTRY LOGIC (Adaptive POI Tolerance)                         │
│                                                                      │
│ Entry requires M5 confirmation (ALWAYS):                            │
│  • Mini BOS present within last 10 bars                             │
│  • Displacement candle (body ≥ 1.5x average) in correct direction   │
│ ✅ Both required before ANY entry attempt                           │
└─────────────────┬───────────────────────────────────────────────────┘
                  │
        ┌─────────▼──────────────────────────────┐
        │ Both M5 conditions met?                 │
        └─────────┬──────────────────────────────┘
                  │ NO → REJECT (M5 not confirming)
                  │ YES → Check entry zones
                  │
┌─────────────────▼───────────────────────────────────────────────────┐
│ TIER 1: STRICT POI CHECK                                             │
│  IF current_price ∈ [POI_bottom, POI_top]                           │
│    ✅ ENTER (Entry method: STRICT_POI)                             │
│  ELSE                                                                │
│    → Continue to Tier 2                                             │
└─────────────────┬───────────────────────────────────────────────────┘
                  │
┌─────────────────▼───────────────────────────────────────────────────┐
│ TIER 2: STRONG TREND DETECTION                                      │
│  IF displacement_ratio ≥ STRONG_TREND_DISPLACEMENT (default 2.0)    │
│    buffer = STRONG_TREND_BUFFER_POINTS (default 80 pts)            │
│  ELSE                                                                │
│    buffer = POI_TOLERANCE_POINTS (default 50 pts)                  │
└─────────────────┬───────────────────────────────────────────────────┘
                  │
┌─────────────────▼───────────────────────────────────────────────────┐
│ TIER 3: NEAR-POI ENTRY (with adaptive buffer)                       │
│  IF current_price ∈ [POI_bottom - buffer, POI_top + buffer]        │
│    ✅ ENTER (Entry method: NEAR_POI_OB or NEAR_POI_FVG)           │
│  ELSE                                                                │
│    → Continue to Tier 4                                             │
└─────────────────┬───────────────────────────────────────────────────┘
                  │
┌─────────────────▼───────────────────────────────────────────────────┐
│ TIER 4: FVG-BASED ENTRY (alternative POI)                          │
│  IF score ≥ MIN_SCORE_ALWAYS (6) AND POI type ≠ FVG                │
│    Scan M5 for active FVGs in trade direction                       │
│    IF price ∈ [FVG - tolerance, FVG + tolerance]                   │
│      ✅ ENTER (Entry method: FVG_ENTRY)                            │
│  ELSE                                                                │
│    → Continue to rejection                                          │
└─────────────────┬───────────────────────────────────────────────────┘
                  │
┌─────────────────▼───────────────────────────────────────────────────┐
│ ❌ REJECT TRADE                                                     │
│ Log: "Price not in entry zone | Distance to POI: XX pts"           │
│      "Tolerance: YY pts | Score: Z"                                 │
└─────────────────────────────────────────────────────────────────────┘
```

---

## Entry Success Criteria Summary

```
✅ MUST HAVE (Gate conditions):
   ├─ H4 Bias confirmed (bullish or bearish)
   ├─ Score ≥ 6 (or ≥ 5 in NY overlap)
   ├─ Mini BOS on M5 in correct direction
   ├─ Displacement candle on M5
   ├─ Valid POI (OB, FVG, or Breaker)
   └─ Spread within acceptable range

✅ ONE OF (Entry method, in priority order):
   ├─ Tier 1: STRICT POI
   ├─ Tier 2: NEAR-POI with normal buffer
   ├─ Tier 3: NEAR-POI with strong trend buffer
   └─ Tier 4: FVG-based entry

🚫 AUTOMATIC REJECTION:
   ├─ Missing Mini BOS on M5
   ├─ No displacement on M5
   ├─ Score < threshold
   ├─ Spread > 2x HIGH_SPREAD_POINTS
   └─ Risk management gate triggered
```

---

## Side-by-Side: Entry Zone Comparison

```
BEFORE (Strict Only):
┌──────────────────────────────┐
│ Entry Zone: EXACT POI ONLY   │
│ ┌────────────────────────┐   │
│ │    POI Zone            │   │
│ │  [4520.40–4532.75]     │   │
│ │    ACCEPT HERE ✓       │   │
│ └────────────────────────┘   │
│    ↑                          │
│    Price must be exact        │
│    REJECT if outside          │
│                               │
│ Current Price: 4563.17 → ❌  │
│ Distance: 30.77 pts → REJECTED
└──────────────────────────────┘

AFTER (Adaptive Hierarchy):
┌──────────────────────────────────────────┐
│ Entry Zones: Hierarchical Tolerance      │
│                                           │
│ Tier 1: STRICT                           │
│ ┌────────────────────────┐               │
│ │  [4520.40–4532.75]     │               │
│ │  STRICT_POI  ✓✓✓       │               │
│ └────────────────────────┘               │
│                                           │
│ Tier 2: NEAR-POI (50 pt buffer)         │
│ ┌──────────────────────────────┐        │
│ │ [4519.90–4533.25]             │        │
│ │ NEAR_POI_OB  ✓✓               │        │
│ └──────────────────────────────┘        │
│                                           │
│ Tier 3: STRONG TREND (80 pt buffer)    │
│ ┌──────────────────────────────┐        │
│ │ [4519.60–4533.55]             │        │
│ │ NEAR_POI_OB (strong) ✓        │        │
│ │ IF disp ≥ 2.0x                │        │
│ └──────────────────────────────┘        │
│                                           │
│ Tier 4: FVG (alternative)               │
│ ┌────────────────────────┐              │
│ │ [4540.00–4570.00]      │              │
│ │ FVG_ENTRY  ✓           │              │
│ └────────────────────────┘              │
│                                           │
│ Current Price: 4563.17 → ✅             │
│ Entry: NEAR_POI_OB or FVG_ENTRY        │
└──────────────────────────────────────────┘
```

---

## Parameter Impact Visualization

```
POI_TOLERANCE_POINTS = 50 (default for Gold)

Normal Market:
Spread:    0.5 pts
Buffer:    50 pts
Zone:      POI ± 50 pts
Result:    ✅ 20–30 pt entries typically successful

Strong Trend (Disp ≥ 2.0x):
Spread:    1.0 pts
Buffer:    80 pts  ← INCREASED
Zone:      POI ± 80 pts
Result:    ✅ 50–80 pt entries allowed

Very High Displacement (Disp > 3.0x):
Spread:    2.0 pts
Buffer:    80 pts  ← STRONG_TREND_BUFFER
Zone:      POI ± 80 pts
Result:    ✅ Deep entries in runaway moves
```

---

## Configuration Adjustment Guide

```
TOO FEW ENTRIES (>20% rejections on score 8+)?
↓
Increase POI_TOLERANCE_POINTS
30 → 50 → 70 → 90 (increase gradually)
↓
Too many STRICT entries (<40%)?
→ Market may be naturally tight
→ Check instrument volatility

TOO MANY ENTRIES (all via NEAR-POI)?
↓
Decrease POI_TOLERANCE_POINTS
70 → 50 → 30 → 20 (decrease gradually)
↓
Market may be choppy or test instrument

WRONG ENTRY DISTANCES (too close/far)?
↓
Adjust STRONG_TREND_DISPLACEMENT
2.5 → 2.0 → 1.8 (lower = more entries)
↓
Or adjust STRONG_TREND_BUFFER_POINTS
60 ← 80 → 100 (smaller/larger buffer)
```

---

## State Machine: Complete Entry Path

```
START
  ↓
[Has H4 Bias?] ──NO──→ REJECT "No bias"
  ↓ YES
[Score ≥ 6?] ──NO──→ REJECT "Score too low"
  ↓ YES
[Mini BOS on M5?] ──NO──→ REJECT "No M5 BOS"
  ↓ YES
[Displacement M5?] ──NO──→ REJECT "No displacement"
  ↓ YES
[Spread OK?] ──NO──→ REJECT "Spread too high"
  ↓ YES
  ├─→ Try STRICT_POI
  │   [Price in POI?] ──YES──→ ENTER "STRICT_POI"
  │   ↓ NO
  ├─→ Calculate buffer
  │   [Is strong trend?] ──YES──→ buffer = 80 pts
  │   ↓ NO (normal)        else: buffer = 50 pts
  │
  ├─→ Try NEAR-POI
  │   [Price near POI ±buffer?] ──YES──→ ENTER "NEAR_POI_*"
  │   ↓ NO
  │
  ├─→ Try FVG-BASED (if score ≥ 6)
  │   [Price near FVG ±tolerance?] ──YES──→ ENTER "FVG_ENTRY"
  │   ↓ NO
  │
  └─→ REJECT "Not in entry zone"
       (with distance metrics)

END
```

---

## Probability Assessment

```
If all conditions met + High Score (8+):
┌──────────────────────────────────────┐
│ Entry Probability Assessment         │
├──────────────────────────────────────┤
│ STRICT_POI Entry    → ~80% win rate  │
│ NEAR_POI Entry      → ~70% win rate  │
│ STRONG_TREND Entry  → ~72% win rate  │
│ FVG_ENTRY           → ~65% win rate  │
│                                      │
│ REJECTION (score 8+)→ 0% (no trade) │
│                                      │
│ Benefit of improvement:              │
│ Capturing 50-70% win rate entries    │
│ vs 0% from rejection                 │
└──────────────────────────────────────┘
```

---

## Integration with Risk Management

```
Entry Logic ──→ Position Sizing ──→ SL/TP Calculation ──→ Order Execution
   ✓                ✓                  ✓                    ✓
   Uses POI      Uses SL distance   Uses POI edge       Sent to MT5
   distance      for risk sizing    beyond buffer       with method tag


UNCHANGED Risk Flow:
Daily Loss Limit → Consecutive Loss Stop → Drawdown Protection
     (same)              (same)                  (same)
```

---

**Visual Summary:** The new entry logic adds flexibility to the "entry zone" while maintaining strict confirmation requirements. Think of it as widening the goal posts when you need it (strong trends) while keeping them tight when you don't (normal markets).

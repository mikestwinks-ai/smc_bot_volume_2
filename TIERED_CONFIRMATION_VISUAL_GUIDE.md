# 🎯 Tiered Confirmation System - Visual Guide

## Decision Flow Diagram

```
┌─────────────────────────────────────────────────────────────┐
│ ENTRY ATTEMPT STARTS                                        │
└────────────────────┬────────────────────────────────────────┘
                     │
                     ▼
        ┌────────────────────────────┐
        │ STEP 1: Check Displacement │
        │ (Always Required)          │
        └────┬───────────────────────┘
             │
          YES│  NO
             │   └──────────────────────┐
             │                          │
             ▼                          ▼
      ┌─────────────┐          ┌──────────────┐
      │ Continue    │          │ REJECT       │
      └────┬────────┘          │ "No disp"    │
           │                   └──────────────┘
           │
           ▼
  ┌────────────────────────────────────┐
  │ STEP 2: Tiered Confirmation Check  │
  │ (Conditional Mini BOS)             │
  └────┬─────────────────────────────────┘
       │
       ▼
   ┌──────────────────────────┐
   │ displacement >= 2.0?     │
   └───┬──────────────┬───────┘
    YES│              │ NO
       │              └────────────┐
       ▼                           │
   ┌──────────────────┐            │
   │ has_sweep?       │            │
   └───┬────────┬─────┘            │
   YES │        │NO               │
       │        │                 │
       │        ▼                 │
       │  ┌──────────────────┐   │
       │  │ REJECT           │   │
       │  │ "sweep missing"  │   │
       │  └──────────────────┘   │
       │                         │
       ▼                         ▼
   ┌──────────────────┐    ┌──────────────────────────┐
   │ TIER 1 ACCEPT    │    │ displacement >= 1.5?     │
   │ STRONG_DISPLAC.  │    └───┬──────────────┬───────┘
   │ (no BOS needed)  │    YES │              │ NO
   └──────┬───────────┘        │              │
          │                    ▼              │
          │              ┌──────────────┐    │
          │              │ has_bos?     │    │
          │              └───┬──────┬───┘    │
          │              YES │      │ NO    │
          │                  │      │       │
          │                  ▼      ▼       ▼
          │             ┌────────┐ ┌──────────────────┐
          │             │TIER 2  │ │TIER 3 REJECT     │
          │             │ACCEPT  │ │"Weak disp"       │
          │             │BOS_    │ │(<1.5x)           │
          │             │CONFIRM │ └──────────────────┘
          │             │(BOS ok)│
          │             └────┬───┘
          │                  │
          └──────────────────┘
                     │
                     ▼
         ┌─────────────────────────┐
         │ Confirmation PASSED     │
         │ → Continue to POI check │
         └────────────┬────────────┘
                      │
                      ▼
            ┌──────────────────────┐
            │ STEP 3: POI Check    │
            │ (4-tier entry logic) │
            └────────────┬─────────┘
                         │
                    PASS │FAIL
                         │ │
                         │ ▼
                         │ REJECT
                         │
                         ▼
             ┌─────────────────────────┐
             │ STEP 4: SL/TP, Sizing  │
             │ STEP 5: Order Submit   │
             └────────────┬────────────┘
                          │
                          ▼
                    ┌──────────────┐
                    │ TRADE OPENED │
                    └──────────────┘
```

---

## Tier Decision Matrix

```
┌─────────────────────────────────────────────────────────────────────┐
│                    TIERED CONFIRMATION MATRIX                       │
├─────────────────────────┬──────────────┬──────────┬────────────────┤
│ Tier                    │ Displacement │ Mini BOS │ Result         │
├─────────────────────────┼──────────────┼──────────┼────────────────┤
│ 1️⃣  STRONG              │ >= 2.0x      │ ❌ NO   │ ✅ ACCEPT      │
│ (High-Conviction)       │              │ (skip)   │ (if sweep OK)  │
├─────────────────────────┼──────────────┼──────────┼────────────────┤
│ 2️⃣  MEDIUM              │ 1.5-2.0x     │ ✅ YES  │ ✅ ACCEPT      │
│ (Medium-Conviction)     │              │ (req'd)  │ (if BOS OK)    │
├─────────────────────────┼──────────────┼──────────┼────────────────┤
│ 3️⃣  WEAK                │ < 1.5x       │ N/A     │ ❌ REJECT      │
│ (Low-Conviction)        │              │ (n/a)   │ (always)       │
└─────────────────────────┴──────────────┴──────────┴────────────────┘
```

---

## Decision Examples

### Example 1: STRONG Tier + Sweep ✅

```
Scenario:
  ├─ Displacement ratio: 2.4x (>= 2.0) ✅
  ├─ Liquidity sweep: Confirmed ✅
  ├─ Mini BOS: Not found ❌
  └─ HTF bias: Bullish ✅

Decision Path:
  1. Check disp >= 2.0? YES ✅
  2. Check sweep? YES ✅
  3. Return: (True, "STRONG_DISPLACEMENT")

Result: ✅ ENTER (no BOS needed)
Log: ✓ STRONG_DISPLACEMENT entry allowed | Displacement: 2.40x | Mini BOS: skipped | Liquidity sweep: confirmed
```

### Example 2: STRONG Tier + No Sweep ❌

```
Scenario:
  ├─ Displacement ratio: 2.4x (>= 2.0) ✅
  ├─ Liquidity sweep: Not found ❌
  ├─ Mini BOS: Confirmed ✅
  └─ HTF bias: Bullish ✅

Decision Path:
  1. Check disp >= 2.0? YES ✅
  2. Check sweep? NO ❌
  3. Return: (False, "sweep missing")

Result: ❌ REJECT (strong setup needs sweep)
Log: STRONG_DISPLACEMENT detected (2.40x) but liquidity sweep missing
```

### Example 3: MEDIUM Tier + BOS ✅

```
Scenario:
  ├─ Displacement ratio: 1.7x (1.5-2.0) ✅
  ├─ Liquidity sweep: Not confirmed ❌
  ├─ Mini BOS: Confirmed ✅
  └─ HTF bias: Bullish ✅

Decision Path:
  1. Check disp >= 2.0? NO
  2. Check disp >= 1.5? YES ✅
  3. Check BOS? YES ✅
  4. Return: (True, "BOS_CONFIRMED")

Result: ✅ ENTER (BOS validates setup)
Log: ✓ BOS_CONFIRMED entry | Displacement: 1.72x | Mini BOS: confirmed
```

### Example 4: MEDIUM Tier + No BOS ❌

```
Scenario:
  ├─ Displacement ratio: 1.7x (1.5-2.0) ✅
  ├─ Liquidity sweep: Not confirmed ❌
  ├─ Mini BOS: Not found ❌
  └─ HTF bias: Bullish ✅

Decision Path:
  1. Check disp >= 2.0? NO
  2. Check disp >= 1.5? YES ✅
  3. Check BOS? NO ❌
  4. Return: (False, "BOS missing")

Result: ❌ REJECT (needs BOS validation)
Log: Medium displacement (1.72x) requires mini BOS confirmation but BOS not found
```

### Example 5: WEAK Tier ❌

```
Scenario:
  ├─ Displacement ratio: 1.3x (< 1.5) ❌
  ├─ Liquidity sweep: Not confirmed ❌
  ├─ Mini BOS: Confirmed ✅
  └─ HTF bias: Bullish ✅

Decision Path:
  1. Check disp >= 2.0? NO
  2. Check disp >= 1.5? NO ❌
  3. Return: (False, "Weak displacement")

Result: ❌ REJECT (not enough strength)
Log: Weak displacement (1.32x < 1.5) — trade rejected
```

---

## Before vs After Timeline

### BEFORE (Mandatory Mini BOS)

```
Setup arrives with:
  ├─ 2.4x displacement (strong!)
  ├─ Liquidity sweep confirmed (strong signal!)
  └─ NO mini BOS

Result: ❌ REJECTED
Reason: "No mini BOS" (too strict!)
```

### AFTER (Tiered Conditional BOS)

```
Setup arrives with:
  ├─ 2.4x displacement (strong!)
  ├─ Liquidity sweep confirmed (strong signal!)
  └─ NO mini BOS

Result: ✅ ACCEPTED (STRONG_DISPLACEMENT)
Reason: "Strong setup with sweep, BOS not needed"
```

---

## Threshold Visualization

```
Displacement Strength Spectrum
│
│ 2.5x ├──────────────────────┐ TIER 1: STRONG
│ 2.3x │    ✅ ACCEPT         │ entry WITHOUT BOS
│ 2.1x │   (if sweep OK)      │ (higher conviction)
│ 2.0x ├──────────────────────┤
│      │                      │ threshold
│ 1.9x │ TIER 2: MEDIUM       │
│ 1.8x │  ✅ ACCEPT           │
│ 1.7x │ (if BOS OK)          │
│ 1.6x │ (needs structure)    │
│ 1.5x ├──────────────────────┤
│      │                      │ threshold
│ 1.4x │ TIER 3: WEAK         │
│ 1.3x │  ❌ REJECT           │
│ 1.2x │ (too low conviction) │
│ 1.0x │                      │
│      └──────────────────────┘
└─────────────────────────────────
  (Configurable Boundaries)
```

---

## Entry Type Breakdown (Expected)

```
100 Entries Before
  ├─ 60% Medium + BOS (BOS_CONFIRMED)
  ├─ 40% Weak rejection (rejected)
  └─ 0% Strong entries (rejected without BOS)

~130 Entries After (30% more)
  ├─ 40% NEW Strong entries (STRONG_DISPLACEMENT) ⭐
  ├─ 50% Medium + BOS (BOS_CONFIRMED) (mostly unchanged)
  ├─ 40% Weak rejection (rejected) (unchanged)
  └─ Total: ~130 entries (more participation)
```

---

## Configuration Tuning Spectrum

```
        Fewer Entries ◄─────► More Entries
                 ↓              ↓
               (2.2)          (1.8)
  ├────────────────────────┤
  ├────────────────────────┤ STRONG_DISPLACEMENT_THRESHOLD
  │                        │
  │      DEFAULT (2.0)     │
  │     ✓ Recommended      │
  ├────────────────────────┤

  ├────────────────────────┤
  ├────────────────────────┤ MEDIUM_DISPLACEMENT_THRESHOLD
  │      DEFAULT (1.5)     │
  │     ✓ Recommended      │
  ├────────────────────────┤
```

---

## Signal Quality Comparison

```
BEFORE: All entries filtered by mini BOS
┌──────────────────────┐
│ ✅ High quality      │
│ (fewer entries)      │
│ - Filtered by BOS    │
│ - Medium conviction  │
│ - Good win rate      │
│ - Limited by gate    │
└──────────────────────┘

AFTER: Tiers by displacement strength
┌──────────────────────┬──────────────────────┐
│ ✅ STRONG tier       │ ✅ MEDIUM tier       │
│ (new entries!)       │ (same as before)     │
│ + High conviction    │ ✅ Good quality      │
│ + Large moves        │ ✅ Medium conviction │
│ + Sweep validation   │ ✅ Filtered by BOS   │
│ ✅ More entries      │ ✅ Same entries      │
├──────────────────────┼──────────────────────┤
│ Expected: 40% of     │ Expected: 60% of     │
│ total entries        │ total entries        │
└──────────────────────┴──────────────────────┘
```

---

## Implementation Summary Diagram

```
┌─────────────────────────────────────────┐
│  TIERED CONFIRMATION SYSTEM             │
├─────────────────────────────────────────┤
│                                         │
│ Input Data:                             │
│  ├─ confluence.displacement_ratio       │
│  ├─ confluence.sweep (present/absent)   │
│  ├─ mini BOS (detected/not detected)    │
│  └─ confluence.direction                │
│                                         │
├─────────────────────────────────────────┤
│ Processing:                             │
│  └─ _validate_entry_confirmation()      │
│     ├─ Tier 1 check (>= 2.0)            │
│     ├─ Tier 2 check (>= 1.5)            │
│     └─ Tier 3 (< 1.5)                   │
│                                         │
├─────────────────────────────────────────┤
│ Output:                                 │
│  ├─ (True, "STRONG_DISPLACEMENT")       │
│  ├─ (True, "BOS_CONFIRMED")             │
│  └─ (False, rejection_reason)           │
│                                         │
├─────────────────────────────────────────┤
│ Logging:                                │
│  ├─ ✅ Accepted: INFO level             │
│  └─ ❌ Rejected: DEBUG level             │
│                                         │
├─────────────────────────────────────────┤
│ Trade Comments:                         │
│  └─ SMC_POI_SNN_{CONFIRMATION}_{METHOD} │
│                                         │
└─────────────────────────────────────────┘
```

---

## Quick Reference Cheatsheet

```
╔════════════════════════════════════════════════════════════╗
║        TIERED CONFIRMATION QUICK REFERENCE               ║
╠════════════════════════════════════════════════════════════╣
║ TIER 1: STRONG                                            ║
║ ─────────────────────────────────────────────────────────  ║
║ IF:     displacement >= 2.0 AND liquidity_sweep           ║
║ THEN:   ✅ ENTER (no BOS needed)                          ║
║ TYPE:   STRONG_DISPLACEMENT                              ║
║ EXPECT: ~40% of new entries                              ║
║                                                            ║
║ TIER 2: MEDIUM                                            ║
║ ─────────────────────────────────────────────────────────  ║
║ IF:     1.5 <= displacement < 2.0 AND mini_BOS            ║
║ THEN:   ✅ ENTER (BOS validates)                          ║
║ TYPE:   BOS_CONFIRMED                                     ║
║ EXPECT: ~50% of entries (unchanged)                       ║
║                                                            ║
║ TIER 3: WEAK                                              ║
║ ─────────────────────────────────────────────────────────  ║
║ IF:     displacement < 1.5                                ║
║ THEN:   ❌ REJECT (low conviction)                        ║
║ TYPE:   (rejected)                                        ║
║ EXPECT: ~40% rejections (unchanged)                       ║
║                                                            ║
╠════════════════════════════════════════════════════════════╣
║ CONFIGURATION (in .env)                                  ║
║ ─────────────────────────────────────────────────────────  ║
║ STRONG_DISPLACEMENT_THRESHOLD = 2.0 (default)            ║
║ MEDIUM_DISPLACEMENT_THRESHOLD = 1.5 (default)            ║
║                                                            ║
║ TUNING:                                                    ║
║ → More entries: lower thresholds (1.8 / 1.3)             ║
║ → Fewer entries: raise thresholds (2.2 / 1.7)            ║
║                                                            ║
╚════════════════════════════════════════════════════════════╝
```

---

**Use this visual guide to understand the tiered system at a glance!** 🎯

# SMC Trading Bot — MetaTrader 5

A production-ready Python trading bot implementing **Smart Money Concepts (SMC)** and **ICT methodology** for XAUUSD (Gold) on MetaTrader 5 via Exness.

---

## Features

| Feature          | Details                                               |
| ---------------- | ----------------------------------------------------- |
| Platform         | MetaTrader 5 (Python API)                             |
| Symbol           | XAUUSDm                                               |
| Broker           | Exness                                                |
| Timeframes       | H4 (bias) → M15 (setup) → M5 (entry)                  |
| Session logic    | EAT (UTC+3) — Asia/Active/NY Overlap/Lock             |
| SMC models       | OB, FVG, Breaker, Mitigation, Liquidity, Structure    |
| Risk management  | Dynamic lot sizing, drawdown protection, daily limits |
| Trade management | Profit lock (1.5R), time rule (8h), partial close     |
| Logging          | Colourised console + daily rotating log files         |

---

## Project Structure

```
smc_bot/
├── main.py                  # Entry point & main loop
├── config/
│   ├── settings.py          # All parameters and .env loader
│   └── sessions.py          # EAT session windows & gates
├── models/
│   ├── structure_model.py   # Swing H/L, HH/HL/LH/LL, BOS, CHoCH
│   ├── liquidity_model.py   # Equal H/L pools & sweep detection
│   ├── ob_model.py          # Order Block detection
│   ├── fvg_model.py         # Fair Value Gap detection
│   ├── breaker_model.py     # Breaker Block detection
│   └── mitigation_model.py  # Mitigation Block detection
├── strategy/
│   ├── bias_engine.py       # H4 directional bias
│   └── confluence_engine.py # SMC scoring system
├── execution/
│   ├── entry_engine.py      # M5 entry conditions & order submission
│   ├── risk_manager.py      # Lot sizing, drawdown, daily limits
│   └── trade_manager.py     # Active position management
├── utils/
│   ├── logger.py            # Structured logging
│   └── mt5_connector.py     # All MT5 API interaction
├── logs/                    # Auto-created log files
├── .env                     # Credentials (never commit!)
├── requirements.txt
└── README.md
```

---

## Prerequisites

- **Windows OS** (MT5 Python API is Windows-only)
- **Python 3.11+** (64-bit)
- **MetaTrader 5** installed and logged into your Exness account
- **VS Code** (recommended)

---

## Installation

```bash
# 1. Clone / download the project
cd smc_bot

# 2. Create a virtual environment
python -m venv venv
venv\Scripts\activate      # Windows

# 3. Install dependencies
pip install -r requirements.txt

# 4. Configure credentials
copy .env .env              # edit .env with your details
```

### Edit `.env`

```env
MT5_LOGIN=12345678
MT5_PASSWORD=your_password_here
MT5_SERVER=Exness-MT5Real
SYMBOL=XAUUSDm
RISK_PERCENT=0.5
MAX_DAILY_TRADES=3
MAX_DAILY_LOSS_PERCENT=2.0
```

---

## Running the Bot

```bash
# Make sure venv is active
python main.py
```

The bot will:

1. Connect to MT5 and log account info
2. Enter the main loop (60-second intervals)
3. Log every decision (trade or no-trade) to console and `logs/`

**Stop gracefully:** Press `Ctrl+C` — the bot will close all open positions before exiting.

---

## Session Logic (EAT = UTC+3)

| Window     | Time        | Action                              |
| ---------- | ----------- | ----------------------------------- |
| Asia       | 03:00–11:00 | No entries. Mark liquidity.         |
| Active     | 11:00–23:00 | Entries allowed                     |
| NY Overlap | 16:00–19:00 | Highest priority (Score=5 accepted) |
| Entry Lock | 23:00+      | No new entries; manage existing     |
| Friday     | 18:00 EAT   | Force-close all positions           |
| Friday     | 23:00 EAT   | Disable new entries                 |
| Weekend    | Sat–Sun     | No trading                          |

---

## Scoring System

| Factor          | Points |
| --------------- | ------ |
| HTF Bias (H4)   | +2     |
| Liquidity Sweep | +2     |
| Displacement    | +2     |
| Order Block     | +1     |
| Fair Value Gap  | +1     |
| Breaker Block   | +2     |
| CHoCH (M5)      | +1     |
| **Maximum**     | **11** |

- Score **≥ 6** → trade always
- Score **= 5** → trade only during NY Overlap (16:00–19:00 EAT)
- Score **< 5** → no trade

---

## Risk Rules

| Rule               | Value                |
| ------------------ | -------------------- |
| Risk per trade     | 0.5% of balance      |
| Max trades/day     | 3                    |
| Max daily loss     | 2%                   |
| Consecutive losses | 2 → pause            |
| Drawdown 5%        | Reduce risk to 0.25% |
| Drawdown 10%       | Halt bot             |

---

## Tiered Entry Confirmation System

**NEW:** Entry confirmation is now based on **displacement strength**. Mini BOS is conditional, not mandatory.

### Decision Logic

| Tier       | Condition                | BOS Required | Action                        |
| ---------- | ------------------------ | ------------ | ----------------------------- |
| **STRONG** | displacement ≥ 2.0       | ❌ NO        | ✅ ENTER (if sweep confirmed) |
| **MEDIUM** | 1.5 ≤ displacement < 2.0 | ✅ YES       | ✅ ENTER (if BOS present)     |
| **WEAK**   | displacement < 1.5       | N/A          | ❌ REJECT                     |

### What This Means

- **High-conviction setups** (2.0x+ displacement with liquidity sweep) → Entry WITHOUT mini BOS
- **Medium setups** (1.5–2.0x displacement) → Entry WITH mini BOS (unchanged)
- **Weak setups** (< 1.5x displacement) → Rejected (unchanged)

### Expected Impact

- ~15–30% more entries (mostly STRONG_DISPLACEMENT type)
- Win rate: same or improved
- Safety: preserved (displacement always checked, sweep used for validation)

### Configuration

Both thresholds are configurable in `.env`:

```env
# Default values (ready to use)
STRONG_DISPLACEMENT_THRESHOLD=2.0
MEDIUM_DISPLACEMENT_THRESHOLD=1.5

# For more entries (more aggressive):
STRONG_DISPLACEMENT_THRESHOLD=1.8
MEDIUM_DISPLACEMENT_THRESHOLD=1.3

# For fewer entries (more selective):
STRONG_DISPLACEMENT_THRESHOLD=2.2
MEDIUM_DISPLACEMENT_THRESHOLD=1.7
```

### Trade Comments

Trade comments now include the confirmation type:

```
SMC_OB_S11_STRONG_DISPLACEMENT_NEAR_POI_OB
            ↑ confirmation type (STRONG_DISPLACEMENT or BOS_CONFIRMED)
```

### Log Examples

#### ✅ Accepted (STRONG)

```
✓ STRONG_DISPLACEMENT entry allowed | Displacement: 2.40x | Mini BOS: skipped | Liquidity sweep: confirmed
```

#### ✅ Accepted (MEDIUM)

```
✓ BOS_CONFIRMED entry | Displacement: 1.72x | Mini BOS: confirmed
```

#### ❌ Rejected (No Sweep)

```
STRONG_DISPLACEMENT detected (2.40x) but liquidity sweep missing
```

#### ❌ Rejected (No BOS)

```
Medium displacement (1.72x) requires mini BOS confirmation but BOS not found
```

#### ❌ Rejected (Weak)

```
Weak displacement (1.32x < 1.5) — trade rejected
```

### Documentation

For detailed information on the tiered confirmation system:

- **Quick start:** [TIERED_CONFIRMATION_QUICKSTART.md](TIERED_CONFIRMATION_QUICKSTART.md)
- **Quick reference:** [TIERED_CONFIRMATION_QUICK_REF.md](TIERED_CONFIRMATION_QUICK_REF.md)
- **Full details:** [TIERED_CONFIRMATION_REFACTORING.md](TIERED_CONFIRMATION_REFACTORING.md)
- **Index:** [DOCUMENTATION_INDEX.md](DOCUMENTATION_INDEX.md)

---

## Trade Management

1. **Profit lock** — at ≥ 1.5R, SL moves to entry + 0.5R
2. **Time rule** — trade open ≥ 8 hours → partial close (50%) + SL to B/E
3. **Spread filter** — no SL modifications when spread > 50 points

---

## Log Files

Located in `logs/smc_bot_YYYY-MM-DD.log`. Examples:

```
10:35:22 | INFO     | NO TRADE | Reason: Asia session | session: ASIA
10:35:22 | INFO     | H4 Bias: bullish | Confidence: 7.5/10
16:03:11 | INFO     | SIGNAL ▶ BULLISH | Score: 8 | POI: OB [1985.50–1988.20]
16:03:11 | INFO     | TRADE OPENED ✔ | Ticket: 1234567 | BUY XAUUSDm | ...
16:45:00 | INFO     | SL MOVED | Ticket: 1234567 | 1984.00 → 1986.50 | Profit lock at 1.7R
```

---

## Disclaimer

This bot is provided for **educational purposes**. Algorithmic trading involves substantial risk. Always test on a **demo account** before using live funds. Past performance does not guarantee future results.

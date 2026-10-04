"""
settings.py — Central configuration for the SMC Trading Bot.
All constants and tuneable parameters live here.
"""

import os
from dotenv import load_dotenv

load_dotenv()

# ─────────────────────────────────────────────
# MT5 CONNECTION
# ─────────────────────────────────────────────
MT5_LOGIN    = int(os.getenv("MT5_LOGIN", 0))
MT5_PASSWORD = os.getenv("MT5_PASSWORD", "")
MT5_SERVER   = os.getenv("MT5_SERVER", "Exness-MT5Real")

# ─────────────────────────────────────────────
# SYMBOL
# ─────────────────────────────────────────────
SYMBOL      = os.getenv("SYMBOL", "XAUUSDm")
MAGIC       = 202401          # unique magic number for this bot
DEVIATION   = 20              # max price deviation in points

# ─────────────────────────────────────────────
# TIMEFRAMES  (MT5 constants assigned at runtime)
# ─────────────────────────────────────────────
TF_H4  = None   # set in mt5_connector after MT5 import
TF_M15 = None
TF_M5  = None

# ─────────────────────────────────────────────
# RISK MANAGEMENT
# ─────────────────────────────────────────────
RISK_PERCENT            = float(os.getenv("RISK_PERCENT", 0.5))      # % per trade
MAX_DAILY_TRADES        = int(os.getenv("MAX_DAILY_TRADES", 3))
MAX_DAILY_LOSS_PERCENT  = float(os.getenv("MAX_DAILY_LOSS_PERCENT", 2.0))
CONSECUTIVE_LOSS_LIMIT  = 2      # stop after N consecutive losses
DRAWDOWN_REDUCE_PCT     = 5.0    # reduce risk at this drawdown %
DRAWDOWN_STOP_PCT       = 10.0   # stop bot at this drawdown %
REDUCED_RISK_PERCENT    = 0.25   # risk % when drawdown triggers reduce

# ─────────────────────────────────────────────
# TRADE MANAGEMENT
# ─────────────────────────────────────────────
PROFIT_LOCK_R           = 1.5    # move SL to lock profit at X R
MAX_TRADE_HOURS         = 8      # tighten/close after this many hours
HIGH_SPREAD_POINTS      = 50     # avoid SL mods above this spread (points)
PARTIAL_CLOSE_PCT       = 0.5    # close 50% of position on time rule

# ─────────────────────────────────────────────
# SMC PARAMETERS
# ─────────────────────────────────────────────
SWING_LOOKBACK          = 5      # bars either side to confirm swing
LIQUIDITY_TOLERANCE_PCT = 0.0015 # 0.15% price tolerance for equal H/L
DISPLACEMENT_MULTIPLIER = 1.5    # body must be Nx avg of last 10 candles
DISPLACEMENT_LOOKBACK   = 10     # candles used for avg body calc
FVG_MIN_GAP_POINTS      = 5      # minimum FVG size to be valid

# ─────────────────────────────────────────────
# ENTRY LOGIC (ADAPTIVE)
# ─────────────────────────────────────────────
# POI Tolerance Buffer: allows entry if price is within N points of POI edge
POI_TOLERANCE_POINTS    = int(os.getenv("POI_TOLERANCE_POINTS", 50))

# Near-POI Entry: enter if price within this distance AND score is high & conditions met
NEAR_POI_PROXIMITY_POINTS = int(os.getenv("NEAR_POI_PROXIMITY_POINTS", 30))

# Strong Trend Detection: if displacement >= this, reduce POI strictness
STRONG_TREND_DISPLACEMENT  = float(os.getenv("STRONG_TREND_DISPLACEMENT", 2.0))

# Strong Trend Buffer: larger tolerance when in strong trend (points)
STRONG_TREND_BUFFER_POINTS = int(os.getenv("STRONG_TREND_BUFFER_POINTS", 80))

# FVG Entry Tolerance: allow entry if price within N points of FVG boundary
FVG_ENTRY_TOLERANCE_POINTS = int(os.getenv("FVG_ENTRY_TOLERANCE_POINTS", 20))

# ─────────────────────────────────────────────
# ENTRY CONFIRMATION (TIERED BY DISPLACEMENT)
# ─────────────────────────────────────────────
# STRONG_DISPLACEMENT: >= this threshold allows entry WITHOUT mini BOS
STRONG_DISPLACEMENT_THRESHOLD = float(os.getenv("STRONG_DISPLACEMENT_THRESHOLD", 2.0))

# MEDIUM: < STRONG but >= this requires mini BOS confirmation
MEDIUM_DISPLACEMENT_THRESHOLD = float(os.getenv("MEDIUM_DISPLACEMENT_THRESHOLD", 1.5))

# ─────────────────────────────────────────────
# SCORING THRESHOLDS
# ─────────────────────────────────────────────
MIN_SCORE_ALWAYS        = 6
MIN_SCORE_NY_ONLY       = 5

# ─────────────────────────────────────────────
# CANDLE HISTORY (bars to fetch per TF)
# ─────────────────────────────────────────────
H4_BARS  = 200
M15_BARS = 300
M5_BARS  = 200

# ─────────────────────────────────────────────
# BOT LOOP
# ─────────────────────────────────────────────
LOOP_SLEEP_SECONDS = 60   # main loop interval

# Production hardening (watchdog / recovery)
WATCHDOG_FREEZE_MULTIPLIER = 5.0
WATCHDOG_MAX_CONSECUTIVE_EXCEPTIONS = 5
MT5_RECOVERY_COOLDOWN_SECONDS = 120
LOGGER_HEALTH_INTERVAL_SECONDS = 300

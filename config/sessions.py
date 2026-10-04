"""
sessions.py — Session windows and time-gate logic.
All times are EAT (UTC+3).
"""

from datetime import datetime, time, timezone, timedelta
import pytz

EAT = pytz.timezone("Africa/Nairobi")   # UTC+3 — covers EAT


# ─── Session windows (EAT, 24h) ──────────────────────────────────────────────
ASIA_START   = time(3, 0)
ASIA_END     = time(11, 0)

ACTIVE_START = time(11, 0)
ACTIVE_END   = time(23, 0)

ENTRY_LOCK   = time(21, 30)

# ─── DAILY INTRADAY FLATTENING WINDOWS (Mon-Fri) ──────────────────────────
# Every trading day must have zero overnight exposure
AGGRESSIVE_MANAGEMENT_START = time(22, 0)    # Begin tighter protection
PROACTIVE_FLATTENING_START  = time(22, 15)   # Actively close positions
HARD_FLATTEN_START          = time(22, 45)   # Aggressive forced close
HARD_FLATTEN_END            = time(22, 55)   # Hard close window
EMERGENCY_CUTOFF_TIME       = time(23, 5)    # Final emergency cutoff

# Overlap windows inside ACTIVE
ASIAN_LONDON_START = time(11, 0)
ASIAN_LONDON_END   = time(12, 0)

LONDON_KZ_START    = time(11, 0)
LONDON_KZ_END      = time(14, 0)

NY_OVERLAP_START   = time(16, 0)
NY_OVERLAP_END     = time(19, 0)

# Friday close rule
FRIDAY_CLOSE_HOUR  = 18   # 18:00 EAT — close all trades
FRIDAY_ENTRY_LOCK  = 23   # 23:00 EAT — disable new entries


def _now_eat() -> datetime:
    return datetime.now(EAT)


def current_session() -> str:
    """Return human-readable current session name."""
    now = _now_eat()
    t   = now.time()

    if now.weekday() in (5, 6):
        return "WEEKEND"

    if t >= ACTIVE_START and t < ACTIVE_END:
        if t >= NY_OVERLAP_START and t < NY_OVERLAP_END:
            return "NY_OVERLAP"
        if t >= LONDON_KZ_START and t < LONDON_KZ_END:
            return "LONDON_KZ"
        return "ACTIVE"

    if t >= ASIA_START and t < ASIA_END:
        return "ASIA"

    if t >= ENTRY_LOCK:
        return "ENTRY_LOCK"

    return "OFF"


def can_open_trade() -> tuple[bool, str]:
    """
    Returns (allowed: bool, reason: str).
    True  → new entries permitted.
    False → blocked; reason explains why.
    """
    from execution.startup_gate import is_trading_ready

    if not is_trading_ready():
        return False, "MT5 reconciliation not complete"

    now = _now_eat()
    t   = now.time()
    wd  = now.weekday()   # 0=Mon … 6=Sun

    if wd == 6 or wd == 5:                       # Saturday / Sunday
        return False, "Weekend — no trading"

    if wd == 4 and t >= time(FRIDAY_ENTRY_LOCK, 0):  # Friday ≥23:00
        return False, "Friday entry lock (23:00 EAT)"

    if t < ASIA_END:                              # Before 11:00
        return False, f"Asia session — entry not allowed (current={t})"

    if t >= ENTRY_LOCK:                           # After 21:30
        return False, f"Entry lock after 21:30 (current={t})"

    return True, "Active window"


def must_close_all() -> tuple[bool, str]:
    """
    Return True when all open trades must be force-closed immediately.
    Uses EAT timezone (UTC+3) as authoritative source.
    
    Trigger conditions:
    - Friday >= 18:00 EAT (market close, prevent overnight exposure)
    - Saturday (24h)
    - Sunday (24h until market opens Monday)
    """
    now = _now_eat()
    t   = now.time()
    wd  = now.weekday()
    
    # Friday at close time
    if wd == 4 and t >= time(FRIDAY_CLOSE_HOUR, 0):
        mins_until = 0
        return True, f"Friday {FRIDAY_CLOSE_HOUR}:00 EAT close | Prevent overnight exposure"
    
    # Full weekend (Saturday/Sunday)
    if wd in (5, 6):
        day_name = "Saturday" if wd == 5 else "Sunday"
        return True, f"{day_name} overnight protection"
    
    return False, ""


def check_market_close_approaching(log=None) -> tuple[bool, str]:
    """
    Check if market close is approaching soon (< 30 minutes).
    Used to provide advance warning and block new entries.
    
    Args:
        log: Optional logger instance for observability (may be called with or without)
    
    Returns (is_close_approaching, reason)
    """
    now = _now_eat()
    t   = now.time()
    wd  = now.weekday()
    
    # Friday approaching 18:00
    if wd == 4:
        close_time = time(FRIDAY_CLOSE_HOUR, 0)
        mins_until = (close_time.hour * 60 + close_time.minute) - (t.hour * 60 + t.minute)
        
        if 0 < mins_until <= 30:
            reason = f"Market closes in {mins_until}m | Block new entries"
            if log:
                log.warning(f"MARKET CLOSE APPROACH | {reason}")
            return True, reason
    
    return False, ""


def is_ny_overlap() -> bool:
    now = _now_eat()
    t   = now.time()
    return NY_OVERLAP_START <= t < NY_OVERLAP_END


def session_score_multiplier() -> float:
    """NY overlap gets a small priority boost (used in confluence)."""
    return 1.0 if not is_ny_overlap() else 1.2


def get_asian_session_high_low(df_h4) -> tuple[float, float]:
    """
    Extract Asian session high/low from H4 data.
    
    Asian Session: 03:00 - 11:00 EAT
    On H4 timeframe, this spans roughly 2-3 candles depending on UTC offset.
    
    Returns: (asian_high, asian_low) or (None, None) if insufficient data
    """
    if df_h4 is None or len(df_h4) < 3:
        return None, None
    
    try:
        # Last 3 H4 candles should contain most of Asian session
        # (H4 closes at: 00:00, 04:00, 08:00, 12:00 EAT, etc.)
        recent = df_h4.tail(3)
        asian_high = recent['High'].max()
        asian_low = recent['Low'].min()
        return float(asian_high), float(asian_low)
    except Exception as e:
        return None, None


def get_asian_session_context(df_h4) -> dict:
    """
    Calculate Asian session context (high, low, range, midpoint).
    Used for market positioning awareness (premium/discount).
    
    Returns dict with keys: 'high', 'low', 'range', 'midpoint'
    or empty dict if calculation failed
    """
    asian_h, asian_l = get_asian_session_high_low(df_h4)
    
    if asian_h is None or asian_l is None:
        return {}
    
    context = {
        'asian_high': asian_h,
        'asian_low': asian_l,
        'asian_range': asian_h - asian_l,
        'asian_midpoint': (asian_h + asian_l) / 2.0,
    }
    return context


# ─── DAILY INTRADAY FLATTENING PHASES (Session State) ─────────────────────
# Tracks current phase for transition logging and behavioral changes
_CURRENT_DAILY_PHASE = None
_PHASE_TRANSITION_LOGGED = False


def _get_daily_intraday_phase() -> tuple[str, str]:
    """
    Determine current daily intraday flattening phase (Mon-Fri).
    Returns (phase_name, description) or ("OFF", "Not trading hours")
    
    Phases (EVERY trading day):
      NORMAL_SESSION (11:00-21:30): Normal entries and management
      ENTRY_LOCK (21:30-22:00): No new entries, normal management
      AGGRESSIVE_MANAGEMENT (22:00-22:15): Tighter protection, no new entries
      PROACTIVE_FLATTENING (22:15-22:45): Actively flatten positions
      HARD_FLATTEN (22:45-22:55): Aggressive forced close ALL positions
      EMERGENCY_CUTOFF (22:55-23:05): Final verification, emergency close
    """
    now = _now_eat()
    t = now.time()
    wd = now.weekday()
    
    # Only applies Mon-Fri (0-4)
    if wd >= 5:
        return "WEEKEND", "Weekend — no trading"
    
    # Before 11:00 or after 23:05
    if t < ACTIVE_START or t >= EMERGENCY_CUTOFF_TIME:
        return "OFF", "Outside trading hours"
    
    # Phase transitions
    if t >= EMERGENCY_CUTOFF_TIME:
        return "EMERGENCY_CUTOFF", "Emergency final cutoff (23:05+)"
    elif t >= HARD_FLATTEN_START:
        return "HARD_FLATTEN", "Hard flatten window (close ALL)"
    elif t >= PROACTIVE_FLATTENING_START:
        return "PROACTIVE_FLATTENING", "Actively flatten positions"
    elif t >= AGGRESSIVE_MANAGEMENT_START:
        return "AGGRESSIVE_MANAGEMENT", "Tighten protection"
    elif t >= ENTRY_LOCK:
        return "ENTRY_LOCK", "Entry locked, management only"
    else:
        return "NORMAL_SESSION", "Normal entries and management"


def get_daily_intraday_phase() -> tuple[str, str]:
    """
    Get current daily intraday phase and log transitions only once per phase.
    
    Returns (phase_name, description)
    """
    global _CURRENT_DAILY_PHASE, _PHASE_TRANSITION_LOGGED
    
    phase, desc = _get_daily_intraday_phase()
    
    # Log transition ONLY when phase changes
    if phase != _CURRENT_DAILY_PHASE:
        _CURRENT_DAILY_PHASE = phase
        _PHASE_TRANSITION_LOGGED = False
        # Caller should log the transition using logger
    
    return phase, desc


def should_log_phase_transition() -> bool:
    """Check if we should log a phase transition (only once per phase)."""
    global _PHASE_TRANSITION_LOGGED
    if _PHASE_TRANSITION_LOGGED:
        return False
    _PHASE_TRANSITION_LOGGED = True
    return True


def is_aggressive_management_active() -> bool:
    """Check if aggressive management phase is active (22:00+)."""
    phase, _ = _get_daily_intraday_phase()
    return phase in ("AGGRESSIVE_MANAGEMENT", "PROACTIVE_FLATTENING", "HARD_FLATTEN", "EMERGENCY_CUTOFF")


def is_proactive_flattening_active() -> bool:
    """Check if proactive flattening phase is active (22:15+)."""
    phase, _ = _get_daily_intraday_phase()
    return phase in ("PROACTIVE_FLATTENING", "HARD_FLATTEN", "EMERGENCY_CUTOFF")


def is_hard_flatten_window() -> bool:
    """Check if hard flatten window is active (22:45-22:55)."""
    now = _now_eat()
    t = now.time()
    return HARD_FLATTEN_START <= t < HARD_FLATTEN_END and now.weekday() < 5


def is_emergency_cutoff_active() -> bool:
    """Check if emergency cutoff is active (23:05+)."""
    phase, _ = _get_daily_intraday_phase()
    return phase == "EMERGENCY_CUTOFF"

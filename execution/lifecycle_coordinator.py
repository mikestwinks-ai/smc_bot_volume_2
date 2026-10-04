"""
lifecycle_coordinator.py — Deterministic Trade Lifecycle Management

CRITICAL SEPARATION:
  1. STABILIZATION LOCK — Technical broker synchronization (30-120s)
     - Triggered by live position count changes ONLY (not startup)
     - Prevents same-second re-entry during uncertainty
     - Short duration
  
  2. STRATEGIC TRADE COOLDOWN — Post-trade entry prevention
     - Triggered ONLY after confirmed trade closure
     - Direction-aware
     - Reason-based durations (TP, SL, loss, etc.)
     - Long duration (10-15 minutes)

LIFECYCLE STAGES:
  TRADE_SIGNALLED     → Confluence engine identified setup
  TRADE_SUBMITTED     → Order sent to broker
  TRADE_CONFIRMED     → Position opened on MT5
  TRADE_TRACKED       → Position registered in memory
  TRADE_CLOSED        → Position disappeared from broker
  COOLDOWN_STARTED    → Strategic cooldown activated
  LIFECYCLE_COMPLETED → Full cycle finished, state cleaned
"""

import time
from dataclasses import dataclass
from typing import Optional, Dict
from datetime import datetime

from config import settings
from utils.logger import get_logger

log = get_logger(__name__)

# ─── STABILIZATION LOCK (Technical Sync) ──────────────────────────────────
# This ONLY triggers on LIVE position count changes, NOT during startup reconciliation
_STABILIZATION_LOCK_ACTIVE = False
_STABILIZATION_LOCK_UNTIL = 0.0
_STABILIZATION_DURATION = 120  # 2 minutes max

_STARTUP_RECONCILIATION_PHASE = True  # Flag to skip stabilization during startup
_POSITION_COUNT_AT_LAST_CHECK = 0    # Track position count for changes


def mark_startup_complete() -> None:
    """Called after startup reconciliation to enable stabilization lock for runtime changes."""
    global _STARTUP_RECONCILIATION_PHASE
    _STARTUP_RECONCILIATION_PHASE = False
    log.info("STARTUP RECONCILIATION COMPLETE | Stabilization lock now active for runtime events")


def is_in_startup_phase() -> bool:
    """Check if we're currently in startup reconciliation phase."""
    return _STARTUP_RECONCILIATION_PHASE


def engage_stabilization_lock(reason: str, position_count: int) -> None:
    """
    Engage stabilization lock for position count changes ONLY during runtime.
    
    NOT triggered during startup reconciliation.
    
    Args:
        reason: Human-readable reason (e.g., "Position closed")
        position_count: Current position count after change
    """
    global _STABILIZATION_LOCK_ACTIVE, _STABILIZATION_LOCK_UNTIL
    
    if _STARTUP_RECONCILIATION_PHASE:
        log.debug(f"Position count change during startup | Not engaging stabilization lock")
        return
    
    _STABILIZATION_LOCK_ACTIVE = True
    _STABILIZATION_LOCK_UNTIL = time.time() + _STABILIZATION_DURATION
    
    log.warning(
        f"STABILIZATION LOCK ENGAGED | Technical sync required | "
        f"Reason: {reason} | Position count: {position_count} | "
        f"Duration: {_STABILIZATION_DURATION}s"
    )


def is_stabilization_lock_active() -> bool:
    """Check if stabilization lock is still active."""
    global _STABILIZATION_LOCK_ACTIVE, _STABILIZATION_LOCK_UNTIL
    
    if _STABILIZATION_LOCK_ACTIVE:
        if time.time() < _STABILIZATION_LOCK_UNTIL:
            remaining = _STABILIZATION_LOCK_UNTIL - time.time()
            log.debug(f"STABILIZATION ACTIVE | Remaining: {remaining:.1f}s")
            return True
        else:
            _STABILIZATION_LOCK_ACTIVE = False
            log.info("STABILIZATION LOCK EXPIRED | Sync complete")
    
    return False


def check_position_count_change(current_count: int) -> bool:
    """
    Detect position count changes during runtime (after startup).
    
    Returns True if count changed, False otherwise.
    Engages stabilization lock only if change detected during runtime.
    """
    global _POSITION_COUNT_AT_LAST_CHECK
    
    if _POSITION_COUNT_AT_LAST_CHECK == current_count:
        return False  # No change
    
    # Change detected
    previous_count = _POSITION_COUNT_AT_LAST_CHECK
    change = current_count - previous_count
    direction = "decreased" if change < 0 else "increased"
    
    log.warning(
        f"POSITION COUNT CHANGE | Previous: {previous_count} -> Current: {current_count} | "
        f"({direction} by {abs(change)})"
    )
    
    _POSITION_COUNT_AT_LAST_CHECK = current_count
    
    # Only engage stabilization lock if not in startup phase
    if not _STARTUP_RECONCILIATION_PHASE:
        engage_stabilization_lock(
            f"Position count {direction} from {previous_count} to {current_count}",
            current_count
        )
    
    return True


# ─── TRADE LIFECYCLE TELEMETRY ────────────────────────────────────────────

@dataclass
class LifecycleEvent:
    """Record a single lifecycle event for forensic trail."""
    timestamp: float
    event_type: str  # SIGNALLED, SUBMITTED, CONFIRMED, TRACKED, CLOSED, COOLDOWN_STARTED, COMPLETED
    ticket: int
    symbol: str
    direction: str
    details: Dict = None
    
    def __post_init__(self):
        if self.details is None:
            self.details = {}
    
    def to_log_string(self) -> str:
        """Format for logging."""
        time_str = datetime.fromtimestamp(self.timestamp).strftime("%H:%M:%S.%f")[:-3]
        details_str = " | ".join(f"{k}={v}" for k, v in self.details.items())
        return f"{time_str} | {self.event_type:20} | TKT:{self.ticket:8} | {self.direction:8} | {details_str}"


class TradeLifecycleRecord:
    """Complete record of a single trade's lifecycle."""
    
    def __init__(self, ticket: int, symbol: str, direction: str):
        self.ticket = ticket
        self.symbol = symbol
        self.direction = direction
        self.events: list[LifecycleEvent] = []
        self.entry_price = 0.0
        self.closure_price = 0.0
        self.realized_pnl = 0.0
        self.realized_rr = 0.0
        self.closure_reason = ""
        self.cooldown_registered = False
    
    def add_event(self, event_type: str, details: Dict = None) -> None:
        """Record a lifecycle event."""
        event = LifecycleEvent(
            timestamp=time.time(),
            event_type=event_type,
            ticket=self.ticket,
            symbol=self.symbol,
            direction=self.direction,
            details=details or {}
        )
        self.events.append(event)
        log.info(f"LIFECYCLE | {event.to_log_string()}")
    
    def mark_closure(self, reason: str, pnl: float, rr: float) -> None:
        """Record trade closure details."""
        self.closure_reason = reason
        self.realized_pnl = pnl
        self.realized_rr = rr
        self.add_event("TRADE_CLOSED", {
            "reason": reason,
            "pnl": f"{pnl:+.2f}",
            "rr": f"{rr:+.2f}",
        })
    
    def mark_cooldown_started(self, duration_seconds: int, cooldown_reason: str) -> None:
        """Record cooldown activation."""
        self.cooldown_registered = True
        self.add_event("COOLDOWN_STARTED", {
            "duration": f"{duration_seconds}s",
            "reason": cooldown_reason,
            "expires_at": f"+{duration_seconds}s"
        })
    
    def mark_completed(self) -> None:
        """Mark lifecycle as complete."""
        self.add_event("LIFECYCLE_COMPLETED", {})


# Global registry of all trade lifecycles
_TRADE_LIFECYCLES: Dict[int, TradeLifecycleRecord] = {}


def get_or_create_lifecycle(ticket: int, symbol: str, direction: str) -> TradeLifecycleRecord:
    """Get existing or create new lifecycle record."""
    if ticket not in _TRADE_LIFECYCLES:
        _TRADE_LIFECYCLES[ticket] = TradeLifecycleRecord(ticket, symbol, direction)
    return _TRADE_LIFECYCLES[ticket]


def record_lifecycle_event(ticket: int, event_type: str, details: Dict = None) -> None:
    """Record event for a known ticket."""
    if ticket in _TRADE_LIFECYCLES:
        _TRADE_LIFECYCLES[ticket].add_event(event_type, details)


# ─── DETERMINISTIC TRADE CLOSURE PROCESSOR ─────────────────────────────────

def process_trade_closure(
    ticket: int,
    symbol: str,
    direction: str,
    closure_reason: str,
    realized_pnl: float,
    realized_rr: float,
    source: str = "UNKNOWN"
) -> None:
    """
    CANONICAL CLOSURE HANDLER — ALL closure paths must route through this.
    
    Guarantees:
    - Idempotent (safe to call multiple times for same ticket)
    - Registers strategic cooldown
    - Logs complete telemetry
    - Updates lifecycle record
    - Persists state
    - Removes from memory safely
    
    Args:
        ticket: Position ticket
        symbol: Trading symbol
        direction: bullish or bearish
        closure_reason: TP, SL, BE, TIME_RULE, FORCE_CLOSE, RECONCILIATION_CLEANUP, etc.
        realized_pnl: Actual profit/loss in account currency
        realized_rr: Achieved R/R ratio
        source: Where closure was detected (DETECT_AND_PROCESS, MANAGE_POSITION, RECONCILIATION, etc.)
    """
    # Get or create lifecycle record
    lifecycle = get_or_create_lifecycle(ticket, symbol, direction)
    
    # Check if already processed (idempotency)
    if lifecycle.closure_reason:
        log.debug(f"Trade closure already processed | Ticket: {ticket} | Reason: {lifecycle.closure_reason}")
        return
    
    # Record closure
    lifecycle.mark_closure(closure_reason, realized_pnl, realized_rr)
    
    log.warning(
        f"TRADE CLOSED | Ticket: {ticket} | Symbol: {symbol} | Direction: {direction.upper()} | "
        f"Reason: {closure_reason} | PnL: {realized_pnl:+.2f} | RR: {realized_rr:+.2f} | "
        f"Source: {source}"
    )
    
    # Register strategic post-trade cooldown
    register_strategic_cooldown(symbol, direction, closure_reason, ticket)
    
    # Mark completed
    lifecycle.mark_completed()
    
    log.info(f"LIFECYCLE FINALIZED | Ticket: {ticket} | All processing complete")


def register_strategic_cooldown(
    symbol: str,
    direction: str,
    closure_reason: str,
    ticket: int = 0
) -> None:
    """
    Register strategic post-trade cooldown to prevent revenge trading.
    
    Cooldown ONLY starts AFTER confirmed trade closure.
    Cooldown is direction-aware.
    Cooldown persists across restart.
    """
    from execution.entry_engine import register_trade_exit
    
    # Use standard exit cooldown durations
    register_trade_exit(symbol, direction, closure_reason)
    
    # Update lifecycle record
    if ticket > 0 and ticket in _TRADE_LIFECYCLES:
        lifecycle = _TRADE_LIFECYCLES[ticket]
        # Determine cooldown duration based on reason
        from execution.entry_engine import EXIT_COOLDOWN_DURATIONS
        cooldown_secs = EXIT_COOLDOWN_DURATIONS.get(closure_reason, 900)
        lifecycle.mark_cooldown_started(cooldown_secs, closure_reason)
    
    log.warning(
        f"STRATEGIC COOLDOWN REGISTERED | Symbol: {symbol} | Direction: {direction.upper()} | "
        f"Reason: {closure_reason} | Post-trade protection active"
    )


# ─── SIGNAL DEDUPLICATION ───────────────────────────────────────────────────

_LAST_SIGNAL_FINGERPRINT = None
_LAST_SIGNAL_TIME = 0
_SIGNAL_DEDUP_TIMEOUT = 60  # Suppress identical signals for 60 seconds


def calculate_signal_fingerprint(
    direction: str,
    poi_low: float,
    poi_high: float,
    htf_bias: str,
    sweep_type: str,
    displacement_tier: str,
    bos_active: bool
) -> str:
    """
    Create deterministic fingerprint of a signal to detect duplicates.
    
    Fingerprint changes when:
    - Direction changes
    - POI changes
    - HTF bias changes
    - Sweep type changes
    - Displacement tier changes
    - BOS/CHoCH happens
    
    Fingerprint SAME when signal repeated every minute with same structure.
    """
    import hashlib
    
    fingerprint_data = (
        f"{direction}|{poi_low:.2f}|{poi_high:.2f}|{htf_bias}|"
        f"{sweep_type}|{displacement_tier}|{bos_active}"
    )
    return hashlib.md5(fingerprint_data.encode()).hexdigest()


def should_suppress_signal(fingerprint: str, signal_summary: str = "") -> bool:
    """
    Check if signal should be suppressed as duplicate.
    
    Returns True if identical signal within dedup window.
    """
    global _LAST_SIGNAL_FINGERPRINT, _LAST_SIGNAL_TIME
    
    # Check if fingerprint identical and recent
    if fingerprint == _LAST_SIGNAL_FINGERPRINT:
        elapsed = time.time() - _LAST_SIGNAL_TIME
        if elapsed < _SIGNAL_DEDUP_TIMEOUT:
            remaining = _SIGNAL_DEDUP_TIMEOUT - elapsed
            log.debug(
                f"SIGNAL SUPPRESSED | Duplicate within dedup window | "
                f"Remaining: {remaining:.1f}s | {signal_summary}"
            )
            return True
    
    # Update tracking (not suppressed)
    _LAST_SIGNAL_FINGERPRINT = fingerprint
    _LAST_SIGNAL_TIME = time.time()
    return False


def reset_signal_fingerprint(reason: str = "") -> None:
    """
    Reset signal dedup on structure changes.
    
    Called when: BOS, CHoCH, sweep type change, POI change, direction change, etc.
    """
    global _LAST_SIGNAL_FINGERPRINT, _LAST_SIGNAL_TIME
    _LAST_SIGNAL_FINGERPRINT = None
    _LAST_SIGNAL_TIME = 0
    log.info(f"SIGNAL FINGERPRINT RESET | Reason: {reason} | Dedup cleared, next signal will not be suppressed")


# ─── CLEANUP AND DAILY RESET ────────────────────────────────────────────────

def cleanup_daily() -> None:
    """Called at daily reset (midnight)."""
    global _TRADE_LIFECYCLES
    
    # Clear old lifecycle records
    initial_count = len(_TRADE_LIFECYCLES)
    _TRADE_LIFECYCLES.clear()
    
    log.info(f"DAILY CLEANUP | Cleared {initial_count} lifecycle records | Starting fresh day")

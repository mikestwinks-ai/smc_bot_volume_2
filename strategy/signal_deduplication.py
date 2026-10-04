"""
signal_deduplication.py — Suppress Repeated Identical Signals

PROBLEM SOLVED:
  - Bot logs identical signals every minute
  - No confluence change
  - No structure change  
  - Wastes logs, hides real events

SOLUTION:
  - Fingerprint each signal based on key factors
  - Suppress identical fingerprints until reset conditions
  - Reset on structure changes or new POI

FINGERPRINT INCLUDES:
  - Direction
  - POI (Point of Interest)
  - HTF Bias
  - Sweep type
  - Displacement tier
  - Structure state
"""

import time
from hashlib import md5
from typing import Optional
from dataclasses import dataclass

from utils.logger import get_logger

log = get_logger(__name__)

# ─── SIGNAL FINGERPRINTING ────────────────────────────────────────────────

@dataclass
class SignalFingerprint:
    """Unique fingerprint for a trading signal."""
    direction: str
    poi: str  # Point of interest description
    htf_bias: str  # H4 bias direction
    sweep_type: str  # Bullish/Bearish sweep
    displacement_tier: str  # WEAK, MEDIUM, STRONG, VERY_STRONG
    structure_state: str  # Current market structure state
    
    def hash(self) -> str:
        """Generate hash of this fingerprint."""
        fp_str = f"{self.direction}|{self.poi}|{self.htf_bias}|{self.sweep_type}|{self.displacement_tier}|{self.structure_state}"
        return md5(fp_str.encode()).hexdigest()[:12]  # Use first 12 chars


class SignalDeduplicator:
    """Suppress repeated identical signals to reduce log spam."""
    
    def __init__(self, suppress_duration_seconds: int = 300):
        """
        Initialize deduplicator.
        
        Args:
            suppress_duration_seconds: How long to suppress identical fingerprints (default 5 min)
        """
        self.suppress_duration = suppress_duration_seconds
        self.last_signal_fingerprint: Optional[str] = None
        self.last_signal_time: float = 0.0
        self.last_signal_count: int = 0  # How many times this signal was suppressed
    
    def should_log_signal(self, fingerprint: SignalFingerprint) -> tuple[bool, str]:
        """
        Determine if signal should be logged or suppressed.
        
        Returns:
            (should_log, reason)
              - (True, "NEW_SIGNAL" | "STRUCTURE_CHANGED" | "SUPPRESSION_EXPIRED") if should log
              - (False, "DUPLICATE_SUPPRESSED") if should suppress
        """
        current_hash = fingerprint.hash()
        now = time.time()
        
        # First signal ever
        if self.last_signal_fingerprint is None:
            self._register_signal(current_hash, now)
            return True, "FIRST_SIGNAL"
        
        # Check if enough time has passed for suppression to expire
        if now - self.last_signal_time > self.suppress_duration:
            self._register_signal(current_hash, now)
            return True, "SUPPRESSION_EXPIRED"
        
        # Same fingerprint
        if current_hash == self.last_signal_fingerprint:
            self.last_signal_count += 1
            elapsed = now - self.last_signal_time
            remaining = self.suppress_duration - elapsed
            log.debug(
                f"SIGNAL SUPPRESSED | Duplicate fingerprint {current_hash} | "
                f"Occurrences: {self.last_signal_count} | Remaining: {remaining:.1f}s"
            )
            return False, "DUPLICATE_SUPPRESSED"
        
        # Different fingerprint (structure changed, direction changed, POI changed, etc.)
        self._register_signal(current_hash, now)
        return True, "STRUCTURE_CHANGED"
    
    def _register_signal(self, fingerprint_hash: str, timestamp: float) -> None:
        """Register a new signal fingerprint."""
        if self.last_signal_fingerprint and self.last_signal_count > 1:
            log.info(
                f"SIGNAL SUPPRESSION ENDED | Fingerprint: {self.last_signal_fingerprint} | "
                f"Was suppressed for {self.last_signal_count - 1} iterations"
            )
        
        self.last_signal_fingerprint = fingerprint_hash
        self.last_signal_time = timestamp
        self.last_signal_count = 1
        
        log.debug(f"NEW SIGNAL FINGERPRINT REGISTERED | Hash: {fingerprint_hash}")
    
    def get_status(self) -> str:
        """Get current deduplicator status."""
        if self.last_signal_fingerprint is None:
            return "No signals yet"
        
        elapsed = time.time() - self.last_signal_time
        remaining = max(0, self.suppress_duration - elapsed)
        
        return (
            f"Last signal: {self.last_signal_fingerprint} | "
            f"Count: {self.last_signal_count} | "
            f"Suppression expires in: {remaining:.1f}s"
        )


# Global deduplicator instance
_SIGNAL_DEDUPLICATOR = SignalDeduplicator(suppress_duration_seconds=300)  # 5 minutes


def check_signal_duplication(
    direction: str,
    poi: str,
    htf_bias: str,
    sweep_type: str,
    displacement_tier: str,
    structure_state: str
) -> tuple[bool, str]:
    """
    Check if signal should be logged or suppressed.
    
    Returns:
        (should_log_signal, reason_string)
    """
    fingerprint = SignalFingerprint(
        direction=direction,
        poi=poi,
        htf_bias=htf_bias,
        sweep_type=sweep_type,
        displacement_tier=displacement_tier,
        structure_state=structure_state
    )
    
    should_log, reason = _SIGNAL_DEDUPLICATOR.should_log_signal(fingerprint)
    
    return should_log, reason


def get_deduplicator_status() -> str:
    """Get current deduplicator status for logging."""
    return _SIGNAL_DEDUPLICATOR.get_status()


def reset_deduplicator() -> None:
    """Reset deduplicator (call when major structure change occurs)."""
    _SIGNAL_DEDUPLICATOR.last_signal_fingerprint = None
    _SIGNAL_DEDUPLICATOR.last_signal_time = 0.0
    _SIGNAL_DEDUPLICATOR.last_signal_count = 0
    log.info("SIGNAL DEDUPLICATOR RESET | Structure or direction change detected")

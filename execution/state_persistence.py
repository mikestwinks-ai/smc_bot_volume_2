"""
state_persistence.py — Lightweight state persistence for trade recovery.

Periodically saves trade state to JSON for recovery after crashes/restarts.
Restored on bot startup before position reconciliation.

Handles:
  - _TRADE_STATES from trade_manager.py (TradeState objects)
  - Daily risk state from risk_manager.py (RiskState)
"""

import json
import os
from datetime import datetime, date
from dataclasses import asdict
from typing import Optional

from config import settings
from utils.logger import get_logger

log = get_logger(__name__)

STATE_DIR = os.path.join(os.path.dirname(__file__), "..", "logs", "state")
os.makedirs(STATE_DIR, exist_ok=True)

STATE_FILE = os.path.join(STATE_DIR, "trades_state.json")
RISK_STATE_FILE = os.path.join(STATE_DIR, "risk_state.json")


class StateEncoder(json.JSONEncoder):
    """Handle dataclass serialization to JSON."""
    def default(self, obj):
        if hasattr(obj, "__dataclass_fields__"):
            return asdict(obj)
        if isinstance(obj, date):
            return obj.isoformat()
        return super().default(obj)


def save_trade_states(trade_states: dict) -> None:
    """
    Save current trade states to JSON file.
    Called periodically during main loop (e.g., every position update).
    """
    if not trade_states:
        return  # Nothing to save
    
    try:
        with open(STATE_FILE, 'w', encoding='utf-8') as f:
            json.dump(trade_states, f, cls=StateEncoder, indent=2)
        log.debug(f"Saved {len(trade_states)} trade state(s) to {STATE_FILE}")
    except Exception as e:
        log.error(f"Failed to save trade states: {e}")


def load_trade_states() -> Optional[dict]:
    """
    Load trade states from JSON file (on bot startup).
    Returns dict of {ticket -> state_dict} or None if file doesn't exist/invalid.
    """
    if not os.path.exists(STATE_FILE):
        log.debug("No state file found — starting fresh")
        return None
    
    try:
        with open(STATE_FILE, 'r', encoding='utf-8') as f:
            states = json.load(f)
        log.info(f"Loaded {len(states)} trade state(s) from persistent storage")
        return states
    except Exception as e:
        log.error(f"Failed to load trade states: {e} — starting fresh")
        return None


def save_risk_state(risk_state) -> None:
    """
    Save daily risk state to JSON file.
    Called at end of each trading day or on shutdown.
    """
    try:
        with open(RISK_STATE_FILE, 'w', encoding='utf-8') as f:
            json.dump(asdict(risk_state), f, cls=StateEncoder, indent=2)
        log.debug(f"Saved risk state to {RISK_STATE_FILE}")
    except Exception as e:
        log.error(f"Failed to save risk state: {e}")


def load_risk_state() -> Optional[dict]:
    """
    Load risk state from JSON file.
    Returns dict of risk state or None if file doesn't exist/invalid.
    """
    if not os.path.exists(RISK_STATE_FILE):
        log.debug("No risk state file found — starting fresh")
        return None
    
    try:
        with open(RISK_STATE_FILE, 'r', encoding='utf-8') as f:
            state_dict = json.load(f)
        
        # Verify date hasn't changed (daily reset)
        if state_dict.get("day") != datetime.now().strftime("%Y-%m-%d"):
            log.info("Daily state expired — starting fresh")
            return None
        
        log.info(f"Loaded daily risk state from persistent storage")
        return state_dict
    except Exception as e:
        log.error(f"Failed to load risk state: {e} — starting fresh")
        return None


def clear_state_files() -> None:
    """
    Clear all state files (used on clean shutdown or reset).
    """
    try:
        if os.path.exists(STATE_FILE):
            os.remove(STATE_FILE)
            log.debug(f"Cleared {STATE_FILE}")
        if os.path.exists(RISK_STATE_FILE):
            os.remove(RISK_STATE_FILE)
            log.debug(f"Cleared {RISK_STATE_FILE}")
    except Exception as e:
        log.error(f"Failed to clear state files: {e}")


def clear_trades_state_file() -> None:
    """Clear trade state persistence only — preserves risk_state.json."""
    try:
        if os.path.exists(STATE_FILE):
            os.remove(STATE_FILE)
            log.debug(f"Cleared {STATE_FILE} (risk state preserved)")
    except Exception as e:
        log.error(f"Failed to clear trades state file: {e}")


# ── PHASE 4: Cooldown Persistence ────────────────────────────────────────
COOLDOWN_STATE_FILE = os.path.join(STATE_DIR, "cooldown_state.json")


def save_cooldown_state(cooldown_data: dict) -> None:
    """
    Save cooldown state to JSON for recovery after restarts.
    Preserves active exit cooldowns so restart cannot bypass protection.
    
    Args:
        cooldown_data: Dict of {symbol_direction: (exit_time, exit_reason, cooldown_secs)}
    """
    if not cooldown_data:
        return
    
    try:
        # Convert to serializable format
        serializable = {}
        for key, (exit_time, reason, duration) in cooldown_data.items():
            serializable[key] = {
                "exit_time": exit_time,
                "exit_reason": reason,
                "cooldown_secs": duration,
                "saved_at": datetime.now().isoformat()
            }
        
        with open(COOLDOWN_STATE_FILE, 'w', encoding='utf-8') as f:
            json.dump(serializable, f, indent=2)
        log.debug(f"Saved cooldown state: {len(cooldown_data)} entries")
    except Exception as e:
        log.error(f"Failed to save cooldown state: {e}")


def load_cooldown_state() -> dict:
    """
    Load cooldown state from JSON (on bot startup).
    Restores active cooldowns so restart cannot bypass revenge-trading protection.
    
    Returns: Dict of {symbol_direction: (exit_time, exit_reason, cooldown_secs)} or empty dict
    """
    if not os.path.exists(COOLDOWN_STATE_FILE):
        log.debug("No cooldown state file found")
        return {}
    
    try:
        with open(COOLDOWN_STATE_FILE, 'r', encoding='utf-8') as f:
            data = json.load(f)
        
        # Deserialize back to runtime format
        restored = {}
        now_timestamp = datetime.now().timestamp()
        for key, state in data.items():
            exit_time = state.get("exit_time", 0)
            reason = state.get("exit_reason", "")
            cooldown_secs = state.get("cooldown_secs", 900)
            
            # Only restore if cooldown still active
            elapsed = now_timestamp - exit_time
            if elapsed < cooldown_secs:
                restored[key] = (exit_time, reason, cooldown_secs)
                remaining = cooldown_secs - elapsed
                log.warning(
                    f"COOLDOWN STATE RESTORED | Key: {key} | Reason: {reason} | "
                    f"Remaining: {remaining:.0f}s / {cooldown_secs}s"
                )
            else:
                log.debug(f"Cooldown expired for {key} | Not restoring")
        
        return restored
    except Exception as e:
        log.error(f"Failed to load cooldown state: {e}")
        return {}


def clear_cooldown_state() -> None:
    """
    Clear cooldown state file.
    """
    try:
        if os.path.exists(COOLDOWN_STATE_FILE):
            os.remove(COOLDOWN_STATE_FILE)
            log.debug(f"Cleared cooldown state")
    except Exception as e:
        log.error(f"Failed to clear cooldown state: {e}")

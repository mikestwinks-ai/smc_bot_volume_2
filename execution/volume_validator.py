"""
volume_validator.py — Broker volume validation and normalization.

Ensures all volume operations respect broker minimum lot size and volume step.
Prevents invalid orders like partial closes on 0.01 lots.
"""

import MetaTrader5 as mt5
from utils import mt5_connector as conn
from utils.logger import get_logger

log = get_logger(__name__)


def get_volume_constraints(symbol: str) -> dict:
    """
    Fetch broker's volume constraints for a symbol.
    
    Returns dict with:
      - min_lot: minimum tradeable volume
      - max_lot: maximum tradeable volume
      - step_lot: volume step (increment)
    """
    info = mt5.symbol_info(symbol)
    if info is None:
        log.warning(f"Could not get symbol info for {symbol}")
        return {
            'min_lot': 0.01,
            'max_lot': 100.0,
            'step_lot': 0.01,
        }
    
    return {
        'min_lot': float(info.volume_min),
        'max_lot': float(info.volume_max),
        'step_lot': float(info.volume_step),
    }


def normalize_volume(volume: float, step_lot: float) -> float:
    """
    Normalize volume to broker's step requirement.
    Rounds DOWN to avoid exceeding limit.
    
    Example:
      volume=0.005, step_lot=0.01 → 0.00 (invalid, too small)
      volume=0.015, step_lot=0.01 → 0.01 (valid)
      volume=0.025, step_lot=0.01 → 0.02 (valid)
    """
    if step_lot <= 0:
        step_lot = 0.01
    
    steps = int(volume / step_lot)
    normalized = steps * step_lot
    return round(normalized, 2)


def is_volume_valid(volume: float, symbol: str) -> tuple[bool, str]:
    """
    Check if a volume is valid for trading.
    
    Returns: (is_valid, reason)
    """
    constraints = get_volume_constraints(symbol)
    min_lot = constraints['min_lot']
    max_lot = constraints['max_lot']
    step_lot = constraints['step_lot']
    
    if volume < min_lot:
        return False, f"Volume {volume} < minimum {min_lot}"
    
    if volume > max_lot:
        return False, f"Volume {volume} > maximum {max_lot}"
    
    # Check step compliance
    normalized = normalize_volume(volume, step_lot)
    if normalized != volume:
        return False, f"Volume {volume} not aligned to step {step_lot} (nearest valid: {normalized})"
    
    return True, ""


def validate_partial_close(position, close_pct: float = 0.5) -> tuple[bool, str, float]:
    """
    Validate that a partial close is executable.
    
    Returns: (is_valid, reason, validated_close_volume)
    
    If invalid:
      - is_valid=False
      - reason explains why
      - validated_close_volume=0.0
    
    If valid:
      - is_valid=True
      - reason=""
      - validated_close_volume=actual volume to close
    """
    symbol = position.symbol
    constraints = get_volume_constraints(symbol)
    
    # Calculate volume to close
    volume_to_close = position.volume * close_pct
    
    # Normalize to broker step
    normalized_close = normalize_volume(volume_to_close, constraints['step_lot'])
    
    # Check if normalized close volume is valid
    if normalized_close < constraints['min_lot']:
        return (
            False,
            f"Partial close volume {normalized_close} < broker minimum {constraints['min_lot']}",
            0.0
        )
    
    # Check remaining volume after close
    remaining = position.volume - normalized_close
    remaining_normalized = normalize_volume(remaining, constraints['step_lot'])
    
    if remaining_normalized < constraints['min_lot'] and remaining > 0:
        # Remaining would be too small - close entire position instead
        return (
            False,
            f"Remaining volume {remaining} would be < minimum. Recommend full close.",
            0.0
        )
    
    # Valid partial close
    return (
        True,
        "",
        normalized_close
    )

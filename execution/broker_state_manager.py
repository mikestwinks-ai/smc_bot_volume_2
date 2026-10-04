"""
broker_state_manager.py — Broker-First Lifecycle Authority

ARCHITECTURAL PRINCIPLE:
MT5 broker state is the SOLE source of truth for all trade lifecycle.
Internal memory and persistence are caches that must reconcile to broker reality.

LIFECYCLE STATES (Terminal - Monotonic):
  ACTIVE           → Position open on broker
  CLOSED_VERIFIED  → Closure verified in broker deal history
  CLOSED_RECORDED  → Closure recorded to persistence
  ARCHIVED         → All processing complete, moved to history

Transitions are one-way only: ACTIVE → CLOSED_VERIFIED → CLOSED_RECORDED → ARCHIVED

KEY FUNCTIONS:
  get_broker_positions()       → Get authoritative open positions
  get_broker_closed_deals()    → Get today's closed positions
  verify_closure_in_broker()   → Forensic lookup of deal history
  exactly_once_close()         → Guarantee single TRADE_CLOSED event
  reconcile_to_broker()        → Compare memory to broker, restore truth
"""

import time
from datetime import datetime, timezone
from typing import Optional, Dict, List, Tuple
from dataclasses import dataclass, field

try:
    import MetaTrader5 as mt5
except ImportError:
    mt5 = None  # Allow testing without MT5

from config import settings
from utils import mt5_connector as conn
from utils.logger import get_logger

log = get_logger(__name__)

# ════════════════════════════════════════════════════════════════════════════
# PART 1: TERMINAL STATE MACHINE
# ════════════════════════════════════════════════════════════════════════════

@dataclass
class ClosureVerification:
    """Forensic closure verification from broker deal history."""
    verified: bool = False
    deal_ticket: int = 0
    realized_pnl: float = 0.0
    close_price: float = 0.0
    close_time: float = 0.0
    close_time_str: str = ""
    swap: float = 0.0
    commission: float = 0.0
    reason: str = ""
    comment: str = ""
    entry_type: int = -1  # DEAL_ENTRY_OUT = 1


@dataclass
class TerminalTradeState:
    """Trade state with explicit terminal lifecycle."""
    ticket: int
    symbol: str
    direction: str
    entry_price: float
    initial_sl: float
    initial_tp: float
    
    # Terminal state tracking
    lifecycle_state: str = "ACTIVE"  # ACTIVE, CLOSED_VERIFIED, CLOSED_RECORDED, ARCHIVED
    state_timestamp: float = field(default_factory=time.time)
    
    # Closure details (only populated after CLOSED_VERIFIED)
    closure_deal_ticket: int = 0
    closure_reason: str = ""
    closure_verified_pnl: float = 0.0
    closure_verified_rr: float = 0.0
    closure_swap: float = 0.0
    closure_commission: float = 0.0
    closure_timestamp: float = 0.0
    
    # Idempotent processing guards
    close_event_emitted: bool = False
    accounting_recorded: bool = False
    cooldown_registered: bool = False
    
    def transition_to(self, new_state: str) -> bool:
        """
        Monotonic state transition (one-way only).
        
        Valid transitions:
        ACTIVE → CLOSED_VERIFIED
        CLOSED_VERIFIED → CLOSED_RECORDED
        CLOSED_RECORDED → ARCHIVED
        
        Returns True if transition was valid, False if blocked.
        """
        valid_transitions = {
            "ACTIVE": {"CLOSED_VERIFIED"},
            "CLOSED_VERIFIED": {"CLOSED_RECORDED"},
            "CLOSED_RECORDED": {"ARCHIVED"},
            "ARCHIVED": set(),  # Terminal state
        }
        
        if new_state not in valid_transitions.get(self.lifecycle_state, set()):
            log.error(
                f"INVALID STATE TRANSITION | Ticket: {self.ticket} | "
                f"Current: {self.lifecycle_state} | Attempted: {new_state} | BLOCKED"
            )
            return False
        
        old_state = self.lifecycle_state
        self.lifecycle_state = new_state
        self.state_timestamp = time.time()
        
        log.warning(
            f"STATE TRANSITION | Ticket: {self.ticket} | "
            f"{old_state} → {new_state}"
        )
        return True
    
    def can_transition_to(self, new_state: str) -> bool:
        """Check if transition is valid without performing it."""
        valid_transitions = {
            "ACTIVE": {"CLOSED_VERIFIED"},
            "CLOSED_VERIFIED": {"CLOSED_RECORDED"},
            "CLOSED_RECORDED": {"ARCHIVED"},
            "ARCHIVED": set(),
        }
        return new_state in valid_transitions.get(self.lifecycle_state, set())


# ════════════════════════════════════════════════════════════════════════════
# PART 2: BROKER STATE QUERIES (AUTHORITATIVE)
# ════════════════════════════════════════════════════════════════════════════

def get_broker_open_positions(symbol: str = settings.SYMBOL) -> list:
    """
    Get AUTHORITATIVE open positions from broker.
    This is the source of truth.
    """
    positions = conn.get_open_positions(symbol=symbol, magic=settings.MAGIC)
    return positions or []


def get_broker_closed_deals_today(symbol: str = settings.SYMBOL, lookback_hours: int = 24) -> Dict:
    """
    Get AUTHORITATIVE closed deals from broker deal history.
    This is the source of truth for closures.
    """
    try:
        deals = conn.get_deal_history(
            symbol=symbol,
            magic=settings.MAGIC,
            lookback_hours=lookback_hours
        )
        return deals or {"deals": [], "deal_count": 0}
    except Exception as e:
        log.error(f"BROKER DEAL HISTORY QUERY FAILED | Error: {e}")
        return {"deals": [], "deal_count": 0}


def get_broker_position_by_ticket(ticket: int, symbol: str = settings.SYMBOL) -> Optional[object]:
    """Get single position from broker if it exists (None if closed)."""
    positions = get_broker_open_positions(symbol)
    for pos in positions:
        if hasattr(pos, 'ticket') and pos.ticket == ticket:
            return pos
    return None


# ════════════════════════════════════════════════════════════════════════════
# DEAL / POSITION MAPPING (MT5 field variance)
# ════════════════════════════════════════════════════════════════════════════

DEAL_ENTRY_OUT = 1


def resolve_deal_position_id(deal: dict) -> int:
    """
    Resolve MT5 position identifier from a deal dict.
    Entry deals: order == position ticket. Exit deals: often order=0, position_id set.
    """
    position_id = deal.get("position_id") or 0
    if position_id:
        return int(position_id)
    order = deal.get("order") or 0
    if order:
        return int(order)
    return 0


def deal_closes_position(deal: dict, position_ticket: int) -> bool:
    """True if deal is an exit leg for the given position ticket."""
    if deal.get("entry") != DEAL_ENTRY_OUT:
        return False
    order = deal.get("order") or 0
    position_id = deal.get("position_id") or 0
    if position_id and int(position_id) == int(position_ticket):
        return True
    if order and int(order) == int(position_ticket):
        return True
    return False


# ════════════════════════════════════════════════════════════════════════════
# PART 3: FORENSIC CLOSURE VERIFICATION
# ════════════════════════════════════════════════════════════════════════════

def verify_closure_in_broker(
    ticket: int,
    symbol: str = settings.SYMBOL,
    lookback_hours: int = 24
) -> ClosureVerification:
    """
    FORENSIC CLOSURE LOOKUP: Query broker deal history to verify position closure.
    
    Process:
    1. Get deal history for symbol today
    2. Find closing deal with matching ticket
    3. Extract closure details
    4. Verify deal is DEAL_ENTRY_OUT (close)
    
    Returns: ClosureVerification object with details or empty (verified=False)
    """
    verification = ClosureVerification()
    
    try:
        deals_data = get_broker_closed_deals_today(symbol, lookback_hours)
        deals = deals_data.get("deals", [])
        
        if not deals:
            log.debug(f"NO DEALS FOUND | Ticket: {ticket} | Lookback: {lookback_hours}h")
            return verification
        
        # Find closing deal for this ticket (order, position_id, or order=0 + position_id)
        for deal in deals:
            if not deal_closes_position(deal, ticket):
                continue

            # Found it! Extract details
            verification.verified = True
            verification.deal_ticket = deal.get("ticket", 0)
            verification.realized_pnl = deal.get("profit", 0.0)
            verification.close_price = deal.get("price", 0.0)
            verification.close_time = deal.get("time", 0.0)
            verification.close_time_str = deal.get("time_str", "")
            verification.swap = deal.get("swap", 0.0)
            verification.commission = deal.get("commission", 0.0)
            verification.reason = deal.get("reason", "Unknown")
            verification.comment = deal.get("comment", "")
            verification.entry_type = deal.get("entry", -1)
            
            log.warning(
                f"CLOSURE VERIFIED | Ticket: {ticket} | Deal: {verification.deal_ticket} | "
                f"PnL: {verification.realized_pnl:+.2f} | "
                f"Reason: {verification.reason} | Time: {verification.close_time_str}"
            )
            
            return verification
        
        # Deal not found
        log.warning(f"CLOSURE DEAL NOT FOUND | Ticket: {ticket} | Lookback: {lookback_hours}h")
        return verification
    
    except Exception as e:
        log.error(f"CLOSURE VERIFICATION FAILED | Ticket: {ticket} | Error: {e}")
        return verification


# ════════════════════════════════════════════════════════════════════════════
# PART 4: EXACTLY-ONCE CLOSURE PROCESSING
# ════════════════════════════════════════════════════════════════════════════

def _state_ticket(state) -> int:
    return int(getattr(state, "ticket", 0))


def can_emit_close_event(state) -> bool:
    """Check if TRADE_CLOSED event has already been emitted (exactly-once guard)."""
    if getattr(state, "close_event_emitted", False):
        log.debug(
            f"TRADE_CLOSED EVENT ALREADY EMITTED | Ticket: {_state_ticket(state)} | "
            f"Idempotent guard blocks duplicate"
        )
        return False
    return True


def mark_close_event_emitted(state) -> None:
    """Mark TRADE_CLOSED event as emitted (exactly-once guard)."""
    setattr(state, "close_event_emitted", True)
    log.debug(f"TRADE_CLOSED EVENT MARKED | Ticket: {_state_ticket(state)} | No more events allowed")


def can_record_accounting(state) -> bool:
    """Check if accounting has already been recorded (exactly-once guard)."""
    if getattr(state, "accounting_recorded", False):
        log.debug(
            f"ACCOUNTING ALREADY RECORDED | Ticket: {_state_ticket(state)} | "
            f"Idempotent guard blocks duplicate"
        )
        return False
    return True


def mark_accounting_recorded(state) -> None:
    """Mark accounting as recorded (exactly-once guard)."""
    setattr(state, "accounting_recorded", True)
    log.debug(f"ACCOUNTING RECORDED | Ticket: {_state_ticket(state)} | Marked as recorded")


def can_register_cooldown(state) -> bool:
    """Check if cooldown has already been registered (exactly-once guard)."""
    if getattr(state, "cooldown_registered", False):
        log.debug(
            f"COOLDOWN ALREADY REGISTERED | Ticket: {_state_ticket(state)} | "
            f"Idempotent guard blocks duplicate"
        )
        return False
    return True


def mark_cooldown_registered(state) -> None:
    """Mark cooldown as registered (exactly-once guard)."""
    setattr(state, "cooldown_registered", True)
    log.debug(f"COOLDOWN REGISTERED | Ticket: {_state_ticket(state)} | Marked as registered")


# ════════════════════════════════════════════════════════════════════════════
# PART 5: RECONCILIATION ENGINE
# ════════════════════════════════════════════════════════════════════════════

def reconcile_to_broker(
    memory_states: Dict[int, TerminalTradeState],
    symbol: str = settings.SYMBOL
) -> Tuple[Dict[int, TerminalTradeState], List[int], List[int]]:
    """
    RECONCILIATION ENGINE: Compare memory states to broker truth.
    
    Process:
    1. Get broker's open positions
    2. Get broker's closed deals today
    3. For each memory state:
       - If on broker: ACTIVE (keep in memory)
       - If closed deal exists: CLOSED_VERIFIED (needs finalization)
       - If neither: ORPHAN (stale, remove)
    
    Returns: (updated_memory, verified_closures, orphaned_tickets)
    """
    broker_open = get_broker_open_positions(symbol)
    broker_open_tickets = {p.ticket for p in broker_open if hasattr(p, 'ticket')}
    
    broker_deals = get_broker_closed_deals_today(symbol)
    broker_deal_tickets = set()
    for deal in broker_deals.get("deals", []):
        if deal.get("entry") == 1:  # Only closures
            broker_deal_tickets.add(deal.get("order"))
    
    verified_closures = []
    orphaned_tickets = []
    
    log.info(
        f"RECONCILIATION START | Memory states: {len(memory_states)} | "
        f"Broker open: {len(broker_open_tickets)} | Broker closed deals: {len(broker_deal_tickets)}"
    )
    
    for ticket, state in list(memory_states.items()):
        if ticket in broker_open_tickets:
            # Position still open on broker
            if state.lifecycle_state == "ACTIVE":
                log.debug(f"RECONCILIATION | Ticket {ticket} ACTIVE on broker, state consistent")
            else:
                log.warning(
                    f"RECONCILIATION | Ticket {ticket} marked {state.lifecycle_state} "
                    f"but still OPEN on broker | Reverting to ACTIVE"
                )
                state.lifecycle_state = "ACTIVE"
        
        elif ticket in broker_deal_tickets:
            # Position closed on broker, not yet finalized
            if state.lifecycle_state == "ACTIVE":
                log.warning(
                    f"RECONCILIATION | Ticket {ticket} closed on broker but still ACTIVE in memory | "
                    f"Needs closure finalization"
                )
                verified_closures.append(ticket)
            else:
                log.debug(f"RECONCILIATION | Ticket {ticket} already {state.lifecycle_state}")
        
        else:
            # Ticket on neither broker positions nor closed deals today
            # Could be old, stale, or reconciliation error
            if state.lifecycle_state == "ACTIVE":
                log.error(
                    f"RECONCILIATION | Ticket {ticket} NOT on broker (open or closed) | "
                    f"ORPHAN - removing from memory"
                )
                orphaned_tickets.append(ticket)
            elif state.lifecycle_state == "ARCHIVED":
                log.debug(f"RECONCILIATION | Ticket {ticket} ARCHIVED, expected missing")
            else:
                log.warning(
                    f"RECONCILIATION | Ticket {ticket} {state.lifecycle_state} but not on broker | "
                    f"May be old or reconciliation lag"
                )
    
    # Remove orphans from memory
    for ticket in orphaned_tickets:
        memory_states.pop(ticket, None)
    
    log.info(
        f"RECONCILIATION COMPLETE | Verified closures: {len(verified_closures)} | "
        f"Orphaned removed: {len(orphaned_tickets)}"
    )
    
    return memory_states, verified_closures, orphaned_tickets


# ════════════════════════════════════════════════════════════════════════════
# PART 6: ACCOUNTING RECONSTRUCTION
# ════════════════════════════════════════════════════════════════════════════

def reconstruct_daily_pnl_from_broker(symbol: str = settings.SYMBOL) -> float:
    """
    Reconstruct AUTHORITATIVE daily PnL from broker closed deals.
    
    Sums all closing deal profits for today.
    This is the ground truth for daily accounting.
    """
    deals_data = get_broker_closed_deals_today(symbol)
    total_pnl = 0.0
    deal_count = 0
    
    for deal in deals_data.get("deals", []):
        if deal.get("entry") == 1:  # Exit deals only
            total_pnl += deal.get("profit", 0.0)
            deal_count += 1
    
    log.info(f"DAILY PNL RECONSTRUCTED | Deals: {deal_count} | Total PnL: {total_pnl:+.2f}")
    return total_pnl


def get_broker_account_state() -> Dict:
    """Get AUTHORITATIVE account state from broker."""
    account = conn.get_account_info()
    if account is None:
        return {}
    
    return {
        "balance": account.balance,
        "equity": account.equity,
        "profit": account.profit,
        "margin": account.margin,
        "margin_free": account.margin_free,
        "margin_level": account.margin_level,
        "timestamp": time.time(),
    }

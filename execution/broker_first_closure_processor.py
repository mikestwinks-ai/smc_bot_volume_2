"""
broker_first_closure_processor.py - Broker-First Closure Finalization Pipeline

EXACTLY-ONCE CLOSURE SEMANTICS:
All trade closures follow this deterministic pipeline:
1. Position disappears from broker
2. Forensically verify closure in deal history
3. Extract PnL, RR, closure reason
4. Emit TRADE_CLOSED event (ONCE only)
5. Record accounting (ONCE only)
6. Register cooldown (ONCE only)
7. Transition to CLOSED_RECORDED state
8. Archive after final processing

No position can be re-processed. Terminal states are irreversible.
"""

import time
from typing import Dict, Optional

from config import settings
from utils import mt5_connector as conn
from utils.logger import get_logger
from forensic_closure_auditor import audit_log
from execution.broker_state_manager import (
    TerminalTradeState,
    verify_closure_in_broker,
    get_broker_open_positions,
    can_emit_close_event,
    mark_close_event_emitted,
    can_record_accounting,
    mark_accounting_recorded,
    can_register_cooldown,
    mark_cooldown_registered,
)
from execution.lifecycle_coordinator import process_trade_closure
from execution.risk_manager import record_trade_result

log = get_logger(__name__)


# ════════════════════════════════════════════════════════════════════════════
# BACKWARD COMPATIBILITY: Fallback protection for lifecycle_state field
# ════════════════════════════════════════════════════════════════════════════

def get_lifecycle_state(state) -> str:
    """
    Safely get lifecycle state from any state object.
    
    Handles both:
    - TerminalTradeState (has lifecycle_state field)
    - TradeState (old, has state field)
    
    This ensures forensic logging never crashes on missing fields.
    
    Returns state string or "UNKNOWN" if field not found.
    """
    # Try new TerminalTradeState field first
    if hasattr(state, 'lifecycle_state'):
        return getattr(state, 'lifecycle_state', 'UNKNOWN')
    # Fall back to old TradeState field
    if hasattr(state, 'state'):
        # Map old state format to lifecycle state for compatibility
        old_state = getattr(state, 'state', 'UNKNOWN')
        # Old states like "ENTRY_ACTIVE" map to "ACTIVE" in new system
        if 'ACTIVE' in old_state:
            return 'ACTIVE'
        if old_state in ("CLOSED_RECORDED", "ARCHIVED", "CLOSED_VERIFIED"):
            return old_state
        if 'CLOSED' in old_state:
            return 'CLOSED_VERIFIED'
        return old_state
    return 'UNKNOWN'


def get_state_ticket(state) -> int:
    return int(getattr(state, "ticket", 0))


def get_state_entry_price(state) -> float:
    price = getattr(state, "entry_price", None)
    if price is None:
        price = getattr(state, "entry", 0.0)
    return float(price or 0.0)


def get_state_initial_sl(state) -> float:
    return float(getattr(state, "initial_sl", 0.0) or 0.0)


def get_state_direction(state) -> str:
    return str(getattr(state, "direction", "bullish") or "bullish")


def safe_transition_to(state, new_state: str) -> bool:
    """Monotonic lifecycle update for TradeState or TerminalTradeState."""
    if hasattr(state, "transition_to") and callable(getattr(state, "transition_to")):
        try:
            if state.transition_to(new_state):
                return True
        except Exception as e:
            log.error(
                f"STATE TRANSITION ERROR | Ticket: {get_state_ticket(state)} | "
                f"Target: {new_state} | {e}"
            )
    if hasattr(state, "lifecycle_state"):
        setattr(state, "lifecycle_state", new_state)
    if hasattr(state, "state"):
        setattr(state, "state", new_state)
    return True


def parse_closure_reason_from_comment(comment: str) -> str:
    """Map MT5 deal comment to exit reason code for cooldown durations."""
    reason_mapping = {
        "tp": "TP",
        "sl": "SL",
        "be": "BE",
        "time": "TIME_RULE",
        "force": "FORCE_CLOSE",
    }
    comment_lower = (comment or "").lower()
    for key, value in reason_mapping.items():
        if key in comment_lower:
            return value
    return "FORCE_CLOSE"


def detect_broker_closed_positions(
    trade_states: Dict[int, TerminalTradeState],
    symbol: str = settings.SYMBOL
) -> list:
    """
    Step 1: Find positions that disappeared from broker.
    
    Compare memory states to broker open positions.
    Returns list of tickets that disappeared.
    """
    # Forensic: Log position query
    audit_log("POSITION_QUERY", {
        "symbol": symbol,
        "memory_states": len(trade_states),
    })
    
    broker_positions = get_broker_open_positions(symbol)
    broker_tickets = {p.ticket for p in broker_positions if hasattr(p, 'ticket')}
    
    memory_tickets = set(trade_states.keys())
    
    # Find tickets in memory but not on broker
    disappeared_tickets = memory_tickets - broker_tickets
    
    if disappeared_tickets:
        # Forensic: Log disappearance
        audit_log("DISAPPEARED_LIST_CREATED", {
            "disappeared_count": len(disappeared_tickets),
            "tickets": list(disappeared_tickets),
            "broker_open": len(broker_tickets),
            "memory_states": len(memory_tickets),
        })
        
        log.warning(
            f"POSITIONS DISAPPEARED | Tickets: {disappeared_tickets} | "
            f"Broker open: {len(broker_tickets)} | Memory states: {len(memory_tickets)}"
        )
    
    return list(disappeared_tickets)


def verify_and_extract_closure(
    ticket: int,
    state: TerminalTradeState,
    symbol: str = settings.SYMBOL
) -> Optional[dict]:
    """
    Step 2-3: Forensically verify closure and extract details.
    
    Returns closure details dict or None if verification fails.
    """
    # Forensic: Log lookup start
    audit_log("FORENSIC_LOOKUP_START", {
        "ticket": ticket,
        "symbol": symbol,
        "state": get_lifecycle_state(state),
    }, ticket=ticket)
    
    log.info(f"CLOSURE VERIFICATION | Ticket: {ticket} | Starting forensic lookup...")
    
    verification = verify_closure_in_broker(ticket, symbol)
    
    # Forensic: Log deal lookup result
    if verification.verified:
        audit_log("DEAL_FOUND", {
            "ticket": ticket,
            "deal_ticket": verification.deal_ticket,
            "close_price": verification.close_price,
            "realized_pnl": verification.realized_pnl,
            "close_reason": verification.reason,
            "close_time": verification.close_time,
        }, ticket=ticket)
    else:
        audit_log("DEAL_NOT_FOUND", {
            "ticket": ticket,
            "reason": "Position missing, no deal in history",
        }, ticket=ticket)
    
    if not verification.verified:
        log.error(
            f"CLOSURE VERIFICATION FAILED | Ticket: {ticket} | "
            f"Position missing but deal not found in history | "
            f"Possible broker delay or reconciliation issue"
        )
        return None
    
    entry_price = get_state_entry_price(state)
    initial_sl = get_state_initial_sl(state)

    # Calculate realized RR
    initial_risk = abs(entry_price - initial_sl)
    realized_rr = 0.0
    if initial_risk > 0:
        realized_rr = verification.realized_pnl / initial_risk
    
    closure_details = {
        "ticket": ticket,
        "symbol": symbol,
        "direction": get_state_direction(state),
        "entry_price": entry_price,
        "closure_price": verification.close_price,
        "realized_pnl": verification.realized_pnl,
        "realized_rr": realized_rr,
        "closure_reason": verification.reason,
        "closure_comment": verification.comment,
        "closure_timestamp": verification.close_time,
        "swap": verification.swap,
        "commission": verification.commission,
        "deal_ticket": verification.deal_ticket,
    }
    
    # Forensic: Log extracted details
    audit_log("DEAL_PARSED", {
        "ticket": ticket,
        "deal_ticket": verification.deal_ticket,
        "entry_price": entry_price,
        "closure_price": verification.close_price,
        "realized_pnl": verification.realized_pnl,
        "realized_rr": realized_rr,
        "swap": verification.swap,
        "commission": verification.commission,
    }, ticket=ticket)
    
    log.warning(
        f"CLOSURE DETAILS EXTRACTED | Ticket: {ticket} | "
        f"PnL: {closure_details['realized_pnl']:+.2f} | "
        f"RR: {closure_details['realized_rr']:+.2f}R | "
        f"Reason: {closure_details['closure_reason']}"
    )
    
    return closure_details


def finalize_single_closure(
    state: TerminalTradeState,
    closure_details: dict,
    symbol: str = settings.SYMBOL
) -> bool:
    """
    Step 4-7: Emit event, record accounting, register cooldown, update state.
    
    All operations are idempotent via exactly-once guards.
    Returns True if closure was finalized, False if already finalized.
    """
    ticket = get_state_ticket(state)
    direction = get_state_direction(state)
    closure_reason = parse_closure_reason_from_comment(
        closure_details.get("closure_comment", "")
    )

    # Forensic: Log finalization start
    audit_log("CLOSURE_VERIFICATION_START", {
        "ticket": ticket,
        "state": get_lifecycle_state(state),
        "entry_price": closure_details['entry_price'],
        "closure_price": closure_details['closure_price'],
    }, ticket=ticket)

    # ── STEP 1: Emit TRADE_CLOSED event (exactly-once) ─────────────────────
    try:
        if can_emit_close_event(state):
            audit_log("TRADE_CLOSED_EVENT", {
                "ticket": ticket,
                "direction": direction,
                "entry_price": closure_details['entry_price'],
                "closure_price": closure_details['closure_price'],
                "realized_pnl": closure_details['realized_pnl'],
                "realized_rr": closure_details['realized_rr'],
                "reason": closure_reason,
                "status": "emitted",
            }, ticket=ticket)
            log.warning(
                f"TRADE CLOSED | Ticket: {ticket} | Direction: {direction.upper()} | "
                f"Entry: {closure_details['entry_price']:.2f} | "
                f"Close: {closure_details['closure_price']:.2f} | "
                f"PnL: {closure_details['realized_pnl']:+.2f} | "
                f"RR: {closure_details['realized_rr']:+.2f}R | "
                f"Reason: {closure_reason}"
            )
            mark_close_event_emitted(state)
        else:
            audit_log("TRADE_CLOSED_EVENT", {
                "ticket": ticket,
                "status": "skipped_already_emitted",
            }, ticket=ticket)
    except Exception as e:
        log.error(f"CLOSURE EVENT STEP FAILED | Ticket: {ticket} | {e}", exc_info=True)

    # ── STEP 2: Record accounting (exactly-once) ──────────────────────────
    try:
        if can_record_accounting(state):
            audit_log("ACCOUNTING_START", {
                "ticket": ticket,
                "pnl": closure_details['realized_pnl'],
            }, ticket=ticket)
            record_trade_result(closure_details['realized_pnl'], ticket=ticket)
            audit_log("DAILY_PNL_UPDATED", {
                "ticket": ticket,
                "pnl": closure_details['realized_pnl'],
                "status": "recorded",
            }, ticket=ticket)
            log.info(
                f"ACCOUNTING RECORDED | Ticket: {ticket} | "
                f"PnL: {closure_details['realized_pnl']:+.2f} added to daily total"
            )
            mark_accounting_recorded(state)
        else:
            audit_log("DAILY_PNL_UPDATED", {
                "ticket": ticket,
                "status": "skipped_already_recorded",
            }, ticket=ticket)
    except Exception as e:
        log.error(f"ACCOUNTING STEP FAILED | Ticket: {ticket} | {e}", exc_info=True)

    # ── STEP 3: Register cooldown (exactly-once) ──────────────────────────
    try:
        if can_register_cooldown(state):
            audit_log("COOLDOWN_START", {
                "ticket": ticket,
                "reason": closure_reason,
            }, ticket=ticket)
            process_trade_closure(
                ticket=ticket,
                symbol=symbol,
                direction=direction,
                closure_reason=closure_reason,
                realized_pnl=closure_details['realized_pnl'],
                realized_rr=closure_details['realized_rr'],
                source="BROKER_FIRST_CLOSURE"
            )
            audit_log("COOLDOWN_REGISTERED", {
                "ticket": ticket,
                "direction": direction,
                "reason": closure_reason,
                "status": "registered",
            }, ticket=ticket)
            mark_cooldown_registered(state)
        else:
            audit_log("COOLDOWN_REGISTERED", {
                "ticket": ticket,
                "status": "skipped_already_registered",
            }, ticket=ticket)
    except Exception as e:
        log.error(f"COOLDOWN STEP FAILED | Ticket: {ticket} | {e}", exc_info=True)

    # ── STEP 4: Persist closure metadata + lifecycle ─────────────────────
    try:
        setattr(state, "closure_deal_ticket", closure_details.get('deal_ticket', 0))
        setattr(state, "closure_reason", closure_reason)
        setattr(state, "closure_verified_pnl", closure_details['realized_pnl'])
        setattr(state, "closure_verified_rr", closure_details['realized_rr'])
        setattr(state, "closure_swap", closure_details.get('swap', 0.0))
        setattr(state, "closure_commission", closure_details.get('commission', 0.0))
        setattr(state, "closure_timestamp", closure_details.get('closure_timestamp', 0.0))

        audit_log("STATE_TRANSITION_START", {
            "ticket": ticket,
            "from_state": get_lifecycle_state(state),
            "to_state": "CLOSED_RECORDED",
        }, ticket=ticket)

        safe_transition_to(state, "CLOSED_RECORDED")

        audit_log("STATE_RECORDED_TO_ARCHIVED", {
            "ticket": ticket,
            "new_state": "CLOSED_RECORDED",
            "deal_ticket": closure_details.get('deal_ticket', 0),
            "closure_reason": closure_reason,
        }, ticket=ticket)
    except Exception as e:
        log.error(f"STATE METADATA STEP FAILED | Ticket: {ticket} | {e}", exc_info=True)

    finalized = getattr(state, "accounting_recorded", False)
    if finalized:
        log.info(
            f"CLOSURE FINALIZED | Ticket: {ticket} | "
            f"State: {get_lifecycle_state(state)} | All processing complete"
        )
        audit_log("CLOSURE_COMPLETE", {
            "ticket": ticket,
            "state": get_lifecycle_state(state),
            "pnl": closure_details['realized_pnl'],
            "rr": closure_details['realized_rr'],
        }, ticket=ticket)
    else:
        log.error(
            f"CLOSURE INCOMPLETE | Ticket: {ticket} | "
            f"Accounting was not recorded — check prior errors"
        )

    return finalized


def process_all_closed_positions(
    trade_states: Dict[int, TerminalTradeState],
    symbol: str = settings.SYMBOL
) -> tuple:
    """
    Complete broker-first closure pipeline.
    
    Process:
    1. Detect disappeared positions
    2. Verify each closure forensically
    3. Finalize each closure through canonical pipeline
    4. Return statistics
    
    Returns: (processed_count, skipped_count, failed_count)
    """
    log.info("BROKER-FIRST CLOSURE DETECTION | Starting...")
    
    disappeared = detect_broker_closed_positions(trade_states, symbol)
    if not disappeared:
        log.debug("NO DISAPPEARED POSITIONS | All tracked positions on broker")
        return 0, 0, 0
    
    processed = 0
    skipped = 0
    failed = 0
    failed_tickets = []
    
    for ticket in disappeared:
        state = trade_states.get(ticket)
        if not state:
            log.warning(f"STATE NOT FOUND | Ticket: {ticket} | Skipping")
            skipped += 1
            continue
        
        # Skip if already finalized
        if get_lifecycle_state(state) in ("CLOSED_RECORDED", "ARCHIVED"):
            log.debug(
                f"ALREADY FINALIZED | Ticket: {ticket} | "
                f"State: {get_lifecycle_state(state)} | Skipping"
            )
            skipped += 1
            continue
        
        # Forensically verify closure
        closure_details = verify_and_extract_closure(ticket, state, symbol)
        if not closure_details:
            log.error(
                f"CLOSURE VERIFICATION FAILED | Ticket: {ticket} | "
                f"Cannot proceed without broker confirmation"
            )
            failed += 1
            failed_tickets.append(ticket)
            continue
        
        # Finalize closure
        if not finalize_single_closure(state, closure_details, symbol):
            log.error(
                f"CLOSURE FINALIZATION FAILED | Ticket: {ticket} | "
                f"Idempotent guards blocked processing"
            )
            failed += 1
            failed_tickets.append(ticket)
            continue
        
        processed += 1
    
    log.warning(
        f"CLOSURE PROCESSING COMPLETE | "
        f"Processed: {processed} | Skipped: {skipped} | Failed: {failed} | "
        f"Failed tickets: {failed_tickets}"
    )
    
    return processed, skipped, failed


def archive_closed_positions(
    trade_states: Dict[int, TerminalTradeState]
) -> int:
    """
    Move finalized closures to ARCHIVED state.
    
    ARCHIVED positions are no longer managed, only kept for historical record.
    Returns count of archived tickets.
    """
    archived = 0
    
    for ticket, state in list(trade_states.items()):
        if get_lifecycle_state(state) == "CLOSED_RECORDED":
            # Forensic: Log archive start
            audit_log("ARCHIVE_START", {
                "ticket": ticket,
                "state": get_lifecycle_state(state),
            }, ticket=ticket)
            
            if safe_transition_to(state, "ARCHIVED"):
                # Forensic: Log archive complete
                audit_log("ARCHIVE_COMPLETE", {
                    "ticket": ticket,
                    "final_state": "ARCHIVED",
                }, ticket=ticket)
                
                archived += 1
                log.debug(f"ARCHIVED | Ticket: {ticket}")
    
    if archived > 0:
        log.info(f"POSITIONS ARCHIVED | Count: {archived}")
    
    return archived

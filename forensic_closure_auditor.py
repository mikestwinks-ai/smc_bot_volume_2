"""
forensic_closure_auditor.py - Forensic instrumentation for closure pipeline

This module provides forensic logging hooks for the complete trade closure pipeline.
It traces every stage without modifying trading logic.

Stages Instrumented:
1. Position Disappearance Detection
2. Forensic Deal Lookup  
3. Closure Verification
4. PnL Extraction
5. Accounting Update
6. Cooldown Registration
7. State Transition
8. Persistence Update

Usage:
  from forensic_closure_auditor import audit_log, FORENSIC_ENABLED
  if FORENSIC_ENABLED:
      audit_log("STAGE_NAME", data_dict)
"""

import json
import time
from datetime import datetime
from typing import Optional, Dict, Any

# ════════════════════════════════════════════════════════════════════════════
# FORENSIC CONFIGURATION
# ════════════════════════════════════════════════════════════════════════════

FORENSIC_ENABLED = True  # Toggle for forensic logging
AUDIT_FILE = "logs/forensic_closure_audit.jsonl"

class ForensicAuditor:
    """Forensic event logger for closure pipeline."""
    
    def __init__(self, enabled: bool = FORENSIC_ENABLED):
        self.enabled = enabled
        self.events = []
        self.timeline = []
    
    def log_event(self, stage: str, data: Dict[str, Any], ticket: Optional[int] = None):
        """Log a forensic event."""
        if not self.enabled:
            return
        
        event = {
            "timestamp": time.time(),
            "timestamp_iso": datetime.now().isoformat(),
            "stage": stage,
            "ticket": ticket,
            "data": data,
        }
        
        self.events.append(event)
        self._persist_event(event)
    
    def _persist_event(self, event: Dict[str, Any]):
        """Persist event to audit file (JSONL format)."""
        try:
            with open(AUDIT_FILE, 'a') as f:
                f.write(json.dumps(event) + '\n')
        except Exception as e:
            print(f"⚠️  Forensic persistence failed: {e}")
    
    def get_timeline(self) -> list:
        """Get timeline of all events for a closure."""
        return self.events
    
    def report_closure_timeline(self, ticket: int):
        """Generate closure event timeline."""
        ticket_events = [e for e in self.events if e.get('ticket') == ticket]
        
        if not ticket_events:
            return None
        
        report = {
            "ticket": ticket,
            "start_time": ticket_events[0]['timestamp_iso'],
            "end_time": ticket_events[-1]['timestamp_iso'],
            "duration_seconds": ticket_events[-1]['timestamp'] - ticket_events[0]['timestamp'],
            "event_count": len(ticket_events),
            "stages": [e['stage'] for e in ticket_events],
            "timeline": ticket_events,
        }
        
        return report

# Global auditor instance
_auditor = ForensicAuditor(FORENSIC_ENABLED)

def audit_log(stage: str, data: Dict[str, Any], ticket: Optional[int] = None):
    """Log a forensic event to audit trail."""
    _auditor.log_event(stage, data, ticket)

def get_auditor():
    """Get the global auditor instance."""
    return _auditor

def report_closure(ticket: int):
    """Generate report for a specific ticket's closure."""
    return _auditor.report_closure_timeline(ticket)

# ════════════════════════════════════════════════════════════════════════════
# STAGE DEFINITIONS
# ════════════════════════════════════════════════════════════════════════════

STAGES = {
    # Detection Phase
    "POSITION_QUERY": "Querying broker for open positions",
    "POSITION_DISAPPEARED": "Position no longer on broker",
    "DISAPPEARED_LIST_CREATED": "List of disappeared tickets created",
    
    # Forensic Lookup Phase
    "FORENSIC_LOOKUP_START": "Beginning forensic deal history lookup",
    "DEAL_HISTORY_QUERIED": "Queried broker deal history",
    "DEAL_FOUND": "Matching deal found in history",
    "DEAL_NOT_FOUND": "No matching deal found (orphan)",
    "DEAL_PARSED": "Deal data extracted and parsed",
    
    # Verification Phase
    "CLOSURE_VERIFICATION_START": "Beginning closure verification",
    "CLOSURE_VERIFIED": "Closure verified against broker",
    "CLOSURE_FAILED": "Closure verification failed",
    
    # Extraction Phase
    "PNL_EXTRACTION_START": "Beginning PnL extraction",
    "PNL_EXTRACTED": "PnL extracted from deal",
    "FEES_EXTRACTED": "Fees/swap/commission extracted",
    "CLOSE_DETAILS_EXTRACTED": "Close price/time/reason extracted",
    
    # Accounting Phase
    "ACCOUNTING_START": "Beginning accounting update",
    "DAILY_PNL_UPDATED": "Daily PnL updated",
    "TRADE_RESULT_RECORDED": "Trade result recorded to ledger",
    "PEAK_BALANCE_UPDATED": "Peak balance updated",
    "ACCOUNTING_COMPLETE": "Accounting phase complete",
    
    # Cooldown Phase
    "COOLDOWN_START": "Beginning cooldown registration",
    "COOLDOWN_REGISTERED": "Cooldown registered for bias/direction",
    "COOLDOWN_PERSISTED": "Cooldown saved to state file",
    
    # State Transition Phase
    "STATE_TRANSITION_START": "Beginning state machine transition",
    "STATE_ACTIVE_TO_VERIFIED": "Transitioned ACTIVE → CLOSED_VERIFIED",
    "STATE_VERIFIED_TO_RECORDED": "Transitioned CLOSED_VERIFIED → CLOSED_RECORDED",
    "STATE_RECORDED_TO_ARCHIVED": "Transitioned CLOSED_RECORDED → ARCHIVED",
    "STATE_TRANSITION_COMPLETE": "State machine transition complete",
    
    # Persistence Phase
    "PERSISTENCE_START": "Beginning persistence update",
    "TRADES_STATE_WRITTEN": "trades_state.json updated",
    "RISK_STATE_WRITTEN": "risk_state.json updated",
    "COOLDOWN_STATE_WRITTEN": "cooldown_state.json updated",
    "PERSISTENCE_COMPLETE": "Persistence update complete",
    
    # Event Emission Phase
    "TRADE_CLOSED_EVENT": "TRADE_CLOSED event emitted",
    
    # Archive Phase
    "ARCHIVE_START": "Beginning archive of closed trade",
    "ARCHIVE_COMPLETE": "Archive complete",
    
    # Closure Complete
    "CLOSURE_COMPLETE": "Complete trade closure pipeline finished",
}

if __name__ == "__main__":
    # Test the auditor
    print("Forensic Closure Auditor Ready")
    print(f"Enabled: {FORENSIC_ENABLED}")
    print(f"Output: {AUDIT_FILE}")
    print(f"Stages: {len(STAGES)}")

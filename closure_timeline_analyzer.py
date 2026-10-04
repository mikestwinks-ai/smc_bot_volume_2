"""
closure_timeline_analyzer.py - Parse and analyze forensic closure events

This tool reads the forensic audit log (JSONL format) and produces:
1. Closure event timeline
2. Stage-by-stage trace
3. PnL verification
4. State transition verification
5. Peak balance tracking
"""

import json
from collections import defaultdict
from datetime import datetime
from typing import Dict, List, Any, Optional


def load_forensic_log(filepath: str = "logs/forensic_closure_audit.jsonl") -> List[Dict]:
    """Load all forensic events from JSONL file."""
    events = []
    try:
        with open(filepath, 'r') as f:
            for line in f:
                if line.strip():
                    try:
                        event = json.loads(line)
                        events.append(event)
                    except json.JSONDecodeError:
                        pass
    except FileNotFoundError:
        print(f"❌ Audit log not found: {filepath}")
        return []
    
    return events


def group_by_ticket(events: List[Dict]) -> Dict[int, List[Dict]]:
    """Group events by ticket number."""
    grouped = defaultdict(list)
    for event in events:
        ticket = event.get('ticket')
        if ticket:
            grouped[ticket].append(event)
    return grouped


def generate_closure_timeline(ticket: int, events: List[Dict]) -> Dict[str, Any]:
    """Generate detailed timeline for a single ticket closure."""
    ticket_events = [e for e in events if e.get('ticket') == ticket]
    
    if not ticket_events:
        return None
    
    # Sort by timestamp
    ticket_events = sorted(ticket_events, key=lambda e: e.get('timestamp', 0))
    
    stages = []
    timeline_start = ticket_events[0]['timestamp']
    
    for event in ticket_events:
        stage_name = event.get('stage')
        elapsed = event.get('timestamp', timeline_start) - timeline_start
        
        stage_info = {
            "elapsed_seconds": round(elapsed, 3),
            "stage": stage_name,
            "timestamp": event.get('timestamp_iso'),
            "data": event.get('data', {}),
        }
        stages.append(stage_info)
    
    # Extract key data points
    deal_found = None
    pnl_extracted = None
    peak_balance_updates = []
    state_transitions = []
    
    for event in ticket_events:
        stage = event.get('stage')
        data = event.get('data', {})
        
        if stage == "DEAL_FOUND":
            deal_found = {
                "deal_ticket": data.get('deal_ticket'),
                "close_price": data.get('close_price'),
                "realized_pnl": data.get('realized_pnl'),
            }
        elif stage == "DEAL_PARSED":
            pnl_extracted = {
                "entry_price": data.get('entry_price'),
                "closure_price": data.get('closure_price'),
                "realized_pnl": data.get('realized_pnl'),
                "realized_rr": data.get('realized_rr'),
                "swap": data.get('swap'),
                "commission": data.get('commission'),
            }
        elif stage == "PEAK_BALANCE_UPDATED":
            peak_balance_updates.append({
                "timestamp": event.get('timestamp_iso'),
                "peak_balance": data.get('peak_balance'),
                "current_balance": data.get('current_balance'),
            })
        elif stage == "STATE_TRANSITION_START":
            state_transitions.append({
                "from_state": data.get('from_state'),
                "to_state": data.get('to_state'),
            })
        elif stage == "STATE_RECORDED_TO_ARCHIVED":
            state_transitions.append({
                "from_state": "CLOSED_VERIFIED",
                "to_state": "CLOSED_RECORDED",
                "deal_ticket": data.get('deal_ticket'),
            })
    
    return {
        "ticket": ticket,
        "total_stages": len(stages),
        "start_time": ticket_events[0].get('timestamp_iso'),
        "end_time": ticket_events[-1].get('timestamp_iso'),
        "total_duration_seconds": round(ticket_events[-1].get('timestamp', 0) - timeline_start, 3),
        "stages": stages,
        "deal_found": deal_found,
        "pnl_extracted": pnl_extracted,
        "peak_balance_updates": peak_balance_updates,
        "state_transitions": state_transitions,
    }


def print_closure_timeline(timeline: Dict[str, Any]):
    """Pretty-print closure timeline."""
    if not timeline:
        return
    
    print("\n" + "=" * 100)
    print(f"CLOSURE TIMELINE | TICKET: {timeline['ticket']}")
    print("=" * 100)
    
    print(f"\nDuration: {timeline['total_duration_seconds']:.3f} seconds")
    print(f"Stages: {timeline['total_stages']}")
    print(f"Start: {timeline['start_time']}")
    print(f"End: {timeline['end_time']}")
    
    # Print stage-by-stage trace
    print("\n" + "-" * 100)
    print("STAGE-BY-STAGE TRACE")
    print("-" * 100)
    
    for i, stage in enumerate(timeline['stages'], 1):
        elapsed = stage['elapsed_seconds']
        name = stage['stage']
        data = stage['data']
        
        # Format stage header
        print(f"\n[{i:2d}] T+{elapsed:7.3f}s | {name}")
        
        # Print relevant data based on stage
        if name == "DEAL_FOUND":
            print(f"     └─ Deal Ticket: {data.get('deal_ticket')}")
            print(f"     └─ Close Price: {data.get('close_price'):.2f}")
            print(f"     └─ PnL: {data.get('realized_pnl'):+.2f}")
        
        elif name == "DEAL_PARSED":
            print(f"     └─ Entry: {data.get('entry_price'):.2f}")
            print(f"     └─ Close: {data.get('closure_price'):.2f}")
            print(f"     └─ PnL: {data.get('realized_pnl'):+.2f} ({data.get('realized_rr'):+.2f}R)")
            print(f"     └─ Swap: {data.get('swap'):.2f}, Commission: {data.get('commission'):.2f}")
        
        elif name == "TRADE_CLOSED_EVENT":
            status = data.get('status')
            if status == "emitted":
                print(f"     └─ Direction: {data.get('direction')}")
                print(f"     └─ PnL: {data.get('realized_pnl'):+.2f}")
                print(f"     └─ Reason: {data.get('reason')}")
        
        elif name == "TRADE_RESULT_RECORDED":
            print(f"     └─ PnL: {data.get('pnl'):+.2f}")
            print(f"     └─ Daily PnL: {data.get('daily_pnl'):+.2f}")
            print(f"     └─ Closed Trades: {data.get('closed_trades_today')}")
        
        elif name == "PEAK_BALANCE_UPDATED":
            print(f"     └─ Current Balance: {data.get('current_balance'):.2f}")
            print(f"     └─ Peak Balance: {data.get('peak_balance'):.2f}")
            print(f"     └─ Daily PnL: {data.get('daily_pnl'):+.2f}")
        
        elif name == "STATE_TRANSITION_START":
            print(f"     └─ {data.get('from_state')} → {data.get('to_state')}")
        
        elif name == "STATE_RECORDED_TO_ARCHIVED":
            print(f"     └─ State: CLOSED_RECORDED")
            print(f"     └─ Deal Ticket: {data.get('deal_ticket')}")
        
        elif name == "COOLDOWN_REGISTERED":
            status = data.get('status')
            if status == "registered":
                print(f"     └─ Direction: {data.get('direction')}")
                print(f"     └─ Reason: {data.get('reason')}")
    
    # Summary
    print("\n" + "-" * 100)
    print("CLOSURE SUMMARY")
    print("-" * 100)
    
    if timeline['deal_found']:
        deal = timeline['deal_found']
        print(f"✅ Deal Found: Ticket {deal['deal_ticket']} | PnL {deal['realized_pnl']:+.2f}")
    
    if timeline['pnl_extracted']:
        pnl = timeline['pnl_extracted']
        print(f"✅ PnL Extracted: {pnl['realized_pnl']:+.2f} ({pnl['realized_rr']:+.2f}R)")
    
    if timeline['state_transitions']:
        print(f"✅ State Transitions: {len(timeline['state_transitions'])} transitions")
        for trans in timeline['state_transitions']:
            if 'to_state' in trans:
                print(f"   └─ {trans.get('from_state')} → {trans.get('to_state')}")
    
    if timeline['peak_balance_updates']:
        latest_peak = timeline['peak_balance_updates'][-1]
        print(f"✅ Peak Balance Updated: {latest_peak['peak_balance']:.2f}")


def analyze_all_closures(events: List[Dict]):
    """Analyze all closures in the forensic log."""
    grouped = group_by_ticket(events)
    
    print("\n" + "=" * 100)
    print("FORENSIC CLOSURE AUDIT ANALYSIS")
    print("=" * 100)
    
    print(f"\nTotal Events: {len(events)}")
    print(f"Unique Tickets: {len(grouped)}")
    
    for ticket in sorted(grouped.keys()):
        timeline = generate_closure_timeline(ticket, events)
        print_closure_timeline(timeline)
    
    # Summary statistics
    print("\n" + "=" * 100)
    print("AUDIT SUMMARY")
    print("=" * 100)
    
    total_closures = len(grouped)
    successful_closures = sum(1 for t in grouped.keys() if any(
        e.get('stage') == "CLOSURE_COMPLETE" for e in grouped[t]
    ))
    
    print(f"\n✅ Successful Closures: {successful_closures}/{total_closures}")
    
    # Check for issues
    for ticket in grouped.keys():
        events_for_ticket = grouped[ticket]
        
        # Check for duplicate event emissions
        event_counts = defaultdict(int)
        for event in events_for_ticket:
            event_counts[event.get('stage')] += 1
        
        # Flag any suspicious duplicates
        suspicious = False
        for stage, count in event_counts.items():
            if "EMITTED" in stage and count > 1:
                print(f"\n⚠️  Ticket {ticket}: {stage} fired {count} times (expected 1)")
                suspicious = True
        
        if suspicious:
            print(f"   └─ May indicate replay or duplicate processing")


if __name__ == "__main__":
    import sys
    
    filepath = "logs/forensic_closure_audit.jsonl"
    if len(sys.argv) > 1:
        filepath = sys.argv[1]
    
    events = load_forensic_log(filepath)
    
    if not events:
        print("❌ No forensic events to analyze")
        sys.exit(1)
    
    analyze_all_closures(events)

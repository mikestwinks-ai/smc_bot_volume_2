"""
validation_baseline.py - Establish baseline for broker-first validation

Captures:
1. Current broker state (open positions, closed deals today)
2. Current memory state (trades_state.json)
3. Current persistence state (risk, cooldowns)
4. Compares all three
"""

import json
import time
from datetime import datetime, date as date_type
from utils import mt5_connector as conn
from config import settings
from utils.logger import get_logger

log = get_logger("validation.baseline")

def capture_broker_state():
    """Get authoritative broker state."""
    print("\n" + "=" * 80)
    print("BROKER STATE SNAPSHOT")
    print("=" * 80)
    
    # Open positions
    open_positions = conn.get_open_positions(symbol=settings.SYMBOL, magic=settings.MAGIC)
    print(f"\nOPEN POSITIONS: {len(open_positions)}")
    for pos in open_positions:
        print(f"  Ticket: {pos.ticket} | Direction: {'BUY' if pos.type == 0 else 'SELL'} | "
              f"Entry: {pos.price_open:.2f} | SL: {pos.sl:.2f} | TP: {pos.tp:.2f} | "
              f"Profit: {pos.profit:.2f}")
    
    # Closed deals today
    deals_data = conn.get_deal_history(symbol=settings.SYMBOL, magic=settings.MAGIC, lookback_hours=24)
    print(f"\nCLOSED DEALS TODAY: {deals_data.get('deal_count', 0)}")
    for deal in deals_data.get('deals', []):
        print(f"  Ticket: {deal['ticket']} | Order: {deal['order']} | "
              f"PnL: {deal['profit']:+.2f} | Reason: {deal['reason']} | Comment: {deal['comment']}")
    
    return {
        "timestamp": time.time(),
        "timestamp_str": datetime.now().isoformat(),
        "open_positions": len(open_positions),
        "position_tickets": [p.ticket for p in open_positions],
        "closed_deals_today": deals_data.get('deal_count', 0),
        "daily_pnl": deals_data.get('total_pnl', 0.0),
    }

def capture_memory_state():
    """Get memory state from trades_state.json."""
    print("\n" + "=" * 80)
    print("MEMORY STATE SNAPSHOT")
    print("=" * 80)
    
    try:
        with open('logs/state/trades_state.json', 'r') as f:
            trades = json.load(f)
        
        print(f"\nTRADES IN MEMORY: {len(trades)}")
        for ticket_str, state in trades.items():
            ticket = int(ticket_str)
            print(f"  Ticket: {ticket} | Direction: {state['direction'].upper()} | "
                  f"Entry: {state['entry']:.2f} | SL: {state['initial_sl']:.2f} | "
                  f"TP: {state['initial_tp']:.2f} | State: {state['state']} | RR: {state['rr_achieved']:.2f}R")
        
        return {
            "timestamp": time.time(),
            "count": len(trades),
            "tickets": list(trades.keys()),
            "trades": trades,
        }
    except FileNotFoundError:
        print("  [No trades_state.json found]")
        return {"timestamp": time.time(), "count": 0, "tickets": [], "trades": {}}

def capture_persistence_state():
    """Get persistence state (risk and cooldowns)."""
    print("\n" + "=" * 80)
    print("PERSISTENCE STATE SNAPSHOT")
    print("=" * 80)
    
    try:
        with open('logs/state/risk_state.json', 'r') as f:
            risk = json.load(f)
        print(f"\nRISK STATE (Date: {risk.get('day')})")
        print(f"  Trades today: {risk.get('trades_today')} | Closed: {risk.get('closed_trades_today')} | "
              f"Daily PnL: {risk.get('daily_pnl'):+.2f} | Peak Balance: {risk.get('peak_balance'):.2f}")
    except FileNotFoundError:
        risk = {}
        print("  [No risk_state.json found]")
    
    try:
        with open('logs/state/cooldown_state.json', 'r') as f:
            cooldowns = json.load(f)
        print(f"\nCOOLDOWN STATE: {len(cooldowns)} active")
        for key, cooldown in cooldowns.items():
            print(f"  {key}: Reason={cooldown['exit_reason']}, Expires at {cooldown['saved_at']}")
    except FileNotFoundError:
        cooldowns = {}
        print("  [No cooldown_state.json found]")
    
    return {
        "risk": risk,
        "cooldowns": cooldowns,
    }

def compare_states(broker, memory, persist):
    """Compare all three states."""
    print("\n" + "=" * 80)
    print("STATE COMPARISON")
    print("=" * 80)
    
    broker_tickets = set(broker['position_tickets'])
    memory_tickets = set(int(t) for t in memory['tickets'])
    
    print(f"\nBROKER vs MEMORY:")
    print(f"  Broker open: {len(broker_tickets)} | Memory active: {len(memory_tickets)}")
    print(f"  Broker tickets: {sorted(broker_tickets)}")
    print(f"  Memory tickets: {sorted(memory_tickets)}")
    
    in_broker_not_memory = broker_tickets - memory_tickets
    in_memory_not_broker = memory_tickets - broker_tickets
    in_both = broker_tickets & memory_tickets
    
    if in_broker_not_memory:
        print(f"\n⚠️  IN BROKER BUT NOT MEMORY: {in_broker_not_memory}")
    if in_memory_not_broker:
        print(f"\n⚠️  IN MEMORY BUT NOT BROKER: {in_memory_not_broker}")
    if in_both:
        print(f"\n✅ IN BOTH (Consistent): {in_both}")
    
    print(f"\nACCOUNTING:")
    print(f"  Broker daily PnL: {broker['daily_pnl']:+.2f}")
    print(f"  Memory daily PnL: {persist['risk'].get('daily_pnl', 0):+.2f}")
    
    if broker['daily_pnl'] == persist['risk'].get('daily_pnl', 0):
        print(f"  ✅ PnL matches!")
    else:
        print(f"  ❌ PnL MISMATCH: {abs(broker['daily_pnl'] - persist['risk'].get('daily_pnl', 0)):.2f}")

if __name__ == "__main__":
    print("\n" + "=" * 80)
    print(f"BROKER-FIRST VALIDATION BASELINE - {datetime.now().isoformat()}")
    print("=" * 80)
    
    try:
        broker = capture_broker_state()
        memory = capture_memory_state()
        persist = capture_persistence_state()
        compare_states(broker, memory, persist)
        
        # Save baseline
        baseline = {
            "timestamp": datetime.now().isoformat(),
            "broker": broker,
            "memory": memory,
            "persistence": persist,
        }
        with open('validation_baseline.json', 'w') as f:
            json.dump(baseline, f, indent=2, default=str)
        print("\n✅ Baseline saved to validation_baseline.json")
        
    except Exception as e:
        log.error(f"Baseline capture failed: {e}", exc_info=True)
        print(f"\n❌ Error: {e}")

"""
FORENSIC MT5 DEAL AUDIT — RAW BROKER TRUTH EXTRACTION

Purpose: Print EVERY MT5 deal for today with full details.
No filtering. No summaries. Only raw broker data.

This proves what the broker actually has vs what bot reconstructs.
"""

import MetaTrader5 as mt5
from datetime import datetime, timedelta
import pytz
from config import settings

# Initialize MT5 (assumes already connected)
if not mt5.initialize():
    print("ERROR: MT5 not initialized")
    exit(1)

# Settings
SYMBOL = settings.SYMBOL
MAGIC = settings.MAGIC

print("=" * 80)
print("FORENSIC MT5 DEAL AUDIT")
print("=" * 80)

# ─── TIME BOUNDARIES ────────────────────────────────────────────────────────
server_time_utc = datetime.utcnow()
local_time = datetime.now()
EAT = pytz.timezone("Africa/Nairobi")
server_time_eat = datetime.now(EAT)

print("\nTIME BOUNDARIES:")
print(f"  Server UTC now:     {server_time_utc.isoformat()}")
print(f"  Local machine:      {local_time.isoformat()}")
print(f"  EAT timezone now:   {server_time_eat.isoformat()}")

# Get today's boundaries in EAT
today_eat = server_time_eat.date()
today_start_eat = EAT.localize(datetime.combine(today_eat, datetime.min.time()))
today_end_eat = EAT.localize(datetime.combine(today_eat, datetime.max.time()))

# Convert to UTC for MT5 query
today_start_utc = today_start_eat.astimezone(pytz.utc)
today_end_utc = today_end_eat.astimezone(pytz.utc)

print(f"\nTODAY BOUNDARIES (EAT):   {today_eat}")
print(f"  Query start (UTC):  {today_start_utc.isoformat()}")
print(f"  Query end (UTC):    {today_end_utc.isoformat()}")

# ─── QUERY MT5 DEAL HISTORY ────────────────────────────────────────────────
print("\n" + "=" * 80)
print("QUERYING MT5 DEAL HISTORY")
print("=" * 80)

deals = mt5.history_deals_get(today_start_utc, today_end_utc, group="*")
if deals is None:
    print(f"ERROR: MT5 history_deals_get failed: {mt5.last_error()}")
    exit(1)

print(f"\nTotal deals returned by MT5: {len(deals)}")

# ─── PRINT EVERY RAW DEAL ────────────────────────────────────────────────────
print("\n" + "=" * 80)
print("RAW DEAL DUMP (NO FILTERING)")
print("=" * 80)

for i, deal in enumerate(deals, 1):
    print(f"\n--- DEAL #{i} ---")
    print(f"  Ticket:       {deal.ticket}")
    print(f"  Order:        {deal.order}")
    print(f"  Symbol:       {deal.symbol}")
    print(f"  Magic:        {deal.magic}")
    print(f"  Type:         {deal.type} ({mt5.DEAL_TYPE_BUY if deal.type == mt5.DEAL_TYPE_BUY else 'SELL' if deal.type == mt5.DEAL_TYPE_SELL else 'OTHER'})")
    print(f"  Entry:        {deal.entry} ({mt5.DEAL_ENTRY_IN if deal.entry == mt5.DEAL_ENTRY_IN else 'OUT' if deal.entry == mt5.DEAL_ENTRY_OUT else 'OTHER'})")
    print(f"  Volume:       {deal.volume}")
    print(f"  Price:        {deal.price}")
    print(f"  Profit:       {deal.profit}")
    print(f"  Swap:         {deal.swap}")
    print(f"  Commission:   {deal.commission}")
    print(f"  Time (epoch): {deal.time}")
    deal_time = datetime.fromtimestamp(deal.time, tz=EAT)
    print(f"  Time (EAT):   {deal_time.isoformat()}")
    print(f"  Comment:      {deal.comment}")

# ─── FILTER BY SYMBOL ──────────────────────────────────────────────────────
print("\n" + "=" * 80)
print(f"FILTERING: Symbol == {SYMBOL}")
print("=" * 80)

symbol_deals = [d for d in deals if d.symbol == SYMBOL]
print(f"Deals with symbol {SYMBOL}: {len(symbol_deals)}")

for i, deal in enumerate(symbol_deals, 1):
    print(f"\n--- SYMBOL MATCH #{i} (Ticket {deal.ticket}) ---")
    print(f"  Symbol:  {deal.symbol} ✓")
    print(f"  Magic:   {deal.magic}")
    print(f"  Type:    {deal.type}")
    print(f"  Entry:   {deal.entry} {'(OPEN)' if deal.entry == mt5.DEAL_ENTRY_IN else '(CLOSE)' if deal.entry == mt5.DEAL_ENTRY_OUT else '(OTHER)'}")
    print(f"  Profit:  {deal.profit}")
    print(f"  Time:    {datetime.fromtimestamp(deal.time, tz=EAT).isoformat()}")

# ─── FILTER BY MAGIC NUMBER ────────────────────────────────────────────────
print("\n" + "=" * 80)
print(f"FILTERING: Magic == {MAGIC}")
print("=" * 80)

magic_deals = [d for d in symbol_deals if d.magic == MAGIC]
print(f"Deals with magic {MAGIC}: {len(magic_deals)}")

for i, deal in enumerate(magic_deals, 1):
    print(f"\n--- MAGIC MATCH #{i} (Ticket {deal.ticket}) ---")
    print(f"  Symbol:  {deal.symbol} ✓")
    print(f"  Magic:   {deal.magic} ✓")
    print(f"  Type:    {deal.type}")
    print(f"  Entry:   {deal.entry} {'(OPEN)' if deal.entry == mt5.DEAL_ENTRY_IN else '(CLOSE)' if deal.entry == mt5.DEAL_ENTRY_OUT else '(OTHER)'}")
    print(f"  Profit:  {deal.profit}")
    print(f"  Time:    {datetime.fromtimestamp(deal.time, tz=EAT).isoformat()}")

# ─── COUNT TRADES (ENTRY DEALS ONLY) ────────────────────────────────────────
print("\n" + "=" * 80)
print("TRADE COUNT LOGIC")
print("=" * 80)

entry_deals = [d for d in magic_deals if d.entry == mt5.DEAL_ENTRY_IN]
print(f"\nENTRY DEALS (DEAL_ENTRY_IN): {len(entry_deals)}")
for deal in entry_deals:
    print(f"  Ticket {deal.ticket}: {deal.symbol} {deal.type} @ {deal.price} | Time: {datetime.fromtimestamp(deal.time, tz=EAT).isoformat()}")

exit_deals = [d for d in magic_deals if d.entry == mt5.DEAL_ENTRY_OUT]
print(f"\nEXIT DEALS (DEAL_ENTRY_OUT): {len(exit_deals)}")
for deal in exit_deals:
    print(f"  Ticket {deal.ticket}: {deal.symbol} {deal.type} @ {deal.price} | Profit: {deal.profit} | Time: {datetime.fromtimestamp(deal.time, tz=EAT).isoformat()}")

print(f"\nTOTAL TRADES (ENTRY+EXIT): {len(entry_deals) + len(exit_deals)}")

# ─── CALCULATE DAILY PNL ────────────────────────────────────────────────────
realized_pnl = sum(d.profit for d in exit_deals)
wins = len([d for d in exit_deals if d.profit > 0])
losses = len([d for d in exit_deals if d.profit < 0])

print(f"\nPNL RECONSTRUCTION:")
print(f"  Realized PnL (from exits): {realized_pnl:.2f}")
print(f"  Wins: {wins}")
print(f"  Losses: {losses}")

# Track consecutive losses
consecutive_losses = 0
for deal in exit_deals:
    if deal.profit < 0:
        consecutive_losses += 1
    else:
        consecutive_losses = 0
print(f"  Consecutive losses (trailing): {consecutive_losses}")

# ─── FINAL SUMMARY ──────────────────────────────────────────────────────────
print("\n" + "=" * 80)
print("FORENSIC SUMMARY")
print("=" * 80)
print(f"\nRaw MT5 deals (all): {len(deals)}")
print(f"Filtered by symbol ({SYMBOL}): {len(symbol_deals)}")
print(f"Filtered by magic ({MAGIC}): {len(magic_deals)}")
print(f"\nEntry deals (trades opened): {len(entry_deals)}")
print(f"Exit deals (trades closed): {len(exit_deals)}")
print(f"Total trades today: {len(entry_deals) + len(exit_deals)}")
print(f"Realized daily PnL: {realized_pnl:.2f}")
print(f"Consecutive losses: {consecutive_losses}")

print("\n" + "=" * 80)
print("END FORENSIC AUDIT")
print("=" * 80)

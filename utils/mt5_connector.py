"""
mt5_connector.py — MT5 connection lifecycle and data fetching utilities.
All raw MT5 interaction is encapsulated here so other modules stay clean.
"""

import time
import pandas as pd

try:
    import MetaTrader5 as mt5
except ImportError:
    mt5 = None  # Allow testing without MT5

from config import settings
from utils.logger import get_logger

log = get_logger(__name__)


# ─── Inject MT5 timeframe constants into settings ─────────────────────────────
def _bind_timeframes() -> None:
    if mt5 is None:
        # Set defaults for testing
        settings.TF_H4  = 240  # MT5.TIMEFRAME_H4
        settings.TF_M15 = 15   # MT5.TIMEFRAME_M15
        settings.TF_M5  = 5    # MT5.TIMEFRAME_M5
        return
    settings.TF_H4  = mt5.TIMEFRAME_H4
    settings.TF_M15 = mt5.TIMEFRAME_M15
    settings.TF_M5  = mt5.TIMEFRAME_M5


# ─── Connection ───────────────────────────────────────────────────────────────

def connect() -> bool:
    """Initialise MT5, log in, and bind timeframe constants."""
    if mt5 is None:
        log.warning("MT5 module not installed - running in test mode")
        _bind_timeframes()
        return False

    _init_ok = mt5.initialize()
    if not _init_ok:
        log.error(f"MT5 initialize() failed: {mt5.last_error()}")
        return False

    ok = mt5.login(
        login=settings.MT5_LOGIN,
        password=settings.MT5_PASSWORD,
        server=settings.MT5_SERVER,
    )
    if not ok:
        log.error(f"MT5 login failed: {mt5.last_error()}")
        mt5.shutdown()
        return False

    _bind_timeframes()
    
    # Get and log symbol info for debugging point value issues
    sym_info = mt5.symbol_info(settings.SYMBOL)
    if sym_info:
        log.info(
            f"MT5 SYMBOL INFO | {settings.SYMBOL} | "
            f"Point: {sym_info.point} | Digits: {sym_info.digits} | "
            f"Ask: {sym_info.ask} | Bid: {sym_info.bid}"
        )
    
    info = mt5.account_info()
    log.info(
        f"MT5 connected | Account: {info.login} | Balance: {info.balance:.2f} "
        f"{info.currency} | Leverage: 1:{info.leverage}"
    )
    return True


def disconnect() -> None:
    if mt5 is None:
        return
    mt5.shutdown()
    log.info("MT5 disconnected.")


def is_connected() -> bool:
    if mt5 is None:
        return False
    return mt5.terminal_info() is not None


def reconnect(retries: int = 5, delay: float = 10.0) -> bool:
    """Attempt to reconnect up to N times."""
    if mt5 is None:
        log.warning("MT5 module not installed - reconnect skipped")
        return False
    
    for attempt in range(1, retries + 1):
        log.warning(f"Reconnect attempt {attempt}/{retries}...")
        mt5.shutdown()
        time.sleep(delay)
        if connect():
            return True
    log.error("All reconnect attempts failed.")
    return False


# ─── Market data ─────────────────────────────────────────────────────────────

def get_bars(symbol: str, timeframe: int, count: int) -> pd.DataFrame | None:
    """
    Fetch OHLCV bars and return a tidy DataFrame.
    Returns None on failure.
    """
    if mt5 is None:
        log.warning(f"MT5 module not available - returning None for {symbol}")
        return None
    
    rates = mt5.copy_rates_from_pos(symbol, timeframe, 0, count)
    if rates is None or len(rates) == 0:
        log.warning(f"No bars returned for {symbol} TF={timeframe}")
        return None

    df = pd.DataFrame(rates)
    df["time"] = pd.to_datetime(df["time"], unit="s", utc=True)
    df.rename(columns={
        "open": "Open", "high": "High",
        "low":  "Low",  "close": "Close",
        "tick_volume": "Volume"
    }, inplace=True)
    df.set_index("time", inplace=True)
    return df[["Open", "High", "Low", "Close", "Volume"]]


def get_symbol_info(symbol: str):
    """
    Fetch symbol info. Never modify MT5 objects (they are read-only).
    Use get_trading_point() for internal calculations instead.
    """
    if mt5 is None:
        log.warning(f"MT5 module not available - returning None for {symbol} info")
        return None
    
    info = mt5.symbol_info(symbol)
    if info is None:
        log.error(f"Symbol info not found: {symbol}")
        return None
    
    return info


# ── Global cache for point value corrections (to avoid log spam) ──
_POINT_VALUE_CACHE = {}  # {symbol: (point_value, logged)}

def get_trading_point(symbol: str) -> float:
    """
    Get the INTERNAL trading point value for distance/buffer calculations.
    
    XAUUSDm (Gold) reports point=0.001 from MT5, but actual pip is 0.01.
    This function returns the correct value to use in all calculations.
    
    Correction is cached to avoid repetitive logging (logged only once per session).
    
    Returns: float (e.g., 0.01 for XAUUSDm, or info.point for others)
    """
    global _POINT_VALUE_CACHE
    
    # Check cache first
    if symbol in _POINT_VALUE_CACHE:
        return _POINT_VALUE_CACHE[symbol][0]
    
    if mt5 is None:
        log.warning(f"MT5 module not available - using default point=0.01 for {symbol}")
        return 0.01
    
    info = mt5.symbol_info(symbol)
    if info is None:
        log.warning(f"Could not get symbol info for {symbol}, using default point=0.01")
        return 0.01
    
    # ── INTERNAL POINT VALUE LOGIC ────────────────────────────────────────
    # For gold symbols, override the MT5-reported point value
    if symbol.upper() in ("XAUUSDM", "XAUUSD", "GOLD"):
        if info.point == 0.001:
            # Log only once per session
            if symbol not in _POINT_VALUE_CACHE:
                log.info(
                    f"POINT VALUE CORRECTION | Symbol: {symbol} | "
                    f"MT5 reported: {info.point} | Using internally: 0.01"
                )
            _POINT_VALUE_CACHE[symbol] = (0.01, True)
            return 0.01
        elif info.point != 0.01:
            log.warning(
                f"UNUSUAL POINT VALUE | Symbol: {symbol} | Point: {info.point} | "
                f"Expected 0.01 for gold. Verify with broker."
            )
            _POINT_VALUE_CACHE[symbol] = (info.point, True)
            return info.point
        else:
            _POINT_VALUE_CACHE[symbol] = (0.01, True)
            return 0.01
    
    # For non-gold symbols, use the MT5-reported value
    _POINT_VALUE_CACHE[symbol] = (info.point, True)
    return info.point


def get_tick(symbol: str):
    if mt5 is None:
        log.warning(f"MT5 module not available - returning None for {symbol} tick")
        return None
    tick = mt5.symbol_info_tick(symbol)
    if tick is None:
        log.warning(f"Could not get tick for {symbol}")
    return tick


def get_account_info():
    if mt5 is None:
        log.warning("MT5 module not available - returning None for account info")
        return None
    return mt5.account_info()


def get_open_positions(symbol: str = None, magic: int = None):
    """Return list of open Position objects, optionally filtered."""
    if mt5 is None:
        log.warning("MT5 module not available - returning empty positions list")
        return []
    
    positions = mt5.positions_get(symbol=symbol) if symbol else mt5.positions_get()
    if positions is None:
        return []
    if magic is not None:
        positions = [p for p in positions if p.magic == magic]
    return list(positions)


def get_spread_points(symbol: str) -> int:
    """Return current bid/ask spread in points."""
    if mt5 is None:
        log.warning("MT5 module not available - returning default spread")
        return 9999
    
    tick = get_tick(symbol)
    if tick is None:
        return 9999
    info = get_symbol_info(symbol)
    if info is None:
        return 9999
    # Use internal trading point for correct calculation
    point = get_trading_point(symbol)
    return int(round((tick.ask - tick.bid) / point))


# ─── Order execution ──────────────────────────────────────────────────────────

def send_order(request: dict):
    """Send an order request dict and return the result."""
    if mt5 is None:
        log.error("MT5 module not available - cannot send order")
        return None
    
    result = mt5.order_send(request)
    if result is None:
        log.error(f"EXECUTION FAILED | order_send returned None | Error: {mt5.last_error()}")
        return None
    if result.retcode != mt5.TRADE_RETCODE_DONE:
        log.error(
            f"EXECUTION FAILED | retcode={result.retcode} | comment={result.comment}"
        )
        return None
    log.debug(f"EXECUTION SUCCESS | deal={result.deal}")
    return result


def close_position(position) -> bool:
    """Market-close a single position."""
    if mt5 is None:
        log.error("MT5 module not available - cannot close position")
        return False
    
    tick = get_tick(position.symbol)
    if tick is None:
        log.warning("POSITION CLOSE FAILED | Could not get tick")
        return False

    order_type = (
        mt5.ORDER_TYPE_SELL if position.type == mt5.ORDER_TYPE_BUY
        else mt5.ORDER_TYPE_BUY
    )
    price = tick.bid if order_type == mt5.ORDER_TYPE_SELL else tick.ask

    request = {
        "action":    mt5.TRADE_ACTION_DEAL,
        "symbol":    position.symbol,
        "volume":    position.volume,
        "type":      order_type,
        "position":  position.ticket,
        "price":     price,
        "deviation": settings.DEVIATION,
        "magic":     settings.MAGIC,
        "comment":   "SMC_BOT_CLOSE",
        "type_time": mt5.ORDER_TIME_GTC,
        "type_filling": mt5.ORDER_FILLING_IOC,
    }
    result = send_order(request)
    if result is None or result.retcode != mt5.TRADE_RETCODE_DONE:
        log.warning(f"POSITION CLOSE FAILED | retcode={result.retcode if result else 'None'}")
        return False
    
    log.info(f"POSITION CLOSED | ticket={position.ticket}")
    return True


def modify_sl(ticket: int, symbol: str, new_sl: float,
              new_tp: float = None) -> bool:
    """Modify stop-loss (and optionally TP) of an open position."""
    if mt5 is None:
        log.error("MT5 module not available - cannot modify SL")
        return False
    
    positions = mt5.positions_get(ticket=ticket)
    if not positions:
        log.warning(f"SL MODIFY FAILED | ticket {ticket} not found")
        return False
    pos = positions[0]
    tp  = new_tp if new_tp is not None else pos.tp

    request = {
        "action":   mt5.TRADE_ACTION_SLTP,
        "symbol":   symbol,
        "sl":       new_sl,
        "tp":       tp,
        "position": ticket,
        "magic":    settings.MAGIC,
    }
    result = send_order(request)
    if result is None or result.retcode != mt5.TRADE_RETCODE_DONE:
        log.warning(f"SL MODIFY FAILED | ticket={ticket} | retcode={result.retcode if result else 'None'}")
        return False
    
    log.info(f"SL MODIFIED | ticket={ticket} | old_sl={pos.sl:.2f} new_sl={new_sl:.2f}")
    return True


def partial_close(position, close_pct: float = 0.5) -> tuple[bool, str]:
    """Close a fraction of a position (default 50%).
    
    Returns: (success, message)
    
    Uses volume_validator to ensure broker compliance.
    If invalid, returns (False, reason) without sending order.
    """
    if mt5 is None:
        log.error("MT5 module not available - cannot partial close")
        return False, "MT5 module not available"
    
    from execution.volume_validator import validate_partial_close
    
    # Validate that partial close is executable
    is_valid, reason, validated_volume = validate_partial_close(position, close_pct)
    
    if not is_valid:
        log.info(f"PARTIAL CLOSE SKIPPED | {reason} | position={position.ticket} volume={position.volume}")
        return False, f"PARTIAL CLOSE SKIPPED | {reason}"
    
    if validated_volume <= 0:
        log.info(f"PARTIAL CLOSE SKIPPED | Validated volume <= 0 | position={position.ticket}")
        return False, "PARTIAL CLOSE SKIPPED | Validated volume <= 0"

    tick = get_tick(position.symbol)
    if tick is None:
        log.warning(f"PARTIAL CLOSE FAILED | Could not get tick")
        return False, "PARTIAL CLOSE FAILED | Could not get tick"

    order_type = (
        mt5.ORDER_TYPE_SELL if position.type == mt5.ORDER_TYPE_BUY
        else mt5.ORDER_TYPE_BUY
    )
    price = tick.bid if order_type == mt5.ORDER_TYPE_SELL else tick.ask

    request = {
        "action":    mt5.TRADE_ACTION_DEAL,
        "symbol":    position.symbol,
        "volume":    validated_volume,
        "type":      order_type,
        "position":  position.ticket,
        "price":     price,
        "deviation": settings.DEVIATION,
        "magic":     settings.MAGIC,
        "comment":   "SMC_BOT_PARTIAL",
        "type_time": mt5.ORDER_TIME_GTC,
        "type_filling": mt5.ORDER_FILLING_IOC,
    }
    result = send_order(request)
    if result is None or result.retcode != mt5.TRADE_RETCODE_DONE:
        log.warning(f"PARTIAL CLOSE FAILED | ticket={position.ticket} | close_volume={validated_volume} | retcode={result.retcode if result else 'None'}")
        return False, f"PARTIAL CLOSE FAILED | retcode={result.retcode if result else 'None'}"
    
    log.warning(f"PARTIAL CLOSE SUCCESS | ticket={position.ticket} | closed_volume={validated_volume} | remaining={position.volume - validated_volume:.2f}")
    return True, f"PARTIAL CLOSE SUCCESS | closed={validated_volume}"


# ─── Deal History (Trade Result Verification) ──────────────────────────────────

def get_deal_history(symbol: str = None, magic: int = None, lookback_hours: int = 24) -> dict:
    """
    Retrieve recent deal history from MT5 to verify trade closures.
    Returns empty deals list if MT5 unavailable.
    """
    if mt5 is None:
        log.warning("MT5 module not available - returning empty deal history")
        return {"error": "MT5 module not available", "deals": []}
    
    if symbol is None:
        symbol = settings.SYMBOL
    
    try:
        from datetime import datetime, date as date_type, timedelta
        
        today_start = datetime.combine(date_type.today(), datetime.min.time())
        today_end = datetime.combine(date_type.today(), datetime.max.time())
        query_from = today_start - timedelta(hours=1)
        query_to = today_end + timedelta(hours=1)
        
        deals = mt5.history_deals_get(query_from, query_to)
        if deals is None:
            log.warning(f"get_deal_history failed for {symbol}: {mt5.last_error()}")
            return {"error": f"MT5 history_deals_get failed", "deals": []}
        
        result_deals = []
        total_volume = 0
        total_pnl = 0.0
        
        for deal in deals:
            # Filter by symbol and magic
            if deal.symbol != symbol:
                continue
            if magic is not None and deal.magic != magic:
                continue
            
            deal_time_dt = datetime.fromtimestamp(deal.time)
            if deal_time_dt.date() != date_type.today():
                continue
            
            result_deals.append({
                "ticket": deal.ticket,
                "order": deal.order,
                "position_id": deal.position_id,
                "symbol": deal.symbol,
                "magic": deal.magic,
                "type": "BUY" if deal.type == mt5.DEAL_TYPE_BUY else "SELL",
                "entry": deal.entry,
                "profit": deal.profit,
                "commission": deal.commission,
                "swap": deal.swap,
                "price": deal.price,
                "time": deal.time,
                "time_str": deal_time_dt.isoformat(),
                "reason": deal.reason_str if hasattr(deal, 'reason_str') else "",
                "comment": deal.comment,
            })
            
            total_volume += deal.volume
            total_pnl += deal.profit
        
        return {
            "deals": result_deals,
            "deal_count": len(result_deals),
            "total_volume": total_volume,
            "total_pnl": total_pnl,
        }
    
    except Exception as e:
        log.error(f"get_deal_history exception: {e}")
        return {"error": f"Exception: {e}", "deals": []}


def get_deal_by_ticket(ticket: int) -> dict:
    """
    Retrieve a specific deal/trade from MT5 history by ticket number.
    
    Returns dict with:
    - ticket, order, symbol, type, volume, price, profit, commission, swap, comment, time
    - or {"error": "..."} if not found
    
    Usage:
        deal = get_deal_by_ticket(12345)
        if "error" not in deal:
            print(f"Trade profit: {deal['profit']}")
    """
    if mt5 is None:
        log.warning("MT5 module not available - returning error for get_deal_by_ticket")
        return {"error": "MT5 module not available"}
    
    try:
        # Search in recent deals using CORRECT API method
        from datetime import datetime, timedelta
        from_time = datetime.now() - timedelta(hours=24)
        to_time = datetime.now()
        
        deals = mt5.history_deals_get(from_time, to_time, group="*SMC*")
        if deals is None:
            return {"error": f"MT5 history_deals_get failed: {mt5.last_error()}"}
        
        for deal in deals:
            if deal.ticket == ticket or deal.order == ticket:
                return {
                    "ticket": deal.ticket,
                    "order": deal.order,
                    "symbol": deal.symbol,
                    "type": "BUY" if deal.type == mt5.DEAL_TYPE_BUY else "SELL",
                    "volume": deal.volume,
                    "price": deal.price,
                    "profit": deal.profit,
                    "commission": deal.commission,
                    "swap": deal.swap,
                    "comment": deal.comment,
                    "time": deal.time,
                }
        
        return {"error": f"Deal ticket {ticket} not found in recent history"}
        
    except Exception as e:
        log.error(f"get_deal_by_ticket exception: {e}")
        return {"error": str(e)}

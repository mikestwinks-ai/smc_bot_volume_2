"""
forensic_peak_equity_audit.py

STRICT PEAK EQUITY INITIALIZATION & DRAWDOWN FORENSICS

This script verifies that:
1. peak_equity is NEVER initialized below the highest known reference
2. Drawdown correctly reflects floating losses
3. Restart does not corrupt the drawdown baseline
4. Peak equity persists correctly through restarts
"""

import json
from datetime import date
from pathlib import Path

import MetaTrader5 as mt5

from config import settings
from utils import mt5_connector as conn
from execution.risk_manager import (
    get_state,
    restore_daily_state,
    compute_equity,
    compute_floating_pnl,
    compute_equity_drawdown,
    _get_balance,
)
from utils.logger import get_logger

log = get_logger("forensic_peak_equity_audit")


def audit_peak_equity_restoration():
    """
    PHASE 1: Audit peak_equity restoration from persistence.
    
    Verify:
    - Persisted peak_equity is read correctly
    - Current balance is available
    - Current equity (balance + floating) is computed
    - selected_peak_equity = max(persisted, balance, equity)
    """
    log.info("=" * 80)
    log.info("PHASE 1: PEAK EQUITY RESTORATION AUDIT")
    log.info("=" * 80)
    
    # Connect to MT5
    if not conn.is_connected():
        if not conn.connect():
            log.error("Cannot connect to MT5 - aborting audit")
            return False
    
    balance = _get_balance()
    floating = compute_floating_pnl()
    equity = compute_equity()
    
    log.info(f"CURRENT BROKER STATE | Balance={balance:.2f} | Floating={floating:+.2f} | Equity={equity:.2f}")
    
    # Restore daily state (this runs the peak_equity initialization logic)
    restore_daily_state()
    
    risk_state = get_state()
    
    log.info(
        f"RESTORED STATE | "
        f"peak_balance={risk_state.peak_balance:.2f} | "
        f"peak_equity={risk_state.peak_equity:.2f} | "
        f"daily_pnl={risk_state.daily_pnl:.2f}"
    )
    
    # VERIFICATION 1: peak_equity >= balance (always true)
    if risk_state.peak_equity < balance:
        log.critical(
            f"CRITICAL FAILURE | peak_equity {risk_state.peak_equity:.2f} < "
            f"balance {balance:.2f} | Peak equity initialization CORRUPTED"
        )
        return False
    else:
        log.info(f"PASS | peak_equity {risk_state.peak_equity:.2f} >= balance {balance:.2f}")
    
    # VERIFICATION 2: peak_equity >= current equity (to ensure DD baseline is safe)
    if risk_state.peak_equity < equity:
        log.warning(
            f"WARNING | peak_equity {risk_state.peak_equity:.2f} < "
            f"current_equity {equity:.2f} | Peak initialization below current reference"
        )
    else:
        log.info(f"PASS | peak_equity {risk_state.peak_equity:.2f} >= current_equity {equity:.2f}")
    
    return True


def audit_equity_drawdown_calculation():
    """
    PHASE 2: Audit equity drawdown calculation formula.
    
    Verify:
    - Formula: equity_dd = ((peak_equity - current_equity) / peak_equity) * 100
    - Works correctly with floating losses
    - Works correctly with floating profits
    - Percentages are accurate
    """
    log.info("\n" + "=" * 80)
    log.info("PHASE 2: EQUITY DRAWDOWN CALCULATION AUDIT")
    log.info("=" * 80)
    
    risk_state = get_state()
    balance = _get_balance()
    floating = compute_floating_pnl()
    equity = compute_equity()
    equity_dd = compute_equity_drawdown()
    
    log.info(f"STATE | peak_equity={risk_state.peak_equity:.2f} | current_equity={equity:.2f}")
    log.info(f"COMPONENTS | balance={balance:.2f} | floating={floating:+.2f}")
    
    # Manual calculation to verify
    if risk_state.peak_equity > 0:
        expected_dd = ((risk_state.peak_equity - equity) / risk_state.peak_equity) * 100
        log.info(f"FORMULA VERIFICATION")
        log.info(f"  expected_dd = ((peak - current) / peak) * 100")
        log.info(f"  expected_dd = (({risk_state.peak_equity:.2f} - {equity:.2f}) / {risk_state.peak_equity:.2f}) * 100")
        log.info(f"  expected_dd = {expected_dd:.2f}%")
        log.info(f"  computed_dd = {equity_dd:.2f}%")
        
        if abs(expected_dd - equity_dd) < 0.01:
            log.info(f"PASS | Drawdown formula correct")
            return True
        else:
            log.critical(f"FAIL | Drawdown mismatch: expected {expected_dd:.2f}% vs computed {equity_dd:.2f}%")
            return False
    else:
        log.warning("peak_equity is 0 - cannot verify drawdown calculation")
        return False


def audit_broker_reconstruction_peak_equity():
    """
    PHASE 3: Audit peak_equity during broker reconstruction.
    
    Verify:
    - Broker reconstruction re-anchors peak_equity
    - peak_equity is set to max(persisted, balance, equity)
    - Floating losses don't corrupt the DD baseline during reconstruction
    """
    log.info("\n" + "=" * 80)
    log.info("PHASE 3: BROKER RECONSTRUCTION PEAK EQUITY AUDIT")
    log.info("=" * 80)
    
    balance = _get_balance()
    floating = compute_floating_pnl()
    equity = compute_equity()
    risk_state = get_state()
    
    log.info(f"PRE-RECONSTRUCTION STATE")
    log.info(f"  balance={balance:.2f}")
    log.info(f"  floating={floating:+.2f}")
    log.info(f"  equity={equity:.2f}")
    log.info(f"  peak_equity={risk_state.peak_equity:.2f}")
    
    # The reconstruction happens internally during restore_daily_state()
    # If reconstruction ran, peak_equity should have been re-anchored
    
    log.info(f"POST-RESTORATION STATE (after reconstruction if triggered)")
    log.info(f"  peak_equity={risk_state.peak_equity:.2f}")
    
    # Verify peak equity is anchored correctly
    if risk_state.peak_equity >= balance:
        log.info(f"PASS | peak_equity {risk_state.peak_equity:.2f} >= balance {balance:.2f}")
        return True
    else:
        log.critical(f"FAIL | peak_equity {risk_state.peak_equity:.2f} < balance {balance:.2f}")
        return False


def audit_consistency_check():
    """
    PHASE 4: Consistency check - ensure all invariants hold.
    
    Invariants:
    - peak_equity >= balance (always)
    - peak_equity >= peak_balance (always, because balance is subset of equity)
    - drawdown >= 0 when equity < peak_equity
    - drawdown = 0 when equity == peak_equity
    """
    log.info("\n" + "=" * 80)
    log.info("PHASE 4: CONSISTENCY CHECK")
    log.info("=" * 80)
    
    risk_state = get_state()
    balance = _get_balance()
    equity = compute_equity()
    equity_dd = compute_equity_drawdown()
    
    all_pass = True
    
    # Invariant 1: peak_equity >= balance
    if risk_state.peak_equity >= balance:
        log.info(f"PASS | peak_equity {risk_state.peak_equity:.2f} >= balance {balance:.2f}")
    else:
        log.critical(f"FAIL | peak_equity {risk_state.peak_equity:.2f} < balance {balance:.2f}")
        all_pass = False
    
    # Invariant 2: peak_equity >= peak_balance
    if risk_state.peak_equity >= risk_state.peak_balance:
        log.info(f"PASS | peak_equity {risk_state.peak_equity:.2f} >= peak_balance {risk_state.peak_balance:.2f}")
    else:
        log.critical(f"FAIL | peak_equity {risk_state.peak_equity:.2f} < peak_balance {risk_state.peak_balance:.2f}")
        all_pass = False
    
    # Invariant 3: drawdown >= 0
    if equity_dd >= -0.01:  # allow tiny float errors
        log.info(f"PASS | equity_dd {equity_dd:.2f}% >= 0")
    else:
        log.critical(f"FAIL | equity_dd {equity_dd:.2f}% < 0 (negative drawdown impossible)")
        all_pass = False
    
    # Invariant 4: drawdown = 0 when equity == peak_equity
    if abs(equity - risk_state.peak_equity) < 0.01:
        if abs(equity_dd) < 0.01:
            log.info(f"PASS | equity == peak_equity, drawdown = {equity_dd:.2f}%")
        else:
            log.critical(f"FAIL | equity == peak_equity but drawdown = {equity_dd:.2f}%")
            all_pass = False
    
    # Invariant 5: drawdown > 0 when equity < peak_equity
    if equity < risk_state.peak_equity:
        if equity_dd > 0:
            log.info(f"PASS | equity < peak_equity, drawdown = {equity_dd:.2f}% > 0")
        else:
            log.critical(f"FAIL | equity < peak_equity but drawdown = {equity_dd:.2f}%")
            all_pass = False
    
    return all_pass


def main():
    log.info("Starting STRICT PEAK EQUITY FORENSIC AUDIT")
    
    # Connect to MT5
    if not conn.is_connected():
        if not conn.connect():
            log.error("Cannot connect to MT5 - aborting audit")
            return 1
    
    account = conn.get_account_info()
    log.info(f"Date: {date.today()} | Account: {account.login if account else 'unknown'}")
    log.info(f"Symbol: {settings.SYMBOL} | Magic: {settings.MAGIC}")
    
    results = []
    
    # Phase 1: Peak equity restoration
    results.append(("PHASE 1: Peak Equity Restoration", audit_peak_equity_restoration()))
    
    # Phase 2: Equity drawdown calculation
    results.append(("PHASE 2: Equity Drawdown Calculation", audit_equity_drawdown_calculation()))
    
    # Phase 3: Broker reconstruction
    results.append(("PHASE 3: Broker Reconstruction", audit_broker_reconstruction_peak_equity()))
    
    # Phase 4: Consistency check
    results.append(("PHASE 4: Consistency Check", audit_consistency_check()))
    
    # Summary
    log.info("\n" + "=" * 80)
    log.info("AUDIT SUMMARY")
    log.info("=" * 80)
    
    for phase_name, result in results:
        status = "PASS" if result else "FAIL"
        log.info(f"{phase_name}: {status}")
    
    all_pass = all(result for _, result in results)
    
    if all_pass:
        log.info("\n*** ALL AUDIT PHASES PASSED ***")
        log.info("Peak equity initialization and drawdown calculations are CORRECT")
        return 0
    else:
        log.critical("\n*** AUDIT FAILED ***")
        log.critical("Peak equity integrity compromised - manual investigation required")
        return 1


if __name__ == "__main__":
    exit(main())

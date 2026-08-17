"""
metals_trade_engine.py

PRO AI QUANT TERMINAL V3.5
Autonomous Metals Paper Execution Engine

Responsibilities:
- Scan Gold and Silver
- Select best approved setup
- Open max ONE metals position
- Monitor independent metals TP / SL
- Preserve Crypto position
- Use METALS_MAIN slot only
- PAPER TRADING ONLY
- REAL ORDERS DISABLED
"""

from typing import Dict, Optional

from metals_scanner import (
    scan_metals,
    get_best_metals_setup,
    calculate_metals_position_size,
)

from metals_engine import (
    build_metal_snapshot,
)

from paper_trader import (
    METALS_SLOT,
)


# ============================================================
# CONFIG
# ============================================================

DEFAULT_METALS_RISK_PCT = 1.0


# ============================================================
# GET LIVE METALS PRICE
# ============================================================

def get_metals_current_price(
    symbol: str,
) -> Optional[float]:

    try:

        snapshot = build_metal_snapshot(
            symbol
        )

        if snapshot.get(
            "status"
        ) != "LIVE":

            return None

        price = snapshot.get(
            "last"
        )

        if price is None:

            return None

        price = float(
            price
        )

        if price <= 0:

            return None

        return price

    except Exception as error:

        print(
            "[METALS PRICE ERROR] "
            f"{symbol}: {error}",
            flush=True,
        )

        return None


# ============================================================
# MONITOR OPEN METALS POSITION
# ============================================================

def monitor_metals_position(
    trader,
) -> Dict:

    position = trader.get_position(
        METALS_SLOT
    )

    if not position:

        return {
            "status":
                "NO_POSITION",
        }

    symbol = position.get(
        "symbol"
    )

    current_price = (
        get_metals_current_price(
            symbol
        )
    )

    if current_price is None:

        return {
            "status":
                "PRICE_UNAVAILABLE",

            "position":
                position,
        }

    result = trader.update_price(
        current_price=current_price,
        slot=METALS_SLOT,
    )

    if result is None:

        return {
            "status":
                "NO_POSITION",
        }

    result[
        "current_price"
    ] = current_price

    return result


# ============================================================
# OPEN APPROVED METALS TRADE
# ============================================================

def open_metals_trade(
    trader,
    setup: Dict,
    risk_pct: float = DEFAULT_METALS_RISK_PCT,
) -> Dict:

    if not setup:

        return {
            "status":
                "SKIPPED",

            "reason":
                "No metals setup",
        }

    if not setup.get(
        "approved",
        False,
    ):

        return {
            "status":
                "SKIPPED",

            "reason":
                "Setup not approved",
        }

    if not trader.slot_available(
        METALS_SLOT
    ):

        return {
            "status":
                "SKIPPED",

            "reason":
                "METALS_MAIN already occupied",

            "position":
                trader.get_position(
                    METALS_SLOT
                ),
        }

    symbol = setup.get(
        "symbol"
    )

    signal = setup.get(
        "signal"
    )

    entry_price = setup.get(
        "entry_price"
    )

    targets = setup.get(
        "targets",
        {},
    )

    take_profit = targets.get(
        "take_profit"
    )

    stop_loss = targets.get(
        "stop_loss"
    )

    if not all(
        [
            symbol,
            signal,
            entry_price,
            take_profit,
            stop_loss,
        ]
    ):

        return {
            "status":
                "SKIPPED",

            "reason":
                "Incomplete metals trade parameters",
        }

    balance = trader.get_balance()

    quantity = (
        calculate_metals_position_size(
            account_balance=balance,
            risk_pct=risk_pct,
            entry_price=entry_price,
            stop_loss=stop_loss,
        )
    )

    if quantity <= 0:

        return {
            "status":
                "SKIPPED",

            "reason":
                "Invalid metals position size",
        }

    result = trader.open_trade(
        symbol=symbol,
        signal=signal,
        entry_price=entry_price,
        quantity=quantity,
        take_profit=take_profit,
        stop_loss=stop_loss,
        slot=METALS_SLOT,
    )

    result[
        "risk_pct"
    ] = risk_pct

    result[
        "mtf_confidence"
    ] = setup.get(
        "mtf_confidence",
        0.0,
    )

    result[
        "score"
    ] = setup.get(
        "score",
        0.0,
    )

    return result


# ============================================================
# FULL METALS AUTONOMOUS CYCLE
# ============================================================

def run_metals_cycle(
    trader,
    risk_pct: float = DEFAULT_METALS_RISK_PCT,
) -> Dict:

    # --------------------------------------------------------
    # FIRST: MANAGE EXISTING METALS POSITION
    # --------------------------------------------------------

    existing = trader.get_position(
        METALS_SLOT
    )

    if existing:

        monitor_result = (
            monitor_metals_position(
                trader
            )
        )

        return {
            "status":
                "MANAGING_POSITION",

            "position":
                trader.get_position(
                    METALS_SLOT
                ),

            "monitor":
                monitor_result,

            "scanner_results":
                [],

            "best_setup":
                None,
        }

    # --------------------------------------------------------
    # SECOND: SCAN GOLD + SILVER
    # --------------------------------------------------------

    results = scan_metals()

    best_setup = (
        get_best_metals_setup(
            results
        )
    )

    if best_setup is None:

        return {
            "status":
                "NO_QUALIFYING_METALS_TRADE",

            "position":
                None,

            "scanner_results":
                results,

            "best_setup":
                None,
        }

    # --------------------------------------------------------
    # THIRD: OPEN PAPER POSITION
    # --------------------------------------------------------

    execution = open_metals_trade(
        trader=trader,
        setup=best_setup,
        risk_pct=risk_pct,
    )

    return {
        "status":
            execution.get(
                "status",
                "UNKNOWN",
            ),

        "position":
            trader.get_position(
                METALS_SLOT
            ),

        "scanner_results":
            results,

        "best_setup":
            best_setup,

        "execution":
            execution,
    }


# ============================================================
# SAFE STATUS SNAPSHOT
# ============================================================

def get_metals_trade_status(
    trader,
) -> Dict:

    position = trader.get_position(
        METALS_SLOT
    )

    if position:

        current_price = (
            get_metals_current_price(
                position.get(
                    "symbol"
                )
            )
        )

        return {
            "status":
                "POSITION_OPEN",

            "position":
                position,

            "current_price":
                current_price,

            "real_orders":
                False,
        }

    return {
        "status":
            "FLAT",

        "position":
            None,

        "current_price":
            None,

        "real_orders":
            False,
    }

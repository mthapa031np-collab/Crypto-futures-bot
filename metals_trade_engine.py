"""
metals_trade_engine.py

PRO AI QUANT TERMINAL V3.7
Autonomous Metals Paper Execution Engine

Responsibilities:
- Scan Gold and Silver
- Select best SAFE approved setup
- Open max ONE metals position
- Monitor independent metals TP / SL
- Preserve Crypto position
- Use METALS_MAIN slot only
- Reject stale / unsafe quote data
- Require scanner safety gate
- PAPER TRADING ONLY
- REAL ORDERS DISABLED
"""

from typing import Dict, Optional

from metals_scanner import (
    scan_metals,
    get_best_metals_setup,
    calculate_metals_position_size,
)

from metals_provider import (
    get_metal_quote,
)

from paper_trader import (
    METALS_SLOT,
)


# ============================================================
# CONFIG
# ============================================================

DEFAULT_METALS_RISK_PCT = 1.0

REAL_METALS_ORDERS_ENABLED = False


# ============================================================
# SAFE HELPERS
# ============================================================

def _safe_float(
    value,
    default=None,
):

    try:

        if value is None:
            return default

        value = float(value)

        if value <= 0:
            return default

        return value

    except (
        TypeError,
        ValueError,
    ):

        return default


def _quote_is_safe(
    quote: Optional[Dict],
) -> bool:

    if not quote:
        return False

    price = _safe_float(
        quote.get(
            "last"
        )
    )

    if price is None:
        return False

    if quote.get(
        "stale",
        False,
    ):
        return False

    if quote.get(
        "data_fresh",
        True,
    ) is False:
        return False

    if quote.get(
        "tradable_data",
        True,
    ) is False:
        return False

    return True


# ============================================================
# GET SAFE LIVE METALS PRICE
# ============================================================

def get_metals_current_price(
    symbol: str,
) -> Optional[float]:

    try:

        quote = get_metal_quote(
            symbol
        )

        if not _quote_is_safe(
            quote
        ):

            return None

        return _safe_float(
            quote.get(
                "last"
            )
        )

    except Exception as error:

        print(
            "[METALS PRICE ERROR] "
            f"{symbol}: {error}",
            flush=True,
        )

        return None


# ============================================================
# GET SAFE LIVE QUOTE
# ============================================================

def get_safe_metals_quote(
    symbol: str,
) -> Optional[Dict]:

    try:

        quote = get_metal_quote(
            symbol
        )

        if not _quote_is_safe(
            quote
        ):

            return None

        return quote

    except Exception as error:

        print(
            "[METALS SAFE QUOTE ERROR] "
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

    if not symbol:

        return {
            "status":
                "POSITION_ERROR",

            "reason":
                "Open metals position has no symbol",

            "position":
                position,
        }

    # --------------------------------------------------------
    # CRITICAL SAFETY:
    # NEVER trigger TP/SL using stale price.
    # --------------------------------------------------------

    quote = get_safe_metals_quote(
        symbol
    )

    if quote is None:

        return {
            "status":
                "PRICE_UNAVAILABLE",

            "reason":
                "Fresh tradable metals quote unavailable",

            "position":
                position,

            "tp_sl_updated":
                False,
        }

    current_price = _safe_float(
        quote.get(
            "last"
        )
    )

    if current_price is None:

        return {
            "status":
                "PRICE_UNAVAILABLE",

            "reason":
                "Invalid metals price",

            "position":
                position,

            "tp_sl_updated":
                False,
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

    result[
        "quote_source"
    ] = quote.get(
        "source"
    )

    result[
        "quote_fresh"
    ] = True

    result[
        "tp_sl_updated"
    ] = True

    return result


# ============================================================
# VALIDATE APPROVED SETUP
# ============================================================

def validate_metals_setup(
    setup: Optional[Dict],
) -> Dict:

    if not setup:

        return {
            "valid":
                False,

            "reason":
                "No metals setup",
        }

    if not setup.get(
        "approved",
        False,
    ):

        return {
            "valid":
                False,

            "reason":
                "Setup not approved",
        }

    # --------------------------------------------------------
    # V3.7 SCANNER SAFETY GATE
    # --------------------------------------------------------

    if not setup.get(
        "safety_gate",
        False,
    ):

        return {
            "valid":
                False,

            "reason":
                "Scanner safety gate failed",
        }

    if not setup.get(
        "quote_fresh",
        False,
    ):

        return {
            "valid":
                False,

            "reason":
                "Metals quote not fresh",
        }

    if not setup.get(
        "candles_fresh",
        False,
    ):

        return {
            "valid":
                False,

            "reason":
                "Metals candles not fresh",
        }

    if not setup.get(
        "all_timeframes_valid",
        False,
    ):

        return {
            "valid":
                False,

            "reason":
                "Not all metals timeframes valid",
        }

    symbol = setup.get(
        "symbol"
    )

    signal = str(
        setup.get(
            "signal",
            ""
        )
    ).upper()

    if symbol not in (
        "XAUUSD",
        "XAGUSD",
    ):

        return {
            "valid":
                False,

            "reason":
                "Unsupported metals symbol",
        }

    if signal not in (
        "BUY",
        "SELL",
    ):

        return {
            "valid":
                False,

            "reason":
                "Invalid metals signal",
        }

    entry_price = _safe_float(
        setup.get(
            "entry_price"
        )
    )

    targets = setup.get(
        "targets",
        {},
    )

    take_profit = _safe_float(
        targets.get(
            "take_profit"
        )
    )

    stop_loss = _safe_float(
        targets.get(
            "stop_loss"
        )
    )

    if (
        entry_price is None
        or take_profit is None
        or stop_loss is None
    ):

        return {
            "valid":
                False,

            "reason":
                "Incomplete metals trade parameters",
        }

    # --------------------------------------------------------
    # TP / SL DIRECTION VALIDATION
    # --------------------------------------------------------

    if signal == "BUY":

        if not (
            stop_loss
            < entry_price
            < take_profit
        ):

            return {
                "valid":
                    False,

                "reason":
                    "Invalid BUY TP/SL structure",
            }

    if signal == "SELL":

        if not (
            take_profit
            < entry_price
            < stop_loss
        ):

            return {
                "valid":
                    False,

                "reason":
                    "Invalid SELL TP/SL structure",
            }

    # --------------------------------------------------------
    # FINAL LIVE QUOTE REVALIDATION
    # --------------------------------------------------------

    quote = get_safe_metals_quote(
        symbol
    )

    if quote is None:

        return {
            "valid":
                False,

            "reason":
                "Fresh quote unavailable at execution time",
        }

    live_price = _safe_float(
        quote.get(
            "last"
        )
    )

    if live_price is None:

        return {
            "valid":
                False,

            "reason":
                "Invalid live metals execution price",
        }

    return {
        "valid":
            True,

        "reason":
            "Metals setup passed execution safety",

        "symbol":
            symbol,

        "signal":
            signal,

        "entry_price":
            entry_price,

        "live_price":
            live_price,

        "take_profit":
            take_profit,

        "stop_loss":
            stop_loss,

        "quote":
            quote,
    }


# ============================================================
# OPEN APPROVED METALS TRADE
# ============================================================

def open_metals_trade(
    trader,
    setup: Dict,
    risk_pct: float = DEFAULT_METALS_RISK_PCT,
) -> Dict:

    # --------------------------------------------------------
    # REAL ORDER MASTER LOCK
    # --------------------------------------------------------

    if REAL_METALS_ORDERS_ENABLED:

        return {
            "status":
                "BLOCKED",

            "reason":
                "Real metals execution is not supported",
        }

    # --------------------------------------------------------
    # FULL SAFETY VALIDATION
    # --------------------------------------------------------

    validation = validate_metals_setup(
        setup
    )

    if not validation.get(
        "valid",
        False,
    ):

        return {
            "status":
                "SKIPPED",

            "reason":
                validation.get(
                    "reason",
                    "Metals safety validation failed",
                ),
        }

    # --------------------------------------------------------
    # SLOT SAFETY
    # --------------------------------------------------------

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

    symbol = validation[
        "symbol"
    ]

    signal = validation[
        "signal"
    ]

    # IMPORTANT:
    # Use fresh live execution price rather than
    # blindly trusting earlier scanner price.
    entry_price = validation[
        "live_price"
    ]

    take_profit = validation[
        "take_profit"
    ]

    stop_loss = validation[
        "stop_loss"
    ]

    # --------------------------------------------------------
    # REBUILD TARGET DISTANCES FROM LIVE ENTRY
    # --------------------------------------------------------
    #
    # Scanner targets were calculated from the scanner entry.
    # We preserve target distances while moving them to the
    # freshly validated execution price.
    # --------------------------------------------------------

    scanner_entry = validation[
        "entry_price"
    ]

    tp_distance = abs(
        take_profit
        - scanner_entry
    )

    sl_distance = abs(
        scanner_entry
        - stop_loss
    )

    if (
        tp_distance <= 0
        or sl_distance <= 0
    ):

        return {
            "status":
                "SKIPPED",

            "reason":
                "Invalid TP/SL distance",
        }

    if signal == "BUY":

        take_profit = (
            entry_price
            + tp_distance
        )

        stop_loss = (
            entry_price
            - sl_distance
        )

    elif signal == "SELL":

        take_profit = (
            entry_price
            - tp_distance
        )

        stop_loss = (
            entry_price
            + sl_distance
        )

    # --------------------------------------------------------
    # BALANCE / POSITION SIZE
    # --------------------------------------------------------

    balance = _safe_float(
        trader.get_balance()
    )

    if balance is None:

        return {
            "status":
                "SKIPPED",

            "reason":
                "Invalid paper account balance",
        }

    risk_pct = _safe_float(
        risk_pct
    )

    if risk_pct is None:

        return {
            "status":
                "SKIPPED",

            "reason":
                "Invalid metals risk percentage",
        }

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

    # --------------------------------------------------------
    # PAPER TRADE ONLY
    # --------------------------------------------------------

    result = trader.open_trade(
        symbol=symbol,
        signal=signal,
        entry_price=entry_price,
        quantity=quantity,
        take_profit=take_profit,
        stop_loss=stop_loss,
        slot=METALS_SLOT,
    )

    if result is None:

        return {
            "status":
                "ERROR",

            "reason":
                "Paper trader returned no result",
        }

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

    result[
        "safety_gate"
    ] = True

    result[
        "quote_fresh"
    ] = True

    result[
        "candles_fresh"
    ] = setup.get(
        "candles_fresh",
        False,
    )

    result[
        "paper_trade"
    ] = True

    result[
        "real_order"
    ] = False

    return result


# ============================================================
# FULL METALS AUTONOMOUS CYCLE
# ============================================================

def run_metals_cycle(
    trader,
    risk_pct: float = DEFAULT_METALS_RISK_PCT,
) -> Dict:

    # --------------------------------------------------------
    # 1. MANAGE EXISTING METALS POSITION
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

            "real_orders":
                False,
        }

    # --------------------------------------------------------
    # 2. SCAN GOLD + SILVER
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

            "real_orders":
                False,
        }

    # --------------------------------------------------------
    # 3. EXECUTION SAFETY CHECK
    # --------------------------------------------------------

    if not best_setup.get(
        "safety_gate",
        False,
    ):

        return {
            "status":
                "SAFETY_BLOCKED",

            "reason":
                "Best setup failed scanner safety gate",

            "position":
                None,

            "scanner_results":
                results,

            "best_setup":
                best_setup,

            "real_orders":
                False,
        }

    # --------------------------------------------------------
    # 4. OPEN PAPER POSITION
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

        "real_orders":
            False,
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

        symbol = position.get(
            "symbol"
        )

        quote = get_safe_metals_quote(
            symbol
        )

        current_price = None

        if quote:

            current_price = _safe_float(
                quote.get(
                    "last"
                )
            )

        return {
            "status":
                "POSITION_OPEN",

            "position":
                position,

            "current_price":
                current_price,

            "price_fresh":
                quote is not None,

            "real_orders":
                False,

            "paper_only":
                True,
        }

    return {
        "status":
            "FLAT",

        "position":
            None,

        "current_price":
            None,

        "price_fresh":
            False,

        "real_orders":
            False,

        "paper_only":
            True,
    }

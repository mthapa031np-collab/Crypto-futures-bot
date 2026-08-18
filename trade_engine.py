"""
trade_engine.py

PRO AI QUANT TERMINAL V4.1
CRYPTO PAPER EXECUTION ENGINE
WITH UNIFIED PORTFOLIO RISK GOVERNOR

Responsibilities
----------------
- Open approved Crypto paper trades
- Use CRYPTO_MAIN only
- Preserve independent METALS_MAIN position
- Central Portfolio Risk Governor approval
- Automatic TP / SL monitoring
- Manual paper close
- Existing Test Mode compatibility
- Existing risk_manager compatibility
- Future-ready for trailing stop / break-even

Execution chain
---------------
Crypto Scanner / Strategy
        ↓
trade_engine.py
        ↓
risk_manager.py
        ↓
Portfolio Risk Governor V4
        ↓
PaperTrader CRYPTO_MAIN

IMPORTANT
---------
PAPER TRADING ONLY
REAL ORDERS HARD DISABLED
"""

from __future__ import annotations

from typing import Dict, Optional

from market_data import (
    get_candles,
    get_ticker,
)

from risk_manager import (
    calculate_trade_plan,
    validate_trade_plan,
)

from settings import (
    RISK_PCT,
    TP_PCT,
    SL_PCT,
    TEST_MODE,
    TEST_TP_PCT,
    TEST_SL_PCT,
    TIMEFRAME_MINUTES,
    CANDLE_LIMIT,
    TRAILING_STOP_ENABLED,
    TRAILING_STOP_PCT,
    BREAK_EVEN_ENABLED,
    BREAK_EVEN_TRIGGER_PCT,
)

from paper_trader import (
    CRYPTO_SLOT,
)

from portfolio_risk_governor import (
    authorize_trade,
)


# ============================================================
# HARD SAFETY
# ============================================================

PAPER_ONLY = True
REAL_CRYPTO_ORDERS_ENABLED = False


# ============================================================
# HELPERS
# ============================================================

def _safe_float(
    value,
    default=0.0,
):

    try:

        if value is None:
            return default

        number = float(
            value
        )

        if number != number:
            return default

        return number

    except (
        TypeError,
        ValueError,
    ):

        return default


def _normalize_symbol(
    symbol,
):

    return (
        str(symbol)
        .upper()
        .replace("/", "")
        .replace("-", "")
        .replace(" ", "")
        .strip()
    )


def _active_tp_pct():

    if TEST_MODE:

        return TEST_TP_PCT

    return TP_PCT


def _active_sl_pct():

    if TEST_MODE:

        return TEST_SL_PCT

    return SL_PCT


# ============================================================
# CURRENT MARKET PRICE
# ============================================================

def get_current_price(
    symbol: str,
) -> Optional[float]:

    symbol = _normalize_symbol(
        symbol
    )

    if not symbol:

        return None

    # --------------------------------------------------------
    # PRIMARY:
    # PUBLIC LIVE TICKER
    # --------------------------------------------------------

    try:

        ticker = get_ticker(
            symbol=symbol,
            exchange="PUBLIC",
            api_key="",
            api_secret="",
            use_testnet=False,
        )

        if ticker:

            price = _safe_float(
                ticker.get(
                    "last"
                ),
                0.0,
            )

            if price > 0:

                return price

    except Exception as error:

        print(
            "[CRYPTO PRICE TICKER ERROR] "
            f"{symbol}: {error}",
            flush=True,
        )

    # --------------------------------------------------------
    # FALLBACK:
    # LATEST PUBLIC CANDLE CLOSE
    # --------------------------------------------------------

    try:

        candles = get_candles(
            exchange="PUBLIC",
            symbol=symbol,
            timeframe_minutes=TIMEFRAME_MINUTES,
            limit=CANDLE_LIMIT,
            api_key="",
            api_secret="",
            use_testnet=False,
        )

        if (
            candles is None
            or len(candles) == 0
        ):

            return None

        price = _safe_float(
            candles[
                "close"
            ].iloc[-1],
            0.0,
        )

        if price <= 0:

            return None

        return price

    except Exception as error:

        print(
            "[CRYPTO PRICE CANDLE ERROR] "
            f"{symbol}: {error}",
            flush=True,
        )

        return None


# ============================================================
# POSITION STATUS
# ============================================================

def get_position_status(
    trader,
) -> Dict:

    position = trader.get_position(
        CRYPTO_SLOT
    )

    if not position:

        return {
            "has_position":
                False,

            "slot":
                CRYPTO_SLOT,

            "position":
                None,

            "paper_only":
                True,

            "real_orders":
                False,
        }

    return {
        "has_position":
            True,

        "slot":
            CRYPTO_SLOT,

        "position":
            position,

        "paper_only":
            True,

        "real_orders":
            False,
    }


# ============================================================
# SETUP VALIDATION
# ============================================================

def _validate_crypto_setup(
    setup: Dict,
) -> Dict:

    if not setup:

        return {
            "valid":
                False,

            "reason":
                "Missing setup",
        }

    symbol = _normalize_symbol(
        setup.get(
            "symbol",
            "",
        )
    )

    signal = str(
        setup.get(
            "signal",
            "NO TRADE",
        )
    ).upper().strip()

    if not symbol:

        return {
            "valid":
                False,

            "reason":
                "Missing Crypto symbol",
        }

    if signal not in (
        "BUY",
        "SELL",
    ):

        return {
            "valid":
                False,

            "reason":
                "Invalid Crypto signal",
        }

    # Scanner / strategy layers may provide approved=False.
    # Respect it when explicitly present.
    if (
        "approved" in setup
        and setup.get(
            "approved"
        ) is False
    ):

        return {
            "valid":
                False,

            "reason":
                "Crypto setup not approved",
        }

    return {
        "valid":
            True,

        "symbol":
            symbol,

        "signal":
            signal,
    }


# ============================================================
# ENTRY PRICE
# ============================================================

def _resolve_entry_price(
    setup: Dict,
    symbol: str,
) -> Optional[float]:

    # Existing scanner uses "price".
    # Future strategy layers may use "entry_price".

    candidates = (
        setup.get(
            "entry_price"
        ),
        setup.get(
            "price"
        ),
    )

    for candidate in candidates:

        value = _safe_float(
            candidate,
            0.0,
        )

        if value > 0:

            return value

    return get_current_price(
        symbol
    )


# ============================================================
# OPEN APPROVED CRYPTO TRADE
# ============================================================

def open_approved_trade(
    trader,
    setup: Dict,
) -> Dict:

    # --------------------------------------------------------
    # HARD REAL EXECUTION LOCK
    # --------------------------------------------------------

    if (
        not PAPER_ONLY
        or REAL_CRYPTO_ORDERS_ENABLED
    ):

        return {
            "status":
                "BLOCKED",

            "reason":
                "Real Crypto execution is hard locked",

            "paper_only":
                True,

            "real_orders":
                False,
        }

    # --------------------------------------------------------
    # VALIDATE SETUP
    # --------------------------------------------------------

    validation = _validate_crypto_setup(
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
                    "Invalid Crypto setup",
                ),

            "paper_only":
                True,

            "real_orders":
                False,
        }

    symbol = validation[
        "symbol"
    ]

    signal = validation[
        "signal"
    ]

    # --------------------------------------------------------
    # CRYPTO SLOT PROTECTION
    # --------------------------------------------------------

    existing = trader.get_position(
        CRYPTO_SLOT
    )

    if existing:

        return {
            "status":
                "SKIPPED",

            "reason":
                "CRYPTO_MAIN already occupied",

            "position":
                existing,

            "paper_only":
                True,

            "real_orders":
                False,
        }

    if not trader.slot_available(
        CRYPTO_SLOT
    ):

        return {
            "status":
                "SKIPPED",

            "reason":
                "CRYPTO_MAIN is not available",

            "paper_only":
                True,

            "real_orders":
                False,
        }

    # --------------------------------------------------------
    # ENTRY PRICE
    # --------------------------------------------------------

    entry_price = _resolve_entry_price(
        setup,
        symbol,
    )

    entry_price = _safe_float(
        entry_price,
        0.0,
    )

    if entry_price <= 0:

        return {
            "status":
                "SKIPPED",

            "reason":
                (
                    "Could not determine "
                    "Crypto entry price"
                ),

            "paper_only":
                True,

            "real_orders":
                False,
        }

    # --------------------------------------------------------
    # BALANCE
    # --------------------------------------------------------

    balance = _safe_float(
        trader.get_balance(),
        0.0,
    )

    if balance <= 0:

        return {
            "status":
                "REJECTED",

            "reason":
                "Invalid paper account balance",

            "paper_only":
                True,

            "real_orders":
                False,
        }

    # --------------------------------------------------------
    # ACTIVE TP / SL
    # --------------------------------------------------------

    tp_pct = _safe_float(
        _active_tp_pct(),
        0.0,
    )

    sl_pct = _safe_float(
        _active_sl_pct(),
        0.0,
    )

    if (
        tp_pct <= 0
        or sl_pct <= 0
    ):

        return {
            "status":
                "REJECTED",

            "reason":
                "Invalid active TP/SL configuration",

            "paper_only":
                True,

            "real_orders":
                False,
        }

    # --------------------------------------------------------
    # EXISTING CRYPTO RISK MANAGER
    # --------------------------------------------------------

    plan = calculate_trade_plan(
        balance=balance,
        entry_price=entry_price,
        signal=signal,
        risk_percent=RISK_PCT,
        stop_loss_percent=sl_pct,
        take_profit_percent=tp_pct,
    )

    if not validate_trade_plan(
        plan
    ):

        return {
            "status":
                "REJECTED",

            "reason":
                "Risk manager rejected plan",

            "plan":
                plan,

            "paper_only":
                True,

            "real_orders":
                False,
        }

    quantity = _safe_float(
        plan.get(
            "quantity"
        ),
        0.0,
    )

    take_profit = _safe_float(
        plan.get(
            "take_profit"
        ),
        0.0,
    )

    stop_loss = _safe_float(
        plan.get(
            "stop_loss"
        ),
        0.0,
    )

    if (
        quantity <= 0
        or take_profit <= 0
        or stop_loss <= 0
    ):

        return {
            "status":
                "REJECTED",

            "reason":
                "Risk plan contains invalid parameters",

            "plan":
                plan,

            "paper_only":
                True,

            "real_orders":
                False,
        }

    # --------------------------------------------------------
    # TP / SL STRUCTURE VALIDATION
    # --------------------------------------------------------

    if signal == "BUY":

        structure_valid = (
            stop_loss
            < entry_price
            < take_profit
        )

    else:

        structure_valid = (
            take_profit
            < entry_price
            < stop_loss
        )

    if not structure_valid:

        return {
            "status":
                "REJECTED",

            "reason":
                "Invalid Crypto TP/SL structure",

            "plan":
                plan,

            "paper_only":
                True,

            "real_orders":
                False,
        }

    # ========================================================
    # PORTFOLIO RISK GOVERNOR
    # ========================================================

    governor = authorize_trade(
        trader,
        asset_class="CRYPTO",
        symbol=symbol,
        entry_price=entry_price,
        stop_loss=stop_loss,
        quantity=quantity,
        risk_pct=RISK_PCT,
    )

    if not governor.get(
        "approved",
        False,
    ):

        return {
            "status":
                "RISK_BLOCKED",

            "reason":
                governor.get(
                    "reason",
                    "Portfolio Risk Governor blocked Crypto trade",
                ),

            "governor":
                governor,

            "plan":
                plan,

            "paper_only":
                True,

            "real_orders":
                False,
        }

    # --------------------------------------------------------
    # FINAL SLOT RECHECK
    # --------------------------------------------------------

    if not trader.slot_available(
        CRYPTO_SLOT
    ):

        return {
            "status":
                "SKIPPED",

            "reason":
                (
                    "CRYPTO_MAIN became occupied "
                    "before execution"
                ),

            "paper_only":
                True,

            "real_orders":
                False,
        }

    # ========================================================
    # PAPER EXECUTION ONLY
    # ========================================================

    result = trader.open_trade(
        symbol=symbol,
        signal=signal,
        entry_price=entry_price,
        quantity=quantity,
        take_profit=take_profit,
        stop_loss=stop_loss,
        slot=CRYPTO_SLOT,
    )

    if not isinstance(
        result,
        dict,
    ):

        return {
            "status":
                "ERROR",

            "reason":
                "PaperTrader returned invalid result",

            "plan":
                plan,

            "governor":
                governor,

            "paper_only":
                True,

            "real_orders":
                False,
        }

    return {
        "status":
            result.get(
                "status",
                "UNKNOWN",
            ),

        "slot":
            CRYPTO_SLOT,

        "symbol":
            symbol,

        "signal":
            signal,

        "entry_price":
            entry_price,

        "tp_pct":
            tp_pct,

        "sl_pct":
            sl_pct,

        "test_mode":
            TEST_MODE,

        "plan":
            plan,

        "governor":
            governor,

        "portfolio_risk_approved":
            True,

        "result":
            result,

        "paper_trade":
            True,

        "paper_only":
            True,

        "real_orders":
            False,
    }


# ============================================================
# MONITOR OPEN CRYPTO POSITION
# ============================================================

def monitor_open_position(
    trader,
) -> Dict:

    position = trader.get_position(
        CRYPTO_SLOT
    )

    if not position:

        return {
            "status":
                "NO POSITION",

            "slot":
                CRYPTO_SLOT,

            "position":
                None,

            "paper_only":
                True,

            "real_orders":
                False,
        }

    symbol = _normalize_symbol(
        position.get(
            "symbol"
        )
    )

    current_price = get_current_price(
        symbol
    )

    if current_price is None:

        return {
            "status":
                "WAITING FOR PRICE",

            "slot":
                CRYPTO_SLOT,

            "symbol":
                symbol,

            "position":
                position,

            "paper_only":
                True,

            "real_orders":
                False,
        }

    current_price = _safe_float(
        current_price,
        0.0,
    )

    if current_price <= 0:

        return {
            "status":
                "WAITING FOR PRICE",

            "slot":
                CRYPTO_SLOT,

            "symbol":
                symbol,

            "position":
                position,

            "paper_only":
                True,

            "real_orders":
                False,
        }

    # Explicit CRYPTO_MAIN protects Metals position.
    result = trader.update_price(
        current_price=current_price,
        slot=CRYPTO_SLOT,
    )

    latest_position = trader.get_position(
        CRYPTO_SLOT
    )

    if (
        result
        and result.get(
            "status"
        )
        == "CLOSED"
    ):

        return {
            "status":
                "CLOSED",

            "slot":
                CRYPTO_SLOT,

            "symbol":
                symbol,

            "current_price":
                current_price,

            "trade":
                result,

            "position":
                None,

            "paper_only":
                True,

            "real_orders":
                False,
        }

    return {
        "status":
            "OPEN",

        "slot":
            CRYPTO_SLOT,

        "symbol":
            symbol,

        "current_price":
            current_price,

        "position":
            latest_position,

        "result":
            result,

        "paper_only":
            True,

        "real_orders":
            False,
    }


# ============================================================
# MANUAL CRYPTO PAPER CLOSE
# ============================================================

def manual_close_position(
    trader,
) -> Dict:

    position = trader.get_position(
        CRYPTO_SLOT
    )

    if not position:

        return {
            "status":
                "SKIPPED",

            "reason":
                "No open Crypto paper position",

            "slot":
                CRYPTO_SLOT,

            "paper_only":
                True,

            "real_orders":
                False,
        }

    symbol = _normalize_symbol(
        position.get(
            "symbol"
        )
    )

    current_price = get_current_price(
        symbol
    )

    if current_price is None:

        return {
            "status":
                "FAILED",

            "reason":
                "Could not fetch current Crypto market price",

            "position":
                position,

            "paper_only":
                True,

            "real_orders":
                False,
        }

    result = trader.close_trade(
        exit_price=current_price,
        reason="MANUAL_TEST_CLOSE",
        slot=CRYPTO_SLOT,
    )

    return {
        "status":
            result.get(
                "status",
                "UNKNOWN",
            ),

        "slot":
            CRYPTO_SLOT,

        "symbol":
            symbol,

        "exit_price":
            current_price,

        "result":
            result,

        "paper_only":
            True,

        "real_orders":
            False,
    }


# ============================================================
# TRADE MANAGEMENT SNAPSHOT
# ============================================================

def trade_management_snapshot(
    trader,
) -> Dict:

    position = trader.get_position(
        CRYPTO_SLOT
    )

    return {
        "engine":
            "V4.1 Crypto Paper Execution",

        "slot":
            CRYPTO_SLOT,

        "test_mode":
            TEST_MODE,

        "risk_pct":
            RISK_PCT,

        "active_tp_pct":
            _active_tp_pct(),

        "active_sl_pct":
            _active_sl_pct(),

        "trailing_stop_enabled":
            TRAILING_STOP_ENABLED,

        "trailing_stop_pct":
            TRAILING_STOP_PCT,

        "break_even_enabled":
            BREAK_EVEN_ENABLED,

        "break_even_trigger_pct":
            BREAK_EVEN_TRIGGER_PCT,

        "portfolio_governor":
            True,

        "position":
            position,

        "has_position":
            position is not None,

        "paper_only":
            True,

        "real_orders":
            False,

        "real_execution_locked":
            True,
    }


# ============================================================
# ENGINE HEALTH
# ============================================================

def crypto_trade_engine_health(
    trader=None,
) -> Dict:

    result = {
        "ok":
            True,

        "engine":
            "V4.1 Crypto Paper Execution",

        "slot":
            CRYPTO_SLOT,

        "portfolio_governor":
            True,

        "paper_only":
            True,

        "real_orders":
            False,

        "real_execution_locked":
            True,

        "test_mode":
            TEST_MODE,

        "risk_pct":
            RISK_PCT,

        "active_tp_pct":
            _active_tp_pct(),

        "active_sl_pct":
            _active_sl_pct(),
    }

    if trader is not None:

        try:

            result[
                "position"
            ] = trader.get_position(
                CRYPTO_SLOT
            )

            result[
                "has_position"
            ] = (
                result[
                    "position"
                ]
                is not None
            )

        except Exception as error:

            result[
                "ok"
            ] = False

            result[
                "reason"
            ] = str(
                error
            )

    return result

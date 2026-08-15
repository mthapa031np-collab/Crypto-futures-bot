"""
trade_engine.py

PRO AI QUANT TERMINAL V2
Paper trade execution and management layer.

Responsibilities:
- Open approved paper trades
- Monitor existing position
- Automatic TP / SL
- Manual paper close
- Testing TP / SL mode
- Centralized trade decisions
- Future-ready for trailing stop / break-even

IMPORTANT:
PAPER TRADING ONLY.
REAL ORDERS ARE DISABLED.
"""

from typing import Dict, Optional

from market_data import get_candles, get_ticker
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

        return float(
            value
        )

    except (
        TypeError,
        ValueError,
    ):

        return default


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

    symbol = str(
        symbol
    ).upper().strip()

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

    except Exception:

        pass

    # Fallback to candles
    try:

        candles = get_candles(
            exchange="PUBLIC",
            symbol=symbol,
            timeframe_minutes=(
                TIMEFRAME_MINUTES
            ),
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

    except Exception:

        return None


# ============================================================
# POSITION STATUS
# ============================================================

def get_position_status(
    trader,
) -> Dict:

    position = trader.get_position()

    if not position:

        return {
            "has_position": False,
            "position": None,
        }

    return {
        "has_position": True,
        "position": position,
    }


# ============================================================
# OPEN APPROVED SETUP
# ============================================================

def open_approved_trade(
    trader,
    setup: Dict,
) -> Dict:

    if not setup:

        return {
            "status": "SKIPPED",
            "reason": "Missing setup",
        }

    existing = trader.get_position()

    if existing:

        return {
            "status": "SKIPPED",
            "reason": "Position already open",
            "position": existing,
        }

    symbol = str(
        setup.get(
            "symbol",
            "",
        )
    ).upper().strip()

    signal = str(
        setup.get(
            "signal",
            "NO TRADE",
        )
    ).upper().strip()

    if signal not in (
        "BUY",
        "SELL",
    ):

        return {
            "status": "SKIPPED",
            "reason": "Invalid signal",
        }

    entry_price = _safe_float(
        setup.get(
            "price"
        ),
        0.0,
    )

    if entry_price <= 0:

        entry_price = (
            get_current_price(
                symbol
            )
            or 0.0
        )

    if entry_price <= 0:

        return {
            "status": "SKIPPED",
            "reason": (
                "Could not determine "
                "entry price"
            ),
        }

    balance = trader.get_balance()

    tp_pct = _active_tp_pct()
    sl_pct = _active_sl_pct()

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
            "status": "REJECTED",
            "reason": (
                "Risk manager rejected plan"
            ),
            "plan": plan,
        }

    result = trader.open_trade(
        symbol=symbol,
        signal=signal,
        entry_price=entry_price,
        quantity=plan[
            "quantity"
        ],
        take_profit=plan[
            "take_profit"
        ],
        stop_loss=plan[
            "stop_loss"
        ],
    )

    return {
        "status": result.get(
            "status",
            "UNKNOWN",
        ),

        "symbol": symbol,

        "signal": signal,

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

        "result":
            result,
    }


# ============================================================
# MONITOR OPEN POSITION
# ============================================================

def monitor_open_position(
    trader,
) -> Dict:

    position = trader.get_position()

    if not position:

        return {
            "status": "NO POSITION",
            "position": None,
        }

    symbol = position.get(
        "symbol"
    )

    current_price = (
        get_current_price(
            symbol
        )
    )

    if current_price is None:

        return {
            "status": "WAITING FOR PRICE",
            "position": position,
        }

    result = trader.update_price(
        current_price
    )

    latest_position = (
        trader.get_position()
    )

    if (
        result
        and result.get(
            "status"
        )
        == "CLOSED"
    ):

        return {
            "status": "CLOSED",
            "symbol": symbol,
            "current_price":
                current_price,
            "trade":
                result,
            "position": None,
        }

    return {
        "status": "OPEN",
        "symbol": symbol,
        "current_price":
            current_price,
        "position":
            latest_position,
        "result":
            result,
    }


# ============================================================
# MANUAL PAPER CLOSE
# ============================================================

def manual_close_position(
    trader,
) -> Dict:

    position = trader.get_position()

    if not position:

        return {
            "status": "SKIPPED",
            "reason": (
                "No open paper position"
            ),
        }

    symbol = position.get(
        "symbol"
    )

    current_price = (
        get_current_price(
            symbol
        )
    )

    if current_price is None:

        return {
            "status": "FAILED",
            "reason": (
                "Could not fetch "
                "current market price"
            ),
            "position": position,
        }

    result = trader.close_trade(
        exit_price=current_price,
        reason="MANUAL_TEST_CLOSE",
    )

    return {
        "status": result.get(
            "status",
            "UNKNOWN",
        ),

        "symbol": symbol,

        "exit_price":
            current_price,

        "result":
            result,
    }


# ============================================================
# TRADE MANAGEMENT SNAPSHOT
# ============================================================

def trade_management_snapshot(
    trader,
) -> Dict:

    position = trader.get_position()

    return {
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

        "position":
            position,

        "has_position":
            position is not None,
    }

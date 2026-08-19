"""
trade_engine.py

PRO AI QUANT TERMINAL V5
CRYPTO INTRADAY PAPER EXECUTION ENGINE

Purpose
-------
Single orchestration layer for approved CRYPTO paper entries.

Authoritative execution chain
-----------------------------
Scanner
    ↓
V5 Strategy Engine
    ↓
V5 Risk Manager
    ↓
V5 Portfolio Risk Governor
    ↓
PaperTrader
    ↓
V5 Trade Lifecycle Engine

Responsibilities
----------------
- CRYPTO_MAIN entry orchestration
- Reconfirm V5 strategy before execution
- Use strategy-generated SL / TP
- Shift strategy risk geometry to live entry price
- Reject stale / drifted entries
- Enforce confidence and quality gates
- Enforce execution-cost gate
- Risk-based position sizing
- Portfolio Governor final approval
- Preserve independent METALS_MAIN slot
- Current-price access
- Read-only position monitoring
- Manual PAPER close
- PAPER ONLY
- REAL ORDERS HARD DISABLED

IMPORTANT
---------
This module does NOT manage an open trade's trailing stop,
break-even, stale exit or maximum holding time.

Those responsibilities belong exclusively to:

    trade_lifecycle_engine.py

This prevents duplicate trade-management authorities.
"""

from __future__ import annotations

import inspect
import math
import os
from typing import Any, Dict, Optional

from market_data import (
    get_candles,
    get_ticker,
)

from paper_trader import (
    CRYPTO_SLOT,
)

from portfolio_risk_governor import (
    authorize_trade,
)

from risk_manager import (
    calculate_trade_plan,
    calculate_trade_plan_from_prices,
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
)

from strategy_engine import (
    confirm_scanner_setup,
)


# ============================================================
# VERSION
# ============================================================

ENGINE_VERSION = "V5 Crypto Intraday Paper Execution"


# ============================================================
# HARD SAFETY
# ============================================================

PAPER_ONLY = True
REAL_CRYPTO_ORDERS_ENABLED = False

if REAL_CRYPTO_ORDERS_ENABLED:

    raise RuntimeError(
        "REAL_CRYPTO_ORDERS_ENABLED must remain False."
    )


# ============================================================
# ENV HELPERS
# ============================================================

def _env_float(
    name: str,
    default: float,
    minimum: Optional[float] = None,
    maximum: Optional[float] = None,
) -> float:

    raw = os.environ.get(
        name,
        str(default),
    )

    try:

        value = float(
            raw
        )

    except (
        TypeError,
        ValueError,
    ):

        value = float(
            default
        )

    if not math.isfinite(
        value
    ):

        value = float(
            default
        )

    if minimum is not None:

        value = max(
            minimum,
            value,
        )

    if maximum is not None:

        value = min(
            maximum,
            value,
        )

    return value


def _env_bool(
    name: str,
    default: bool,
) -> bool:

    raw = os.environ.get(
        name,
        "true"
        if default
        else "false",
    )

    return (
        raw.strip()
        .lower()
        in {
            "1",
            "true",
            "yes",
            "on",
        }
    )


# ============================================================
# V5 EXECUTION POLICY
# ============================================================

MIN_EXECUTION_CONFIDENCE = _env_float(
    "CRYPTO_EXECUTION_MIN_CONFIDENCE",
    68.0,
    minimum=50.0,
    maximum=98.0,
)


# Maximum acceptable movement between the strategy's analysed
# price and the actual execution price.
MAX_ENTRY_DRIFT_PCT = _env_float(
    "CRYPTO_MAX_ENTRY_DRIFT_PCT",
    0.35,
    minimum=0.05,
    maximum=3.0,
)


# Entry may also move only this fraction of the initial
# strategy stop distance before we reject it as stale.
MAX_ENTRY_DRIFT_STOP_FRACTION = _env_float(
    "CRYPTO_MAX_ENTRY_DRIFT_STOP_FRACTION",
    0.35,
    minimum=0.05,
    maximum=1.0,
)


# Strategy risk geometry is shifted to current live price
# rather than blindly executing old absolute prices.
SHIFT_STRATEGY_LEVELS_TO_LIVE_ENTRY = _env_bool(
    "CRYPTO_SHIFT_LEVELS_TO_LIVE_ENTRY",
    True,
)


# Fail closed by default.
# Legacy fixed-percent TP/SL only exists for compatibility.
ALLOW_LEGACY_PERCENT_FALLBACK = _env_bool(
    "CRYPTO_ALLOW_LEGACY_PERCENT_FALLBACK",
    False,
)


# B-grade or better from V5 Strategy Engine.
ALLOWED_STRATEGY_QUALITIES = {
    "A",
    "B",
}


# ============================================================
# HELPERS
# ============================================================

def _safe_float(
    value,
    default=0.0,
) -> float:

    try:

        if value is None:

            return default

        number = float(
            value
        )

        if not math.isfinite(
            number
        ):

            return default

        return number

    except (
        TypeError,
        ValueError,
        OverflowError,
    ):

        return default


def _normalize_symbol(
    symbol,
) -> str:

    return (
        str(
            symbol
            or ""
        )
        .upper()
        .replace("/", "")
        .replace("-", "")
        .replace(" ", "")
        .strip()
    )


def _normalize_signal(
    signal,
) -> str:

    value = (
        str(
            signal
            or ""
        )
        .upper()
        .strip()
    )

    aliases = {
        "LONG":
            "BUY",

        "SHORT":
            "SELL",
    }

    value = aliases.get(
        value,
        value,
    )

    if value not in (
        "BUY",
        "SELL",
    ):

        return "NO TRADE"

    return value


def _signal_to_side(
    signal: str,
) -> str:

    if signal == "BUY":

        return "LONG"

    if signal == "SELL":

        return "SHORT"

    return ""


def _pct_difference(
    first: float,
    second: float,
) -> float:

    first = _safe_float(
        first
    )

    second = _safe_float(
        second
    )

    if first <= 0:

        return 0.0

    return (
        abs(
            second
            - first
        )
        / first
        * 100.0
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
    # PRIMARY LIVE PUBLIC TICKER
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
                )
            )

            if price > 0:

                return price

    except Exception as error:

        print(
            "[V5 CRYPTO PRICE TICKER ERROR] "
            f"{symbol}: {error}",
            flush=True,
        )

    # --------------------------------------------------------
    # FALLBACK PUBLIC CANDLE
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
            or len(
                candles
            ) == 0
        ):

            return None

        price = _safe_float(
            candles[
                "close"
            ].iloc[
                -1
            ]
        )

        if price <= 0:

            return None

        return price

    except Exception as error:

        print(
            "[V5 CRYPTO PRICE CANDLE ERROR] "
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

    try:

        position = trader.get_position(
            CRYPTO_SLOT
        )

    except Exception as error:

        return {
            "has_position":
                False,

            "slot":
                CRYPTO_SLOT,

            "position":
                None,

            "status":
                "ERROR",

            "reason":
                str(
                    error
                ),

            "paper_only":
                True,

            "real_orders":
                False,
        }

    return {
        "has_position":
            position
            is not None,

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
# BASIC SCANNER SETUP VALIDATION
# ============================================================

def _validate_scanner_setup(
    setup: Dict,
) -> Dict:

    if not isinstance(
        setup,
        dict,
    ):

        return {
            "valid":
                False,

            "reason":
                "Missing scanner setup",
        }

    symbol = _normalize_symbol(
        setup.get(
            "symbol"
        )
    )

    signal = _normalize_signal(
        setup.get(
            "signal"
        )
    )

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
                "Scanner has no directional signal",
        }

    if (
        "approved"
        in setup
        and setup.get(
            "approved"
        )
        is False
    ):

        return {
            "valid":
                False,

            "reason":
                "Scanner explicitly rejected setup",
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
# V5 STRATEGY RECONFIRMATION
# ============================================================

def _resolve_strategy_confirmation(
    setup: Dict,
) -> Dict:

    """
    Prefer an already-attached V5 strategy confirmation.

    If app/scanner does not attach it, recompute exactly once
    here before paper execution.

    This keeps trade_engine authoritative at execution time.
    """

    attached_candidates = (
        setup.get(
            "confirmation"
        ),
        setup.get(
            "strategy_confirmation"
        ),
    )

    for attached in attached_candidates:

        if (
            isinstance(
                attached,
                dict,
            )
            and
            "approved"
            in attached
        ):

            return attached

    # --------------------------------------------------------
    # Reconfirm immediately before execution.
    # --------------------------------------------------------

    try:

        return confirm_scanner_setup(
            setup
        )

    except Exception as error:

        return {
            "approved":
                False,

            "reason":
                (
                    "V5 strategy confirmation failed: "
                    f"{error}"
                ),
        }


# ============================================================
# STRATEGY QUALITY GATE
# ============================================================

def _validate_strategy_confirmation(
    confirmation: Dict,
    scanner_signal: str,
) -> Dict:

    if not isinstance(
        confirmation,
        dict,
    ):

        return {
            "valid":
                False,

            "reason":
                "Missing V5 strategy confirmation",
        }

    if not confirmation.get(
        "approved",
        False,
    ):

        return {
            "valid":
                False,

            "reason":
                confirmation.get(
                    "reason",
                    "V5 strategy rejected setup",
                ),
        }

    strategy_signal = (
        _normalize_signal(
            confirmation.get(
                "strategy_signal",
                confirmation.get(
                    "signal"
                ),
            )
        )
    )

    if (
        strategy_signal
        != scanner_signal
    ):

        return {
            "valid":
                False,

            "reason":
                (
                    "Scanner and V5 Strategy "
                    "directions disagree"
                ),
        }

    confidence = _safe_float(
        confirmation.get(
            "confidence"
        )
    )

    if (
        confidence
        < MIN_EXECUTION_CONFIDENCE
    ):

        return {
            "valid":
                False,

            "reason":
                (
                    "V5 Strategy confidence below "
                    f"{MIN_EXECUTION_CONFIDENCE:.1f}%"
                ),

            "confidence":
                confidence,
        }

    quality = (
        str(
            confirmation.get(
                "quality",
                ""
            )
        )
        .upper()
        .strip()
    )

    if (
        quality
        and quality
        not in ALLOWED_STRATEGY_QUALITIES
    ):

        return {
            "valid":
                False,

            "reason":
                (
                    f"Strategy quality {quality} "
                    "is not executable"
                ),

            "quality":
                quality,
        }

    cost_filter = confirmation.get(
        "cost_filter_passed"
    )

    if cost_filter is False:

        return {
            "valid":
                False,

            "reason":
                "Execution-cost filter rejected trade",
        }

    return {
        "valid":
            True,

        "strategy_signal":
            strategy_signal,

        "confidence":
            confidence,

        "quality":
            quality
            or "B",
    }


# ============================================================
# EXTRACT STRATEGY PLAN
# ============================================================

def _extract_strategy_prices(
    confirmation: Dict,
) -> Dict:

    strategy = confirmation.get(
        "strategy"
    )

    if not isinstance(
        strategy,
        dict,
    ):

        strategy = {}

    entry_price = _safe_float(
        confirmation.get(
            "entry_price",
            strategy.get(
                "entry_price"
            ),
        )
    )

    stop_loss = _safe_float(
        confirmation.get(
            "suggested_stop_loss",
            strategy.get(
                "suggested_stop_loss"
            ),
        )
    )

    take_profit = _safe_float(
        confirmation.get(
            "suggested_take_profit",
            strategy.get(
                "suggested_take_profit"
            ),
        )
    )

    reward_risk = _safe_float(
        confirmation.get(
            "suggested_reward_risk",
            strategy.get(
                "suggested_reward_risk"
            ),
        )
    )

    target_hold_hours = _safe_float(
        confirmation.get(
            "target_hold_hours",
            strategy.get(
                "target_hold_hours",
                3.0,
            ),
        ),
        3.0,
    )

    return {
        "entry_price":
            entry_price,

        "stop_loss":
            stop_loss,

        "take_profit":
            take_profit,

        "reward_risk":
            reward_risk,

        "target_hold_hours":
            target_hold_hours,
    }


# ============================================================
# LIVE ENTRY / STALE SIGNAL CONTROL
# ============================================================

def _build_live_execution_levels(
    *,
    signal: str,
    strategy_entry: float,
    strategy_stop: float,
    strategy_target: float,
    live_entry: float,
) -> Dict:

    if (
        strategy_entry <= 0
        or strategy_stop <= 0
        or strategy_target <= 0
        or live_entry <= 0
    ):

        return {
            "valid":
                False,

            "reason":
                "Invalid strategy/live execution prices",
        }

    # --------------------------------------------------------
    # VALID ORIGINAL STRATEGY GEOMETRY
    # --------------------------------------------------------

    if signal == "BUY":

        original_structure_valid = (
            strategy_stop
            < strategy_entry
            < strategy_target
        )

    else:

        original_structure_valid = (
            strategy_target
            < strategy_entry
            < strategy_stop
        )

    if not original_structure_valid:

        return {
            "valid":
                False,

            "reason":
                "V5 strategy produced invalid SL/TP geometry",
        }

    stop_distance = abs(
        strategy_entry
        - strategy_stop
    )

    target_distance = abs(
        strategy_target
        - strategy_entry
    )

    if (
        stop_distance <= 0
        or target_distance <= 0
    ):

        return {
            "valid":
                False,

            "reason":
                "Invalid strategy risk distance",
        }

    # --------------------------------------------------------
    # STALE / ENTRY DRIFT FILTER
    # --------------------------------------------------------

    drift_amount = abs(
        live_entry
        - strategy_entry
    )

    drift_pct = _pct_difference(
        strategy_entry,
        live_entry,
    )

    stop_fraction = (
        drift_amount
        / stop_distance
    )

    if (
        drift_pct
        > MAX_ENTRY_DRIFT_PCT
    ):

        return {
            "valid":
                False,

            "reason":
                (
                    "Entry moved too far after signal "
                    f"({drift_pct:.3f}% drift)"
                ),

            "drift_pct":
                drift_pct,

            "stop_fraction":
                stop_fraction,
        }

    if (
        stop_fraction
        > MAX_ENTRY_DRIFT_STOP_FRACTION
    ):

        return {
            "valid":
                False,

            "reason":
                (
                    "Entry drift consumed too much "
                    "of initial stop distance"
                ),

            "drift_pct":
                drift_pct,

            "stop_fraction":
                stop_fraction,
        }

    # --------------------------------------------------------
    # SHIFT RISK GEOMETRY TO ACTUAL ENTRY
    # --------------------------------------------------------

    if SHIFT_STRATEGY_LEVELS_TO_LIVE_ENTRY:

        if signal == "BUY":

            execution_stop = (
                live_entry
                - stop_distance
            )

            execution_target = (
                live_entry
                + target_distance
            )

        else:

            execution_stop = (
                live_entry
                + stop_distance
            )

            execution_target = (
                live_entry
                - target_distance
            )

    else:

        execution_stop = (
            strategy_stop
        )

        execution_target = (
            strategy_target
        )

    # --------------------------------------------------------
    # FINAL STRUCTURE
    # --------------------------------------------------------

    if signal == "BUY":

        final_structure_valid = (
            execution_stop
            < live_entry
            < execution_target
        )

    else:

        final_structure_valid = (
            execution_target
            < live_entry
            < execution_stop
        )

    if not final_structure_valid:

        return {
            "valid":
                False,

            "reason":
                "Live execution geometry is invalid",
        }

    reward_risk = (
        abs(
            execution_target
            - live_entry
        )
        /
        abs(
            live_entry
            - execution_stop
        )
    )

    return {
        "valid":
            True,

        "entry_price":
            live_entry,

        "stop_loss":
            execution_stop,

        "take_profit":
            execution_target,

        "reward_risk":
            reward_risk,

        "strategy_entry":
            strategy_entry,

        "entry_drift_pct":
            drift_pct,

        "entry_drift_stop_fraction":
            stop_fraction,

        "levels_shifted":
            SHIFT_STRATEGY_LEVELS_TO_LIVE_ENTRY,
    }


# ============================================================
# LEGACY FALLBACK
# ============================================================

def _build_legacy_plan(
    *,
    balance: float,
    entry_price: float,
    signal: str,
) -> Dict:

    if not ALLOW_LEGACY_PERCENT_FALLBACK:

        return {
            "valid":
                False,

            "reason":
                (
                    "V5 strategy prices unavailable and "
                    "legacy fallback is disabled"
                ),
        }

    return calculate_trade_plan(
        balance=balance,
        entry_price=entry_price,
        signal=signal,
        risk_percent=RISK_PCT,
        stop_loss_percent=_safe_float(
            _active_sl_pct()
        ),
        take_profit_percent=_safe_float(
            _active_tp_pct()
        ),
    )


# ============================================================
# PAPERTRADER OPEN CAPABILITY
# ============================================================

def _paper_trader_open_capability(
    trader,
) -> Dict:

    method = getattr(
        trader,
        "open_trade",
        None,
    )

    if not callable(
        method
    ):

        return {
            "ok":
                False,

            "reason":
                "PaperTrader.open_trade unavailable",
        }

    try:

        signature = inspect.signature(
            method
        )

        parameters = list(
            signature.parameters.keys()
        )

    except Exception:

        parameters = []

    return {
        "ok":
            True,

        "parameters":
            parameters,
    }


# ============================================================
# OPEN APPROVED CRYPTO TRADE
# ============================================================

def open_approved_trade(
    trader,
    setup: Dict,
) -> Dict:

    # ========================================================
    # HARD REAL-ORDER LOCK
    # ========================================================

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

    # ========================================================
    # 1. BASIC SCANNER VALIDATION
    # ========================================================

    scanner = _validate_scanner_setup(
        setup
    )

    if not scanner.get(
        "valid",
        False,
    ):

        return {
            "status":
                "SKIPPED",

            "reason":
                scanner.get(
                    "reason",
                    "Invalid scanner setup",
                ),

            "paper_only":
                True,

            "real_orders":
                False,
        }

    symbol = scanner[
        "symbol"
    ]

    signal = scanner[
        "signal"
    ]

    # ========================================================
    # 2. CRYPTO SLOT PROTECTION
    # ========================================================

    try:

        existing = trader.get_position(
            CRYPTO_SLOT
        )

    except Exception as error:

        return {
            "status":
                "ERROR",

            "reason":
                (
                    "Could not inspect CRYPTO_MAIN: "
                    f"{error}"
                ),

            "paper_only":
                True,

            "real_orders":
                False,
        }

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

    try:

        slot_available = trader.slot_available(
            CRYPTO_SLOT
        )

    except Exception:

        slot_available = False

    if not slot_available:

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

    # ========================================================
    # 3. V5 STRATEGY RECONFIRMATION
    # ========================================================

    confirmation = (
        _resolve_strategy_confirmation(
            setup
        )
    )

    quality_gate = (
        _validate_strategy_confirmation(
            confirmation,
            signal,
        )
    )

    if not quality_gate.get(
        "valid",
        False,
    ):

        return {
            "status":
                "STRATEGY_REJECTED",

            "reason":
                quality_gate.get(
                    "reason",
                    "V5 Strategy rejected setup",
                ),

            "confirmation":
                confirmation,

            "paper_only":
                True,

            "real_orders":
                False,
        }

    confidence = _safe_float(
        quality_gate.get(
            "confidence"
        )
    )

    strategy_quality = (
        quality_gate.get(
            "quality",
            "B",
        )
    )

    # ========================================================
    # 4. STRATEGY PRICE PLAN
    # ========================================================

    strategy_prices = (
        _extract_strategy_prices(
            confirmation
        )
    )

    strategy_entry = _safe_float(
        strategy_prices[
            "entry_price"
        ]
    )

    strategy_stop = _safe_float(
        strategy_prices[
            "stop_loss"
        ]
    )

    strategy_target = _safe_float(
        strategy_prices[
            "take_profit"
        ]
    )

    # ========================================================
    # 5. LIVE ENTRY PRICE
    # ========================================================

    live_entry = get_current_price(
        symbol
    )

    live_entry = _safe_float(
        live_entry
    )

    if live_entry <= 0:

        return {
            "status":
                "SKIPPED",

            "reason":
                "Could not determine live Crypto entry price",

            "confirmation":
                confirmation,

            "paper_only":
                True,

            "real_orders":
                False,
        }

    # ========================================================
    # 6. BALANCE
    # ========================================================

    try:

        balance = _safe_float(
            trader.get_balance()
        )

    except Exception:

        balance = 0.0

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

    # ========================================================
    # 7. LIVE EXECUTION GEOMETRY
    # ========================================================

    execution_levels = None

    if (
        strategy_entry > 0
        and strategy_stop > 0
        and strategy_target > 0
    ):

        execution_levels = (
            _build_live_execution_levels(
                signal=signal,
                strategy_entry=
                    strategy_entry,
                strategy_stop=
                    strategy_stop,
                strategy_target=
                    strategy_target,
                live_entry=
                    live_entry,
            )
        )

    if (
        execution_levels
        and execution_levels.get(
            "valid",
            False,
        )
    ):

        # ----------------------------------------------------
        # V5 EXPLICIT-PRICE RISK PLAN
        # ----------------------------------------------------

        plan = (
            calculate_trade_plan_from_prices(
                balance=balance,
                entry_price=
                    execution_levels[
                        "entry_price"
                    ],
                signal=signal,
                stop_loss_price=
                    execution_levels[
                        "stop_loss"
                    ],
                take_profit_price=
                    execution_levels[
                        "take_profit"
                    ],
                risk_percent=
                    RISK_PCT,
            )
        )

        plan_source = (
            "V5_STRATEGY_EXPLICIT_PRICES"
        )

    else:

        if (
            execution_levels
            and not execution_levels.get(
                "valid",
                False,
            )
            and strategy_entry > 0
        ):

            # Entry drift or malformed V5 strategy geometry
            # should NOT silently fall back to legacy TP/SL.
            return {
                "status":
                    "STALE_ENTRY",

                "reason":
                    execution_levels.get(
                        "reason",
                        "V5 strategy entry is stale",
                    ),

                "execution_levels":
                    execution_levels,

                "confirmation":
                    confirmation,

                "paper_only":
                    True,

                "real_orders":
                    False,
            }

        plan = _build_legacy_plan(
            balance=balance,
            entry_price=live_entry,
            signal=signal,
        )

        plan_source = (
            "LEGACY_PERCENT_FALLBACK"
        )

    # ========================================================
    # 8. LOCAL RISK PLAN VALIDATION
    # ========================================================

    if not validate_trade_plan(
        plan
    ):

        return {
            "status":
                "RISK_PLAN_REJECTED",

            "reason":
                plan.get(
                    "reason",
                    "V5 Risk Manager rejected plan",
                ),

            "plan":
                plan,

            "plan_source":
                plan_source,

            "confirmation":
                confirmation,

            "paper_only":
                True,

            "real_orders":
                False,
        }

    quantity = _safe_float(
        plan.get(
            "quantity"
        )
    )

    take_profit = _safe_float(
        plan.get(
            "take_profit"
        )
    )

    stop_loss = _safe_float(
        plan.get(
            "stop_loss"
        )
    )

    entry_price = _safe_float(
        plan.get(
            "entry_price"
        )
    )

    reward_risk = _safe_float(
        plan.get(
            "reward_risk_ratio"
        )
    )

    if (
        quantity <= 0
        or take_profit <= 0
        or stop_loss <= 0
        or entry_price <= 0
    ):

        return {
            "status":
                "RISK_PLAN_REJECTED",

            "reason":
                "Risk plan contains invalid values",

            "plan":
                plan,

            "paper_only":
                True,

            "real_orders":
                False,
        }

    # ========================================================
    # 9. PORTFOLIO RISK GOVERNOR
    # ========================================================

    governor = authorize_trade(
        trader,
        asset_class="CRYPTO",
        symbol=symbol,
        entry_price=entry_price,
        stop_loss=stop_loss,
        quantity=quantity,
        risk_pct=RISK_PCT,
        side=_signal_to_side(
            signal
        ),
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
                    (
                        "Portfolio Risk Governor "
                        "blocked Crypto trade"
                    ),
                ),

            "governor":
                governor,

            "plan":
                plan,

            "confirmation":
                confirmation,

            "paper_only":
                True,

            "real_orders":
                False,
        }

    # ========================================================
    # 10. FINAL SLOT RECHECK
    # ========================================================

    try:

        final_slot_available = (
            trader.slot_available(
                CRYPTO_SLOT
            )
        )

    except Exception:

        final_slot_available = False

    if not final_slot_available:

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
    # 11. PAPERTRADER CAPABILITY CHECK
    # ========================================================

    capability = (
        _paper_trader_open_capability(
            trader
        )
    )

    if not capability.get(
        "ok",
        False,
    ):

        return {
            "status":
                "ERROR",

            "reason":
                capability.get(
                    "reason",
                    "PaperTrader cannot open trade",
                ),

            "paper_only":
                True,

            "real_orders":
                False,
        }

    # ========================================================
    # 12. PAPER EXECUTION
    # ========================================================

    try:

        result = trader.open_trade(
            symbol=symbol,
            signal=signal,
            entry_price=entry_price,
            quantity=quantity,
            take_profit=take_profit,
            stop_loss=stop_loss,
            slot=CRYPTO_SLOT,
        )

    except Exception as error:

        return {
            "status":
                "ERROR",

            "reason":
                (
                    "PaperTrader open_trade failed: "
                    f"{error}"
                ),

            "plan":
                plan,

            "governor":
                governor,

            "confirmation":
                confirmation,

            "paper_only":
                True,

            "real_orders":
                False,
        }

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

            "confirmation":
                confirmation,

            "paper_only":
                True,

            "real_orders":
                False,
        }

    # ========================================================
    # SUCCESS
    # ========================================================

    return {
        "status":
            result.get(
                "status",
                "UNKNOWN",
            ),

        "engine":
            ENGINE_VERSION,

        "slot":
            CRYPTO_SLOT,

        "symbol":
            symbol,

        "signal":
            signal,

        "entry_price":
            entry_price,

        "take_profit":
            take_profit,

        "stop_loss":
            stop_loss,

        "quantity":
            quantity,

        "reward_risk_ratio":
            reward_risk,

        "confidence":
            confidence,

        "quality":
            strategy_quality,

        "target_hold_hours":
            strategy_prices.get(
                "target_hold_hours",
                3.0,
            ),

        "plan_source":
            plan_source,

        "entry_drift_pct":
            (
                execution_levels.get(
                    "entry_drift_pct"
                )
                if execution_levels
                else None
            ),

        "strategy_confirmation":
            confirmation,

        "plan":
            plan,

        "governor":
            governor,

        "portfolio_risk_approved":
            True,

        "result":
            result,

        "lifecycle_authority":
            "trade_lifecycle_engine",

        "paper_trade":
            True,

        "paper_only":
            True,

        "real_orders":
            False,
    }


# ============================================================
# READ-ONLY OPEN POSITION MONITOR
# ============================================================

def monitor_open_position(
    trader,
) -> Dict:

    """
    IMPORTANT V5 CHANGE

    This function is intentionally READ-ONLY.

    TP / SL / break-even / trailing / stale exit /
    time exit are managed by trade_lifecycle_engine.py.

    This prevents app.py and lifecycle runtime from both
    attempting to close the same trade simultaneously.
    """

    try:

        position = trader.get_position(
            CRYPTO_SLOT
        )

    except Exception as error:

        return {
            "status":
                "ERROR",

            "reason":
                str(
                    error
                ),

            "slot":
                CRYPTO_SLOT,

            "paper_only":
                True,

            "real_orders":
                False,
        }

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

    current_price = _safe_float(
        current_price
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
            position,

        "management_authority":
            "trade_lifecycle_engine",

        "read_only_monitor":
            True,

        "paper_only":
            True,

        "real_orders":
            False,
    }


# ============================================================
# MANUAL PAPER CLOSE
# ============================================================

def manual_close_position(
    trader,
) -> Dict:

    try:

        position = trader.get_position(
            CRYPTO_SLOT
        )

    except Exception as error:

        return {
            "status":
                "FAILED",

            "reason":
                str(
                    error
                ),

            "paper_only":
                True,

            "real_orders":
                False,
        }

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

    current_price = _safe_float(
        current_price
    )

    if current_price <= 0:

        return {
            "status":
                "FAILED",

            "reason":
                "Could not fetch current Crypto price",

            "position":
                position,

            "paper_only":
                True,

            "real_orders":
                False,
        }

    try:

        result = trader.close_trade(
            exit_price=current_price,
            reason="MANUAL_TEST_CLOSE",
            slot=CRYPTO_SLOT,
        )

    except Exception as error:

        return {
            "status":
                "FAILED",

            "reason":
                str(
                    error
                ),

            "position":
                position,

            "paper_only":
                True,

            "real_orders":
                False,
        }

    if not isinstance(
        result,
        dict,
    ):

        return {
            "status":
                "UNKNOWN",

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
# MANAGEMENT SNAPSHOT
# ============================================================

def trade_management_snapshot(
    trader,
) -> Dict:

    try:

        position = trader.get_position(
            CRYPTO_SLOT
        )

    except Exception:

        position = None

    return {
        "engine":
            ENGINE_VERSION,

        "slot":
            CRYPTO_SLOT,

        "strategy_engine":
            "V5 Intraday Confluence",

        "risk_manager":
            "V5 Local Trade Risk Manager",

        "portfolio_governor":
            True,

        "lifecycle_authority":
            "trade_lifecycle_engine",

        "risk_pct":
            RISK_PCT,

        "execution_min_confidence":
            MIN_EXECUTION_CONFIDENCE,

        "allowed_qualities":
            sorted(
                ALLOWED_STRATEGY_QUALITIES
            ),

        "max_entry_drift_pct":
            MAX_ENTRY_DRIFT_PCT,

        "max_entry_drift_stop_fraction":
            MAX_ENTRY_DRIFT_STOP_FRACTION,

        "shift_strategy_levels_to_live_entry":
            SHIFT_STRATEGY_LEVELS_TO_LIVE_ENTRY,

        "legacy_percent_fallback":
            ALLOW_LEGACY_PERCENT_FALLBACK,

        "legacy_tp_pct":
            _active_tp_pct(),

        "legacy_sl_pct":
            _active_sl_pct(),

        "test_mode":
            TEST_MODE,

        "position":
            position,

        "has_position":
            position
            is not None,

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
            ENGINE_VERSION,

        "slot":
            CRYPTO_SLOT,

        "strategy_aware":
            True,

        "explicit_strategy_sl_tp":
            True,

        "live_entry_drift_filter":
            True,

        "risk_based_position_sizing":
            True,

        "portfolio_governor":
            True,

        "lifecycle_authority":
            "trade_lifecycle_engine",

        "duplicate_position_management":
            False,

        "execution_min_confidence":
            MIN_EXECUTION_CONFIDENCE,

        "legacy_percent_fallback":
            ALLOW_LEGACY_PERCENT_FALLBACK,

        "paper_only":
            True,

        "real_orders":
            False,

        "real_execution_locked":
            True,

        "test_mode":
            TEST_MODE,
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

            result[
                "paper_trader_capability"
            ] = (
                _paper_trader_open_capability(
                    trader
                )
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

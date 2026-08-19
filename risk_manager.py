"""
risk_manager.py

PRO AI QUANT TERMINAL V5
LOCAL TRADE PLAN + POSITION SIZING ENGINE

Purpose
-------
This module owns ONLY trade-level risk construction:

    - Position sizing
    - Explicit Entry / Stop / Target validation
    - Reward-to-risk validation
    - Backward-compatible percent-based trade planning

It DOES NOT own account-level portfolio authorization.

Account-level authority belongs to:

    portfolio_risk_governor.py

Architecture
------------
Strategy Engine
        ↓
Risk Manager
        ↓
Portfolio Risk Governor
        ↓
Trade Engine
        ↓
PaperTrader

V5 Design
---------
- Strategy-supplied SL / TP supported directly
- Risk-based position sizing
- Finite-number protection
- LONG / SHORT structural validation
- Reward:risk validation
- Backward-compatible calculate_trade_plan(...)
- Explicit calculate_trade_plan_from_prices(...)
- No duplicate account-level risk authority
- PAPER ONLY
"""

from __future__ import annotations

import math
import os
from typing import Dict, Optional

from settings import (
    RISK_PCT,
    MAX_OPEN_POSITIONS,
    MAX_PORTFOLIO_RISK_PCT,
)


# ============================================================
# VERSION
# ============================================================

ENGINE_VERSION = "V5 Local Trade Risk Manager"


# ============================================================
# HARD SAFETY
# ============================================================

PAPER_ONLY = True
REAL_EXECUTION_ENABLED = False


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


# ============================================================
# LOCAL TRADE LIMITS
# ============================================================

MIN_RISK_PCT = _env_float(
    "MIN_TRADE_RISK_PCT",
    0.05,
    minimum=0.01,
    maximum=5.0,
)

MAX_RISK_PCT = _env_float(
    "MAX_TRADE_RISK_PCT",
    5.0,
    minimum=0.10,
    maximum=20.0,
)

MIN_SL_PCT = _env_float(
    "MIN_STOP_DISTANCE_PCT",
    0.05,
    minimum=0.01,
    maximum=10.0,
)

MAX_SL_PCT = _env_float(
    "MAX_STOP_DISTANCE_PCT",
    10.0,
    minimum=0.10,
    maximum=50.0,
)

MIN_TP_PCT = _env_float(
    "MIN_TARGET_DISTANCE_PCT",
    0.05,
    minimum=0.01,
    maximum=10.0,
)

MAX_TP_PCT = _env_float(
    "MAX_TARGET_DISTANCE_PCT",
    25.0,
    minimum=0.10,
    maximum=100.0,
)

MIN_REWARD_RISK_RATIO = _env_float(
    "MIN_REWARD_RISK_RATIO",
    1.20,
    minimum=0.50,
    maximum=10.0,
)


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


def _safe_int(
    value,
    default=0,
) -> int:

    try:

        if value is None:
            return default

        return int(
            value
        )

    except (
        TypeError,
        ValueError,
    ):

        return default


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

    return aliases.get(
        value,
        value,
    )


def _pct_distance(
    entry: float,
    other: float,
) -> float:

    if entry <= 0:
        return 0.0

    return (
        abs(
            other
            - entry
        )
        / entry
        * 100
    )


# ============================================================
# POSITION SIZE
# ============================================================

def calculate_position_size(
    balance: float,
    entry_price: float,
    stop_loss_price: float,
    risk_percent: float,
) -> float:

    balance = _safe_float(
        balance
    )

    entry_price = _safe_float(
        entry_price
    )

    stop_loss_price = _safe_float(
        stop_loss_price
    )

    risk_percent = _safe_float(
        risk_percent,
        RISK_PCT,
    )

    if (
        balance <= 0
        or entry_price <= 0
        or stop_loss_price <= 0
    ):

        return 0.0

    if not (
        MIN_RISK_PCT
        <= risk_percent
        <= MAX_RISK_PCT
    ):

        return 0.0

    stop_distance = abs(
        entry_price
        - stop_loss_price
    )

    if stop_distance <= 0:

        return 0.0

    risk_amount = (
        balance
        * risk_percent
        / 100.0
    )

    quantity = (
        risk_amount
        / stop_distance
    )

    if (
        quantity <= 0
        or not math.isfinite(
            quantity
        )
    ):

        return 0.0

    return round(
        quantity,
        8,
    )


# ============================================================
# EXPLICIT PRICE-BASED PLAN
# ============================================================

def calculate_trade_plan_from_prices(
    *,
    balance: float,
    entry_price: float,
    signal: str,
    stop_loss_price: float,
    take_profit_price: float,
    risk_percent: float = RISK_PCT,
) -> Dict:

    """
    Preferred V5 path.

    Strategy supplies:
        entry
        stop loss
        take profit

    Risk Manager supplies:
        quantity
        risk amount
        reward:risk metrics
        validation
    """

    balance = _safe_float(
        balance
    )

    entry_price = _safe_float(
        entry_price
    )

    stop_loss = _safe_float(
        stop_loss_price
    )

    take_profit = _safe_float(
        take_profit_price
    )

    risk_percent = _safe_float(
        risk_percent,
        RISK_PCT,
    )

    signal = _normalize_signal(
        signal
    )

    if signal not in (
        "BUY",
        "SELL",
    ):

        return {
            "valid":
                False,

            "reason":
                "Invalid signal",

            "engine":
                ENGINE_VERSION,
        }

    if balance <= 0:

        return {
            "valid":
                False,

            "reason":
                "Balance must be positive",

            "engine":
                ENGINE_VERSION,
        }

    if (
        entry_price <= 0
        or stop_loss <= 0
        or take_profit <= 0
    ):

        return {
            "valid":
                False,

            "reason":
                "Entry, stop and target must be positive",

            "engine":
                ENGINE_VERSION,
        }

    if not (
        MIN_RISK_PCT
        <= risk_percent
        <= MAX_RISK_PCT
    ):

        return {
            "valid":
                False,

            "reason":
                (
                    f"Risk percent outside safe range "
                    f"{MIN_RISK_PCT:.2f}%–"
                    f"{MAX_RISK_PCT:.2f}%"
                ),

            "engine":
                ENGINE_VERSION,
        }

    # --------------------------------------------------------
    # STRUCTURE
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
            "valid":
                False,

            "reason":
                "Invalid stop/entry/target structure",

            "engine":
                ENGINE_VERSION,
        }

    # --------------------------------------------------------
    # DISTANCES
    # --------------------------------------------------------

    stop_distance = abs(
        entry_price
        - stop_loss
    )

    target_distance = abs(
        take_profit
        - entry_price
    )

    stop_loss_percent = (
        _pct_distance(
            entry_price,
            stop_loss,
        )
    )

    take_profit_percent = (
        _pct_distance(
            entry_price,
            take_profit,
        )
    )

    if (
        stop_loss_percent
        < MIN_SL_PCT
        or stop_loss_percent
        > MAX_SL_PCT
    ):

        return {
            "valid":
                False,

            "reason":
                (
                    "Stop distance outside "
                    "allowed range"
                ),

            "stop_loss_percent":
                stop_loss_percent,

            "engine":
                ENGINE_VERSION,
        }

    if (
        take_profit_percent
        < MIN_TP_PCT
        or take_profit_percent
        > MAX_TP_PCT
    ):

        return {
            "valid":
                False,

            "reason":
                (
                    "Target distance outside "
                    "allowed range"
                ),

            "take_profit_percent":
                take_profit_percent,

            "engine":
                ENGINE_VERSION,
        }

    # --------------------------------------------------------
    # REWARD / RISK
    # --------------------------------------------------------

    reward_risk_ratio = 0.0

    if stop_distance > 0:

        reward_risk_ratio = (
            target_distance
            / stop_distance
        )

    if (
        reward_risk_ratio
        < MIN_REWARD_RISK_RATIO
    ):

        return {
            "valid":
                False,

            "reason":
                (
                    "Reward:risk ratio below "
                    f"minimum {MIN_REWARD_RISK_RATIO:.2f}"
                ),

            "reward_risk_ratio":
                reward_risk_ratio,

            "engine":
                ENGINE_VERSION,
        }

    # --------------------------------------------------------
    # POSITION SIZE
    # --------------------------------------------------------

    quantity = (
        calculate_position_size(
            balance=balance,
            entry_price=entry_price,
            stop_loss_price=stop_loss,
            risk_percent=risk_percent,
        )
    )

    if quantity <= 0:

        return {
            "valid":
                False,

            "reason":
                "Position sizing failed",

            "engine":
                ENGINE_VERSION,
        }

    planned_risk_amount = (
        balance
        * risk_percent
        / 100.0
    )

    actual_risk_amount = (
        stop_distance
        * quantity
    )

    reward_amount = (
        target_distance
        * quantity
    )

    return {
        "valid":
            True,

        "engine":
            ENGINE_VERSION,

        "plan_type":
            "EXPLICIT_PRICES",

        "signal":
            signal,

        "balance":
            balance,

        "entry_price":
            entry_price,

        "quantity":
            quantity,

        "stop_loss":
            round(
                stop_loss,
                8,
            ),

        "take_profit":
            round(
                take_profit,
                8,
            ),

        "risk_percent":
            risk_percent,

        "planned_risk_amount":
            round(
                planned_risk_amount,
                8,
            ),

        "risk_amount":
            round(
                actual_risk_amount,
                8,
            ),

        "actual_risk_amount":
            round(
                actual_risk_amount,
                8,
            ),

        "reward_amount":
            round(
                reward_amount,
                8,
            ),

        "reward_risk_ratio":
            round(
                reward_risk_ratio,
                3,
            ),

        "stop_loss_percent":
            round(
                stop_loss_percent,
                4,
            ),

        "take_profit_percent":
            round(
                take_profit_percent,
                4,
            ),

        "paper_only":
            True,

        "real_execution":
            False,
    }


# ============================================================
# BACKWARD-COMPATIBLE PERCENT PLAN
# ============================================================

def calculate_trade_plan(
    balance,
    entry_price,
    signal,
    risk_percent=RISK_PCT,
    stop_loss_percent=1.0,
    take_profit_percent=2.0,
):

    """
    Legacy-compatible wrapper.

    Existing callers may continue supplying percentages.

    New V5 execution should prefer:
        calculate_trade_plan_from_prices(...)
    """

    balance = _safe_float(
        balance
    )

    entry_price = _safe_float(
        entry_price
    )

    risk_percent = _safe_float(
        risk_percent,
        RISK_PCT,
    )

    stop_loss_percent = _safe_float(
        stop_loss_percent,
        1.0,
    )

    take_profit_percent = _safe_float(
        take_profit_percent,
        2.0,
    )

    signal = _normalize_signal(
        signal
    )

    if signal not in (
        "BUY",
        "SELL",
    ):

        return {
            "valid":
                False,

            "reason":
                "Invalid signal",

            "engine":
                ENGINE_VERSION,
        }

    if entry_price <= 0:

        return {
            "valid":
                False,

            "reason":
                "Entry price must be positive",

            "engine":
                ENGINE_VERSION,
        }

    if signal == "BUY":

        stop_loss = (
            entry_price
            * (
                1
                - stop_loss_percent
                / 100.0
            )
        )

        take_profit = (
            entry_price
            * (
                1
                + take_profit_percent
                / 100.0
            )
        )

    else:

        stop_loss = (
            entry_price
            * (
                1
                + stop_loss_percent
                / 100.0
            )
        )

        take_profit = (
            entry_price
            * (
                1
                - take_profit_percent
                / 100.0
            )
        )

    result = (
        calculate_trade_plan_from_prices(
            balance=balance,
            entry_price=entry_price,
            signal=signal,
            stop_loss_price=stop_loss,
            take_profit_price=take_profit,
            risk_percent=risk_percent,
        )
    )

    if result.get(
        "valid",
        False,
    ):

        result[
            "plan_type"
        ] = "LEGACY_PERCENT"

    return result


# ============================================================
# PLAN VALIDATION
# ============================================================

def validate_trade_plan(
    plan: Optional[Dict],
) -> bool:

    if not isinstance(
        plan,
        dict,
    ):

        return False

    if not plan.get(
        "valid",
        False,
    ):

        return False

    signal = _normalize_signal(
        plan.get(
            "signal"
        )
    )

    if signal not in (
        "BUY",
        "SELL",
    ):

        return False

    entry = _safe_float(
        plan.get(
            "entry_price"
        )
    )

    stop_loss = _safe_float(
        plan.get(
            "stop_loss"
        )
    )

    take_profit = _safe_float(
        plan.get(
            "take_profit"
        )
    )

    quantity = _safe_float(
        plan.get(
            "quantity"
        )
    )

    reward_risk_ratio = (
        _safe_float(
            plan.get(
                "reward_risk_ratio"
            )
        )
    )

    if (
        entry <= 0
        or stop_loss <= 0
        or take_profit <= 0
        or quantity <= 0
    ):

        return False

    if (
        reward_risk_ratio
        < MIN_REWARD_RISK_RATIO
    ):

        return False

    if signal == "BUY":

        return (
            stop_loss
            < entry
            < take_profit
        )

    return (
        take_profit
        < entry
        < stop_loss
    )


# ============================================================
# LEGACY COMPATIBILITY HELPERS
# ============================================================

def can_open_new_position(
    open_positions_count: int,
) -> bool:

    """
    Compatibility only.

    Portfolio Risk Governor is the authoritative
    account-level position-limit engine.
    """

    count = _safe_int(
        open_positions_count
    )

    return (
        count
        < MAX_OPEN_POSITIONS
    )


def calculate_portfolio_risk_pct(
    balance: float,
    open_risk_amount: float,
) -> float:

    """
    Compatibility helper only.

    Account-level enforcement belongs to
    portfolio_risk_governor.py.
    """

    balance = _safe_float(
        balance
    )

    open_risk_amount = _safe_float(
        open_risk_amount
    )

    if balance <= 0:

        return 0.0

    return (
        open_risk_amount
        / balance
        * 100.0
    )


def portfolio_risk_allowed(
    balance: float,
    open_risk_amount: float,
    new_trade_risk_amount: float,
) -> bool:

    """
    Compatibility helper only.

    New execution code must rely on
    Portfolio Risk Governor for final authorization.
    """

    balance = _safe_float(
        balance
    )

    open_risk_amount = _safe_float(
        open_risk_amount
    )

    new_trade_risk_amount = _safe_float(
        new_trade_risk_amount
    )

    if balance <= 0:

        return False

    projected = (
        open_risk_amount
        + new_trade_risk_amount
    )

    risk_pct = (
        projected
        / balance
        * 100.0
    )

    return (
        risk_pct
        <= MAX_PORTFOLIO_RISK_PCT
    )


# ============================================================
# LOCAL RISK EVALUATION
# ============================================================

def evaluate_trade_risk(
    plan: Dict,
    balance: float,
    open_positions_count: int = 0,
    open_risk_amount: float = 0.0,
) -> Dict:

    """
    Backward-compatible local risk evaluation.

    IMPORTANT:
    This does NOT replace Portfolio Risk Governor.

    New execution chain:
        validate_trade_plan()
        ↓
        authorize_trade()
    """

    if not validate_trade_plan(
        plan
    ):

        return {
            "approved":
                False,

            "reason":
                "Trade plan validation failed",

            "engine":
                ENGINE_VERSION,
        }

    return {
        "approved":
            True,

        "reason":
            (
                "Local trade-plan validation passed. "
                "Portfolio Governor authorization still required."
            ),

        "reward_risk_ratio":
            plan.get(
                "reward_risk_ratio"
            ),

        "trade_risk_amount":
            plan.get(
                "actual_risk_amount",
                plan.get(
                    "risk_amount",
                    0.0,
                ),
            ),

        "portfolio_authority":
            "portfolio_risk_governor",

        "engine":
            ENGINE_VERSION,

        "paper_only":
            True,

        "real_execution":
            False,
    }


# ============================================================
# HEALTH
# ============================================================

def risk_manager_health() -> Dict:

    return {
        "ok":
            True,

        "engine":
            ENGINE_VERSION,

        "paper_only":
            True,

        "real_execution_locked":
            True,

        "role":
            "LOCAL_TRADE_PLAN_AND_POSITION_SIZING",

        "strategy_price_plan_supported":
            True,

        "legacy_percent_plan_supported":
            True,

        "finite_number_validation":
            True,

        "reward_risk_validation":
            True,

        "structural_stop_target_validation":
            True,

        "account_level_authority":
            "portfolio_risk_governor",

        "minimum_reward_risk_ratio":
            MIN_REWARD_RISK_RATIO,

        "risk_range":
            {
                "minimum_pct":
                    MIN_RISK_PCT,

                "maximum_pct":
                    MAX_RISK_PCT,
            },
    }

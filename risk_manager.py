"""
risk_manager.py

PRO AI QUANT TERMINAL V2
Central risk management layer.

Responsibilities:
- Position sizing
- Stop-loss / take-profit validation
- Reward-to-risk checks
- Portfolio risk limits
- Open-position limits
- Safe trade-plan validation

Compatible with existing calls:
    calculate_trade_plan(...)
    validate_trade_plan(...)
"""

from typing import Dict, Optional

from settings import (
    RISK_PCT,
    MAX_OPEN_POSITIONS,
    MAX_PORTFOLIO_RISK_PCT,
)


# ============================================================
# CONSTANTS
# ============================================================

MIN_RISK_PCT = 0.1
MAX_RISK_PCT = 5.0

MIN_SL_PCT = 0.1
MAX_SL_PCT = 10.0

MIN_TP_PCT = 0.1
MAX_TP_PCT = 25.0

MIN_REWARD_RISK_RATIO = 1.0


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

        return float(value)

    except (
        TypeError,
        ValueError,
    ):

        return default


def _safe_int(
    value,
    default=0,
):

    try:

        if value is None:
            return default

        return int(value)

    except (
        TypeError,
        ValueError,
    ):

        return default


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

    if balance <= 0:
        return 0.0

    if entry_price <= 0:
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
        / 100
    )

    quantity = (
        risk_amount
        / stop_distance
    )

    if quantity <= 0:
        return 0.0

    return round(
        quantity,
        8,
    )


# ============================================================
# TRADE PLAN
# ============================================================

def calculate_trade_plan(
    balance,
    entry_price,
    signal,
    risk_percent=RISK_PCT,
    stop_loss_percent=1.0,
    take_profit_percent=2.0,
):

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

    signal = str(
        signal or ""
    ).upper().strip()

    if signal not in (
        "BUY",
        "SELL",
    ):

        return {
            "valid": False,
            "reason": "Invalid signal",
        }

    if balance <= 0:

        return {
            "valid": False,
            "reason": (
                "Balance must be positive"
            ),
        }

    if entry_price <= 0:

        return {
            "valid": False,
            "reason": (
                "Entry price must be positive"
            ),
        }

    if not (
        MIN_RISK_PCT
        <= risk_percent
        <= MAX_RISK_PCT
    ):

        return {
            "valid": False,
            "reason": (
                f"Risk percent outside "
                f"safe range "
                f"{MIN_RISK_PCT}%–"
                f"{MAX_RISK_PCT}%"
            ),
        }

    if not (
        MIN_SL_PCT
        <= stop_loss_percent
        <= MAX_SL_PCT
    ):

        return {
            "valid": False,
            "reason": (
                "Stop loss percent "
                "outside allowed range"
            ),
        }

    if not (
        MIN_TP_PCT
        <= take_profit_percent
        <= MAX_TP_PCT
    ):

        return {
            "valid": False,
            "reason": (
                "Take profit percent "
                "outside allowed range"
            ),
        }

    if signal == "BUY":

        stop_loss = (
            entry_price
            * (
                1
                - stop_loss_percent
                / 100
            )
        )

        take_profit = (
            entry_price
            * (
                1
                + take_profit_percent
                / 100
            )
        )

    else:

        stop_loss = (
            entry_price
            * (
                1
                + stop_loss_percent
                / 100
            )
        )

        take_profit = (
            entry_price
            * (
                1
                - take_profit_percent
                / 100
            )
        )

    quantity = (
        calculate_position_size(
            balance=balance,
            entry_price=entry_price,
            stop_loss_price=stop_loss,
            risk_percent=risk_percent,
        )
    )

    risk_amount = (
        balance
        * risk_percent
        / 100
    )

    reward_amount = (
        abs(
            take_profit
            - entry_price
        )
        * quantity
    )

    actual_risk_amount = (
        abs(
            entry_price
            - stop_loss
        )
        * quantity
    )

    reward_risk_ratio = 0.0

    if actual_risk_amount > 0:

        reward_risk_ratio = (
            reward_amount
            / actual_risk_amount
        )

    return {
        "valid": True,

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

        "risk_amount":
            round(
                risk_amount,
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
            stop_loss_percent,

        "take_profit_percent":
            take_profit_percent,
    }


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

    signal = plan.get(
        "signal"
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

    if entry <= 0:
        return False

    if stop_loss <= 0:
        return False

    if take_profit <= 0:
        return False

    if quantity <= 0:
        return False

    if (
        reward_risk_ratio
        < MIN_REWARD_RISK_RATIO
    ):
        return False

    if signal == "BUY":

        if not (
            stop_loss
            < entry
            < take_profit
        ):
            return False

    elif signal == "SELL":

        if not (
            take_profit
            < entry
            < stop_loss
        ):
            return False

    return True


# ============================================================
# OPEN POSITION LIMIT
# ============================================================

def can_open_new_position(
    open_positions_count: int,
) -> bool:

    count = _safe_int(
        open_positions_count
    )

    return (
        count
        < MAX_OPEN_POSITIONS
    )


# ============================================================
# PORTFOLIO RISK
# ============================================================

def calculate_portfolio_risk_pct(
    balance: float,
    open_risk_amount: float,
) -> float:

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
        * 100
    )


def portfolio_risk_allowed(
    balance: float,
    open_risk_amount: float,
    new_trade_risk_amount: float,
) -> bool:

    balance = _safe_float(
        balance
    )

    open_risk_amount = _safe_float(
        open_risk_amount
    )

    new_trade_risk_amount = (
        _safe_float(
            new_trade_risk_amount
        )
    )

    if balance <= 0:
        return False

    total_risk_amount = (
        open_risk_amount
        + new_trade_risk_amount
    )

    portfolio_risk_pct = (
        total_risk_amount
        / balance
        * 100
    )

    return (
        portfolio_risk_pct
        <= MAX_PORTFOLIO_RISK_PCT
    )


# ============================================================
# FULL RISK CHECK
# ============================================================

def evaluate_trade_risk(
    plan: Dict,
    balance: float,
    open_positions_count: int = 0,
    open_risk_amount: float = 0.0,
) -> Dict:

    if not validate_trade_plan(
        plan
    ):

        return {
            "approved": False,
            "reason": (
                "Trade plan validation failed"
            ),
        }

    if not can_open_new_position(
        open_positions_count
    ):

        return {
            "approved": False,
            "reason": (
                "Maximum open positions reached"
            ),
        }

    new_trade_risk = _safe_float(
        plan.get(
            "actual_risk_amount",
            plan.get(
                "risk_amount",
                0,
            ),
        )
    )

    if not portfolio_risk_allowed(
        balance=balance,
        open_risk_amount=open_risk_amount,
        new_trade_risk_amount=(
            new_trade_risk
        ),
    ):

        return {
            "approved": False,
            "reason": (
                "Portfolio risk limit exceeded"
            ),
        }

    return {
        "approved": True,

        "reason":
            "Risk checks passed",

        "reward_risk_ratio":
            plan.get(
                "reward_risk_ratio"
            ),

        "trade_risk_amount":
            new_trade_risk,

        "max_open_positions":
            MAX_OPEN_POSITIONS,

        "max_portfolio_risk_pct":
            MAX_PORTFOLIO_RISK_PCT,
    }

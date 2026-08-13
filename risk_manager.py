"""
risk_manager.py

Risk management engine for the autonomous trading bot.

Calculates:
- Position size
- Stop Loss
- Take Profit
- Risk amount
"""

DEFAULT_RISK_PERCENT = 1.0
DEFAULT_STOP_LOSS_PERCENT = 1.0
DEFAULT_TAKE_PROFIT_PERCENT = 2.0

MAX_RISK_PERCENT = 2.0


def calculate_trade_plan(
    balance,
    entry_price,
    signal,
    risk_percent=DEFAULT_RISK_PERCENT,
    stop_loss_percent=DEFAULT_STOP_LOSS_PERCENT,
    take_profit_percent=DEFAULT_TAKE_PROFIT_PERCENT,
):
    """
    Create a complete trade plan.

    signal must be:
        BUY
        SELL
    """

    if balance <= 0:
        raise ValueError("Balance must be greater than zero.")

    if entry_price <= 0:
        raise ValueError("Entry price must be greater than zero.")

    signal = str(signal).upper()

    if signal not in ("BUY", "SELL"):
        return {
            "action": "NO TRADE",
            "reason": "Signal is not BUY or SELL",
        }

    # Safety limit
    risk_percent = min(
        float(risk_percent),
        MAX_RISK_PERCENT,
    )

    stop_loss_percent = float(stop_loss_percent)
    take_profit_percent = float(take_profit_percent)

    # Maximum money allowed to lose
    risk_amount = balance * (risk_percent / 100)

    # Stop-loss distance
    stop_distance = entry_price * (
        stop_loss_percent / 100
    )

    # Position size based on risk
    quantity = risk_amount / stop_distance

    if signal == "BUY":
        side = "LONG"

        stop_loss = entry_price - stop_distance

        take_profit = entry_price + (
            entry_price * take_profit_percent / 100
        )

    else:
        side = "SHORT"

        stop_loss = entry_price + stop_distance

        take_profit = entry_price - (
            entry_price * take_profit_percent / 100
        )

    position_value = quantity * entry_price

    return {
        "action": "TRADE",
        "side": side,
        "entry_price": float(entry_price),
        "quantity": float(quantity),
        "position_value": float(position_value),
        "risk_percent": float(risk_percent),
        "risk_amount": float(risk_amount),
        "stop_loss": float(stop_loss),
        "take_profit": float(take_profit),
    }


def validate_trade_plan(plan):
    """
    Basic safety validation before an order is allowed.
    """

    if not plan:
        return False

    if plan.get("action") != "TRADE":
        return False

    if plan.get("quantity", 0) <= 0:
        return False

    if plan.get("entry_price", 0) <= 0:
        return False

    if plan.get("stop_loss", 0) <= 0:
        return False

    if plan.get("take_profit", 0) <= 0:
        return False

    return True

"""
trade_executor.py

Autonomous trade execution layer.

Flow:
Signal -> Risk Manager -> Order

Safety:
- Testnet required
- Does not execute if testnet is disabled
- Prevents duplicate positions
"""

from exchanges import get_client
from risk_manager import (
    calculate_trade_plan,
    validate_trade_plan,
)


class TradeExecutor:

    def __init__(
        self,
        exchange,
        api_key="",
        api_secret="",
        use_testnet=True,
    ):
        if not use_testnet:
            raise RuntimeError(
                "Safety lock: autonomous execution "
                "requires TESTNET mode."
            )

        self.exchange_name = exchange

        self.client = get_client(
            exchange=exchange,
            api_key=api_key,
            api_secret=api_secret,
            use_testnet=True,
        )

    def get_balance(self):
        return self.client.get_balance()

    def get_position(self, symbol):
        return self.client.get_position(symbol)

    def create_trade_plan(
        self,
        balance,
        entry_price,
        signal,
        risk_percent=1.0,
        stop_loss_percent=1.0,
        take_profit_percent=2.0,
    ):
        return calculate_trade_plan(
            balance=balance,
            entry_price=entry_price,
            signal=signal,
            risk_percent=risk_percent,
            stop_loss_percent=stop_loss_percent,
            take_profit_percent=take_profit_percent,
        )

    def execute(
        self,
        symbol,
        balance,
        entry_price,
        signal,
        risk_percent=1.0,
        stop_loss_percent=1.0,
        take_profit_percent=2.0,
    ):
        """
        Execute a trade on TESTNET.

        Returns a result dictionary.
        """

        signal = str(signal).upper()

        if signal not in ("BUY", "SELL"):
            return {
                "status": "SKIPPED",
                "reason": "No valid trading signal.",
            }

        # Prevent duplicate position
        existing_position = self.get_position(symbol)

        if existing_position:
            return {
                "status": "SKIPPED",
                "reason": "Existing position detected.",
                "position": existing_position,
            }

        # Create risk-managed trade plan
        plan = self.create_trade_plan(
            balance=balance,
            entry_price=entry_price,
            signal=signal,
            risk_percent=risk_percent,
            stop_loss_percent=stop_loss_percent,
            take_profit_percent=take_profit_percent,
        )

        if not validate_trade_plan(plan):
            return {
                "status": "SKIPPED",
                "reason": "Invalid trade plan.",
                "plan": plan,
            }

        side = "buy" if signal == "BUY" else "sell"

        # Execute market order
        order = self.client.place_order(
            symbol=symbol,
            side=side,
            qty=plan["quantity"],
        )

        # Check for exchange error
        if isinstance(order, dict) and order.get("error"):
            return {
                "status": "ERROR",
                "reason": order["error"],
                "plan": plan,
            }

        # Attach TP/SL
        close_side = "sell" if signal == "BUY" else "buy"

        tp_result, sl_result = self.client.place_tp_sl(
            symbol=symbol,
            close_side=close_side,
            tp_price=plan["take_profit"],
            sl_price=plan["stop_loss"],
        )

        return {
            "status": "EXECUTED",
            "exchange": self.exchange_name,
            "symbol": symbol,
            "side": plan["side"],
            "entry": plan["entry_price"],
            "quantity": plan["quantity"],
            "stop_loss": plan["stop_loss"],
            "take_profit": plan["take_profit"],
            "order": order,
            "tp": tp_result,
            "sl": sl_result,
        }

"""
paper_trader.py

Simple paper trading engine.
No real orders are sent to Binance or Bybit.
"""

from datetime import datetime, timezone


class PaperTrader:

    def __init__(self, starting_balance=10000.0):
        self.balance = float(starting_balance)
        self.position = None
        self.trade_history = []

    def get_balance(self):
        return self.balance

    def get_position(self):
        return self.position

    def open_trade(
        self,
        symbol,
        signal,
        entry_price,
        quantity,
        take_profit,
        stop_loss,
    ):
        if self.position is not None:
            return {
                "status": "SKIPPED",
                "reason": "Position already open",
            }

        side = "LONG" if signal == "BUY" else "SHORT"

        self.position = {
            "symbol": symbol,
            "side": side,
            "entry_price": float(entry_price),
            "quantity": float(quantity),
            "take_profit": float(take_profit),
            "stop_loss": float(stop_loss),
            "opened_at": datetime.now(timezone.utc).isoformat(),
        }

        return {
            "status": "EXECUTED",
            "mode": "PAPER",
            "position": self.position,
        }

    def update_price(self, current_price):
        if self.position is None:
            return None

        current_price = float(current_price)
        pos = self.position

        exit_reason = None

        if pos["side"] == "LONG":
            if current_price >= pos["take_profit"]:
                exit_reason = "TAKE_PROFIT"
            elif current_price <= pos["stop_loss"]:
                exit_reason = "STOP_LOSS"

        elif pos["side"] == "SHORT":
            if current_price <= pos["take_profit"]:
                exit_reason = "TAKE_PROFIT"
            elif current_price >= pos["stop_loss"]:
                exit_reason = "STOP_LOSS"

        if exit_reason is None:
            return {
                "status": "OPEN",
                "position": pos,
            }

        return self.close_trade(
            exit_price=current_price,
            reason=exit_reason,
        )

    def close_trade(self, exit_price, reason="MANUAL"):
        if self.position is None:
            return {
                "status": "SKIPPED",
                "reason": "No open position",
            }

        pos = self.position
        exit_price = float(exit_price)

        if pos["side"] == "LONG":
            pnl = (
                exit_price - pos["entry_price"]
            ) * pos["quantity"]
        else:
            pnl = (
                pos["entry_price"] - exit_price
            ) * pos["quantity"]

        self.balance += pnl

        result = {
            "status": "CLOSED",
            "symbol": pos["symbol"],
            "side": pos["side"],
            "entry_price": pos["entry_price"],
            "exit_price": exit_price,
            "quantity": pos["quantity"],
            "pnl": float(pnl),
            "reason": reason,
            "balance": float(self.balance),
            "closed_at": datetime.now(timezone.utc).isoformat(),
        }

        self.trade_history.append(result)
        self.position = None

        return result

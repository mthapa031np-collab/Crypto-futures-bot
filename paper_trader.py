"""
paper_trader.py

Persistent paper trading engine.

Stores:
- Paper balance
- Open position
- Trade history

State is saved to a local JSON file so the bot can restore
its paper-trading state after an app/process restart.

IMPORTANT:
This is still PAPER TRADING only.
No real exchange orders are sent.
"""

import json
import os
from datetime import datetime, timezone


STATE_FILE = os.environ.get(
    "PAPER_STATE_FILE",
    "paper_state.json",
)


class PaperTrader:

    def __init__(
        self,
        starting_balance=10000.0,
        state_file=STATE_FILE,
    ):
        self.starting_balance = float(
            starting_balance
        )

        self.state_file = state_file

        self.balance = self.starting_balance
        self.position = None
        self.trade_history = []

        self._load_state()

    # ========================================================
    # STATE STORAGE
    # ========================================================

    def _default_state(self):
        return {
            "balance": self.starting_balance,
            "position": None,
            "trade_history": [],
        }

    def _load_state(self):
        """
        Restore previous paper-trading state if available.
        """

        if not os.path.exists(
            self.state_file
        ):
            self._save_state()
            return

        try:

            with open(
                self.state_file,
                "r",
                encoding="utf-8",
            ) as file:

                data = json.load(
                    file
                )

            self.balance = float(
                data.get(
                    "balance",
                    self.starting_balance,
                )
            )

            self.position = data.get(
                "position"
            )

            self.trade_history = data.get(
                "trade_history",
                [],
            )

            if not isinstance(
                self.trade_history,
                list,
            ):
                self.trade_history = []

            print(
                "[PAPER STATE] Restored | "
                f"Balance={self.balance:.2f} | "
                f"Position="
                f"{self.position if self.position else 'None'} | "
                f"Trades={len(self.trade_history)}",
                flush=True,
            )

        except Exception as error:

            print(
                "[PAPER STATE ERROR] "
                f"Could not load state: {error}",
                flush=True,
            )

            self.balance = (
                self.starting_balance
            )

            self.position = None
            self.trade_history = []

            self._save_state()

    def _save_state(self):
        """
        Save paper-trading state to disk.
        """

        state = {
            "balance": float(
                self.balance
            ),
            "position": self.position,
            "trade_history": (
                self.trade_history
            ),
        }

        temp_file = (
            f"{self.state_file}.tmp"
        )

        try:

            with open(
                temp_file,
                "w",
                encoding="utf-8",
            ) as file:

                json.dump(
                    state,
                    file,
                    indent=2,
                )

            os.replace(
                temp_file,
                self.state_file,
            )

        except Exception as error:

            print(
                "[PAPER STATE ERROR] "
                f"Could not save state: {error}",
                flush=True,
            )

    # ========================================================
    # ACCOUNT
    # ========================================================

    def get_balance(self):
        return float(
            self.balance
        )

    def get_position(self):
        return self.position

    def get_trade_history(self):
        return list(
            self.trade_history
        )

    # ========================================================
    # OPEN TRADE
    # ========================================================

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
                "reason": (
                    "Position already open"
                ),
                "position": self.position,
            }

        signal = str(
            signal
        ).upper()

        if signal not in (
            "BUY",
            "SELL",
        ):

            return {
                "status": "SKIPPED",
                "reason": (
                    "Invalid signal"
                ),
            }

        side = (
            "LONG"
            if signal == "BUY"
            else "SHORT"
        )

        self.position = {
            "symbol": str(
                symbol
            ).upper(),
            "side": side,
            "entry_price": float(
                entry_price
            ),
            "quantity": float(
                quantity
            ),
            "take_profit": float(
                take_profit
            ),
            "stop_loss": float(
                stop_loss
            ),
            "opened_at": (
                datetime.now(
                    timezone.utc
                ).isoformat()
            ),
        }

        self._save_state()

        print(
            "[PAPER STATE] "
            "Position saved | "
            f"{self.position}",
            flush=True,
        )

        return {
            "status": "EXECUTED",
            "mode": "PAPER",
            "position": self.position,
        }

    # ========================================================
    # UPDATE OPEN POSITION
    # ========================================================

    def update_price(
        self,
        current_price,
    ):

        if self.position is None:
            return None

        current_price = float(
            current_price
        )

        position = self.position

        exit_reason = None

        if position["side"] == "LONG":

            if (
                current_price
                >= position[
                    "take_profit"
                ]
            ):
                exit_reason = (
                    "TAKE_PROFIT"
                )

            elif (
                current_price
                <= position[
                    "stop_loss"
                ]
            ):
                exit_reason = (
                    "STOP_LOSS"
                )

        elif position["side"] == "SHORT":

            if (
                current_price
                <= position[
                    "take_profit"
                ]
            ):
                exit_reason = (
                    "TAKE_PROFIT"
                )

            elif (
                current_price
                >= position[
                    "stop_loss"
                ]
            ):
                exit_reason = (
                    "STOP_LOSS"
                )

        if exit_reason is None:

            return {
                "status": "OPEN",
                "position": position,
                "current_price": (
                    current_price
                ),
            }

        return self.close_trade(
            exit_price=current_price,
            reason=exit_reason,
        )

    # ========================================================
    # CLOSE TRADE
    # ========================================================

    def close_trade(
        self,
        exit_price,
        reason="MANUAL",
    ):

        if self.position is None:

            return {
                "status": "SKIPPED",
                "reason": (
                    "No open position"
                ),
            }

        position = self.position

        exit_price = float(
            exit_price
        )

        if position[
            "side"
        ] == "LONG":

            pnl = (
                exit_price
                - position[
                    "entry_price"
                ]
            ) * position[
                "quantity"
            ]

        else:

            pnl = (
                position[
                    "entry_price"
                ]
                - exit_price
            ) * position[
                "quantity"
            ]

        self.balance += pnl

        result = {
            "status": "CLOSED",
            "symbol": position[
                "symbol"
            ],
            "side": position[
                "side"
            ],
            "entry_price": position[
                "entry_price"
            ],
            "exit_price": (
                exit_price
            ),
            "quantity": position[
                "quantity"
            ],
            "take_profit": position[
                "take_profit"
            ],
            "stop_loss": position[
                "stop_loss"
            ],
            "pnl": float(
                pnl
            ),
            "reason": reason,
            "balance": float(
                self.balance
            ),
            "opened_at": position.get(
                "opened_at"
            ),
            "closed_at": (
                datetime.now(
                    timezone.utc
                ).isoformat()
            ),
        }

        self.trade_history.append(
            result
        )

        self.position = None

        self._save_state()

        print(
            "[PAPER STATE] "
            "Trade closed and saved | "
            f"PnL={pnl:.2f} | "
            f"Balance={self.balance:.2f}",
            flush=True,
        )

        return result

    # ========================================================
    # RESET - FOR TESTING ONLY
    # ========================================================

    def reset(
        self,
        starting_balance=None,
    ):
        """
        Reset paper account manually.
        Do not call this automatically.
        """

        if starting_balance is None:

            starting_balance = (
                self.starting_balance
            )

        self.balance = float(
            starting_balance
        )

        self.position = None

        self.trade_history = []

        self._save_state()

        return {
            "status": "RESET",
            "balance": self.balance,
        }

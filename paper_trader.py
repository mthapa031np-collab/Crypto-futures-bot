"""
paper_trader.py

Persistent PostgreSQL-backed PAPER trading engine.

Stores:
- Paper balance
- Open position
- Trade history

Uses:
DATABASE_URL from Render environment variables.

IMPORTANT:
- PAPER TRADING ONLY
- NO REAL EXCHANGE ORDERS
"""

import os
from datetime import datetime, timezone

import psycopg
from psycopg.rows import dict_row


DATABASE_URL = os.environ.get("DATABASE_URL", "").strip()


class PaperTrader:

    def __init__(self, starting_balance=10000.0):

        self.starting_balance = float(starting_balance)

        if not DATABASE_URL:
            raise RuntimeError(
                "DATABASE_URL is not set."
            )

        self._create_tables()
        self._create_account_if_missing()

    # ========================================================
    # DATABASE CONNECTION
    # ========================================================

    def _connect(self):

        return psycopg.connect(
            DATABASE_URL,
            row_factory=dict_row,
            connect_timeout=10,
        )

    # ========================================================
    # DATABASE SETUP
    # ========================================================

    def _create_tables(self):

        with self._connect() as conn:

            with conn.cursor() as cur:

                cur.execute(
                    """
                    CREATE TABLE IF NOT EXISTS paper_account (
                        id INTEGER PRIMARY KEY,
                        balance DOUBLE PRECISION NOT NULL,
                        starting_balance DOUBLE PRECISION NOT NULL,
                        updated_at TIMESTAMPTZ NOT NULL
                    )
                    """
                )

                cur.execute(
                    """
                    CREATE TABLE IF NOT EXISTS paper_position (
                        id INTEGER PRIMARY KEY,
                        symbol TEXT NOT NULL,
                        side TEXT NOT NULL,
                        entry_price DOUBLE PRECISION NOT NULL,
                        quantity DOUBLE PRECISION NOT NULL,
                        take_profit DOUBLE PRECISION NOT NULL,
                        stop_loss DOUBLE PRECISION NOT NULL,
                        opened_at TIMESTAMPTZ NOT NULL
                    )
                    """
                )

                cur.execute(
                    """
                    CREATE TABLE IF NOT EXISTS paper_trades (
                        id BIGSERIAL PRIMARY KEY,
                        symbol TEXT NOT NULL,
                        side TEXT NOT NULL,
                        entry_price DOUBLE PRECISION NOT NULL,
                        exit_price DOUBLE PRECISION NOT NULL,
                        quantity DOUBLE PRECISION NOT NULL,
                        take_profit DOUBLE PRECISION NOT NULL,
                        stop_loss DOUBLE PRECISION NOT NULL,
                        pnl DOUBLE PRECISION NOT NULL,
                        reason TEXT NOT NULL,
                        balance_after DOUBLE PRECISION NOT NULL,
                        opened_at TIMESTAMPTZ,
                        closed_at TIMESTAMPTZ NOT NULL
                    )
                    """
                )

            conn.commit()

    def _create_account_if_missing(self):

        now = datetime.now(timezone.utc)

        with self._connect() as conn:

            with conn.cursor() as cur:

                cur.execute(
                    """
                    SELECT id
                    FROM paper_account
                    WHERE id = 1
                    """
                )

                row = cur.fetchone()

                if row is None:

                    cur.execute(
                        """
                        INSERT INTO paper_account (
                            id,
                            balance,
                            starting_balance,
                            updated_at
                        )
                        VALUES (%s, %s, %s, %s)
                        """,
                        (
                            1,
                            self.starting_balance,
                            self.starting_balance,
                            now,
                        ),
                    )

            conn.commit()

    # ========================================================
    # ACCOUNT
    # ========================================================

    def get_balance(self):

        with self._connect() as conn:

            with conn.cursor() as cur:

                cur.execute(
                    """
                    SELECT balance
                    FROM paper_account
                    WHERE id = 1
                    """
                )

                row = cur.fetchone()

                if not row:
                    return self.starting_balance

                return float(row["balance"])

    def _set_balance(self, balance):

        with self._connect() as conn:

            with conn.cursor() as cur:

                cur.execute(
                    """
                    UPDATE paper_account
                    SET balance = %s,
                        updated_at = %s
                    WHERE id = 1
                    """,
                    (
                        float(balance),
                        datetime.now(timezone.utc),
                    ),
                )

            conn.commit()

    # ========================================================
    # POSITION
    # ========================================================

    def get_position(self):

        with self._connect() as conn:

            with conn.cursor() as cur:

                cur.execute(
                    """
                    SELECT
                        symbol,
                        side,
                        entry_price,
                        quantity,
                        take_profit,
                        stop_loss,
                        opened_at
                    FROM paper_position
                    WHERE id = 1
                    """
                )

                row = cur.fetchone()

                if not row:
                    return None

                return {
                    "symbol": row["symbol"],
                    "side": row["side"],
                    "entry_price": float(row["entry_price"]),
                    "quantity": float(row["quantity"]),
                    "take_profit": float(row["take_profit"]),
                    "stop_loss": float(row["stop_loss"]),
                    "opened_at": row["opened_at"].isoformat(),
                }

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

        existing = self.get_position()

        if existing is not None:

            return {
                "status": "SKIPPED",
                "reason": "Position already open",
                "position": existing,
            }

        signal = str(signal).upper()

        if signal not in ("BUY", "SELL"):

            return {
                "status": "SKIPPED",
                "reason": "Invalid signal",
            }

        side = (
            "LONG"
            if signal == "BUY"
            else "SHORT"
        )

        opened_at = datetime.now(
            timezone.utc
        )

        with self._connect() as conn:

            with conn.cursor() as cur:

                cur.execute(
                    """
                    INSERT INTO paper_position (
                        id,
                        symbol,
                        side,
                        entry_price,
                        quantity,
                        take_profit,
                        stop_loss,
                        opened_at
                    )
                    VALUES (
                        1, %s, %s, %s, %s, %s, %s, %s
                    )
                    """,
                    (
                        str(symbol).upper(),
                        side,
                        float(entry_price),
                        float(quantity),
                        float(take_profit),
                        float(stop_loss),
                        opened_at,
                    ),
                )

            conn.commit()

        position = self.get_position()

        print(
            "[POSTGRES PAPER] "
            f"Position opened: {position}",
            flush=True,
        )

        return {
            "status": "EXECUTED",
            "mode": "PAPER",
            "position": position,
        }

    # ========================================================
    # UPDATE POSITION
    # ========================================================

    def update_price(
        self,
        current_price,
    ):

        position = self.get_position()

        if position is None:
            return None

        current_price = float(
            current_price
        )

        exit_reason = None

        if position["side"] == "LONG":

            if current_price >= position["take_profit"]:
                exit_reason = "TAKE_PROFIT"

            elif current_price <= position["stop_loss"]:
                exit_reason = "STOP_LOSS"

        elif position["side"] == "SHORT":

            if current_price <= position["take_profit"]:
                exit_reason = "TAKE_PROFIT"

            elif current_price >= position["stop_loss"]:
                exit_reason = "STOP_LOSS"

        if exit_reason is None:

            return {
                "status": "OPEN",
                "position": position,
                "current_price": current_price,
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

        position = self.get_position()

        if position is None:

            return {
                "status": "SKIPPED",
                "reason": "No open position",
            }

        exit_price = float(exit_price)

        if position["side"] == "LONG":

            pnl = (
                exit_price
                - position["entry_price"]
            ) * position["quantity"]

        else:

            pnl = (
                position["entry_price"]
                - exit_price
            ) * position["quantity"]

        old_balance = self.get_balance()

        new_balance = (
            old_balance
            + pnl
        )

        closed_at = datetime.now(
            timezone.utc
        )

        with self._connect() as conn:

            with conn.cursor() as cur:

                cur.execute(
                    """
                    UPDATE paper_account
                    SET balance = %s,
                        updated_at = %s
                    WHERE id = 1
                    """,
                    (
                        new_balance,
                        closed_at,
                    ),
                )

                cur.execute(
                    """
                    INSERT INTO paper_trades (
                        symbol,
                        side,
                        entry_price,
                        exit_price,
                        quantity,
                        take_profit,
                        stop_loss,
                        pnl,
                        reason,
                        balance_after,
                        opened_at,
                        closed_at
                    )
                    VALUES (
                        %s, %s, %s, %s,
                        %s, %s, %s, %s,
                        %s, %s, %s, %s
                    )
                    """,
                    (
                        position["symbol"],
                        position["side"],
                        position["entry_price"],
                        exit_price,
                        position["quantity"],
                        position["take_profit"],
                        position["stop_loss"],
                        pnl,
                        reason,
                        new_balance,
                        position["opened_at"],
                        closed_at,
                    ),
                )

                cur.execute(
                    """
                    DELETE FROM paper_position
                    WHERE id = 1
                    """
                )

            conn.commit()

        result = {
            "status": "CLOSED",
            "symbol": position["symbol"],
            "side": position["side"],
            "entry_price": position["entry_price"],
            "exit_price": exit_price,
            "quantity": position["quantity"],
            "take_profit": position["take_profit"],
            "stop_loss": position["stop_loss"],
            "pnl": float(pnl),
            "reason": reason,
            "balance": float(new_balance),
            "opened_at": position["opened_at"],
            "closed_at": closed_at.isoformat(),
        }

        print(
            "[POSTGRES PAPER] "
            f"Trade closed | "
            f"PnL={pnl:.2f} | "
            f"Balance={new_balance:.2f}",
            flush=True,
        )

        return result

    # ========================================================
    # TRADE HISTORY
    # ========================================================

    def get_trade_history(self):

        with self._connect() as conn:

            with conn.cursor() as cur:

                cur.execute(
                    """
                    SELECT
                        id,
                        symbol,
                        side,
                        entry_price,
                        exit_price,
                        quantity,
                        take_profit,
                        stop_loss,
                        pnl,
                        reason,
                        balance_after,
                        opened_at,
                        closed_at
                    FROM paper_trades
                    ORDER BY id DESC
                    """
                )

                rows = cur.fetchall()

                history = []

                for row in rows:

                    history.append(
                        {
                            "id": row["id"],
                            "symbol": row["symbol"],
                            "side": row["side"],
                            "entry_price": float(row["entry_price"]),
                            "exit_price": float(row["exit_price"]),
                            "quantity": float(row["quantity"]),
                            "take_profit": float(row["take_profit"]),
                            "stop_loss": float(row["stop_loss"]),
                            "pnl": float(row["pnl"]),
                            "reason": row["reason"],
                            "balance": float(row["balance_after"]),
                            "opened_at": (
                                row["opened_at"].isoformat()
                                if row["opened_at"]
                                else None
                            ),
                            "closed_at": row["closed_at"].isoformat(),
                        }
                    )

                return history

    # ========================================================
    # RESET - TESTING ONLY
    # ========================================================

    def reset(
        self,
        starting_balance=None,
    ):

        if starting_balance is None:
            starting_balance = self.starting_balance

        now = datetime.now(
            timezone.utc
        )

        with self._connect() as conn:

            with conn.cursor() as cur:

                cur.execute(
                    """
                    DELETE FROM paper_position
                    """
                )

                cur.execute(
                    """
                    DELETE FROM paper_trades
                    """
                )

                cur.execute(
                    """
                    UPDATE paper_account
                    SET balance = %s,
                        starting_balance = %s,
                        updated_at = %s
                    WHERE id = 1
                    """,
                    (
                        float(starting_balance),
                        float(starting_balance),
                        now,
                    ),
                )

            conn.commit()

        return {
            "status": "RESET",
            "balance": float(
                starting_balance
            ),
        }

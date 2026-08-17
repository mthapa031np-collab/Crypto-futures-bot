"""
paper_trader.py

PRO AI QUANT TERMINAL V3.5

Persistent PostgreSQL-backed MULTI-ASSET PAPER trading engine.

Supports independent position slots:

    CRYPTO_MAIN
        Maximum 1 Crypto position

    METALS_MAIN
        Maximum 1 Metals position

Therefore the platform can hold:

    1 Crypto trade
    +
    1 Gold/Silver trade

at the same time.

IMPORTANT:
- PAPER TRADING ONLY
- NO REAL EXCHANGE ORDERS
- Existing legacy Crypto position is migrated safely
- Existing paper balance and trade history are preserved
"""

import os
from datetime import datetime, timezone

import psycopg
from psycopg.rows import dict_row


# ============================================================
# CONFIG
# ============================================================

DATABASE_URL = os.environ.get(
    "DATABASE_URL",
    "",
).strip()


CRYPTO_SLOT = "CRYPTO_MAIN"
METALS_SLOT = "METALS_MAIN"


VALID_SLOTS = {
    CRYPTO_SLOT,
    METALS_SLOT,
}


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


def _infer_asset_class(
    symbol,
):

    symbol = _normalize_symbol(
        symbol
    )

    if symbol in (
        "XAUUSD",
        "XAGUSD",
    ):

        return "METAL"

    return "CRYPTO"


def _infer_slot(
    symbol,
):

    asset_class = (
        _infer_asset_class(
            symbol
        )
    )

    if asset_class == "METAL":

        return METALS_SLOT

    return CRYPTO_SLOT


def _normalize_slot(
    slot=None,
    symbol=None,
):

    if slot is None:

        if symbol is not None:

            return _infer_slot(
                symbol
            )

        return CRYPTO_SLOT

    slot = (
        str(slot)
        .upper()
        .strip()
    )

    if slot not in VALID_SLOTS:

        raise ValueError(
            f"Invalid position slot: {slot}"
        )

    return slot


# ============================================================
# PAPER TRADER
# ============================================================

class PaperTrader:

    def __init__(
        self,
        starting_balance=10000.0,
    ):

        self.starting_balance = float(
            starting_balance
        )

        if not DATABASE_URL:

            raise RuntimeError(
                "DATABASE_URL is not set."
            )

        self._create_tables()

        self._upgrade_trade_history_table()

        self._create_account_if_missing()

        self._migrate_legacy_position()


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

                # --------------------------------------------
                # PAPER ACCOUNT
                # --------------------------------------------

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

                # --------------------------------------------
                # LEGACY TABLE
                #
                # Kept so existing installations remain safe.
                # New engine does NOT use this table for active
                # position management after migration.
                # --------------------------------------------

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

                # --------------------------------------------
                # V3.5 MULTI-ASSET POSITION TABLE
                # --------------------------------------------

                cur.execute(
                    """
                    CREATE TABLE IF NOT EXISTS paper_positions (
                        slot TEXT PRIMARY KEY,
                        asset_class TEXT NOT NULL,
                        symbol TEXT NOT NULL,
                        side TEXT NOT NULL,
                        entry_price DOUBLE PRECISION NOT NULL,
                        quantity DOUBLE PRECISION NOT NULL,
                        take_profit DOUBLE PRECISION NOT NULL,
                        stop_loss DOUBLE PRECISION NOT NULL,
                        opened_at TIMESTAMPTZ NOT NULL,
                        updated_at TIMESTAMPTZ NOT NULL
                    )
                    """
                )

                # --------------------------------------------
                # TRADE HISTORY
                # --------------------------------------------

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


    # ========================================================
    # SAFE SCHEMA UPGRADE
    # ========================================================

    def _upgrade_trade_history_table(self):

        with self._connect() as conn:

            with conn.cursor() as cur:

                cur.execute(
                    """
                    ALTER TABLE paper_trades
                    ADD COLUMN IF NOT EXISTS slot TEXT
                    """
                )

                cur.execute(
                    """
                    ALTER TABLE paper_trades
                    ADD COLUMN IF NOT EXISTS asset_class TEXT
                    """
                )

            conn.commit()


    # ========================================================
    # ACCOUNT INITIALISATION
    # ========================================================

    def _create_account_if_missing(self):

        now = datetime.now(
            timezone.utc
        )

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
                        VALUES (
                            %s,
                            %s,
                            %s,
                            %s
                        )
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
    # LEGACY POSITION MIGRATION
    # ========================================================

    def _migrate_legacy_position(self):

        """
        Safely migrates the old single-position table into
        CRYPTO_MAIN.

        Example:
            Existing DOGEUSDT SHORT
                ↓
            CRYPTO_MAIN

        Existing position is NOT deleted until successful copy.
        """

        with self._connect() as conn:

            with conn.cursor() as cur:

                # Is CRYPTO_MAIN already populated?

                cur.execute(
                    """
                    SELECT slot
                    FROM paper_positions
                    WHERE slot = %s
                    """,
                    (
                        CRYPTO_SLOT,
                    ),
                )

                existing_new = (
                    cur.fetchone()
                )

                if existing_new:

                    return

                # Read old position.

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

                legacy = (
                    cur.fetchone()
                )

                if not legacy:

                    return

                now = datetime.now(
                    timezone.utc
                )

                cur.execute(
                    """
                    INSERT INTO paper_positions (
                        slot,
                        asset_class,
                        symbol,
                        side,
                        entry_price,
                        quantity,
                        take_profit,
                        stop_loss,
                        opened_at,
                        updated_at
                    )
                    VALUES (
                        %s,
                        %s,
                        %s,
                        %s,
                        %s,
                        %s,
                        %s,
                        %s,
                        %s,
                        %s
                    )
                    ON CONFLICT (slot)
                    DO NOTHING
                    """,
                    (
                        CRYPTO_SLOT,
                        "CRYPTO",
                        legacy[
                            "symbol"
                        ],
                        legacy[
                            "side"
                        ],
                        legacy[
                            "entry_price"
                        ],
                        legacy[
                            "quantity"
                        ],
                        legacy[
                            "take_profit"
                        ],
                        legacy[
                            "stop_loss"
                        ],
                        legacy[
                            "opened_at"
                        ],
                        now,
                    ),
                )

            conn.commit()

        print(
            "[POSTGRES MIGRATION] "
            "Legacy Crypto position migrated "
            "to CRYPTO_MAIN.",
            flush=True,
        )


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

                    return (
                        self.starting_balance
                    )

                return float(
                    row[
                        "balance"
                    ]
                )


    def _set_balance(
        self,
        balance,
    ):

        with self._connect() as conn:

            with conn.cursor() as cur:

                cur.execute(
                    """
                    UPDATE paper_account
                    SET
                        balance = %s,
                        updated_at = %s
                    WHERE id = 1
                    """,
                    (
                        float(
                            balance
                        ),
                        datetime.now(
                            timezone.utc
                        ),
                    ),
                )

            conn.commit()


    # ========================================================
    # POSITION SERIALIZER
    # ========================================================

    def _serialize_position(
        self,
        row,
    ):

        if not row:

            return None

        opened_at = row[
            "opened_at"
        ]

        return {
            "slot":
                row[
                    "slot"
                ],

            "asset_class":
                row[
                    "asset_class"
                ],

            "symbol":
                row[
                    "symbol"
                ],

            "side":
                row[
                    "side"
                ],

            "entry_price":
                float(
                    row[
                        "entry_price"
                    ]
                ),

            "quantity":
                float(
                    row[
                        "quantity"
                    ]
                ),

            "take_profit":
                float(
                    row[
                        "take_profit"
                    ]
                ),

            "stop_loss":
                float(
                    row[
                        "stop_loss"
                    ]
                ),

            "opened_at":
                (
                    opened_at.isoformat()
                    if opened_at
                    else None
                ),
        }


    # ========================================================
    # GET ONE POSITION
    # ========================================================

    def get_position(
        self,
        slot=CRYPTO_SLOT,
    ):

        """
        Backward compatible:

            trader.get_position()

        still returns CRYPTO_MAIN.

        For metals:

            trader.get_position("METALS_MAIN")
        """

        slot = _normalize_slot(
            slot
        )

        with self._connect() as conn:

            with conn.cursor() as cur:

                cur.execute(
                    """
                    SELECT
                        slot,
                        asset_class,
                        symbol,
                        side,
                        entry_price,
                        quantity,
                        take_profit,
                        stop_loss,
                        opened_at
                    FROM paper_positions
                    WHERE slot = %s
                    """,
                    (
                        slot,
                    ),
                )

                row = cur.fetchone()

                return (
                    self._serialize_position(
                        row
                    )
                )


    # ========================================================
    # GET ALL OPEN POSITIONS
    # ========================================================

    def get_positions(self):

        with self._connect() as conn:

            with conn.cursor() as cur:

                cur.execute(
                    """
                    SELECT
                        slot,
                        asset_class,
                        symbol,
                        side,
                        entry_price,
                        quantity,
                        take_profit,
                        stop_loss,
                        opened_at
                    FROM paper_positions
                    ORDER BY slot
                    """
                )

                rows = cur.fetchall()

        return [
            self._serialize_position(
                row
            )
            for row in rows
        ]


    # ========================================================
    # POSITION COUNT
    # ========================================================

    def get_open_position_count(self):

        with self._connect() as conn:

            with conn.cursor() as cur:

                cur.execute(
                    """
                    SELECT COUNT(*) AS count
                    FROM paper_positions
                    """
                )

                row = cur.fetchone()

                return int(
                    row[
                        "count"
                    ]
                )


    # ========================================================
    # SLOT AVAILABILITY
    # ========================================================

    def slot_available(
        self,
        slot,
    ):

        return (
            self.get_position(
                slot
            )
            is None
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
        slot=None,
    ):

        symbol = _normalize_symbol(
            symbol
        )

        slot = _normalize_slot(
            slot=slot,
            symbol=symbol,
        )

        asset_class = (
            _infer_asset_class(
                symbol
            )
        )

        existing = self.get_position(
            slot
        )

        if existing is not None:

            return {
                "status":
                    "SKIPPED",

                "reason":
                    (
                        f"Position already "
                        f"open in {slot}"
                    ),

                "position":
                    existing,
            }

        signal = (
            str(signal)
            .upper()
            .strip()
        )

        if signal not in (
            "BUY",
            "SELL",
        ):

            return {
                "status":
                    "SKIPPED",

                "reason":
                    "Invalid signal",
            }

        entry_price = _safe_float(
            entry_price
        )

        quantity = _safe_float(
            quantity
        )

        take_profit = _safe_float(
            take_profit
        )

        stop_loss = _safe_float(
            stop_loss
        )

        if (
            entry_price <= 0
            or quantity <= 0
            or take_profit <= 0
            or stop_loss <= 0
        ):

            return {
                "status":
                    "SKIPPED",

                "reason":
                    "Invalid trade parameters",
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
                    INSERT INTO paper_positions (
                        slot,
                        asset_class,
                        symbol,
                        side,
                        entry_price,
                        quantity,
                        take_profit,
                        stop_loss,
                        opened_at,
                        updated_at
                    )
                    VALUES (
                        %s,
                        %s,
                        %s,
                        %s,
                        %s,
                        %s,
                        %s,
                        %s,
                        %s,
                        %s
                    )
                    """,
                    (
                        slot,
                        asset_class,
                        symbol,
                        side,
                        entry_price,
                        quantity,
                        take_profit,
                        stop_loss,
                        opened_at,
                        opened_at,
                    ),
                )

            conn.commit()

        position = self.get_position(
            slot
        )

        print(
            "[POSTGRES PAPER] "
            f"Position opened | "
            f"Slot={slot} | "
            f"Symbol={symbol} | "
            f"Side={side}",
            flush=True,
        )

        return {
            "status":
                "EXECUTED",

            "mode":
                "PAPER",

            "slot":
                slot,

            "asset_class":
                asset_class,

            "position":
                position,
        }


    # ========================================================
    # UPDATE ONE POSITION PRICE
    # ========================================================

    def update_price(
        self,
        current_price,
        slot=CRYPTO_SLOT,
    ):

        """
        Backward compatible:

            update_price(price)

        monitors CRYPTO_MAIN.

        Metals:

            update_price(
                price,
                slot="METALS_MAIN"
            )
        """

        slot = _normalize_slot(
            slot
        )

        position = self.get_position(
            slot
        )

        if position is None:

            return None

        current_price = _safe_float(
            current_price
        )

        if current_price <= 0:

            return {
                "status":
                    "INVALID PRICE",

                "slot":
                    slot,

                "position":
                    position,
            }

        exit_reason = None

        if position[
            "side"
        ] == "LONG":

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

        elif position[
            "side"
        ] == "SHORT":

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
                "status":
                    "OPEN",

                "slot":
                    slot,

                "position":
                    position,

                "current_price":
                    current_price,
            }

        return self.close_trade(
            exit_price=current_price,
            reason=exit_reason,
            slot=slot,
        )


    # ========================================================
    # CLOSE ONE TRADE
    # ========================================================

    def close_trade(
        self,
        exit_price,
        reason="MANUAL",
        slot=CRYPTO_SLOT,
    ):

        slot = _normalize_slot(
            slot
        )

        position = self.get_position(
            slot
        )

        if position is None:

            return {
                "status":
                    "SKIPPED",

                "reason":
                    (
                        f"No open position "
                        f"in {slot}"
                    ),
            }

        exit_price = _safe_float(
            exit_price
        )

        if exit_price <= 0:

            return {
                "status":
                    "SKIPPED",

                "reason":
                    "Invalid exit price",
            }

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

        old_balance = (
            self.get_balance()
        )

        new_balance = (
            old_balance
            + pnl
        )

        closed_at = datetime.now(
            timezone.utc
        )

        with self._connect() as conn:

            with conn.cursor() as cur:

                # --------------------------------------------
                # ACCOUNT
                # --------------------------------------------

                cur.execute(
                    """
                    UPDATE paper_account
                    SET
                        balance = %s,
                        updated_at = %s
                    WHERE id = 1
                    """,
                    (
                        new_balance,
                        closed_at,
                    ),
                )

                # --------------------------------------------
                # HISTORY
                # --------------------------------------------

                cur.execute(
                    """
                    INSERT INTO paper_trades (
                        slot,
                        asset_class,
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
                        %s,
                        %s,
                        %s,
                        %s,
                        %s,
                        %s,
                        %s,
                        %s,
                        %s,
                        %s,
                        %s,
                        %s,
                        %s,
                        %s
                    )
                    """,
                    (
                        slot,
                        position[
                            "asset_class"
                        ],
                        position[
                            "symbol"
                        ],
                        position[
                            "side"
                        ],
                        position[
                            "entry_price"
                        ],
                        exit_price,
                        position[
                            "quantity"
                        ],
                        position[
                            "take_profit"
                        ],
                        position[
                            "stop_loss"
                        ],
                        pnl,
                        reason,
                        new_balance,
                        position[
                            "opened_at"
                        ],
                        closed_at,
                    ),
                )

                # --------------------------------------------
                # REMOVE ONLY THIS SLOT
                # --------------------------------------------

                cur.execute(
                    """
                    DELETE FROM paper_positions
                    WHERE slot = %s
                    """,
                    (
                        slot,
                    ),
                )

                # --------------------------------------------
                # LEGACY TABLE CLEANUP
                #
                # If Crypto position closes, delete the old
                # legacy record too so it cannot be migrated
                # again on a future restart.
                # --------------------------------------------

                if slot == CRYPTO_SLOT:

                    cur.execute(
                        """
                        DELETE FROM paper_position
                        WHERE id = 1
                        """
                    )

            conn.commit()

        result = {
            "status":
                "CLOSED",

            "slot":
                slot,

            "asset_class":
                position[
                    "asset_class"
                ],

            "symbol":
                position[
                    "symbol"
                ],

            "side":
                position[
                    "side"
                ],

            "entry_price":
                position[
                    "entry_price"
                ],

            "exit_price":
                exit_price,

            "quantity":
                position[
                    "quantity"
                ],

            "take_profit":
                position[
                    "take_profit"
                ],

            "stop_loss":
                position[
                    "stop_loss"
                ],

            "pnl":
                float(
                    pnl
                ),

            "reason":
                reason,

            "balance":
                float(
                    new_balance
                ),

            "opened_at":
                position[
                    "opened_at"
                ],

            "closed_at":
                closed_at.isoformat(),
        }

        print(
            "[POSTGRES PAPER] "
            f"Trade closed | "
            f"Slot={slot} | "
            f"Symbol="
            f"{position['symbol']} | "
            f"PnL={pnl:.2f} | "
            f"Balance={new_balance:.2f}",
            flush=True,
        )

        return result


    # ========================================================
    # CLOSE BY SYMBOL
    # ========================================================

    def close_symbol(
        self,
        symbol,
        exit_price,
        reason="MANUAL",
    ):

        symbol = _normalize_symbol(
            symbol
        )

        slot = _infer_slot(
            symbol
        )

        position = self.get_position(
            slot
        )

        if (
            not position
            or position.get(
                "symbol"
            ) != symbol
        ):

            return {
                "status":
                    "SKIPPED",

                "reason":
                    (
                        f"No open {symbol} "
                        f"position"
                    ),
            }

        return self.close_trade(
            exit_price=exit_price,
            reason=reason,
            slot=slot,
        )


    # ========================================================
    # TRADE HISTORY
    # ========================================================

    def get_trade_history(
        self,
        asset_class=None,
        slot=None,
    ):

        query = """
            SELECT
                id,
                slot,
                asset_class,
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
        """

        conditions = []
        params = []

        if asset_class:

            conditions.append(
                "asset_class = %s"
            )

            params.append(
                str(
                    asset_class
                ).upper()
            )

        if slot:

            slot = _normalize_slot(
                slot
            )

            conditions.append(
                "slot = %s"
            )

            params.append(
                slot
            )

        if conditions:

            query += (
                " WHERE "
                + " AND ".join(
                    conditions
                )
            )

        query += (
            " ORDER BY id DESC"
        )

        with self._connect() as conn:

            with conn.cursor() as cur:

                cur.execute(
                    query,
                    tuple(
                        params
                    ),
                )

                rows = cur.fetchall()

        history = []

        for row in rows:

            row_slot = (
                row.get(
                    "slot"
                )
                or CRYPTO_SLOT
            )

            row_asset = (
                row.get(
                    "asset_class"
                )
                or _infer_asset_class(
                    row[
                        "symbol"
                    ]
                )
            )

            history.append(
                {
                    "id":
                        row[
                            "id"
                        ],

                    "slot":
                        row_slot,

                    "asset_class":
                        row_asset,

                    "symbol":
                        row[
                            "symbol"
                        ],

                    "side":
                        row[
                            "side"
                        ],

                    "entry_price":
                        float(
                            row[
                                "entry_price"
                            ]
                        ),

                    "exit_price":
                        float(
                            row[
                                "exit_price"
                            ]
                        ),

                    "quantity":
                        float(
                            row[
                                "quantity"
                            ]
                        ),

                    "take_profit":
                        float(
                            row[
                                "take_profit"
                            ]
                        ),

                    "stop_loss":
                        float(
                            row[
                                "stop_loss"
                            ]
                        ),

                    "pnl":
                        float(
                            row[
                                "pnl"
                            ]
                        ),

                    "reason":
                        row[
                            "reason"
                        ],

                    "balance":
                        float(
                            row[
                                "balance_after"
                            ]
                        ),

                    "opened_at":
                        (
                            row[
                                "opened_at"
                            ].isoformat()
                            if row[
                                "opened_at"
                            ]
                            else None
                        ),

                    "closed_at":
                        row[
                            "closed_at"
                        ].isoformat(),
                }
            )

        return history


    # ========================================================
    # PORTFOLIO SNAPSHOT
    # ========================================================

    def get_portfolio_snapshot(self):

        crypto = self.get_position(
            CRYPTO_SLOT
        )

        metals = self.get_position(
            METALS_SLOT
        )

        positions = [
            position
            for position in (
                crypto,
                metals,
            )
            if position
        ]

        return {
            "balance":
                self.get_balance(),

            "open_positions":
                positions,

            "open_position_count":
                len(
                    positions
                ),

            "crypto_position":
                crypto,

            "metals_position":
                metals,

            "crypto_slot_available":
                crypto is None,

            "metals_slot_available":
                metals is None,

            "max_crypto_positions":
                1,

            "max_metals_positions":
                1,

            "max_total_positions":
                2,

            "real_orders_enabled":
                False,
        }


    # ========================================================
    # RESET
    # TESTING ONLY
    # ========================================================

    def reset(
        self,
        starting_balance=None,
    ):

        if starting_balance is None:

            starting_balance = (
                self.starting_balance
            )

        now = datetime.now(
            timezone.utc
        )

        with self._connect() as conn:

            with conn.cursor() as cur:

                cur.execute(
                    """
                    DELETE FROM paper_positions
                    """
                )

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
                    SET
                        balance = %s,
                        starting_balance = %s,
                        updated_at = %s
                    WHERE id = 1
                    """,
                    (
                        float(
                            starting_balance
                        ),
                        float(
                            starting_balance
                        ),
                        now,
                    ),
                )

            conn.commit()

        return {
            "status":
                "RESET",

            "balance":
                float(
                    starting_balance
                ),

            "positions":
                [],
        }

"""
trade_lifecycle_engine.py

PRO AI QUANT TERMINAL V5
AUTONOMOUS MULTI-ASSET TRADE LIFECYCLE ENGINE V1.0

Purpose
-------
Central lifecycle management for existing PAPER positions.

Supported now:
    - CRYPTO
    - METALS

Future-ready:
    - STOCKS
    - FX
    - INDICES
    - FUTURES / CFDs

Architecture
------------
PaperTrader open position
        ↓
Existing TP / SL engine
        ↓
Trade Lifecycle Engine
        ↓
Persistent PostgreSQL lifecycle state
        ↓
HOLD / BREAK_EVEN / TRAIL / STALE_EXIT / TIME_EXIT
        ↓
PaperTrader.close_trade()

Core goals
----------
- No zombie trades lasting for days
- Default maximum hold = 24 hours
- Existing TP / SL remains first authority
- Break-even protection
- Risk-normalized trailing protection
- Stale / no-progress exit
- Persistent MFE / MAE tracking
- Restart-safe
- Audit every lifecycle decision
- One-runtime PostgreSQL advisory-lock support
- Asset-agnostic R-multiple architecture
- PAPER ONLY
- REAL ORDERS HARD DISABLED

Important
---------
This engine DOES NOT open trades.

It only manages already-open PAPER positions.

No additional paid Render Background Worker is required.
"""

from __future__ import annotations

import math
import os
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional, Tuple

import psycopg
from psycopg.rows import dict_row

from paper_trader import (
    CRYPTO_SLOT,
    METALS_SLOT,
)


# ============================================================
# VERSION
# ============================================================

ENGINE_VERSION = "V1.0 Trade Lifecycle Engine"


# ============================================================
# HARD SAFETY
# ============================================================

PAPER_ONLY = True
REAL_EXECUTION_ENABLED = False


# ============================================================
# DATABASE
# ============================================================

DATABASE_URL = os.environ.get(
    "DATABASE_URL",
    "",
).strip()


# ============================================================
# RUNTIME LOCK
# ============================================================

LIFECYCLE_RUNTIME_LOCK_ID = 93739002


# ============================================================
# CONFIG HELPERS
# ============================================================

def _env_float(
    name: str,
    default: float,
    *,
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

    if (
        minimum is not None
        and value < minimum
    ):

        value = minimum

    if (
        maximum is not None
        and value > maximum
    ):

        value = maximum

    return value


def _env_int(
    name: str,
    default: int,
    *,
    minimum: Optional[int] = None,
    maximum: Optional[int] = None,
) -> int:

    raw = os.environ.get(
        name,
        str(default),
    )

    try:

        value = int(
            raw
        )

    except (
        TypeError,
        ValueError,
    ):

        value = int(
            default
        )

    if (
        minimum is not None
        and value < minimum
    ):

        value = minimum

    if (
        maximum is not None
        and value > maximum
    ):

        value = maximum

    return value


# ============================================================
# LIFECYCLE CONFIG
# ============================================================

MAX_HOLD_HOURS = _env_float(
    "TRADE_MAX_HOLD_HOURS",
    24.0,
    minimum=1.0,
    maximum=168.0,
)


# Break-even activates after trade reaches this many R.
BREAK_EVEN_TRIGGER_R = _env_float(
    "TRADE_BREAK_EVEN_TRIGGER_R",
    0.75,
    minimum=0.10,
    maximum=10.0,
)


# Small positive buffer beyond entry once BE activates.
BREAK_EVEN_BUFFER_R = _env_float(
    "TRADE_BREAK_EVEN_BUFFER_R",
    0.05,
    minimum=0.0,
    maximum=2.0,
)


# Trailing begins only after stronger favorable movement.
TRAILING_TRIGGER_R = _env_float(
    "TRADE_TRAILING_TRIGGER_R",
    1.25,
    minimum=0.20,
    maximum=20.0,
)


# Virtual stop trails this far behind best favorable move.
TRAILING_DISTANCE_R = _env_float(
    "TRADE_TRAILING_DISTANCE_R",
    0.75,
    minimum=0.10,
    maximum=10.0,
)


# Stale trade management.
STALE_EXIT_ENABLED = (
    os.environ.get(
        "TRADE_STALE_EXIT_ENABLED",
        "true",
    )
    .strip()
    .lower()
    in (
        "1",
        "true",
        "yes",
        "on",
    )
)


# Do not classify a fresh trade as stale too quickly.
STALE_MIN_AGE_HOURS = _env_float(
    "TRADE_STALE_MIN_AGE_HOURS",
    8.0,
    minimum=1.0,
    maximum=72.0,
)


# Trade must show no new favorable progress for this long.
STALE_NO_PROGRESS_HOURS = _env_float(
    "TRADE_STALE_NO_PROGRESS_HOURS",
    4.0,
    minimum=1.0,
    maximum=72.0,
)


# If best favorable excursion never exceeds this R,
# trade is considered weak / stagnant.
STALE_MAX_MFE_R = _env_float(
    "TRADE_STALE_MAX_MFE_R",
    0.40,
    minimum=0.0,
    maximum=10.0,
)


# Stale trade is only exited if current result is not
# meaningfully positive.
STALE_MAX_CURRENT_R = _env_float(
    "TRADE_STALE_MAX_CURRENT_R",
    0.15,
    minimum=-10.0,
    maximum=10.0,
)


# Improvement threshold before last_progress_at updates.
PROGRESS_EPSILON_R = _env_float(
    "TRADE_PROGRESS_EPSILON_R",
    0.05,
    minimum=0.001,
    maximum=5.0,
)


# Safety polling recommendation for caller runtime.
RECOMMENDED_CYCLE_SECONDS = _env_int(
    "TRADE_LIFECYCLE_CYCLE_SECONDS",
    60,
    minimum=15,
    maximum=900,
)


# ============================================================
# BASIC HELPERS
# ============================================================

def _utc_now() -> datetime:

    return datetime.now(
        timezone.utc
    )


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


def _safe_positive_float(
    value,
    default=0.0,
) -> float:

    number = _safe_float(
        value,
        default,
    )

    if number <= 0:

        return default

    return number


def _parse_datetime(
    value,
) -> Optional[datetime]:

    if not value:

        return None

    if isinstance(
        value,
        datetime,
    ):

        dt = value

    else:

        try:

            dt = datetime.fromisoformat(
                str(
                    value
                ).replace(
                    "Z",
                    "+00:00",
                )
            )

        except Exception:

            return None

    if dt.tzinfo is None:

        dt = dt.replace(
            tzinfo=timezone.utc
        )

    return dt.astimezone(
        timezone.utc
    )


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


def _normalize_asset_class(
    asset_class,
) -> str:

    value = (
        str(
            asset_class
            or ""
        )
        .upper()
        .strip()
    )

    aliases = {
        "METALS":
            "METAL",

        "FOREX":
            "FX",

        "EQUITIES":
            "STOCK",

        "EQUITY":
            "STOCK",

        "INDICES":
            "INDEX",

        "FUTURE":
            "FUTURES",
    }

    return aliases.get(
        value,
        value,
    )


def _normalize_side(
    value,
) -> Optional[str]:

    if value is None:

        return None

    text = (
        str(
            value
        )
        .upper()
        .strip()
    )

    aliases = {
        "BUY":
            "LONG",

        "LONG":
            "LONG",

        "SELL":
            "SHORT",

        "SHORT":
            "SHORT",
    }

    return aliases.get(
        text
    )


# ============================================================
# DATABASE
# ============================================================

def _connect():

    if not DATABASE_URL:

        raise RuntimeError(
            "DATABASE_URL is not configured."
        )

    return psycopg.connect(
        DATABASE_URL,
        row_factory=dict_row,
        connect_timeout=10,
    )


# ============================================================
# DATABASE SCHEMA
# ============================================================

def ensure_lifecycle_tables():

    if not DATABASE_URL:

        return

    with _connect() as conn:

        with conn.cursor() as cur:

            # ------------------------------------------------
            # CURRENT LIFECYCLE STATE
            # ------------------------------------------------

            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS
                trade_lifecycle_state (

                    lifecycle_key TEXT PRIMARY KEY,

                    slot TEXT NOT NULL,

                    asset_class TEXT,

                    symbol TEXT NOT NULL,

                    side TEXT,

                    entry_price DOUBLE PRECISION,

                    original_stop DOUBLE PRECISION,

                    initial_risk_per_unit DOUBLE PRECISION,

                    virtual_stop DOUBLE PRECISION,

                    best_price DOUBLE PRECISION,

                    worst_price DOUBLE PRECISION,

                    mfe_r DOUBLE PRECISION
                        NOT NULL
                        DEFAULT 0,

                    mae_r DOUBLE PRECISION
                        NOT NULL
                        DEFAULT 0,

                    first_seen_at TIMESTAMPTZ
                        NOT NULL
                        DEFAULT NOW(),

                    opened_at TIMESTAMPTZ,

                    last_progress_at TIMESTAMPTZ
                        NOT NULL
                        DEFAULT NOW(),

                    last_evaluated_at TIMESTAMPTZ
                        NOT NULL
                        DEFAULT NOW(),

                    break_even_active BOOLEAN
                        NOT NULL
                        DEFAULT FALSE,

                    trailing_active BOOLEAN
                        NOT NULL
                        DEFAULT FALSE,

                    status TEXT
                        NOT NULL
                        DEFAULT 'OPEN',

                    last_action TEXT,

                    updated_at TIMESTAMPTZ
                        NOT NULL
                        DEFAULT NOW()
                )
                """
            )

            # ------------------------------------------------
            # DECISION / EVENT AUDIT
            # ------------------------------------------------

            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS
                trade_lifecycle_events (

                    id BIGSERIAL PRIMARY KEY,

                    lifecycle_key TEXT,

                    slot TEXT,

                    asset_class TEXT,

                    symbol TEXT,

                    side TEXT,

                    event_type TEXT NOT NULL,

                    reason TEXT,

                    price DOUBLE PRECISION,

                    current_r DOUBLE PRECISION,

                    mfe_r DOUBLE PRECISION,

                    mae_r DOUBLE PRECISION,

                    virtual_stop DOUBLE PRECISION,

                    hold_hours DOUBLE PRECISION,

                    created_at TIMESTAMPTZ
                        NOT NULL
                        DEFAULT NOW()
                )
                """
            )

            cur.execute(
                """
                CREATE INDEX IF NOT EXISTS
                idx_trade_lifecycle_events_time

                ON trade_lifecycle_events (
                    created_at DESC
                )
                """
            )

            cur.execute(
                """
                CREATE INDEX IF NOT EXISTS
                idx_trade_lifecycle_events_symbol

                ON trade_lifecycle_events (
                    symbol,
                    created_at DESC
                )
                """
            )

        conn.commit()


# ============================================================
# RUNTIME ADVISORY LOCK
# ============================================================

def acquire_lifecycle_runtime_lock():

    """
    Returns a live PostgreSQL connection if lock acquired.

    Caller MUST keep this connection alive while lifecycle
    runtime is active.

    Returns None when another runtime owns the lock.
    """

    if not DATABASE_URL:

        raise RuntimeError(
            "DATABASE_URL is not configured."
        )

    connection = psycopg.connect(
        DATABASE_URL,
        autocommit=True,
        connect_timeout=10,
    )

    try:

        with connection.cursor() as cur:

            cur.execute(
                """
                SELECT pg_try_advisory_lock(%s)
                """,
                (
                    LIFECYCLE_RUNTIME_LOCK_ID,
                ),
            )

            row = cur.fetchone()

        acquired = bool(
            row
            and row[0]
        )

        if not acquired:

            connection.close()

            return None

        return connection

    except Exception:

        try:

            connection.close()

        except Exception:

            pass

        raise


def release_lifecycle_runtime_lock(
    connection,
):

    if connection is None:

        return

    try:

        with connection.cursor() as cur:

            cur.execute(
                """
                SELECT pg_advisory_unlock(%s)
                """,
                (
                    LIFECYCLE_RUNTIME_LOCK_ID,
                ),
            )

    except Exception:

        pass

    try:

        connection.close()

    except Exception:

        pass


# ============================================================
# POSITION KEY
# ============================================================

def _position_key(
    position: Dict,
) -> str:

    slot = str(
        position.get(
            "slot"
        )
        or "UNKNOWN"
    )

    symbol = _normalize_symbol(
        position.get(
            "symbol"
        )
    )

    opened_at = str(
        position.get(
            "opened_at"
        )
        or "UNKNOWN"
    )

    return (
        f"{slot}|"
        f"{symbol}|"
        f"{opened_at}"
    )


# ============================================================
# EVENT AUDIT
# ============================================================

def _record_event(
    *,
    lifecycle_key: str,
    position: Dict,
    event_type: str,
    reason: str = "",
    price: Optional[float] = None,
    current_r: Optional[float] = None,
    mfe_r: Optional[float] = None,
    mae_r: Optional[float] = None,
    virtual_stop: Optional[float] = None,
    hold_hours: Optional[float] = None,
):

    if not DATABASE_URL:

        return

    try:

        ensure_lifecycle_tables()

        with _connect() as conn:

            with conn.cursor() as cur:

                cur.execute(
                    """
                    INSERT INTO
                    trade_lifecycle_events (

                        lifecycle_key,
                        slot,
                        asset_class,
                        symbol,
                        side,
                        event_type,
                        reason,
                        price,
                        current_r,
                        mfe_r,
                        mae_r,
                        virtual_stop,
                        hold_hours
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
                        %s
                    )
                    """,
                    (
                        lifecycle_key,

                        position.get(
                            "slot"
                        ),

                        _normalize_asset_class(
                            position.get(
                                "asset_class"
                            )
                        ),

                        _normalize_symbol(
                            position.get(
                                "symbol"
                            )
                        ),

                        _normalize_side(
                            position.get(
                                "side"
                            )
                            or position.get(
                                "signal"
                            )
                        ),

                        str(
                            event_type
                        ),

                        str(
                            reason
                        ),

                        price,

                        current_r,

                        mfe_r,

                        mae_r,

                        virtual_stop,

                        hold_hours,
                    ),
                )

            conn.commit()

    except Exception:

        # Observability must never stop position management.
        pass


# ============================================================
# LOAD STATE
# ============================================================

def _load_state(
    lifecycle_key: str,
) -> Optional[Dict]:

    if not DATABASE_URL:

        return None

    ensure_lifecycle_tables()

    with _connect() as conn:

        with conn.cursor() as cur:

            cur.execute(
                """
                SELECT *

                FROM trade_lifecycle_state

                WHERE lifecycle_key = %s
                """,
                (
                    lifecycle_key,
                ),
            )

            return cur.fetchone()


# ============================================================
# UPSERT STATE
# ============================================================

def _save_state(
    state: Dict,
):

    if not DATABASE_URL:

        return

    ensure_lifecycle_tables()

    with _connect() as conn:

        with conn.cursor() as cur:

            cur.execute(
                """
                INSERT INTO
                trade_lifecycle_state (

                    lifecycle_key,
                    slot,
                    asset_class,
                    symbol,
                    side,
                    entry_price,
                    original_stop,
                    initial_risk_per_unit,
                    virtual_stop,
                    best_price,
                    worst_price,
                    mfe_r,
                    mae_r,
                    first_seen_at,
                    opened_at,
                    last_progress_at,
                    last_evaluated_at,
                    break_even_active,
                    trailing_active,
                    status,
                    last_action,
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
                    NOW()
                )

                ON CONFLICT (
                    lifecycle_key
                )

                DO UPDATE SET

                    virtual_stop =
                        EXCLUDED.virtual_stop,

                    best_price =
                        EXCLUDED.best_price,

                    worst_price =
                        EXCLUDED.worst_price,

                    mfe_r =
                        EXCLUDED.mfe_r,

                    mae_r =
                        EXCLUDED.mae_r,

                    last_progress_at =
                        EXCLUDED.last_progress_at,

                    last_evaluated_at =
                        EXCLUDED.last_evaluated_at,

                    break_even_active =
                        EXCLUDED.break_even_active,

                    trailing_active =
                        EXCLUDED.trailing_active,

                    status =
                        EXCLUDED.status,

                    last_action =
                        EXCLUDED.last_action,

                    updated_at =
                        NOW()
                """,
                (
                    state[
                        "lifecycle_key"
                    ],

                    state[
                        "slot"
                    ],

                    state[
                        "asset_class"
                    ],

                    state[
                        "symbol"
                    ],

                    state[
                        "side"
                    ],

                    state[
                        "entry_price"
                    ],

                    state[
                        "original_stop"
                    ],

                    state[
                        "initial_risk_per_unit"
                    ],

                    state[
                        "virtual_stop"
                    ],

                    state[
                        "best_price"
                    ],

                    state[
                        "worst_price"
                    ],

                    state[
                        "mfe_r"
                    ],

                    state[
                        "mae_r"
                    ],

                    state[
                        "first_seen_at"
                    ],

                    state[
                        "opened_at"
                    ],

                    state[
                        "last_progress_at"
                    ],

                    state[
                        "last_evaluated_at"
                    ],

                    state[
                        "break_even_active"
                    ],

                    state[
                        "trailing_active"
                    ],

                    state[
                        "status"
                    ],

                    state[
                        "last_action"
                    ],
                ),
            )

        conn.commit()


# ============================================================
# NEW LIFECYCLE STATE
# ============================================================

def _create_state(
    position: Dict,
) -> Dict:

    now = _utc_now()

    lifecycle_key = (
        _position_key(
            position
        )
    )

    entry = _safe_positive_float(
        position.get(
            "entry_price"
        )
    )

    original_stop = _safe_positive_float(
        position.get(
            "stop_loss"
        )
    )

    side = _normalize_side(
        position.get(
            "side"
        )
        or position.get(
            "signal"
        )
    )

    opened_at = _parse_datetime(
        position.get(
            "opened_at"
        )
    )

    if opened_at is None:

        opened_at = now

    initial_risk = abs(
        entry
        - original_stop
    )

    state = {
        "lifecycle_key":
            lifecycle_key,

        "slot":
            str(
                position.get(
                    "slot"
                )
                or ""
            ),

        "asset_class":
            _normalize_asset_class(
                position.get(
                    "asset_class"
                )
            ),

        "symbol":
            _normalize_symbol(
                position.get(
                    "symbol"
                )
            ),

        "side":
            side,

        "entry_price":
            entry,

        "original_stop":
            original_stop,

        "initial_risk_per_unit":
            initial_risk,

        "virtual_stop":
            original_stop,

        "best_price":
            entry,

        "worst_price":
            entry,

        "mfe_r":
            0.0,

        "mae_r":
            0.0,

        "first_seen_at":
            now,

        "opened_at":
            opened_at,

        "last_progress_at":
            now,

        "last_evaluated_at":
            now,

        "break_even_active":
            False,

        "trailing_active":
            False,

        "status":
            "OPEN",

        "last_action":
            "INITIALIZED",
    }

    _save_state(
        state
    )

    _record_event(
        lifecycle_key=
            lifecycle_key,

        position=
            position,

        event_type=
            "INITIALIZED",

        reason=
            "Lifecycle state created.",
    )

    return state


# ============================================================
# ENSURE STATE
# ============================================================

def _ensure_state(
    position: Dict,
) -> Dict:

    key = (
        _position_key(
            position
        )
    )

    try:

        existing = (
            _load_state(
                key
            )
        )

    except Exception:

        existing = None

    if existing:

        return dict(
            existing
        )

    return _create_state(
        position
    )


# ============================================================
# MARKET PRICE ADAPTER
# ============================================================

def _get_current_price(
    position: Dict,
) -> Optional[float]:

    symbol = _normalize_symbol(
        position.get(
            "symbol"
        )
    )

    asset_class = _normalize_asset_class(
        position.get(
            "asset_class"
        )
    )

    try:

        if asset_class == "METAL":

            from metals_trade_engine import (
                get_metals_current_price,
            )

            price = (
                get_metals_current_price(
                    symbol
                )
            )

        else:

            from trade_engine import (
                get_current_price,
            )

            price = (
                get_current_price(
                    symbol
                )
            )

        price = _safe_positive_float(
            price
        )

        if price <= 0:

            return None

        return price

    except Exception:

        return None


# ============================================================
# POSITION AGE
# ============================================================

def _position_age_hours(
    state: Dict,
) -> float:

    opened_at = _parse_datetime(
        state.get(
            "opened_at"
        )
    )

    if opened_at is None:

        opened_at = _parse_datetime(
            state.get(
                "first_seen_at"
            )
        )

    if opened_at is None:

        return 0.0

    age = (
        _utc_now()
        - opened_at
    ).total_seconds()

    return max(
        0.0,
        age / 3600.0,
    )


# ============================================================
# R MULTIPLE
# ============================================================

def _current_r(
    *,
    side: str,
    entry: float,
    current_price: float,
    initial_risk: float,
) -> float:

    if initial_risk <= 0:

        return 0.0

    if side == "LONG":

        return (
            current_price
            - entry
        ) / initial_risk

    if side == "SHORT":

        return (
            entry
            - current_price
        ) / initial_risk

    return 0.0


# ============================================================
# UPDATE MFE / MAE
# ============================================================

def _update_excursions(
    state: Dict,
    current_price: float,
) -> Dict:

    now = _utc_now()

    side = state.get(
        "side"
    )

    entry = _safe_positive_float(
        state.get(
            "entry_price"
        )
    )

    risk = _safe_positive_float(
        state.get(
            "initial_risk_per_unit"
        )
    )

    best = _safe_positive_float(
        state.get(
            "best_price"
        ),
        entry,
    )

    worst = _safe_positive_float(
        state.get(
            "worst_price"
        ),
        entry,
    )

    previous_mfe = _safe_float(
        state.get(
            "mfe_r"
        )
    )

    if side == "LONG":

        best = max(
            best,
            current_price,
        )

        worst = min(
            worst,
            current_price,
        )

        mfe_r = (
            (
                best
                - entry
            )
            / risk
            if risk > 0
            else 0.0
        )

        mae_r = (
            (
                entry
                - worst
            )
            / risk
            if risk > 0
            else 0.0
        )

    elif side == "SHORT":

        best = min(
            best,
            current_price,
        )

        worst = max(
            worst,
            current_price,
        )

        mfe_r = (
            (
                entry
                - best
            )
            / risk
            if risk > 0
            else 0.0
        )

        mae_r = (
            (
                worst
                - entry
            )
            / risk
            if risk > 0
            else 0.0
        )

    else:

        mfe_r = 0.0
        mae_r = 0.0

    mfe_r = max(
        0.0,
        mfe_r,
    )

    mae_r = max(
        0.0,
        mae_r,
    )

    last_progress_at = (
        state.get(
            "last_progress_at"
        )
    )

    if (
        mfe_r
        >= previous_mfe
        + PROGRESS_EPSILON_R
    ):

        last_progress_at = now

    state[
        "best_price"
    ] = best

    state[
        "worst_price"
    ] = worst

    state[
        "mfe_r"
    ] = mfe_r

    state[
        "mae_r"
    ] = mae_r

    state[
        "last_progress_at"
    ] = last_progress_at

    state[
        "last_evaluated_at"
    ] = now

    return state


# ============================================================
# VIRTUAL STOP ENGINE
# ============================================================

def _calculate_virtual_stop(
    state: Dict,
) -> Tuple[
    float,
    bool,
    bool,
]:

    side = state.get(
        "side"
    )

    entry = _safe_positive_float(
        state.get(
            "entry_price"
        )
    )

    risk = _safe_positive_float(
        state.get(
            "initial_risk_per_unit"
        )
    )

    original_stop = _safe_positive_float(
        state.get(
            "original_stop"
        )
    )

    best = _safe_positive_float(
        state.get(
            "best_price"
        ),
        entry,
    )

    mfe_r = _safe_float(
        state.get(
            "mfe_r"
        )
    )

    virtual_stop = _safe_positive_float(
        state.get(
            "virtual_stop"
        ),
        original_stop,
    )

    break_even_active = bool(
        state.get(
            "break_even_active"
        )
    )

    trailing_active = bool(
        state.get(
            "trailing_active"
        )
    )

    if (
        entry <= 0
        or risk <= 0
        or original_stop <= 0
        or side not in (
            "LONG",
            "SHORT",
        )
    ):

        return (
            virtual_stop,
            break_even_active,
            trailing_active,
        )

    # --------------------------------------------------------
    # BREAK EVEN
    # --------------------------------------------------------

    if (
        mfe_r
        >= BREAK_EVEN_TRIGGER_R
    ):

        break_even_active = True

        if side == "LONG":

            break_even_stop = (
                entry
                + (
                    BREAK_EVEN_BUFFER_R
                    * risk
                )
            )

            virtual_stop = max(
                virtual_stop,
                break_even_stop,
            )

        else:

            break_even_stop = (
                entry
                - (
                    BREAK_EVEN_BUFFER_R
                    * risk
                )
            )

            virtual_stop = min(
                virtual_stop,
                break_even_stop,
            )

    # --------------------------------------------------------
    # TRAILING
    # --------------------------------------------------------

    if (
        mfe_r
        >= TRAILING_TRIGGER_R
    ):

        trailing_active = True

        if side == "LONG":

            trailing_stop = (
                best
                - (
                    TRAILING_DISTANCE_R
                    * risk
                )
            )

            virtual_stop = max(
                virtual_stop,
                trailing_stop,
            )

        else:

            trailing_stop = (
                best
                + (
                    TRAILING_DISTANCE_R
                    * risk
                )
            )

            virtual_stop = min(
                virtual_stop,
                trailing_stop,
            )

    return (
        virtual_stop,
        break_even_active,
        trailing_active,
    )


# ============================================================
# VIRTUAL STOP HIT
# ============================================================

def _virtual_stop_hit(
    *,
    side: str,
    current_price: float,
    virtual_stop: float,
) -> bool:

    if (
        current_price <= 0
        or virtual_stop <= 0
    ):

        return False

    if side == "LONG":

        return (
            current_price
            <= virtual_stop
        )

    if side == "SHORT":

        return (
            current_price
            >= virtual_stop
        )

    return False


# ============================================================
# STALE LOGIC
# ============================================================

def _stale_exit_due(
    state: Dict,
    current_r: float,
) -> Dict:

    if not STALE_EXIT_ENABLED:

        return {
            "exit":
                False,
        }

    age_hours = (
        _position_age_hours(
            state
        )
    )

    if (
        age_hours
        < STALE_MIN_AGE_HOURS
    ):

        return {
            "exit":
                False,
        }

    last_progress = _parse_datetime(
        state.get(
            "last_progress_at"
        )
    )

    if last_progress is None:

        return {
            "exit":
                False,
        }

    no_progress_hours = (
        (
            _utc_now()
            - last_progress
        ).total_seconds()
        / 3600.0
    )

    mfe_r = _safe_float(
        state.get(
            "mfe_r"
        )
    )

    stale = (
        no_progress_hours
        >= STALE_NO_PROGRESS_HOURS
        and mfe_r
        <= STALE_MAX_MFE_R
        and current_r
        <= STALE_MAX_CURRENT_R
    )

    return {
        "exit":
            stale,

        "age_hours":
            age_hours,

        "no_progress_hours":
            no_progress_hours,

        "mfe_r":
            mfe_r,

        "current_r":
            current_r,
    }


# ============================================================
# PAPER CLOSE
# ============================================================

def _close_position(
    trader,
    *,
    position: Dict,
    current_price: float,
    reason: str,
) -> Dict:

    if (
        not PAPER_ONLY
        or REAL_EXECUTION_ENABLED
    ):

        return {
            "status":
                "BLOCKED",

            "reason":
                "Real execution hard locked.",
        }

    slot = position.get(
        "slot"
    )

    try:

        result = trader.close_trade(
            exit_price=
                current_price,

            reason=
                reason,

            slot=
                slot,
        )

        if isinstance(
            result,
            dict,
        ):

            return result

        return {
            "status":
                "UNKNOWN",

            "result":
                result,
        }

    except Exception as error:

        return {
            "status":
                "ERROR",

            "reason":
                str(
                    error
                ),
        }


# ============================================================
# MARK STATE CLOSED
# ============================================================

def _mark_closed(
    state: Dict,
    action: str,
):

    state[
        "status"
    ] = "CLOSED"

    state[
        "last_action"
    ] = action

    state[
        "last_evaluated_at"
    ] = _utc_now()

    _save_state(
        state
    )


# ============================================================
# MANAGE ONE POSITION
# ============================================================

def manage_position(
    trader,
    position: Dict,
) -> Dict:

    lifecycle_key = (
        _position_key(
            position
        )
    )

    state = (
        _ensure_state(
            position
        )
    )

    side = _normalize_side(
        position.get(
            "side"
        )
        or position.get(
            "signal"
        )
        or state.get(
            "side"
        )
    )

    entry = _safe_positive_float(
        position.get(
            "entry_price"
        )
        or state.get(
            "entry_price"
        )
    )

    original_stop = _safe_positive_float(
        position.get(
            "stop_loss"
        )
        or state.get(
            "original_stop"
        )
    )

    initial_risk = _safe_positive_float(
        state.get(
            "initial_risk_per_unit"
        )
    )

    # --------------------------------------------------------
    # STRUCTURE VALIDATION
    # --------------------------------------------------------

    if (
        side not in (
            "LONG",
            "SHORT",
        )
        or entry <= 0
        or original_stop <= 0
        or initial_risk <= 0
    ):

        return {
            "status":
                "INVALID_POSITION",

            "symbol":
                position.get(
                    "symbol"
                ),

            "slot":
                position.get(
                    "slot"
                ),

            "reason":
                "Lifecycle cannot safely determine side/entry/stop.",
        }

    # --------------------------------------------------------
    # CURRENT PRICE
    # --------------------------------------------------------

    current_price = (
        _get_current_price(
            position
        )
    )

    if current_price is None:

        return {
            "status":
                "WAITING_FOR_PRICE",

            "symbol":
                position.get(
                    "symbol"
                ),

            "slot":
                position.get(
                    "slot"
                ),
        }

    # ========================================================
    # EXISTING TP / SL FIRST
    # ========================================================

    try:

        existing_result = (
            trader.update_price(
                current_price=
                    current_price,

                slot=
                    position.get(
                        "slot"
                    ),
            )
        )

    except Exception as error:

        existing_result = {
            "status":
                "ERROR",

            "reason":
                str(
                    error
                ),
        }

    # If PaperTrader already closed at TP/SL, lifecycle stops.
    if (
        isinstance(
            existing_result,
            dict,
        )
        and existing_result.get(
            "status"
        )
        == "CLOSED"
    ):

        _mark_closed(
            state,
            "BASE_TP_SL_CLOSE",
        )

        _record_event(
            lifecycle_key=
                lifecycle_key,

            position=
                position,

            event_type=
                "BASE_TP_SL_CLOSE",

            reason=
                str(
                    existing_result.get(
                        "reason",
                        "Existing TP/SL closed trade",
                    )
                ),

            price=
                current_price,
        )

        return {
            "status":
                "CLOSED",

            "action":
                "BASE_TP_SL_CLOSE",

            "price":
                current_price,

            "result":
                existing_result,
        }

    # Extra confirmation in case update_price closed without
    # returning the expected shape.
    try:

        still_open = (
            trader.get_position(
                position.get(
                    "slot"
                )
            )
        )

    except Exception:

        still_open = position

    if not still_open:

        _mark_closed(
            state,
            "BASE_ENGINE_CLOSE",
        )

        return {
            "status":
                "CLOSED",

            "action":
                "BASE_ENGINE_CLOSE",

            "price":
                current_price,
        }

    # ========================================================
    # UPDATE MFE / MAE
    # ========================================================

    state = _update_excursions(
        state,
        current_price,
    )

    current_r = _current_r(
        side=
            side,

        entry=
            entry,

        current_price=
            current_price,

        initial_risk=
            initial_risk,
    )

    hold_hours = (
        _position_age_hours(
            state
        )
    )

    # ========================================================
    # HARD MAX HOLD — 24H DEFAULT
    # ========================================================

    if (
        hold_hours
        >= MAX_HOLD_HOURS
    ):

        result = _close_position(
            trader,
            position=
                position,
            current_price=
                current_price,
            reason=
                "LIFECYCLE_MAX_HOLD_EXIT",
        )

        if (
            result.get(
                "status"
            )
            != "ERROR"
        ):

            _mark_closed(
                state,
                "TIME_EXIT",
            )

        _record_event(
            lifecycle_key=
                lifecycle_key,

            position=
                position,

            event_type=
                "TIME_EXIT",

            reason=(
                f"Maximum hold "
                f"{MAX_HOLD_HOURS:.1f}h reached."
            ),

            price=
                current_price,

            current_r=
                current_r,

            mfe_r=
                state.get(
                    "mfe_r"
                ),

            mae_r=
                state.get(
                    "mae_r"
                ),

            virtual_stop=
                state.get(
                    "virtual_stop"
                ),

            hold_hours=
                hold_hours,
        )

        return {
            "status":
                "CLOSED",

            "action":
                "TIME_EXIT",

            "symbol":
                state[
                    "symbol"
                ],

            "hold_hours":
                hold_hours,

            "current_r":
                current_r,

            "result":
                result,
        }

    # ========================================================
    # BREAK-EVEN / TRAILING
    # ========================================================

    (
        new_virtual_stop,
        break_even_active,
        trailing_active,
    ) = _calculate_virtual_stop(
        state
    )

    old_virtual_stop = (
        _safe_positive_float(
            state.get(
                "virtual_stop"
            ),
            original_stop,
        )
    )

    virtual_stop_changed = (
        abs(
            new_virtual_stop
            - old_virtual_stop
        )
        > 1e-12
    )

    state[
        "virtual_stop"
    ] = new_virtual_stop

    state[
        "break_even_active"
    ] = break_even_active

    state[
        "trailing_active"
    ] = trailing_active

    if virtual_stop_changed:

        if trailing_active:

            action = "TRAIL"

        elif break_even_active:

            action = "BREAK_EVEN"

        else:

            action = "STOP_UPDATE"

        state[
            "last_action"
        ] = action

        _record_event(
            lifecycle_key=
                lifecycle_key,

            position=
                position,

            event_type=
                action,

            reason=
                "Virtual lifecycle stop tightened.",

            price=
                current_price,

            current_r=
                current_r,

            mfe_r=
                state.get(
                    "mfe_r"
                ),

            mae_r=
                state.get(
                    "mae_r"
                ),

            virtual_stop=
                new_virtual_stop,

            hold_hours=
                hold_hours,
        )

    # ========================================================
    # VIRTUAL STOP EXIT
    # ========================================================

    if _virtual_stop_hit(
        side=
            side,

        current_price=
            current_price,

        virtual_stop=
            new_virtual_stop,
    ):

        reason = (
            "LIFECYCLE_TRAILING_EXIT"
            if trailing_active
            else
            (
                "LIFECYCLE_BREAK_EVEN_EXIT"
                if break_even_active
                else
                "LIFECYCLE_VIRTUAL_STOP_EXIT"
            )
        )

        result = _close_position(
            trader,
            position=
                position,
            current_price=
                current_price,
            reason=
                reason,
        )

        if (
            result.get(
                "status"
            )
            != "ERROR"
        ):

            _mark_closed(
                state,
                reason,
            )

        _record_event(
            lifecycle_key=
                lifecycle_key,

            position=
                position,

            event_type=
                reason,

            reason=
                "Virtual lifecycle stop reached.",

            price=
                current_price,

            current_r=
                current_r,

            mfe_r=
                state.get(
                    "mfe_r"
                ),

            mae_r=
                state.get(
                    "mae_r"
                ),

            virtual_stop=
                new_virtual_stop,

            hold_hours=
                hold_hours,
        )

        return {
            "status":
                "CLOSED",

            "action":
                reason,

            "symbol":
                state[
                    "symbol"
                ],

            "current_r":
                current_r,

            "virtual_stop":
                new_virtual_stop,

            "result":
                result,
        }

    # ========================================================
    # STALE / NO-PROGRESS EXIT
    # ========================================================

    stale = _stale_exit_due(
        state,
        current_r,
    )

    if stale.get(
        "exit",
        False,
    ):

        result = _close_position(
            trader,
            position=
                position,
            current_price=
                current_price,
            reason=
                "LIFECYCLE_STALE_EXIT",
        )

        if (
            result.get(
                "status"
            )
            != "ERROR"
        ):

            _mark_closed(
                state,
                "STALE_EXIT",
            )

        _record_event(
            lifecycle_key=
                lifecycle_key,

            position=
                position,

            event_type=
                "STALE_EXIT",

            reason=(
                "Trade showed insufficient "
                "favorable progress."
            ),

            price=
                current_price,

            current_r=
                current_r,

            mfe_r=
                state.get(
                    "mfe_r"
                ),

            mae_r=
                state.get(
                    "mae_r"
                ),

            virtual_stop=
                new_virtual_stop,

            hold_hours=
                hold_hours,
        )

        return {
            "status":
                "CLOSED",

            "action":
                "STALE_EXIT",

            "symbol":
                state[
                    "symbol"
                ],

            "current_r":
                current_r,

            "stale":
                stale,

            "result":
                result,
        }

    # ========================================================
    # HOLD
    # ========================================================

    state[
        "status"
    ] = "OPEN"

    state[
        "last_action"
    ] = "HOLD"

    _save_state(
        state
    )

    return {
        "status":
            "OPEN",

        "action":
            "HOLD",

        "symbol":
            state[
                "symbol"
            ],

        "slot":
            state[
                "slot"
            ],

        "side":
            side,

        "entry_price":
            entry,

        "current_price":
            current_price,

        "current_r":
            current_r,

        "mfe_r":
            state[
                "mfe_r"
            ],

        "mae_r":
            state[
                "mae_r"
            ],

        "virtual_stop":
            state[
                "virtual_stop"
            ],

        "break_even_active":
            state[
                "break_even_active"
            ],

        "trailing_active":
            state[
                "trailing_active"
            ],

        "hold_hours":
            hold_hours,

        "max_hold_hours":
            MAX_HOLD_HOURS,

        "paper_only":
            True,
    }


# ============================================================
# GET OPEN POSITIONS
# ============================================================

def _get_positions(
    trader,
) -> List[Dict]:

    try:

        positions = (
            trader.get_positions()
        )

    except Exception:

        positions = []

    if not isinstance(
        positions,
        list,
    ):

        return []

    return [
        position
        for position in positions
        if isinstance(
            position,
            dict,
        )
    ]


# ============================================================
# ONE FULL LIFECYCLE CYCLE
# ============================================================

def run_lifecycle_cycle(
    trader,
) -> Dict:

    """
    Run one lifecycle evaluation across every open position.

    Safe to call repeatedly.

    Recommended caller interval:
        ~60 seconds

    This function itself creates no thread.
    """

    if (
        not PAPER_ONLY
        or REAL_EXECUTION_ENABLED
    ):

        return {
            "ok":
                False,

            "status":
                "HARD_LOCK",

            "reason":
                "Real execution is disabled.",
        }

    try:

        ensure_lifecycle_tables()

    except Exception as error:

        return {
            "ok":
                False,

            "status":
                "DATABASE_ERROR",

            "reason":
                str(
                    error
                ),
        }

    positions = _get_positions(
        trader
    )

    if not positions:

        return {
            "ok":
                True,

            "status":
                "FLAT",

            "open_positions":
                0,

            "results":
                [],

            "paper_only":
                True,
        }

    results = []

    errors = []

    for position in positions:

        try:

            result = manage_position(
                trader,
                position,
            )

            results.append(
                result
            )

        except Exception as error:

            item = {
                "status":
                    "ERROR",

                "symbol":
                    position.get(
                        "symbol"
                    ),

                "slot":
                    position.get(
                        "slot"
                    ),

                "reason":
                    str(
                        error
                    ),
            }

            results.append(
                item
            )

            errors.append(
                item
            )

    closed = sum(
        1
        for item in results
        if item.get(
            "status"
        )
        == "CLOSED"
    )

    open_count = sum(
        1
        for item in results
        if item.get(
            "status"
        )
        == "OPEN"
    )

    return {
        "ok":
            len(
                errors
            )
            == 0,

        "status":
            (
                "OK"
                if not errors
                else "DEGRADED"
            ),

        "positions_evaluated":
            len(
                positions
            ),

        "positions_open":
            open_count,

        "positions_closed":
            closed,

        "errors":
            errors,

        "results":
            results,

        "timestamp":
            _utc_now().isoformat(),

        "paper_only":
            True,

        "real_execution":
            False,
    }


# ============================================================
# CURRENT LIFECYCLE SNAPSHOT
# ============================================================

def get_lifecycle_snapshot(
    limit: int = 100,
) -> Dict:

    if not DATABASE_URL:

        return {
            "ok":
                False,

            "reason":
                "DATABASE_URL not configured.",
        }

    ensure_lifecycle_tables()

    limit = max(
        1,
        min(
            int(
                limit
            ),
            500,
        ),
    )

    with _connect() as conn:

        with conn.cursor() as cur:

            cur.execute(
                """
                SELECT *

                FROM trade_lifecycle_state

                ORDER BY updated_at DESC

                LIMIT %s
                """,
                (
                    limit,
                ),
            )

            states = cur.fetchall()

            cur.execute(
                """
                SELECT *

                FROM trade_lifecycle_events

                ORDER BY created_at DESC

                LIMIT %s
                """,
                (
                    limit,
                ),
            )

            events = cur.fetchall()

    return {
        "ok":
            True,

        "engine":
            ENGINE_VERSION,

        "states":
            [
                dict(
                    row
                )
                for row in states
            ],

        "events":
            [
                dict(
                    row
                )
                for row in events
            ],

        "paper_only":
            True,
    }


# ============================================================
# HEALTH
# ============================================================

def trade_lifecycle_health() -> Dict:

    result = {
        "ok":
            True,

        "engine":
            ENGINE_VERSION,

        "paper_only":
            True,

        "real_execution_locked":
            True,

        "max_hold_hours":
            MAX_HOLD_HOURS,

        "break_even_trigger_r":
            BREAK_EVEN_TRIGGER_R,

        "break_even_buffer_r":
            BREAK_EVEN_BUFFER_R,

        "trailing_trigger_r":
            TRAILING_TRIGGER_R,

        "trailing_distance_r":
            TRAILING_DISTANCE_R,

        "stale_exit_enabled":
            STALE_EXIT_ENABLED,

        "stale_min_age_hours":
            STALE_MIN_AGE_HOURS,

        "stale_no_progress_hours":
            STALE_NO_PROGRESS_HOURS,

        "stale_max_mfe_r":
            STALE_MAX_MFE_R,

        "stale_max_current_r":
            STALE_MAX_CURRENT_R,

        "recommended_cycle_seconds":
            RECOMMENDED_CYCLE_SECONDS,

        "runtime_lock_id":
            LIFECYCLE_RUNTIME_LOCK_ID,

        "persistent_state":
            bool(
                DATABASE_URL
            ),

        "mfe_tracking":
            True,

        "mae_tracking":
            True,

        "break_even":
            True,

        "risk_normalized_trailing":
            True,

        "hard_time_stop":
            True,

        "stale_exit":
            STALE_EXIT_ENABLED,

        "restart_safe":
            bool(
                DATABASE_URL
            ),
    }

    if DATABASE_URL:

        try:

            ensure_lifecycle_tables()

            result[
                "database"
            ] = "ONLINE"

        except Exception as error:

            result[
                "ok"
            ] = False

            result[
                "database"
            ] = "ERROR"

            result[
                "reason"
            ] = str(
                error
            )

    else:

        result[
            "database"
        ] = "NOT_CONFIGURED"

    return result

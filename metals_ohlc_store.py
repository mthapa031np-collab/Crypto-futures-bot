"""
metals_ohlc_store.py

PRO AI QUANT TERMINAL V4.3
HYBRID PERSISTENT METALS OHLC ENGINE

============================================================
ARCHITECTURE
============================================================

INITIAL WARM-UP
---------------
Gold-API OHLC
    ↓
Direct real historical seeds:
    15m
    1h
    4h
    ↓
PostgreSQL metals_seed_candles

LONG-TERM LIVE ENGINE
---------------------
Gold-API realtime XAU / XAG
    ↓
PostgreSQL metals_ticks
    ↓
Canonical local 15m candles
    ↓
Local deterministic resampling
    ↓
1h + 4h

HYBRID READER
-------------
15m:
    Historical direct 15m seed
        +
    Live 15m aggregation

1h / 4h:
    Direct real historical seed
        +
    Locally-derived candles from canonical 15m

When timestamps overlap:
    LOCAL_DERIVED wins over DIRECT_SEED

WHY
---
- Existing historical API work is never wasted.
- Scanner can warm up faster from direct 1h / 4h history.
- Long-term operation stops depending on historical
  higher-timeframe API requests.
- PostgreSQL survives Render restarts.
- No synthetic historical prices are invented.
- Incomplete candles are excluded.
- Duplicate timestamps are resolved deterministically.

IMPORTANT
---------
PAPER TRADING ONLY.
REAL ORDERS DISABLED.
"""

from __future__ import annotations

import os
from datetime import datetime, timezone
from typing import Dict, Optional

import pandas as pd
import psycopg
from psycopg.rows import dict_row


# ============================================================
# CONFIG
# ============================================================

DATABASE_URL = os.environ.get(
    "DATABASE_URL",
    "",
).strip()


SUPPORTED_SYMBOLS = {
    "XAUUSD",
    "XAGUSD",
}


TIMEFRAME_MINUTES = {
    "15m": 15,
    "1h": 60,
    "4h": 240,
}


RESAMPLE_RULES = {
    "1h": "1h",
    "4h": "4h",
}


EXPECTED_15M_BARS = {
    "15m": 1,
    "1h": 4,
    "4h": 16,
}


MINIMUM_CANDLES = {
    "15m": 60,
    "1h": 60,
    "4h": 60,
}


EMPTY_COLUMNS = [
    "datetime",
    "open",
    "high",
    "low",
    "close",
    "volume",
]


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
# GENERIC HELPERS
# ============================================================

def _utc_now():

    return datetime.now(
        timezone.utc
    )


def _normalize_symbol(
    symbol,
):

    normalized = (
        str(symbol)
        .upper()
        .replace("/", "")
        .replace("-", "")
        .replace(" ", "")
        .strip()
    )

    if normalized not in SUPPORTED_SYMBOLS:

        raise ValueError(
            f"Unsupported metals symbol: {symbol}"
        )

    return normalized


def _normalize_timeframe(
    timeframe,
):

    value = (
        str(timeframe)
        .lower()
        .replace(" ", "")
        .strip()
    )

    aliases = {
        "15m": "15m",
        "15min": "15m",
        "15minute": "15m",

        "1h": "1h",
        "60m": "1h",
        "60min": "1h",
        "1hour": "1h",

        "4h": "4h",
        "240m": "4h",
        "240min": "4h",
        "4hour": "4h",
    }

    normalized = aliases.get(
        value
    )

    if normalized not in TIMEFRAME_MINUTES:

        raise ValueError(
            f"Unsupported metals timeframe: {timeframe}"
        )

    return normalized


def _safe_float(
    value,
    default=None,
):

    try:

        if value is None:
            return default

        number = float(
            value
        )

        if number != number:
            return default

        return number

    except (
        TypeError,
        ValueError,
    ):

        return default


def _empty_candles():

    return pd.DataFrame(
        columns=EMPTY_COLUMNS
    )


# ============================================================
# CLOSED-CANDLE BOUNDARIES
# ============================================================

def _current_boundary(
    timeframe,
):

    timeframe = _normalize_timeframe(
        timeframe
    )

    minutes = TIMEFRAME_MINUTES[
        timeframe
    ]

    now = pd.Timestamp.now(
        tz="UTC"
    )

    return now.floor(
        f"{minutes}min"
    )


def _remove_open_candle(
    dataframe,
    timeframe,
):

    if (
        dataframe is None
        or dataframe.empty
    ):

        return _empty_candles()

    boundary = _current_boundary(
        timeframe
    )

    result = dataframe[
        dataframe["datetime"]
        < boundary
    ].copy()

    if result.empty:

        return _empty_candles()

    return result.reset_index(
        drop=True
    )


# ============================================================
# OHLC VALIDATION
# ============================================================

def _valid_ohlc_values(
    open_price,
    high_price,
    low_price,
    close_price,
):

    open_price = _safe_float(
        open_price
    )

    high_price = _safe_float(
        high_price
    )

    low_price = _safe_float(
        low_price
    )

    close_price = _safe_float(
        close_price
    )

    if None in (
        open_price,
        high_price,
        low_price,
        close_price,
    ):

        return False

    if (
        open_price <= 0
        or high_price <= 0
        or low_price <= 0
        or close_price <= 0
    ):

        return False

    if high_price < low_price:
        return False

    if high_price < open_price:
        return False

    if high_price < close_price:
        return False

    if low_price > open_price:
        return False

    if low_price > close_price:
        return False

    return True


def _standardize_candles(
    dataframe,
):

    if (
        dataframe is None
        or not isinstance(
            dataframe,
            pd.DataFrame,
        )
        or dataframe.empty
    ):

        return _empty_candles()

    required = {
        "datetime",
        "open",
        "high",
        "low",
        "close",
        "volume",
    }

    if not required.issubset(
        dataframe.columns
    ):

        return _empty_candles()

    result = dataframe.copy()

    result["datetime"] = pd.to_datetime(
        result["datetime"],
        utc=True,
        errors="coerce",
    )

    for column in (
        "open",
        "high",
        "low",
        "close",
        "volume",
    ):

        result[column] = pd.to_numeric(
            result[column],
            errors="coerce",
        )

    result = result.dropna(
        subset=[
            "datetime",
            "open",
            "high",
            "low",
            "close",
        ]
    )

    if result.empty:

        return _empty_candles()

    valid = (
        (result["open"] > 0)
        & (result["high"] > 0)
        & (result["low"] > 0)
        & (result["close"] > 0)
        & (
            result["high"]
            >= result["low"]
        )
        & (
            result["high"]
            >= result["open"]
        )
        & (
            result["high"]
            >= result["close"]
        )
        & (
            result["low"]
            <= result["open"]
        )
        & (
            result["low"]
            <= result["close"]
        )
    )

    result = result[
        valid
    ]

    if result.empty:

        return _empty_candles()

    result = (
        result
        .sort_values(
            "datetime"
        )
        .drop_duplicates(
            subset=[
                "datetime"
            ],
            keep="last",
        )
        .reset_index(
            drop=True
        )
    )

    return result


# ============================================================
# TABLE SETUP
# ============================================================

def ensure_metals_tables():

    with _connect() as conn:

        with conn.cursor() as cur:

            # ------------------------------------------------
            # REALTIME TICKS
            # ------------------------------------------------

            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS metals_ticks (
                    id BIGSERIAL PRIMARY KEY,

                    symbol TEXT NOT NULL,

                    price DOUBLE PRECISION NOT NULL,

                    provider TEXT NOT NULL,

                    observed_at TIMESTAMPTZ NOT NULL
                )
                """
            )

            cur.execute(
                """
                CREATE INDEX IF NOT EXISTS
                idx_metals_ticks_symbol_time

                ON metals_ticks (
                    symbol,
                    observed_at
                )
                """
            )

            # ------------------------------------------------
            # DIRECT HISTORICAL SEEDS
            # ------------------------------------------------

            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS metals_seed_candles (
                    id BIGSERIAL PRIMARY KEY,

                    symbol TEXT NOT NULL,

                    timeframe TEXT NOT NULL,

                    candle_start TIMESTAMPTZ NOT NULL,

                    candle_end TIMESTAMPTZ NOT NULL,

                    open DOUBLE PRECISION NOT NULL,

                    high DOUBLE PRECISION NOT NULL,

                    low DOUBLE PRECISION NOT NULL,

                    close DOUBLE PRECISION NOT NULL,

                    provider TEXT NOT NULL,

                    created_at TIMESTAMPTZ NOT NULL
                        DEFAULT NOW(),

                    UNIQUE (
                        symbol,
                        timeframe,
                        candle_start
                    )
                )
                """
            )

            cur.execute(
                """
                CREATE INDEX IF NOT EXISTS
                idx_metals_seed_symbol_tf_time

                ON metals_seed_candles (
                    symbol,
                    timeframe,
                    candle_start
                )
                """
            )

        conn.commit()


# ============================================================
# STORE REALTIME QUOTE
# ============================================================

def store_metal_quote(
    symbol,
    price,
    provider="Gold-API",
    observed_at=None,
):

    ensure_metals_tables()

    symbol = _normalize_symbol(
        symbol
    )

    price = _safe_float(
        price
    )

    if (
        price is None
        or price <= 0
    ):

        return {
            "ok":
                False,

            "reason":
                "Invalid metal price",
        }

    if observed_at is None:

        observed_at = _utc_now()

    with _connect() as conn:

        with conn.cursor() as cur:

            # Avoid exact timestamp duplicates.
            cur.execute(
                """
                SELECT
                    observed_at

                FROM metals_ticks

                WHERE symbol = %s

                ORDER BY observed_at DESC

                LIMIT 1
                """,
                (
                    symbol,
                ),
            )

            latest = cur.fetchone()

            if (
                latest
                and latest[
                    "observed_at"
                ]
                == observed_at
            ):

                return {
                    "ok":
                        True,

                    "duplicate":
                        True,

                    "symbol":
                        symbol,

                    "price":
                        price,
                }

            cur.execute(
                """
                INSERT INTO metals_ticks (
                    symbol,
                    price,
                    provider,
                    observed_at
                )

                VALUES (
                    %s,
                    %s,
                    %s,
                    %s
                )
                """,
                (
                    symbol,
                    price,
                    str(provider),
                    observed_at,
                ),
            )

        conn.commit()

    return {
        "ok":
            True,

        "duplicate":
            False,

        "symbol":
            symbol,

        "price":
            price,

        "provider":
            provider,

        "observed_at":
            observed_at.isoformat(),
    }


# ============================================================
# LATEST STORED QUOTE
# ============================================================

def get_latest_stored_quote(
    symbol,
):

    ensure_metals_tables()

    symbol = _normalize_symbol(
        symbol
    )

    with _connect() as conn:

        with conn.cursor() as cur:

            cur.execute(
                """
                SELECT
                    symbol,
                    price,
                    provider,
                    observed_at

                FROM metals_ticks

                WHERE symbol = %s

                ORDER BY observed_at DESC

                LIMIT 1
                """,
                (
                    symbol,
                ),
            )

            row = cur.fetchone()

    if not row:

        return None

    return {
        "symbol":
            row[
                "symbol"
            ],

        "price":
            float(
                row[
                    "price"
                ]
            ),

        "provider":
            row[
                "provider"
            ],

        "observed_at":
            row[
                "observed_at"
            ].isoformat(),
    }


# ============================================================
# READ REALTIME TICKS
# ============================================================

def get_ticks(
    symbol,
    limit=200000,
):

    ensure_metals_tables()

    symbol = _normalize_symbol(
        symbol
    )

    try:

        limit = int(
            limit
        )

    except (
        TypeError,
        ValueError,
    ):

        limit = 200000

    limit = max(
        10,
        min(
            limit,
            250000,
        ),
    )

    with _connect() as conn:

        with conn.cursor() as cur:

            cur.execute(
                """
                SELECT
                    price,
                    observed_at

                FROM metals_ticks

                WHERE symbol = %s

                ORDER BY observed_at DESC

                LIMIT %s
                """,
                (
                    symbol,
                    limit,
                ),
            )

            rows = cur.fetchall()

    if not rows:

        return pd.DataFrame(
            columns=[
                "datetime",
                "price",
            ]
        )

    dataframe = pd.DataFrame(
        [
            {
                "datetime":
                    row[
                        "observed_at"
                    ],

                "price":
                    float(
                        row[
                            "price"
                        ]
                    ),
            }

            for row in rows
        ]
    )

    dataframe["datetime"] = (
        pd.to_datetime(
            dataframe[
                "datetime"
            ],
            utc=True,
            errors="coerce",
        )
    )

    dataframe["price"] = (
        pd.to_numeric(
            dataframe[
                "price"
            ],
            errors="coerce",
        )
    )

    dataframe = (
        dataframe
        .dropna(
            subset=[
                "datetime",
                "price",
            ]
        )
        .sort_values(
            "datetime"
        )
        .drop_duplicates(
            subset=[
                "datetime"
            ],
            keep="last",
        )
        .reset_index(
            drop=True
        )
    )

    return dataframe


# ============================================================
# READ DIRECT HISTORICAL SEEDS
# ============================================================

def get_seed_candles(
    symbol,
    timeframe,
    limit=10000,
):

    ensure_metals_tables()

    symbol = _normalize_symbol(
        symbol
    )

    timeframe = _normalize_timeframe(
        timeframe
    )

    try:

        limit = int(
            limit
        )

    except (
        TypeError,
        ValueError,
    ):

        limit = 10000

    limit = max(
        1,
        min(
            limit,
            20000,
        ),
    )

    with _connect() as conn:

        with conn.cursor() as cur:

            cur.execute(
                """
                SELECT
                    candle_start,
                    candle_end,
                    open,
                    high,
                    low,
                    close,
                    provider

                FROM metals_seed_candles

                WHERE symbol = %s
                  AND timeframe = %s

                ORDER BY candle_start DESC

                LIMIT %s
                """,
                (
                    symbol,
                    timeframe,
                    limit,
                ),
            )

            rows = cur.fetchall()

    if not rows:

        return _empty_candles()

    data = []

    for row in rows:

        if not _valid_ohlc_values(
            row[
                "open"
            ],
            row[
                "high"
            ],
            row[
                "low"
            ],
            row[
                "close"
            ],
        ):

            continue

        data.append(
            {
                "datetime":
                    row[
                        "candle_start"
                    ],

                "open":
                    float(
                        row[
                            "open"
                        ]
                    ),

                "high":
                    float(
                        row[
                            "high"
                        ]
                    ),

                "low":
                    float(
                        row[
                            "low"
                        ]
                    ),

                "close":
                    float(
                        row[
                            "close"
                        ]
                    ),

                "volume":
                    0.0,

                "_source":
                    "DIRECT_SEED",

                "_priority":
                    1,
            }
        )

    if not data:

        return _empty_candles()

    dataframe = pd.DataFrame(
        data
    )

    dataframe = _standardize_candles(
        dataframe
    )

    dataframe = _remove_open_candle(
        dataframe,
        timeframe,
    )

    return dataframe


# ============================================================
# BUILD LOCAL 15M FROM REALTIME TICKS
# ============================================================

def build_live_15m_candles(
    symbol,
    limit=10000,
):

    symbol = _normalize_symbol(
        symbol
    )

    ticks = get_ticks(
        symbol,
        limit=250000,
    )

    if ticks.empty:

        return _empty_candles()

    work = ticks.set_index(
        "datetime"
    )

    candles = (
        work[
            "price"
        ]
        .resample(
            "15min",
            label="left",
            closed="left",
            origin="epoch",
        )
        .ohlc()
        .dropna()
        .reset_index()
    )

    if candles.empty:

        return _empty_candles()

    candles[
        "volume"
    ] = 0.0

    candles[
        "_source"
    ] = "LIVE_15M"

    candles[
        "_priority"
    ] = 2

    candles = _standardize_candles(
        candles
    )

    candles = _remove_open_candle(
        candles,
        "15m",
    )

    if candles.empty:

        return _empty_candles()

    return (
        candles
        .tail(
            max(
                1,
                int(
                    limit
                ),
            )
        )
        .reset_index(
            drop=True
        )
    )


# ============================================================
# CANONICAL 15M HYBRID DATASET
# ============================================================

def build_canonical_15m(
    symbol,
    limit=10000,
):

    symbol = _normalize_symbol(
        symbol
    )

    direct_seed = get_seed_candles(
        symbol,
        "15m",
        limit=20000,
    )

    live = build_live_15m_candles(
        symbol,
        limit=20000,
    )

    frames = []

    if (
        isinstance(
            direct_seed,
            pd.DataFrame,
        )
        and not direct_seed.empty
    ):

        direct_seed = (
            direct_seed.copy()
        )

        direct_seed[
            "_source"
        ] = "DIRECT_SEED"

        direct_seed[
            "_priority"
        ] = 1

        frames.append(
            direct_seed
        )

    if (
        isinstance(
            live,
            pd.DataFrame,
        )
        and not live.empty
    ):

        live = live.copy()

        live[
            "_source"
        ] = "LIVE_15M"

        live[
            "_priority"
        ] = 2

        frames.append(
            live
        )

    if not frames:

        return _empty_candles()

    combined = pd.concat(
        frames,
        ignore_index=True,
    )

    combined = _standardize_candles(
        combined
    )

    if combined.empty:

        return _empty_candles()

    # --------------------------------------------------------
    # DETERMINE PRIORITY AGAIN AFTER STANDARDIZATION
    # --------------------------------------------------------

    if "_priority" not in combined.columns:

        combined[
            "_priority"
        ] = 1

    combined = (
        combined
        .sort_values(
            [
                "datetime",
                "_priority",
            ]
        )
        .drop_duplicates(
            subset=[
                "datetime"
            ],
            keep="last",
        )
        .sort_values(
            "datetime"
        )
        .reset_index(
            drop=True
        )
    )

    combined = _remove_open_candle(
        combined,
        "15m",
    )

    if combined.empty:

        return _empty_candles()

    return (
        combined
        .tail(
            max(
                1,
                int(
                    limit
                ),
            )
        )
        .reset_index(
            drop=True
        )
    )


# ============================================================
# GAP-AWARE LOCAL RESAMPLING
# ============================================================

def build_local_resampled_candles(
    symbol,
    timeframe,
    limit=5000,
):

    symbol = _normalize_symbol(
        symbol
    )

    timeframe = _normalize_timeframe(
        timeframe
    )

    if timeframe == "15m":

        canonical = build_canonical_15m(
            symbol,
            limit=limit,
        )

        if canonical.empty:

            return _empty_candles()

        return canonical

    if timeframe not in RESAMPLE_RULES:

        return _empty_candles()

    required_underlying = (
        EXPECTED_15M_BARS[
            timeframe
        ]
    )

    source_limit = max(
        (
            int(limit)
            * required_underlying
            * 2
        ),
        1000,
    )

    source = build_canonical_15m(
        symbol,
        limit=source_limit,
    )

    if source.empty:

        return _empty_candles()

    working = source.copy()

    working = working.set_index(
        "datetime"
    )

    rule = RESAMPLE_RULES[
        timeframe
    ]

    grouped = working.resample(
        rule,
        label="left",
        closed="left",
        origin="epoch",
    )

    candles = grouped.agg(
        {
            "open":
                "first",

            "high":
                "max",

            "low":
                "min",

            "close":
                "last",

            "volume":
                "sum",
        }
    )

    counts = grouped[
        "close"
    ].count()

    candles[
        "_source_count"
    ] = counts

    candles = candles.reset_index()

    # --------------------------------------------------------
    # REQUIRE COMPLETE 15M COVERAGE
    # --------------------------------------------------------

    candles = candles[
        candles[
            "_source_count"
        ]
        >= required_underlying
    ]

    if candles.empty:

        return _empty_candles()

    candles[
        "_source"
    ] = "LOCAL_RESAMPLE"

    candles[
        "_priority"
    ] = 2

    candles = _standardize_candles(
        candles
    )

    candles = _remove_open_candle(
        candles,
        timeframe,
    )

    if candles.empty:

        return _empty_candles()

    return (
        candles
        .tail(
            max(
                1,
                int(
                    limit
                ),
            )
        )
        .reset_index(
            drop=True
        )
    )


# ============================================================
# HYBRID HIGHER-TIMEFRAME READER
# ============================================================

def build_hybrid_higher_timeframe(
    symbol,
    timeframe,
    limit=5000,
):

    """
    Merge:

        DIRECT historical seed
            +
        LOCAL resampled canonical 15m

    Priority:
        LOCAL_RESAMPLE > DIRECT_SEED

    This preserves initial bootstrap history while allowing
    realtime-derived candles to take over naturally.
    """

    symbol = _normalize_symbol(
        symbol
    )

    timeframe = _normalize_timeframe(
        timeframe
    )

    if timeframe == "15m":

        return build_canonical_15m(
            symbol,
            limit=limit,
        )

    direct = get_seed_candles(
        symbol,
        timeframe,
        limit=20000,
    )

    local = build_local_resampled_candles(
        symbol,
        timeframe,
        limit=20000,
    )

    frames = []

    if (
        isinstance(
            direct,
            pd.DataFrame,
        )
        and not direct.empty
    ):

        direct = direct.copy()

        direct[
            "_source"
        ] = "DIRECT_SEED"

        direct[
            "_priority"
        ] = 1

        frames.append(
            direct
        )

    if (
        isinstance(
            local,
            pd.DataFrame,
        )
        and not local.empty
    ):

        local = local.copy()

        local[
            "_source"
        ] = "LOCAL_RESAMPLE"

        local[
            "_priority"
        ] = 2

        frames.append(
            local
        )

    if not frames:

        return _empty_candles()

    combined = pd.concat(
        frames,
        ignore_index=True,
    )

    combined = _standardize_candles(
        combined
    )

    if combined.empty:

        return _empty_candles()

    if "_priority" not in combined.columns:

        combined[
            "_priority"
        ] = 1

    combined = (
        combined
        .sort_values(
            [
                "datetime",
                "_priority",
            ]
        )
        .drop_duplicates(
            subset=[
                "datetime"
            ],
            keep="last",
        )
        .sort_values(
            "datetime"
        )
        .reset_index(
            drop=True
        )
    )

    combined = _remove_open_candle(
        combined,
        timeframe,
    )

    if combined.empty:

        return _empty_candles()

    return (
        combined
        .tail(
            max(
                1,
                int(
                    limit
                ),
            )
        )
        .reset_index(
            drop=True
        )
    )


# ============================================================
# PUBLIC SCANNER CANDLE API
# ============================================================

def build_candles(
    symbol,
    timeframe="15m",
    limit=200,
):

    symbol = _normalize_symbol(
        symbol
    )

    timeframe = _normalize_timeframe(
        timeframe
    )

    try:

        limit = int(
            limit
        )

    except (
        TypeError,
        ValueError,
    ):

        limit = 200

    limit = max(
        1,
        min(
            limit,
            10000,
        ),
    )

    if timeframe == "15m":

        result = build_canonical_15m(
            symbol,
            limit=limit,
        )

    else:

        result = (
            build_hybrid_higher_timeframe(
                symbol,
                timeframe,
                limit=limit,
            )
        )

    if (
        result is None
        or result.empty
    ):

        return _empty_candles()

    result = _standardize_candles(
        result
    )

    if result.empty:

        return _empty_candles()

    return (
        result[
            EMPTY_COLUMNS
        ]
        .tail(
            limit
        )
        .reset_index(
            drop=True
        )
    )


# ============================================================
# MULTI-TIMEFRAME SCANNER API
# ============================================================

def get_metals_mtf_candles(
    symbol,
    limit=200,
):

    symbol = _normalize_symbol(
        symbol
    )

    return {
        "15m":
            build_candles(
                symbol,
                "15m",
                limit,
            ),

        "1h":
            build_candles(
                symbol,
                "1h",
                limit,
            ),

        "4h":
            build_candles(
                symbol,
                "4h",
                limit,
            ),
    }


# ============================================================
# DIRECT SEED COUNTS
# ============================================================

def get_seed_candle_counts(
    symbol,
) -> Dict:

    symbol = _normalize_symbol(
        symbol
    )

    ensure_metals_tables()

    result = {}

    with _connect() as conn:

        with conn.cursor() as cur:

            for timeframe in (
                "15m",
                "1h",
                "4h",
            ):

                cur.execute(
                    """
                    SELECT COUNT(*) AS count

                    FROM metals_seed_candles

                    WHERE symbol = %s
                      AND timeframe = %s
                    """,
                    (
                        symbol,
                        timeframe,
                    ),
                )

                row = cur.fetchone()

                result[
                    timeframe
                ] = int(
                    row[
                        "count"
                    ]
                    if row
                    else 0
                )

    return result


# ============================================================
# EFFECTIVE SCANNER COUNTS
# ============================================================

def get_effective_candle_counts(
    symbol,
) -> Dict:

    symbol = _normalize_symbol(
        symbol
    )

    result = {}

    for timeframe in (
        "15m",
        "1h",
        "4h",
    ):

        candles = build_candles(
            symbol,
            timeframe,
            limit=10000,
        )

        result[
            timeframe
        ] = len(
            candles
        )

    return result


# ============================================================
# READINESS
# ============================================================

def metals_ohlc_readiness(
    symbol,
):

    symbol = _normalize_symbol(
        symbol
    )

    result = {
        "symbol":
            symbol,

        "ready":
            False,

        "state":
            "WARMING_UP",

        "architecture":
            "HYBRID_DIRECT_PLUS_LOCAL",

        "canonical_timeframe":
            "15m",

        "timeframes":
            {},
    }

    all_ready = True

    for timeframe, minimum in (
        MINIMUM_CANDLES.items()
    ):

        candles = build_candles(
            symbol,
            timeframe,
            limit=minimum,
        )

        count = len(
            candles
        )

        ready = (
            count >= minimum
        )

        result[
            "timeframes"
        ][
            timeframe
        ] = {
            "candles":
                count,

            "minimum":
                minimum,

            "remaining":
                max(
                    0,
                    minimum - count,
                ),

            "ready":
                ready,
        }

        if not ready:

            all_ready = False

    result[
        "ready"
    ] = all_ready

    result[
        "state"
    ] = (
        "READY"
        if all_ready
        else "WARMING_UP"
    )

    return result


# ============================================================
# SOURCE STATUS
# ============================================================

def metals_ohlc_source_status(
    symbol,
):

    symbol = _normalize_symbol(
        symbol
    )

    seed_counts = (
        get_seed_candle_counts(
            symbol
        )
    )

    effective_counts = (
        get_effective_candle_counts(
            symbol
        )
    )

    ticks = get_ticks(
        symbol,
        limit=250000,
    )

    readiness = (
        metals_ohlc_readiness(
            symbol
        )
    )

    return {
        "symbol":
            symbol,

        "engine":
            "V4.3 Hybrid Metals OHLC",

        "direct_seed_counts":
            seed_counts,

        "effective_counts":
            effective_counts,

        "live_tick_count":
            len(
                ticks
            ),

        "readiness":
            readiness,

        "historical_bootstrap":
            "DIRECT_15M_1H_4H",

        "long_term_engine":
            "REALTIME_15M_PLUS_LOCAL_RESAMPLE",

        "higher_tf_fallback":
            "DIRECT_SEED",

        "storage":
            "PostgreSQL",

        "twelve_data_required":
            False,

        "metals_dev_required":
            False,

        "paper_only":
            True,

        "real_orders":
            False,
    }


# ============================================================
# BACKWARD-COMPATIBLE CACHE STATUS
# ============================================================

def metals_candles_cache_status(
    symbol=None,
):

    symbols = (
        [symbol]
        if symbol
        else [
            "XAUUSD",
            "XAGUSD",
        ]
    )

    result = {
        "provider":
            "HYBRID_POSTGRES_OHLC",

        "external_api":
            False,

        "paid_candle_api_required":
            False,
    }

    for raw_symbol in symbols:

        normalized = (
            _normalize_symbol(
                raw_symbol
            )
        )

        readiness = (
            metals_ohlc_readiness(
                normalized
            )
        )

        timeframes = readiness.get(
            "timeframes",
            {},
        )

        key_map = {
            "15m":
                f"{normalized}:15min:200",

            "1h":
                f"{normalized}:1h:200",

            "4h":
                f"{normalized}:4h:200",
        }

        for timeframe, cache_key in (
            key_map.items()
        ):

            info = timeframes.get(
                timeframe,
                {},
            )

            ready = bool(
                info.get(
                    "ready",
                    False,
                )
            )

            result[
                cache_key
            ] = {
                "ready":
                    ready,

                "fresh":
                    ready,

                "state":
                    (
                        "READY"
                        if ready
                        else "WARMING_UP"
                    ),

                "candles":
                    int(
                        info.get(
                            "candles",
                            0,
                        )
                        or 0
                    ),

                "minimum":
                    int(
                        info.get(
                            "minimum",
                            60,
                        )
                        or 60
                    ),

                "remaining":
                    int(
                        info.get(
                            "remaining",
                            0,
                        )
                        or 0
                    ),

                "source":
                    (
                        "HYBRID_DIRECT_PLUS_LOCAL"
                    ),

                "external_api":
                    False,
            }

    return result


# ============================================================
# HEALTH
# ============================================================

def metals_ohlc_health():

    try:

        ensure_metals_tables()

        gold = metals_ohlc_source_status(
            "XAUUSD"
        )

        silver = metals_ohlc_source_status(
            "XAGUSD"
        )

        return {
            "ok":
                True,

            "database":
                "ONLINE",

            "engine":
                "V4.3 Hybrid Metals OHLC",

            "architecture":
                (
                    "DIRECT_INITIAL_HISTORY"
                    " + "
                    "LOCAL_LONG_TERM_RESAMPLE"
                ),

            "canonical_timeframe":
                "15m",

            "historical_provider":
                "Gold-API",

            "live_provider":
                "Gold-API realtime",

            "gold":
                gold,

            "silver":
                silver,

            "restart_safe":
                True,

            "persistent":
                True,

            "twelve_data_required":
                False,

            "metals_dev_required":
                False,

            "paper_only":
                True,

            "real_orders":
                False,
        }

    except Exception as error:

        return {
            "ok":
                False,

            "database":
                "ERROR",

            "engine":
                "V4.3 Hybrid Metals OHLC",

            "reason":
                str(
                    error
                ),

            "paper_only":
                True,

            "real_orders":
                False,
        }

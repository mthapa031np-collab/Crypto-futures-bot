"""
metals_ohlc_store.py

PRO AI QUANT TERMINAL V4.2
CANONICAL 15-MINUTE METALS OHLC STORE

Core architecture
-----------------
Gold-API realtime / limited OHLC
            ↓
PostgreSQL persistent storage
            ↓
Canonical 15m candles
            ↓
Local deterministic resampling
        ↙                 ↘
      1h                  4h
            ↓
     Metals Scanner

Design goals
------------
- One canonical external candle timeframe: 15m
- 1h and 4h generated locally
- No repeated external API calls for higher timeframes
- Persistent across Render restarts
- Historical seed + live ticks unified
- Closed-candle safety
- Duplicate protection
- OHLC validation
- Gap-aware higher timeframe generation
- Scanner backward compatibility
- PAPER ONLY
- NO REAL ORDERS
"""

from __future__ import annotations

import os
from datetime import datetime, timezone
from typing import Dict

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


CANONICAL_TIMEFRAME = "15m"


TIMEFRAME_MINUTES = {
    "15m": 15,
    "1h": 60,
    "4h": 240,
}


RESAMPLE_RULES = {
    "1h": "1h",
    "4h": "4h",
}


EXPECTED_15M_PER_TIMEFRAME = {
    "15m": 1,
    "1h": 4,
    "4h": 16,
}


MINIMUM_CANDLES = {
    "15m": 60,
    "1h": 60,
    "4h": 60,
}


EMPTY_CANDLE_COLUMNS = [
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
# HELPERS
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

        "4h": "4h",
        "240m": "4h",
        "240min": "4h",
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
        columns=EMPTY_CANDLE_COLUMNS
    )


def _floor_timestamp(
    timestamp,
    minutes,
):

    ts = pd.Timestamp(
        timestamp
    )

    if ts.tzinfo is None:

        ts = ts.tz_localize(
            "UTC"
        )

    else:

        ts = ts.tz_convert(
            "UTC"
        )

    return ts.floor(
        f"{minutes}min"
    )


def _last_closed_boundary(
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


# ============================================================
# OHLC VALIDATION
# ============================================================

def _validate_ohlc_row(
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


# ============================================================
# TABLE SETUP
# ============================================================

def ensure_metals_tables():

    with _connect() as conn:

        with conn.cursor() as cur:

            # ------------------------------------------------
            # LIVE QUOTE TICKS
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
            # HISTORICAL SEED STORAGE
            #
            # Existing table preserved for compatibility.
            # V4.2 treats 15m as canonical source.
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
# STORE LIVE QUOTE
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
            "ok": False,
            "reason": "Invalid metal price",
        }

    if observed_at is None:

        observed_at = _utc_now()

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

                LIMIT 1
                """,
                (
                    symbol,
                ),
            )

            latest = cur.fetchone()

            if latest:

                if (
                    latest["observed_at"]
                    == observed_at
                ):

                    return {
                        "ok": True,
                        "duplicate": True,
                        "symbol": symbol,
                        "price": price,
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
        "ok": True,
        "duplicate": False,
        "symbol": symbol,
        "price": price,
        "provider": provider,
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
            row["symbol"],

        "price":
            float(
                row["price"]
            ),

        "provider":
            row["provider"],

        "observed_at":
            row[
                "observed_at"
            ].isoformat(),
    }


# ============================================================
# RAW TICKS
# ============================================================

def get_ticks(
    symbol,
    limit=100000,
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

        limit = 100000

    limit = max(
        10,
        min(
            limit,
            200000,
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

    df = pd.DataFrame(
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

    df["datetime"] = pd.to_datetime(
        df["datetime"],
        utc=True,
        errors="coerce",
    )

    df["price"] = pd.to_numeric(
        df["price"],
        errors="coerce",
    )

    return (
        df
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


# ============================================================
# READ RAW SEED CANDLES
# ============================================================

def get_seed_candles(
    symbol,
    timeframe="15m",
    limit=5000,
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

        limit = 5000

    limit = max(
        1,
        min(
            limit,
            10000,
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

        if not _validate_ohlc_row(
            row["open"],
            row["high"],
            row["low"],
            row["close"],
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
                        row["open"]
                    ),

                "high":
                    float(
                        row["high"]
                    ),

                "low":
                    float(
                        row["low"]
                    ),

                "close":
                    float(
                        row["close"]
                    ),

                "volume":
                    0.0,

                "_source":
                    "SEED",
            }
        )

    if not data:

        return _empty_candles()

    df = pd.DataFrame(
        data
    )

    df["datetime"] = pd.to_datetime(
        df["datetime"],
        utc=True,
        errors="coerce",
    )

    return (
        df
        .dropna(
            subset=[
                "datetime"
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


# ============================================================
# LIVE 15M CANDLES FROM TICKS
# ============================================================

def build_live_15m_candles(
    symbol,
    limit=5000,
):

    symbol = _normalize_symbol(
        symbol
    )

    ticks = get_ticks(
        symbol,
        limit=200000,
    )

    if ticks.empty:

        return _empty_candles()

    work = ticks.set_index(
        "datetime"
    )

    candles = (
        work["price"]
        .resample(
            "15min",
            label="left",
            closed="left",
        )
        .ohlc()
        .dropna()
        .reset_index()
    )

    if candles.empty:

        return _empty_candles()

    # --------------------------------------------------------
    # REMOVE CURRENT / INCOMPLETE 15M BAR
    # --------------------------------------------------------

    current_boundary = (
        _last_closed_boundary(
            "15m"
        )
    )

    candles = candles[
        candles["datetime"]
        < current_boundary
    ]

    if candles.empty:

        return _empty_candles()

    candles["volume"] = 0.0

    candles["_source"] = "LIVE"

    return (
        candles
        .tail(
            max(
                1,
                int(limit),
            )
        )
        .reset_index(
            drop=True
        )
    )


# ============================================================
# CANONICAL 15M DATASET
# ============================================================

def build_canonical_15m(
    symbol,
    limit=5000,
):

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

        limit = 5000

    limit = max(
        1,
        min(
            limit,
            10000,
        ),
    )

    seed = get_seed_candles(
        symbol,
        "15m",
        limit=10000,
    )

    live = build_live_15m_candles(
        symbol,
        limit=10000,
    )

    frames = []

    if (
        isinstance(
            seed,
            pd.DataFrame,
        )
        and not seed.empty
    ):

        frames.append(
            seed
        )

    if (
        isinstance(
            live,
            pd.DataFrame,
        )
        and not live.empty
    ):

        frames.append(
            live
        )

    if not frames:

        return _empty_candles()

    combined = pd.concat(
        frames,
        ignore_index=True,
    )

    combined["datetime"] = pd.to_datetime(
        combined["datetime"],
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

        combined[column] = pd.to_numeric(
            combined[column],
            errors="coerce",
        )

    combined = (
        combined
        .dropna(
            subset=[
                "datetime",
                "open",
                "high",
                "low",
                "close",
            ]
        )
        .sort_values(
            [
                "datetime",
                "_source",
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

    valid_mask = (
        (combined["open"] > 0)
        & (combined["high"] > 0)
        & (combined["low"] > 0)
        & (combined["close"] > 0)
        & (
            combined["high"]
            >= combined["low"]
        )
        & (
            combined["high"]
            >= combined["open"]
        )
        & (
            combined["high"]
            >= combined["close"]
        )
        & (
            combined["low"]
            <= combined["open"]
        )
        & (
            combined["low"]
            <= combined["close"]
        )
    )

    combined = combined[
        valid_mask
    ]

    # --------------------------------------------------------
    # REMOVE CURRENT / INCOMPLETE 15M BAR
    # --------------------------------------------------------

    current_boundary = (
        _last_closed_boundary(
            "15m"
        )
    )

    combined = combined[
        combined["datetime"]
        < current_boundary
    ]

    if combined.empty:

        return _empty_candles()

    return (
        combined
        .tail(
            limit
        )
        .reset_index(
            drop=True
        )
    )


# ============================================================
# LOCAL HIGHER-TIMEFRAME RESAMPLING
# ============================================================

def _resample_from_15m(
    symbol,
    timeframe,
    limit=200,
):

    symbol = _normalize_symbol(
        symbol
    )

    timeframe = _normalize_timeframe(
        timeframe
    )

    if timeframe == "15m":

        result = build_canonical_15m(
            symbol,
            limit=limit,
        )

        if result.empty:

            return _empty_candles()

        return result[
            EMPTY_CANDLE_COLUMNS
        ].copy()

    if timeframe not in RESAMPLE_RULES:

        return _empty_candles()

    expected_count = (
        EXPECTED_15M_PER_TIMEFRAME[
            timeframe
        ]
    )

    # Fetch enough canonical bars for requested output.
    source_limit = max(
        int(limit)
        * expected_count
        * 2,
        500,
    )

    source = build_canonical_15m(
        symbol,
        limit=source_limit,
    )

    if source.empty:

        return _empty_candles()

    source = source.copy()

    source = source.set_index(
        "datetime"
    )

    rule = RESAMPLE_RULES[
        timeframe
    ]

    grouped = source.resample(
        rule,
        label="left",
        closed="left",
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
    # REQUIRE COMPLETE UNDERLYING 15M COVERAGE
    # --------------------------------------------------------

    candles = candles[
        candles[
            "_source_count"
        ]
        >= expected_count
    ]

    if candles.empty:

        return _empty_candles()

    # --------------------------------------------------------
    # REMOVE CURRENT / INCOMPLETE HIGHER-TF BAR
    # --------------------------------------------------------

    current_boundary = (
        _last_closed_boundary(
            timeframe
        )
    )

    candles = candles[
        candles["datetime"]
        < current_boundary
    ]

    if candles.empty:

        return _empty_candles()

    valid = (
        (candles["open"] > 0)
        & (candles["high"] > 0)
        & (candles["low"] > 0)
        & (candles["close"] > 0)
        & (
            candles["high"]
            >= candles["low"]
        )
        & (
            candles["high"]
            >= candles["open"]
        )
        & (
            candles["high"]
            >= candles["close"]
        )
        & (
            candles["low"]
            <= candles["open"]
        )
        & (
            candles["low"]
            <= candles["close"]
        )
    )

    candles = candles[
        valid
    ]

    if candles.empty:

        return _empty_candles()

    return (
        candles
        .tail(
            max(
                1,
                int(limit),
            )
        )[
            EMPTY_CANDLE_COLUMNS
        ]
        .reset_index(
            drop=True
        )
    )


# ============================================================
# PUBLIC BUILD_CANDLES API
# ============================================================

def build_candles(
    symbol,
    timeframe="15m",
    limit=200,
):

    """
    Scanner-compatible public candle reader.

    V4.2 behavior:
        15m -> canonical persisted + live dataset
        1h  -> locally derived from canonical 15m
        4h  -> locally derived from canonical 15m

    No higher-timeframe provider request is required.
    """

    symbol = _normalize_symbol(
        symbol
    )

    timeframe = _normalize_timeframe(
        timeframe
    )

    return _resample_from_15m(
        symbol,
        timeframe,
        limit,
    )


# ============================================================
# MULTI-TIMEFRAME API
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
# RAW SEED COUNTS
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
                    row["count"]
                    if row
                    else 0
                )

    return result


# ============================================================
# EFFECTIVE LOCAL COUNTS
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
            limit=5000,
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

        "canonical_timeframe":
            CANONICAL_TIMEFRAME,

        "higher_timeframes":
            "LOCAL_RESAMPLE",

        "timeframes":
            {},

        "source":
            "POSTGRES_15M_PLUS_LIVE",
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
# DATA SOURCE STATUS
# ============================================================

def metals_ohlc_source_status(
    symbol,
):

    symbol = _normalize_symbol(
        symbol
    )

    raw_seed = get_seed_candle_counts(
        symbol
    )

    effective = get_effective_candle_counts(
        symbol
    )

    live_ticks = get_ticks(
        symbol,
        limit=200000,
    )

    readiness = metals_ohlc_readiness(
        symbol
    )

    return {
        "symbol":
            symbol,

        "canonical_timeframe":
            "15m",

        "raw_seed_counts":
            raw_seed,

        "effective_counts":
            effective,

        "live_tick_count":
            len(
                live_ticks
            ),

        "readiness":
            readiness,

        "historical_source":
            "Gold-API limited 15m seed",

        "live_source":
            "Gold-API realtime",

        "higher_timeframe_source":
            "LOCAL_15M_RESAMPLE",

        "storage":
            "PostgreSQL",

        "requires_external_1h":
            False,

        "requires_external_4h":
            False,

        "real_orders":
            False,
    }


# ============================================================
# CACHE STATUS COMPATIBILITY
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

    result = {}

    for item in symbols:

        normalized = _normalize_symbol(
            item
        )

        readiness = metals_ohlc_readiness(
            normalized
        )

        result[
            normalized
        ] = {
            "ready":
                readiness[
                    "ready"
                ],

            "state":
                readiness[
                    "state"
                ],

            "timeframes":
                readiness[
                    "timeframes"
                ],

            "canonical_timeframe":
                "15m",

            "higher_timeframes":
                "LOCAL_RESAMPLE",
        }

    return result


# ============================================================
# HEALTH
# ============================================================

def metals_ohlc_health():

    try:

        ensure_metals_tables()

        gold = metals_ohlc_readiness(
            "XAUUSD"
        )

        silver = metals_ohlc_readiness(
            "XAGUSD"
        )

        return {
            "ok":
                True,

            "database":
                "ONLINE",

            "engine":
                "V4.2 Canonical Metals OHLC",

            "canonical_timeframe":
                "15m",

            "higher_timeframe_engine":
                "LOCAL_RESAMPLE",

            "historical_source":
                "Gold-API",

            "live_source":
                "Gold-API realtime",

            "gold":
                gold,

            "silver":
                silver,

            "twelve_data_required":
                False,

            "metals_dev_required":
                False,

            "external_1h_required":
                False,

            "external_4h_required":
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
                "V4.2 Canonical Metals OHLC",

            "reason":
                str(
                    error
                ),

            "paper_only":
                True,

            "real_orders":
                False,
        }

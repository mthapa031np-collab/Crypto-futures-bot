"""
metals_ohlc_store.py

PRO AI QUANT TERMINAL V3.9
UNIFIED PERSISTENT METALS OHLC STORE

Architecture
------------
Historical bootstrap:
    Gold-API OHLC
        ↓
    metals_seed_candles

Live market:
    Gold-API realtime XAU/XAG
        ↓
    metals_ticks
        ↓
    local OHLC aggregation

Unified scanner feed:
    historical seed candles
            +
    live locally-built candles
            ↓
    15m / 1h / 4h
            ↓
    Metals Scanner / MTF Engine

Design goals
------------
- Persistent across Render restarts
- Historical bootstrap reused permanently
- Live candles automatically continue history
- No Twelve Data dependency
- No Metals.Dev candle dependency
- No synthetic / invented prices
- Backward compatible with existing V3.8 code
- PAPER TRADING SAFE
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


TIMEFRAME_MINUTES = {
    "15m": 15,
    "1h": 60,
    "4h": 240,
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
# DATABASE CONNECTION
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
            f"Unsupported metals symbol: "
            f"{symbol}"
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

        "1h": "1h",
        "60m": "1h",
        "60min": "1h",

        "4h": "4h",
        "240m": "4h",
        "240min": "4h",
    }

    normalized = (
        aliases.get(
            value
        )
    )

    if normalized not in TIMEFRAME_MINUTES:

        raise ValueError(
            f"Unsupported metals timeframe: "
            f"{timeframe}"
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

        if number <= 0:

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


# ============================================================
# DATABASE SETUP
# ============================================================

def ensure_metals_tables():

    with _connect() as conn:

        with conn.cursor() as cur:

            # ------------------------------------------------
            # LIVE TICKS
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
            # HISTORICAL SEED CANDLES
            #
            # Same schema used by metals_bootstrap.py.
            # Creating it here makes the OHLC layer safe
            # even before bootstrap is manually executed.
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

    if price is None:

        return {
            "ok": False,
            "reason": "Invalid metal price",
        }

    if observed_at is None:

        observed_at = (
            _utc_now()
        )

    with _connect() as conn:

        with conn.cursor() as cur:

            # Avoid storing exactly the same timestamp twice.
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

            latest = (
                cur.fetchone()
            )

            if latest:

                latest_time = (
                    latest[
                        "observed_at"
                    ]
                )

                if (
                    latest_time
                    == observed_at
                ):

                    return {
                        "ok": True,
                        "duplicate": True,
                        "symbol": symbol,
                        "price": price,
                        "provider": provider,
                        "observed_at":
                            observed_at.isoformat(),
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
                    str(
                        provider
                    ),
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

            row = (
                cur.fetchone()
            )

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
# RAW LIVE TICKS
# ============================================================

def get_ticks(
    symbol,
    limit=50000,
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

        limit = 50000

    limit = max(
        10,
        min(
            limit,
            100000,
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

            rows = (
                cur.fetchall()
            )

    if not rows:

        return pd.DataFrame(
            columns=[
                "datetime",
                "price",
            ]
        )

    data = [
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

    df = pd.DataFrame(
        data
    )

    df[
        "datetime"
    ] = pd.to_datetime(
        df[
            "datetime"
        ],
        utc=True,
        errors="coerce",
    )

    df[
        "price"
    ] = pd.to_numeric(
        df[
            "price"
        ],
        errors="coerce",
    )

    df = (
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

    return df


# ============================================================
# HISTORICAL SEED CANDLES
# ============================================================

def get_seed_candles(
    symbol,
    timeframe,
    limit=1000,
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

        limit = 1000

    limit = max(
        1,
        min(
            limit,
            5000,
        ),
    )

    with _connect() as conn:

        with conn.cursor() as cur:

            cur.execute(
                """
                SELECT
                    candle_start,
                    open,
                    high,
                    low,
                    close

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

            rows = (
                cur.fetchall()
            )

    if not rows:

        return _empty_candles()

    data = []

    for row in rows:

        open_price = _safe_float(
            row[
                "open"
            ]
        )

        high_price = _safe_float(
            row[
                "high"
            ]
        )

        low_price = _safe_float(
            row[
                "low"
            ]
        )

        close_price = _safe_float(
            row[
                "close"
            ]
        )

        if None in (
            open_price,
            high_price,
            low_price,
            close_price,
        ):

            continue

        if (
            high_price < low_price
            or high_price < open_price
            or high_price < close_price
            or low_price > open_price
            or low_price > close_price
        ):

            continue

        data.append(
            {
                "datetime":
                    row[
                        "candle_start"
                    ],

                "open":
                    open_price,

                "high":
                    high_price,

                "low":
                    low_price,

                "close":
                    close_price,

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

    df[
        "datetime"
    ] = pd.to_datetime(
        df[
            "datetime"
        ],
        utc=True,
        errors="coerce",
    )

    df = (
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

    return df


# ============================================================
# BUILD LIVE OHLC FROM TICKS
# ============================================================

def build_live_candles(
    symbol,
    timeframe="15m",
    limit=1000,
):

    symbol = _normalize_symbol(
        symbol
    )

    timeframe = _normalize_timeframe(
        timeframe
    )

    minutes = (
        TIMEFRAME_MINUTES[
            timeframe
        ]
    )

    ticks = get_ticks(
        symbol,
        limit=100000,
    )

    if ticks.empty:

        return _empty_candles()

    work = (
        ticks
        .set_index(
            "datetime"
        )
    )

    rule = (
        f"{minutes}min"
    )

    ohlc = (
        work[
            "price"
        ]
        .resample(
            rule,
            label="left",
            closed="left",
        )
        .ohlc()
        .dropna()
        .reset_index()
    )

    if ohlc.empty:

        return _empty_candles()

    ohlc[
        "volume"
    ] = 0.0

    ohlc[
        "_source"
    ] = "LIVE"

    ohlc = (
        ohlc
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

    return ohlc


# ============================================================
# UNIFIED HISTORICAL + LIVE CANDLES
# ============================================================

def build_candles(
    symbol,
    timeframe="15m",
    limit=200,
):

    """
    Unified candle reader used by the scanner.

    Priority:
        historical Gold-API seed
            +
        live locally aggregated ticks

    If both contain the same timestamp,
    LIVE wins because it is the newer local observation.
    """

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
            5000,
        ),
    )

    # Pull extra rows before de-duplication.
    fetch_limit = max(
        limit * 2,
        200,
    )

    seed = get_seed_candles(
        symbol,
        timeframe,
        fetch_limit,
    )

    live = build_live_candles(
        symbol,
        timeframe,
        fetch_limit,
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

    combined[
        "datetime"
    ] = pd.to_datetime(
        combined[
            "datetime"
        ],
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

        combined[
            column
        ] = pd.to_numeric(
            combined[
                column
            ],
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

    # --------------------------------------------------------
    # OHLC VALIDATION
    # --------------------------------------------------------

    valid = (
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

    combined = (
        combined[
            valid
        ]
        .tail(
            limit
        )
        .reset_index(
            drop=True
        )
    )

    if combined.empty:

        return _empty_candles()

    return combined[
        EMPTY_CANDLE_COLUMNS
    ].copy()


# ============================================================
# MULTI-TIMEFRAME CANDLES
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
# SEED COUNTS
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

                row = (
                    cur.fetchone()
                )

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
# DATA READINESS
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

        "timeframes":
            {},

        "source":
            "SEED_PLUS_LIVE_POSTGRES",
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

    seed_counts = (
        get_seed_candle_counts(
            symbol
        )
    )

    live_ticks = (
        get_ticks(
            symbol,
            limit=100000,
        )
    )

    readiness = (
        metals_ohlc_readiness(
            symbol
        )
    )

    return {
        "symbol":
            symbol,

        "seed_counts":
            seed_counts,

        "live_tick_count":
            len(
                live_ticks
            ),

        "readiness":
            readiness,

        "historical_source":
            "Gold-API OHLC",

        "live_source":
            "Gold-API realtime",

        "storage":
            "PostgreSQL",

        "external_paid_candle_api":
            False,

        "real_orders":
            False,
    }


# ============================================================
# HEALTH
# ============================================================

def metals_ohlc_health():

    try:

        ensure_metals_tables()

        gold = (
            metals_ohlc_readiness(
                "XAUUSD"
            )
        )

        silver = (
            metals_ohlc_readiness(
                "XAGUSD"
            )
        )

        return {
            "ok":
                True,

            "database":
                "ONLINE",

            "engine":
                "V3.9 Unified Metals OHLC",

            "historical_source":
                "Gold-API OHLC",

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
                "V3.9 Unified Metals OHLC",

            "reason":
                str(
                    error
                ),

            "real_orders":
                False,
        }

"""
metals_ohlc_store.py

PRO AI QUANT TERMINAL V3.7

Persistent PostgreSQL metals quote + OHLC store.

Purpose
-------
- Store XAU / XAG live quotes
- Build our own candles
- Remove dependency on paid candle APIs
- Support:
    15m
    1h
    4h
- Persistent across Render restarts
- Paper-trading safe

NO REAL ORDERS.
"""

import os
from datetime import datetime, timezone

import pandas as pd
import psycopg
from psycopg.rows import dict_row


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


# ============================================================
# HELPERS
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


def _normalize_symbol(
    symbol,
):

    symbol = (
        str(symbol)
        .upper()
        .replace("/", "")
        .replace("-", "")
        .replace(" ", "")
        .strip()
    )

    if symbol not in SUPPORTED_SYMBOLS:

        raise ValueError(
            f"Unsupported metals symbol: {symbol}"
        )

    return symbol


def _safe_float(
    value,
):

    try:

        value = float(value)

        if value <= 0:
            return None

        return value

    except (
        TypeError,
        ValueError,
    ):

        return None


def _utc_now():

    return datetime.now(
        timezone.utc
    )


# ============================================================
# DATABASE SETUP
# ============================================================

def ensure_metals_tables():

    with _connect() as conn:

        with conn.cursor() as cur:

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

        observed_at = _utc_now()

    with _connect() as conn:

        with conn.cursor() as cur:

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
        "symbol": symbol,
        "price": price,
        "provider": provider,
        "observed_at": (
            observed_at.isoformat()
        ),
    }


# ============================================================
# LATEST STORED PRICE
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
        "symbol": row["symbol"],
        "price": float(
            row["price"]
        ),
        "provider": row["provider"],
        "observed_at": (
            row["observed_at"]
            .isoformat()
        ),
    }


# ============================================================
# READ RAW TICKS
# ============================================================

def get_ticks(
    symbol,
    limit=5000,
):

    ensure_metals_tables()

    symbol = _normalize_symbol(
        symbol
    )

    limit = max(
        10,
        min(
            int(limit),
            50000,
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

    data = [
        {
            "datetime":
                row["observed_at"],

            "price":
                float(
                    row["price"]
                ),
        }
        for row in rows
    ]

    df = pd.DataFrame(
        data
    )

    df["datetime"] = (
        pd.to_datetime(
            df["datetime"],
            utc=True,
        )
    )

    df = (
        df
        .sort_values(
            "datetime"
        )
        .drop_duplicates(
            subset=[
                "datetime"
            ]
        )
        .reset_index(
            drop=True
        )
    )

    return df


# ============================================================
# BUILD OHLC CANDLES
# ============================================================

def build_candles(
    symbol,
    timeframe="15m",
    limit=200,
):

    symbol = _normalize_symbol(
        symbol
    )

    if timeframe not in TIMEFRAME_MINUTES:

        raise ValueError(
            f"Unsupported timeframe: {timeframe}"
        )

    minutes = (
        TIMEFRAME_MINUTES[
            timeframe
        ]
    )

    ticks = get_ticks(
        symbol,
        limit=50000,
    )

    if ticks.empty:

        return pd.DataFrame(
            columns=[
                "datetime",
                "open",
                "high",
                "low",
                "close",
                "volume",
            ]
        )

    work = ticks.set_index(
        "datetime"
    )

    rule = (
        f"{minutes}min"
    )

    ohlc = (
        work[
            "price"
        ]
        .resample(
            rule
        )
        .ohlc()
        .dropna()
        .reset_index()
    )

    if ohlc.empty:

        return pd.DataFrame(
            columns=[
                "datetime",
                "open",
                "high",
                "low",
                "close",
                "volume",
            ]
        )

    ohlc[
        "volume"
    ] = 0.0

    ohlc = (
        ohlc
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

    return ohlc


# ============================================================
# MULTI-TIMEFRAME CANDLES
# ============================================================

def get_metals_mtf_candles(
    symbol,
    limit=200,
):

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
# DATA READINESS
# ============================================================

def metals_ohlc_readiness(
    symbol,
):

    symbol = _normalize_symbol(
        symbol
    )

    result = {
        "symbol": symbol,
        "ready": False,
        "timeframes": {},
    }

    required = {
        "15m": 60,
        "1h": 60,
        "4h": 60,
    }

    all_ready = True

    for timeframe, minimum in (
        required.items()
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

            "ready":
                ready,
        }

        if not ready:

            all_ready = False

    result[
        "ready"
    ] = all_ready

    return result


# ============================================================
# HEALTH
# ============================================================

def metals_ohlc_health():

    try:

        ensure_metals_tables()

        return {
            "ok": True,
            "database": "ONLINE",
            "engine": (
                "V3.7 Local Metals OHLC"
            ),
        }

    except Exception as error:

        return {
            "ok": False,
            "database": "ERROR",
            "engine": (
                "V3.7 Local Metals OHLC"
            ),
            "reason": str(
                error
            ),
        }

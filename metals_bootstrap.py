"""
metals_bootstrap.py

PRO AI QUANT TERMINAL V3.8
PERSISTENT FREE-TIER METALS HISTORICAL BOOTSTRAP ENGINE

Purpose
-------
Bootstrap REAL historical Gold / Silver OHLC data into PostgreSQL
without inventing or synthesizing candles.

Provider
--------
Gold-API.com OHLC endpoint

Free-tier design
----------------
- Historical/OHLC API key required
- Respects provider rate limits
- Maximum 10 historical/OHLC requests per hour on free tier
- Persists every completed candle
- Resumes safely after Render restarts
- Never overwrites live trading state
- Never creates fake candles
- No real orders

Architecture
------------
Gold-API historical OHLC
        ↓
metals_seed_candles PostgreSQL table
        ↓
persistent history
        ↓
15m / 1h / 4h scanner bootstrap

Later:
Gold-API unlimited realtime price
        ↓
metals_ticks
        ↓
live/current candle continuation
"""

from __future__ import annotations

import os
import time
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional

import requests
import psycopg
from psycopg.rows import dict_row


# ============================================================
# CONFIG
# ============================================================

DATABASE_URL = os.environ.get(
    "DATABASE_URL",
    "",
).strip()

GOLD_API_KEY = os.environ.get(
    "GOLD_API_KEY",
    "",
).strip()

GOLD_API_BASE_URL = (
    "https://api.gold-api.com"
)

REQUEST_TIMEOUT = 15


# Gold-API free plan:
# 10 historical/OHLC requests per hour.
#
# We deliberately stay below that limit.
FREE_REQUESTS_PER_HOUR = 8

REQUEST_WINDOW_SECONDS = 3600


SUPPORTED_SYMBOLS = {
    "XAUUSD": "XAU",
    "XAGUSD": "XAG",
}


TIMEFRAMES = {
    "15m": 15,
    "1h": 60,
    "4h": 240,
}


# Scanner currently requires 60 candles per timeframe.
TARGET_CANDLES = {
    "15m": 60,
    "1h": 60,
    "4h": 60,
}


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


def ensure_bootstrap_tables():

    with _connect() as conn:

        with conn.cursor() as cur:

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

            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS
                metals_bootstrap_requests (
                    id BIGSERIAL PRIMARY KEY,

                    requested_at TIMESTAMPTZ NOT NULL
                        DEFAULT NOW(),

                    symbol TEXT,

                    timeframe TEXT,

                    success BOOLEAN NOT NULL
                        DEFAULT FALSE
                )
                """
            )

            cur.execute(
                """
                CREATE INDEX IF NOT EXISTS
                idx_metals_bootstrap_request_time

                ON metals_bootstrap_requests (
                    requested_at
                )
                """
            )

        conn.commit()


# ============================================================
# HELPERS
# ============================================================

def _utc_now():

    return datetime.now(
        timezone.utc
    )


def _normalize_symbol(
    symbol: str,
) -> str:

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
    timeframe: str,
) -> str:

    value = (
        str(timeframe)
        .lower()
        .strip()
    )

    aliases = {
        "15m": "15m",
        "15min": "15m",

        "1h": "1h",
        "60m": "1h",

        "4h": "4h",
        "240m": "4h",
    }

    normalized = aliases.get(
        value
    )

    if normalized not in TIMEFRAMES:

        raise ValueError(
            f"Unsupported timeframe: {timeframe}"
        )

    return normalized


def _safe_float(
    value,
    default=None,
):

    try:

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


# ============================================================
# FREE-TIER REQUEST BUDGET
# ============================================================

def requests_used_last_hour() -> int:

    ensure_bootstrap_tables()

    cutoff = (
        _utc_now()
        - timedelta(
            seconds=REQUEST_WINDOW_SECONDS
        )
    )

    with _connect() as conn:

        with conn.cursor() as cur:

            cur.execute(
                """
                SELECT COUNT(*) AS count
                FROM metals_bootstrap_requests
                WHERE requested_at >= %s
                """,
                (
                    cutoff,
                ),
            )

            row = cur.fetchone()

    return int(
        row["count"]
        if row
        else 0
    )


def historical_request_allowed() -> bool:

    return (
        requests_used_last_hour()
        < FREE_REQUESTS_PER_HOUR
    )


def _record_request(
    symbol: str,
    timeframe: str,
    success: bool,
):

    ensure_bootstrap_tables()

    with _connect() as conn:

        with conn.cursor() as cur:

            cur.execute(
                """
                INSERT INTO metals_bootstrap_requests (
                    requested_at,
                    symbol,
                    timeframe,
                    success
                )
                VALUES (
                    %s,
                    %s,
                    %s,
                    %s
                )
                """,
                (
                    _utc_now(),
                    symbol,
                    timeframe,
                    bool(
                        success
                    ),
                ),
            )

        conn.commit()


# ============================================================
# CANDLE STORAGE
# ============================================================

def stored_seed_count(
    symbol: str,
    timeframe: str,
) -> int:

    ensure_bootstrap_tables()

    symbol = _normalize_symbol(
        symbol
    )

    timeframe = _normalize_timeframe(
        timeframe
    )

    with _connect() as conn:

        with conn.cursor() as cur:

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

    return int(
        row["count"]
        if row
        else 0
    )


def _oldest_seed_start(
    symbol: str,
    timeframe: str,
) -> Optional[datetime]:

    ensure_bootstrap_tables()

    with _connect() as conn:

        with conn.cursor() as cur:

            cur.execute(
                """
                SELECT MIN(
                    candle_start
                ) AS oldest

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

    if not row:

        return None

    return row.get(
        "oldest"
    )


def store_seed_candle(
    symbol: str,
    timeframe: str,
    candle_start: datetime,
    candle_end: datetime,
    open_price: float,
    high_price: float,
    low_price: float,
    close_price: float,
) -> bool:

    symbol = _normalize_symbol(
        symbol
    )

    timeframe = _normalize_timeframe(
        timeframe
    )

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
        high_price < low_price
        or high_price < open_price
        or high_price < close_price
        or low_price > open_price
        or low_price > close_price
    ):

        return False

    ensure_bootstrap_tables()

    with _connect() as conn:

        with conn.cursor() as cur:

            cur.execute(
                """
                INSERT INTO metals_seed_candles (
                    symbol,
                    timeframe,
                    candle_start,
                    candle_end,
                    open,
                    high,
                    low,
                    close,
                    provider
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
                    %s
                )

                ON CONFLICT (
                    symbol,
                    timeframe,
                    candle_start
                )

                DO NOTHING
                """,
                (
                    symbol,
                    timeframe,
                    candle_start,
                    candle_end,
                    open_price,
                    high_price,
                    low_price,
                    close_price,
                    "Gold-API",
                ),
            )

            inserted = (
                cur.rowcount
                > 0
            )

        conn.commit()

    return inserted


# ============================================================
# NEXT HISTORICAL SEGMENT
# ============================================================

def next_bootstrap_range(
    symbol: str,
    timeframe: str,
):

    symbol = _normalize_symbol(
        symbol
    )

    timeframe = _normalize_timeframe(
        timeframe
    )

    minutes = TIMEFRAMES[
        timeframe
    ]

    duration = timedelta(
        minutes=minutes
    )

    oldest = _oldest_seed_start(
        symbol,
        timeframe,
    )

    if oldest is None:

        # Never use the currently forming candle.
        end = (
            _utc_now()
            - duration
        )

    else:

        end = oldest

    start = (
        end
        - duration
    )

    return (
        start,
        end,
    )


# ============================================================
# GOLD-API OHLC REQUEST
# ============================================================

def fetch_gold_api_ohlc(
    symbol: str,
    timeframe: str,
) -> Dict:

    if not GOLD_API_KEY:

        return {
            "ok": False,
            "reason": (
                "GOLD_API_KEY is not configured."
            ),
        }

    symbol = _normalize_symbol(
        symbol
    )

    timeframe = _normalize_timeframe(
        timeframe
    )

    if not historical_request_allowed():

        return {
            "ok": False,
            "rate_limited_locally": True,
            "reason": (
                "Free historical request budget "
                "for this hour has been reached."
            ),
        }

    provider_symbol = (
        SUPPORTED_SYMBOLS[
            symbol
        ]
    )

    start, end = (
        next_bootstrap_range(
            symbol,
            timeframe,
        )
    )

    url = (
        f"{GOLD_API_BASE_URL}"
        f"/ohlc/{provider_symbol}"
    )

    params = {
        "startTimestamp":
            int(
                start.timestamp()
            ),

        "endTimestamp":
            int(
                end.timestamp()
            ),
    }

    headers = {
        "Accept":
            "application/json",

        "x-api-key":
            GOLD_API_KEY,

        "User-Agent":
            "pro-ai-quant-terminal-v3.8",
    }

    success = False

    try:

        response = requests.get(
            url,
            params=params,
            headers=headers,
            timeout=REQUEST_TIMEOUT,
        )

        if response.status_code == 429:

            return {
                "ok": False,
                "provider_rate_limited": True,
                "reason": (
                    "Gold-API historical rate limit reached."
                ),
            }

        if not response.ok:

            return {
                "ok": False,
                "status_code":
                    response.status_code,

                "reason":
                    response.text[
                        :500
                    ],
            }

        payload = (
            response.json()
        )

        if not isinstance(
            payload,
            dict,
        ):

            return {
                "ok": False,
                "reason": (
                    "Invalid Gold-API OHLC response."
                ),
            }

        open_price = _safe_float(
            payload.get(
                "open"
            )
        )

        high_price = _safe_float(
            payload.get(
                "high"
            )
        )

        low_price = _safe_float(
            payload.get(
                "low"
            )
        )

        close_price = _safe_float(
            payload.get(
                "close"
            )
        )

        if None in (
            open_price,
            high_price,
            low_price,
            close_price,
        ):

            return {
                "ok": False,
                "reason": (
                    "Gold-API returned unusable OHLC."
                ),
                "payload":
                    payload,
            }

        inserted = (
            store_seed_candle(
                symbol=symbol,
                timeframe=timeframe,
                candle_start=start,
                candle_end=end,
                open_price=open_price,
                high_price=high_price,
                low_price=low_price,
                close_price=close_price,
            )
        )

        success = True

        return {
            "ok": True,
            "symbol": symbol,
            "timeframe": timeframe,
            "start": start.isoformat(),
            "end": end.isoformat(),
            "inserted": inserted,
            "ohlc": {
                "open": open_price,
                "high": high_price,
                "low": low_price,
                "close": close_price,
            },
        }

    except Exception as error:

        return {
            "ok": False,
            "reason": str(
                error
            ),
        }

    finally:

        _record_request(
            symbol=symbol,
            timeframe=timeframe,
            success=success,
        )


# ============================================================
# BOOTSTRAP PRIORITY
# ============================================================

def _bootstrap_priority() -> List:

    """
    Prioritize higher timeframes first because
    they take longest to accumulate naturally.
    """

    return [
        ("XAUUSD", "4h"),
        ("XAGUSD", "4h"),

        ("XAUUSD", "1h"),
        ("XAGUSD", "1h"),

        ("XAUUSD", "15m"),
        ("XAGUSD", "15m"),
    ]


# ============================================================
# ONE SAFE BOOTSTRAP CYCLE
# ============================================================

def run_bootstrap_cycle(
    max_requests: int = 4,
) -> Dict:

    ensure_bootstrap_tables()

    try:

        max_requests = int(
            max_requests
        )

    except (
        TypeError,
        ValueError,
    ):

        max_requests = 4

    max_requests = max(
        1,
        min(
            max_requests,
            FREE_REQUESTS_PER_HOUR,
        ),
    )

    results = []

    requests_made = 0

    for symbol, timeframe in (
        _bootstrap_priority()
    ):

        if requests_made >= max_requests:
            break

        current_count = (
            stored_seed_count(
                symbol,
                timeframe,
            )
        )

        target = (
            TARGET_CANDLES[
                timeframe
            ]
        )

        if current_count >= target:
            continue

        if not historical_request_allowed():

            break

        result = (
            fetch_gold_api_ohlc(
                symbol,
                timeframe,
            )
        )

        results.append(
            result
        )

        if not result.get(
            "rate_limited_locally",
            False,
        ):

            requests_made += 1

        if (
            result.get(
                "provider_rate_limited",
                False,
            )
        ):

            break

        time.sleep(
            1.0
        )

    return {
        "ok": True,
        "requests_made": requests_made,
        "requests_used_last_hour":
            requests_used_last_hour(),
        "hourly_budget":
            FREE_REQUESTS_PER_HOUR,
        "results": results,
        "status":
            bootstrap_status(),
    }


# ============================================================
# STATUS
# ============================================================

def bootstrap_status() -> Dict:

    ensure_bootstrap_tables()

    markets = {}

    all_ready = True

    for symbol in SUPPORTED_SYMBOLS:

        markets[
            symbol
        ] = {}

        for timeframe in TIMEFRAMES:

            count = (
                stored_seed_count(
                    symbol,
                    timeframe,
                )
            )

            target = (
                TARGET_CANDLES[
                    timeframe
                ]
            )

            ready = (
                count >= target
            )

            markets[
                symbol
            ][
                timeframe
            ] = {
                "candles":
                    count,

                "target":
                    target,

                "remaining":
                    max(
                        0,
                        target - count,
                    ),

                "ready":
                    ready,
            }

            if not ready:

                all_ready = False

    return {
        "ready":
            all_ready,

        "markets":
            markets,

        "requests_used_last_hour":
            requests_used_last_hour(),

        "hourly_budget":
            FREE_REQUESTS_PER_HOUR,

        "provider":
            "Gold-API",

        "historical_mode":
            "FREE_TIER_SAFE",

        "real_orders":
            False,
    }


# ============================================================
# HEALTH
# ============================================================

def metals_bootstrap_health() -> Dict:

    try:

        ensure_bootstrap_tables()

        return {
            "ok":
                True,

            "database":
                "ONLINE",

            "api_key":
                bool(
                    GOLD_API_KEY
                ),

            "provider":
                "Gold-API",

            "free_tier_limit":
                "10 historical/OHLC requests per hour",

            "internal_safety_limit":
                FREE_REQUESTS_PER_HOUR,

            "status":
                bootstrap_status(),

            "real_orders":
                False,
        }

    except Exception as error:

        return {
            "ok":
                False,

            "reason":
                str(
                    error
                ),

            "real_orders":
                False,
        }

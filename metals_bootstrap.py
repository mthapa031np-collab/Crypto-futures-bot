"""
metals_bootstrap.py

PRO AI QUANT TERMINAL V4.3
HYBRID FREE-TIER METALS HISTORICAL BOOTSTRAP ENGINE

IMPORTANT DESIGN
----------------
Initial warm-up:
    XAUUSD + XAGUSD
        ×
    15m + 1h + 4h
        ×
    60 valid historical OHLC candles

Why?
----
Gold-API /ohlc returns ONE OHLC segment per request.
Bootstrapping 4h from 15m alone would require far more
historical API requests.

Therefore:

INITIAL BOOTSTRAP
    Gold-API OHLC
        ↓
    Real 15m / 1h / 4h seed candles
        ↓
    PostgreSQL

AFTER WARM-UP
    Gold-API realtime quotes
        ↓
    Local canonical 15m
        ↓
    Local 1h / 4h resampling

This keeps initial warm-up efficient while future operation
becomes increasingly independent of historical API requests.

Safety
------
- Free-tier aware
- Internal ceiling: 8 historical calls/hour
- Persistent progress
- Restart-safe cursors
- Weekend / closed-session skip protection
- Duplicate-safe
- Never creates synthetic historical prices
- PAPER ONLY
- NO REAL ORDERS
"""

from __future__ import annotations

import os
import time
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional, Tuple

import psycopg
from psycopg.rows import dict_row
import requests


# ============================================================
# ENVIRONMENT
# ============================================================

DATABASE_URL = os.environ.get(
    "DATABASE_URL",
    "",
).strip()

GOLD_API_KEY = os.environ.get(
    "GOLD_API_KEY",
    "",
).strip()


# ============================================================
# PROVIDER
# ============================================================

GOLD_API_BASE_URL = (
    "https://api.gold-api.com"
)

REQUEST_TIMEOUT = 15


# Provider free tier = 10 history/OHLC calls per hour.
# Keep a safety margin.
INTERNAL_REQUEST_LIMIT_PER_HOUR = 8


# ============================================================
# MARKETS
# ============================================================

SUPPORTED_SYMBOLS = {
    "XAUUSD": "XAU",
    "XAGUSD": "XAG",
}


TIMEFRAME_MINUTES = {
    "15m": 15,
    "1h": 60,
    "4h": 240,
}


TARGET_CANDLES = {
    "15m": 60,
    "1h": 60,
    "4h": 60,
}


# ============================================================
# HELPERS
# ============================================================

def _utc_now() -> datetime:

    return datetime.now(
        timezone.utc
    )


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

        if number <= 0:
            return default

        return number

    except (
        TypeError,
        ValueError,
    ):

        return default


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

    normalized = aliases.get(
        value
    )

    if normalized not in TIMEFRAME_MINUTES:

        raise ValueError(
            f"Unsupported metals timeframe: {timeframe}"
        )

    return normalized


def _timeframe_duration(
    timeframe: str,
) -> timedelta:

    timeframe = _normalize_timeframe(
        timeframe
    )

    return timedelta(
        minutes=TIMEFRAME_MINUTES[
            timeframe
        ]
    )


def _latest_closed_boundary(
    timeframe: str,
) -> datetime:

    timeframe = _normalize_timeframe(
        timeframe
    )

    minutes = TIMEFRAME_MINUTES[
        timeframe
    ]

    now = _utc_now()

    total_minutes = (
        now.hour * 60
        + now.minute
    )

    floored_minutes = (
        total_minutes
        // minutes
        * minutes
    )

    day_start = now.replace(
        hour=0,
        minute=0,
        second=0,
        microsecond=0,
    )

    return (
        day_start
        + timedelta(
            minutes=floored_minutes
        )
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
# TABLE SETUP
# ============================================================

def ensure_bootstrap_tables():

    with _connect() as conn:

        with conn.cursor() as cur:

            # ------------------------------------------------
            # CANDLES
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

            # ------------------------------------------------
            # REQUEST HISTORY
            # ------------------------------------------------

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
                        DEFAULT FALSE,

                    result_type TEXT
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

            # ------------------------------------------------
            # PERSISTENT BACKFILL CURSOR
            #
            # Crucial for restart safety and weekend/no-data
            # intervals.
            # ------------------------------------------------

            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS
                metals_bootstrap_cursor (
                    symbol TEXT NOT NULL,
                    timeframe TEXT NOT NULL,

                    next_end TIMESTAMPTZ NOT NULL,

                    updated_at TIMESTAMPTZ NOT NULL
                        DEFAULT NOW(),

                    PRIMARY KEY (
                        symbol,
                        timeframe
                    )
                )
                """
            )

        conn.commit()


# ============================================================
# REQUEST ACCOUNTING
# ============================================================

def requests_used_last_hour() -> int:

    ensure_bootstrap_tables()

    cutoff = (
        _utc_now()
        - timedelta(
            hours=1
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
        < INTERNAL_REQUEST_LIMIT_PER_HOUR
    )


def _record_request(
    symbol: str,
    timeframe: str,
    success: bool,
    result_type: str,
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
                    success,
                    result_type
                )

                VALUES (
                    %s,
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
                    bool(success),
                    str(result_type),
                ),
            )

        conn.commit()


# ============================================================
# STORED HISTORY
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


# ============================================================
# PERSISTENT CURSOR
# ============================================================

def _get_cursor(
    symbol: str,
    timeframe: str,
) -> datetime:

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
                SELECT next_end

                FROM metals_bootstrap_cursor

                WHERE symbol = %s
                  AND timeframe = %s
                """,
                (
                    symbol,
                    timeframe,
                ),
            )

            row = cur.fetchone()

    if row:

        return row[
            "next_end"
        ]

    # ---------------------------------------------
    # Preserve old bootstrap progress.
    # ---------------------------------------------

    oldest = _oldest_seed_start(
        symbol,
        timeframe,
    )

    if oldest is not None:

        initial_end = oldest

    else:

        initial_end = (
            _latest_closed_boundary(
                timeframe
            )
        )

    _set_cursor(
        symbol,
        timeframe,
        initial_end,
    )

    return initial_end


def _set_cursor(
    symbol: str,
    timeframe: str,
    next_end: datetime,
):

    ensure_bootstrap_tables()

    with _connect() as conn:

        with conn.cursor() as cur:

            cur.execute(
                """
                INSERT INTO metals_bootstrap_cursor (
                    symbol,
                    timeframe,
                    next_end,
                    updated_at
                )

                VALUES (
                    %s,
                    %s,
                    %s,
                    NOW()
                )

                ON CONFLICT (
                    symbol,
                    timeframe
                )

                DO UPDATE SET
                    next_end =
                        EXCLUDED.next_end,

                    updated_at =
                        NOW()
                """,
                (
                    symbol,
                    timeframe,
                    next_end,
                ),
            )

        conn.commit()


# ============================================================
# NEXT SEGMENT
# ============================================================

def next_bootstrap_range(
    symbol: str,
    timeframe: str,
) -> Tuple[
    datetime,
    datetime,
]:

    symbol = _normalize_symbol(
        symbol
    )

    timeframe = _normalize_timeframe(
        timeframe
    )

    end = _get_cursor(
        symbol,
        timeframe,
    )

    duration = (
        _timeframe_duration(
            timeframe
        )
    )

    start = (
        end
        - duration
    )

    return (
        start,
        end,
    )


# ============================================================
# STORE REAL HISTORICAL CANDLE
# ============================================================

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
# GOLD-API OHLC REQUEST
# ============================================================

def fetch_gold_api_ohlc(
    symbol: str,
    timeframe: str,
) -> Dict:

    if not GOLD_API_KEY:

        return {
            "ok":
                False,

            "reason":
                "GOLD_API_KEY is not configured.",
        }

    symbol = _normalize_symbol(
        symbol
    )

    timeframe = _normalize_timeframe(
        timeframe
    )

    if (
        stored_seed_count(
            symbol,
            timeframe,
        )
        >= TARGET_CANDLES[
            timeframe
        ]
    ):

        return {
            "ok":
                True,

            "complete":
                True,

            "symbol":
                symbol,

            "timeframe":
                timeframe,

            "reason":
                "Target already reached.",
        }

    if not historical_request_allowed():

        return {
            "ok":
                False,

            "rate_limited_locally":
                True,

            "reason":
                (
                    "Internal hourly historical "
                    "API budget reached."
                ),
        }

    provider_symbol = (
        SUPPORTED_SYMBOLS[
            symbol
        ]
    )

    start, end = next_bootstrap_range(
        symbol,
        timeframe,
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
            "pro-ai-quant-terminal-v4.3",
    }

    provider_request_sent = False

    try:

        provider_request_sent = True

        response = requests.get(
            url,
            params=params,
            headers=headers,
            timeout=REQUEST_TIMEOUT,
        )

        # ---------------------------------------------
        # RATE LIMIT
        # ---------------------------------------------

        if response.status_code == 429:

            _record_request(
                symbol,
                timeframe,
                False,
                "PROVIDER_RATE_LIMIT",
            )

            return {
                "ok":
                    False,

                "provider_rate_limited":
                    True,

                "reason":
                    "Gold-API rate limit reached.",
            }

        # ---------------------------------------------
        # HTTP FAILURE
        # ---------------------------------------------

        if not response.ok:

            _record_request(
                symbol,
                timeframe,
                False,
                f"HTTP_{response.status_code}",
            )

            return {
                "ok":
                    False,

                "status_code":
                    response.status_code,

                "reason":
                    response.text[:500],
            }

        payload = response.json()

        if not isinstance(
            payload,
            dict,
        ):

            _record_request(
                symbol,
                timeframe,
                False,
                "INVALID_JSON",
            )

            # Valid provider response path but no usable
            # OHLC. Move backward so worker cannot become
            # permanently stuck on one interval.
            _set_cursor(
                symbol,
                timeframe,
                start,
            )

            return {
                "ok":
                    False,

                "skipped_interval":
                    True,

                "reason":
                    "Invalid OHLC response.",
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

        # ---------------------------------------------
        # CLOSED MARKET / NO USABLE DATA
        # ---------------------------------------------

        if None in (
            open_price,
            high_price,
            low_price,
            close_price,
        ):

            _record_request(
                symbol,
                timeframe,
                False,
                "NO_USABLE_OHLC",
            )

            # Skip this real calendar segment.
            # Important for weekends / closures.
            _set_cursor(
                symbol,
                timeframe,
                start,
            )

            return {
                "ok":
                    False,

                "skipped_interval":
                    True,

                "symbol":
                    symbol,

                "timeframe":
                    timeframe,

                "start":
                    start.isoformat(),

                "end":
                    end.isoformat(),

                "reason":
                    "No usable OHLC for segment.",
            }

        inserted = store_seed_candle(
            symbol=symbol,
            timeframe=timeframe,
            candle_start=start,
            candle_end=end,
            open_price=open_price,
            high_price=high_price,
            low_price=low_price,
            close_price=close_price,
        )

        # Always advance after a valid provider segment,
        # including duplicate data.
        _set_cursor(
            symbol,
            timeframe,
            start,
        )

        _record_request(
            symbol,
            timeframe,
            True,
            (
                "INSERTED"
                if inserted
                else "DUPLICATE"
            ),
        )

        return {
            "ok":
                True,

            "symbol":
                symbol,

            "timeframe":
                timeframe,

            "start":
                start.isoformat(),

            "end":
                end.isoformat(),

            "inserted":
                inserted,

            "stored_count":
                stored_seed_count(
                    symbol,
                    timeframe,
                ),

            "target":
                TARGET_CANDLES[
                    timeframe
                ],

            "ohlc":
                {
                    "open":
                        open_price,

                    "high":
                        high_price,

                    "low":
                        low_price,

                    "close":
                        close_price,
                },
        }

    except requests.Timeout:

        if provider_request_sent:

            _record_request(
                symbol,
                timeframe,
                False,
                "TIMEOUT",
            )

        return {
            "ok":
                False,

            "reason":
                "Gold-API request timed out.",
        }

    except Exception as error:

        if provider_request_sent:

            _record_request(
                symbol,
                timeframe,
                False,
                "EXCEPTION",
            )

        return {
            "ok":
                False,

            "reason":
                str(error),
        }


# ============================================================
# FAIR BOOTSTRAP PRIORITY
# ============================================================

def _bootstrap_candidates() -> List[Dict]:

    candidates = []

    # Higher timeframe gets a small tie-break advantage,
    # but completion percentage is always primary.
    timeframe_priority = {
        "4h": 0,
        "1h": 1,
        "15m": 2,
    }

    symbol_priority = {
        "XAUUSD": 0,
        "XAGUSD": 1,
    }

    for symbol in (
        "XAUUSD",
        "XAGUSD",
    ):

        for timeframe in (
            "4h",
            "1h",
            "15m",
        ):

            count = stored_seed_count(
                symbol,
                timeframe,
            )

            target = TARGET_CANDLES[
                timeframe
            ]

            if count >= target:

                continue

            completion = (
                count / target
                if target > 0
                else 1.0
            )

            candidates.append(
                {
                    "symbol":
                        symbol,

                    "timeframe":
                        timeframe,

                    "count":
                        count,

                    "target":
                        target,

                    "completion":
                        completion,

                    "timeframe_priority":
                        timeframe_priority[
                            timeframe
                        ],

                    "symbol_priority":
                        symbol_priority[
                            symbol
                        ],
                }
            )

    candidates.sort(
        key=lambda item: (
            item[
                "completion"
            ],

            item[
                "timeframe_priority"
            ],

            item[
                "symbol_priority"
            ],
        )
    )

    return candidates


# ============================================================
# ONE SAFE BOOTSTRAP CYCLE
# ============================================================

def run_bootstrap_cycle(
    max_requests: int = 2,
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

        max_requests = 2

    max_requests = max(
        1,
        min(
            max_requests,
            INTERNAL_REQUEST_LIMIT_PER_HOUR,
        ),
    )

    results = []

    requests_before = (
        requests_used_last_hour()
    )

    available_budget = max(
        0,
        INTERNAL_REQUEST_LIMIT_PER_HOUR
        - requests_before,
    )

    request_budget = min(
        max_requests,
        available_budget,
    )

    if request_budget <= 0:

        return {
            "ok":
                True,

            "requests_made":
                0,

            "budget_exhausted":
                True,

            "requests_used_last_hour":
                requests_before,

            "hourly_budget":
                INTERNAL_REQUEST_LIMIT_PER_HOUR,

            "results":
                [],

            "status":
                bootstrap_status(),
        }

    requests_made = 0

    while (
        requests_made
        < request_budget
    ):

        candidates = (
            _bootstrap_candidates()
        )

        if not candidates:

            break

        selected = candidates[
            0
        ]

        result = fetch_gold_api_ohlc(
            selected[
                "symbol"
            ],
            selected[
                "timeframe"
            ],
        )

        results.append(
            result
        )

        # Only actual provider attempts count here.
        if not result.get(
            "rate_limited_locally",
            False,
        ):

            requests_made += 1

        if result.get(
            "provider_rate_limited",
            False,
        ):

            break

        if result.get(
            "rate_limited_locally",
            False,
        ):

            break

        time.sleep(
            1.0
        )

    return {
        "ok":
            True,

        "requests_made":
            requests_made,

        "budget_exhausted":
            (
                requests_used_last_hour()
                >= INTERNAL_REQUEST_LIMIT_PER_HOUR
            ),

        "requests_used_last_hour":
            requests_used_last_hour(),

        "hourly_budget":
            INTERNAL_REQUEST_LIMIT_PER_HOUR,

        "results":
            results,

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

    total_valid = 0
    total_target = 0

    for symbol in SUPPORTED_SYMBOLS:

        markets[
            symbol
        ] = {}

        for timeframe in (
            "15m",
            "1h",
            "4h",
        ):

            count = stored_seed_count(
                symbol,
                timeframe,
            )

            target = TARGET_CANDLES[
                timeframe
            ]

            ready = (
                count >= target
            )

            total_valid += min(
                count,
                target,
            )

            total_target += target

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

    progress_pct = 0.0

    if total_target > 0:

        progress_pct = (
            total_valid
            / total_target
            * 100
        )

    return {
        "ready":
            all_ready,

        "progress_pct":
            round(
                progress_pct,
                2,
            ),

        "markets":
            markets,

        "requests_used_last_hour":
            requests_used_last_hour(),

        "hourly_budget":
            INTERNAL_REQUEST_LIMIT_PER_HOUR,

        "provider":
            "Gold-API",

        "bootstrap_mode":
            "DIRECT_INITIAL_15M_1H_4H",

        "post_bootstrap_mode":
            "REALTIME_15M_PLUS_LOCAL_RESAMPLE",

        "paper_only":
            True,

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

            "api_key_configured":
                bool(
                    GOLD_API_KEY
                ),

            "provider":
                "Gold-API",

            "provider_free_limit":
                "10 History/OHLC requests/hour",

            "internal_limit":
                INTERNAL_REQUEST_LIMIT_PER_HOUR,

            "restart_safe":
                True,

            "persistent_cursor":
                True,

            "duplicate_protection":
                True,

            "closed_session_skip":
                True,

            "status":
                bootstrap_status(),

            "paper_only":
                True,

            "real_orders":
                False,
        }

    except Exception as error:

        return {
            "ok":
                False,

            "reason":
                str(error),

            "paper_only":
                True,

            "real_orders":
                False,
        }

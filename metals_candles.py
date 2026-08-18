"""
metals_candles.py

PRO AI QUANT TERMINAL V3.7

Quota-Safe Historical / Intraday Candle Provider for Metals.

Provider:
    Twelve Data

Supported:
    XAUUSD -> XAU/USD
    XAGUSD -> XAG/USD

Timeframes:
    15m
    1h
    4h
    1day

Features:
- Candle caching
- 429 / API-credit protection
- Provider cooldown
- Last-good candle preservation
- Duplicate log suppression
- MTF-safe fetching
- Paper trading only

Environment variable required:
    TWELVE_DATA_API_KEY

Optional environment variables:
    METALS_CANDLE_CACHE_SECONDS
    METALS_CANDLE_STALE_SECONDS
    METALS_CANDLE_COOLDOWN_SECONDS
    METALS_CANDLE_LOG_SECONDS
"""

import os
import time
import threading
from copy import deepcopy
from typing import Dict

import requests
import pandas as pd


# ============================================================
# CONFIG
# ============================================================

TWELVE_DATA_API_KEY = os.environ.get(
    "TWELVE_DATA_API_KEY",
    "",
).strip()

BASE_URL = (
    "https://api.twelvedata.com/time_series"
)

REQUEST_TIMEOUT = 15


METALS_CANDLE_CACHE_SECONDS = int(
    os.environ.get(
        "METALS_CANDLE_CACHE_SECONDS",
        "300",
    )
)

METALS_CANDLE_STALE_SECONDS = int(
    os.environ.get(
        "METALS_CANDLE_STALE_SECONDS",
        "1800",
    )
)

METALS_CANDLE_COOLDOWN_SECONDS = int(
    os.environ.get(
        "METALS_CANDLE_COOLDOWN_SECONDS",
        "600",
    )
)

METALS_CANDLE_LOG_SECONDS = int(
    os.environ.get(
        "METALS_CANDLE_LOG_SECONDS",
        "300",
    )
)


# ============================================================
# SYMBOL MAP
# ============================================================

SYMBOL_MAP = {
    "XAUUSD": "XAU/USD",
    "XAGUSD": "XAG/USD",
}


# ============================================================
# TIMEFRAME MAP
# ============================================================

TIMEFRAME_MAP = {
    "15m": "15min",
    "15min": "15min",

    "1h": "1h",
    "60m": "1h",

    "4h": "4h",
    "240m": "4h",

    "1d": "1day",
    "1day": "1day",
}


# ============================================================
# RUNTIME STATE
# ============================================================

_state_lock = threading.RLock()

_candle_cache = {}

_last_good_candles = {}

_provider_cooldown_until = 0.0

_last_error_logs = {}


# ============================================================
# TIME HELPERS
# ============================================================

def _now() -> float:
    return time.monotonic()


def _age(
    timestamp: float,
) -> float:

    if not timestamp:
        return float("inf")

    return max(
        0.0,
        _now() - timestamp,
    )


# ============================================================
# LOG THROTTLING
# ============================================================

def _log_once(
    key: str,
    message: str,
    interval: int = None,
):

    if interval is None:
        interval = (
            METALS_CANDLE_LOG_SECONDS
        )

    current = _now()

    with _state_lock:

        previous = (
            _last_error_logs.get(
                key,
                0.0,
            )
        )

        if (
            current - previous
            < interval
        ):
            return

        _last_error_logs[
            key
        ] = current

    print(
        message,
        flush=True,
    )


# ============================================================
# PROVIDER COOLDOWN
# ============================================================

def _provider_available() -> bool:

    with _state_lock:

        cooldown_until = (
            _provider_cooldown_until
        )

    return (
        _now()
        >= cooldown_until
    )


def _set_provider_cooldown(
    seconds: int,
):

    global _provider_cooldown_until

    with _state_lock:

        _provider_cooldown_until = max(
            _provider_cooldown_until,
            _now()
            + max(
                1,
                int(seconds),
            ),
        )


def _provider_cooldown_remaining() -> int:

    with _state_lock:

        remaining = (
            _provider_cooldown_until
            - _now()
        )

    return max(
        0,
        int(
            remaining
        ),
    )


# ============================================================
# HELPERS
# ============================================================

def _normalize_symbol(
    symbol: str,
) -> str:

    return (
        str(symbol)
        .upper()
        .replace("/", "")
        .replace("-", "")
        .replace(" ", "")
        .strip()
    )


def _normalize_timeframe(
    timeframe: str,
) -> str:

    timeframe = (
        str(timeframe)
        .lower()
        .strip()
    )

    if timeframe not in TIMEFRAME_MAP:

        raise ValueError(
            f"Unsupported metals timeframe: "
            f"{timeframe}"
        )

    return TIMEFRAME_MAP[
        timeframe
    ]


def _require_api_key():

    if not TWELVE_DATA_API_KEY:

        raise RuntimeError(
            "TWELVE_DATA_API_KEY "
            "is not configured."
        )


def _cache_key(
    symbol: str,
    timeframe: str,
    outputsize: int,
) -> str:

    normalized_symbol = (
        _normalize_symbol(
            symbol
        )
    )

    interval = (
        _normalize_timeframe(
            timeframe
        )
    )

    return (
        f"{normalized_symbol}:"
        f"{interval}:"
        f"{int(outputsize)}"
    )


def _copy_df(
    df: pd.DataFrame,
) -> pd.DataFrame:

    if df is None:
        return pd.DataFrame()

    return df.copy(
        deep=True
    )


# ============================================================
# CACHE HELPERS
# ============================================================

def _get_fresh_cached_candles(
    key: str,
) -> pd.DataFrame:

    with _state_lock:

        record = (
            _candle_cache.get(
                key
            )
        )

        if not record:
            return pd.DataFrame()

        timestamp = record.get(
            "timestamp",
            0.0,
        )

        if (
            _age(timestamp)
            > METALS_CANDLE_CACHE_SECONDS
        ):
            return pd.DataFrame()

        df = _copy_df(
            record.get(
                "df"
            )
        )

    return df


def _store_good_candles(
    key: str,
    df: pd.DataFrame,
):

    if (
        df is None
        or df.empty
    ):
        return

    record = {
        "timestamp":
            _now(),

        "df":
            _copy_df(
                df
            ),
    }

    with _state_lock:

        _candle_cache[
            key
        ] = deepcopy(
            record
        )

        _last_good_candles[
            key
        ] = deepcopy(
            record
        )


def _get_last_good_candles(
    key: str,
) -> pd.DataFrame:

    with _state_lock:

        record = (
            _last_good_candles.get(
                key
            )
        )

        if not record:
            return pd.DataFrame()

        timestamp = record.get(
            "timestamp",
            0.0,
        )

        if (
            _age(timestamp)
            > METALS_CANDLE_STALE_SECONDS
        ):
            return pd.DataFrame()

        df = _copy_df(
            record.get(
                "df"
            )
        )

    return df


# ============================================================
# RATE LIMIT DETECTION
# ============================================================

def _looks_like_rate_limit(
    status_code: int,
    body,
) -> bool:

    if status_code == 429:
        return True

    text = str(
        body
    ).lower()

    markers = (
        "too many requests",
        "api credits",
        "credits",
        "rate limit",
        "run out",
        "limit being",
    )

    return any(
        marker in text
        for marker in markers
    )


# ============================================================
# FETCH RAW CANDLES
# ============================================================

def get_metals_candles_raw(
    symbol: str,
    timeframe: str = "15m",
    outputsize: int = 200,
) -> Dict:

    _require_api_key()

    normalized_symbol = (
        _normalize_symbol(
            symbol
        )
    )

    if normalized_symbol not in SYMBOL_MAP:

        raise ValueError(
            f"Unsupported metal symbol: "
            f"{symbol}"
        )

    interval = (
        _normalize_timeframe(
            timeframe
        )
    )

    if not _provider_available():

        remaining = (
            _provider_cooldown_remaining()
        )

        raise RuntimeError(
            "Twelve Data candle provider "
            "temporarily paused for "
            "rate-limit protection "
            f"({remaining}s remaining)."
        )

    params = {
        "symbol":
            SYMBOL_MAP[
                normalized_symbol
            ],

        "interval":
            interval,

        "outputsize":
            int(
                outputsize
            ),

        "apikey":
            TWELVE_DATA_API_KEY,

        "format":
            "JSON",
    }

    try:

        response = requests.get(
            BASE_URL,
            params=params,
            timeout=REQUEST_TIMEOUT,
        )

    except requests.RequestException as error:

        _set_provider_cooldown(
            METALS_CANDLE_COOLDOWN_SECONDS
        )

        raise RuntimeError(
            "Twelve Data candle "
            f"network error: {error}"
        ) from error

    if not response.ok:

        try:

            body = (
                response.json()
            )

        except Exception:

            body = (
                response.text[:500]
            )

        if _looks_like_rate_limit(
            response.status_code,
            body,
        ):

            _set_provider_cooldown(
                METALS_CANDLE_COOLDOWN_SECONDS
            )

            raise RuntimeError(
                "Twelve Data candle "
                "rate/API-credit limit reached. "
                "Provider paused automatically."
            )

        raise RuntimeError(
            "Twelve Data HTTP "
            f"{response.status_code}: "
            f"{body}"
        )

    try:

        data = response.json()

    except Exception as error:

        raise RuntimeError(
            "Invalid Twelve Data "
            "JSON response."
        ) from error

    if not isinstance(
        data,
        dict,
    ):

        raise RuntimeError(
            "Invalid Twelve Data response."
        )

    if (
        str(
            data.get(
                "status",
                ""
            )
        ).lower()
        == "error"
    ):

        if _looks_like_rate_limit(
            200,
            data,
        ):

            _set_provider_cooldown(
                METALS_CANDLE_COOLDOWN_SECONDS
            )

        raise RuntimeError(
            data.get(
                "message",
                "Twelve Data API error",
            )
        )

    return data


# ============================================================
# PARSE TO DATAFRAME
# ============================================================

def parse_metals_candles(
    payload: Dict,
) -> pd.DataFrame:

    values = payload.get(
        "values"
    )

    if not values:

        return pd.DataFrame()

    df = pd.DataFrame(
        values
    )

    required_columns = [
        "datetime",
        "open",
        "high",
        "low",
        "close",
    ]

    for column in required_columns:

        if column not in df.columns:

            return pd.DataFrame()

    df[
        "datetime"
    ] = pd.to_datetime(
        df[
            "datetime"
        ],
        utc=True,
        errors="coerce",
    )

    numeric_columns = [
        "open",
        "high",
        "low",
        "close",
    ]

    if "volume" in df.columns:

        numeric_columns.append(
            "volume"
        )

    for column in numeric_columns:

        df[
            column
        ] = pd.to_numeric(
            df[
                column
            ],
            errors="coerce",
        )

    df = (
        df
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
            "datetime"
        )
        .reset_index(
            drop=True
        )
    )

    return df


# ============================================================
# PUBLIC CANDLE FUNCTION
# ============================================================

def get_metals_candles(
    symbol: str,
    timeframe: str = "15m",
    outputsize: int = 200,
) -> pd.DataFrame:

    key = _cache_key(
        symbol,
        timeframe,
        outputsize,
    )

    # --------------------------------------------------------
    # 1. Fresh cache
    # --------------------------------------------------------

    cached = (
        _get_fresh_cached_candles(
            key
        )
    )

    if not cached.empty:
        return cached

    # --------------------------------------------------------
    # 2. Provider call
    # --------------------------------------------------------

    if _provider_available():

        try:

            raw = (
                get_metals_candles_raw(
                    symbol=symbol,
                    timeframe=timeframe,
                    outputsize=outputsize,
                )
            )

            df = (
                parse_metals_candles(
                    raw
                )
            )

            if not df.empty:

                _store_good_candles(
                    key,
                    df,
                )

                return df

        except Exception as error:

            _log_once(
                f"candle_error_"
                f"{_normalize_symbol(symbol)}_"
                f"{_normalize_timeframe(timeframe)}",
                "[METALS CANDLE ERROR] "
                f"{symbol} "
                f"{timeframe}: "
                f"{error}",
            )

    # --------------------------------------------------------
    # 3. Last-good stale candles
    # --------------------------------------------------------

    stale = (
        _get_last_good_candles(
            key
        )
    )

    if not stale.empty:

        _log_once(
            f"candle_cache_"
            f"{_normalize_symbol(symbol)}_"
            f"{_normalize_timeframe(timeframe)}",
            "[METALS CANDLE CACHE] "
            f"{symbol} {timeframe}: "
            "using last-good cached candles",
        )

        return stale

    return pd.DataFrame()


# ============================================================
# MULTI-TIMEFRAME SNAPSHOT
# ============================================================

def get_metals_mtf_candles(
    symbol: str,
) -> Dict[str, pd.DataFrame]:

    results = {}

    timeframes = (
        ("15m", 200),
        ("1h", 200),
        ("4h", 200),
    )

    for timeframe, outputsize in timeframes:

        results[
            timeframe
        ] = get_metals_candles(
            symbol=symbol,
            timeframe=timeframe,
            outputsize=outputsize,
        )

        # IMPORTANT:
        # Small spacing avoids burst requests
        # when provider is actually being called.
        if _provider_available():
            time.sleep(
                0.35
            )

    return results


# ============================================================
# HEALTH CHECK
# ============================================================

def metals_candles_health(
    symbol: str = "XAUUSD",
) -> Dict:

    if not TWELVE_DATA_API_KEY:

        return {
            "ok":
                False,

            "provider":
                "Twelve Data",

            "reason":
                "TWELVE_DATA_API_KEY "
                "is not configured",
        }

    df = (
        get_metals_candles(
            symbol=symbol,
            timeframe="15m",
            outputsize=20,
        )
    )

    if df.empty:

        return {
            "ok":
                False,

            "provider":
                "Twelve Data",

            "reason":
                f"No candle data for "
                f"{symbol}",

            "cooldown_seconds":
                _provider_cooldown_remaining(),
        }

    return {
        "ok":
            True,

        "provider":
            "Twelve Data",

        "symbol":
            symbol,

        "candles":
            len(df),

        "latest_close":
            float(
                df.iloc[-1][
                    "close"
                ]
            ),

        "latest_time":
            str(
                df.iloc[-1][
                    "datetime"
                ]
            ),

        "cooldown_seconds":
            _provider_cooldown_remaining(),
    }


# ============================================================
# CACHE STATUS
# ============================================================

def metals_candles_cache_status() -> Dict:

    result = {}

    with _state_lock:

        items = list(
            _last_good_candles.items()
        )

    for key, record in items:

        age_seconds = (
            _age(
                record.get(
                    "timestamp",
                    0.0,
                )
            )
        )

        result[
            key
        ] = {
            "age_seconds":
                round(
                    age_seconds,
                    1,
                ),

            "fresh":
                (
                    age_seconds
                    <= METALS_CANDLE_CACHE_SECONDS
                ),

            "stale_usable":
                (
                    age_seconds
                    <= METALS_CANDLE_STALE_SECONDS
                ),
        }

    result[
        "provider_cooldown_seconds"
    ] = (
        _provider_cooldown_remaining()
    )

    return result

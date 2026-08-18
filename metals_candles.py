"""
metals_candles.py

PRO AI QUANT TERMINAL V3.8
PRODUCTION LOCAL METALS CANDLE + WARM-UP ENGINE

Primary candle source:
    PostgreSQL metals_ticks

Built from:
    Gold-API live XAU / XAG quotes

Supported:
    XAUUSD
    XAGUSD

Timeframes:
    15m
    1h
    4h

Goals
-----
- Zero Twelve Data dependency
- Zero Metals.Dev candle dependency
- Build OHLC locally
- Reject invalid / stale candles
- Clear WARMING_UP state
- Scanner backward compatibility
- Safe paper-trading behavior
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Dict, Optional

import pandas as pd

from metals_ohlc_store import (
    build_candles,
    get_metals_mtf_candles,
    metals_ohlc_readiness,
    get_latest_stored_quote,
)


# ============================================================
# SUPPORTED MARKETS
# ============================================================

SUPPORTED_SYMBOLS = {
    "XAUUSD",
    "XAGUSD",
}


# ============================================================
# TIMEFRAMES
# ============================================================

TIMEFRAME_ALIASES = {
    "15m": "15m",
    "15min": "15m",
    "15": "15m",
    "15minute": "15m",
    "15minutes": "15m",

    "1h": "1h",
    "60m": "1h",
    "60min": "1h",
    "60": "1h",
    "1hour": "1h",

    "4h": "4h",
    "240m": "4h",
    "240min": "4h",
    "240": "4h",
    "4hour": "4h",
}


MINIMUM_CANDLES = {
    "15m": 60,
    "1h": 60,
    "4h": 60,
}


MAX_QUOTE_AGE_SECONDS = 300


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
    timeframe,
) -> str:

    key = (
        str(timeframe)
        .lower()
        .replace(" ", "")
        .strip()
    )

    normalized = (
        TIMEFRAME_ALIASES.get(
            key
        )
    )

    if normalized is None:

        raise ValueError(
            f"Unsupported metals timeframe: "
            f"{timeframe}"
        )

    return normalized


def _empty_candles():

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


# ============================================================
# STANDARDIZE / VALIDATE DATAFRAME
# ============================================================

def _standardize_dataframe(
    df: Optional[pd.DataFrame],
) -> pd.DataFrame:

    if (
        df is None
        or not isinstance(
            df,
            pd.DataFrame,
        )
        or df.empty
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

    missing = (
        required
        - set(
            df.columns
        )
    )

    if missing:

        print(
            "[METALS CANDLE FORMAT ERROR] "
            f"Missing columns: "
            f"{sorted(missing)}",
            flush=True,
        )

        return _empty_candles()

    result = df[
        [
            "datetime",
            "open",
            "high",
            "low",
            "close",
            "volume",
        ]
    ].copy()

    result["datetime"] = (
        pd.to_datetime(
            result["datetime"],
            utc=True,
            errors="coerce",
        )
    )

    for column in (
        "open",
        "high",
        "low",
        "close",
        "volume",
    ):

        result[column] = (
            pd.to_numeric(
                result[column],
                errors="coerce",
            )
        )

    result = (
        result
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

    if result.empty:

        return _empty_candles()

    # Reject impossible OHLC rows
    valid = (
        (result["open"] > 0)
        & (result["high"] > 0)
        & (result["low"] > 0)
        & (result["close"] > 0)
        & (result["high"] >= result["low"])
        & (result["high"] >= result["open"])
        & (result["high"] >= result["close"])
        & (result["low"] <= result["open"])
        & (result["low"] <= result["close"])
    )

    result = (
        result[
            valid
        ]
        .reset_index(
            drop=True
        )
    )

    return result


# ============================================================
# LIVE QUOTE FRESHNESS
# ============================================================

def metals_quote_freshness(
    symbol: str,
) -> Dict:

    normalized = (
        _normalize_symbol(
            symbol
        )
    )

    try:

        quote = (
            get_latest_stored_quote(
                normalized
            )
        )

        if not quote:

            return {
                "symbol": normalized,
                "fresh": False,
                "age_seconds": None,
                "reason": "No stored quote",
            }

        observed_at = (
            datetime.fromisoformat(
                quote[
                    "observed_at"
                ]
            )
        )

        age_seconds = (
            _utc_now()
            - observed_at
        ).total_seconds()

        fresh = (
            age_seconds
            <= MAX_QUOTE_AGE_SECONDS
        )

        return {
            "symbol": normalized,
            "fresh": fresh,
            "age_seconds": round(
                age_seconds,
                2,
            ),
            "provider": quote.get(
                "provider"
            ),
            "price": quote.get(
                "price"
            ),
            "reason": (
                "OK"
                if fresh
                else "Stored quote is stale"
            ),
        }

    except Exception as error:

        return {
            "symbol": normalized,
            "fresh": False,
            "age_seconds": None,
            "reason": str(
                error
            ),
        }


# ============================================================
# MAIN CANDLE FUNCTION
# ============================================================

def get_metals_candles(
    symbol: str,
    timeframe="15m",
    limit: int = 200,
) -> pd.DataFrame:

    normalized_symbol = (
        _normalize_symbol(
            symbol
        )
    )

    normalized_timeframe = (
        _normalize_timeframe(
            timeframe
        )
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
            1000,
        ),
    )

    try:

        candles = (
            build_candles(
                symbol=normalized_symbol,
                timeframe=normalized_timeframe,
                limit=limit,
            )
        )

        candles = (
            _standardize_dataframe(
                candles
            )
        )

        return candles

    except Exception as error:

        print(
            "[LOCAL METALS CANDLE ERROR] "
            f"{normalized_symbol} "
            f"{normalized_timeframe}: "
            f"{error}",
            flush=True,
        )

        return _empty_candles()


# ============================================================
# BACKWARD-COMPATIBLE ALIAS
# ============================================================

def get_metal_candles(
    symbol: str,
    timeframe="15m",
    limit: int = 200,
) -> pd.DataFrame:

    return get_metals_candles(
        symbol=symbol,
        timeframe=timeframe,
        limit=limit,
    )


# ============================================================
# TIMEFRAME HELPERS
# ============================================================

def get_15m_candles(
    symbol: str,
    limit: int = 200,
) -> pd.DataFrame:

    return get_metals_candles(
        symbol=symbol,
        timeframe="15m",
        limit=limit,
    )


def get_1h_candles(
    symbol: str,
    limit: int = 200,
) -> pd.DataFrame:

    return get_metals_candles(
        symbol=symbol,
        timeframe="1h",
        limit=limit,
    )


def get_4h_candles(
    symbol: str,
    limit: int = 200,
) -> pd.DataFrame:

    return get_metals_candles(
        symbol=symbol,
        timeframe="4h",
        limit=limit,
    )


# ============================================================
# MTF BUNDLE
# ============================================================

def get_mtf_metals_candles(
    symbol: str,
    limit: int = 200,
) -> Dict[str, pd.DataFrame]:

    normalized_symbol = (
        _normalize_symbol(
            symbol
        )
    )

    try:

        bundle = (
            get_metals_mtf_candles(
                symbol=normalized_symbol,
                limit=limit,
            )
        )

        return {
            "15m":
                _standardize_dataframe(
                    bundle.get(
                        "15m"
                    )
                ),

            "1h":
                _standardize_dataframe(
                    bundle.get(
                        "1h"
                    )
                ),

            "4h":
                _standardize_dataframe(
                    bundle.get(
                        "4h"
                    )
                ),
        }

    except Exception as error:

        print(
            "[METALS MTF CANDLE ERROR] "
            f"{normalized_symbol}: "
            f"{error}",
            flush=True,
        )

        return {
            "15m":
                _empty_candles(),

            "1h":
                _empty_candles(),

            "4h":
                _empty_candles(),
        }


def get_metals_multi_timeframe_candles(
    symbol: str,
    limit: int = 200,
) -> Dict[str, pd.DataFrame]:

    return get_mtf_metals_candles(
        symbol=symbol,
        limit=limit,
    )


# ============================================================
# READINESS
# ============================================================

def get_metals_candle_readiness(
    symbol: str,
) -> Dict:

    normalized_symbol = (
        _normalize_symbol(
            symbol
        )
    )

    freshness = (
        metals_quote_freshness(
            normalized_symbol
        )
    )

    try:

        timeframes = {}

        all_ready = True

        for timeframe, minimum in (
            MINIMUM_CANDLES.items()
        ):

            candles = (
                get_metals_candles(
                    symbol=normalized_symbol,
                    timeframe=timeframe,
                    limit=minimum,
                )
            )

            count = len(
                candles
            )

            ready = (
                count
                >= minimum
            )

            timeframes[
                timeframe
            ] = {
                "candles":
                    count,

                "minimum":
                    minimum,

                "ready":
                    ready,

                "remaining":
                    max(
                        0,
                        minimum - count,
                    ),
            }

            if not ready:

                all_ready = False

        if not freshness.get(
            "fresh",
            False,
        ):

            all_ready = False

        state = (
            "READY"
            if all_ready
            else "WARMING_UP"
        )

        return {
            "symbol":
                normalized_symbol,

            "ready":
                all_ready,

            "state":
                state,

            "timeframes":
                timeframes,

            "quote_freshness":
                freshness,

            "source":
                "LOCAL_POSTGRES_OHLC",
        }

    except Exception as error:

        return {
            "symbol":
                normalized_symbol,

            "ready":
                False,

            "state":
                "ERROR",

            "timeframes":
                {},

            "quote_freshness":
                freshness,

            "reason":
                str(
                    error
                ),
        }


# ============================================================
# SCANNER SAFETY
# ============================================================

def metals_candles_ready(
    symbol: str,
) -> bool:

    readiness = (
        get_metals_candle_readiness(
            symbol
        )
    )

    return bool(
        readiness.get(
            "ready",
            False,
        )
    )


# ============================================================
# WARM-UP STATUS
# ============================================================

def metals_warmup_status(
    symbol: str,
) -> Dict:

    readiness = (
        get_metals_candle_readiness(
            symbol
        )
    )

    return {
        "symbol":
            readiness.get(
                "symbol"
            ),

        "state":
            readiness.get(
                "state",
                "WARMING_UP",
            ),

        "ready":
            readiness.get(
                "ready",
                False,
            ),

        "timeframes":
            readiness.get(
                "timeframes",
                {},
            ),

        "quote_freshness":
            readiness.get(
                "quote_freshness",
                {},
            ),

        "message":
            (
                "Metals MTF candles ready."
                if readiness.get(
                    "ready",
                    False,
                )
                else
                "Building local 15m / 1h / 4h "
                "metals candle history."
            ),
    }


# ============================================================
# STATUS SUMMARY
# ============================================================

def metals_candle_status(
    symbol: str,
) -> Dict:

    normalized_symbol = (
        _normalize_symbol(
            symbol
        )
    )

    readiness = (
        get_metals_candle_readiness(
            normalized_symbol
        )
    )

    return {
        "symbol":
            normalized_symbol,

        "provider":
            "LOCAL_POSTGRES_OHLC",

        "external_candle_api":
            False,

        "ready":
            readiness.get(
                "ready",
                False,
            ),

        "state":
            readiness.get(
                "state",
                "WARMING_UP",
            ),

        "timeframes":
            readiness.get(
                "timeframes",
                {},
            ),

        "quote_freshness":
            readiness.get(
                "quote_freshness",
                {},
            ),

        "real_orders":
            False,
    }


# ============================================================
# LEGACY / SCANNER COMPATIBILITY
# ============================================================

def metals_candles_cache_status(
    symbol=None,
) -> Dict:
    """
    Compatibility adapter for existing metals_scanner.py.

    Old scanner expects cache-style keys such as:
        XAUUSD:15min:200
        XAUUSD:1h:200
        XAUUSD:4h:200

    V3.8 now maps local PostgreSQL OHLC readiness
    into that old interface.
    """

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
            "LOCAL_POSTGRES_OHLC",

        "provider_cooldown_seconds":
            0,

        "external_api":
            False,

        "twelve_data_required":
            False,

        "metals_dev_required":
            False,

        "paid_api_required":
            False,
    }

    for raw_symbol in symbols:

        normalized = (
            _normalize_symbol(
                raw_symbol
            )
        )

        readiness = (
            get_metals_candle_readiness(
                normalized
            )
        )

        timeframes = (
            readiness.get(
                "timeframes",
                {}
            )
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

            tf_status = (
                timeframes.get(
                    timeframe,
                    {}
                )
            )

            ready = bool(
                tf_status.get(
                    "ready",
                    False,
                )
            )

            candle_count = int(
                tf_status.get(
                    "candles",
                    0,
                )
                or 0
            )

            minimum = int(
                tf_status.get(
                    "minimum",
                    MINIMUM_CANDLES[
                        timeframe
                    ],
                )
                or MINIMUM_CANDLES[
                    timeframe
                ]
            )

            result[
                cache_key
            ] = {
                "fresh":
                    ready,

                "stale_usable":
                    False,

                "age_seconds":
                    0
                    if ready
                    else None,

                "ready":
                    ready,

                "state":
                    (
                        "READY"
                        if ready
                        else "WARMING_UP"
                    ),

                "candles":
                    candle_count,

                "minimum":
                    minimum,

                "remaining":
                    max(
                        0,
                        minimum
                        - candle_count,
                    ),

                "source":
                    "LOCAL_POSTGRES_OHLC",

                "provider":
                    "Gold-API + PostgreSQL",

                "external_api":
                    False,
            }

    return result


# ============================================================
# HEALTH
# ============================================================

def metals_candles_health():

    results = {}

    overall_ok = True

    for symbol in (
        "XAUUSD",
        "XAGUSD",
    ):

        try:

            status = (
                metals_candle_status(
                    symbol
                )
            )

            results[
                symbol
            ] = status

        except Exception as error:

            overall_ok = False

            results[
                symbol
            ] = {
                "ready":
                    False,

                "state":
                    "ERROR",

                "reason":
                    str(
                        error
                    ),
            }

    return {
        "ok":
            overall_ok,

        "provider":
            "LOCAL_POSTGRES_OHLC",

        "symbols":
            results,

        "twelve_data_required":
            False,

        "metals_dev_required":
            False,

        "paid_candle_api_required":
            False,

        "real_orders":
            False,
    }

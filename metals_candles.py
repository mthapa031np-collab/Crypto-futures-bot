"""
metals_candles.py

PRO AI QUANT TERMINAL V3.7
LOCAL METALS CANDLE ENGINE

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

Purpose
-------
- Remove Twelve Data candle dependency
- Remove paid commodity API dependency
- Build persistent OHLC candles locally
- Feed existing Metals scanner / MTF engine
- Safe readiness checks
- Never invent candle data

IMPORTANT
---------
PAPER TRADING ONLY
NO REAL ORDERS
"""

from __future__ import annotations

from typing import Dict, Optional

import pandas as pd

from metals_ohlc_store import (
    build_candles,
    get_metals_mtf_candles,
    metals_ohlc_readiness,
)


# ============================================================
# SUPPORTED MARKETS
# ============================================================

SUPPORTED_SYMBOLS = {
    "XAUUSD",
    "XAGUSD",
}


# ============================================================
# TIMEFRAME NORMALIZATION
# ============================================================

TIMEFRAME_ALIASES = {
    # 15 minute
    "15m": "15m",
    "15min": "15m",
    "15": "15m",
    "15minute": "15m",
    "15minutes": "15m",

    # 1 hour
    "1h": "1h",
    "60m": "1h",
    "60min": "1h",
    "60": "1h",
    "1hour": "1h",

    # 4 hour
    "4h": "4h",
    "240m": "4h",
    "240min": "4h",
    "240": "4h",
    "4hour": "4h",
}


# ============================================================
# HELPERS
# ============================================================

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
            f"missing columns: "
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

    return result


# ============================================================
# MAIN CANDLE FUNCTION
# ============================================================

def get_metals_candles(
    symbol: str,
    timeframe="15m",
    limit: int = 200,
) -> pd.DataFrame:
    """
    Return locally-built OHLC candles.

    This function intentionally performs NO external
    candle API requests.

    Source:
        metals_ticks PostgreSQL table
            ↓
        local OHLC aggregation
    """

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

        candles = build_candles(
            symbol=normalized_symbol,
            timeframe=normalized_timeframe,
            limit=limit,
        )

        return (
            _standardize_dataframe(
                candles
            )
        )

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
    """
    Compatibility alias for older scanner code.
    """

    return get_metals_candles(
        symbol=symbol,
        timeframe=timeframe,
        limit=limit,
    )


# ============================================================
# 15M
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


# ============================================================
# 1H
# ============================================================

def get_1h_candles(
    symbol: str,
    limit: int = 200,
) -> pd.DataFrame:

    return get_metals_candles(
        symbol=symbol,
        timeframe="1h",
        limit=limit,
    )


# ============================================================
# 4H
# ============================================================

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


# ============================================================
# BACKWARD-COMPATIBLE MTF ALIAS
# ============================================================

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

    try:

        return (
            metals_ohlc_readiness(
                normalized_symbol
            )
        )

    except Exception as error:

        return {
            "symbol":
                normalized_symbol,

            "ready":
                False,

            "timeframes":
                {},

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
    """
    True only after enough locally-built history
    exists for the MTF scanner.
    """

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
# CANDLE STATUS SUMMARY
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

        "timeframes":
            readiness.get(
                "timeframes",
                {},
            ),

        "real_orders":
            False,
    }


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
    }

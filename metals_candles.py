"""
metals_candles.py

PRO AI QUANT TERMINAL V3.5

Historical / intraday candle provider for Metals.

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

Purpose:
- Metals historical candles
- MTF analysis foundation
- RSI / MACD / EMA / ATR calculations later
- Paper trading only

Environment variable required:
    TWELVE_DATA_API_KEY
"""

import os
from typing import Dict, List, Optional

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

    response = requests.get(
        BASE_URL,
        params=params,
        timeout=REQUEST_TIMEOUT,
    )

    response.raise_for_status()

    data = response.json()

    if not isinstance(
        data,
        dict,
    ):

        raise RuntimeError(
            "Invalid Twelve Data response."
        )

    if data.get(
        "status"
    ) == "error":

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

    try:

        raw = get_metals_candles_raw(
            symbol=symbol,
            timeframe=timeframe,
            outputsize=outputsize,
        )

        return parse_metals_candles(
            raw
        )

    except Exception as error:

        print(
            "[METALS CANDLE ERROR] "
            f"{symbol} "
            f"{timeframe}: "
            f"{error}",
            flush=True,
        )

        return pd.DataFrame()


# ============================================================
# MULTI-TIMEFRAME SNAPSHOT
# ============================================================

def get_metals_mtf_candles(
    symbol: str,
) -> Dict[str, pd.DataFrame]:

    return {
        "15m":
            get_metals_candles(
                symbol,
                "15m",
                200,
            ),

        "1h":
            get_metals_candles(
                symbol,
                "1h",
                200,
            ),

        "4h":
            get_metals_candles(
                symbol,
                "4h",
                200,
            ),
    }


# ============================================================
# HEALTH CHECK
# ============================================================

def metals_candles_health(
    symbol: str = "XAUUSD",
) -> Dict:

    if not TWELVE_DATA_API_KEY:

        return {
            "ok": False,
            "provider": "Twelve Data",
            "reason": (
                "TWELVE_DATA_API_KEY "
                "is not configured"
            ),
        }

    df = get_metals_candles(
        symbol=symbol,
        timeframe="15m",
        outputsize=20,
    )

    if df.empty:

        return {
            "ok": False,
            "provider": "Twelve Data",
            "reason": (
                f"No candle data for "
                f"{symbol}"
            ),
        }

    return {
        "ok": True,
        "provider": "Twelve Data",
        "symbol": symbol,
        "candles": len(
            df
        ),
        "latest_close": float(
            df.iloc[-1][
                "close"
            ]
        ),
        "latest_time": str(
            df.iloc[-1][
                "datetime"
            ]
        ),
    }

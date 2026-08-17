"""
metals_provider.py

PRO AI QUANT TERMINAL V3.6
Resilient Precious Metals Quote Provider

Primary provider:
    Metals.Dev

Automatic fallback:
    Twelve Data

Supported:
    XAUUSD -> Gold
    XAGUSD -> Silver

Purpose:
- Live / near-live metals quote layer
- Automatic provider failover
- Safe API-key handling
- Better error diagnostics
- No real order execution

Environment variables:
    METALS_API_KEY
    TWELVE_DATA_API_KEY
"""

import os
from typing import Dict, Optional

import requests


# ============================================================
# CONFIG
# ============================================================

METALS_API_KEY = os.environ.get(
    "METALS_API_KEY",
    "",
).strip()

TWELVE_DATA_API_KEY = os.environ.get(
    "TWELVE_DATA_API_KEY",
    "",
).strip()


METALS_BASE_URL = (
    "https://api.metals.dev/v1"
)

TWELVE_QUOTE_URL = (
    "https://api.twelvedata.com/quote"
)


DEFAULT_CURRENCY = "USD"
DEFAULT_UNIT = "toz"

REQUEST_TIMEOUT = 12


# ============================================================
# SYMBOL MAP
# ============================================================

SYMBOL_MAP = {
    "XAUUSD": {
        "metal_key": "gold",
        "twelve_symbol": "XAU/USD",
        "name": "Gold",
        "base": "XAU",
        "quote": "USD",
    },

    "XAGUSD": {
        "metal_key": "silver",
        "twelve_symbol": "XAG/USD",
        "name": "Silver",
        "base": "XAG",
        "quote": "USD",
    },
}


# ============================================================
# HELPERS
# ============================================================

def _safe_float(
    value,
    default=None,
):

    try:

        if value is None:
            return default

        value = float(value)

        if value <= 0:
            return default

        return value

    except (
        TypeError,
        ValueError,
    ):

        return default


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


def _masked_key(
    key: str,
) -> str:

    if not key:
        return "NOT_SET"

    if len(key) <= 6:
        return "***"

    return (
        key[:3]
        + "***"
        + key[-3:]
    )


# ============================================================
# METALS.DEV RAW REQUEST
# ============================================================

def get_latest_metals_raw(
    currency: str = DEFAULT_CURRENCY,
    unit: str = DEFAULT_UNIT,
) -> Dict:

    if not METALS_API_KEY:

        raise RuntimeError(
            "METALS_API_KEY is not configured."
        )

    url = (
        f"{METALS_BASE_URL}/latest"
    )

    params = {
        "api_key":
            METALS_API_KEY,

        "currency":
            str(currency).upper(),

        "unit":
            unit,
    }

    headers = {
        "Accept":
            "application/json",

        "User-Agent":
            "pro-ai-quant-terminal-v3.6",
    }

    response = requests.get(
        url,
        params=params,
        headers=headers,
        timeout=REQUEST_TIMEOUT,
    )

    # IMPORTANT:
    # Do not use raise_for_status() immediately.
    # First capture provider's real error message.
    if not response.ok:

        try:
            error_payload = (
                response.json()
            )

        except Exception:

            error_payload = (
                response.text[:500]
            )

        raise RuntimeError(
            "Metals.Dev HTTP "
            f"{response.status_code}: "
            f"{error_payload}"
        )

    data = response.json()

    if not isinstance(
        data,
        dict,
    ):

        raise RuntimeError(
            "Invalid Metals.Dev response."
        )

    status = str(
        data.get(
            "status",
            ""
        )
    ).lower()

    if (
        status
        and status != "success"
    ):

        raise RuntimeError(
            "Metals.Dev API error: "
            f"{data}"
        )

    return data


# ============================================================
# METALS.DEV PRICE EXTRACTION
# ============================================================

def _extract_metal_price(
    payload: Dict,
    metal_key: str,
):

    metals = payload.get(
        "metals"
    )

    if isinstance(
        metals,
        dict,
    ):

        value = _safe_float(
            metals.get(
                metal_key
            ),
            None,
        )

        if value is not None:
            return value

    candidate = payload.get(
        metal_key
    )

    value = _safe_float(
        candidate,
        None,
    )

    if value is not None:
        return value

    return None


# ============================================================
# TWELVE DATA FALLBACK
# ============================================================

def _get_twelve_data_quote(
    normalized_symbol: str,
) -> Optional[Dict]:

    if not TWELVE_DATA_API_KEY:

        return None

    info = SYMBOL_MAP.get(
        normalized_symbol
    )

    if not info:

        return None

    params = {
        "symbol":
            info[
                "twelve_symbol"
            ],

        "apikey":
            TWELVE_DATA_API_KEY,
    }

    try:

        response = requests.get(
            TWELVE_QUOTE_URL,
            params=params,
            timeout=REQUEST_TIMEOUT,
        )

        if not response.ok:

            try:
                body = response.json()

            except Exception:
                body = response.text[:300]

            print(
                "[TWELVE DATA ERROR] "
                f"{normalized_symbol}: "
                f"HTTP {response.status_code} "
                f"{body}",
                flush=True,
            )

            return None

        data = response.json()

        if not isinstance(
            data,
            dict,
        ):

            return None

        if (
            str(
                data.get(
                    "status",
                    ""
                )
            ).lower()
            == "error"
        ):

            print(
                "[TWELVE DATA ERROR] "
                f"{normalized_symbol}: "
                f"{data.get('message')}",
                flush=True,
            )

            return None

        last = (
            _safe_float(
                data.get(
                    "close"
                ),
                None,
            )
            or
            _safe_float(
                data.get(
                    "price"
                ),
                None,
            )
        )

        if last is None:

            return None

        return {
            "symbol":
                normalized_symbol,

            "name":
                info[
                    "name"
                ],

            "asset_class":
                "METAL",

            "base":
                info[
                    "base"
                ],

            "quote":
                info[
                    "quote"
                ],

            "last":
                last,

            "bid":
                _safe_float(
                    data.get(
                        "bid"
                    ),
                    None,
                ),

            "ask":
                _safe_float(
                    data.get(
                        "ask"
                    ),
                    None,
                ),

            "high":
                _safe_float(
                    data.get(
                        "high"
                    ),
                    None,
                ),

            "low":
                _safe_float(
                    data.get(
                        "low"
                    ),
                    None,
                ),

            "open":
                _safe_float(
                    data.get(
                        "open"
                    ),
                    None,
                ),

            "previous_close":
                _safe_float(
                    data.get(
                        "previous_close"
                    ),
                    None,
                ),

            "change_pct":
                _safe_float(
                    data.get(
                        "percent_change"
                    ),
                    None,
                ),

            "spread_pct":
                None,

            "currency":
                "USD",

            "unit":
                "troy_ounce",

            "source":
                "Twelve Data",

            "provider_fallback":
                True,

            "raw":
                data,
        }

    except Exception as error:

        print(
            "[TWELVE DATA FALLBACK ERROR] "
            f"{normalized_symbol}: "
            f"{error}",
            flush=True,
        )

        return None


# ============================================================
# PRIMARY METALS.DEV QUOTE
# ============================================================

def _get_metals_dev_quote(
    normalized_symbol: str,
) -> Optional[Dict]:

    info = SYMBOL_MAP.get(
        normalized_symbol
    )

    if not info:

        return None

    payload = (
        get_latest_metals_raw(
            currency="USD",
            unit="toz",
        )
    )

    metal_key = (
        info[
            "metal_key"
        ]
    )

    last = (
        _extract_metal_price(
            payload,
            metal_key,
        )
    )

    if (
        last is None
        or last <= 0
    ):

        raise RuntimeError(
            "Metals.Dev returned no "
            f"{metal_key} price."
        )

    return {
        "symbol":
            normalized_symbol,

        "name":
            info[
                "name"
            ],

        "asset_class":
            "METAL",

        "base":
            info[
                "base"
            ],

        "quote":
            info[
                "quote"
            ],

        "last":
            float(
                last
            ),

        # /latest generally provides price rates,
        # not full bid/ask fields.
        "bid":
            None,

        "ask":
            None,

        "high":
            None,

        "low":
            None,

        "change_pct":
            None,

        "spread_pct":
            None,

        "currency":
            "USD",

        "unit":
            "troy_ounce",

        "source":
            "Metals.Dev",

        "provider_fallback":
            False,

        "raw":
            payload,
    }


# ============================================================
# PUBLIC METAL QUOTE
# ============================================================

def get_metal_quote(
    symbol: str,
) -> Optional[Dict]:

    normalized = (
        _normalize_symbol(
            symbol
        )
    )

    if normalized not in SYMBOL_MAP:

        raise ValueError(
            f"Unsupported metal symbol: "
            f"{symbol}"
        )

    # --------------------------------------------------------
    # PRIMARY PROVIDER
    # --------------------------------------------------------

    try:

        quote = (
            _get_metals_dev_quote(
                normalized
            )
        )

        if (
            quote
            and quote.get(
                "last"
            )
        ):

            return quote

    except Exception as error:

        # IMPORTANT:
        # Never print API key or complete URL.
        print(
            "[METALS.DEV ERROR] "
            f"{normalized}: "
            f"{error}",
            flush=True,
        )

    # --------------------------------------------------------
    # AUTOMATIC FALLBACK
    # --------------------------------------------------------

    fallback = (
        _get_twelve_data_quote(
            normalized
        )
    )

    if fallback:

        print(
            "[METALS PROVIDER FALLBACK] "
            f"{normalized}: "
            "using Twelve Data",
            flush=True,
        )

        return fallback

    print(
        "[METALS PROVIDER FAILED] "
        f"{normalized}: "
        "all providers unavailable",
        flush=True,
    )

    return None


# ============================================================
# GOLD
# ============================================================

def get_gold_quote():

    return get_metal_quote(
        "XAUUSD"
    )


# ============================================================
# SILVER
# ============================================================

def get_silver_quote():

    return get_metal_quote(
        "XAGUSD"
    )


# ============================================================
# ALL METALS
# ============================================================

def get_all_metal_quotes():

    results = []

    for symbol in SYMBOL_MAP:

        quote = (
            get_metal_quote(
                symbol
            )
        )

        if quote is not None:

            results.append(
                quote
            )

    return results


# ============================================================
# PROVIDER HEALTH
# ============================================================

def metals_provider_health():

    gold = (
        get_gold_quote()
    )

    if gold is None:

        return {
            "ok":
                False,

            "provider":
                "Metals.Dev + Twelve Data",

            "reason":
                "Both providers failed",

            "metals_dev_key":
                _masked_key(
                    METALS_API_KEY
                ),

            "twelve_data_key":
                _masked_key(
                    TWELVE_DATA_API_KEY
                ),
        }

    return {
        "ok":
            True,

        "provider":
            gold.get(
                "source"
            ),

        "fallback":
            gold.get(
                "provider_fallback",
                False,
            ),

        "gold_price":
            gold.get(
                "last"
            ),
    }

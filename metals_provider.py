"""
metals_provider.py

PRO AI QUANT TERMINAL V3.7
Quota-Safe Resilient Precious Metals Quote Provider

Primary provider:
    Metals.Dev

Automatic fallback:
    Twelve Data

Supported:
    XAUUSD -> Gold
    XAGUSD -> Silver

Features:
- Live / near-live metals quotes
- Provider failover
- Request caching
- Provider cooldown protection
- HTTP 429 protection
- Monthly quota protection
- Last-good quote preservation
- Stale quote detection
- Duplicate log suppression
- Safe API-key handling
- No real order execution

Environment variables:
    METALS_API_KEY
    TWELVE_DATA_API_KEY

Optional tuning:
    METALS_CACHE_SECONDS
    METALS_STALE_SECONDS
    METALS_DEV_COOLDOWN_SECONDS
    TWELVE_COOLDOWN_SECONDS
    METALS_ERROR_LOG_SECONDS
"""

import os
import time
import threading
from copy import deepcopy
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


METALS_BASE_URL = "https://api.metals.dev/v1"

TWELVE_QUOTE_URL = "https://api.twelvedata.com/quote"


DEFAULT_CURRENCY = "USD"
DEFAULT_UNIT = "toz"

REQUEST_TIMEOUT = 12


# ------------------------------------------------------------
# QUOTA / CACHE PROTECTION
# ------------------------------------------------------------

# Fresh quote cache.
# The UI/scanner can request repeatedly without hitting APIs every time.
METALS_CACHE_SECONDS = int(
    os.environ.get(
        "METALS_CACHE_SECONDS",
        "60",
    )
)

# Last-good quote may temporarily survive provider outages.
# After this limit, it is no longer returned.
METALS_STALE_SECONDS = int(
    os.environ.get(
        "METALS_STALE_SECONDS",
        "900",
    )
)

# General Metals.Dev failure cooldown.
METALS_DEV_COOLDOWN_SECONDS = int(
    os.environ.get(
        "METALS_DEV_COOLDOWN_SECONDS",
        "900",
    )
)

# Twelve Data failure / rate-limit cooldown.
TWELVE_COOLDOWN_SECONDS = int(
    os.environ.get(
        "TWELVE_COOLDOWN_SECONDS",
        "300",
    )
)

# Same error should not flood Render logs.
METALS_ERROR_LOG_SECONDS = int(
    os.environ.get(
        "METALS_ERROR_LOG_SECONDS",
        "300",
    )
)

# If Metals.Dev reports monthly quota exhausted,
# stop retrying for several hours.
METALS_DEV_QUOTA_COOLDOWN_SECONDS = 6 * 60 * 60


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
# RUNTIME STATE
# ============================================================

_state_lock = threading.RLock()


_quote_cache = {
    # Example:
    # "XAUUSD": {
    #     "quote": {...},
    #     "timestamp": 123456.0,
    # }
}


_last_good_quotes = {
    # Example:
    # "XAUUSD": {
    #     "quote": {...},
    #     "timestamp": 123456.0,
    # }
}


_provider_cooldown_until = {
    "metals_dev": 0.0,
    "twelve_data": 0.0,
}


_last_error_logs = {}


# Metals.Dev /latest returns both metals.
# Cache raw response independently so Gold + Silver
# do not consume two API calls.
_metals_dev_raw_cache = {
    "payload": None,
    "timestamp": 0.0,
}


# ============================================================
# TIME HELPERS
# ============================================================

def _now() -> float:
    return time.monotonic()


def _age(timestamp: float) -> float:
    if not timestamp:
        return float("inf")

    return max(
        0.0,
        _now() - timestamp,
    )


# ============================================================
# GENERAL HELPERS
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


def _clone_quote(
    quote: Optional[Dict],
) -> Optional[Dict]:

    if quote is None:
        return None

    return deepcopy(
        quote
    )


# ============================================================
# LOG THROTTLING
# ============================================================

def _log_once(
    key: str,
    message: str,
    interval: Optional[int] = None,
):

    if interval is None:
        interval = METALS_ERROR_LOG_SECONDS

    current = _now()

    with _state_lock:

        previous = _last_error_logs.get(
            key,
            0.0,
        )

        if (
            current - previous
            < interval
        ):
            return

        _last_error_logs[key] = current

    print(
        message,
        flush=True,
    )


# ============================================================
# PROVIDER COOLDOWNS
# ============================================================

def _provider_available(
    provider: str,
) -> bool:

    with _state_lock:

        cooldown_until = (
            _provider_cooldown_until.get(
                provider,
                0.0,
            )
        )

    return (
        _now()
        >= cooldown_until
    )


def _set_provider_cooldown(
    provider: str,
    seconds: int,
):

    seconds = max(
        1,
        int(seconds),
    )

    with _state_lock:

        _provider_cooldown_until[
            provider
        ] = max(
            _provider_cooldown_until.get(
                provider,
                0.0,
            ),
            _now() + seconds,
        )


def _provider_cooldown_remaining(
    provider: str,
) -> int:

    with _state_lock:

        until = (
            _provider_cooldown_until.get(
                provider,
                0.0,
            )
        )

    return max(
        0,
        int(
            until - _now()
        ),
    )


# ============================================================
# QUOTE CACHE
# ============================================================

def _get_fresh_cached_quote(
    symbol: str,
) -> Optional[Dict]:

    with _state_lock:

        cached = (
            _quote_cache.get(
                symbol
            )
        )

        if not cached:
            return None

        timestamp = cached.get(
            "timestamp",
            0.0,
        )

        if (
            _age(timestamp)
            > METALS_CACHE_SECONDS
        ):
            return None

        quote = _clone_quote(
            cached.get(
                "quote"
            )
        )

    if quote:

        quote["cached"] = True
        quote["stale"] = False
        quote["data_fresh"] = True
        quote["tradable_data"] = True
        quote["cache_age_seconds"] = round(
            _age(timestamp),
            1,
        )

    return quote


def _store_good_quote(
    symbol: str,
    quote: Dict,
):

    current = _now()

    clean_quote = _clone_quote(
        quote
    )

    if clean_quote is None:
        return

    clean_quote["cached"] = False
    clean_quote["stale"] = False
    clean_quote["data_fresh"] = True
    clean_quote["tradable_data"] = True
    clean_quote["cache_age_seconds"] = 0.0

    record = {
        "quote": clean_quote,
        "timestamp": current,
    }

    with _state_lock:

        _quote_cache[
            symbol
        ] = deepcopy(
            record
        )

        _last_good_quotes[
            symbol
        ] = deepcopy(
            record
        )


def _get_last_good_quote(
    symbol: str,
) -> Optional[Dict]:

    with _state_lock:

        cached = (
            _last_good_quotes.get(
                symbol
            )
        )

        if not cached:
            return None

        timestamp = cached.get(
            "timestamp",
            0.0,
        )

        quote = _clone_quote(
            cached.get(
                "quote"
            )
        )

    age_seconds = _age(
        timestamp
    )

    if (
        age_seconds
        > METALS_STALE_SECONDS
    ):
        return None

    if quote is None:
        return None

    # IMPORTANT:
    # Stale quote may be displayed,
    # but must NOT be treated as safe trading data.
    quote["cached"] = True
    quote["stale"] = True
    quote["data_fresh"] = False
    quote["tradable_data"] = False
    quote["provider_fallback"] = True
    quote["cache_age_seconds"] = round(
        age_seconds,
        1,
    )

    original_source = quote.get(
        "source",
        "Unknown",
    )

    quote["source"] = (
        f"{original_source} • cached"
    )

    return quote


# ============================================================
# METALS.DEV ERROR DETECTION
# ============================================================

def _looks_like_metals_quota_error(
    status_code: int,
    body,
) -> bool:

    text = str(
        body
    ).lower()

    quota_markers = (
        "quota",
        "exhausted",
        "monthly",
        "error_code': 1203",
        '"error_code": 1203',
        "error_code\":1203",
    )

    if any(
        marker in text
        for marker in quota_markers
    ):
        return True

    return False


# ============================================================
# TWELVE DATA ERROR DETECTION
# ============================================================

def _looks_like_twelve_rate_limit(
    status_code: int,
    body,
) -> bool:

    if status_code == 429:
        return True

    text = str(
        body
    ).lower()

    markers = (
        "api credits",
        "credits",
        "rate limit",
        "too many requests",
        "run out",
    )

    return any(
        marker in text
        for marker in markers
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

    # --------------------------------------------------------
    # Raw Metals.Dev cache
    # --------------------------------------------------------

    with _state_lock:

        cached_payload = (
            _metals_dev_raw_cache.get(
                "payload"
            )
        )

        cached_timestamp = (
            _metals_dev_raw_cache.get(
                "timestamp",
                0.0,
            )
        )

    if (
        cached_payload is not None
        and _age(
            cached_timestamp
        )
        <= METALS_CACHE_SECONDS
    ):

        return deepcopy(
            cached_payload
        )

    # --------------------------------------------------------
    # Provider cooldown
    # --------------------------------------------------------

    if not _provider_available(
        "metals_dev"
    ):

        remaining = (
            _provider_cooldown_remaining(
                "metals_dev"
            )
        )

        raise RuntimeError(
            "Metals.Dev temporarily paused "
            f"for quota/rate protection "
            f"({remaining}s remaining)."
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
            "pro-ai-quant-terminal-v3.7",
    }

    try:

        response = requests.get(
            url,
            params=params,
            headers=headers,
            timeout=REQUEST_TIMEOUT,
        )

    except requests.RequestException as error:

        _set_provider_cooldown(
            "metals_dev",
            METALS_DEV_COOLDOWN_SECONDS,
        )

        raise RuntimeError(
            "Metals.Dev network error: "
            f"{error}"
        ) from error

    # --------------------------------------------------------
    # Provider error
    # --------------------------------------------------------

    if not response.ok:

        try:
            error_payload = (
                response.json()
            )

        except Exception:
            error_payload = (
                response.text[:500]
            )

        if _looks_like_metals_quota_error(
            response.status_code,
            error_payload,
        ):

            _set_provider_cooldown(
                "metals_dev",
                METALS_DEV_QUOTA_COOLDOWN_SECONDS,
            )

            raise RuntimeError(
                "Metals.Dev monthly quota "
                "appears exhausted. "
                "Provider paused automatically."
            )

        if response.status_code == 429:

            _set_provider_cooldown(
                "metals_dev",
                METALS_DEV_COOLDOWN_SECONDS,
            )

            raise RuntimeError(
                "Metals.Dev rate limit reached. "
                "Provider paused automatically."
            )

        _set_provider_cooldown(
            "metals_dev",
            METALS_DEV_COOLDOWN_SECONDS,
        )

        raise RuntimeError(
            "Metals.Dev HTTP "
            f"{response.status_code}: "
            f"{error_payload}"
        )

    # --------------------------------------------------------
    # Parse response
    # --------------------------------------------------------

    try:

        data = (
            response.json()
        )

    except Exception as error:

        _set_provider_cooldown(
            "metals_dev",
            METALS_DEV_COOLDOWN_SECONDS,
        )

        raise RuntimeError(
            "Invalid Metals.Dev JSON response."
        ) from error

    if not isinstance(
        data,
        dict,
    ):

        _set_provider_cooldown(
            "metals_dev",
            METALS_DEV_COOLDOWN_SECONDS,
        )

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

        if _looks_like_metals_quota_error(
            200,
            data,
        ):

            _set_provider_cooldown(
                "metals_dev",
                METALS_DEV_QUOTA_COOLDOWN_SECONDS,
            )

        else:

            _set_provider_cooldown(
                "metals_dev",
                METALS_DEV_COOLDOWN_SECONDS,
            )

        raise RuntimeError(
            "Metals.Dev API error: "
            f"{data}"
        )

    # --------------------------------------------------------
    # Save one raw response for Gold + Silver
    # --------------------------------------------------------

    with _state_lock:

        _metals_dev_raw_cache[
            "payload"
        ] = deepcopy(
            data
        )

        _metals_dev_raw_cache[
            "timestamp"
        ] = _now()

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

    if not _provider_available(
        "twelve_data"
    ):

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

    except requests.RequestException as error:

        _set_provider_cooldown(
            "twelve_data",
            TWELVE_COOLDOWN_SECONDS,
        )

        _log_once(
            "twelve_network",
            "[TWELVE DATA ERROR] "
            f"{normalized_symbol}: "
            f"network error: {error}",
        )

        return None

    # --------------------------------------------------------
    # HTTP error
    # --------------------------------------------------------

    if not response.ok:

        try:
            body = (
                response.json()
            )

        except Exception:
            body = (
                response.text[:300]
            )

        if _looks_like_twelve_rate_limit(
            response.status_code,
            body,
        ):

            _set_provider_cooldown(
                "twelve_data",
                TWELVE_COOLDOWN_SECONDS,
            )

            _log_once(
                "twelve_rate_limit",
                "[TWELVE DATA RATE LIMIT] "
                "API credit/rate limit reached. "
                "Fallback provider paused automatically.",
            )

            return None

        _set_provider_cooldown(
            "twelve_data",
            TWELVE_COOLDOWN_SECONDS,
        )

        _log_once(
            f"twelve_http_{response.status_code}",
            "[TWELVE DATA ERROR] "
            f"{normalized_symbol}: "
            f"HTTP {response.status_code} "
            f"{body}",
        )

        return None

    # --------------------------------------------------------
    # Parse data
    # --------------------------------------------------------

    try:

        data = (
            response.json()
        )

    except Exception:

        _log_once(
            "twelve_invalid_json",
            "[TWELVE DATA ERROR] "
            f"{normalized_symbol}: "
            "invalid JSON response",
        )

        return None

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

        if _looks_like_twelve_rate_limit(
            response.status_code,
            data,
        ):

            _set_provider_cooldown(
                "twelve_data",
                TWELVE_COOLDOWN_SECONDS,
            )

        _log_once(
            "twelve_api_error",
            "[TWELVE DATA ERROR] "
            f"{normalized_symbol}: "
            f"{data.get('message')}",
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

    bid = _safe_float(
        data.get(
            "bid"
        ),
        None,
    )

    ask = _safe_float(
        data.get(
            "ask"
        ),
        None,
    )

    spread_pct = None

    if (
        bid is not None
        and ask is not None
        and bid > 0
        and ask >= bid
    ):

        midpoint = (
            bid + ask
        ) / 2

        if midpoint > 0:

            spread_pct = (
                (ask - bid)
                / midpoint
            ) * 100

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
            bid,

        "ask":
            ask,

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
            spread_pct,

        "currency":
            "USD",

        "unit":
            "troy_ounce",

        "source":
            "Twelve Data",

        "provider_fallback":
            True,

        "cached":
            False,

        "stale":
            False,

        "data_fresh":
            True,

        "tradable_data":
            True,

        "raw":
            data,
    }


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

        "bid":
            None,

        "ask":
            None,

        "high":
            None,

        "low":
            None,

        "open":
            None,

        "previous_close":
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

        "cached":
            False,

        "stale":
            False,

        "data_fresh":
            True,

        "tradable_data":
            True,

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
    # 1. FRESH LOCAL CACHE
    # --------------------------------------------------------

    cached = (
        _get_fresh_cached_quote(
            normalized
        )
    )

    if cached is not None:
        return cached

    # --------------------------------------------------------
    # 2. PRIMARY PROVIDER
    # --------------------------------------------------------

    if _provider_available(
        "metals_dev"
    ):

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

                _store_good_quote(
                    normalized,
                    quote,
                )

                return _clone_quote(
                    quote
                )

        except Exception as error:

            _log_once(
                "metals_dev_error",
                "[METALS.DEV ERROR] "
                f"{normalized}: "
                f"{error}",
            )

    # --------------------------------------------------------
    # 3. TWELVE DATA FALLBACK
    # --------------------------------------------------------

    fallback = (
        _get_twelve_data_quote(
            normalized
        )
    )

    if fallback:

        _store_good_quote(
            normalized,
            fallback,
        )

        _log_once(
            f"fallback_{normalized}",
            "[METALS PROVIDER FALLBACK] "
            f"{normalized}: "
            "using Twelve Data",
            interval=900,
        )

        return _clone_quote(
            fallback
        )

    # --------------------------------------------------------
    # 4. LAST-GOOD QUOTE
    # --------------------------------------------------------

    stale_quote = (
        _get_last_good_quote(
            normalized
        )
    )

    if stale_quote:

        _log_once(
            f"stale_{normalized}",
            "[METALS CACHE FALLBACK] "
            f"{normalized}: "
            "using last-good cached quote "
            "(NOT tradable data)",
        )

        return stale_quote

    # --------------------------------------------------------
    # 5. COMPLETE FAILURE
    # --------------------------------------------------------

    _log_once(
        f"failed_{normalized}",
        "[METALS PROVIDER FAILED] "
        f"{normalized}: "
        "all providers unavailable "
        "and no valid cached quote exists",
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

    metals_dev_remaining = (
        _provider_cooldown_remaining(
            "metals_dev"
        )
    )

    twelve_remaining = (
        _provider_cooldown_remaining(
            "twelve_data"
        )
    )

    if gold is None:

        return {
            "ok":
                False,

            "provider":
                "Metals.Dev + Twelve Data",

            "reason":
                "Both providers unavailable",

            "metals_dev_key":
                _masked_key(
                    METALS_API_KEY
                ),

            "twelve_data_key":
                _masked_key(
                    TWELVE_DATA_API_KEY
                ),

            "metals_dev_cooldown_seconds":
                metals_dev_remaining,

            "twelve_data_cooldown_seconds":
                twelve_remaining,
        }

    stale = bool(
        gold.get(
            "stale",
            False,
        )
    )

    return {
        "ok":
            not stale,

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

        "stale":
            stale,

        "data_fresh":
            gold.get(
                "data_fresh",
                False,
            ),

        "tradable_data":
            gold.get(
                "tradable_data",
                False,
            ),

        "cache_age_seconds":
            gold.get(
                "cache_age_seconds",
                0.0,
            ),

        "metals_dev_cooldown_seconds":
            metals_dev_remaining,

        "twelve_data_cooldown_seconds":
            twelve_remaining,
    }


# ============================================================
# MANUAL CACHE STATUS
# ============================================================

def metals_cache_status():

    result = {}

    for symbol in SYMBOL_MAP:

        with _state_lock:

            record = (
                _last_good_quotes.get(
                    symbol
                )
            )

        if not record:

            result[
                symbol
            ] = {
                "available":
                    False,
            }

            continue

        age_seconds = (
            _age(
                record.get(
                    "timestamp",
                    0.0,
                )
            )
        )

        result[
            symbol
        ] = {
            "available":
                True,

            "age_seconds":
                round(
                    age_seconds,
                    1,
                ),

            "fresh":
                (
                    age_seconds
                    <= METALS_CACHE_SECONDS
                ),

            "usable_as_stale":
                (
                    age_seconds
                    <= METALS_STALE_SECONDS
                ),
        }

    return result

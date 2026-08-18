"""
metals_provider.py

PRO AI QUANT TERMINAL V3.7
FREE REAL-METALS PROVIDER

Primary provider:
    Gold-API.com

Supported:
    XAUUSD -> Gold
    XAGUSD -> Silver

Architecture:
    Gold-API live quote
        ↓
    validation
        ↓
    PostgreSQL metals tick store
        ↓
    local 15m / 1h / 4h OHLC builder

IMPORTANT:
- No API key required
- No paid metals provider required
- PAPER TRADING ONLY
- NO REAL ORDERS
"""

from datetime import datetime, timezone
from typing import Dict, Optional

import requests

from metals_ohlc_store import (
    store_metal_quote,
    get_latest_stored_quote,
)


# ============================================================
# CONFIG
# ============================================================

GOLD_API_BASE_URL = (
    "https://api.gold-api.com"
)

REQUEST_TIMEOUT = 12

MAX_CACHED_QUOTE_AGE_SECONDS = 300


# ============================================================
# SYMBOL MAP
# ============================================================

SYMBOL_MAP = {
    "XAUUSD": {
        "api_symbol": "XAU",
        "name": "Gold",
        "base": "XAU",
        "quote": "USD",
    },

    "XAGUSD": {
        "api_symbol": "XAG",
        "name": "Silver",
        "base": "XAG",
        "quote": "USD",
    },
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


def _utc_now():

    return datetime.now(
        timezone.utc
    )


# ============================================================
# RAW GOLD-API REQUEST
# ============================================================

def _get_gold_api_raw(
    api_symbol: str,
) -> Dict:

    url = (
        f"{GOLD_API_BASE_URL}"
        f"/price/{api_symbol}"
    )

    headers = {
        "Accept":
            "application/json",

        "User-Agent":
            "pro-ai-quant-terminal-v3.7",
    }

    response = requests.get(
        url,
        headers=headers,
        timeout=REQUEST_TIMEOUT,
    )

    if not response.ok:

        try:
            body = response.json()

        except Exception:
            body = (
                response.text[:500]
            )

        raise RuntimeError(
            "Gold-API HTTP "
            f"{response.status_code}: "
            f"{body}"
        )

    data = response.json()

    if not isinstance(
        data,
        dict,
    ):

        raise RuntimeError(
            "Invalid Gold-API response."
        )

    return data


# ============================================================
# EXTRACT PRICE
# ============================================================

def _extract_price(
    payload: Dict,
):

    for key in (
        "price",
        "close",
        "value",
        "last",
    ):

        price = _safe_float(
            payload.get(
                key
            ),
            None,
        )

        if price is not None:

            return price

    return None


# ============================================================
# OPTIONAL FIELD
# ============================================================

def _extract_optional(
    payload: Dict,
    *keys,
):

    for key in keys:

        value = _safe_float(
            payload.get(
                key
            ),
            None,
        )

        if value is not None:

            return value

    return None


# ============================================================
# CACHE FALLBACK
# ============================================================

def _cached_quote(
    normalized_symbol: str,
) -> Optional[Dict]:

    try:

        cached = (
            get_latest_stored_quote(
                normalized_symbol
            )
        )

        if not cached:

            return None

        observed_at = (
            datetime.fromisoformat(
                cached[
                    "observed_at"
                ]
            )
        )

        age_seconds = (
            _utc_now()
            - observed_at
        ).total_seconds()

        if (
            age_seconds
            > MAX_CACHED_QUOTE_AGE_SECONDS
        ):

            return None

        info = SYMBOL_MAP[
            normalized_symbol
        ]

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
                    cached[
                        "price"
                    ]
                ),

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
                (
                    "LOCAL_CACHE"
                ),

            "provider_fallback":
                True,

            "cached":
                True,

            "cache_age_seconds":
                round(
                    age_seconds,
                    2,
                ),

            "observed_at":
                cached[
                    "observed_at"
                ],
        }

    except Exception as error:

        print(
            "[METALS CACHE ERROR] "
            f"{normalized_symbol}: "
            f"{error}",
            flush=True,
        )

        return None


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

    info = SYMBOL_MAP.get(
        normalized
    )

    if not info:

        raise ValueError(
            f"Unsupported metal symbol: "
            f"{symbol}"
        )

    try:

        payload = (
            _get_gold_api_raw(
                info[
                    "api_symbol"
                ]
            )
        )

        last = (
            _extract_price(
                payload
            )
        )

        if last is None:

            raise RuntimeError(
                "Gold-API returned "
                "no usable price."
            )

        bid = (
            _extract_optional(
                payload,
                "bid",
                "bid_price",
            )
        )

        ask = (
            _extract_optional(
                payload,
                "ask",
                "ask_price",
            )
        )

        high = (
            _extract_optional(
                payload,
                "high",
                "day_high",
            )
        )

        low = (
            _extract_optional(
                payload,
                "low",
                "day_low",
            )
        )

        change_pct = (
            _extract_optional(
                payload,
                "change_percent",
                "change_pct",
                "percent_change",
            )
        )

        spread_pct = None

        if (
            bid is not None
            and ask is not None
            and ask >= bid
        ):

            midpoint = (
                bid + ask
            ) / 2

            if midpoint > 0:

                spread_pct = (
                    (
                        ask - bid
                    )
                    / midpoint
                    * 100
                )

        observed_at = (
            _utc_now()
        )

        # ----------------------------------------------------
        # PERSIST LIVE TICK
        # ----------------------------------------------------

        try:

            store_metal_quote(
                symbol=normalized,
                price=last,
                provider="Gold-API",
                observed_at=observed_at,
            )

        except Exception as store_error:

            print(
                "[METALS STORE ERROR] "
                f"{normalized}: "
                f"{store_error}",
                flush=True,
            )

        return {
            "symbol":
                normalized,

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
                bid,

            "ask":
                ask,

            "high":
                high,

            "low":
                low,

            "change_pct":
                change_pct,

            "spread_pct":
                spread_pct,

            "currency":
                "USD",

            "unit":
                "troy_ounce",

            "source":
                "Gold-API",

            "provider_fallback":
                False,

            "cached":
                False,

            "observed_at":
                observed_at.isoformat(),

            "raw":
                payload,
        }

    except Exception as error:

        print(
            "[GOLD-API ERROR] "
            f"{normalized}: "
            f"{error}",
            flush=True,
        )

        # ----------------------------------------------------
        # SAFE LAST-KNOWN-GOOD FALLBACK
        # ----------------------------------------------------

        cached = (
            _cached_quote(
                normalized
            )
        )

        if cached:

            print(
                "[METALS CACHE FALLBACK] "
                f"{normalized}",
                flush=True,
            )

            return cached

        print(
            "[METALS PROVIDER FAILED] "
            f"{normalized}: "
            "no valid live or cached quote",
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
# HEALTH CHECK
# ============================================================

def metals_provider_health():

    gold = (
        get_gold_quote()
    )

    silver = (
        get_silver_quote()
    )

    gold_ok = (
        gold is not None
        and gold.get(
            "last"
        )
    )

    silver_ok = (
        silver is not None
        and silver.get(
            "last"
        )
    )

    return {
        "ok":
            bool(
                gold_ok
                or silver_ok
            ),

        "provider":
            "Gold-API",

        "gold_status":
            (
                "ONLINE"
                if gold_ok
                else "OFFLINE"
            ),

        "silver_status":
            (
                "ONLINE"
                if silver_ok
                else "OFFLINE"
            ),

        "gold_price":
            (
                gold.get(
                    "last"
                )
                if gold
                else None
            ),

        "silver_price":
            (
                silver.get(
                    "last"
                )
                if silver
                else None
            ),

        "database_tick_store":
            True,

        "api_key_required":
            False,

        "real_orders":
            False,
    }

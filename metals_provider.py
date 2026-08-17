"""
metals_provider.py

PRO AI QUANT TERMINAL V3
Precious-metals live quote provider.

Current provider:
    Metals.Dev

Supported:
    XAUUSD -> Gold
    XAGUSD -> Silver

Purpose:
- Live spot quote layer
- Bid / ask / high / low / change when available
- Safe API-key handling via environment variable
- No real order execution
- Future-ready for separate intraday candle provider

Environment variable required:
    METALS_API_KEY
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

METALS_BASE_URL = (
    "https://api.metals.dev/v1"
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
        "name": "Gold",
        "base": "XAU",
        "quote": "USD",
    },

    "XAGUSD": {
        "metal_key": "silver",
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

        return float(value)

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


def _require_api_key():

    if not METALS_API_KEY:

        raise RuntimeError(
            "METALS_API_KEY is not set."
        )


# ============================================================
# RAW LATEST RESPONSE
# ============================================================

def get_latest_metals_raw(
    currency: str = DEFAULT_CURRENCY,
    unit: str = DEFAULT_UNIT,
) -> Dict:

    _require_api_key()

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
            "pro-ai-quant-terminal-v3/1.0",
    }

    response = requests.get(
        url,
        params=params,
        headers=headers,
        timeout=REQUEST_TIMEOUT,
    )

    response.raise_for_status()

    data = response.json()

    if not isinstance(
        data,
        dict,
    ):

        raise RuntimeError(
            "Invalid Metals.Dev response."
        )

    return data


# ============================================================
# PARSE METAL PRICE
# ============================================================

def _extract_metal_price(
    payload: Dict,
    metal_key: str,
):

    # Metals.Dev responses can evolve by plan/version,
    # so we safely inspect common containers.

    candidates = []

    if isinstance(
        payload.get("metals"),
        dict,
    ):

        candidates.append(
            payload["metals"].get(
                metal_key
            )
        )

    if isinstance(
        payload.get("rates"),
        dict,
    ):

        candidates.append(
            payload["rates"].get(
                metal_key
            )
        )

    candidates.append(
        payload.get(
            metal_key
        )
    )

    for candidate in candidates:

        if candidate is None:
            continue

        # Direct number.
        value = _safe_float(
            candidate,
            None,
        )

        if value is not None:
            return value

        # Nested object.
        if isinstance(
            candidate,
            dict,
        ):

            for key in (
                "price",
                "rate",
                "value",
                "close",
                "spot",
            ):

                value = _safe_float(
                    candidate.get(
                        key
                    ),
                    None,
                )

                if value is not None:
                    return value

    return None


# ============================================================
# OPTIONAL DETAIL EXTRACTION
# ============================================================

def _extract_optional_detail(
    payload: Dict,
    metal_key: str,
    field_names,
):

    containers = []

    metals = payload.get(
        "metals"
    )

    if isinstance(
        metals,
        dict,
    ):

        metal_data = metals.get(
            metal_key
        )

        if isinstance(
            metal_data,
            dict,
        ):

            containers.append(
                metal_data
            )

    direct = payload.get(
        metal_key
    )

    if isinstance(
        direct,
        dict,
    ):

        containers.append(
            direct
        )

    for container in containers:

        for field in field_names:

            value = _safe_float(
                container.get(
                    field
                ),
                None,
            )

            if value is not None:
                return value

    return None


# ============================================================
# ONE METAL QUOTE
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
            get_latest_metals_raw(
                currency="USD",
                unit="toz",
            )
        )

        metal_key = info[
            "metal_key"
        ]

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

            return None

        bid = (
            _extract_optional_detail(
                payload,
                metal_key,
                (
                    "bid",
                    "bid_price",
                ),
            )
        )

        ask = (
            _extract_optional_detail(
                payload,
                metal_key,
                (
                    "ask",
                    "ask_price",
                ),
            )
        )

        high = (
            _extract_optional_detail(
                payload,
                metal_key,
                (
                    "high",
                    "day_high",
                    "high_24h",
                ),
            )
        )

        low = (
            _extract_optional_detail(
                payload,
                metal_key,
                (
                    "low",
                    "day_low",
                    "low_24h",
                ),
            )
        )

        change_pct = (
            _extract_optional_detail(
                payload,
                metal_key,
                (
                    "change_percent",
                    "change_pct",
                    "percent_change",
                ),
            )
        )

        spread_pct = None

        if (
            bid is not None
            and ask is not None
            and bid > 0
            and ask > 0
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
                float(last),

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
                "Metals.Dev",

            "raw":
                payload,
        }

    except Exception as error:

        print(
            "[METALS PROVIDER ERROR] "
            f"{normalized}: "
            f"{error}",
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
# ALL SUPPORTED METALS
# ============================================================

def get_all_metal_quotes():

    results = []

    for symbol in SYMBOL_MAP:

        quote = get_metal_quote(
            symbol
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

    if not METALS_API_KEY:

        return {
            "ok": False,
            "provider": "Metals.Dev",
            "reason": (
                "METALS_API_KEY "
                "is not configured"
            ),
        }

    gold = get_gold_quote()

    if gold is None:

        return {
            "ok": False,
            "provider": "Metals.Dev",
            "reason": (
                "Could not fetch "
                "Gold quote"
            ),
        }

    return {
        "ok": True,
        "provider": "Metals.Dev",
        "gold_price": gold.get(
            "last"
        ),
    }

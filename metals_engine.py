"""
metals_engine.py

PRO AI QUANT TERMINAL V3
Core metals intelligence engine.

Purpose:
- Build validated Gold/Silver market snapshots
- Normalize live quote data
- Detect stale/unavailable data
- Calculate spread quality
- Prepare metals data for scanner / MTF / risk layers
- Keep execution disabled until dedicated paper strategy is ready

Supported:
    XAUUSD
    XAGUSD

NO REAL ORDERS.
"""

from datetime import datetime, timezone
from typing import Dict, List, Optional

from metals_provider import (
    get_gold_quote,
    get_silver_quote,
    get_metal_quote,
    metals_provider_health,
)


# ============================================================
# CONFIG
# ============================================================

SUPPORTED_METALS = (
    "XAUUSD",
    "XAGUSD",
)

MAX_QUOTE_AGE_SECONDS = 120

MAX_SPREAD_PCT = {
    "XAUUSD": 0.20,
    "XAGUSD": 0.35,
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


def _utc_now():

    return datetime.now(
        timezone.utc
    )


# ============================================================
# QUOTE VALIDATION
# ============================================================

def validate_quote(
    quote: Optional[Dict],
) -> Dict:

    if not quote:

        return {
            "valid": False,
            "reason": "Quote unavailable",
        }

    symbol = _normalize_symbol(
        quote.get(
            "symbol",
            "",
        )
    )

    if symbol not in SUPPORTED_METALS:

        return {
            "valid": False,
            "reason": (
                f"Unsupported symbol: "
                f"{symbol}"
            ),
        }

    last = _safe_float(
        quote.get(
            "last"
        )
    )

    if (
        last is None
        or last <= 0
    ):

        return {
            "valid": False,
            "reason": "Invalid last price",
        }

    bid = _safe_float(
        quote.get(
            "bid"
        )
    )

    ask = _safe_float(
        quote.get(
            "ask"
        )
    )

    spread_pct = _safe_float(
        quote.get(
            "spread_pct"
        )
    )

    if (
        spread_pct is None
        and bid is not None
        and ask is not None
        and bid > 0
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

    max_spread = MAX_SPREAD_PCT.get(
        symbol,
        0.25,
    )

    spread_ok = True

    if (
        spread_pct is not None
        and spread_pct > max_spread
    ):

        spread_ok = False

    return {
        "valid": True,
        "reason": "OK",
        "symbol": symbol,
        "last": last,
        "spread_pct": spread_pct,
        "spread_ok": spread_ok,
        "max_spread_pct": max_spread,
    }


# ============================================================
# MARKET QUALITY
# ============================================================

def classify_market_quality(
    quote: Dict,
) -> Dict:

    validation = validate_quote(
        quote
    )

    if not validation.get(
        "valid",
        False,
    ):

        return {
            "quality": "UNAVAILABLE",
            "score": 0,
            "reason": validation.get(
                "reason",
                "Invalid quote",
            ),
        }

    spread_pct = validation.get(
        "spread_pct"
    )

    score = 100
    reasons = []

    if spread_pct is None:

        score -= 10

        reasons.append(
            "No spread data"
        )

    else:

        max_spread = validation.get(
            "max_spread_pct",
            0.25,
        )

        ratio = (
            spread_pct
            / max_spread
            if max_spread > 0
            else 0
        )

        if ratio <= 0.35:

            reasons.append(
                "Excellent spread"
            )

        elif ratio <= 0.65:

            score -= 10

            reasons.append(
                "Normal spread"
            )

        elif ratio <= 1.0:

            score -= 25

            reasons.append(
                "Wide spread"
            )

        else:

            score -= 50

            reasons.append(
                "Spread too wide"
            )

    if score >= 85:

        quality = "EXCELLENT"

    elif score >= 70:

        quality = "GOOD"

    elif score >= 50:

        quality = "CAUTION"

    else:

        quality = "POOR"

    return {
        "quality": quality,
        "score": max(
            0,
            min(
                100,
                score,
            ),
        ),
        "reason": ", ".join(
            reasons
        ),
    }


# ============================================================
# BUILD ONE METAL SNAPSHOT
# ============================================================

def build_metal_snapshot(
    symbol: str,
) -> Dict:

    symbol = _normalize_symbol(
        symbol
    )

    if symbol not in SUPPORTED_METALS:

        return {
            "symbol": symbol,
            "status": "UNSUPPORTED",
            "tradable": False,
            "paper_trading_enabled": False,
        }

    quote = get_metal_quote(
        symbol
    )

    now = _utc_now()

    if not quote:

        return {
            "symbol": symbol,
            "status": "UNAVAILABLE",
            "tradable": False,
            "paper_trading_enabled": False,
            "timestamp": now.isoformat(),
            "source": "Metals.Dev",
        }

    validation = validate_quote(
        quote
    )

    quality = classify_market_quality(
        quote
    )

    last = _safe_float(
        quote.get(
            "last"
        ),
        0.0,
    )

    bid = _safe_float(
        quote.get(
            "bid"
        )
    )

    ask = _safe_float(
        quote.get(
            "ask"
        )
    )

    high = _safe_float(
        quote.get(
            "high"
        )
    )

    low = _safe_float(
        quote.get(
            "low"
        )
    )

    change_pct = _safe_float(
        quote.get(
            "change_pct"
        )
    )

    spread_pct = _safe_float(
        quote.get(
            "spread_pct"
        )
    )

    direction = "FLAT"

    if change_pct is not None:

        if change_pct > 0:

            direction = "BULLISH"

        elif change_pct < 0:

            direction = "BEARISH"

    range_pct = None

    if (
        high is not None
        and low is not None
        and low > 0
    ):

        range_pct = (
            (
                high - low
            )
            / low
            * 100
        )

    return {
        "symbol": symbol,
        "name": quote.get(
            "name"
        ),
        "asset_class": "METAL",
        "status": (
            "LIVE"
            if validation.get(
                "valid",
                False,
            )
            else "INVALID"
        ),
        "last": last,
        "bid": bid,
        "ask": ask,
        "high": high,
        "low": low,
        "change_pct": change_pct,
        "spread_pct": spread_pct,
        "range_pct": range_pct,
        "direction": direction,
        "market_quality": quality.get(
            "quality"
        ),
        "quality_score": quality.get(
            "score"
        ),
        "quality_reason": quality.get(
            "reason"
        ),
        "spread_ok": validation.get(
            "spread_ok",
            False,
        ),
        "source": quote.get(
            "source",
            "Metals.Dev",
        ),
        "currency": quote.get(
            "currency",
            "USD",
        ),
        "unit": quote.get(
            "unit",
            "troy_ounce",
        ),
        "timestamp": now.isoformat(),

        # Important:
        # Execution stays disabled until
        # candle / MTF / risk validation exists.
        "tradable": False,
        "paper_trading_enabled": False,
        "real_orders_enabled": False,
    }


# ============================================================
# GOLD SNAPSHOT
# ============================================================

def get_gold_snapshot():

    return build_metal_snapshot(
        "XAUUSD"
    )


# ============================================================
# SILVER SNAPSHOT
# ============================================================

def get_silver_snapshot():

    return build_metal_snapshot(
        "XAGUSD"
    )


# ============================================================
# ALL METALS
# ============================================================

def get_metals_snapshots() -> List[Dict]:

    return [
        get_gold_snapshot(),
        get_silver_snapshot(),
    ]


# ============================================================
# STRONGEST METAL
# ============================================================

def strongest_metal() -> Optional[Dict]:

    snapshots = (
        get_metals_snapshots()
    )

    valid = [
        item
        for item in snapshots
        if item.get(
            "status"
        ) == "LIVE"
    ]

    if not valid:

        return None

    def rank(
        item,
    ):

        change = abs(
            _safe_float(
                item.get(
                    "change_pct"
                ),
                0.0,
            )
        )

        quality = _safe_float(
            item.get(
                "quality_score"
            ),
            0.0,
        )

        return (
            change * 10
            + quality
        )

    return max(
        valid,
        key=rank,
    )


# ============================================================
# METALS ENGINE HEALTH
# ============================================================

def metals_engine_health() -> Dict:

    provider = (
        metals_provider_health()
    )

    if not provider.get(
        "ok",
        False,
    ):

        return {
            "ok": False,
            "engine": "V3 Metals Engine",
            "provider": "Metals.Dev",
            "reason": provider.get(
                "reason",
                "Provider unavailable",
            ),
        }

    gold = get_gold_snapshot()

    silver = get_silver_snapshot()

    live_count = sum(
        1
        for item in (
            gold,
            silver,
        )
        if item.get(
            "status"
        ) == "LIVE"
    )

    return {
        "ok": (
            live_count > 0
        ),
        "engine": "V3 Metals Engine",
        "provider": "Metals.Dev",
        "live_markets": live_count,
        "supported_markets": 2,
        "gold_status": gold.get(
            "status"
        ),
        "silver_status": silver.get(
            "status"
        ),
        "paper_execution": False,
        "real_execution": False,
    }


# ============================================================
# METALS SUMMARY
# ============================================================

def metals_summary() -> Dict:

    snapshots = (
        get_metals_snapshots()
    )

    strongest = (
        strongest_metal()
    )

    bullish = sum(
        1
        for item in snapshots
        if item.get(
            "direction"
        ) == "BULLISH"
    )

    bearish = sum(
        1
        for item in snapshots
        if item.get(
            "direction"
        ) == "BEARISH"
    )

    return {
        "markets": snapshots,
        "strongest": strongest,
        "bullish_count": bullish,
        "bearish_count": bearish,
        "total_markets": len(
            snapshots
        ),
        "paper_execution": False,
        "real_execution": False,
    }


# ============================================================
# SAFE DEBUG SNAPSHOT
# ============================================================

def debug_metals_engine() -> Dict:

    return {
        "health":
            metals_engine_health(),

        "summary":
            metals_summary(),

        "timestamp":
            _utc_now().isoformat(),
    }

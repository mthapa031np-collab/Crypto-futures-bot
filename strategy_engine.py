"""
strategy_engine.py

PRO AI QUANT TERMINAL V2
Multi-timeframe strategy confirmation engine.

Responsibilities:
- Analyse 15m / 1h / 4h
- Reuse signal_engine.py
- Confirm direction across timeframes
- Build confidence score
- Reject weak/conflicting setups

PAPER TRADING ONLY for now.
"""

from typing import Dict, Optional

from market_data import get_candles
from signal_engine import generate_signal


# ============================================================
# TIMEFRAMES
# ============================================================

TIMEFRAMES = {
    "15m": 15,
    "1h": 60,
    "4h": 240,
}

TIMEFRAME_WEIGHTS = {
    "15m": 1.0,
    "1h": 1.5,
    "4h": 2.0,
}


# ============================================================
# HELPERS
# ============================================================

def _safe_float(value, default=0.0):

    try:
        if value is None:
            return default
        return float(value)

    except (TypeError, ValueError):
        return default


def _clean_signal(value):

    signal = str(
        value or "NO TRADE"
    ).upper().strip()

    if signal not in (
        "BUY",
        "SELL",
        "NO TRADE",
    ):
        return "NO TRADE"

    return signal


# ============================================================
# ANALYSE ONE TIMEFRAME
# ============================================================

def analyse_timeframe(
    symbol: str,
    timeframe_minutes: int,
    limit: int = 120,
) -> Optional[Dict]:

    try:

        candles = get_candles(
            exchange="PUBLIC",
            symbol=symbol,
            timeframe_minutes=timeframe_minutes,
            limit=limit,
            api_key="",
            api_secret="",
            use_testnet=False,
        )

        if candles is None:
            return None

        if len(candles) < 50:
            return None

        signal_data = generate_signal(
            candles
        )

        return {
            "signal": _clean_signal(
                signal_data.get(
                    "signal",
                    "NO TRADE",
                )
            ),

            "score": _safe_float(
                signal_data.get(
                    "score",
                    0,
                )
            ),

            "rsi": (
                _safe_float(
                    signal_data.get(
                        "rsi"
                    )
                )
                if signal_data.get(
                    "rsi"
                )
                is not None
                else None
            ),

            "macd": (
                _safe_float(
                    signal_data.get(
                        "macd"
                    )
                )
                if signal_data.get(
                    "macd"
                )
                is not None
                else None
            ),

            "reason": str(
                signal_data.get(
                    "reason",
                    "",
                )
            ),

            "price": _safe_float(
                candles[
                    "close"
                ].iloc[-1]
            ),
        }

    except Exception as error:

        print(
            "[STRATEGY ERROR] "
            f"{symbol} "
            f"{timeframe_minutes}m: "
            f"{error}",
            flush=True,
        )

        return None


# ============================================================
# MULTI-TIMEFRAME ANALYSIS
# ============================================================

def analyse_multi_timeframe(
    symbol: str,
) -> Dict:

    symbol = str(
        symbol
    ).upper().strip()

    timeframe_data = {}

    for label, minutes in TIMEFRAMES.items():

        result = analyse_timeframe(
            symbol=symbol,
            timeframe_minutes=minutes,
        )

        if result is not None:

            timeframe_data[
                label
            ] = result

    if not timeframe_data:

        return {
            "symbol": symbol,
            "valid": False,
            "signal": "NO TRADE",
            "confidence": 0.0,
            "reason": (
                "No valid timeframe data"
            ),
            "timeframes": {},
        }

    # ========================================================
    # WEIGHTED DIRECTION SCORE
    # ========================================================

    weighted_score = 0.0
    total_weight = 0.0

    bullish_votes = 0.0
    bearish_votes = 0.0

    for label, data in timeframe_data.items():

        weight = TIMEFRAME_WEIGHTS.get(
            label,
            1.0,
        )

        score = _safe_float(
            data.get(
                "score",
                0,
            )
        )

        signal = data.get(
            "signal",
            "NO TRADE",
        )

        weighted_score += (
            score
            * weight
        )

        total_weight += weight

        if signal == "BUY":
            bullish_votes += weight

        elif signal == "SELL":
            bearish_votes += weight

    if total_weight > 0:

        normalized_score = (
            weighted_score
            / total_weight
        )

    else:

        normalized_score = 0.0

    # ========================================================
    # TREND ALIGNMENT
    # ========================================================

    tf_15m = timeframe_data.get(
        "15m"
    )

    tf_1h = timeframe_data.get(
        "1h"
    )

    tf_4h = timeframe_data.get(
        "4h"
    )

    higher_tf_bullish = (
        tf_1h
        and tf_4h
        and tf_1h.get(
            "score",
            0,
        ) > 0
        and tf_4h.get(
            "score",
            0,
        ) > 0
    )

    higher_tf_bearish = (
        tf_1h
        and tf_4h
        and tf_1h.get(
            "score",
            0,
        ) < 0
        and tf_4h.get(
            "score",
            0,
        ) < 0
    )

    entry_bullish = (
        tf_15m
        and tf_15m.get(
            "score",
            0,
        ) > 0
    )

    entry_bearish = (
        tf_15m
        and tf_15m.get(
            "score",
            0,
        ) < 0
    )

    # ========================================================
    # FINAL SIGNAL
    # ========================================================

    final_signal = (
        "NO TRADE"
    )

    alignment_bonus = 0.0

    if (
        higher_tf_bullish
        and entry_bullish
    ):

        final_signal = "BUY"
        alignment_bonus = 2.0

    elif (
        higher_tf_bearish
        and entry_bearish
    ):

        final_signal = "SELL"
        alignment_bonus = 2.0

    # ========================================================
    # CONFIDENCE
    # ========================================================

    directional_strength = min(
        abs(
            normalized_score
        )
        / 5.0,
        1.0,
    )

    vote_strength = 0.0

    if total_weight > 0:

        vote_strength = max(
            bullish_votes,
            bearish_votes,
        ) / total_weight

    confidence = (
        directional_strength
        * 60.0
        + vote_strength
        * 30.0
        + alignment_bonus
        * 5.0
    )

    confidence = max(
        0.0,
        min(
            confidence,
            100.0,
        ),
    )

    # ========================================================
    # QUALITY FILTER
    # ========================================================

    if confidence < 60:

        final_signal = (
            "NO TRADE"
        )

    # ========================================================
    # REASON
    # ========================================================

    reason_parts = []

    if higher_tf_bullish:
        reason_parts.append(
            "1h and 4h bullish"
        )

    elif higher_tf_bearish:
        reason_parts.append(
            "1h and 4h bearish"
        )

    else:
        reason_parts.append(
            "Higher timeframes mixed"
        )

    if entry_bullish:
        reason_parts.append(
            "15m bullish"
        )

    elif entry_bearish:
        reason_parts.append(
            "15m bearish"
        )

    else:
        reason_parts.append(
            "15m neutral"
        )

    reason_parts.append(
        f"confidence={confidence:.1f}%"
    )

    reason_parts.append(
        f"weighted_score={normalized_score:.2f}"
    )

    return {
        "symbol": symbol,
        "valid": True,

        "signal": final_signal,

        "confidence": round(
            confidence,
            2,
        ),

        "weighted_score": round(
            normalized_score,
            3,
        ),

        "bullish_votes": round(
            bullish_votes,
            2,
        ),

        "bearish_votes": round(
            bearish_votes,
            2,
        ),

        "reason": ", ".join(
            reason_parts
        ),

        "timeframes":
            timeframe_data,
    }


# ============================================================
# CONFIRM SCANNER SETUP
# ============================================================

def confirm_scanner_setup(
    scanner_setup: Dict,
) -> Dict:

    if not scanner_setup:

        return {
            "approved": False,
            "reason": (
                "No scanner setup"
            ),
        }

    symbol = scanner_setup.get(
        "symbol"
    )

    scanner_signal = scanner_setup.get(
        "signal",
        "NO TRADE",
    )

    if not symbol:

        return {
            "approved": False,
            "reason": (
                "Missing symbol"
            ),
        }

    strategy = analyse_multi_timeframe(
        symbol
    )

    strategy_signal = strategy.get(
        "signal",
        "NO TRADE",
    )

    confidence = _safe_float(
        strategy.get(
            "confidence",
            0,
        )
    )

    approved = (
        scanner_signal
        in (
            "BUY",
            "SELL",
        )
        and strategy_signal
        == scanner_signal
        and confidence >= 60
    )

    return {
        "approved": approved,

        "symbol": symbol,

        "scanner_signal":
            scanner_signal,

        "strategy_signal":
            strategy_signal,

        "confidence":
            confidence,

        "reason":
            strategy.get(
                "reason",
                "",
            ),

        "strategy":
            strategy,
    }

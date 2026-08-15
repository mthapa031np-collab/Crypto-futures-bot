"""
scanner.py

PRO AI QUANT TERMINAL V2
Multi-market scanner.

Responsibilities:
- Scan configured crypto markets
- Fetch candles from market_data.py
- Run signal engine
- Calculate/collect market metrics
- Rank strongest setups
- Return clean scanner results to app.py / bot_worker.py

PAPER TRADING ONLY for now.
"""

from typing import List, Dict, Optional

from market_data import get_candles, get_ticker
from signal_engine import generate_signal

from settings import (
    SCAN_MARKETS,
    TIMEFRAME_MINUTES,
    CANDLE_LIMIT,
    MIN_BUY_SCORE,
    MAX_SELL_SCORE,
)


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


def _clean_signal(signal):

    signal = str(
        signal or "NO TRADE"
    ).upper().strip()

    if signal not in (
        "BUY",
        "SELL",
        "NO TRADE",
    ):
        return "NO TRADE"

    return signal


# ============================================================
# ANALYSE ONE MARKET
# ============================================================

def analyse_market(
    symbol: str,
) -> Dict:

    symbol = str(
        symbol
    ).upper().strip()

    try:

        candles = get_candles(
            exchange="PUBLIC",
            symbol=symbol,
            timeframe_minutes=TIMEFRAME_MINUTES,
            limit=CANDLE_LIMIT,
            api_key="",
            api_secret="",
            use_testnet=False,
        )

        if candles is None:

            return {
                "symbol": symbol,
                "valid": False,
                "signal": "NO TRADE",
                "score": 0,
                "reason": "No candle data",
            }

        if len(candles) < 50:

            return {
                "symbol": symbol,
                "valid": False,
                "signal": "NO TRADE",
                "score": 0,
                "reason": (
                    f"Not enough candles: "
                    f"{len(candles)}"
                ),
            }

        latest_close = _safe_float(
            candles[
                "close"
            ].iloc[-1]
        )

        signal_data = generate_signal(
            candles
        )

        signal = _clean_signal(
            signal_data.get(
                "signal",
                "NO TRADE",
            )
        )

        score = _safe_float(
            signal_data.get(
                "score",
                0,
            )
        )

        rsi = signal_data.get(
            "rsi"
        )

        macd = signal_data.get(
            "macd"
        )

        reason = str(
            signal_data.get(
                "reason",
                "",
            )
        )

        # --------------------------------------------
        # Public ticker
        # --------------------------------------------

        ticker = get_ticker(
            symbol=symbol,
            exchange="PUBLIC",
            api_key="",
            api_secret="",
            use_testnet=False,
        )

        change_pct = 0.0
        high = 0.0
        low = 0.0
        volume = 0.0

        if ticker:

            change_pct = _safe_float(
                ticker.get(
                    "change_pct"
                )
            )

            high = _safe_float(
                ticker.get(
                    "high"
                )
            )

            low = _safe_float(
                ticker.get(
                    "low"
                )
            )

            volume = _safe_float(
                ticker.get(
                    "volume"
                )
            )

        # --------------------------------------------
        # Confirmation state
        # --------------------------------------------

        confirmed = False

        if (
            signal == "BUY"
            and score >= MIN_BUY_SCORE
        ):
            confirmed = True

        elif (
            signal == "SELL"
            and score <= MAX_SELL_SCORE
        ):
            confirmed = True

        return {
            "symbol": symbol,
            "valid": True,

            "price": latest_close,

            "signal": signal,
            "score": score,

            "absolute_score": abs(
                score
            ),

            "confirmed": confirmed,

            "rsi": (
                _safe_float(
                    rsi,
                    None,
                )
                if rsi is not None
                else None
            ),

            "macd": (
                _safe_float(
                    macd,
                    None,
                )
                if macd is not None
                else None
            ),

            "change_pct": change_pct,
            "high": high,
            "low": low,
            "volume": volume,

            "reason": reason,

            "timeframe_minutes":
                TIMEFRAME_MINUTES,

            "candles":
                len(candles),
        }

    except Exception as error:

        return {
            "symbol": symbol,
            "valid": False,
            "signal": "NO TRADE",
            "score": 0,
            "confirmed": False,
            "reason": (
                f"Scanner error: {error}"
            ),
        }


# ============================================================
# SCAN MARKET LIST
# ============================================================

def scan_markets(
    markets: Optional[List[str]] = None,
) -> List[Dict]:

    if markets is None:
        markets = SCAN_MARKETS

    results = []

    seen = set()

    for raw_symbol in markets:

        symbol = str(
            raw_symbol
        ).upper().strip()

        if not symbol:
            continue

        if symbol in seen:
            continue

        seen.add(
            symbol
        )

        result = analyse_market(
            symbol
        )

        results.append(
            result
        )

    return results


# ============================================================
# VALID RESULTS
# ============================================================

def get_valid_results(
    results: List[Dict],
) -> List[Dict]:

    return [
        item
        for item in results
        if item.get(
            "valid"
        )
    ]


# ============================================================
# CONFIRMED SETUPS
# ============================================================

def get_confirmed_setups(
    results: List[Dict],
) -> List[Dict]:

    confirmed = []

    for item in results:

        if not item.get(
            "valid"
        ):
            continue

        if not item.get(
            "confirmed"
        ):
            continue

        signal = item.get(
            "signal"
        )

        if signal not in (
            "BUY",
            "SELL",
        ):
            continue

        confirmed.append(
            dict(
                item
            )
        )

    return confirmed


# ============================================================
# STRONGEST CONFIRMED SETUP
# ============================================================

def select_best_setup(
    results: List[Dict],
) -> Optional[Dict]:

    confirmed = get_confirmed_setups(
        results
    )

    if not confirmed:
        return None

    confirmed.sort(
        key=lambda item: (
            item.get(
                "absolute_score",
                0,
            ),
            item.get(
                "volume",
                0,
            ),
        ),
        reverse=True,
    )

    return confirmed[0]


# ============================================================
# STRONGEST MARKET FOR DISPLAY
# ============================================================

def select_strongest_market(
    results: List[Dict],
) -> Optional[Dict]:

    valid = get_valid_results(
        results
    )

    if not valid:
        return None

    valid.sort(
        key=lambda item: (
            item.get(
                "absolute_score",
                0,
            ),
            item.get(
                "volume",
                0,
            ),
        ),
        reverse=True,
    )

    return valid[0]


# ============================================================
# TOP MARKET RANKING
# ============================================================

def rank_markets(
    results: List[Dict],
    limit: int = 10,
) -> List[Dict]:

    valid = get_valid_results(
        results
    )

    valid.sort(
        key=lambda item: (
            item.get(
                "absolute_score",
                0,
            ),
            item.get(
                "volume",
                0,
            ),
        ),
        reverse=True,
    )

    return valid[
        :max(
            1,
            int(limit),
        )
    ]


# ============================================================
# SCANNER SUMMARY
# ============================================================

def scanner_summary(
    results: List[Dict],
) -> Dict:

    valid = get_valid_results(
        results
    )

    confirmed = get_confirmed_setups(
        results
    )

    buy_count = sum(
        1
        for item in valid
        if item.get(
            "signal"
        )
        == "BUY"
    )

    sell_count = sum(
        1
        for item in valid
        if item.get(
            "signal"
        )
        == "SELL"
    )

    no_trade_count = sum(
        1
        for item in valid
        if item.get(
            "signal"
        )
        == "NO TRADE"
    )

    best = select_best_setup(
        results
    )

    strongest = select_strongest_market(
        results
    )

    return {
        "requested_markets":
            len(results),

        "valid_markets":
            len(valid),

        "confirmed_setups":
            len(confirmed),

        "buy_signals":
            buy_count,

        "sell_signals":
            sell_count,

        "no_trade_signals":
            no_trade_count,

        "best_setup":
            best,

        "strongest_market":
            strongest,
    }

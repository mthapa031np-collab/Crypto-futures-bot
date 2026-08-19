"""
scanner.py

PRO AI QUANT TERMINAL V5.5
ADAPTIVE CRYPTO OPPORTUNITY SCANNER

Purpose
-------
Fast, selective crypto opportunity discovery for 1-3 hour PAPER trades.

Contract preserved
------------------
- scan_markets()
- scanner_summary(results)

Design
------
- Uses existing PUBLIC market_data.get_candles()
- Uses existing signal_engine.generate_signal() as one input
- Adds adaptive trend / momentum / breakout / volatility scoring
- Avoids forcing trades in weak or conflicting conditions
- Produces BUY / SELL only when multiple factors align
- Leaves final multi-timeframe confirmation to strategy_engine.py
- PAPER ONLY. This module never executes orders.

Important
---------
This scanner is intentionally an opportunity detector, not an execution engine.
Risk approval and trade execution remain downstream.
"""

from __future__ import annotations

import math
import os
from typing import Any, Dict, List, Optional

import pandas as pd

from market_data import get_candles
from settings import SCAN_MARKETS
from signal_engine import generate_signal


# ============================================================
# CONFIG
# ============================================================

SCAN_TIMEFRAME_MINUTES = int(
    os.environ.get(
        "CRYPTO_SCAN_TIMEFRAME_MINUTES",
        "15",
    )
)

SCAN_CANDLE_LIMIT = int(
    os.environ.get(
        "CRYPTO_SCAN_CANDLE_LIMIT",
        "120",
    )
)

MIN_CANDLES = 60

BASE_ENTRY_SCORE = float(
    os.environ.get(
        "CRYPTO_SCANNER_ENTRY_SCORE",
        "3.0",
    )
)

HIGH_VOL_ATR_PCT = float(
    os.environ.get(
        "CRYPTO_HIGH_VOL_ATR_PCT",
        "1.8",
    )
)

LOW_VOL_ATR_PCT = float(
    os.environ.get(
        "CRYPTO_LOW_VOL_ATR_PCT",
        "0.25",
    )
)

MIN_VOLUME_RATIO = float(
    os.environ.get(
        "CRYPTO_MIN_VOLUME_RATIO",
        "0.80",
    )
)


# ============================================================
# HELPERS
# ============================================================

def _safe_float(
    value: Any,
    default: float = 0.0,
) -> float:

    try:
        if value is None:
            return default

        number = float(value)

        if not math.isfinite(number):
            return default

        return number

    except (
        TypeError,
        ValueError,
    ):
        return default


def _normalize_symbol(
    symbol: Any,
) -> str:

    return (
        str(symbol or "")
        .upper()
        .replace("/", "")
        .replace("-", "")
        .replace(" ", "")
        .strip()
    )


def _required_columns_exist(
    candles: pd.DataFrame,
) -> bool:

    required = {
        "open",
        "high",
        "low",
        "close",
        "volume",
    }

    return (
        isinstance(candles, pd.DataFrame)
        and required.issubset(
            set(candles.columns)
        )
    )


def _clean_frame(
    candles: pd.DataFrame,
) -> Optional[pd.DataFrame]:

    if not _required_columns_exist(
        candles
    ):
        return None

    frame = candles.copy()

    for column in (
        "open",
        "high",
        "low",
        "close",
        "volume",
    ):
        frame[column] = pd.to_numeric(
            frame[column],
            errors="coerce",
        )

    frame = frame.dropna(
        subset=[
            "open",
            "high",
            "low",
            "close",
        ]
    )

    if len(frame) < MIN_CANDLES:
        return None

    return frame


def _ema(
    series: pd.Series,
    span: int,
) -> pd.Series:

    return series.ewm(
        span=span,
        adjust=False,
    ).mean()


def _rsi(
    close: pd.Series,
    period: int = 14,
) -> pd.Series:

    delta = close.diff()

    gain = delta.clip(
        lower=0
    )

    loss = (
        -delta.clip(
            upper=0
        )
    )

    avg_gain = gain.ewm(
        alpha=1 / period,
        adjust=False,
        min_periods=period,
    ).mean()

    avg_loss = loss.ewm(
        alpha=1 / period,
        adjust=False,
        min_periods=period,
    ).mean()

    rs = (
        avg_gain
        / avg_loss.replace(
            0,
            float("nan"),
        )
    )

    rsi = (
        100
        - (
            100
            / (
                1 + rs
            )
        )
    )

    return rsi.fillna(
        50.0
    )


def _atr(
    frame: pd.DataFrame,
    period: int = 14,
) -> pd.Series:

    high = frame["high"]
    low = frame["low"]
    close = frame["close"]

    previous_close = close.shift(
        1
    )

    true_range = pd.concat(
        [
            high - low,
            (
                high
                - previous_close
            ).abs(),
            (
                low
                - previous_close
            ).abs(),
        ],
        axis=1,
    ).max(
        axis=1
    )

    return true_range.ewm(
        alpha=1 / period,
        adjust=False,
        min_periods=period,
    ).mean()


def _macd(
    close: pd.Series,
) -> Dict[str, pd.Series]:

    fast = _ema(
        close,
        12,
    )

    slow = _ema(
        close,
        26,
    )

    line = (
        fast
        - slow
    )

    signal = _ema(
        line,
        9,
    )

    histogram = (
        line
        - signal
    )

    return {
        "line":
            line,

        "signal":
            signal,

        "histogram":
            histogram,
    }


# ============================================================
# ADAPTIVE MARKET ANALYSIS
# ============================================================

def analyse_market(
    symbol: str,
) -> Dict[str, Any]:

    symbol = _normalize_symbol(
        symbol
    )

    empty = {
        "symbol":
            symbol,

        "valid":
            False,

        "price":
            0.0,

        "signal":
            "NO TRADE",

        "score":
            0.0,

        "absolute_score":
            0.0,

        "confirmed":
            False,

        "rsi":
            None,

        "macd":
            None,

        "change_pct":
            0.0,

        "high":
            0.0,

        "low":
            0.0,

        "volume":
            0.0,

        "atr_pct":
            0.0,

        "volume_ratio":
            0.0,

        "entry_threshold":
            BASE_ENTRY_SCORE,

        "reason":
            "No valid market data",
    }

    if not symbol:
        return empty

    try:
        candles = get_candles(
            exchange="PUBLIC",
            symbol=symbol,
            timeframe_minutes=(
                SCAN_TIMEFRAME_MINUTES
            ),
            limit=(
                SCAN_CANDLE_LIMIT
            ),
            api_key="",
            api_secret="",
            use_testnet=False,
        )

    except Exception as error:

        empty["reason"] = (
            "Market data error: "
            f"{error}"
        )

        return empty

    frame = _clean_frame(
        candles
    )

    if frame is None:

        empty["reason"] = (
            "Insufficient or invalid candles"
        )

        return empty

    close = frame[
        "close"
    ]

    # Use the most recent available market price for display/entry handoff,
    # but all trend calculations are smoothed and therefore less sensitive
    # to one unfinished candle.
    price = _safe_float(
        close.iloc[-1]
    )

    if price <= 0:

        empty["reason"] = (
            "Invalid latest close"
        )

        return empty

    ema9 = _ema(
        close,
        9,
    )

    ema20 = _ema(
        close,
        20,
    )

    ema50 = _ema(
        close,
        50,
    )

    rsi_series = _rsi(
        close,
        14,
    )

    macd = _macd(
        close
    )

    atr_series = _atr(
        frame,
        14,
    )

    rsi_value = _safe_float(
        rsi_series.iloc[-1],
        50.0,
    )

    macd_line = _safe_float(
        macd[
            "line"
        ].iloc[-1]
    )

    macd_signal = _safe_float(
        macd[
            "signal"
        ].iloc[-1]
    )

    macd_hist = _safe_float(
        macd[
            "histogram"
        ].iloc[-1]
    )

    macd_hist_prev = _safe_float(
        macd[
            "histogram"
        ].iloc[-2]
    )

    atr_value = _safe_float(
        atr_series.iloc[-1]
    )

    atr_pct = (
        atr_value
        / price
        * 100
        if price > 0
        else 0.0
    )

    ema9_value = _safe_float(
        ema9.iloc[-1]
    )

    ema20_value = _safe_float(
        ema20.iloc[-1]
    )

    ema50_value = _safe_float(
        ema50.iloc[-1]
    )

    previous_close = _safe_float(
        close.iloc[-2]
    )

    change_pct = (
        (
            price
            - previous_close
        )
        / previous_close
        * 100
        if previous_close > 0
        else 0.0
    )

    recent_high = _safe_float(
        frame[
            "high"
        ].iloc[-21:-1].max()
    )

    recent_low = _safe_float(
        frame[
            "low"
        ].iloc[-21:-1].min()
    )

    current_high = _safe_float(
        frame[
            "high"
        ].iloc[-1]
    )

    current_low = _safe_float(
        frame[
            "low"
        ].iloc[-1]
    )

    current_volume = _safe_float(
        frame[
            "volume"
        ].iloc[-1]
    )

    median_volume = _safe_float(
        frame[
            "volume"
        ].iloc[-21:-1].median()
    )

    volume_ratio = (
        current_volume
        / median_volume
        if median_volume > 0
        else 1.0
    )

    score = 0.0
    reasons: List[str] = []

    # --------------------------------------------------------
    # 1) TREND STRUCTURE
    # Max contribution: Â±2.0
    # --------------------------------------------------------

    if (
        ema9_value
        > ema20_value
        > ema50_value
    ):
        score += 2.0
        reasons.append(
            "EMA9>20>50 bullish"
        )

    elif (
        ema9_value
        < ema20_value
        < ema50_value
    ):
        score -= 2.0
        reasons.append(
            "EMA9<20<50 bearish"
        )

    elif (
        ema20_value
        > ema50_value
    ):
        score += 0.75
        reasons.append(
            "medium trend bullish"
        )

    elif (
        ema20_value
        < ema50_value
    ):
        score -= 0.75
        reasons.append(
            "medium trend bearish"
        )

    # --------------------------------------------------------
    # 2) RSI MOMENTUM
    # Max contribution: Â±1.25
    # Avoid chasing extreme RSI.
    # --------------------------------------------------------

    if (
        54.0
        <= rsi_value
        <= 68.0
    ):
        score += 1.25
        reasons.append(
            f"RSI bullish {rsi_value:.1f}"
        )

    elif (
        32.0
        <= rsi_value
        <= 46.0
    ):
        score -= 1.25
        reasons.append(
            f"RSI bearish {rsi_value:.1f}"
        )

    elif rsi_value > 76.0:
        score -= 0.35
        reasons.append(
            f"RSI overextended {rsi_value:.1f}"
        )

    elif rsi_value < 24.0:
        score += 0.35
        reasons.append(
            f"RSI oversold {rsi_value:.1f}"
        )

    # --------------------------------------------------------
    # 3) MACD DIRECTION + ACCELERATION
    # Max contribution: Â±1.5
    # --------------------------------------------------------

    if (
        macd_line
        > macd_signal
        and macd_hist > 0
    ):
        score += 1.0

        if (
            macd_hist
            > macd_hist_prev
        ):
            score += 0.5
            reasons.append(
                "MACD bullish accelerating"
            )
        else:
            reasons.append(
                "MACD bullish"
            )

    elif (
        macd_line
        < macd_signal
        and macd_hist < 0
    ):
        score -= 1.0

        if (
            macd_hist
            < macd_hist_prev
        ):
            score -= 0.5
            reasons.append(
                "MACD bearish accelerating"
            )
        else:
            reasons.append(
                "MACD bearish"
            )

    # --------------------------------------------------------
    # 4) 20-BAR BREAKOUT / BREAKDOWN
    # Max contribution: Â±1.5
    # --------------------------------------------------------

    breakout_buffer = (
        max(
            atr_value * 0.08,
            price * 0.0005,
        )
    )

    bullish_breakout = (
        recent_high > 0
        and price
        > recent_high
        + breakout_buffer
    )

    bearish_breakdown = (
        recent_low > 0
        and price
        < recent_low
        - breakout_buffer
    )

    if bullish_breakout:
        score += 1.5
        reasons.append(
            "20-bar breakout"
        )

    elif bearish_breakdown:
        score -= 1.5
        reasons.append(
            "20-bar breakdown"
        )

    # --------------------------------------------------------
    # 5) VOLUME PARTICIPATION
    # Directional only when current candle agrees.
    # Max contribution: Â±0.75
    # --------------------------------------------------------

    candle_direction = (
        price
        - _safe_float(
            frame[
                "open"
            ].iloc[-1]
        )
    )

    if (
        volume_ratio >= 1.20
        and candle_direction > 0
    ):
        score += 0.75
        reasons.append(
            f"volume expansion {volume_ratio:.2f}x"
        )

    elif (
        volume_ratio >= 1.20
        and candle_direction < 0
    ):
        score -= 0.75
        reasons.append(
            f"volume expansion {volume_ratio:.2f}x"
        )

    # --------------------------------------------------------
    # 6) EXISTING SIGNAL ENGINE
    # Reuse it, but do not let a single legacy signal dominate.
    # Max contribution: Â±1.0
    # --------------------------------------------------------

    legacy_signal = (
        "NO TRADE"
    )

    legacy_score = 0.0

    try:
        legacy = generate_signal(
            frame
        )

        if isinstance(
            legacy,
            dict,
        ):
            legacy_signal = str(
                legacy.get(
                    "signal",
                    "NO TRADE",
                )
            ).upper().strip()

            legacy_score = _safe_float(
                legacy.get(
                    "score"
                )
            )

            if legacy_signal == "BUY":
                score += 1.0
                reasons.append(
                    "legacy engine BUY"
                )

            elif legacy_signal == "SELL":
                score -= 1.0
                reasons.append(
                    "legacy engine SELL"
                )

    except Exception as error:
        reasons.append(
            "legacy engine unavailable"
        )

    # --------------------------------------------------------
    # ADAPTIVE ENTRY THRESHOLD
    # --------------------------------------------------------

    threshold = (
        BASE_ENTRY_SCORE
    )

    if atr_pct >= HIGH_VOL_ATR_PCT:
        threshold += 0.75
        reasons.append(
            "high-vol threshold raised"
        )

    elif (
        atr_pct > 0
        and atr_pct
        <= LOW_VOL_ATR_PCT
    ):
        threshold += 0.50
        reasons.append(
            "low-vol threshold raised"
        )

    if volume_ratio < MIN_VOLUME_RATIO:
        threshold += 0.50
        reasons.append(
            "thin-volume threshold raised"
        )

    # --------------------------------------------------------
    # DIRECTIONAL GUARDS
    # These stop threshold tuning from turning into forced trading.
    # --------------------------------------------------------

    bullish_structure = (
        ema20_value
        > ema50_value
        and ema9_value
        >= ema20_value
    )

    bearish_structure = (
        ema20_value
        < ema50_value
        and ema9_value
        <= ema20_value
    )

    bullish_momentum = (
        rsi_value >= 50.0
        and macd_hist >= 0
    )

    bearish_momentum = (
        rsi_value <= 50.0
        and macd_hist <= 0
    )

    final_signal = (
        "NO TRADE"
    )

    if (
        score >= threshold
        and bullish_structure
        and bullish_momentum
        and rsi_value < 76.0
    ):
        final_signal = "BUY"

    elif (
        score <= -threshold
        and bearish_structure
        and bearish_momentum
        and rsi_value > 24.0
    ):
        final_signal = "SELL"

    confirmed = (
        final_signal
        in (
            "BUY",
            "SELL",
        )
    )

    if not confirmed:
        reasons.append(
            (
                "below adaptive entry gate "
                f"{threshold:.2f}"
            )
        )

    return {
        "symbol":
            symbol,

        "valid":
            True,

        "price":
            round(
                price,
                8,
            ),

        "entry_price":
            round(
                price,
                8,
            ),

        "signal":
            final_signal,

        "score":
            round(
                score,
                3,
            ),

        "absolute_score":
            round(
                abs(
                    score
                ),
                3,
            ),

        "confirmed":
            confirmed,

        "rsi":
            round(
                rsi_value,
                3,
            ),

        "macd":
            round(
                macd_line,
                8,
            ),

        "macd_signal":
            round(
                macd_signal,
                8,
            ),

        "macd_histogram":
            round(
                macd_hist,
                8,
            ),

        "change_pct":
            round(
                change_pct,
                4,
            ),

        "high":
            current_high,

        "low":
            current_low,

        "volume":
            current_volume,

        "atr_pct":
            round(
                atr_pct,
                4,
            ),

        "volume_ratio":
            round(
                volume_ratio,
                3,
            ),

        "entry_threshold":
            round(
                threshold,
                3,
            ),

        "legacy_signal":
            legacy_signal,

        "legacy_score":
            round(
                legacy_score,
                3,
            ),

        "reason":
            ", ".join(
                reasons
            ),
    }


# ============================================================
# SCAN ALL MARKETS
# ============================================================

def scan_markets() -> List[Dict[str, Any]]:

    results: List[
        Dict[str, Any]
    ] = []

    for raw_symbol in SCAN_MARKETS:

        symbol = _normalize_symbol(
            raw_symbol
        )

        try:
            result = analyse_market(
                symbol
            )

        except Exception as error:

            result = {
                "symbol":
                    symbol,

                "valid":
                    False,

                "price":
                    0.0,

                "signal":
                    "NO TRADE",

                "score":
                    0.0,

                "absolute_score":
                    0.0,

                "confirmed":
                    False,

                "rsi":
                    None,

                "macd":
                    None,

                "change_pct":
                    0.0,

                "high":
                    0.0,

                "low":
                    0.0,

                "volume":
                    0.0,

                "reason":
                    (
                        "Scanner error: "
                        f"{error}"
                    ),
            }

        results.append(
            result
        )

    return results


# ============================================================
# SCANNER SUMMARY
# ============================================================

def scanner_summary(
    results: List[
        Dict[str, Any]
    ],
) -> Dict[str, Any]:

    if not isinstance(
        results,
        list,
    ):

        results = []

    valid_results = [
        item
        for item in results
        if (
            isinstance(
                item,
                dict,
            )
            and item.get(
                "valid",
                False,
            )
        )
    ]

    if not valid_results:

        return {
            "markets_scanned":
                len(
                    results
                ),

            "valid_markets":
                0,

            "qualifying_markets":
                0,

            "strongest_market":
                None,

            "best_setup":
                None,

            "buy_count":
                0,

            "sell_count":
                0,

            "no_trade_count":
                len(
                    results
                ),
        }

    strongest_market = max(
        valid_results,
        key=lambda item: _safe_float(
            item.get(
                "absolute_score"
            )
        ),
    )

    qualifying = [
        item
        for item in valid_results
        if (
            item.get(
                "confirmed",
                False,
            )
            and item.get(
                "signal"
            )
            in (
                "BUY",
                "SELL",
            )
        )
    ]

    best_setup = None

    if qualifying:

        # Quality first. If scores tie, prefer stronger
        # participation and reasonable ATR.
        best_setup = max(
            qualifying,
            key=lambda item: (
                _safe_float(
                    item.get(
                        "absolute_score"
                    )
                ),
                _safe_float(
                    item.get(
                        "volume_ratio"
                    )
                ),
                -abs(
                    _safe_float(
                        item.get(
                            "atr_pct"
                        )
                    )
                    - 0.8
                ),
            ),
        )

    buy_count = sum(
        1
        for item in valid_results
        if item.get(
            "signal"
        ) == "BUY"
    )

    sell_count = sum(
        1
        for item in valid_results
        if item.get(
            "signal"
        ) == "SELL"
    )

    no_trade_count = (
        len(
            valid_results
        )
        - buy_count
        - sell_count
    )

    return {
        "markets_scanned":
            len(
                results
            ),

        "valid_markets":
            len(
                valid_results
            ),

        "qualifying_markets":
            len(
                qualifying
            ),

        "strongest_market":
            strongest_market,

        "best_setup":
            best_setup,

        "buy_count":
            buy_count,

        "sell_count":
            sell_count,

        "no_trade_count":
            no_trade_count,
    }


# ============================================================
# HEALTH
# ============================================================

def scanner_health() -> Dict[str, Any]:

    return {
        "ok":
            True,

        "engine":
            "V5.5 Adaptive Crypto Opportunity Scanner",

        "timeframe_minutes":
            SCAN_TIMEFRAME_MINUTES,

        "candle_limit":
            SCAN_CANDLE_LIMIT,

        "base_entry_score":
            BASE_ENTRY_SCORE,

        "high_vol_atr_pct":
            HIGH_VOL_ATR_PCT,

        "low_vol_atr_pct":
            LOW_VOL_ATR_PCT,

        "paper_only":
            True,

        "real_execution":
            False,
    }

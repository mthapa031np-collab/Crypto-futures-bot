"""
metals_scanner.py

PRO AI QUANT TERMINAL V3.8

Gold / Silver Multi-Timeframe Safety Scanner

Supported markets:
    XAUUSD
    XAGUSD

Uses:
    15m
    1h
    4h

Indicators:
    EMA 20 / EMA 50
    RSI 14
    MACD 12 / 26 / 9
    ATR 14
    Momentum
    Multi-Timeframe confirmation

Safety:
- Fresh live quote required
- Local PostgreSQL candles required
- WARMING_UP state while history builds
- All 15m / 1h / 4h timeframes must be valid
- Higher timeframe confirmation required
- ATR target validation required

IMPORTANT:
    PAPER TRADING ONLY
    NO REAL ORDERS
"""

from typing import Dict, List, Optional

import numpy as np
import pandas as pd

from metals_candles import (
    get_metals_mtf_candles,
    metals_candles_cache_status,
    get_metals_candle_readiness,
)

from metals_engine import (
    build_metal_snapshot,
)

from metals_provider import (
    get_metal_quote,
)


# ============================================================
# CONFIG
# ============================================================

METAL_MARKETS = (
    "XAUUSD",
    "XAGUSD",
)

TIMEFRAMES = (
    "15m",
    "1h",
    "4h",
)

MIN_CANDLES = 60

MIN_ENTRY_SCORE = 6
MIN_MTF_CONFIDENCE = 66.0

RSI_OVERSOLD = 30.0
RSI_OVERBOUGHT = 70.0

ATR_SL_MULTIPLIER = {
    "XAUUSD": 1.50,
    "XAGUSD": 1.65,
}

ATR_TP_MULTIPLIER = {
    "XAUUSD": 2.40,
    "XAGUSD": 2.60,
}

DEFAULT_METALS_RISK_PCT = 1.0


# ============================================================
# SAFE HELPERS
# ============================================================

def _safe_float(
    value,
    default=0.0,
):

    try:

        if value is None:
            return default

        value = float(value)

        if not np.isfinite(value):
            return default

        return value

    except (
        TypeError,
        ValueError,
    ):

        return default


def _empty_timeframe_result(
    timeframe,
    reason,
):

    return {
        "timeframe": timeframe,
        "valid": False,
        "direction": "NEUTRAL",
        "score": 0,
        "confidence": 0.0,
        "close": 0.0,
        "ema20": 0.0,
        "ema50": 0.0,
        "rsi": 50.0,
        "macd": 0.0,
        "macd_signal": 0.0,
        "macd_histogram": 0.0,
        "atr": 0.0,
        "atr_pct": 0.0,
        "momentum_pct": 0.0,
        "reason": reason,
    }


def _no_trade_result(
    symbol: str,
    reason: str,
    market_snapshot: Optional[Dict] = None,
    quote: Optional[Dict] = None,
    timeframes: Optional[Dict] = None,
) -> Dict:

    return {
        "symbol": symbol,
        "asset_class": "METAL",
        "signal": "NO TRADE",
        "score": 0.0,
        "mtf_confidence": 0.0,
        "higher_tf_confirmed": False,
        "approved": False,
        "entry_price": 0.0,
        "targets": {},
        "risk_pct": DEFAULT_METALS_RISK_PCT,
        "timeframes": timeframes or {},
        "market_snapshot": market_snapshot or {},
        "quote": quote or {},
        "quote_fresh": False,
        "candles_fresh": False,
        "safety_gate": False,
        "reason": reason,
    }


# ============================================================
# QUOTE SAFETY
# ============================================================

def _quote_is_safe(
    quote: Optional[Dict],
) -> bool:

    if not quote:
        return False

    last = _safe_float(
        quote.get(
            "last"
        )
    )

    if last <= 0:
        return False

    if quote.get(
        "stale",
        False,
    ):
        return False

    if quote.get(
        "data_fresh",
        True,
    ) is False:
        return False

    if quote.get(
        "tradable_data",
        True,
    ) is False:
        return False

    return True


# ============================================================
# CANDLE CACHE EXPECTATION
# ============================================================

def _expected_candle_cache_keys(
    symbol: str,
):

    return {
        "15m": f"{symbol}:15min:200",
        "1h": f"{symbol}:1h:200",
        "4h": f"{symbol}:4h:200",
    }


# ============================================================
# CANDLE FRESHNESS
# ============================================================

def _check_candle_freshness(
    symbol: str,
) -> Dict:

    try:

        cache_status = (
            metals_candles_cache_status(
                symbol
            )
        )

    except Exception as error:

        return {
            "all_fresh": False,
            "timeframes": {},
            "reason": str(error),
        }

    expected = (
        _expected_candle_cache_keys(
            symbol
        )
    )

    frames = {}

    all_fresh = True

    for timeframe, cache_key in (
        expected.items()
    ):

        info = (
            cache_status.get(
                cache_key,
                {}
            )
        )

        fresh = bool(
            info.get(
                "fresh",
                False,
            )
        )

        frames[
            timeframe
        ] = {
            "fresh": fresh,
            "ready": info.get(
                "ready",
                fresh,
            ),
            "state": info.get(
                "state",
                (
                    "READY"
                    if fresh
                    else "WARMING_UP"
                ),
            ),
            "candles": info.get(
                "candles",
                0,
            ),
            "minimum": info.get(
                "minimum",
                MIN_CANDLES,
            ),
            "remaining": info.get(
                "remaining",
                0,
            ),
            "source": info.get(
                "source",
                "LOCAL_POSTGRES_OHLC",
            ),
        }

        if not fresh:
            all_fresh = False

    return {
        "all_fresh": all_fresh,
        "timeframes": frames,
        "provider": cache_status.get(
            "provider"
        ),
        "external_api": cache_status.get(
            "external_api",
            False,
        ),
    }


# ============================================================
# EMA
# ============================================================

def calculate_ema(
    series,
    period,
):

    numeric = (
        pd.to_numeric(
            series,
            errors="coerce",
        )
        .dropna()
    )

    if len(numeric) < period:
        return 0.0

    result = (
        numeric
        .ewm(
            span=period,
            adjust=False,
        )
        .mean()
        .iloc[-1]
    )

    return _safe_float(
        result
    )


# ============================================================
# RSI
# ============================================================

def calculate_rsi(
    series,
    period=14,
):

    numeric = (
        pd.to_numeric(
            series,
            errors="coerce",
        )
        .dropna()
    )

    if len(numeric) < (
        period + 1
    ):
        return 50.0

    delta = (
        numeric.diff()
    )

    gains = (
        delta.clip(
            lower=0
        )
    )

    losses = (
        -delta.clip(
            upper=0
        )
    )

    average_gain = (
        gains
        .ewm(
            alpha=1 / period,
            adjust=False,
        )
        .mean()
    )

    average_loss = (
        losses
        .ewm(
            alpha=1 / period,
            adjust=False,
        )
        .mean()
    )

    last_gain = _safe_float(
        average_gain.iloc[-1]
    )

    last_loss = _safe_float(
        average_loss.iloc[-1]
    )

    if last_loss <= 0:
        return 100.0

    rs = (
        last_gain
        / last_loss
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

    return _safe_float(
        rsi,
        50.0,
    )


# ============================================================
# MACD
# ============================================================

def calculate_macd(
    series,
):

    numeric = (
        pd.to_numeric(
            series,
            errors="coerce",
        )
        .dropna()
    )

    if len(numeric) < 35:

        return {
            "macd": 0.0,
            "signal": 0.0,
            "histogram": 0.0,
        }

    ema_fast = (
        numeric
        .ewm(
            span=12,
            adjust=False,
        )
        .mean()
    )

    ema_slow = (
        numeric
        .ewm(
            span=26,
            adjust=False,
        )
        .mean()
    )

    macd_line = (
        ema_fast
        - ema_slow
    )

    signal_line = (
        macd_line
        .ewm(
            span=9,
            adjust=False,
        )
        .mean()
    )

    histogram = (
        macd_line
        - signal_line
    )

    return {
        "macd":
            _safe_float(
                macd_line.iloc[-1]
            ),

        "signal":
            _safe_float(
                signal_line.iloc[-1]
            ),

        "histogram":
            _safe_float(
                histogram.iloc[-1]
            ),
    }


# ============================================================
# ATR
# ============================================================

def calculate_atr(
    dataframe,
    period=14,
):

    if (
        dataframe is None
        or dataframe.empty
        or len(dataframe)
        < (
            period + 1
        )
    ):

        return 0.0

    high = (
        pd.to_numeric(
            dataframe["high"],
            errors="coerce",
        )
    )

    low = (
        pd.to_numeric(
            dataframe["low"],
            errors="coerce",
        )
    )

    close = (
        pd.to_numeric(
            dataframe["close"],
            errors="coerce",
        )
    )

    previous_close = (
        close.shift(1)
    )

    true_range = (
        pd.concat(
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
        )
        .max(
            axis=1
        )
    )

    atr = (
        true_range
        .ewm(
            alpha=1 / period,
            adjust=False,
        )
        .mean()
        .iloc[-1]
    )

    return _safe_float(
        atr
    )


# ============================================================
# MOMENTUM
# ============================================================

def calculate_momentum_pct(
    series,
    lookback=5,
):

    numeric = (
        pd.to_numeric(
            series,
            errors="coerce",
        )
        .dropna()
    )

    if len(numeric) <= lookback:
        return 0.0

    current = _safe_float(
        numeric.iloc[-1]
    )

    previous = _safe_float(
        numeric.iloc[
            -1 - lookback
        ]
    )

    if previous <= 0:
        return 0.0

    return (
        (
            current
            - previous
        )
        / previous
        * 100
    )
    # ============================================================
# TIMEFRAME ANALYSIS
# ============================================================

def analyze_timeframe(
    dataframe: pd.DataFrame,
    timeframe: str,
) -> Dict:

    if (
        dataframe is None
        or not isinstance(
            dataframe,
            pd.DataFrame,
        )
        or dataframe.empty
    ):

        return _empty_timeframe_result(
            timeframe,
            "No candle data",
        )

    required_columns = {
        "open",
        "high",
        "low",
        "close",
    }

    if not required_columns.issubset(
        set(
            dataframe.columns
        )
    ):

        return _empty_timeframe_result(
            timeframe,
            "Missing OHLC columns",
        )

    if len(
        dataframe
    ) < MIN_CANDLES:

        return _empty_timeframe_result(
            timeframe,
            (
                "Insufficient candles: "
                f"{len(dataframe)}/{MIN_CANDLES}"
            ),
        )

    close = (
        pd.to_numeric(
            dataframe["close"],
            errors="coerce",
        )
        .dropna()
    )

    if len(
        close
    ) < MIN_CANDLES:

        return _empty_timeframe_result(
            timeframe,
            "Invalid close series",
        )

    last_close = _safe_float(
        close.iloc[-1]
    )

    if last_close <= 0:

        return _empty_timeframe_result(
            timeframe,
            "Invalid last close",
        )

    ema20 = calculate_ema(
        close,
        20,
    )

    ema50 = calculate_ema(
        close,
        50,
    )

    rsi = calculate_rsi(
        close,
        14,
    )

    macd = calculate_macd(
        close
    )

    atr = calculate_atr(
        dataframe,
        14,
    )

    momentum_pct = (
        calculate_momentum_pct(
            close,
            5,
        )
    )

    atr_pct = 0.0

    if (
        atr > 0
        and last_close > 0
    ):

        atr_pct = (
            atr
            / last_close
            * 100
        )

    bullish_score = 0
    bearish_score = 0

    reasons = []

    # --------------------------------------------------------
    # TREND
    # --------------------------------------------------------

    if (
        ema20 > ema50
        and last_close > ema20
    ):

        bullish_score += 2
        reasons.append(
            "EMA trend bullish"
        )

    elif (
        ema20 < ema50
        and last_close < ema20
    ):

        bearish_score += 2
        reasons.append(
            "EMA trend bearish"
        )

    # --------------------------------------------------------
    # RSI
    # --------------------------------------------------------

    if (
        50.0 < rsi < RSI_OVERBOUGHT
    ):

        bullish_score += 1
        reasons.append(
            "RSI bullish"
        )

    elif (
        RSI_OVERSOLD < rsi < 50.0
    ):

        bearish_score += 1
        reasons.append(
            "RSI bearish"
        )

    elif rsi <= RSI_OVERSOLD:

        bullish_score += 1
        reasons.append(
            "RSI oversold"
        )

    elif rsi >= RSI_OVERBOUGHT:

        bearish_score += 1
        reasons.append(
            "RSI overbought"
        )

    # --------------------------------------------------------
    # MACD
    # --------------------------------------------------------

    macd_line = _safe_float(
        macd.get(
            "macd"
        )
    )

    macd_signal = _safe_float(
        macd.get(
            "signal"
        )
    )

    macd_histogram = _safe_float(
        macd.get(
            "histogram"
        )
    )

    if (
        macd_line > macd_signal
        and macd_histogram > 0
    ):

        bullish_score += 2
        reasons.append(
            "MACD bullish"
        )

    elif (
        macd_line < macd_signal
        and macd_histogram < 0
    ):

        bearish_score += 2
        reasons.append(
            "MACD bearish"
        )

    # --------------------------------------------------------
    # MOMENTUM
    # --------------------------------------------------------

    if momentum_pct > 0:

        bullish_score += 1
        reasons.append(
            "Positive momentum"
        )

    elif momentum_pct < 0:

        bearish_score += 1
        reasons.append(
            "Negative momentum"
        )

    # --------------------------------------------------------
    # DIRECTION
    # --------------------------------------------------------

    if bullish_score > bearish_score:

        direction = "BULLISH"
        score = bullish_score

    elif bearish_score > bullish_score:

        direction = "BEARISH"
        score = bearish_score

    else:

        direction = "NEUTRAL"
        score = 0

    max_score = 6

    confidence = (
        min(
            100.0,
            (
                score
                / max_score
                * 100
            ),
        )
        if score > 0
        else 0.0
    )

    return {
        "timeframe":
            timeframe,

        "valid":
            True,

        "direction":
            direction,

        "score":
            score,

        "confidence":
            round(
                confidence,
                2,
            ),

        "close":
            last_close,

        "ema20":
            ema20,

        "ema50":
            ema50,

        "rsi":
            rsi,

        "macd":
            macd_line,

        "macd_signal":
            macd_signal,

        "macd_histogram":
            macd_histogram,

        "atr":
            atr,

        "atr_pct":
            atr_pct,

        "momentum_pct":
            momentum_pct,

        "bullish_score":
            bullish_score,

        "bearish_score":
            bearish_score,

        "reason":
            ", ".join(
                reasons
            ),
    }


# ============================================================
# MULTI-TIMEFRAME ANALYSIS
# ============================================================

def analyze_metals_mtf(
    symbol: str,
) -> Dict:

    try:

        bundle = (
            get_metals_mtf_candles(
                symbol=symbol,
                limit=200,
            )
        )

    except Exception as error:

        return {
            timeframe:
                _empty_timeframe_result(
                    timeframe,
                    str(
                        error
                    ),
                )
            for timeframe in TIMEFRAMES
        }

    results = {}

    for timeframe in TIMEFRAMES:

        dataframe = (
            bundle.get(
                timeframe
            )
        )

        results[
            timeframe
        ] = analyze_timeframe(
            dataframe,
            timeframe,
        )

    return results


# ============================================================
# HIGHER TIMEFRAME CONFIRMATION
# ============================================================

def higher_timeframe_confirmation(
    analyses: Dict,
    desired_direction: str,
) -> Dict:

    one_hour = (
        analyses.get(
            "1h",
            {}
        )
    )

    four_hour = (
        analyses.get(
            "4h",
            {}
        )
    )

    confirmations = 0

    total = 2

    if (
        one_hour.get(
            "valid",
            False,
        )
        and one_hour.get(
            "direction"
        )
        == desired_direction
    ):

        confirmations += 1

    if (
        four_hour.get(
            "valid",
            False,
        )
        and four_hour.get(
            "direction"
        )
        == desired_direction
    ):

        confirmations += 1

    confidence = (
        confirmations
        / total
        * 100
    )

    return {
        "confirmed":
            confirmations
            == total,

        "confirmations":
            confirmations,

        "total":
            total,

        "confidence":
            round(
                confidence,
                2,
            ),
    }


# ============================================================
# WEIGHTED MTF SCORE
# ============================================================

def calculate_weighted_mtf_score(
    analyses: Dict,
) -> Dict:

    weights = {
        "15m": 0.30,
        "1h": 0.35,
        "4h": 0.35,
    }

    bullish = 0.0
    bearish = 0.0

    for timeframe, weight in (
        weights.items()
    ):

        info = (
            analyses.get(
                timeframe,
                {}
            )
        )

        if not info.get(
            "valid",
            False,
        ):

            continue

        score = _safe_float(
            info.get(
                "score"
            )
        )

        direction = (
            info.get(
                "direction"
            )
        )

        weighted = (
            score
            * weight
        )

        if direction == "BULLISH":

            bullish += weighted

        elif direction == "BEARISH":

            bearish += weighted

    if bullish > bearish:

        direction = "BULLISH"
        net_score = bullish

    elif bearish > bullish:

        direction = "BEARISH"
        net_score = bearish

    else:

        direction = "NEUTRAL"
        net_score = 0.0

    return {
        "direction":
            direction,

        "bullish_score":
            round(
                bullish,
                3,
            ),

        "bearish_score":
            round(
                bearish,
                3,
            ),

        "net_score":
            round(
                net_score,
                3,
            ),
    }


# ============================================================
# TARGET BUILDER
# ============================================================

def build_metal_targets(
    symbol: str,
    signal: str,
    entry_price: float,
    atr: float,
) -> Dict:

    entry_price = _safe_float(
        entry_price
    )

    atr = _safe_float(
        atr
    )

    if (
        entry_price <= 0
        or atr <= 0
    ):

        return {}

    sl_multiplier = (
        ATR_SL_MULTIPLIER.get(
            symbol,
            1.50,
        )
    )

    tp_multiplier = (
        ATR_TP_MULTIPLIER.get(
            symbol,
            2.40,
        )
    )

    if signal == "BUY":

        stop_loss = (
            entry_price
            - (
                atr
                * sl_multiplier
            )
        )

        take_profit = (
            entry_price
            + (
                atr
                * tp_multiplier
            )
        )

    elif signal == "SELL":

        stop_loss = (
            entry_price
            + (
                atr
                * sl_multiplier
            )
        )

        take_profit = (
            entry_price
            - (
                atr
                * tp_multiplier
            )
        )

    else:

        return {}

    risk_distance = abs(
        entry_price
        - stop_loss
    )

    reward_distance = abs(
        take_profit
        - entry_price
    )

    rr = 0.0

    if risk_distance > 0:

        rr = (
            reward_distance
            / risk_distance
        )

    return {
        "entry":
            entry_price,

        "take_profit":
            take_profit,

        "stop_loss":
            stop_loss,

        "risk_distance":
            risk_distance,

        "reward_distance":
            reward_distance,

        "risk_reward":
            rr,

        "atr":
            atr,

        "atr_sl_multiplier":
            sl_multiplier,

        "atr_tp_multiplier":
            tp_multiplier,
    }
    # ============================================================
# SIGNAL DIRECTION
# ============================================================

def determine_signal(
    analyses: Dict,
) -> Dict:

    weighted = (
        calculate_weighted_mtf_score(
            analyses
        )
    )

    direction = (
        weighted.get(
            "direction",
            "NEUTRAL",
        )
    )

    if direction == "BULLISH":

        signal = "BUY"

    elif direction == "BEARISH":

        signal = "SELL"

    else:

        signal = "NO TRADE"

    return {
        "signal":
            signal,

        "direction":
            direction,

        "weighted":
            weighted,
    }


# ============================================================
# WARM-UP PROGRESS
# ============================================================

def _build_warmup_reason(
    readiness: Dict,
) -> str:

    frames = (
        readiness.get(
            "timeframes",
            {},
        )
    )

    progress = []

    for timeframe in TIMEFRAMES:

        info = (
            frames.get(
                timeframe,
                {},
            )
        )

        candles = int(
            info.get(
                "candles",
                0,
            )
            or 0
        )

        minimum = int(
            info.get(
                "minimum",
                MIN_CANDLES,
            )
            or MIN_CANDLES
        )

        progress.append(
            f"{timeframe}: "
            f"{candles}/{minimum}"
        )

    return (
        "WARMING UP — building local "
        "Gold/Silver MTF history | "
        + " | ".join(
            progress
        )
    )


# ============================================================
# MAIN SINGLE-MARKET SCANNER
# ============================================================

def scan_metal_market(
    symbol: str,
) -> Dict:

    symbol = (
        str(symbol)
        .upper()
        .replace("/", "")
        .replace("-", "")
        .replace(" ", "")
        .strip()
    )

    if symbol not in METAL_MARKETS:

        return _no_trade_result(
            symbol,
            "Unsupported metals market",
        )

    # --------------------------------------------------------
    # LIVE QUOTE
    # --------------------------------------------------------

    try:

        quote = (
            get_metal_quote(
                symbol
            )
        )

    except Exception as error:

        return _no_trade_result(
            symbol,
            (
                "Metals quote error: "
                f"{error}"
            ),
        )

    if not _quote_is_safe(
        quote
    ):

        return _no_trade_result(
            symbol,
            "Invalid or stale metals quote",
            quote=quote,
        )

    entry_price = _safe_float(
        quote.get(
            "last"
        )
    )

    # --------------------------------------------------------
    # MARKET SNAPSHOT
    # --------------------------------------------------------

    try:

        market_snapshot = (
            build_metal_snapshot(
                symbol
            )
        )

    except Exception as error:

        market_snapshot = {
            "symbol": symbol,
            "error": str(
                error
            ),
        }

    # --------------------------------------------------------
    # SAFETY GATE 1:
    # LOCAL CANDLE READINESS
    # --------------------------------------------------------

    try:

        readiness = (
            get_metals_candle_readiness(
                symbol
            )
        )

    except Exception as error:

        return _no_trade_result(
            symbol,
            (
                "Metals candle readiness "
                f"error: {error}"
            ),
            market_snapshot=market_snapshot,
            quote=quote,
        )

    if not readiness.get(
        "ready",
        False,
    ):

        result = (
            _no_trade_result(
                symbol,
                _build_warmup_reason(
                    readiness
                ),
                market_snapshot=market_snapshot,
                quote=quote,
            )
        )

        result[
            "scanner_state"
        ] = "WARMING_UP"

        result[
            "candle_readiness"
        ] = readiness

        result[
            "history_ready"
        ] = False

        result[
            "quote_fresh"
        ] = bool(
            readiness.get(
                "quote_freshness",
                {},
            ).get(
                "fresh",
                False,
            )
        )

        return result

    # --------------------------------------------------------
    # CANDLE CACHE SAFETY
    # --------------------------------------------------------

    candle_freshness = (
        _check_candle_freshness(
            symbol
        )
    )

    if not candle_freshness.get(
        "all_fresh",
        False,
    ):

        result = (
            _no_trade_result(
                symbol,
                (
                    "Local metals candles "
                    "are not ready/fresh"
                ),
                market_snapshot=market_snapshot,
                quote=quote,
            )
        )

        result[
            "scanner_state"
        ] = "WARMING_UP"

        result[
            "candle_readiness"
        ] = readiness

        result[
            "candle_freshness"
        ] = candle_freshness

        result[
            "history_ready"
        ] = False

        return result

    # --------------------------------------------------------
    # ANALYZE ALL TIMEFRAMES
    # --------------------------------------------------------

    analyses = (
        analyze_metals_mtf(
            symbol
        )
    )

    # --------------------------------------------------------
    # SAFETY GATE 2:
    # EVERY TIMEFRAME MUST BE VALID
    # --------------------------------------------------------

    all_timeframes_valid = all(
        analyses.get(
            timeframe,
            {},
        ).get(
            "valid",
            False,
        )
        for timeframe in TIMEFRAMES
    )

    if not all_timeframes_valid:

        invalid = [
            timeframe
            for timeframe in TIMEFRAMES
            if not analyses.get(
                timeframe,
                {},
            ).get(
                "valid",
                False,
            )
        ]

        result = (
            _no_trade_result(
                symbol,
                (
                    "Candle history reports READY "
                    "but analysis is invalid: "
                    + ", ".join(
                        invalid
                    )
                ),
                market_snapshot=market_snapshot,
                quote=quote,
                timeframes=analyses,
            )
        )

        result[
            "scanner_state"
        ] = "DATA_ERROR"

        result[
            "candle_readiness"
        ] = readiness

        result[
            "history_ready"
        ] = True

        return result

    # --------------------------------------------------------
    # WEIGHTED MTF SIGNAL
    # --------------------------------------------------------

    signal_info = (
        determine_signal(
            analyses
        )
    )

    signal = (
        signal_info.get(
            "signal",
            "NO TRADE",
        )
    )

    weighted = (
        signal_info.get(
            "weighted",
            {},
        )
    )

    weighted_direction = (
        weighted.get(
            "direction",
            "NEUTRAL",
        )
    )

    weighted_score = _safe_float(
        weighted.get(
            "net_score"
        )
    )

    # --------------------------------------------------------
    # NO DIRECTION
    # --------------------------------------------------------

    if signal == "NO TRADE":

        result = (
            _no_trade_result(
                symbol,
                "No clear MTF metals direction",
                market_snapshot=market_snapshot,
                quote=quote,
                timeframes=analyses,
            )
        )

        result[
            "scanner_state"
        ] = "READY"

        result[
            "history_ready"
        ] = True

        result[
            "candle_readiness"
        ] = readiness

        result[
            "weighted_mtf"
        ] = weighted

        result[
            "quote_fresh"
        ] = True

        result[
            "candles_fresh"
        ] = True

        return result

    # --------------------------------------------------------
    # HIGHER-TIMEFRAME CONFIRMATION
    # --------------------------------------------------------

    confirmation = (
        higher_timeframe_confirmation(
            analyses,
            weighted_direction,
        )
    )

    mtf_confidence = _safe_float(
        confirmation.get(
            "confidence"
        )
    )

    # --------------------------------------------------------
    # ENTRY TIMEFRAME
    # --------------------------------------------------------

    entry_tf = (
        analyses.get(
            "15m",
            {}
        )
    )

    entry_direction = (
        entry_tf.get(
            "direction",
            "NEUTRAL",
        )
    )

    expected_entry_direction = (
        "BULLISH"
        if signal == "BUY"
        else "BEARISH"
    )

    if (
        entry_direction
        != expected_entry_direction
    ):

        result = (
            _no_trade_result(
                symbol,
                (
                    "15m entry timeframe does "
                    "not confirm MTF direction"
                ),
                market_snapshot=market_snapshot,
                quote=quote,
                timeframes=analyses,
            )
        )

        result[
            "scanner_state"
        ] = "READY"

        result[
            "history_ready"
        ] = True

        result[
            "weighted_mtf"
        ] = weighted

        result[
            "higher_tf_confirmation"
        ] = confirmation

        result[
            "quote_fresh"
        ] = True

        result[
            "candles_fresh"
        ] = True

        return result

    # --------------------------------------------------------
    # HIGHER-TF SAFETY GATE
    # --------------------------------------------------------

    if not confirmation.get(
        "confirmed",
        False,
    ):

        result = (
            _no_trade_result(
                symbol,
                (
                    "1h + 4h higher timeframe "
                    "confirmation not aligned"
                ),
                market_snapshot=market_snapshot,
                quote=quote,
                timeframes=analyses,
            )
        )

        result[
            "scanner_state"
        ] = "READY"

        result[
            "history_ready"
        ] = True

        result[
            "weighted_mtf"
        ] = weighted

        result[
            "higher_tf_confirmation"
        ] = confirmation

        result[
            "quote_fresh"
        ] = True

        result[
            "candles_fresh"
        ] = True

        return result

    # --------------------------------------------------------
    # CONFIDENCE GATE
    # --------------------------------------------------------

    if (
        mtf_confidence
        < MIN_MTF_CONFIDENCE
    ):

        result = (
            _no_trade_result(
                symbol,
                (
                    "MTF confidence below "
                    "minimum threshold"
                ),
                market_snapshot=market_snapshot,
                quote=quote,
                timeframes=analyses,
            )
        )

        result[
            "scanner_state"
        ] = "READY"

        result[
            "history_ready"
        ] = True

        result[
            "weighted_mtf"
        ] = weighted

        result[
            "higher_tf_confirmation"
        ] = confirmation

        result[
            "quote_fresh"
        ] = True

        result[
            "candles_fresh"
        ] = True

        return result

    # --------------------------------------------------------
    # ATR TARGET SOURCE
    # --------------------------------------------------------

    atr = _safe_float(
        entry_tf.get(
            "atr"
        )
    )

    if atr <= 0:

        result = (
            _no_trade_result(
                symbol,
                "Invalid ATR for metals targets",
                market_snapshot=market_snapshot,
                quote=quote,
                timeframes=analyses,
            )
        )

        result[
            "scanner_state"
        ] = "DATA_ERROR"

        result[
            "history_ready"
        ] = True

        return result

    # --------------------------------------------------------
    # TARGETS
    # --------------------------------------------------------

    targets = (
        build_metal_targets(
            symbol=symbol,
            signal=signal,
            entry_price=entry_price,
            atr=atr,
        )
    )

    if not targets:

        result = (
            _no_trade_result(
                symbol,
                "Could not build safe metals targets",
                market_snapshot=market_snapshot,
                quote=quote,
                timeframes=analyses,
            )
        )

        result[
            "scanner_state"
        ] = "DATA_ERROR"

        result[
            "history_ready"
        ] = True

        return result

    # --------------------------------------------------------
    # RISK / REWARD GATE
    # --------------------------------------------------------

    risk_reward = _safe_float(
        targets.get(
            "risk_reward"
        )
    )

    if risk_reward < 1.25:

        result = (
            _no_trade_result(
                symbol,
                (
                    "Risk/reward below "
                    "minimum threshold"
                ),
                market_snapshot=market_snapshot,
                quote=quote,
                timeframes=analyses,
            )
        )

        result[
            "scanner_state"
        ] = "READY"

        result[
            "history_ready"
        ] = True

        result[
            "targets"
        ] = targets

        return result
        # --------------------------------------------------------
    # FINAL SCORE NORMALIZATION
    # --------------------------------------------------------

    # Weighted MTF score is based on per-timeframe
    # technical strength. Convert it into a cleaner
    # 0–100 AI-style score for the UI / ranking layer.

    ai_score = min(
        100.0,
        (
            weighted_score
            / 6.0
            * 100
        )
        if weighted_score > 0
        else 0.0,
    )

    # --------------------------------------------------------
    # FINAL APPROVAL
    # --------------------------------------------------------

    approved = (
        signal
        in (
            "BUY",
            "SELL",
        )
        and confirmation.get(
            "confirmed",
            False,
        )
        and mtf_confidence
        >= MIN_MTF_CONFIDENCE
        and risk_reward
        >= 1.25
    )

    # --------------------------------------------------------
    # FINAL REASON
    # --------------------------------------------------------

    reason_parts = [
        f"{signal} setup",
        f"AI score {ai_score:.1f}",
        f"MTF confidence {mtf_confidence:.1f}%",
        "1h + 4h aligned",
        f"R/R {risk_reward:.2f}",
    ]

    # Include entry-TF reasoning when available.
    entry_reason = (
        entry_tf.get(
            "reason"
        )
    )

    if entry_reason:

        reason_parts.append(
            f"15m: {entry_reason}"
        )

    # --------------------------------------------------------
    # FINAL RESULT
    # --------------------------------------------------------

    return {
        "symbol":
            symbol,

        "asset_class":
            "METAL",

        "signal":
            signal,

        "score":
            round(
                ai_score,
                2,
            ),

        "raw_weighted_score":
            round(
                weighted_score,
                3,
            ),

        "mtf_confidence":
            round(
                mtf_confidence,
                2,
            ),

        "higher_tf_confirmed":
            confirmation.get(
                "confirmed",
                False,
            ),

        "approved":
            approved,

        "entry_price":
            entry_price,

        "targets":
            targets,

        "risk_pct":
            DEFAULT_METALS_RISK_PCT,

        "risk_reward":
            risk_reward,

        "timeframes":
            analyses,

        "market_snapshot":
            market_snapshot,

        "quote":
            quote,

        "quote_fresh":
            True,

        "candles_fresh":
            True,

        "safety_gate":
            True,

        "scanner_state":
            "READY",

        "history_ready":
            True,

        "candle_readiness":
            readiness,

        "weighted_mtf":
            weighted,

        "higher_tf_confirmation":
            confirmation,

        "reason":
            " | ".join(
                reason_parts
            ),
    }


# ============================================================
# BACKWARD-COMPATIBLE SINGLE-MARKET ALIAS
# ============================================================

def scan_metal(
    symbol: str,
) -> Dict:

    return scan_metal_market(
        symbol
    )


# ============================================================
# SCAN ALL METALS
# ============================================================

def scan_metals() -> List[Dict]:

    results = []

    for symbol in METAL_MARKETS:

        try:

            result = (
                scan_metal_market(
                    symbol
                )
            )

        except Exception as error:

            result = (
                _no_trade_result(
                    symbol,
                    (
                        "Scanner error: "
                        f"{error}"
                    ),
                )
            )

            result[
                "scanner_state"
            ] = "ERROR"

        results.append(
            result
        )

    return results


# ============================================================
# BEST APPROVED SETUP
# ============================================================

def get_best_metals_setup(
    results: Optional[List[Dict]] = None,
) -> Optional[Dict]:

    if results is None:

        results = (
            scan_metals()
        )

    approved = [
        item
        for item in results
        if item.get(
            "approved",
            False,
        )
    ]

    if not approved:

        return None

    approved.sort(
        key=lambda item: (
            _safe_float(
                item.get(
                    "score"
                )
            ),
            _safe_float(
                item.get(
                    "mtf_confidence"
                )
            ),
            _safe_float(
                item.get(
                    "risk_reward"
                )
            ),
        ),
        reverse=True,
    )

    return approved[
        0
    ]


# ============================================================
# STRONGEST MARKET
# ============================================================

def get_strongest_metals_market(
    results: Optional[List[Dict]] = None,
) -> Optional[Dict]:

    if results is None:

        results = (
            scan_metals()
        )

    usable = [
        item
        for item in results
        if item.get(
            "scanner_state"
        )
        in (
            "READY",
            "WARMING_UP",
        )
    ]

    if not usable:

        return None

    usable.sort(
        key=lambda item: (
            _safe_float(
                item.get(
                    "score"
                )
            ),
            _safe_float(
                item.get(
                    "mtf_confidence"
                )
            ),
        ),
        reverse=True,
    )

    return usable[
        0
    ]


# ============================================================
# SCANNER SUMMARY
# ============================================================

def metals_scanner_summary(
    results: Optional[List[Dict]] = None,
) -> Dict:

    if results is None:

        results = (
            scan_metals()
        )

    best_setup = (
        get_best_metals_setup(
            results
        )
    )

    strongest = (
        get_strongest_metals_market(
            results
        )
    )

    gold = next(
        (
            item
            for item in results
            if item.get(
                "symbol"
            ) == "XAUUSD"
        ),
        None,
    )

    silver = next(
        (
            item
            for item in results
            if item.get(
                "symbol"
            ) == "XAGUSD"
        ),
        None,
    )

    warming_up_count = sum(
        1
        for item in results
        if item.get(
            "scanner_state"
        )
        == "WARMING_UP"
    )

    ready_count = sum(
        1
        for item in results
        if item.get(
            "scanner_state"
        )
        == "READY"
    )

    approved_count = sum(
        1
        for item in results
        if item.get(
            "approved",
            False,
        )
    )

    error_count = sum(
        1
        for item in results
        if item.get(
            "scanner_state"
        )
        == "ERROR"
    )

    return {
        "markets":
            results,

        "gold":
            gold,

        "silver":
            silver,

        "strongest_market":
            strongest,

        "best_setup":
            best_setup,

        "approved_count":
            approved_count,

        "ready_count":
            ready_count,

        "warming_up_count":
            warming_up_count,

        "error_count":
            error_count,

        "total_markets":
            len(
                results
            ),

        "execution_enabled":
            False,

        "real_orders_enabled":
            False,
    }


# ============================================================
# POSITION SIZE
# ============================================================

def calculate_metals_position_size(
    account_balance: float,
    risk_pct: float,
    entry_price: float,
    stop_loss: float,
) -> float:

    account_balance = _safe_float(
        account_balance
    )

    risk_pct = _safe_float(
        risk_pct,
        DEFAULT_METALS_RISK_PCT,
    )

    entry_price = _safe_float(
        entry_price
    )

    stop_loss = _safe_float(
        stop_loss
    )

    if (
        account_balance <= 0
        or risk_pct <= 0
        or entry_price <= 0
        or stop_loss <= 0
    ):

        return 0.0

    risk_amount = (
        account_balance
        * risk_pct
        / 100
    )

    stop_distance = abs(
        entry_price
        - stop_loss
    )

    if stop_distance <= 0:

        return 0.0

    quantity = (
        risk_amount
        / stop_distance
    )

    return round(
        quantity,
        6,
    )


# ============================================================
# WARM-UP STATUS
# ============================================================

def metals_scanner_warmup_status() -> Dict:

    result = {
        "markets": {},
        "all_ready": True,
    }

    for symbol in METAL_MARKETS:

        try:

            readiness = (
                get_metals_candle_readiness(
                    symbol
                )
            )

        except Exception as error:

            readiness = {
                "symbol":
                    symbol,

                "ready":
                    False,

                "state":
                    "ERROR",

                "reason":
                    str(
                        error
                    ),

                "timeframes":
                    {},
            }

        result[
            "markets"
        ][
            symbol
        ] = readiness

        if not readiness.get(
            "ready",
            False,
        ):

            result[
                "all_ready"
            ] = False

    return result


# ============================================================
# HEALTH CHECK
# ============================================================

def metals_scanner_health() -> Dict:

    try:

        results = (
            scan_metals()
        )

        summary = (
            metals_scanner_summary(
                results
            )
        )

        warmup = (
            metals_scanner_warmup_status()
        )

        hard_errors = [
            item
            for item in results
            if item.get(
                "scanner_state"
            )
            == "ERROR"
        ]

        return {
            "ok":
                len(
                    hard_errors
                )
                == 0,

            "engine":
                "V3.8 Metals Scanner",

            "provider":
                "Gold-API + LOCAL_POSTGRES_OHLC",

            "markets":
                len(
                    results
                ),

            "ready_markets":
                summary.get(
                    "ready_count",
                    0,
                ),

            "warming_up_markets":
                summary.get(
                    "warming_up_count",
                    0,
                ),

            "approved_markets":
                summary.get(
                    "approved_count",
                    0,
                ),

            "errors":
                summary.get(
                    "error_count",
                    0,
                ),

            "all_history_ready":
                warmup.get(
                    "all_ready",
                    False,
                ),

            "paper_execution":
                True,

            "real_execution":
                False,
        }

    except Exception as error:

        return {
            "ok":
                False,

            "engine":
                "V3.8 Metals Scanner",

            "provider":
                "Gold-API + LOCAL_POSTGRES_OHLC",

            "reason":
                str(
                    error
                ),

            "paper_execution":
                True,

            "real_execution":
                False,
        }


# ============================================================
# SAFE DEBUG SNAPSHOT
# ============================================================

def debug_metals_scanner() -> Dict:

    results = (
        scan_metals()
    )

    return {
        "summary":
            metals_scanner_summary(
                results
            ),

        "warmup":
            metals_scanner_warmup_status(),

        "health":
            metals_scanner_health(),

        "real_orders":
            False,
    }

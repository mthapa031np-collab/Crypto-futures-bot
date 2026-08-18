"""
metals_scanner.py

PRO AI QUANT TERMINAL V3.7

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
- Stale quotes cannot approve trades
- Fresh candle data required
- Stale candle cache cannot approve trades
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


# Entry thresholds.
MIN_ENTRY_SCORE = 6
MIN_MTF_CONFIDENCE = 66.0


# RSI limits.
RSI_OVERSOLD = 30.0
RSI_OVERBOUGHT = 70.0


# ATR-based trade management.
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
        "symbol":
            symbol,

        "asset_class":
            "METAL",

        "signal":
            "NO TRADE",

        "score":
            0.0,

        "mtf_confidence":
            0.0,

        "higher_tf_confirmed":
            False,

        "approved":
            False,

        "entry_price":
            0.0,

        "targets":
            {},

        "risk_pct":
            DEFAULT_METALS_RISK_PCT,

        "timeframes":
            timeframes or {},

        "market_snapshot":
            market_snapshot or {},

        "quote":
            quote or {},

        "quote_fresh":
            False,

        "candles_fresh":
            False,

        "safety_gate":
            False,

        "reason":
            reason,
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
# CANDLE SAFETY
# ============================================================

def _expected_candle_cache_keys(
    symbol: str,
) -> Dict[str, str]:

    return {
        "15m":
            f"{symbol}:15min:200",

        "1h":
            f"{symbol}:1h:200",

        "4h":
            f"{symbol}:4h:200",
    }


def _check_candle_freshness(
    symbol: str,
) -> Dict:

    status = (
        metals_candles_cache_status()
    )

    expected = (
        _expected_candle_cache_keys(
            symbol
        )
    )

    result = {}

    all_fresh = True

    for timeframe, key in (
        expected.items()
    ):

        record = status.get(
            key
        )

        if not isinstance(
            record,
            dict,
        ):

            result[
                timeframe
            ] = {
                "fresh":
                    False,

                "reason":
                    "No candle cache record",
            }

            all_fresh = False

            continue

        fresh = bool(
            record.get(
                "fresh",
                False,
            )
        )

        result[
            timeframe
        ] = {
            "fresh":
                fresh,

            "age_seconds":
                record.get(
                    "age_seconds"
                ),

            "stale_usable":
                record.get(
                    "stale_usable",
                    False,
                ),
        }

        if not fresh:
            all_fresh = False

    return {
        "all_fresh":
            all_fresh,

        "timeframes":
            result,

        "provider_cooldown_seconds":
            status.get(
                "provider_cooldown_seconds",
                0,
            ),
    }


# ============================================================
# EMA
# ============================================================

def calculate_ema(
    series: pd.Series,
    period: int,
) -> pd.Series:

    return series.ewm(
        span=period,
        adjust=False,
    ).mean()


# ============================================================
# RSI
# ============================================================

def calculate_rsi(
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

    average_gain = gain.ewm(
        alpha=1 / period,
        adjust=False,
        min_periods=period,
    ).mean()

    average_loss = loss.ewm(
        alpha=1 / period,
        adjust=False,
        min_periods=period,
    ).mean()

    rs = (
        average_gain
        / average_loss.replace(
            0,
            np.nan,
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

    rsi = rsi.fillna(
        50.0
    )

    return rsi


# ============================================================
# MACD
# ============================================================

def calculate_macd(
    close: pd.Series,
):

    ema12 = calculate_ema(
        close,
        12,
    )

    ema26 = calculate_ema(
        close,
        26,
    )

    macd = (
        ema12
        - ema26
    )

    signal = calculate_ema(
        macd,
        9,
    )

    histogram = (
        macd
        - signal
    )

    return (
        macd,
        signal,
        histogram,
    )


# ============================================================
# ATR
# ============================================================

def calculate_atr(
    df: pd.DataFrame,
    period: int = 14,
) -> pd.Series:

    previous_close = (
        df["close"]
        .shift(1)
    )

    high_low = (
        df["high"]
        - df["low"]
    )

    high_previous = (
        df["high"]
        - previous_close
    ).abs()

    low_previous = (
        df["low"]
        - previous_close
    ).abs()

    true_range = pd.concat(
        [
            high_low,
            high_previous,
            low_previous,
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


# ============================================================
# MOMENTUM
# ============================================================

def calculate_momentum_pct(
    close: pd.Series,
    lookback: int = 10,
) -> float:

    if len(close) <= lookback:

        return 0.0

    current = _safe_float(
        close.iloc[-1]
    )

    previous = _safe_float(
        close.iloc[
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
# ANALYSE ONE TIMEFRAME
# ============================================================

def analyse_timeframe(
    df: pd.DataFrame,
    timeframe: str,
) -> Dict:

    if df is None:

        return _empty_timeframe_result(
            timeframe,
            "No candle dataframe",
        )

    if df.empty:

        return _empty_timeframe_result(
            timeframe,
            "No candle data",
        )

    if len(df) < MIN_CANDLES:

        return _empty_timeframe_result(
            timeframe,
            (
                f"Insufficient candles: "
                f"{len(df)}"
            ),
        )

    required = {
        "open",
        "high",
        "low",
        "close",
    }

    if not required.issubset(
        df.columns
    ):

        return _empty_timeframe_result(
            timeframe,
            "OHLC columns missing",
        )

    work = (
        df.copy()
        .reset_index(
            drop=True
        )
    )

    for column in required:

        work[
            column
        ] = pd.to_numeric(
            work[
                column
            ],
            errors="coerce",
        )

    work = work.dropna(
        subset=list(
            required
        )
    )

    if len(work) < MIN_CANDLES:

        return _empty_timeframe_result(
            timeframe,
            "Insufficient clean candles",
        )

    close = work[
        "close"
    ]

    work[
        "ema20"
    ] = calculate_ema(
        close,
        20,
    )

    work[
        "ema50"
    ] = calculate_ema(
        close,
        50,
    )

    work[
        "rsi"
    ] = calculate_rsi(
        close,
        14,
    )

    (
        macd,
        macd_signal,
        macd_histogram,
    ) = calculate_macd(
        close
    )

    work[
        "macd"
    ] = macd

    work[
        "macd_signal"
    ] = macd_signal

    work[
        "macd_histogram"
    ] = macd_histogram

    work[
        "atr"
    ] = calculate_atr(
        work,
        14,
    )

    latest = work.iloc[
        -1
    ]

    previous = work.iloc[
        -2
    ]

    price = _safe_float(
        latest[
            "close"
        ]
    )

    ema20 = _safe_float(
        latest[
            "ema20"
        ]
    )

    ema50 = _safe_float(
        latest[
            "ema50"
        ]
    )

    rsi = _safe_float(
        latest[
            "rsi"
        ],
        50.0,
    )

    macd_value = _safe_float(
        latest[
            "macd"
        ]
    )

    macd_signal_value = _safe_float(
        latest[
            "macd_signal"
        ]
    )

    macd_hist = _safe_float(
        latest[
            "macd_histogram"
        ]
    )

    previous_hist = _safe_float(
        previous[
            "macd_histogram"
        ]
    )

    atr = _safe_float(
        latest[
            "atr"
        ]
    )

    atr_pct = 0.0

    if price > 0:

        atr_pct = (
            atr
            / price
            * 100
        )

    momentum_pct = (
        calculate_momentum_pct(
            close,
            10,
        )
    )

    score = 0
    reasons = []

    # --------------------------------------------------------
    # TREND
    # --------------------------------------------------------

    if (
        price > ema20
        and ema20 > ema50
    ):

        score += 2

        reasons.append(
            "Bullish EMA trend"
        )

    elif (
        price < ema20
        and ema20 < ema50
    ):

        score -= 2

        reasons.append(
            "Bearish EMA trend"
        )

    else:

        reasons.append(
            "Mixed EMA trend"
        )

    # --------------------------------------------------------
    # MACD
    # --------------------------------------------------------

    if (
        macd_value
        > macd_signal_value
        and macd_hist > 0
    ):

        score += 2

        reasons.append(
            "MACD bullish"
        )

        if (
            macd_hist
            > previous_hist
        ):

            score += 1

            reasons.append(
                "MACD momentum rising"
            )

    elif (
        macd_value
        < macd_signal_value
        and macd_hist < 0
    ):

        score -= 2

        reasons.append(
            "MACD bearish"
        )

        if (
            macd_hist
            < previous_hist
        ):

            score -= 1

            reasons.append(
                "MACD downside strengthening"
            )

    # --------------------------------------------------------
    # RSI
    # --------------------------------------------------------

    if 52 <= rsi <= 68:

        score += 1

        reasons.append(
            "RSI bullish zone"
        )

    elif 32 <= rsi <= 48:

        score -= 1

        reasons.append(
            "RSI bearish zone"
        )

    elif rsi < RSI_OVERSOLD:

        reasons.append(
            "RSI oversold"
        )

    elif rsi > RSI_OVERBOUGHT:

        reasons.append(
            "RSI overbought"
        )

    # --------------------------------------------------------
    # MOMENTUM
    # --------------------------------------------------------

    if momentum_pct > 0.15:

        score += 1

        reasons.append(
            "Positive momentum"
        )

    elif momentum_pct < -0.15:

        score -= 1

        reasons.append(
            "Negative momentum"
        )

    # --------------------------------------------------------
    # DIRECTION
    # --------------------------------------------------------

    if score >= 3:

        direction = "BULLISH"

    elif score <= -3:

        direction = "BEARISH"

    else:

        direction = "NEUTRAL"

    confidence = min(
        100.0,
        abs(
            score
        )
        / 6
        * 100,
    )

    return {
        "timeframe":
            timeframe,

        "valid":
            True,

        "direction":
            direction,

        "score":
            int(
                score
            ),

        "confidence":
            round(
                confidence,
                2,
            ),

        "close":
            round(
                price,
                6,
            ),

        "ema20":
            round(
                ema20,
                6,
            ),

        "ema50":
            round(
                ema50,
                6,
            ),

        "rsi":
            round(
                rsi,
                2,
            ),

        "macd":
            round(
                macd_value,
                6,
            ),

        "macd_signal":
            round(
                macd_signal_value,
                6,
            ),

        "macd_histogram":
            round(
                macd_hist,
                6,
            ),

        "atr":
            round(
                atr,
                6,
            ),

        "atr_pct":
            round(
                atr_pct,
                3,
            ),

        "momentum_pct":
            round(
                momentum_pct,
                3,
            ),

        "reason":
            ", ".join(
                reasons
            ),
    }


# ============================================================
# MTF WEIGHTING
# ============================================================

TIMEFRAME_WEIGHT = {
    "15m": 1.0,
    "1h": 1.5,
    "4h": 2.0,
}


def calculate_weighted_score(
    analyses: Dict[str, Dict],
) -> float:

    total = 0.0

    for timeframe, analysis in (
        analyses.items()
    ):

        if not analysis.get(
            "valid",
            False,
        ):
            continue

        weight = TIMEFRAME_WEIGHT.get(
            timeframe,
            1.0,
        )

        total += (
            _safe_float(
                analysis.get(
                    "score"
                )
            )
            * weight
        )

    return round(
        total,
        2,
    )


# ============================================================
# MTF CONFIDENCE
# ============================================================

def calculate_mtf_confidence(
    analyses: Dict[str, Dict],
    direction: str,
) -> float:

    valid = [
        analysis
        for analysis in analyses.values()
        if analysis.get(
            "valid",
            False,
        )
    ]

    if not valid:

        return 0.0

    if direction == "BUY":

        aligned = sum(
            1
            for analysis in valid
            if analysis.get(
                "direction"
            ) == "BULLISH"
        )

    elif direction == "SELL":

        aligned = sum(
            1
            for analysis in valid
            if analysis.get(
                "direction"
            ) == "BEARISH"
        )

    else:

        return 0.0

    return round(
        aligned
        / len(
            valid
        )
        * 100,
        2,
    )


# ============================================================
# ATR TP / SL
# ============================================================

def calculate_metals_targets(
    symbol: str,
    signal: str,
    entry_price: float,
    atr: float,
) -> Dict:

    symbol = (
        str(symbol)
        .upper()
        .strip()
    )

    signal = (
        str(signal)
        .upper()
        .strip()
    )

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

        return {
            "valid": False,
            "take_profit": None,
            "stop_loss": None,
            "risk_reward": 0.0,
        }

    sl_multiplier = (
        ATR_SL_MULTIPLIER.get(
            symbol,
            1.5,
        )
    )

    tp_multiplier = (
        ATR_TP_MULTIPLIER.get(
            symbol,
            2.4,
        )
    )

    sl_distance = (
        atr
        * sl_multiplier
    )

    tp_distance = (
        atr
        * tp_multiplier
    )

    if signal == "BUY":

        take_profit = (
            entry_price
            + tp_distance
        )

        stop_loss = (
            entry_price
            - sl_distance
        )

    elif signal == "SELL":

        take_profit = (
            entry_price
            - tp_distance
        )

        stop_loss = (
            entry_price
            + sl_distance
        )

    else:

        return {
            "valid": False,
            "take_profit": None,
            "stop_loss": None,
            "risk_reward": 0.0,
        }

    risk_reward = 0.0

    if sl_distance > 0:

        risk_reward = (
            tp_distance
            / sl_distance
        )

    return {
        "valid":
            True,

        "take_profit":
            round(
                take_profit,
                6,
            ),

        "stop_loss":
            round(
                stop_loss,
                6,
            ),

        "tp_distance":
            round(
                tp_distance,
                6,
            ),

        "sl_distance":
            round(
                sl_distance,
                6,
            ),

        "risk_reward":
            round(
                risk_reward,
                2,
            ),

        "atr":
            round(
                atr,
                6,
            ),

        "atr_sl_multiplier":
            sl_multiplier,

        "atr_tp_multiplier":
            tp_multiplier,
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
# SCAN ONE METAL
# ============================================================

def scan_metal(
    symbol: str,
) -> Dict:

    symbol = (
        str(symbol)
        .upper()
        .strip()
    )

    # --------------------------------------------------------
    # SAFETY GATE 1:
    # DIRECT PROVIDER QUOTE
    # --------------------------------------------------------

    quote = (
        get_metal_quote(
            symbol
        )
    )

    if quote is None:

        return _no_trade_result(
            symbol,
            "Live metals quote unavailable",
        )

    if not _quote_is_safe(
        quote
    ):

        return _no_trade_result(
            symbol,
            (
                "Metal quote is stale or "
                "not safe for trading"
            ),
            quote=quote,
        )

    # --------------------------------------------------------
    # BUILD MARKET SNAPSHOT
    # --------------------------------------------------------

    market_snapshot = (
        build_metal_snapshot(
            symbol
        )
    )

    if market_snapshot.get(
        "status"
    ) != "LIVE":

        return _no_trade_result(
            symbol,
            "Live metals market snapshot unavailable",
            market_snapshot=market_snapshot,
            quote=quote,
        )

    # --------------------------------------------------------
    # SPREAD / MARKET QUALITY
    # --------------------------------------------------------

    if not market_snapshot.get(
        "spread_ok",
        True,
    ):

        return _no_trade_result(
            symbol,
            "Metal spread too wide",
            market_snapshot=market_snapshot,
            quote=quote,
        )

    # --------------------------------------------------------
    # LOAD MTF CANDLES
    # --------------------------------------------------------

    mtf_data = (
        get_metals_mtf_candles(
            symbol
        )
    )

    analyses = {}

    for timeframe in TIMEFRAMES:

        dataframe = (
            mtf_data.get(
                timeframe
            )
        )

        analyses[
            timeframe
        ] = analyse_timeframe(
            dataframe,
            timeframe,
        )

    # --------------------------------------------------------
    # SAFETY GATE 2:
    # EVERY TIMEFRAME MUST BE VALID
    # --------------------------------------------------------

    all_timeframes_valid = all(
        analyses.get(
            timeframe,
            {}
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
                {}
            ).get(
                "valid",
                False,
            )
        ]

        return _no_trade_result(
            symbol,
            (
                "Invalid metals timeframe data: "
                + ", ".join(
                    invalid
                )
            ),
            market_snapshot=market_snapshot,
            quote=quote,
            timeframes=analyses,
        )

    # --------------------------------------------------------
    # SAFETY GATE 3:
    # CANDLES MUST BE FRESH
    # --------------------------------------------------------

    candle_quality = (
        _check_candle_freshness(
            symbol
        )
    )

    candles_fresh = bool(
        candle_quality.get(
            "all_fresh",
            False,
        )
    )

    if not candles_fresh:

        stale_frames = [
            timeframe
            for timeframe, info
            in candle_quality.get(
                "timeframes",
                {}
            ).items()
            if not info.get(
                "fresh",
                False,
            )
        ]

        result = _no_trade_result(
            symbol,
            (
                "Metals candle data stale/unavailable: "
                + ", ".join(
                    stale_frames
                )
            ),
            market_snapshot=market_snapshot,
            quote=quote,
            timeframes=analyses,
        )

        result[
            "candle_quality"
        ] = candle_quality

        return result

    # --------------------------------------------------------
    # WEIGHTED SCORE
    # --------------------------------------------------------

    weighted_score = (
        calculate_weighted_score(
            analyses
        )
    )

    # --------------------------------------------------------
    # DIRECTION
    # --------------------------------------------------------

    if weighted_score >= MIN_ENTRY_SCORE:

        signal = "BUY"

    elif weighted_score <= -MIN_ENTRY_SCORE:

        signal = "SELL"

    else:

        signal = "NO TRADE"

    mtf_confidence = (
        calculate_mtf_confidence(
            analyses,
            signal,
        )
        if signal != "NO TRADE"
        else 0.0
    )

    # --------------------------------------------------------
    # HIGHER TIMEFRAME CONFIRMATION
    # --------------------------------------------------------

    one_hour = analyses.get(
        "1h",
        {}
    )

    four_hour = analyses.get(
        "4h",
        {}
    )

    higher_tf_confirmed = False

    if signal == "BUY":

        higher_tf_confirmed = (
            one_hour.get(
                "direction"
            ) == "BULLISH"
            and
            four_hour.get(
                "direction"
            ) == "BULLISH"
        )

    elif signal == "SELL":

        higher_tf_confirmed = (
            one_hour.get(
                "direction"
            ) == "BEARISH"
            and
            four_hour.get(
                "direction"
            ) == "BEARISH"
        )

    # --------------------------------------------------------
    # FINAL SAFETY APPROVAL
    # --------------------------------------------------------

    approved = (
        signal
        in (
            "BUY",
            "SELL",
        )
        and mtf_confidence
        >= MIN_MTF_CONFIDENCE
        and higher_tf_confirmed
        and all_timeframes_valid
        and candles_fresh
        and _quote_is_safe(
            quote
        )
    )

    entry_price = _safe_float(
        quote.get(
            "last"
        )
    )

    fifteen_minute = analyses.get(
        "15m",
        {}
    )

    atr = _safe_float(
        fifteen_minute.get(
            "atr"
        )
    )

    targets = {}

    if approved:

        targets = (
            calculate_metals_targets(
                symbol=symbol,
                signal=signal,
                entry_price=entry_price,
                atr=atr,
            )
        )

        if not targets.get(
            "valid",
            False,
        ):

            approved = False

    # --------------------------------------------------------
    # REASON
    # --------------------------------------------------------

    reasons = []

    reasons.append(
        f"Weighted score "
        f"{weighted_score:+.2f}"
    )

    if signal != "NO TRADE":

        reasons.append(
            f"MTF confidence "
            f"{mtf_confidence:.1f}%"
        )

    if higher_tf_confirmed:

        reasons.append(
            "1H + 4H confirmed"
        )

    elif signal != "NO TRADE":

        reasons.append(
            "Higher timeframe not aligned"
        )

    quality = market_snapshot.get(
        "market_quality"
    )

    if quality:

        reasons.append(
            f"Market quality {quality}"
        )

    if candles_fresh:

        reasons.append(
            "Candles fresh"
        )

    if _quote_is_safe(
        quote
    ):

        reasons.append(
            "Quote fresh"
        )

    if signal == "NO TRADE":

        reasons.append(
            "Entry threshold not reached"
        )

    return {
        "symbol":
            symbol,

        "asset_class":
            "METAL",

        "signal":
            signal,

        "score":
            weighted_score,

        "mtf_confidence":
            mtf_confidence,

        "higher_tf_confirmed":
            higher_tf_confirmed,

        "approved":
            approved,

        "entry_price":
            entry_price,

        "targets":
            targets,

        "risk_pct":
            DEFAULT_METALS_RISK_PCT,

        "timeframes":
            analyses,

        "market_snapshot":
            market_snapshot,

        "quote":
            quote,

        "quote_fresh":
            True,

        "candles_fresh":
            candles_fresh,

        "all_timeframes_valid":
            all_timeframes_valid,

        "candle_quality":
            candle_quality,

        "safety_gate":
            (
                candles_fresh
                and all_timeframes_valid
                and _quote_is_safe(
                    quote
                )
            ),

        "reason":
            ", ".join(
                reasons
            ),
    }


# ============================================================
# SCAN GOLD + SILVER
# ============================================================

def scan_metals() -> List[Dict]:

    results = []

    for symbol in METAL_MARKETS:

        try:

            result = scan_metal(
                symbol
            )

        except Exception as error:

            result = _no_trade_result(
                symbol,
                f"Scanner error: {error}",
            )

        results.append(
            result
        )

    return results


# ============================================================
# BEST METALS SETUP
# ============================================================

def get_best_metals_setup(
    results: Optional[List[Dict]] = None,
) -> Optional[Dict]:

    if results is None:

        results = scan_metals()

    approved = [
        item
        for item in results
        if (
            item.get(
                "approved",
                False,
            )
            and
            item.get(
                "safety_gate",
                False,
            )
        )
    ]

    if not approved:

        return None

    approved.sort(
        key=lambda item: (
            item.get(
                "mtf_confidence",
                0.0,
            ),
            abs(
                item.get(
                    "score",
                    0.0,
                )
            ),
        ),
        reverse=True,
    )

    return approved[
        0
    ]


# ============================================================
# SCANNER SUMMARY
# ============================================================

def metals_scanner_summary(
    results: Optional[List[Dict]] = None,
) -> Dict:

    if results is None:

        results = scan_metals()

    best = get_best_metals_setup(
        results
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

    return {
        "markets":
            results,

        "gold":
            gold,

        "silver":
            silver,

        "best_setup":
            best,

        "approved_count":
            sum(
                1
                for item in results
                if (
                    item.get(
                        "approved",
                        False,
                    )
                    and
                    item.get(
                        "safety_gate",
                        False,
                    )
                )
            ),

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
# HEALTH CHECK
# ============================================================

def metals_scanner_health() -> Dict:

    try:

        results = scan_metals()

        valid_markets = sum(
            1
            for item in results
            if not str(
                item.get(
                    "reason",
                    ""
                )
            ).startswith(
                "Scanner error"
            )
        )

        safe_markets = sum(
            1
            for item in results
            if item.get(
                "safety_gate",
                False,
            )
        )

        return {
            "ok":
                valid_markets > 0,

            "engine":
                "V3.7 Metals Safety Scanner",

            "markets":
                len(
                    results
                ),

            "valid_markets":
                valid_markets,

            "safe_markets":
                safe_markets,

            "paper_execution":
                False,

            "real_execution":
                False,
        }

    except Exception as error:

        return {
            "ok":
                False,

            "engine":
                "V3.7 Metals Safety Scanner",

            "reason":
                str(
                    error
                ),
        }

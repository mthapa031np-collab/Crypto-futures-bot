"""
strategy_engine.py

PRO AI QUANT TERMINAL V5
CRYPTO INTRADAY CONFLUENCE STRATEGY ENGINE

Primary objective
-----------------
High-quality PAPER crypto setups designed for approximately
1-3 hour trade lifecycles.

Architecture
------------
Scanner
    ↓
V5 Strategy Engine
    ↓
15m Entry Intelligence
1h Regime Confirmation
4h Macro Context
    ↓
Cost / Volatility / Structure Filters
    ↓
Portfolio Risk Governor
    ↓
Paper Execution
    ↓
Trade Lifecycle Engine

Core intelligence
-----------------
- Closed-candle analysis
- Multi-timeframe regime fusion
- EMA trend structure
- VWAP positioning
- RSI momentum quality
- MACD momentum
- ATR volatility regime
- ADX trend-strength estimation
- Volume confirmation
- Market structure
- Fibonacci retracement confluence
- Legacy signal_engine confirmation
- Execution-cost hurdle
- Strong-opposition veto
- Adaptive confidence score
- Suggested ATR risk plan
- 3-hour intended lifecycle
- PAPER ONLY
- NO REAL EXECUTION

Important
---------
No strategy can guarantee 100% accuracy.

The objective is positive expectancy, controlled losses,
quality filtering and repeatable out-of-sample performance.
"""

from __future__ import annotations

import math
import os
from typing import Dict, Optional, Tuple

import numpy as np
import pandas as pd

from market_data import get_candles
from signal_engine import generate_signal


# ============================================================
# VERSION
# ============================================================

STRATEGY_VERSION = "V5_CRYPTO_INTRADAY_CONFLUENCE"


# ============================================================
# HARD SAFETY
# ============================================================

PAPER_ONLY = True
REAL_EXECUTION_ENABLED = False


# ============================================================
# TIMEFRAMES
# ============================================================

TIMEFRAMES = {
    "15m": 15,
    "1h": 60,
    "4h": 240,
}


# ============================================================
# ENV HELPERS
# ============================================================

def _env_float(
    name: str,
    default: float,
    minimum: Optional[float] = None,
    maximum: Optional[float] = None,
) -> float:

    try:

        value = float(
            os.environ.get(
                name,
                str(default),
            )
        )

    except (
        TypeError,
        ValueError,
    ):

        value = float(
            default
        )

    if not math.isfinite(
        value
    ):

        value = float(
            default
        )

    if minimum is not None:

        value = max(
            minimum,
            value,
        )

    if maximum is not None:

        value = min(
            maximum,
            value,
        )

    return value


def _env_int(
    name: str,
    default: int,
    minimum: Optional[int] = None,
    maximum: Optional[int] = None,
) -> int:

    try:

        value = int(
            os.environ.get(
                name,
                str(default),
            )
        )

    except (
        TypeError,
        ValueError,
    ):

        value = int(
            default
        )

    if minimum is not None:

        value = max(
            minimum,
            value,
        )

    if maximum is not None:

        value = min(
            maximum,
            value,
        )

    return value


# ============================================================
# STRATEGY CONFIG
# ============================================================

MIN_CANDLES = _env_int(
    "CRYPTO_STRATEGY_MIN_CANDLES",
    80,
    minimum=60,
    maximum=300,
)

CANDLE_LIMIT = _env_int(
    "CRYPTO_STRATEGY_CANDLE_LIMIT",
    180,
    minimum=100,
    maximum=500,
)

MIN_APPROVAL_CONFIDENCE = _env_float(
    "CRYPTO_MIN_APPROVAL_CONFIDENCE",
    68.0,
    minimum=50.0,
    maximum=95.0,
)

STRONG_APPROVAL_CONFIDENCE = _env_float(
    "CRYPTO_STRONG_APPROVAL_CONFIDENCE",
    78.0,
    minimum=60.0,
    maximum=98.0,
)

# Approximate PAPER execution-cost hurdle.
# Override in Render environment if desired.
ESTIMATED_ROUND_TRIP_COST_BPS = _env_float(
    "CRYPTO_ESTIMATED_ROUND_TRIP_COST_BPS",
    20.0,
    minimum=0.0,
    maximum=200.0,
)

COST_SAFETY_MULTIPLIER = _env_float(
    "CRYPTO_COST_SAFETY_MULTIPLIER",
    2.5,
    minimum=1.0,
    maximum=10.0,
)

MIN_ATR_PCT = _env_float(
    "CRYPTO_MIN_ATR_PCT",
    0.18,
    minimum=0.03,
    maximum=5.0,
)

MAX_ATR_PCT = _env_float(
    "CRYPTO_MAX_ATR_PCT",
    4.0,
    minimum=0.5,
    maximum=20.0,
)

MIN_ADX = _env_float(
    "CRYPTO_MIN_ADX",
    16.0,
    minimum=5.0,
    maximum=50.0,
)

STRONG_ADX = _env_float(
    "CRYPTO_STRONG_ADX",
    24.0,
    minimum=10.0,
    maximum=70.0,
)

FIB_LOOKBACK = _env_int(
    "CRYPTO_FIB_LOOKBACK",
    48,
    minimum=20,
    maximum=150,
)

STRUCTURE_LOOKBACK = _env_int(
    "CRYPTO_STRUCTURE_LOOKBACK",
    20,
    minimum=10,
    maximum=100,
)

TARGET_HOLD_HOURS = _env_float(
    "CRYPTO_TARGET_HOLD_HOURS",
    3.0,
    minimum=1.0,
    maximum=12.0,
)

STOP_ATR_MULTIPLIER = _env_float(
    "CRYPTO_STOP_ATR_MULTIPLIER",
    1.25,
    minimum=0.5,
    maximum=4.0,
)

TARGET_ATR_MULTIPLIER = _env_float(
    "CRYPTO_TARGET_ATR_MULTIPLIER",
    1.80,
    minimum=0.8,
    maximum=6.0,
)


# ============================================================
# SAFE HELPERS
# ============================================================

def _safe_float(
    value,
    default=0.0,
) -> float:

    try:

        if value is None:

            return default

        number = float(
            value
        )

        if not math.isfinite(
            number
        ):

            return default

        return number

    except (
        TypeError,
        ValueError,
        OverflowError,
    ):

        return default


def _clean_signal(
    value,
) -> str:

    signal = str(
        value
        or "NO TRADE"
    ).upper().strip()

    aliases = {
        "LONG":
            "BUY",

        "SHORT":
            "SELL",
    }

    signal = aliases.get(
        signal,
        signal,
    )

    if signal not in (
        "BUY",
        "SELL",
        "NO TRADE",
    ):

        return "NO TRADE"

    return signal


def _clamp(
    value: float,
    minimum: float,
    maximum: float,
) -> float:

    return max(
        minimum,
        min(
            value,
            maximum,
        ),
    )


# ============================================================
# CANDLE NORMALIZATION
# ============================================================

def _prepare_candles(
    candles,
) -> Optional[
    pd.DataFrame
]:

    if candles is None:

        return None

    try:

        df = pd.DataFrame(
            candles
        ).copy()

    except Exception:

        return None

    required = {
        "open",
        "high",
        "low",
        "close",
    }

    if not required.issubset(
        df.columns
    ):

        return None

    for column in (
        "open",
        "high",
        "low",
        "close",
        "volume",
    ):

        if column in df.columns:

            df[
                column
            ] = pd.to_numeric(
                df[
                    column
                ],
                errors="coerce",
            )

    df = df.dropna(
        subset=[
            "open",
            "high",
            "low",
            "close",
        ]
    )

    df = df[
        (
            df["open"] > 0
        )
        &
        (
            df["high"] > 0
        )
        &
        (
            df["low"] > 0
        )
        &
        (
            df["close"] > 0
        )
    ]

    # ---------------------------------------------
    # CLOSED-CANDLE SAFETY
    #
    # Public APIs often include the currently
    # forming candle as the final row.
    #
    # We deliberately remove the final row to
    # avoid intrabar signal instability.
    # ---------------------------------------------

    if len(
        df
    ) > MIN_CANDLES:

        df = df.iloc[
            :-1
        ].copy()

    if len(
        df
    ) < MIN_CANDLES:

        return None

    return df.reset_index(
        drop=True
    )


# ============================================================
# INDICATORS
# ============================================================

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
    ).mean()

    avg_loss = loss.ewm(
        alpha=1 / period,
        adjust=False,
    ).mean()

    rs = (
        avg_gain
        / avg_loss.replace(
            0,
            np.nan,
        )
    )

    result = (
        100
        - (
            100
            / (
                1
                + rs
            )
        )
    )

    return result.fillna(
        50.0
    )


def _true_range(
    df: pd.DataFrame,
) -> pd.Series:

    previous_close = (
        df["close"]
        .shift(
            1
        )
    )

    part1 = (
        df["high"]
        - df["low"]
    )

    part2 = (
        df["high"]
        - previous_close
    ).abs()

    part3 = (
        df["low"]
        - previous_close
    ).abs()

    return pd.concat(
        [
            part1,
            part2,
            part3,
        ],
        axis=1,
    ).max(
        axis=1
    )


def _atr(
    df: pd.DataFrame,
    period: int = 14,
) -> pd.Series:

    tr = _true_range(
        df
    )

    return tr.ewm(
        alpha=1 / period,
        adjust=False,
    ).mean()


def _macd(
    close: pd.Series,
) -> Tuple[
    pd.Series,
    pd.Series,
    pd.Series,
]:

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

    return (
        line,
        signal,
        histogram,
    )


def _adx(
    df: pd.DataFrame,
    period: int = 14,
) -> Tuple[
    pd.Series,
    pd.Series,
    pd.Series,
]:

    high = df[
        "high"
    ]

    low = df[
        "low"
    ]

    up_move = high.diff()

    down_move = (
        -low.diff()
    )

    plus_dm = pd.Series(
        np.where(
            (
                up_move
                > down_move
            )
            &
            (
                up_move
                > 0
            ),
            up_move,
            0.0,
        ),
        index=df.index,
    )

    minus_dm = pd.Series(
        np.where(
            (
                down_move
                > up_move
            )
            &
            (
                down_move
                > 0
            ),
            down_move,
            0.0,
        ),
        index=df.index,
    )

    atr = _atr(
        df,
        period,
    ).replace(
        0,
        np.nan,
    )

    plus_di = (
        100
        * plus_dm.ewm(
            alpha=1 / period,
            adjust=False,
        ).mean()
        / atr
    )

    minus_di = (
        100
        * minus_dm.ewm(
            alpha=1 / period,
            adjust=False,
        ).mean()
        / atr
    )

    denominator = (
        plus_di
        + minus_di
    ).replace(
        0,
        np.nan,
    )

    dx = (
        100
        * (
            plus_di
            - minus_di
        ).abs()
        / denominator
    )

    adx = dx.ewm(
        alpha=1 / period,
        adjust=False,
    ).mean()

    return (
        adx.fillna(
            0
        ),
        plus_di.fillna(
            0
        ),
        minus_di.fillna(
            0
        ),
    )


def _session_vwap(
    df: pd.DataFrame,
) -> pd.Series:

    typical = (
        df[
            "high"
        ]
        + df[
            "low"
        ]
        + df[
            "close"
        ]
    ) / 3.0

    if (
        "volume"
        not in df.columns
    ):

        return typical.expanding().mean()

    volume = (
        df[
            "volume"
        ]
        .fillna(
            0
        )
        .clip(
            lower=0
        )
    )

    cumulative_volume = (
        volume.cumsum()
    )

    if (
        cumulative_volume.iloc[
            -1
        ]
        <= 0
    ):

        return typical.expanding().mean()

    cumulative_pv = (
        typical
        * volume
    ).cumsum()

    return (
        cumulative_pv
        / cumulative_volume.replace(
            0,
            np.nan,
        )
    ).ffill()


# ============================================================
# VOLUME INTELLIGENCE
# ============================================================

def _volume_zscore(
    df: pd.DataFrame,
    window: int = 30,
) -> float:

    if (
        "volume"
        not in df.columns
    ):

        return 0.0

    volume = (
        df[
            "volume"
        ]
        .fillna(
            0
        )
    )

    if len(
        volume
    ) < window:

        return 0.0

    recent = volume.iloc[
        -window:
    ]

    mean = _safe_float(
        recent.mean()
    )

    std = _safe_float(
        recent.std()
    )

    if std <= 0:

        return 0.0

    return (
        _safe_float(
            volume.iloc[
                -1
            ]
        )
        - mean
    ) / std


# ============================================================
# MARKET STRUCTURE
# ============================================================

def _market_structure(
    df: pd.DataFrame,
) -> Dict:

    lookback = min(
        STRUCTURE_LOOKBACK,
        len(
            df
        )
        - 2,
    )

    if lookback < 5:

        return {
            "bullish":
                False,

            "bearish":
                False,

            "breakout_up":
                False,

            "breakout_down":
                False,
        }

    previous = df.iloc[
        -(lookback + 1):-1
    ]

    current = df.iloc[
        -1
    ]

    prior_high = _safe_float(
        previous[
            "high"
        ].max()
    )

    prior_low = _safe_float(
        previous[
            "low"
        ].min()
    )

    close = _safe_float(
        current[
            "close"
        ]
    )

    recent_highs = (
        df[
            "high"
        ]
        .iloc[
            -6:
        ]
    )

    recent_lows = (
        df[
            "low"
        ]
        .iloc[
            -6:
        ]
    )

    bullish_structure = bool(
        recent_highs.iloc[
            -1
        ]
        >= recent_highs.iloc[
            -4
        ]
        and
        recent_lows.iloc[
            -1
        ]
        >= recent_lows.iloc[
            -4
        ]
    )

    bearish_structure = bool(
        recent_highs.iloc[
            -1
        ]
        <= recent_highs.iloc[
            -4
        ]
        and
        recent_lows.iloc[
            -1
        ]
        <= recent_lows.iloc[
            -4
        ]
    )

    return {
        "bullish":
            bullish_structure,

        "bearish":
            bearish_structure,

        "breakout_up":
            close
            > prior_high,

        "breakout_down":
            close
            < prior_low,

        "prior_high":
            prior_high,

        "prior_low":
            prior_low,
    }


# ============================================================
# FIBONACCI CONFLUENCE
# ============================================================

def _fibonacci_context(
    df: pd.DataFrame,
    atr_value: float,
) -> Dict:

    lookback = min(
        FIB_LOOKBACK,
        len(
            df
        ),
    )

    recent = df.iloc[
        -lookback:
    ]

    swing_high = _safe_float(
        recent[
            "high"
        ].max()
    )

    swing_low = _safe_float(
        recent[
            "low"
        ].min()
    )

    current = _safe_float(
        df[
            "close"
        ].iloc[
            -1
        ]
    )

    span = (
        swing_high
        - swing_low
    )

    if (
        swing_high <= 0
        or swing_low <= 0
        or span <= 0
    ):

        return {
            "valid":
                False,

            "long_confluence":
                False,

            "short_confluence":
                False,
        }

    levels = {
        "236":
            swing_high
            - 0.236
            * span,

        "382":
            swing_high
            - 0.382
            * span,

        "500":
            swing_high
            - 0.500
            * span,

        "618":
            swing_high
            - 0.618
            * span,

        "786":
            swing_high
            - 0.786
            * span,
    }

    tolerance = max(
        atr_value
        * 0.40,
        current
        * 0.001,
    )

    nearest_name = None
    nearest_distance = float(
        "inf"
    )

    nearest_price = None

    for (
        name,
        level,
    ) in levels.items():

        distance = abs(
            current
            - level
        )

        if (
            distance
            < nearest_distance
        ):

            nearest_distance = (
                distance
            )

            nearest_name = name

            nearest_price = level

    near_fib = (
        nearest_distance
        <= tolerance
    )

    # Long pullback zone:
    # current around 38.2-61.8% retracement.
    long_zone_low = levels[
        "618"
    ]

    long_zone_high = levels[
        "382"
    ]

    long_confluence = (
        current
        >= (
            long_zone_low
            - tolerance
        )
        and
        current
        <= (
            long_zone_high
            + tolerance
        )
    )

    # For shorts we use the inverse interpretation:
    # price residing in the upper half of the swing range.
    inverse_382 = (
        swing_low
        + 0.382
        * span
    )

    inverse_618 = (
        swing_low
        + 0.618
        * span
    )

    short_confluence = (
        current
        >= (
            inverse_382
            - tolerance
        )
        and
        current
        <= (
            inverse_618
            + tolerance
        )
    )

    return {
        "valid":
            True,

        "swing_high":
            swing_high,

        "swing_low":
            swing_low,

        "nearest_level":
            nearest_name,

        "nearest_price":
            nearest_price,

        "near_fib":
            near_fib,

        "long_confluence":
            long_confluence,

        "short_confluence":
            short_confluence,

        "levels":
            levels,
    }


# ============================================================
# ONE TIMEFRAME INTELLIGENCE
# ============================================================

def analyse_timeframe(
    symbol: str,
    timeframe_minutes: int,
    limit: int = CANDLE_LIMIT,
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

        df = _prepare_candles(
            candles
        )

        if df is None:

            return None

        close = df[
            "close"
        ]

        price = _safe_float(
            close.iloc[
                -1
            ]
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

        (
            macd_line,
            macd_signal,
            macd_hist,
        ) = _macd(
            close
        )

        atr_series = _atr(
            df,
            14,
        )

        (
            adx_series,
            plus_di,
            minus_di,
        ) = _adx(
            df,
            14,
        )

        vwap_series = (
            _session_vwap(
                df
            )
        )

        atr_value = _safe_float(
            atr_series.iloc[
                -1
            ]
        )

        atr_pct = (
            (
                atr_value
                / price
            )
            * 100
            if price > 0
            else 0.0
        )

        ema20_value = _safe_float(
            ema20.iloc[
                -1
            ]
        )

        ema50_value = _safe_float(
            ema50.iloc[
                -1
            ]
        )

        rsi_value = _safe_float(
            rsi_series.iloc[
                -1
            ],
            50.0,
        )

        macd_hist_value = _safe_float(
            macd_hist.iloc[
                -1
            ]
        )

        adx_value = _safe_float(
            adx_series.iloc[
                -1
            ]
        )

        plus_di_value = _safe_float(
            plus_di.iloc[
                -1
            ]
        )

        minus_di_value = _safe_float(
            minus_di.iloc[
                -1
            ]
        )

        vwap_value = _safe_float(
            vwap_series.iloc[
                -1
            ]
        )

        volume_z = _volume_zscore(
            df
        )

        structure = (
            _market_structure(
                df
            )
        )

        fib = _fibonacci_context(
            df,
            atr_value,
        )

        # ---------------------------------------------
        # Legacy engine remains one independent vote.
        # It is NOT the master decision anymore.
        # ---------------------------------------------

        try:

            legacy = generate_signal(
                df
            )

        except Exception:

            legacy = {}

        legacy_signal = _clean_signal(
            legacy.get(
                "signal",
                "NO TRADE",
            )
        )

        legacy_score = _safe_float(
            legacy.get(
                "score",
                0,
            )
        )

        # ====================================================
        # GROUPED FEATURE SCORES
        #
        # Scores are intentionally grouped so multiple similar
        # indicators do not create unlimited double counting.
        # ====================================================

        trend_score = 0.0

        if (
            price
            > ema20_value
            > ema50_value
        ):

            trend_score += 2.0

        elif (
            price
            < ema20_value
            < ema50_value
        ):

            trend_score -= 2.0

        elif (
            ema20_value
            > ema50_value
        ):

            trend_score += 1.0

        elif (
            ema20_value
            < ema50_value
        ):

            trend_score -= 1.0

        # ---------------------------------------------
        # VWAP
        # ---------------------------------------------

        vwap_score = 0.0

        if (
            vwap_value > 0
            and price > vwap_value
        ):

            vwap_score = 1.0

        elif (
            vwap_value > 0
            and price < vwap_value
        ):

            vwap_score = -1.0

        # ---------------------------------------------
        # RSI QUALITY
        # Avoid blindly buying extreme overbought or
        # selling extreme oversold conditions.
        # ---------------------------------------------

        momentum_score = 0.0

        if (
            52
            <= rsi_value
            <= 68
        ):

            momentum_score += 1.0

        elif (
            32
            <= rsi_value
            <= 48
        ):

            momentum_score -= 1.0

        elif (
            rsi_value
            >= 78
        ):

            momentum_score -= 0.35

        elif (
            rsi_value
            <= 22
        ):

            momentum_score += 0.35

        if macd_hist_value > 0:

            momentum_score += 0.75

        elif macd_hist_value < 0:

            momentum_score -= 0.75

        momentum_score = _clamp(
            momentum_score,
            -1.75,
            1.75,
        )

        # ---------------------------------------------
        # ADX / DMI
        # ---------------------------------------------

        trend_strength_score = 0.0

        if (
            adx_value
            >= MIN_ADX
        ):

            if (
                plus_di_value
                > minus_di_value
            ):

                trend_strength_score += (
                    1.0
                )

            elif (
                minus_di_value
                > plus_di_value
            ):

                trend_strength_score -= (
                    1.0
                )

        if (
            adx_value
            >= STRONG_ADX
        ):

            trend_strength_score *= (
                1.25
            )

        # ---------------------------------------------
        # MARKET STRUCTURE
        # ---------------------------------------------

        structure_score = 0.0

        if structure.get(
            "bullish"
        ):

            structure_score += 0.75

        if structure.get(
            "bearish"
        ):

            structure_score -= 0.75

        if structure.get(
            "breakout_up"
        ):

            structure_score += 0.75

        if structure.get(
            "breakout_down"
        ):

            structure_score -= 0.75

        structure_score = _clamp(
            structure_score,
            -1.5,
            1.5,
        )

        # ---------------------------------------------
        # VOLUME
        # Volume only reinforces current direction.
        # ---------------------------------------------

        volume_strength = _clamp(
            volume_z,
            -2.0,
            3.0,
        )

        # ---------------------------------------------
        # LEGACY SIGNAL
        # Small independent contribution.
        # ---------------------------------------------

        legacy_vote = 0.0

        if legacy_signal == "BUY":

            legacy_vote = 0.75

        elif legacy_signal == "SELL":

            legacy_vote = -0.75

        legacy_vote += _clamp(
            legacy_score
            / 10.0,
            -0.50,
            0.50,
        )

        # ---------------------------------------------
        # TOTAL DIRECTIONAL SCORE
        # ---------------------------------------------

        score = (
            trend_score
            + vwap_score
            + momentum_score
            + trend_strength_score
            + structure_score
            + legacy_vote
        )

        # Volume may only modestly amplify.
        if (
            score > 0
            and volume_strength
            >= 0.5
        ):

            score += 0.50

        elif (
            score < 0
            and volume_strength
            >= 0.5
        ):

            score -= 0.50

        score = _clamp(
            score,
            -8.0,
            8.0,
        )

        if score >= 2.25:

            signal = "BUY"

        elif score <= -2.25:

            signal = "SELL"

        else:

            signal = "NO TRADE"

        return {
            "signal":
                signal,

            "score":
                round(
                    score,
                    3,
                ),

            "price":
                price,

            "ema20":
                ema20_value,

            "ema50":
                ema50_value,

            "vwap":
                vwap_value,

            "rsi":
                rsi_value,

            "macd":
                _safe_float(
                    macd_line.iloc[
                        -1
                    ]
                ),

            "macd_signal":
                _safe_float(
                    macd_signal.iloc[
                        -1
                    ]
                ),

            "macd_hist":
                macd_hist_value,

            "atr":
                atr_value,

            "atr_pct":
                atr_pct,

            "adx":
                adx_value,

            "plus_di":
                plus_di_value,

            "minus_di":
                minus_di_value,

            "volume_z":
                volume_z,

            "structure":
                structure,

            "fibonacci":
                fib,

            "legacy_signal":
                legacy_signal,

            "legacy_score":
                legacy_score,

            "feature_scores":
                {
                    "trend":
                        trend_score,

                    "vwap":
                        vwap_score,

                    "momentum":
                        momentum_score,

                    "trend_strength":
                        trend_strength_score,

                    "structure":
                        structure_score,

                    "legacy":
                        legacy_vote,
                },

            "reason":
                (
                    f"score={score:.2f}, "
                    f"RSI={rsi_value:.1f}, "
                    f"ADX={adx_value:.1f}, "
                    f"ATR={atr_pct:.2f}%, "
                    f"volumeZ={volume_z:.2f}"
                ),

            "closed_candle_only":
                True,
        }

    except Exception as error:

        print(
            "[V5 STRATEGY ERROR] "
            f"{symbol} "
            f"{timeframe_minutes}m: "
            f"{error}",
            flush=True,
        )

        return None


# ============================================================
# MULTI-TIMEFRAME FUSION
# ============================================================

def analyse_multi_timeframe(
    symbol: str,
) -> Dict:

    symbol = (
        str(
            symbol
        )
        .upper()
        .strip()
    )

    timeframe_data = {}

    for (
        label,
        minutes,
    ) in TIMEFRAMES.items():

        result = analyse_timeframe(
            symbol=symbol,
            timeframe_minutes=minutes,
        )

        if result is not None:

            timeframe_data[
                label
            ] = result

    tf15 = timeframe_data.get(
        "15m"
    )

    tf1h = timeframe_data.get(
        "1h"
    )

    tf4h = timeframe_data.get(
        "4h"
    )

    # Intraday engine requires 15m + 1h.
    # 4h is context rather than an absolute requirement.
    if (
        tf15 is None
        or tf1h is None
    ):

        return {
            "symbol":
                symbol,

            "valid":
                False,

            "signal":
                "NO TRADE",

            "confidence":
                0.0,

            "reason":
                (
                    "15m and 1h closed-candle "
                    "history are required."
                ),

            "timeframes":
                timeframe_data,

            "strategy_version":
                STRATEGY_VERSION,
        }

    score15 = _safe_float(
        tf15.get(
            "score"
        )
    )

    score1h = _safe_float(
        tf1h.get(
            "score"
        )
    )

    score4h = (
        _safe_float(
            tf4h.get(
                "score"
            )
        )
        if tf4h
        else 0.0
    )

    # ========================================================
    # PRIMARY DIRECTION
    # ========================================================

    long_candidate = (
        score15
        >= 2.25
        and
        score1h
        >= 1.75
    )

    short_candidate = (
        score15
        <= -2.25
        and
        score1h
        <= -1.75
    )

    candidate_signal = (
        "BUY"
        if long_candidate
        else
        (
            "SELL"
            if short_candidate
            else
            "NO TRADE"
        )
    )

    if (
        candidate_signal
        == "NO TRADE"
    ):

        return {
            "symbol":
                symbol,

            "valid":
                True,

            "signal":
                "NO TRADE",

            "confidence":
                0.0,

            "reason":
                (
                    "15m + 1h directional "
                    "threshold not satisfied."
                ),

            "timeframes":
                timeframe_data,

            "strategy_version":
                STRATEGY_VERSION,
        }

    # ========================================================
    # 4H STRONG OPPOSITION VETO
    # ========================================================

    strong_4h_opposition = False

    if tf4h is not None:

        if (
            candidate_signal
            == "BUY"
            and score4h
            <= -3.5
        ):

            strong_4h_opposition = True

        elif (
            candidate_signal
            == "SELL"
            and score4h
            >= 3.5
        ):

            strong_4h_opposition = True

    if strong_4h_opposition:

        return {
            "symbol":
                symbol,

            "valid":
                True,

            "signal":
                "NO TRADE",

            "confidence":
                0.0,

            "reason":
                (
                    "4h regime strongly opposes "
                    "intraday entry."
                ),

            "timeframes":
                timeframe_data,

            "strategy_version":
                STRATEGY_VERSION,
        }

    # ========================================================
    # VOLATILITY FILTER
    # ========================================================

    atr_pct = _safe_float(
        tf15.get(
            "atr_pct"
        )
    )

    if (
        atr_pct
        < MIN_ATR_PCT
    ):

        return {
            "symbol":
                symbol,

            "valid":
                True,

            "signal":
                "NO TRADE",

            "confidence":
                0.0,

            "reason":
                (
                    f"Volatility too low: "
                    f"ATR={atr_pct:.2f}%"
                ),

            "timeframes":
                timeframe_data,

            "strategy_version":
                STRATEGY_VERSION,
        }

    if (
        atr_pct
        > MAX_ATR_PCT
    ):

        return {
            "symbol":
                symbol,

            "valid":
                True,

            "signal":
                "NO TRADE",

            "confidence":
                0.0,

            "reason":
                (
                    f"Volatility too extreme: "
                    f"ATR={atr_pct:.2f}%"
                ),

            "timeframes":
                timeframe_data,

            "strategy_version":
                STRATEGY_VERSION,
        }

    # ========================================================
    # EXECUTION-COST HURDLE
    # ========================================================

    cost_pct = (
        ESTIMATED_ROUND_TRIP_COST_BPS
        / 100.0
    )

    expected_move_pct = (
        atr_pct
        * TARGET_ATR_MULTIPLIER
    )

    required_move_pct = (
        cost_pct
        * COST_SAFETY_MULTIPLIER
    )

    cost_filter_passed = (
        expected_move_pct
        >= required_move_pct
    )

    if not cost_filter_passed:

        return {
            "symbol":
                symbol,

            "valid":
                True,

            "signal":
                "NO TRADE",

            "confidence":
                0.0,

            "reason":
                (
                    "Expected move does not "
                    "clear execution-cost hurdle. "
                    f"expected={expected_move_pct:.2f}% "
                    f"required={required_move_pct:.2f}%"
                ),

            "timeframes":
                timeframe_data,

            "strategy_version":
                STRATEGY_VERSION,
        }

    # ========================================================
    # CONFIDENCE COMPONENTS
    # ========================================================

    entry_strength = _clamp(
        abs(
            score15
        )
        / 6.0,
        0.0,
        1.0,
    )

    regime_strength = _clamp(
        abs(
            score1h
        )
        / 6.0,
        0.0,
        1.0,
    )

    macro_alignment = 0.50

    if tf4h is not None:

        if (
            candidate_signal
            == "BUY"
            and score4h > 0
        ):

            macro_alignment = 1.0

        elif (
            candidate_signal
            == "SELL"
            and score4h < 0
        ):

            macro_alignment = 1.0

        elif abs(
            score4h
        ) < 1.5:

            macro_alignment = 0.65

        else:

            macro_alignment = 0.25

    adx15 = _safe_float(
        tf15.get(
            "adx"
        )
    )

    adx_strength = _clamp(
        (
            adx15
            - MIN_ADX
        )
        / max(
            1.0,
            (
                STRONG_ADX
                - MIN_ADX
            ),
        ),
        0.0,
        1.0,
    )

    fib = tf15.get(
        "fibonacci",
        {},
    )

    fib_confluence = False

    if candidate_signal == "BUY":

        fib_confluence = bool(
            fib.get(
                "long_confluence"
            )
        )

    elif candidate_signal == "SELL":

        fib_confluence = bool(
            fib.get(
                "short_confluence"
            )
        )

    volume_z = _safe_float(
        tf15.get(
            "volume_z"
        )
    )

    volume_strength = _clamp(
        (
            volume_z
            + 0.5
        )
        / 2.5,
        0.0,
        1.0,
    )

    confidence = (
        entry_strength
        * 30.0
        +
        regime_strength
        * 25.0
        +
        macro_alignment
        * 12.0
        +
        adx_strength
        * 10.0
        +
        volume_strength
        * 8.0
        +
        (
            8.0
            if fib_confluence
            else 0.0
        )
        +
        7.0
    )

    confidence = _clamp(
        confidence,
        0.0,
        100.0,
    )

    final_signal = (
        candidate_signal
        if confidence
        >= MIN_APPROVAL_CONFIDENCE
        else
        "NO TRADE"
    )

    # ========================================================
    # RISK / EXIT PLAN
    # ========================================================

    entry_price = _safe_float(
        tf15.get(
            "price"
        )
    )

    atr_value = _safe_float(
        tf15.get(
            "atr"
        )
    )

    stop_distance = (
        atr_value
        * STOP_ATR_MULTIPLIER
    )

    target_distance = (
        atr_value
        * TARGET_ATR_MULTIPLIER
    )

    if candidate_signal == "BUY":

        stop_loss = (
            entry_price
            - stop_distance
        )

        take_profit = (
            entry_price
            + target_distance
        )

    else:

        stop_loss = (
            entry_price
            + stop_distance
        )

        take_profit = (
            entry_price
            - target_distance
        )

    reward_risk = (
        target_distance
        / stop_distance
        if stop_distance > 0
        else 0.0
    )

    quality = (
        "A"
        if confidence
        >= STRONG_APPROVAL_CONFIDENCE
        else
        (
            "B"
            if confidence
            >= MIN_APPROVAL_CONFIDENCE
            else
            "REJECT"
        )
    )

    reason = (
        f"{candidate_signal} intraday confluence | "
        f"15m={score15:.2f} | "
        f"1h={score1h:.2f} | "
        f"4h={score4h:.2f} | "
        f"ADX={adx15:.1f} | "
        f"ATR={atr_pct:.2f}% | "
        f"Fib={'YES' if fib_confluence else 'NO'} | "
        f"CostFilter=PASS | "
        f"Confidence={confidence:.1f}% | "
        f"Quality={quality}"
    )

    return {
        "symbol":
            symbol,

        "valid":
            True,

        "signal":
            final_signal,

        "candidate_signal":
            candidate_signal,

        "confidence":
            round(
                confidence,
                2,
            ),

        "quality":
            quality,

        "reason":
            reason,

        "timeframes":
            timeframe_data,

        "entry_price":
            entry_price,

        "suggested_stop_loss":
            stop_loss,

        "suggested_take_profit":
            take_profit,

        "suggested_reward_risk":
            round(
                reward_risk,
                3,
            ),

        "target_hold_hours":
            TARGET_HOLD_HOURS,

        "expected_move_pct":
            expected_move_pct,

        "estimated_cost_pct":
            cost_pct,

        "cost_filter_passed":
            cost_filter_passed,

        "fib_confluence":
            fib_confluence,

        "strategy_version":
            STRATEGY_VERSION,

        "paper_only":
            True,

        "real_execution":
            False,
    }


# ============================================================
# CONFIRM SCANNER SETUP
# ============================================================

def confirm_scanner_setup(
    scanner_setup: Dict,
) -> Dict:

    if not scanner_setup:

        return {
            "approved":
                False,

            "reason":
                "No scanner setup",

            "strategy_version":
                STRATEGY_VERSION,
        }

    symbol = scanner_setup.get(
        "symbol"
    )

    scanner_signal = _clean_signal(
        scanner_setup.get(
            "signal",
            "NO TRADE",
        )
    )

    if not symbol:

        return {
            "approved":
                False,

            "reason":
                "Missing symbol",

            "strategy_version":
                STRATEGY_VERSION,
        }

    if scanner_signal not in (
        "BUY",
        "SELL",
    ):

        return {
            "approved":
                False,

            "symbol":
                symbol,

            "scanner_signal":
                scanner_signal,

            "reason":
                "Scanner has no directional setup.",

            "strategy_version":
                STRATEGY_VERSION,
        }

    strategy = (
        analyse_multi_timeframe(
            symbol
        )
    )

    strategy_signal = _clean_signal(
        strategy.get(
            "signal",
            "NO TRADE",
        )
    )

    confidence = _safe_float(
        strategy.get(
            "confidence",
            0,
        )
    )

    approved = (
        strategy.get(
            "valid",
            False,
        )
        and
        scanner_signal
        == strategy_signal
        and
        strategy_signal
        in (
            "BUY",
            "SELL",
        )
        and
        confidence
        >= MIN_APPROVAL_CONFIDENCE
        and
        strategy.get(
            "cost_filter_passed",
            False,
        )
    )

    return {
        "approved":
            approved,

        "symbol":
            symbol,

        "scanner_signal":
            scanner_signal,

        "strategy_signal":
            strategy_signal,

        "confidence":
            confidence,

        "quality":
            strategy.get(
                "quality",
                "REJECT",
            ),

        "reason":
            strategy.get(
                "reason",
                "",
            ),

        "entry_price":
            strategy.get(
                "entry_price"
            ),

        "suggested_stop_loss":
            strategy.get(
                "suggested_stop_loss"
            ),

        "suggested_take_profit":
            strategy.get(
                "suggested_take_profit"
            ),

        "suggested_reward_risk":
            strategy.get(
                "suggested_reward_risk"
            ),

        "target_hold_hours":
            strategy.get(
                "target_hold_hours",
                TARGET_HOLD_HOURS,
            ),

        "fib_confluence":
            strategy.get(
                "fib_confluence",
                False,
            ),

        "cost_filter_passed":
            strategy.get(
                "cost_filter_passed",
                False,
            ),

        "strategy_version":
            STRATEGY_VERSION,

        "strategy":
            strategy,

        "paper_only":
            True,

        "real_execution":
            False,
    }


# ============================================================
# HEALTH
# ============================================================

def strategy_engine_health() -> Dict:

    return {
        "ok":
            True,

        "engine":
            STRATEGY_VERSION,

        "paper_only":
            True,

        "real_execution_locked":
            True,

        "primary_entry_timeframe":
            "15m",

        "regime_timeframe":
            "1h",

        "macro_context":
            "4h",

        "closed_candle_only":
            True,

        "minimum_confidence":
            MIN_APPROVAL_CONFIDENCE,

        "strong_confidence":
            STRONG_APPROVAL_CONFIDENCE,

        "target_hold_hours":
            TARGET_HOLD_HOURS,

        "features":
            [
                "EMA20/50",
                "VWAP",
                "RSI",
                "MACD",
                "ATR",
                "ADX/DMI",
                "Volume",
                "Market Structure",
                "Fibonacci",
                "Legacy Signal Vote",
                "Execution Cost Filter",
                "MTF Regime Fusion",
            ],
    }

"""
analytics_engine.py

PRO AI QUANT TERMINAL V3

Institutional analytics layer.

Provides:
- Market regime
- Volatility
- Momentum
- Trend strength
- Correlation
- Breadth
- Scanner statistics
- Portfolio/trade analytics

Does NOT execute trades.
"""

from typing import Dict, List, Optional

import numpy as np
import pandas as pd


# ============================================================
# HELPERS
# ============================================================

def safe_float(value, default=0.0):

    try:
        if value is None:
            return default
        return float(value)

    except (TypeError, ValueError):
        return default


# ============================================================
# VOLATILITY
# ============================================================

def calculate_atr(
    candles: pd.DataFrame,
    period: int = 14,
) -> Optional[float]:

    if candles is None or len(candles) < period + 2:
        return None

    df = candles.copy()

    high = df["high"].astype(float)
    low = df["low"].astype(float)
    close = df["close"].astype(float)

    previous_close = close.shift(1)

    true_range = pd.concat(
        [
            high - low,
            (high - previous_close).abs(),
            (low - previous_close).abs(),
        ],
        axis=1,
    ).max(axis=1)

    atr = true_range.rolling(period).mean()

    value = atr.iloc[-1]

    if pd.isna(value):
        return None

    return float(value)


def calculate_atr_percent(
    candles: pd.DataFrame,
    period: int = 14,
) -> float:

    atr = calculate_atr(
        candles,
        period,
    )

    if atr is None:
        return 0.0

    price = safe_float(
        candles["close"].iloc[-1]
    )

    if price <= 0:
        return 0.0

    return (
        atr
        / price
        * 100
    )


# ============================================================
# TREND
# ============================================================

def calculate_trend_state(
    candles: pd.DataFrame,
) -> Dict:

    if candles is None or len(candles) < 55:

        return {
            "trend": "UNKNOWN",
            "strength": 0.0,
        }

    close = candles[
        "close"
    ].astype(float)

    ema20 = close.ewm(
        span=20,
        adjust=False,
    ).mean()

    ema50 = close.ewm(
        span=50,
        adjust=False,
    ).mean()

    e20 = float(
        ema20.iloc[-1]
    )

    e50 = float(
        ema50.iloc[-1]
    )

    price = float(
        close.iloc[-1]
    )

    if price <= 0:
        return {
            "trend": "UNKNOWN",
            "strength": 0.0,
        }

    distance_pct = abs(
        e20 - e50
    ) / price * 100

    strength = min(
        distance_pct * 20,
        100,
    )

    if e20 > e50:

        trend = "BULLISH"

    elif e20 < e50:

        trend = "BEARISH"

    else:

        trend = "NEUTRAL"

    return {
        "trend": trend,
        "strength": round(
            strength,
            2,
        ),
        "ema20": e20,
        "ema50": e50,
    }


# ============================================================
# MARKET REGIME
# ============================================================

def detect_market_regime(
    candles: pd.DataFrame,
) -> Dict:

    trend_data = (
        calculate_trend_state(
            candles
        )
    )

    atr_pct = (
        calculate_atr_percent(
            candles
        )
    )

    trend = trend_data[
        "trend"
    ]

    strength = trend_data[
        "strength"
    ]

    if atr_pct >= 3.0:

        volatility = "HIGH"

    elif atr_pct >= 1.2:

        volatility = "NORMAL"

    else:

        volatility = "LOW"

    if strength >= 20:

        if trend == "BULLISH":

            regime = (
                "BULL TREND"
            )

        elif trend == "BEARISH":

            regime = (
                "BEAR TREND"
            )

        else:

            regime = "MIXED"

    else:

        if volatility == "HIGH":

            regime = (
                "VOLATILE RANGE"
            )

        else:

            regime = (
                "RANGE / CHOP"
            )

    return {
        "regime": regime,
        "trend": trend,
        "trend_strength":
            strength,
        "volatility":
            volatility,
        "atr_pct":
            round(
                atr_pct,
                3,
            ),
    }


# ============================================================
# MOMENTUM
# ============================================================

def calculate_momentum(
    candles: pd.DataFrame,
    lookback: int = 10,
) -> float:

    if (
        candles is None
        or len(candles)
        <= lookback
    ):
        return 0.0

    close = candles[
        "close"
    ].astype(float)

    current = float(
        close.iloc[-1]
    )

    previous = float(
        close.iloc[
            -(lookback + 1)
        ]
    )

    if previous <= 0:
        return 0.0

    return round(
        (
            current
            - previous
        )
        / previous
        * 100,
        3,
    )


# ============================================================
# CORRELATION
# ============================================================

def correlation_matrix(
    candle_map: Dict[
        str,
        pd.DataFrame
    ],
) -> pd.DataFrame:

    returns = {}

    for symbol, candles in candle_map.items():

        if (
            candles is None
            or len(candles) < 20
        ):
            continue

        close = candles[
            "close"
        ].astype(float)

        returns[
            symbol
        ] = close.pct_change()

    if len(returns) < 2:

        return pd.DataFrame()

    dataframe = pd.DataFrame(
        returns
    )

    return dataframe.corr()


# ============================================================
# MARKET BREADTH
# ============================================================

def calculate_market_breadth(
    scanner_results: List[Dict],
) -> Dict:

    valid = [
        item
        for item in scanner_results
        if item.get(
            "valid"
        )
    ]

    if not valid:

        return {
            "bullish": 0,
            "bearish": 0,
            "neutral": 0,
            "bullish_pct": 0.0,
            "bearish_pct": 0.0,
        }

    bullish = 0
    bearish = 0
    neutral = 0

    for item in valid:

        score = safe_float(
            item.get(
                "score"
            )
        )

        if score > 0:

            bullish += 1

        elif score < 0:

            bearish += 1

        else:

            neutral += 1

    total = len(valid)

    return {
        "bullish": bullish,
        "bearish": bearish,
        "neutral": neutral,

        "bullish_pct": round(
            bullish
            / total
            * 100,
            1,
        ),

        "bearish_pct": round(
            bearish
            / total
            * 100,
            1,
        ),
    }


# ============================================================
# SCANNER INTELLIGENCE
# ============================================================

def scanner_intelligence(
    scanner_results: List[Dict],
) -> Dict:

    valid = [
        item
        for item in scanner_results
        if item.get(
            "valid"
        )
    ]

    confirmed = [
        item
        for item in valid
        if item.get(
            "confirmed"
        )
    ]

    strongest = None

    if valid:

        strongest = max(
            valid,
            key=lambda item: abs(
                safe_float(
                    item.get(
                        "score"
                    )
                )
            ),
        )

    breadth = (
        calculate_market_breadth(
            valid
        )
    )

    return {
        "markets_scanned":
            len(
                scanner_results
            ),

        "valid_markets":
            len(valid),

        "confirmed_setups":
            len(confirmed),

        "strongest_market":
            strongest,

        "breadth":
            breadth,
    }


# ============================================================
# TRADE ANALYTICS
# ============================================================

def trade_statistics(
    trade_history: List[Dict],
) -> Dict:

    if not trade_history:

        return {
            "total_trades": 0,
            "wins": 0,
            "losses": 0,
            "win_rate": 0.0,
            "net_pnl": 0.0,
            "average_win": 0.0,
            "average_loss": 0.0,
            "profit_factor": 0.0,
            "expectancy": 0.0,
        }

    pnl_values = [
        safe_float(
            trade.get(
                "pnl"
            )
        )
        for trade
        in trade_history
    ]

    wins = [
        pnl
        for pnl in pnl_values
        if pnl > 0
    ]

    losses = [
        pnl
        for pnl in pnl_values
        if pnl < 0
    ]

    total = len(
        pnl_values
    )

    win_rate = (
        len(wins)
        / total
        * 100
    )

    gross_profit = sum(
        wins
    )

    gross_loss = abs(
        sum(
            losses
        )
    )

    if gross_loss > 0:

        profit_factor = (
            gross_profit
            / gross_loss
        )

    else:

        profit_factor = (
            gross_profit
            if gross_profit > 0
            else 0.0
        )

    average_win = (
        np.mean(wins)
        if wins
        else 0.0
    )

    average_loss = (
        np.mean(losses)
        if losses
        else 0.0
    )

    expectancy = (
        np.mean(
            pnl_values
        )
    )

    return {
        "total_trades":
            total,

        "wins":
            len(wins),

        "losses":
            len(losses),

        "win_rate":
            round(
                win_rate,
                2,
            ),

        "net_pnl":
            round(
                sum(
                    pnl_values
                ),
                2,
            ),

        "average_win":
            round(
                float(
                    average_win
                ),
                2,
            ),

        "average_loss":
            round(
                float(
                    average_loss
                ),
                2,
            ),

        "profit_factor":
            round(
                float(
                    profit_factor
                ),
                3,
            ),

        "expectancy":
            round(
                float(
                    expectancy
                ),
                3,
            ),
    }


# ============================================================
# TP / SL PROGRESS
# ============================================================

def position_progress(
    position: Optional[Dict],
    current_price: float,
) -> Dict:

    if not position:

        return {
            "active": False
        }

    entry = safe_float(
        position.get(
            "entry_price"
        )
    )

    tp = safe_float(
        position.get(
            "take_profit"
        )
    )

    sl = safe_float(
        position.get(
            "stop_loss"
        )
    )

    current_price = (
        safe_float(
            current_price
        )
    )

    side = position.get(
        "side"
    )

    if (
        entry <= 0
        or current_price <= 0
    ):

        return {
            "active": True,
            "pnl_pct": 0.0,
        }

    if side == "LONG":

        pnl_pct = (
            current_price
            - entry
        ) / entry * 100

    else:

        pnl_pct = (
            entry
            - current_price
        ) / entry * 100

    tp_distance = abs(
        tp
        - current_price
    )

    sl_distance = abs(
        sl
        - current_price
    )

    return {
        "active": True,

        "pnl_pct": round(
            pnl_pct,
            3,
        ),

        "tp_distance": round(
            tp_distance,
            8,
        ),

        "sl_distance": round(
            sl_distance,
            8,
        ),
    }

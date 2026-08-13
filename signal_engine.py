"""
signal_engine.py

Trading signal engine.
Generates BUY / SELL / NO TRADE signals
using RSI, MACD, Bollinger Bands, trend and volume.
"""

import pandas as pd


def calculate_rsi(series, period=14):
    delta = series.diff()

    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)

    avg_gain = gain.rolling(period).mean()
    avg_loss = loss.rolling(period).mean()

    rs = avg_gain / avg_loss.replace(0, pd.NA)

    rsi = 100 - (100 / (1 + rs))

    return rsi.fillna(50)


def calculate_indicators(df):
    df = df.copy()

    # Moving averages
    df["ema_fast"] = df["close"].ewm(
        span=9,
        adjust=False
    ).mean()

    df["ema_slow"] = df["close"].ewm(
        span=21,
        adjust=False
    ).mean()

    # RSI
    df["rsi"] = calculate_rsi(df["close"], 14)

    # MACD
    ema12 = df["close"].ewm(
        span=12,
        adjust=False
    ).mean()

    ema26 = df["close"].ewm(
        span=26,
        adjust=False
    ).mean()

    df["macd"] = ema12 - ema26

    df["macd_signal"] = df["macd"].ewm(
        span=9,
        adjust=False
    ).mean()

    # Bollinger Bands
    middle = df["close"].rolling(20).mean()
    std = df["close"].rolling(20).std()

    df["bb_middle"] = middle
    df["bb_upper"] = middle + (std * 2)
    df["bb_lower"] = middle - (std * 2)

    # Volume average
    df["volume_average"] = df["volume"].rolling(20).mean()

    return df


def generate_signal(df):
    """
    Returns:
        BUY
        SELL
        NO TRADE
    """

    if df is None or len(df) < 50:
        return {
            "signal": "NO TRADE",
            "score": 0,
            "reason": "Not enough market data",
        }

    df = calculate_indicators(df)

    latest = df.iloc[-1]

    score = 0
    reasons = []

    # Trend
    if latest["ema_fast"] > latest["ema_slow"]:
        score += 2
        reasons.append("Bullish trend")

    elif latest["ema_fast"] < latest["ema_slow"]:
        score -= 2
        reasons.append("Bearish trend")

    # RSI
    if latest["rsi"] < 35:
        score += 1
        reasons.append("RSI oversold")

    elif latest["rsi"] > 65:
        score -= 1
        reasons.append("RSI overbought")

    # MACD
    if latest["macd"] > latest["macd_signal"]:
        score += 1
        reasons.append("MACD bullish")

    elif latest["macd"] < latest["macd_signal"]:
        score -= 1
        reasons.append("MACD bearish")

    # Bollinger Bands
    if latest["close"] < latest["bb_lower"]:
        score += 1
        reasons.append("Price below lower Bollinger Band")

    elif latest["close"] > latest["bb_upper"]:
        score -= 1
        reasons.append("Price above upper Bollinger Band")

    # Volume confirmation
    if (
        pd.notna(latest["volume_average"])
        and latest["volume"] > latest["volume_average"]
    ):
        if score > 0:
            score += 1
            reasons.append("Strong volume confirmation")

        elif score < 0:
            score -= 1
            reasons.append("Strong volume confirmation")

    # Final decision
    if score >= 4:
        signal = "BUY"

    elif score <= -4:
        signal = "SELL"

    else:
        signal = "NO TRADE"

    return {
        "signal": signal,
        "score": int(score),
        "reason": ", ".join(reasons),
        "price": float(latest["close"]),
        "rsi": float(latest["rsi"]),
        "macd": float(latest["macd"]),
    }

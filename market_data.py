"""
market_data.py
Live Binance / Bybit USDT Futures market data.

Used by:
    app.py
"""

import time
import pandas as pd

from exchanges import get_client


SYMBOLS = [
    "BTCUSDT",
    "ETHUSDT",
    "SOLUSDT",
    "XRPUSDT",
]


def get_market_data(
    exchange,
    api_key="",
    api_secret="",
    use_testnet=True,
):
    """
    Returns live ticker data for the main crypto futures markets.
    """

    client = get_client(
        exchange=exchange,
        api_key=api_key,
        api_secret=api_secret,
        use_testnet=use_testnet,
    )

    results = []

    for symbol in SYMBOLS:
        ticker = client.get_ticker(symbol)

        if ticker is None:
            results.append({
                "symbol": symbol,
                "price": None,
                "change_pct": None,
                "high": None,
                "low": None,
                "status": "Unavailable",
            })
            continue

        results.append({
            "symbol": symbol,
            "price": ticker["last"],
            "change_pct": ticker["change_pct"],
            "high": ticker["high"],
            "low": ticker["low"],
            "status": "Live",
        })

    return results


def get_candles(
    exchange,
    symbol,
    timeframe_minutes=15,
    limit=100,
    api_key="",
    api_secret="",
    use_testnet=True,
):
    """
    Get OHLCV candles for charting.
    """

    client = get_client(
        exchange=exchange,
        api_key=api_key,
        api_secret=api_secret,
        use_testnet=use_testnet,
    )

    return client.get_klines(
        symbol=symbol,
        timeframe_minutes=timeframe_minutes,
        limit=limit,
    )

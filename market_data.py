"""
market_data.py

UK-friendly public market data provider.

Primary source:
    Coinbase Exchange public REST market data

No API key is required for candles/ticker data.

Used by:
    app.py
    bot_worker.py
"""

import time
import requests
import pandas as pd


COINBASE_BASE = "https://api.exchange.coinbase.com"

SYMBOL_MAP = {
    "BTCUSDT": "BTC-USD",
    "ETHUSDT": "ETH-USD",
    "SOLUSDT": "SOL-USD",
    "XRPUSDT": "XRP-USD",
    "ADAUSDT": "ADA-USD",
    "DOGEUSDT": "DOGE-USD",
    "AVAXUSDT": "AVAX-USD",
    "LINKUSDT": "LINK-USD",
    "DOTUSDT": "DOT-USD",
    "NEARUSDT": "NEAR-USD",
    "SUIUSDT": "SUI-USD",
}

SUPPORTED_GRANULARITIES = {
    1: 60,
    5: 300,
    15: 900,
    60: 3600,
    360: 21600,
    1440: 86400,
}


def _product_id(symbol):
    symbol = str(symbol).upper().replace("/", "").replace("-", "")

    if symbol in SYMBOL_MAP:
        return SYMBOL_MAP[symbol]

    if symbol.endswith("USDT"):
        base = symbol[:-4]
        return f"{base}-USD"

    if symbol.endswith("USD"):
        base = symbol[:-3]
        return f"{base}-USD"

    raise ValueError(f"Unsupported symbol: {symbol}")


def _granularity(timeframe_minutes):
    timeframe_minutes = int(timeframe_minutes)

    if timeframe_minutes in SUPPORTED_GRANULARITIES:
        return SUPPORTED_GRANULARITIES[timeframe_minutes]

    # Safe fallback
    return 900


def get_ticker(
    symbol,
    exchange=None,
    api_key="",
    api_secret="",
    use_testnet=False,
):
    """
    Returns public ticker data from Coinbase Exchange.
    """

    try:
        product = _product_id(symbol)

        ticker_url = (
            f"{COINBASE_BASE}/products/{product}/ticker"
        )

        stats_url = (
            f"{COINBASE_BASE}/products/{product}/stats"
        )

        headers = {
            "User-Agent": "crypto-futures-paper-bot/1.0",
            "Accept": "application/json",
        }

        ticker_response = requests.get(
            ticker_url,
            headers=headers,
            timeout=10,
        )

        ticker_response.raise_for_status()

        ticker = ticker_response.json()

        stats_response = requests.get(
            stats_url,
            headers=headers,
            timeout=10,
        )

        stats_response.raise_for_status()

        stats = stats_response.json()

        last = float(
            ticker.get("price") or 0
        )

        high = float(
            stats.get("high") or 0
        )

        low = float(
            stats.get("low") or 0
        )

        open_price = float(
            stats.get("open") or 0
        )

        volume = float(
            stats.get("volume") or 0
        )

        if open_price > 0:
            change_pct = (
                (last - open_price)
                / open_price
                * 100
            )
        else:
            change_pct = 0.0

        return {
            "last": last,
            "change_pct": change_pct,
            "high": high,
            "low": low,
            "volume": volume,
            "source": "Coinbase",
        }

    except Exception as error:
        print(
            f"Coinbase ticker error: {error}",
            flush=True,
        )

        return None


def get_candles(
    exchange,
    symbol,
    timeframe_minutes=15,
    limit=100,
    api_key="",
    api_secret="",
    use_testnet=False,
):
    """
    Get public OHLCV candles from Coinbase Exchange.

    The exchange/API/testnet arguments are kept so the
    existing app.py and bot_worker.py do not need changing.
    """

    try:
        product = _product_id(symbol)

        granularity = _granularity(
            timeframe_minutes
        )

        limit = max(
            10,
            min(
                int(limit),
                300,
            ),
        )

        now = int(time.time())

        start = (
            now
            - (
                granularity
                * limit
            )
        )

        url = (
            f"{COINBASE_BASE}"
            f"/products/{product}/candles"
        )

        params = {
            "granularity": granularity,
            "start": pd.Timestamp(
                start,
                unit="s",
                tz="UTC",
            ).isoformat(),
            "end": pd.Timestamp(
                now,
                unit="s",
                tz="UTC",
            ).isoformat(),
        }

        headers = {
            "User-Agent": "crypto-futures-paper-bot/1.0",
            "Accept": "application/json",
        }

        response = requests.get(
            url,
            params=params,
            headers=headers,
            timeout=15,
        )

        response.raise_for_status()

        data = response.json()

        if not data:
            print(
                "Coinbase returned no candles.",
                flush=True,
            )
            return None

        rows = []

        for candle in data:

            if (
                not isinstance(candle, list)
                or len(candle) < 6
            ):
                continue

            timestamp = candle[0]
            low = candle[1]
            high = candle[2]
            open_price = candle[3]
            close = candle[4]
            volume = candle[5]

            rows.append(
                {
                    "timestamp": int(timestamp) * 1000,
                    "open": float(open_price),
                    "high": float(high),
                    "low": float(low),
                    "close": float(close),
                    "volume": float(volume),
                }
            )

        if not rows:
            return None

        df = pd.DataFrame(rows)

        # Coinbase usually returns newest first.
        df = (
            df.sort_values("timestamp")
            .drop_duplicates(
                subset=["timestamp"]
            )
            .tail(limit)
            .reset_index(drop=True)
        )

        return df

    except Exception as error:
        print(
            f"Coinbase candles error: {error}",
            flush=True,
        )

        return None


def get_market_data(
    exchange=None,
    api_key="",
    api_secret="",
    use_testnet=False,
):
    """
    Return market snapshots for major crypto assets.
    """

    symbols = [
        "BTCUSDT",
        "ETHUSDT",
        "SOLUSDT",
        "XRPUSDT",
    ]

    results = []

    for symbol in symbols:

        ticker = get_ticker(
            symbol=symbol,
            exchange=exchange,
            api_key=api_key,
            api_secret=api_secret,
            use_testnet=use_testnet,
        )

        if ticker is None:

            results.append(
                {
                    "symbol": symbol,
                    "price": None,
                    "change_pct": None,
                    "high": None,
                    "low": None,
                    "status": "Unavailable",
                    "source": "Coinbase",
                }
            )

            continue

        results.append(
            {
                "symbol": symbol,
                "price": ticker["last"],
                "change_pct": ticker[
                    "change_pct"
                ],
                "high": ticker["high"],
                "low": ticker["low"],
                "status": "Live",
                "source": "Coinbase",
            }
        )

    return results

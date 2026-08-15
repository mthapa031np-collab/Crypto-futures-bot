"""
market_data.py

PRO AI QUANT TERMINAL V2

UK-friendly Coinbase public market-data provider.

Features:
- Public ticker
- Public OHLCV candles
- 1m / 5m / 15m / 1h / 6h / 1d native Coinbase candles
- Proper synthetic 4H candles built from 1H candles
- Compatible with app.py, scanner.py, strategy_engine.py,
  trade_engine.py and bot_worker.py

No private API key required.
"""

import time
import requests
import pandas as pd


COINBASE_BASE = "https://api.exchange.coinbase.com"


# ============================================================
# SYMBOL MAPPING
# ============================================================

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


# Coinbase Exchange native granularities.
SUPPORTED_GRANULARITIES = {
    1: 60,
    5: 300,
    15: 900,
    60: 3600,
    360: 21600,
    1440: 86400,
}


HEADERS = {
    "User-Agent": "pro-ai-quant-terminal/2.0",
    "Accept": "application/json",
}


# ============================================================
# HELPERS
# ============================================================

def _product_id(symbol):

    symbol = (
        str(symbol)
        .upper()
        .replace("/", "")
        .replace("-", "")
        .strip()
    )

    if symbol in SYMBOL_MAP:
        return SYMBOL_MAP[symbol]

    if symbol.endswith("USDT"):

        base = symbol[:-4]

        return f"{base}-USD"

    if symbol.endswith("USD"):

        base = symbol[:-3]

        return f"{base}-USD"

    raise ValueError(
        f"Unsupported symbol: {symbol}"
    )


def _native_granularity(
    timeframe_minutes,
):

    timeframe_minutes = int(
        timeframe_minutes
    )

    return SUPPORTED_GRANULARITIES.get(
        timeframe_minutes
    )


def _request_coinbase_candles(
    product,
    granularity_seconds,
    limit,
):

    limit = max(
        10,
        min(
            int(limit),
            300,
        ),
    )

    now = int(
        time.time()
    )

    start = (
        now
        - (
            granularity_seconds
            * limit
        )
    )

    url = (
        f"{COINBASE_BASE}"
        f"/products/{product}/candles"
    )

    params = {
        "granularity":
            granularity_seconds,

        "start":
            pd.Timestamp(
                start,
                unit="s",
                tz="UTC",
            ).isoformat(),

        "end":
            pd.Timestamp(
                now,
                unit="s",
                tz="UTC",
            ).isoformat(),
    }

    response = requests.get(
        url,
        params=params,
        headers=HEADERS,
        timeout=15,
    )

    response.raise_for_status()

    data = response.json()

    if not data:
        return None

    rows = []

    for candle in data:

        if (
            not isinstance(
                candle,
                list,
            )
            or len(candle) < 6
        ):
            continue

        rows.append(
            {
                "timestamp":
                    int(
                        candle[0]
                    )
                    * 1000,

                "low":
                    float(
                        candle[1]
                    ),

                "high":
                    float(
                        candle[2]
                    ),

                "open":
                    float(
                        candle[3]
                    ),

                "close":
                    float(
                        candle[4]
                    ),

                "volume":
                    float(
                        candle[5]
                    ),
            }
        )

    if not rows:
        return None

    df = pd.DataFrame(
        rows
    )

    df = (
        df
        .sort_values(
            "timestamp"
        )
        .drop_duplicates(
            subset=[
                "timestamp"
            ]
        )
        .reset_index(
            drop=True
        )
    )

    return df


# ============================================================
# BUILD 4H FROM 1H
# ============================================================

def _build_4h_candles(
    product,
    limit,
):

    # Coinbase Exchange has no native 4H candle.
    # We fetch 1H candles and combine every four hours.

    requested_4h = max(
        50,
        int(limit),
    )

    # Coinbase returns at most roughly 300 candles
    # per request, so this gives up to ~75 4H candles.
    hourly_limit = min(
        requested_4h * 4 + 8,
        300,
    )

    hourly = (
        _request_coinbase_candles(
            product=product,
            granularity_seconds=3600,
            limit=hourly_limit,
        )
    )

    if (
        hourly is None
        or len(hourly) < 4
    ):
        return None

    df = hourly.copy()

    df["datetime"] = pd.to_datetime(
        df["timestamp"],
        unit="ms",
        utc=True,
    )

    # Align candles to UTC 4-hour blocks:
    # 00:00, 04:00, 08:00, 12:00, 16:00, 20:00.
    df["bucket"] = (
        df["datetime"]
        .dt.floor("4h")
    )

    aggregated = (
        df.groupby(
            "bucket",
            as_index=False,
        )
        .agg(
            {
                "open": "first",
                "high": "max",
                "low": "min",
                "close": "last",
                "volume": "sum",
            }
        )
    )

    aggregated[
        "timestamp"
    ] = (
        aggregated[
            "bucket"
        ]
        .astype("int64")
        // 10**6
    )

    aggregated = aggregated[
        [
            "timestamp",
            "open",
            "high",
            "low",
            "close",
            "volume",
        ]
    ]

    aggregated = (
        aggregated
        .sort_values(
            "timestamp"
        )
        .tail(
            int(limit)
        )
        .reset_index(
            drop=True
        )
    )

    return aggregated


# ============================================================
# TICKER
# ============================================================

def get_ticker(
    symbol,
    exchange=None,
    api_key="",
    api_secret="",
    use_testnet=False,
):

    try:

        product = _product_id(
            symbol
        )

        ticker_url = (
            f"{COINBASE_BASE}"
            f"/products/{product}/ticker"
        )

        stats_url = (
            f"{COINBASE_BASE}"
            f"/products/{product}/stats"
        )

        ticker_response = requests.get(
            ticker_url,
            headers=HEADERS,
            timeout=10,
        )

        ticker_response.raise_for_status()

        ticker = (
            ticker_response.json()
        )

        stats_response = requests.get(
            stats_url,
            headers=HEADERS,
            timeout=10,
        )

        stats_response.raise_for_status()

        stats = (
            stats_response.json()
        )

        last = float(
            ticker.get(
                "price"
            )
            or 0
        )

        high = float(
            stats.get(
                "high"
            )
            or 0
        )

        low = float(
            stats.get(
                "low"
            )
            or 0
        )

        open_price = float(
            stats.get(
                "open"
            )
            or 0
        )

        volume = float(
            stats.get(
                "volume"
            )
            or 0
        )

        bid = float(
            ticker.get(
                "bid"
            )
            or 0
        )

        ask = float(
            ticker.get(
                "ask"
            )
            or 0
        )

        if open_price > 0:

            change_pct = (
                (
                    last
                    - open_price
                )
                / open_price
                * 100
            )

        else:

            change_pct = 0.0

        spread_pct = 0.0

        if (
            bid > 0
            and ask > 0
        ):

            midpoint = (
                bid + ask
            ) / 2

            if midpoint > 0:

                spread_pct = (
                    (
                        ask - bid
                    )
                    / midpoint
                    * 100
                )

        return {
            "last": last,
            "change_pct":
                change_pct,
            "high": high,
            "low": low,
            "volume": volume,
            "bid": bid,
            "ask": ask,
            "spread_pct":
                spread_pct,
            "source":
                "Coinbase",
        }

    except Exception as error:

        print(
            "Coinbase ticker error: "
            f"{error}",
            flush=True,
        )

        return None


# ============================================================
# CANDLES
# ============================================================

def get_candles(
    exchange,
    symbol,
    timeframe_minutes=15,
    limit=100,
    api_key="",
    api_secret="",
    use_testnet=False,
):

    try:

        product = _product_id(
            symbol
        )

        timeframe_minutes = int(
            timeframe_minutes
        )

        limit = max(
            10,
            min(
                int(limit),
                300,
            ),
        )

        # ----------------------------------------------------
        # TRUE 4H SUPPORT
        # ----------------------------------------------------

        if timeframe_minutes == 240:

            return _build_4h_candles(
                product=product,
                limit=limit,
            )

        # ----------------------------------------------------
        # NATIVE COINBASE TIMEFRAMES
        # ----------------------------------------------------

        granularity = (
            _native_granularity(
                timeframe_minutes
            )
        )

        if granularity is None:

            raise ValueError(
                "Unsupported timeframe: "
                f"{timeframe_minutes} minutes"
            )

        df = (
            _request_coinbase_candles(
                product=product,
                granularity_seconds=(
                    granularity
                ),
                limit=limit,
            )
        )

        if df is None:

            print(
                "Coinbase returned "
                f"no candles for {product}.",
                flush=True,
            )

            return None

        return (
            df
            .tail(limit)
            .reset_index(
                drop=True
            )
        )

    except Exception as error:

        print(
            "Coinbase candles error: "
            f"{error}",
            flush=True,
        )

        return None


# ============================================================
# MARKET SNAPSHOTS
# ============================================================

def get_market_data(
    exchange=None,
    api_key="",
    api_secret="",
    use_testnet=False,
):

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
                    "symbol":
                        symbol,

                    "price":
                        None,

                    "change_pct":
                        None,

                    "high":
                        None,

                    "low":
                        None,

                    "status":
                        "Unavailable",

                    "source":
                        "Coinbase",
                }
            )

            continue

        results.append(
            {
                "symbol":
                    symbol,

                "price":
                    ticker[
                        "last"
                    ],

                "change_pct":
                    ticker[
                        "change_pct"
                    ],

                "high":
                    ticker[
                        "high"
                    ],

                "low":
                    ticker[
                        "low"
                    ],

                "status":
                    "Live",

                "source":
                    "Coinbase",
            }
        )

    return results

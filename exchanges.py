"""
exchanges.py
Simple Binance / Bybit USDT Futures connector.

Used by:
    app.py
    bot_worker.py
"""

import ccxt


def get_client(exchange, api_key="", api_secret="", use_testnet=True):
    exchange_name = str(exchange).strip().lower()

    if exchange_name == "binance":
        client = ccxt.binance({
            "apiKey": api_key,
            "secret": api_secret,
            "enableRateLimit": True,
            "options": {
                "defaultType": "future",
            },
        })

        if use_testnet:
            client.set_sandbox_mode(True)

    elif exchange_name == "bybit":
        client = ccxt.bybit({
            "apiKey": api_key,
            "secret": api_secret,
            "enableRateLimit": True,
            "options": {
                "defaultType": "linear",
            },
        })

        if use_testnet:
            client.set_sandbox_mode(True)

    else:
        raise ValueError(
            f"Unsupported exchange: {exchange}. "
            "Use Binance or Bybit."
        )

    return FuturesClient(client)


class FuturesClient:

    def __init__(self, client):
        self.client = client
        self.markets_loaded = False

    def _load_markets(self):
        if not self.markets_loaded:
            self.client.load_markets()
            self.markets_loaded = True

    def _symbol(self, symbol):
        self._load_markets()

        symbol = symbol.upper().replace("/", "").replace(":", "")

        # Convert BTCUSDT -> BTC/USDT:USDT
        base = symbol[:-4]
        quote = symbol[-4:]

        unified = f"{base}/{quote}:{quote}"

        if unified in self.client.markets:
            return unified

        # Fallback for exchanges using spot-style symbols
        spot_style = f"{base}/{quote}"

        if spot_style in self.client.markets:
            return spot_style

        # Search by market id
        for market_symbol, market in self.client.markets.items():
            if market.get("id") == symbol:
                return market_symbol

        raise ValueError(
            f"Symbol {symbol} not found on {self.client.id}"
        )

    def get_ticker(self, symbol):
        try:
            market_symbol = self._symbol(symbol)
            ticker = self.client.fetch_ticker(market_symbol)

            return {
                "last": float(ticker.get("last") or 0),
                "change_pct": float(ticker.get("percentage") or 0),
                "high": float(ticker.get("high") or 0),
                "low": float(ticker.get("low") or 0),
            }

        except Exception as e:
            print(f"Ticker error: {e}", flush=True)
            return None

    def get_klines(self, symbol, timeframe_minutes=15, limit=100):
        try:
            market_symbol = self._symbol(symbol)

            timeframe = f"{int(timeframe_minutes)}m"

            candles = self.client.fetch_ohlcv(
                market_symbol,
                timeframe=timeframe,
                limit=limit,
            )

            if not candles:
                return None

            import pandas as pd

            df = pd.DataFrame(
                candles,
                columns=[
                    "timestamp",
                    "open",
                    "high",
                    "low",
                    "close",
                    "volume",
                ],
            )

            for column in [
                "open",
                "high",
                "low",
                "close",
                "volume",
            ]:
                df[column] = pd.to_numeric(
                    df[column],
                    errors="coerce",
                )

            return df

        except Exception as e:
            print(f"Klines error: {e}", flush=True)
            return None

    def get_balance(self):
        try:
            balance = self.client.fetch_balance()

            # Futures USDT balance
            if "USDT" in balance:
                usdt = balance["USDT"]

                if isinstance(usdt, dict):
                    total = usdt.get("total")
                    free = usdt.get("free")

                    if total is not None:
                        return float(total)

                    if free is not None:
                        return float(free)

            # Fallback
            total = balance.get("total", {})

            if isinstance(total, dict):
                usdt_total = total.get("USDT")

                if usdt_total is not None:
                    return float(usdt_total)

            return None

        except Exception as e:
            print(f"Balance error: {e}", flush=True)
            return None

    def get_position(self, symbol):
        try:
            market_symbol = self._symbol(symbol)

            positions = self.client.fetch_positions(
                [market_symbol]
            )

            for position in positions:
                contracts = position.get("contracts")

                if contracts is None:
                    contracts = position.get("contractSize", 0)

                try:
                    contracts = float(contracts or 0)
                except Exception:
                    contracts = 0

                if contracts > 0:
                    side = position.get("side")

                    entry = float(
                        position.get("entryPrice") or 0
                    )

                    mark = float(
                        position.get("markPrice") or 0
                    )

                    pnl = float(
                        position.get("unrealizedPnl") or 0
                    )

                    return {
                        "side": side,
                        "size": contracts,
                        "entry": entry,
                        "mark": mark,
                        "pnl": pnl,
                    }

            return None

        except Exception as e:
            print(f"Position error: {e}", flush=True)
            return None

    def set_leverage(self, symbol, leverage):
        try:
            market_symbol = self._symbol(symbol)

            return self.client.set_leverage(
                int(leverage),
                market_symbol,
            )

        except Exception as e:
            print(f"Leverage error: {e}", flush=True)
            return None

    def place_order(self, symbol, side, qty):
        try:
            market_symbol = self._symbol(symbol)

            side = side.lower()

            amount = float(qty)

            order = self.client.create_order(
                market_symbol,
                "market",
                side,
                amount,
            )

            return order

        except Exception as e:
            print(f"Order error: {e}", flush=True)
            return {
                "error": str(e)
            }

    def place_tp_sl(
        self,
        symbol,
        close_side,
        tp_price,
        sl_price,
    ):
        """
        Attempts to place TP and SL using exchange-native
        conditional orders where supported.

        If the exchange rejects the order format, the error
        is returned instead of crashing the whole application.
        """

        results = {
            "tp": None,
            "sl": None,
        }

        try:
            market_symbol = self._symbol(symbol)

            close_side = close_side.lower()

            # Take Profit
            try:
                results["tp"] = self.client.create_order(
                    market_symbol,
                    "limit",
                    close_side,
                    None,
                    float(tp_price),
                    {
                        "reduceOnly": True,
                    },
                )
            except Exception as e:
                results["tp"] = {
                    "error": str(e)
                }

            # Stop Loss
            try:
                results["sl"] = self.client.create_order(
                    market_symbol,
                    "market",
                    close_side,
                    None,
                    None,
                    {
                        "stopLossPrice": float(sl_price),
                        "reduceOnly": True,
                    },
                )
            except Exception as e:
                results["sl"] = {
                    "error": str(e)
                }

            return results["tp"], results["sl"]

        except Exception as e:
            return {
                "error": str(e)
            }, None

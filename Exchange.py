"""
exchanges.py
Shared exchange client for Binance Futures and Bybit (V5 API, linear/USDT perpetuals).
Both app.py and bot_worker.py import from this so trading logic doesn't need to
know which exchange it's talking to.

get_client("Binance" | "Bybit", api_key, api_secret, testnet=True) returns a client
with a common interface:
    get_ticker(symbol) -> {"last","change_pct","high","low"} or None
    get_klines(symbol, interval_minutes=15, limit=100) -> pandas DataFrame with a "close" column, or None
    get_balance() -> float USDT available balance, or None
    get_position(symbol) -> {"side","size","entry","mark","pnl"} or None
    set_leverage(symbol, leverage) -> raw API response
    place_order(symbol, side="BUY"|"SELL", qty) -> raw API response
    place_tp_sl(symbol, close_side, tp_price, sl_price) -> (tp_result, sl_result)
"""

import time
import hmac
import hashlib
import json
import requests
import pandas as pd
from urllib.parse import urlencode


class BinanceFuturesClient:
    name = "Binance"

    def __init__(self, api_key, api_secret, testnet=True):
        self.api_key = api_key
        self.api_secret = api_secret
        self.base_url = "https://testnet.binancefuture.com" if testnet else "https://fapi.binance.com"
        # Public market data is more reliable/liquid from mainnet even when trading on testnet
        self.public_base = "https://fapi.binance.com"

    def _signed(self, method, path, params=None):
        if not self.api_key or not self.api_secret:
            return {"error": "no_api_key"}
        params = params or {}
        params["timestamp"] = int(time.time() * 1000)
        params["recvWindow"] = 5000
        query = urlencode(params)
        sig = hmac.new(self.api_secret.encode(), query.encode(), hashlib.sha256).hexdigest()
        params["signature"] = sig
        headers = {"X-MBX-APIKEY": self.api_key}
        url = self.base_url + path
        try:
            if method == "GET":
                r = requests.get(url, headers=headers, params=params, timeout=8)
            elif method == "POST":
                r = requests.post(url, headers=headers, params=params, timeout=8)
            elif method == "DELETE":
                r = requests.delete(url, headers=headers, params=params, timeout=8)
            return r.json()
        except Exception as e:
            return {"error": str(e)}

    def get_ticker(self, symbol):
        try:
            r = requests.get(f"{self.public_base}/fapi/v1/ticker/24hr?symbol={symbol}", timeout=5)
            if r.status_code == 200:
                d = r.json()
                return {"last": float(d["lastPrice"]), "change_pct": float(d["priceChangePercent"]),
                        "high": float(d["highPrice"]), "low": float(d["lowPrice"])}
        except Exception:
            pass
        return None

    def get_klines(self, symbol, interval_minutes=15, limit=100):
        try:
            r = requests.get(
                f"{self.public_base}/fapi/v1/klines?symbol={symbol}&interval={interval_minutes}m&limit={limit}",
                timeout=5)
            if r.status_code == 200:
                df = pd.DataFrame(r.json(), columns=[
                    "open_time", "open", "high", "low", "close", "volume",
                    "close_time", "qav", "trades", "tbv", "tqv", "ignore"])
                df["close"] = df["close"].astype(float)
                return df
        except Exception:
            pass
        return None

    def get_balance(self):
        data = self._signed("GET", "/fapi/v2/balance")
        if isinstance(data, list):
            for a in data:
                if a.get("asset") == "USDT":
                    return float(a.get("availableBalance", 0))
        return None

    def get_position(self, symbol):
        data = self._signed("GET", "/fapi/v2/positionRisk", {"symbol": symbol})
        if isinstance(data, list):
            for p in data:
                if float(p.get("positionAmt", 0)) != 0:
                    return {"side": "LONG" if float(p["positionAmt"]) > 0 else "SHORT",
                            "size": p["positionAmt"], "entry": float(p["entryPrice"]),
                            "mark": float(p["markPrice"]), "pnl": float(p["unRealizedProfit"])}
        return None

    def set_leverage(self, symbol, leverage):
        return self._signed("POST", "/fapi/v1/leverage", {"symbol": symbol, "leverage": leverage})

    def place_order(self, symbol, side, qty):
        return self._signed("POST", "/fapi/v1/order", {
            "symbol": symbol, "side": side, "type": "MARKET", "quantity": qty})

    def place_tp_sl(self, symbol, close_side, tp_price, sl_price):
        tp = self._signed("POST", "/fapi/v1/order", {
            "symbol": symbol, "side": close_side, "type": "TAKE_PROFIT_MARKET",
            "stopPrice": round(tp_price, 2), "closePosition": "true", "workingType": "MARK_PRICE"})
        sl = self._signed("POST", "/fapi/v1/order", {
            "symbol": symbol, "side": close_side, "type": "STOP_MARKET",
            "stopPrice": round(sl_price, 2), "closePosition": "true", "workingType": "MARK_PRICE"})
        return tp, sl


class BybitClient:
    name = "Bybit"

    def __init__(self, api_key, api_secret, testnet=True):
        self.api_key = api_key
        self.api_secret = api_secret
        self.base_url = "https://api-testnet.bybit.com" if testnet else "https://api.bybit.com"
        self.recv_window = "5000"

    def _sign(self, payload_str):
        return hmac.new(self.api_secret.encode(), payload_str.encode(), hashlib.sha256).hexdigest()

    def _get(self, path, params=None):
        if not self.api_key or not self.api_secret:
            return {"error": "no_api_key"}
        params = params or {}
        timestamp = str(int(time.time() * 1000))
        query = urlencode(sorted(params.items()))
        payload = timestamp + self.api_key + self.recv_window + query
        headers = {
            "X-BAPI-API-KEY": self.api_key, "X-BAPI-TIMESTAMP": timestamp,
            "X-BAPI-SIGN": self._sign(payload), "X-BAPI-RECV-WINDOW": self.recv_window,
        }
        url = f"{self.base_url}{path}?{query}" if query else f"{self.base_url}{path}"
        try:
            r = requests.get(url, headers=headers, timeout=8)
            return r.json()
        except Exception as e:
            return {"error": str(e)}

    def _post(self, path, body):
        if not self.api_key or not self.api_secret:
            return {"error": "no_api_key"}
        body_str = json.dumps(body)
        timestamp = str(int(time.time() * 1000))
        payload = timestamp + self.api_key + self.recv_window + body_str
        headers = {
            "X-BAPI-API-KEY": self.api_key, "X-BAPI-TIMESTAMP": timestamp,
            "X-BAPI-SIGN": self._sign(payload), "X-BAPI-RECV-WINDOW": self.recv_window,
            "Content-Type": "application/json",
        }
        try:
            r = requests.post(f"{self.base_url}{path}", headers=headers, data=body_str, timeout=8)
            return r.json()
        except Exception as e:
            return {"error": str(e)}

    def get_ticker(self, symbol):
        try:
            r = requests.get(f"{self.base_url}/v5/market/tickers?category=linear&symbol={symbol}", timeout=5)
            if r.status_code == 200:
                item = r.json()["result"]["list"][0]
                return {"last": float(item["lastPrice"]), "change_pct": float(item["price24hPcnt"]) * 100,
                        "high": float(item["highPrice24h"]), "low": float(item["lowPrice24h"])}
        except Exception:
            pass
        return None

    def get_klines(self, symbol, interval_minutes=15, limit=100):
        try:
            r = requests.get(
                f"{self.base_url}/v5/market/kline?category=linear&symbol={symbol}&interval={interval_minutes}&limit={limit}",
                timeout=5)
            if r.status_code == 200:
                rows = r.json()["result"]["list"][::-1]  # Bybit returns newest-first
                df = pd.DataFrame(rows, columns=["open_time", "open", "high", "low", "close", "volume", "turnover"])
                df["close"] = df["close"].astype(float)
                return df
        except Exception:
            pass
        return None

    def get_balance(self):
        data = self._get("/v5/account/wallet-balance", {"accountType": "UNIFIED"})
        try:
            for c in data["result"]["list"][0]["coin"]:
                if c["coin"] == "USDT":
                    val = c.get("availableToWithdraw") or c.get("walletBalance", 0)
                    return float(val) if val not in ("", None) else 0.0
        except Exception:
            pass
        return None

    def get_position(self, symbol):
        data = self._get("/v5/position/list", {"category": "linear", "symbol": symbol})
        try:
            for p in data["result"]["list"]:
                if float(p.get("size", 0) or 0) != 0:
                    return {"side": p["side"].upper(), "size": p["size"], "entry": float(p["avgPrice"]),
                            "mark": float(p["markPrice"]), "pnl": float(p["unrealisedPnl"])}
        except Exception:
            pass
        return None

    def set_leverage(self, symbol, leverage):
        return self._post("/v5/position/set-leverage", {
            "category": "linear", "symbol": symbol,
            "buyLeverage": str(leverage), "sellLeverage": str(leverage)})

    def place_order(self, symbol, side, qty):
        bybit_side = "Buy" if side == "BUY" else "Sell"
        return self._post("/v5/order/create", {
            "category": "linear", "symbol": symbol, "side": bybit_side,
            "orderType": "Market", "qty": str(qty)})

    def place_tp_sl(self, symbol, close_side, tp_price, sl_price):
        result = self._post("/v5/position/trading-stop", {
            "category": "linear", "symbol": symbol,
            "takeProfit": str(round(tp_price, 2)), "stopLoss": str(round(sl_price, 2)),
            "tpTriggerBy": "MarkPrice", "slTriggerBy": "MarkPrice", "positionIdx": 0})
        return result, result


def get_client(exchange, api_key, api_secret, testnet=True):
    if exchange == "Bybit":
        return BybitClient(api_key, api_secret, testnet)
    return BinanceFuturesClient(api_key, api_secret, testnet)

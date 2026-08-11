 """
bot_worker.py
Always-on RSI-based futures trading worker.

Deploy this as a Render "Background Worker" (NOT a Web Service) — it has no UI,
it just runs a loop forever, same as a cron job that never stops.

REQUIRED environment variables (set these in Render's dashboard, never in code):
  BINANCE_API_KEY
  BINANCE_API_SECRET
  USE_TESTNET        = "true" or "false"   (default: true — start here!)
  SYMBOL              = e.g. "BTCUSDT"     (default: BTCUSDT)
  LEVERAGE            = e.g. "10"          (default: 10)
  RISK_PCT            = e.g. "2"           (% of balance risked per trade, default: 2)
  RSI_OVERSOLD        = e.g. "30"
  RSI_OVERBOUGHT      = e.g. "70"
  POLL_SECONDS         = e.g. "60"          (how often to check, default: 60)
  MAX_DAILY_LOSS_PCT  = e.g. "5"           (circuit breaker: stop trading for the day if hit)

This is a genuinely simple strategy (single RSI signal). It is not a guarantee of
profit — treat it as a starting framework, backtest and paper-trade (testnet) before
risking real funds, and keep leverage conservative while you validate it.
"""

import os
import time
import hmac
import hashlib
import requests
import pandas as pd
import numpy as np
from urllib.parse import urlencode
from datetime import datetime, timezone

# ---------------- CONFIG (from environment) ----------------
API_KEY = os.environ.get("BINANCE_API_KEY", "")
API_SECRET = os.environ.get("BINANCE_API_SECRET", "")
USE_TESTNET = os.environ.get("USE_TESTNET", "true").lower() == "true"
SYMBOL = os.environ.get("SYMBOL", "BTCUSDT")
LEVERAGE = int(os.environ.get("LEVERAGE", "10"))
RISK_PCT = float(os.environ.get("RISK_PCT", "2"))
RSI_OVERSOLD = float(os.environ.get("RSI_OVERSOLD", "30"))
RSI_OVERBOUGHT = float(os.environ.get("RSI_OVERBOUGHT", "70"))
POLL_SECONDS = int(os.environ.get("POLL_SECONDS", "60"))
MAX_DAILY_LOSS_PCT = float(os.environ.get("MAX_DAILY_LOSS_PCT", "5"))
TP_PCT = float(os.environ.get("TP_PCT", "2"))   # take profit % from entry
SL_PCT = float(os.environ.get("SL_PCT", "1"))   # stop loss % from entry

BASE_URL = "https://testnet.binancefuture.com" if USE_TESTNET else "https://fapi.binance.com"

_day_start_balance = None
_day_start_date = None
_trading_paused = False


def log(msg):
    print(f"[{datetime.now(timezone.utc).isoformat()}] {msg}", flush=True)


def signed_request(method, path, params=None):
    if not API_KEY or not API_SECRET:
        log("ERROR: BINANCE_API_KEY / BINANCE_API_SECRET not set. Exiting.")
        raise SystemExit(1)
    params = params or {}
    params["timestamp"] = int(time.time() * 1000)
    params["recvWindow"] = 5000
    query = urlencode(params)
    signature = hmac.new(API_SECRET.encode(), query.encode(), hashlib.sha256).hexdigest()
    params["signature"] = signature
    headers = {"X-MBX-APIKEY": API_KEY}
    url = BASE_URL + path
    for attempt in range(3):
        try:
            if method == "GET":
                r = requests.get(url, headers=headers, params=params, timeout=10)
            elif method == "POST":
                r = requests.post(url, headers=headers, params=params, timeout=10)
            elif method == "DELETE":
                r = requests.delete(url, headers=headers, params=params, timeout=10)
            return r.json()
        except Exception as e:
            log(f"Request error (attempt {attempt+1}/3): {e}")
            time.sleep(2)
    return {"error": "request_failed_after_retries"}


def get_klines(symbol, interval="15m", limit=100):
    try:
        url = f"https://fapi.binance.com/fapi/v1/klines?symbol={symbol}&interval={interval}&limit={limit}"
        res = requests.get(url, timeout=5)
        if res.status_code == 200:
            df = pd.DataFrame(res.json(), columns=[
                "open_time", "open", "high", "low", "close", "volume",
                "close_time", "qav", "trades", "tbv", "tqv", "ignore"])
            df["close"] = df["close"].astype(float)
            return df
    except Exception as e:
        log(f"Kline fetch error: {e}")
    return None


def calculate_rsi(closes, period=14):
    delta = closes.diff()
    gain = delta.where(delta > 0, 0.0)
    loss = -delta.where(delta < 0, 0.0)
    avg_gain = gain.rolling(period).mean()
    avg_loss = loss.rolling(period).mean()
    rs = avg_gain / avg_loss.replace(0, np.nan)
    rsi = 100 - (100 / (1 + rs))
    return rsi.fillna(50)


def get_balance():
    data = signed_request("GET", "/fapi/v2/balance")
    if isinstance(data, list):
        for a in data:
            if a.get("asset") == "USDT":
                return float(a.get("availableBalance", 0))
    log(f"Balance fetch failed: {data}")
    return None


def get_open_position(symbol):
    data = signed_request("GET", "/fapi/v2/positionRisk", {"symbol": symbol})
    if isinstance(data, list):
        for p in data:
            if float(p.get("positionAmt", 0)) != 0:
                return p
    return None


def set_leverage(symbol, leverage):
    return signed_request("POST", "/fapi/v1/leverage", {"symbol": symbol, "leverage": leverage})


def place_market_order(symbol, side, quantity):
    return signed_request("POST", "/fapi/v1/order", {
        "symbol": symbol, "side": side, "type": "MARKET", "quantity": quantity})


def place_tp_sl(symbol, close_side, tp_price, sl_price):
    tp = signed_request("POST", "/fapi/v1/order", {
        "symbol": symbol, "side": close_side, "type": "TAKE_PROFIT_MARKET",
        "stopPrice": round(tp_price, 2), "closePosition": "true", "workingType": "MARK_PRICE"})
    sl = signed_request("POST", "/fapi/v1/order", {
        "symbol": symbol, "side": close_side, "type": "STOP_MARKET",
        "stopPrice": round(sl_price, 2), "closePosition": "true", "workingType": "MARK_PRICE"})
    return tp, sl


def calc_qty(balance, entry_price, sl_price):
    risk_amount = balance * (RISK_PCT / 100)
    sl_distance = abs(entry_price - sl_price)
    if sl_distance <= 0:
        return 0.0
    return round(risk_amount / sl_distance, 3)


def check_circuit_breaker(balance):
    """Reset baseline each UTC day; pause trading if daily loss limit is hit."""
    global _day_start_balance, _day_start_date, _trading_paused
    today = datetime.now(timezone.utc).date()
    if _day_start_date != today:
        _day_start_date = today
        _day_start_balance = balance
        _trading_paused = False
        log(f"New trading day. Starting balance: {balance}")
        return
    if _day_start_balance:
        drawdown_pct = (_day_start_balance - balance) / _day_start_balance * 100
        if drawdown_pct >= MAX_DAILY_LOSS_PCT and not _trading_paused:
            _trading_paused = True
            log(f"🛑 CIRCUIT BREAKER: daily loss {drawdown_pct:.2f}% >= {MAX_DAILY_LOSS_PCT}%. Pausing new trades until next UTC day.")


def run_once():
    global _trading_paused
    balance = get_balance()
    if balance is None:
        return
    check_circuit_breaker(balance)

    position = get_open_position(SYMBOL)
    klines = get_klines(SYMBOL)
    if klines is None:
        return
    rsi = calculate_rsi(klines["close"]).iloc[-1]
    last_price = float(klines["close"].iloc[-1])
    log(f"{SYMBOL} price={last_price:.2f} RSI={rsi:.1f} balance={balance:.2f} position={'open' if position else 'none'} paused={_trading_paused}")

    if position or _trading_paused:
        return

    side = None
    if rsi < RSI_OVERSOLD:
        side = "BUY"
    elif rsi > RSI_OVERBOUGHT:
        side = "SELL"

    if side is None:
        return

    sl_price = last_price * (1 - SL_PCT / 100) if side == "BUY" else last_price * (1 + SL_PCT / 100)
    tp_price = last_price * (1 + TP_PCT / 100) if side == "BUY" else last_price * (1 - TP_PCT / 100)
    qty = calc_qty(balance, last_price, sl_price)
    if qty <= 0:
        log("Calculated quantity is 0, skipping trade.")
        return

    set_leverage(SYMBOL, LEVERAGE)
    order = place_market_order(SYMBOL, side, qty)
    if isinstance(order, dict) and order.get("code"):
        log(f"❌ Order failed: {order}")
        return
    log(f"✅ {side} {qty} {SYMBOL} @ ~{last_price:.2f} | TP {tp_price:.2f} SL {sl_price:.2f}")

    close_side = "SELL" if side == "BUY" else "BUY"
    tp_res, sl_res = place_tp_sl(SYMBOL, close_side, tp_price, sl_price)
    log(f"TP order: {tp_res.get('status', tp_res)} | SL order: {sl_res.get('status', sl_res)}")


def main():
    log(f"Worker starting. Mode={'TESTNET' if USE_TESTNET else 'LIVE'} Symbol={SYMBOL} "
        f"Leverage={LEVERAGE}x Risk={RISK_PCT}% RSI=({RSI_OVERSOLD}/{RSI_OVERBOUGHT}) "
        f"Poll={POLL_SECONDS}s DailyLossLimit={MAX_DAILY_LOSS_PCT}%")
    if not USE_TESTNET:
        log("⚠️ LIVE MODE — real funds at risk. Make sure you validated this on testnet first.")
    while True:
        try:
            run_once()
        except SystemExit:
            raise
        except Exception as e:
            log(f"Unhandled error in loop: {e}")
        time.sleep(POLL_SECONDS)


if __name__ == "__main__":
    main()

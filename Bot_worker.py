"""
bot_worker.py
Always-on RSI-based futures trading worker. Works with Binance Futures or Bybit
(linear/USDT perpetuals) via exchanges.py.

Deploy this as a Render "Background Worker" (NOT a Web Service) — it has no UI,
it just runs a loop forever, same as a cron job that never stops.

REQUIRED environment variables (set these in Render's dashboard, never in code):
  EXCHANGE            = "Binance" or "Bybit"   (default: Binance)
  API_KEY
  API_SECRET
  USE_TESTNET         = "true" or "false"   (default: true — start here!)
  SYMBOL              = e.g. "BTCUSDT"     (default: BTCUSDT)
  LEVERAGE            = e.g. "10"          (default: 10)
  RISK_PCT            = e.g. "2"           (% of balance risked per trade, default: 2)
  RSI_OVERSOLD        = e.g. "30"
  RSI_OVERBOUGHT      = e.g. "70"
  POLL_SECONDS        = e.g. "60"          (how often to check, default: 60)
  MAX_DAILY_LOSS_PCT  = e.g. "5"           (circuit breaker: stop trading for the day if hit)
  TP_PCT / SL_PCT     = take profit / stop loss distance from entry, in %

This is a genuinely simple strategy (single RSI signal). It is not a guarantee of
profit — treat it as a starting framework, backtest and paper-trade (testnet) before
risking real funds, and keep leverage conservative while you validate it.
"""

import os
import time
from datetime import datetime, timezone
from exchanges import get_client

# ---------------- CONFIG (from environment) ----------------
EXCHANGE = os.environ.get("EXCHANGE", "Binance")
API_KEY = os.environ.get("API_KEY", "")
API_SECRET = os.environ.get("API_SECRET", "")
USE_TESTNET = os.environ.get("USE_TESTNET", "true").lower() == "true"
SYMBOL = os.environ.get("SYMBOL", "BTCUSDT")
LEVERAGE = int(os.environ.get("LEVERAGE", "10"))
RISK_PCT = float(os.environ.get("RISK_PCT", "2"))
RSI_OVERSOLD = float(os.environ.get("RSI_OVERSOLD", "30"))
RSI_OVERBOUGHT = float(os.environ.get("RSI_OVERBOUGHT", "70"))
POLL_SECONDS = int(os.environ.get("POLL_SECONDS", "60"))
MAX_DAILY_LOSS_PCT = float(os.environ.get("MAX_DAILY_LOSS_PCT", "5"))
TP_PCT = float(os.environ.get("TP_PCT", "2"))
SL_PCT = float(os.environ.get("SL_PCT", "1"))

client = get_client(EXCHANGE, API_KEY, API_SECRET, USE_TESTNET)

_day_start_balance = None
_day_start_date = None
_trading_paused = False


def log(msg):
    print(f"[{datetime.now(timezone.utc).isoformat()}] {msg}", flush=True)


def calculate_rsi(closes, period=14):
    delta = closes.diff()
    gain = delta.where(delta > 0, 0.0)
    loss = -delta.where(delta < 0, 0.0)
    avg_gain = gain.rolling(period).mean()
    avg_loss = loss.rolling(period).mean()
    rs = avg_gain / avg_loss.replace(0, float("nan"))
    rsi = 100 - (100 / (1 + rs))
    return rsi.fillna(50)


def calc_qty(balance, entry_price, sl_price):
    risk_amount = balance * (RISK_PCT / 100)
    sl_distance = abs(entry_price - sl_price)
    if sl_distance <= 0:
        return 0.0
    return round(risk_amount / sl_distance, 3)


def check_circuit_breaker(balance):
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
    balance = client.get_balance()
    if balance is None:
        log("Could not fetch balance (check API key/secret/permissions).")
        return
    check_circuit_breaker(balance)

    position = client.get_position(SYMBOL)
    klines = client.get_klines(SYMBOL, 15, 100)
    if klines is None:
        log("Could not fetch klines.")
        return
    rsi = calculate_rsi(klines["close"]).iloc[-1]
    last_price = float(klines["close"].iloc[-1])
    log(f"[{EXCHANGE}] {SYMBOL} price={last_price:.2f} RSI={rsi:.1f} balance={balance:.2f} "
        f"position={'open' if position else 'none'} paused={_trading_paused}")

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

    client.set_leverage(SYMBOL, LEVERAGE)
    order = client.place_order(SYMBOL, side, qty)
    if isinstance(order, dict) and (order.get("error") or order.get("code") not in (None, 0, "0")):
        log(f"❌ Order failed: {order}")
        return
    log(f"✅ {side} {qty} {SYMBOL} @ ~{last_price:.2f} | TP {tp_price:.2f} SL {sl_price:.2f}")

    close_side = "SELL" if side == "BUY" else "BUY"
    tp_res, sl_res = client.place_tp_sl(SYMBOL, close_side, tp_price, sl_price)
    log(f"TP/SL attached: {tp_res}")


def main():
    log(f"Worker starting. Exchange={EXCHANGE} Mode={'TESTNET' if USE_TESTNET else 'LIVE'} Symbol={SYMBOL} "
        f"Leverage={LEVERAGE}x Risk={RISK_PCT}% RSI=({RSI_OVERSOLD}/{RSI_OVERBOUGHT}) "
        f"Poll={POLL_SECONDS}s DailyLossLimit={MAX_DAILY_LOSS_PCT}%")
    if not API_KEY or not API_SECRET:
        log("ERROR: API_KEY / API_SECRET not set. Exiting.")
        raise SystemExit(1)
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

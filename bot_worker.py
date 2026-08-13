"""
bot_worker.py

Autonomous futures trading worker.

Flow:
Market Data
    ↓
Signal Engine
    ↓
Risk Manager
    ↓
Trade Executor
    ↓
Automatic TP / SL

IMPORTANT:
This worker is locked to TESTNET through TradeExecutor.
Do not use real funds until the complete system has been
properly tested and validated.
"""

import os
import time
from datetime import datetime, timezone

from exchanges import get_client
from market_data import get_candles
from signal_engine import generate_signal
from trade_executor import TradeExecutor


# ============================================================
# CONFIGURATION
# ============================================================

EXCHANGE = os.environ.get("EXCHANGE", "Binance")

API_KEY = os.environ.get("API_KEY", "")
API_SECRET = os.environ.get("API_SECRET", "")

USE_TESTNET = (
    os.environ.get("USE_TESTNET", "true").lower() == "true"
)

SYMBOL = os.environ.get("SYMBOL", "BTCUSDT")

LEVERAGE = int(
    os.environ.get("LEVERAGE", "5")
)

RISK_PCT = float(
    os.environ.get("RISK_PCT", "1")
)

SL_PCT = float(
    os.environ.get("SL_PCT", "1")
)

TP_PCT = float(
    os.environ.get("TP_PCT", "2")
)

POLL_SECONDS = int(
    os.environ.get("POLL_SECONDS", "60")
)

MAX_DAILY_LOSS_PCT = float(
    os.environ.get("MAX_DAILY_LOSS_PCT", "5")
)


# ============================================================
# DAILY RISK STATE
# ============================================================

_day_start_balance = None
_day_start_date = None
_trading_paused = False


# ============================================================
# LOGGING
# ============================================================

def log(message):
    timestamp = datetime.now(
        timezone.utc
    ).isoformat()

    print(
        f"[{timestamp}] {message}",
        flush=True
    )


# ============================================================
# CIRCUIT BREAKER
# ============================================================

def check_circuit_breaker(balance):
    global _day_start_balance
    global _day_start_date
    global _trading_paused

    today = datetime.now(
        timezone.utc
    ).date()

    # New trading day
    if _day_start_date != today:

        _day_start_date = today
        _day_start_balance = balance
        _trading_paused = False

        log(
            f"New trading day. "
            f"Starting balance: {balance:.2f}"
        )

        return

    if (
        _day_start_balance is not None
        and _day_start_balance > 0
    ):

        drawdown_pct = (
            (_day_start_balance - balance)
            / _day_start_balance
            * 100
        )

        if (
            drawdown_pct >= MAX_DAILY_LOSS_PCT
            and not _trading_paused
        ):

            _trading_paused = True

            log(
                "CIRCUIT BREAKER ACTIVATED: "
                f"daily loss {drawdown_pct:.2f}% "
                f">= {MAX_DAILY_LOSS_PCT}%"
            )


# ============================================================
# MAIN TRADING CYCLE
# ============================================================

def run_once():

    global _trading_paused

    # --------------------------------------------------------
    # Balance
    # --------------------------------------------------------

    balance = client.get_balance()

    if balance is None:

        log(
            "Could not fetch balance. "
            "Check API credentials and permissions."
        )

        return

    # --------------------------------------------------------
    # Daily risk protection
    # --------------------------------------------------------

    check_circuit_breaker(balance)

    if _trading_paused:

        log(
            "Trading paused by daily loss circuit breaker."
        )

        return

    # --------------------------------------------------------
    # Existing position check
    # --------------------------------------------------------

    position = client.get_position(
        SYMBOL
    )

    if position:

        log(
            f"Existing position detected: "
            f"{position}"
        )

        return

    # --------------------------------------------------------
    # Market candles
    # --------------------------------------------------------

    candles = get_candles(
        exchange=EXCHANGE,
        symbol=SYMBOL,
        timeframe_minutes=15,
        limit=100,
        api_key=API_KEY,
        api_secret=API_SECRET,
        use_testnet=USE_TESTNET,
    )

    if candles is None:

        log(
            "Could not fetch market candles."
        )

        return

    if len(candles) < 50:

        log(
            "Not enough candles for signal analysis."
        )

        return

    # --------------------------------------------------------
    # Signal engine
    # --------------------------------------------------------

    signal_data = generate_signal(
        candles
    )

    signal = signal_data.get(
        "signal",
        "NO TRADE"
    )

    score = signal_data.get(
        "score",
        0
    )

    price = signal_data.get(
        "price"
    )

    rsi = signal_data.get(
        "rsi"
    )

    log(
        f"[{EXCHANGE}] "
        f"{SYMBOL} "
        f"price={price} "
        f"signal={signal} "
        f"score={score} "
        f"RSI={rsi}"
    )

    # --------------------------------------------------------
    # No signal
    # --------------------------------------------------------

    if signal == "NO TRADE":

        log(
            "No strong trading signal. "
            "Waiting..."
        )

        return

    # --------------------------------------------------------
    # Create autonomous executor
    # --------------------------------------------------------

    executor = TradeExecutor(
        exchange=EXCHANGE,
        api_key=API_KEY,
        api_secret=API_SECRET,
        use_testnet=USE_TESTNET,
    )

    # --------------------------------------------------------
    # Create risk-managed trade plan
    # --------------------------------------------------------

    plan = executor.create_trade_plan(
        balance=balance,
        entry_price=price,
        signal=signal,
        risk_percent=RISK_PCT,
        stop_loss_percent=SL_PCT,
        take_profit_percent=TP_PCT,
    )

    if plan.get("action") != "TRADE":

        log(
            f"Trade rejected by risk manager: "
            f"{plan}"
        )

        return

    log(
        f"TRADE PLAN: "
        f"side={plan['side']} "
        f"quantity={plan['quantity']:.6f} "
        f"entry={plan['entry_price']:.4f} "
        f"TP={plan['take_profit']:.4f} "
        f"SL={plan['stop_loss']:.4f}"
    )

    # --------------------------------------------------------
    # Autonomous execution
    # --------------------------------------------------------

    result = executor.execute(
        symbol=SYMBOL,
        balance=balance,
        entry_price=price,
        signal=signal,
        risk_percent=RISK_PCT,
        stop_loss_percent=SL_PCT,
        take_profit_percent=TP_PCT,
    )

    # --------------------------------------------------------
    # Result
    # --------------------------------------------------------

    status = result.get(
        "status",
        "UNKNOWN"
    )

    if status == "EXECUTED":

        log(
            "AUTONOMOUS TRADE EXECUTED"
        )

        log(
            f"Side={result.get('side')} "
            f"Quantity={result.get('quantity')} "
            f"Entry={result.get('entry')} "
            f"TP={result.get('take_profit')} "
            f"SL={result.get('stop_loss')}"
        )

    elif status == "SKIPPED":

        log(
            f"Trade skipped: "
            f"{result.get('reason')}"
        )

    else:

        log(
            f"Trade execution error: "
            f"{result}"
        )


# ============================================================
# START WORKER
# ============================================================

def main():

    log(
        "========================================"
    )

    log(
        "AUTONOMOUS FUTURES BOT STARTING"
    )

    log(
        f"Exchange: {EXCHANGE}"
    )

    log(
        f"Symbol: {SYMBOL}"
    )

    log(
        f"Mode: "
        f"{'TESTNET' if USE_TESTNET else 'LIVE'}"
    )

    log(
        f"Leverage: {LEVERAGE}x"
    )

    log(
        f"Risk: {RISK_PCT}%"
    )

    log(
        f"TP: {TP_PCT}%"
    )

    log(
        f"SL: {SL_PCT}%"
    )

    log(
        f"Polling: {POLL_SECONDS}s"
    )

    log(
        "========================================"
    )

    # --------------------------------------------------------
    # Credentials
    # --------------------------------------------------------

    if not API_KEY or not API_SECRET:

        log(
            "ERROR: API_KEY / API_SECRET "
            "are not configured."
        )

        raise SystemExit(1)

    # --------------------------------------------------------
    # Safety
    # --------------------------------------------------------

    if not USE_TESTNET:

        log(
            "SAFETY ERROR: "
            "This autonomous worker requires "
            "USE_TESTNET=true."
        )

        raise SystemExit(1)

    # --------------------------------------------------------
    # Exchange client
    # --------------------------------------------------------

    global client

    client = get_client(
        EXCHANGE,
        API_KEY,
        API_SECRET,
        USE_TESTNET,
    )

    log(
        "Exchange connection initialized."
    )

    # --------------------------------------------------------
    # Continuous loop
    # --------------------------------------------------------

    while True:

        try:

            run_once()

        except KeyboardInterrupt:

            log(
                "Worker stopped."
            )

            break

        except Exception as error:

            log(
                f"Unhandled worker error: "
                f"{error}"
            )

        time.sleep(
            POLL_SECONDS
        )


# ============================================================
# ENTRY POINT
# ============================================================

if __name__ == "__main__":
    main()

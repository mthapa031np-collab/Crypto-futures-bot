"""
bot_worker.py

Autonomous PAPER TRADING worker.

Flow:
Market Data
    ↓
Signal Engine
    ↓
Risk Manager
    ↓
Paper Trader
    ↓
Automatic simulated TP / SL

IMPORTANT:
This version does NOT send real orders to Binance or Bybit.
"""

import os
import time
from datetime import datetime, timezone

from market_data import get_candles
from signal_engine import generate_signal
from risk_manager import calculate_trade_plan, validate_trade_plan
from paper_trader import PaperTrader


# ============================================================
# CONFIGURATION
# ============================================================

EXCHANGE = os.environ.get("EXCHANGE", "Bybit")

SYMBOL = os.environ.get("SYMBOL", "BTCUSDT")

PAPER_TRADING = (
    os.environ.get("PAPER_TRADING", "true").lower() == "true"
)

PAPER_BALANCE = float(
    os.environ.get("PAPER_BALANCE", "10000")
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
# SAFETY
# ============================================================

if not PAPER_TRADING:
    raise RuntimeError(
        "Safety lock: this worker currently supports "
        "PAPER_TRADING=true only."
    )


# ============================================================
# PAPER TRADER
# ============================================================

paper = PaperTrader(
    starting_balance=PAPER_BALANCE
)


# ============================================================
# DAILY RISK STATE
# ============================================================

_day_start_balance = PAPER_BALANCE
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
# DAILY CIRCUIT BREAKER
# ============================================================

def check_circuit_breaker(balance):
    global _day_start_balance
    global _day_start_date
    global _trading_paused

    today = datetime.now(
        timezone.utc
    ).date()

    if _day_start_date != today:

        _day_start_date = today
        _day_start_balance = balance
        _trading_paused = False

        log(
            f"New trading day. "
            f"Starting paper balance: {balance:.2f}"
        )

        return

    if _day_start_balance <= 0:
        return

    drawdown_pct = (
        (_day_start_balance - balance)
        / _day_start_balance
        * 100
    )

    if drawdown_pct >= MAX_DAILY_LOSS_PCT:

        if not _trading_paused:

            _trading_paused = True

            log(
                "CIRCUIT BREAKER ACTIVATED | "
                f"Daily loss={drawdown_pct:.2f}%"
            )


# ============================================================
# MARKET DATA
# ============================================================

def get_market_candles():

    return get_candles(
        exchange=EXCHANGE,
        symbol=SYMBOL,
        timeframe_minutes=15,
        limit=100,

        # No private API credentials required
        # for public market-data requests.
        api_key="",
        api_secret="",

        # Use public exchange market data.
        use_testnet=False,
    )


# ============================================================
# MAIN TRADING CYCLE
# ============================================================

def run_once():

    global _trading_paused

    balance = paper.get_balance()

    check_circuit_breaker(balance)

    # --------------------------------------------------------
    # Market candles
    # --------------------------------------------------------

    candles = get_market_candles()

    if candles is None:

        log(
            "Could not fetch market candles."
        )

        return

    if len(candles) < 50:

        log(
            "Not enough candles for analysis."
        )

        return

    current_price = float(
        candles["close"].iloc[-1]
    )

    # --------------------------------------------------------
    # Monitor currently open PAPER position
    # --------------------------------------------------------

    existing_position = paper.get_position()

    if existing_position:

        result = paper.update_price(
            current_price
        )

        if result:

            status = result.get("status")

            if status == "CLOSED":

                log(
                    "PAPER TRADE CLOSED | "
                    f"Side={result.get('side')} | "
                    f"Entry={result.get('entry_price'):.4f} | "
                    f"Exit={result.get('exit_price'):.4f} | "
                    f"PnL={result.get('pnl'):.2f} | "
                    f"Reason={result.get('reason')} | "
                    f"Balance={result.get('balance'):.2f}"
                )

            else:

                log(
                    "PAPER POSITION OPEN | "
                    f"{existing_position['side']} | "
                    f"Entry={existing_position['entry_price']:.4f} | "
                    f"Current={current_price:.4f} | "
                    f"TP={existing_position['take_profit']:.4f} | "
                    f"SL={existing_position['stop_loss']:.4f}"
                )

        return

    # --------------------------------------------------------
    # Stop new trades if daily loss breaker is active
    # --------------------------------------------------------

    if _trading_paused:

        log(
            "Paper trading paused by daily loss limit."
        )

        return

    # --------------------------------------------------------
    # Generate trading signal
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

    rsi = signal_data.get(
        "rsi",
        0
    )

    reason = signal_data.get(
        "reason",
        ""
    )

    log(
        f"[PAPER] [{EXCHANGE}] "
        f"{SYMBOL} | "
        f"Price={current_price:.4f} | "
        f"Signal={signal} | "
        f"Score={score} | "
        f"RSI={rsi:.2f} | "
        f"Balance={balance:.2f}"
    )

    log(
        f"Signal reason: {reason}"
    )

    if signal not in (
        "BUY",
        "SELL",
    ):

        log(
            "No strong signal. Waiting..."
        )

        return

    # --------------------------------------------------------
    # Risk management
    # --------------------------------------------------------

    plan = calculate_trade_plan(
        balance=balance,
        entry_price=current_price,
        signal=signal,
        risk_percent=RISK_PCT,
        stop_loss_percent=SL_PCT,
        take_profit_percent=TP_PCT,
    )

    if not validate_trade_plan(plan):

        log(
            f"Trade plan rejected: {plan}"
        )

        return

    # --------------------------------------------------------
    # Open PAPER trade
    # --------------------------------------------------------

    result = paper.open_trade(
        symbol=SYMBOL,
        signal=signal,
        entry_price=current_price,
        quantity=plan["quantity"],
        take_profit=plan["take_profit"],
        stop_loss=plan["stop_loss"],
    )

    if result.get("status") == "EXECUTED":

        position = result["position"]

        log(
            "PAPER TRADE OPENED | "
            f"{position['side']} | "
            f"{SYMBOL} | "
            f"Entry={position['entry_price']:.4f} | "
            f"Qty={position['quantity']:.6f} | "
            f"TP={position['take_profit']:.4f} | "
            f"SL={position['stop_loss']:.4f}"
        )

    else:

        log(
            f"Paper trade skipped: {result}"
        )


# ============================================================
# WORKER START
# ============================================================

def main():

    log(
        "========================================"
    )

    log(
        "AUTONOMOUS PAPER TRADING BOT STARTING"
    )

    log(
        f"Exchange market data: {EXCHANGE}"
    )

    log(
        f"Symbol: {SYMBOL}"
    )

    log(
        f"Starting paper balance: "
        f"{PAPER_BALANCE:.2f} USDT"
    )

    log(
        f"Risk per trade: {RISK_PCT}%"
    )

    log(
        f"Take Profit: {TP_PCT}%"
    )

    log(
        f"Stop Loss: {SL_PCT}%"
    )

    log(
        f"Polling interval: "
        f"{POLL_SECONDS} seconds"
    )

    log(
        "REAL ORDERS: DISABLED"
    )

    log(
        "========================================"
    )

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


if __name__ == "__main__":
    main()

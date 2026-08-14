"""
bot_worker.py

MULTI-MARKET AUTONOMOUS PAPER TRADING WORKER

Scans:
    BTCUSDT
    ETHUSDT
    SOLUSDT
    XRPUSDT
    ADAUSDT
    DOGEUSDT
    AVAXUSDT
    LINKUSDT
    DOTUSDT
    NEARUSDT
    SUIUSDT

Flow:
    Scan all markets
        ↓
    Signal engine
        ↓
    Rank confirmed BUY/SELL setups
        ↓
    Select strongest setup
        ↓
    Risk manager
        ↓
    Paper trade
        ↓
    Automatic simulated TP / SL

IMPORTANT:
- PAPER TRADING ONLY
- NO REAL ORDERS
- Public UK-compatible market data
- One open position at a time with the current PaperTrader
"""

import os
import time
from datetime import datetime, timezone

from market_data import get_candles
from signal_engine import generate_signal
from risk_manager import (
    calculate_trade_plan,
    validate_trade_plan,
)
from paper_trader import PaperTrader


# ============================================================
# CONFIG
# ============================================================

PAPER_TRADING = (
    os.environ.get(
        "PAPER_TRADING",
        "true",
    ).lower()
    == "true"
)

PAPER_BALANCE = float(
    os.environ.get(
        "PAPER_BALANCE",
        "10000",
    )
)

RISK_PCT = float(
    os.environ.get(
        "RISK_PCT",
        "1",
    )
)

SL_PCT = float(
    os.environ.get(
        "SL_PCT",
        "1",
    )
)

TP_PCT = float(
    os.environ.get(
        "TP_PCT",
        "2",
    )
)

POLL_SECONDS = int(
    os.environ.get(
        "POLL_SECONDS",
        "60",
    )
)

MAX_DAILY_LOSS_PCT = float(
    os.environ.get(
        "MAX_DAILY_LOSS_PCT",
        "5",
    )
)

TIMEFRAME_MINUTES = int(
    os.environ.get(
        "TIMEFRAME_MINUTES",
        "15",
    )
)

CANDLE_LIMIT = int(
    os.environ.get(
        "CANDLE_LIMIT",
        "100",
    )
)


# ============================================================
# MARKETS
# ============================================================

DEFAULT_MARKETS = [
    "BTCUSDT",
    "ETHUSDT",
    "SOLUSDT",
    "XRPUSDT",
    "ADAUSDT",
    "DOGEUSDT",
    "AVAXUSDT",
    "LINKUSDT",
    "DOTUSDT",
    "NEARUSDT",
    "SUIUSDT",
]


raw_symbols = os.environ.get(
    "SYMBOLS",
    "",
).strip()


if raw_symbols:

    MARKETS = [
        symbol.strip().upper()
        for symbol in raw_symbols.split(",")
        if symbol.strip()
    ]

else:

    MARKETS = DEFAULT_MARKETS


# ============================================================
# SAFETY LOCK
# ============================================================

if not PAPER_TRADING:

    raise RuntimeError(
        "Safety lock: this worker supports "
        "PAPER_TRADING=true only."
    )


# ============================================================
# PAPER ACCOUNT
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

    now = datetime.now(
        timezone.utc
    ).isoformat()

    print(
        f"[{now}] {message}",
        flush=True,
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
            "NEW TRADING DAY | "
            f"Starting balance="
            f"{balance:.2f}"
        )

        return

    if _day_start_balance <= 0:

        return

    drawdown_pct = (
        (
            _day_start_balance
            - balance
        )
        / _day_start_balance
        * 100
    )

    if (
        drawdown_pct
        >= MAX_DAILY_LOSS_PCT
    ):

        if not _trading_paused:

            _trading_paused = True

            log(
                "CIRCUIT BREAKER | "
                f"Daily loss="
                f"{drawdown_pct:.2f}% | "
                "New trades paused."
            )


# ============================================================
# MARKET DATA
# ============================================================

def get_market_candles(symbol):

    return get_candles(
        exchange="PUBLIC",
        symbol=symbol,
        timeframe_minutes=TIMEFRAME_MINUTES,
        limit=CANDLE_LIMIT,
        api_key="",
        api_secret="",
        use_testnet=False,
    )


# ============================================================
# SCAN ONE MARKET
# ============================================================

def analyse_market(symbol):

    try:

        candles = get_market_candles(
            symbol
        )

        if candles is None:

            return {
                "symbol": symbol,
                "valid": False,
                "reason": (
                    "No market data"
                ),
            }

        if len(candles) < 50:

            return {
                "symbol": symbol,
                "valid": False,
                "reason": (
                    "Not enough candles"
                ),
            }

        current_price = float(
            candles["close"].iloc[-1]
        )

        signal_data = generate_signal(
            candles
        )

        signal = signal_data.get(
            "signal",
            "NO TRADE",
        )

        score = signal_data.get(
            "score",
            0,
        )

        rsi = signal_data.get(
            "rsi",
            None,
        )

        macd = signal_data.get(
            "macd",
            None,
        )

        reason = signal_data.get(
            "reason",
            "",
        )

        return {
            "symbol": symbol,
            "valid": True,
            "price": current_price,
            "signal": signal,
            "score": score,
            "rsi": rsi,
            "macd": macd,
            "reason": reason,
        }

    except Exception as error:

        return {
            "symbol": symbol,
            "valid": False,
            "reason": str(error),
        }


# ============================================================
# SCAN ALL MARKETS
# ============================================================

def scan_all_markets():

    results = []

    log(
        "========================================"
    )

    log(
        f"SCANNING {len(MARKETS)} MARKETS"
    )

    log(
        "========================================"
    )

    for symbol in MARKETS:

        result = analyse_market(
            symbol
        )

        results.append(
            result
        )

        if not result.get(
            "valid"
        ):

            log(
                f"{symbol} | "
                f"DATA ERROR | "
                f"{result.get('reason')}"
            )

            continue

        rsi = result.get(
            "rsi"
        )

        rsi_text = (
            f"{float(rsi):.1f}"
            if rsi is not None
            else "N/A"
        )

        log(
            f"{symbol} | "
            f"Price="
            f"{result['price']:.4f} | "
            f"Signal="
            f"{result['signal']} | "
            f"Score="
            f"{result['score']} | "
            f"RSI="
            f"{rsi_text} | "
            f"{result['reason']}"
        )

    return results


# ============================================================
# SELECT STRONGEST CONFIRMED SIGNAL
# ============================================================

def select_best_setup(results):

    confirmed = []

    for result in results:

        if not result.get(
            "valid"
        ):

            continue

        signal = result.get(
            "signal"
        )

        if signal not in (
            "BUY",
            "SELL",
        ):

            continue

        try:

            score = float(
                result.get(
                    "score",
                    0,
                )
            )

        except Exception:

            score = 0.0

        result[
            "absolute_score"
        ] = abs(
            score
        )

        confirmed.append(
            result
        )

    if not confirmed:

        return None

    confirmed.sort(
        key=lambda item: (
            item[
                "absolute_score"
            ]
        ),
        reverse=True,
    )

    return confirmed[0]


# ============================================================
# MONITOR CURRENT POSITION
# ============================================================

def monitor_position():

    position = paper.get_position()

    if not position:

        return False

    symbol = position.get(
        "symbol"
    )

    if not symbol:

        log(
            "Open position has no symbol."
        )

        return True

    candles = get_market_candles(
        symbol
    )

    if (
        candles is None
        or len(candles) == 0
    ):

        log(
            f"{symbol} | "
            "Could not update "
            "open position price."
        )

        return True

    current_price = float(
        candles["close"].iloc[-1]
    )

    result = paper.update_price(
        current_price
    )

    if (
        result
        and result.get(
            "status"
        )
        == "CLOSED"
    ):

        log(
            "PAPER TRADE CLOSED | "
            f"Symbol="
            f"{symbol} | "
            f"Side="
            f"{result.get('side')} | "
            f"Entry="
            f"{result.get('entry_price')} | "
            f"Exit="
            f"{result.get('exit_price')} | "
            f"PnL="
            f"{result.get('pnl')} | "
            f"Reason="
            f"{result.get('reason')} | "
            f"Balance="
            f"{result.get('balance')}"
        )

        return False

    current_position = (
        paper.get_position()
    )

    if current_position:

        log(
            "POSITION OPEN | "
            f"{symbol} | "
            f"Side="
            f"{current_position.get('side')} | "
            f"Entry="
            f"{current_position.get('entry_price')} | "
            f"Current="
            f"{current_price:.4f} | "
            f"TP="
            f"{current_position.get('take_profit')} | "
            f"SL="
            f"{current_position.get('stop_loss')}"
        )

    return True


# ============================================================
# OPEN BEST PAPER TRADE
# ============================================================

def open_best_trade(
    setup,
    balance,
):

    symbol = setup[
        "symbol"
    ]

    signal = setup[
        "signal"
    ]

    entry_price = float(
        setup[
            "price"
        ]
    )

    score = setup.get(
        "score",
        0,
    )

    log(
        "BEST SETUP FOUND | "
        f"{symbol} | "
        f"Signal="
        f"{signal} | "
        f"Score="
        f"{score} | "
        f"Price="
        f"{entry_price:.4f}"
    )

    plan = calculate_trade_plan(
        balance=balance,
        entry_price=entry_price,
        signal=signal,
        risk_percent=RISK_PCT,
        stop_loss_percent=SL_PCT,
        take_profit_percent=TP_PCT,
    )

    if not validate_trade_plan(
        plan
    ):

        log(
            "TRADE REJECTED BY "
            "RISK MANAGER | "
            f"{symbol} | "
            f"{plan}"
        )

        return

    result = paper.open_trade(
        symbol=symbol,
        signal=signal,
        entry_price=entry_price,
        quantity=plan[
            "quantity"
        ],
        take_profit=plan[
            "take_profit"
        ],
        stop_loss=plan[
            "stop_loss"
        ],
    )

    if (
        result.get(
            "status"
        )
        == "EXECUTED"
    ):

        position = result[
            "position"
        ]

        log(
            "PAPER TRADE OPENED | "
            f"{symbol} | "
            f"Side="
            f"{position['side']} | "
            f"Entry="
            f"{position['entry_price']:.4f} | "
            f"Qty="
            f"{position['quantity']:.6f} | "
            f"TP="
            f"{position['take_profit']:.4f} | "
            f"SL="
            f"{position['stop_loss']:.4f} | "
            f"Score="
            f"{score}"
        )

    else:

        log(
            "PAPER TRADE SKIPPED | "
            f"{symbol} | "
            f"{result}"
        )


# ============================================================
# ONE FULL TRADING CYCLE
# ============================================================

def run_once():

    global _trading_paused

    balance = paper.get_balance()

    check_circuit_breaker(
        balance
    )

    # --------------------------------------------------------
    # FIRST MANAGE EXISTING TRADE
    # --------------------------------------------------------

    if paper.get_position():

        monitor_position()

        return

    # --------------------------------------------------------
    # DAILY LOSS PROTECTION
    # --------------------------------------------------------

    if _trading_paused:

        log(
            "Trading paused by "
            "daily loss circuit breaker."
        )

        return

    # --------------------------------------------------------
    # SCAN ALL MARKETS
    # --------------------------------------------------------

    results = scan_all_markets()

    # --------------------------------------------------------
    # SELECT BEST CONFIRMED SETUP
    # --------------------------------------------------------

    best_setup = (
        select_best_setup(
            results
        )
    )

    if best_setup is None:

        log(
            "NO QUALIFYING TRADE | "
            "All markets scanned."
        )

        return

    # --------------------------------------------------------
    # OPEN STRONGEST PAPER SETUP
    # --------------------------------------------------------

    open_best_trade(
        best_setup,
        balance,
    )


# ============================================================
# MAIN WORKER
# ============================================================

def main():

    log(
        "========================================"
    )

    log(
        "PRO AI MULTI-MARKET "
        "PAPER BOT STARTING"
    )

    log(
        "========================================"
    )

    log(
        f"Markets: "
        f"{', '.join(MARKETS)}"
    )

    log(
        f"Total markets: "
        f"{len(MARKETS)}"
    )

    log(
        f"Timeframe: "
        f"{TIMEFRAME_MINUTES}m"
    )

    log(
        f"Starting balance: "
        f"${PAPER_BALANCE:.2f}"
    )

    log(
        f"Risk per trade: "
        f"{RISK_PCT}%"
    )

    log(
        f"Take Profit: "
        f"{TP_PCT}%"
    )

    log(
        f"Stop Loss: "
        f"{SL_PCT}%"
    )

    log(
        f"Daily loss limit: "
        f"{MAX_DAILY_LOSS_PCT}%"
    )

    log(
        f"Scan interval: "
        f"{POLL_SECONDS}s"
    )

    log(
        "MAX OPEN POSITIONS: 1"
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
                "UNHANDLED WORKER ERROR | "
                f"{error}"
            )

        time.sleep(
            POLL_SECONDS
        )


if __name__ == "__main__":

    main()

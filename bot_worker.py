"""
bot_worker.py

DYNAMIC COINBASE MULTI-MARKET PAPER TRADING WORKER

What it does:
- Discovers Coinbase Exchange spot products dynamically
- Keeps USD / USDC quote markets
- Rejects disabled / cancel-only / post-only markets
- Filters by liquidity and spread
- Keeps only the most liquid eligible markets
- Fetches 15m candles
- Runs signal_engine.py
- Ranks confirmed BUY / SELL setups
- Opens the strongest setup
- Uses PostgreSQL-backed PaperTrader
- Automatic simulated TP / SL
- One open paper position at a time

IMPORTANT:
PAPER TRADING ONLY.
NO REAL ORDERS.
"""

import os
import time
from datetime import datetime, timezone

import requests

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

COINBASE_API = "https://api.exchange.coinbase.com"

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

MAX_SCAN_MARKETS = int(
    os.environ.get(
        "MAX_SCAN_MARKETS",
        "40",
    )
)

MIN_QUOTE_VOLUME_USD = float(
    os.environ.get(
        "MIN_QUOTE_VOLUME_USD",
        "5000000",
    )
)

MAX_SPREAD_PCT = float(
    os.environ.get(
        "MAX_SPREAD_PCT",
        "0.35",
    )
)

MARKET_REFRESH_MINUTES = int(
    os.environ.get(
        "MARKET_REFRESH_MINUTES",
        "30",
    )
)


# ============================================================
# SAFETY
# ============================================================

if not PAPER_TRADING:
    raise RuntimeError(
        "Safety lock: PAPER_TRADING=true is required."
    )


# ============================================================
# PAPER ACCOUNT
# ============================================================

paper = PaperTrader(
    starting_balance=PAPER_BALANCE
)


# ============================================================
# DAILY STATE
# ============================================================

_day_start_balance = PAPER_BALANCE
_day_start_date = None
_trading_paused = False

_cached_markets = []
_cached_markets_at = 0.0


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
# HTTP HELPER
# ============================================================

def coinbase_get(
    path,
    params=None,
    timeout=12,
):

    url = (
        COINBASE_API
        + path
    )

    response = requests.get(
        url,
        params=params,
        timeout=timeout,
        headers={
            "Accept": "application/json",
            "User-Agent": (
                "pro-ai-paper-scanner/1.0"
            ),
        },
    )

    response.raise_for_status()

    return response.json()


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

        _day_start_balance = (
            balance
        )

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
                f"{drawdown_pct:.2f}%"
            )


# ============================================================
# PRODUCT DISCOVERY
# ============================================================

def get_coinbase_products():

    products = coinbase_get(
        "/products"
    )

    if not isinstance(
        products,
        list,
    ):
        return []

    return products


def product_is_allowed(product):

    if not isinstance(
        product,
        dict,
    ):
        return False

    product_id = str(
        product.get(
            "id",
            "",
        )
    ).upper()

    quote = str(
        product.get(
            "quote_currency",
            "",
        )
    ).upper()

    if not product_id:
        return False

    # Use only USD / USDC quote markets.
    if quote not in (
        "USD",
        "USDC",
    ):
        return False

    # Skip restricted markets.
    if product.get(
        "trading_disabled",
        False,
    ):
        return False

    if product.get(
        "cancel_only",
        False,
    ):
        return False

    if product.get(
        "post_only",
        False,
    ):
        return False

    # Remove fiat-to-fiat markets.
    base = str(
        product.get(
            "base_currency",
            "",
        )
    ).upper()

    fiat_like = {
        "USD",
        "USDC",
        "USDT",
        "EUR",
        "GBP",
        "CAD",
        "AUD",
    }

    if base in fiat_like:
        return False

    return True


# ============================================================
# MARKET QUALITY
# ============================================================

def get_market_snapshot(
    product_id,
):

    try:

        ticker = coinbase_get(
            f"/products/{product_id}/ticker"
        )

        stats = coinbase_get(
            f"/products/{product_id}/stats"
        )

        last = float(
            ticker.get(
                "price",
                0,
            )
            or 0
        )

        bid = float(
            ticker.get(
                "bid",
                0,
            )
            or 0
        )

        ask = float(
            ticker.get(
                "ask",
                0,
            )
            or 0
        )

        base_volume = float(
            stats.get(
                "volume",
                0,
            )
            or 0
        )

        if last <= 0:
            return None

        # Approximate quote/USD volume.
        quote_volume = (
            base_volume
            * last
        )

        spread_pct = 999.0

        if (
            bid > 0
            and ask > 0
            and ask >= bid
        ):

            midpoint = (
                bid + ask
            ) / 2

            if midpoint > 0:

                spread_pct = (
                    (ask - bid)
                    / midpoint
                    * 100
                )

        return {
            "product_id": product_id,
            "last": last,
            "bid": bid,
            "ask": ask,
            "quote_volume": (
                quote_volume
            ),
            "spread_pct": (
                spread_pct
            ),
        }

    except Exception as error:

        log(
            f"{product_id} | "
            f"Snapshot error | "
            f"{error}"
        )

        return None


# ============================================================
# DISCOVER TOP LIQUID MARKETS
# ============================================================

def discover_markets():

    global _cached_markets
    global _cached_markets_at

    now = time.time()

    cache_age = (
        now
        - _cached_markets_at
    )

    max_age = (
        MARKET_REFRESH_MINUTES
        * 60
    )

    if (
        _cached_markets
        and cache_age < max_age
    ):

        return list(
            _cached_markets
        )

    log(
        "DISCOVERING COINBASE MARKETS"
    )

    products = (
        get_coinbase_products()
    )

    eligible_products = [
        product
        for product in products
        if product_is_allowed(
            product
        )
    ]

    log(
        f"Coinbase products="
        f"{len(products)} | "
        f"Eligible="
        f"{len(eligible_products)}"
    )

    quality_markets = []

    for product in eligible_products:

        product_id = (
            product["id"]
        )

        snapshot = (
            get_market_snapshot(
                product_id
            )
        )

        if snapshot is None:
            continue

        if (
            snapshot[
                "quote_volume"
            ]
            < MIN_QUOTE_VOLUME_USD
        ):
            continue

        if (
            snapshot[
                "spread_pct"
            ]
            > MAX_SPREAD_PCT
        ):
            continue

        quality_markets.append(
            snapshot
        )

    quality_markets.sort(
        key=lambda item: (
            item[
                "quote_volume"
            ]
        ),
        reverse=True,
    )

    quality_markets = (
        quality_markets[
            :MAX_SCAN_MARKETS
        ]
    )

    _cached_markets = [
        market[
            "product_id"
        ]
        for market
        in quality_markets
    ]

    _cached_markets_at = now

    log(
        "QUALITY MARKET UNIVERSE | "
        f"{len(_cached_markets)} markets"
    )

    for market in quality_markets:

        log(
            f"{market['product_id']} | "
            f"24hApproxUSD="
            f"{market['quote_volume']:,.0f} | "
            f"Spread="
            f"{market['spread_pct']:.4f}%"
        )

    return list(
        _cached_markets
    )


# ============================================================
# COINBASE PRODUCT -> EXISTING SYMBOL FORMAT
# ============================================================

def product_to_symbol(
    product_id,
):

    product_id = str(
        product_id
    ).upper()

    if "-" not in product_id:
        return None

    base, quote = (
        product_id.split(
            "-",
            1,
        )
    )

    # market_data.py currently maps
    # BTCUSDT -> BTC-USD, etc.
    if quote in (
        "USD",
        "USDC",
    ):

        return (
            f"{base}USDT"
        )

    return None


# ============================================================
# CANDLES
# ============================================================

def get_market_candles(
    symbol,
):

    return get_candles(
        exchange="PUBLIC",
        symbol=symbol,
        timeframe_minutes=(
            TIMEFRAME_MINUTES
        ),
        limit=CANDLE_LIMIT,
        api_key="",
        api_secret="",
        use_testnet=False,
    )


# ============================================================
# ANALYSE MARKET
# ============================================================

def analyse_market(
    product_id,
):

    symbol = product_to_symbol(
        product_id
    )

    if not symbol:

        return {
            "product_id": product_id,
            "valid": False,
            "reason": (
                "Unsupported symbol mapping"
            ),
        }

    try:

        candles = (
            get_market_candles(
                symbol
            )
        )

        if candles is None:

            return {
                "product_id": (
                    product_id
                ),
                "symbol": symbol,
                "valid": False,
                "reason": (
                    "No candles"
                ),
            }

        if len(candles) < 50:

            return {
                "product_id": (
                    product_id
                ),
                "symbol": symbol,
                "valid": False,
                "reason": (
                    "Not enough candles"
                ),
            }

        price = float(
            candles[
                "close"
            ].iloc[-1]
        )

        signal_data = (
            generate_signal(
                candles
            )
        )

        signal = (
            signal_data.get(
                "signal",
                "NO TRADE",
            )
        )

        score = float(
            signal_data.get(
                "score",
                0,
            )
        )

        rsi = (
            signal_data.get(
                "rsi"
            )
        )

        macd = (
            signal_data.get(
                "macd"
            )
        )

        reason = (
            signal_data.get(
                "reason",
                "",
            )
        )

        return {
            "product_id": (
                product_id
            ),
            "symbol": symbol,
            "valid": True,
            "price": price,
            "signal": signal,
            "score": score,
            "rsi": rsi,
            "macd": macd,
            "reason": reason,
        }

    except Exception as error:

        return {
            "product_id": product_id,
            "symbol": symbol,
            "valid": False,
            "reason": str(error),
        }


# ============================================================
# SCAN ALL QUALITY MARKETS
# ============================================================

def scan_all_markets():

    market_ids = (
        discover_markets()
    )

    results = []

    log(
        "========================================"
    )

    log(
        f"AI SCANNING "
        f"{len(market_ids)} "
        f"LIQUID MARKETS"
    )

    log(
        "========================================"
    )

    for product_id in market_ids:

        result = (
            analyse_market(
                product_id
            )
        )

        results.append(
            result
        )

        if not result.get(
            "valid"
        ):

            log(
                f"{product_id} | "
                f"SKIP | "
                f"{result.get('reason')}"
            )

            continue

        rsi = (
            result.get(
                "rsi"
            )
        )

        rsi_text = (
            f"{float(rsi):.1f}"
            if rsi is not None
            else "N/A"
        )

        log(
            f"{product_id} | "
            f"Price="
            f"{result['price']:.6f} | "
            f"Signal="
            f"{result['signal']} | "
            f"Score="
            f"{result['score']:+.0f} | "
            f"RSI="
            f"{rsi_text} | "
            f"{result['reason']}"
        )

    return results


# ============================================================
# SELECT BEST CONFIRMED SETUP
# ============================================================

def select_best_setup(
    results,
):

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

        result[
            "absolute_score"
        ] = abs(
            float(
                result.get(
                    "score",
                    0,
                )
            )
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

    position = (
        paper.get_position()
    )

    if not position:
        return False

    symbol = position.get(
        "symbol"
    )

    if not symbol:

        log(
            "Stored position has no symbol."
        )

        return True

    candles = (
        get_market_candles(
            symbol
        )
    )

    if (
        candles is None
        or len(candles) == 0
    ):

        log(
            f"{symbol} | "
            "Could not monitor position."
        )

        return True

    current_price = float(
        candles[
            "close"
        ].iloc[-1]
    )

    result = (
        paper.update_price(
            current_price
        )
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
            f"{symbol} | "
            f"Side="
            f"{result.get('side')} | "
            f"Entry="
            f"{result.get('entry_price')} | "
            f"Exit="
            f"{result.get('exit_price')} | "
            f"PnL="
            f"{result.get('pnl'):.2f} | "
            f"Reason="
            f"{result.get('reason')} | "
            f"Balance="
            f"{result.get('balance'):.2f}"
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
            f"{current_price:.6f} | "
            f"TP="
            f"{current_position.get('take_profit')} | "
            f"SL="
            f"{current_position.get('stop_loss')}"
        )

    return True


# ============================================================
# OPEN BEST TRADE
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

    price = float(
        setup[
            "price"
        ]
    )

    score = float(
        setup.get(
            "score",
            0,
        )
    )

    log(
        "BEST SETUP | "
        f"{setup['product_id']} | "
        f"{signal} | "
        f"Score={score:+.0f} | "
        f"Price={price:.6f}"
    )

    plan = (
        calculate_trade_plan(
            balance=balance,
            entry_price=price,
            signal=signal,
            risk_percent=RISK_PCT,
            stop_loss_percent=SL_PCT,
            take_profit_percent=TP_PCT,
        )
    )

    if not validate_trade_plan(
        plan
    ):

        log(
            "TRADE REJECTED | "
            f"{symbol} | "
            f"{plan}"
        )

        return

    result = paper.open_trade(
        symbol=symbol,
        signal=signal,
        entry_price=price,
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
            f"{position['side']} | "
            f"Entry="
            f"{position['entry_price']:.6f} | "
            f"Qty="
            f"{position['quantity']:.8f} | "
            f"TP="
            f"{position['take_profit']:.6f} | "
            f"SL="
            f"{position['stop_loss']:.6f}"
        )

    else:

        log(
            "PAPER TRADE SKIPPED | "
            f"{symbol} | "
            f"{result}"
        )


# ============================================================
# FULL CYCLE
# ============================================================

def run_once():

    global _trading_paused

    balance = (
        paper.get_balance()
    )

    check_circuit_breaker(
        balance
    )

    # Existing position always gets priority.
    if paper.get_position():

        monitor_position()

        return

    if _trading_paused:

        log(
            "Trading paused by "
            "daily loss protection."
        )

        return

    results = (
        scan_all_markets()
    )

    best_setup = (
        select_best_setup(
            results
        )
    )

    if best_setup is None:

        log(
            "NO QUALIFYING TRADE | "
            "Quality universe scanned."
        )

        return

    open_best_trade(
        best_setup,
        balance,
    )


# ============================================================
# MAIN
# ============================================================

def _legacy_worker_enabled() -> bool:
    return os.environ.get("ENABLE_LEGACY_BOT_WORKER", "false").strip().lower() in {"1", "true", "yes", "on"}


def main():

    if not _legacy_worker_enabled():
        print('[LEGACY BOT WORKER] Disabled by default. Current canonical runtime is app.py embedded Crypto Autonomous. Set ENABLE_LEGACY_BOT_WORKER=true only for an intentional isolated legacy deployment.', flush=True)
        return

    log(
        "========================================"
    )

    log(
        "PRO AI DYNAMIC COINBASE "
        "PAPER SCANNER STARTING"
    )

    log(
        "========================================"
    )

    log(
        f"Max markets scanned: "
        f"{MAX_SCAN_MARKETS}"
    )

    log(
        f"Min approximate "
        f"24h quote volume: "
        f"${MIN_QUOTE_VOLUME_USD:,.0f}"
    )

    log(
        f"Max spread: "
        f"{MAX_SPREAD_PCT:.3f}%"
    )

    log(
        f"Timeframe: "
        f"{TIMEFRAME_MINUTES}m"
    )

    log(
        f"Risk per trade: "
        f"{RISK_PCT}%"
    )

    log(
        f"TP: "
        f"{TP_PCT}%"
    )

    log(
        f"SL: "
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
                "UNHANDLED ERROR | "
                f"{error}"
            )

        time.sleep(
            POLL_SECONDS
        )


if __name__ == "__main__":

    main()

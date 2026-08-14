# Stable autonomous paper-trading logic preserved.
# Quant terminal UI - HTML rendering fixed.

"""
app.py

PRO AI QUANT TERMINAL
Autonomous Paper Trading Dashboard

IMPORTANT:
- UK-compatible public market data
- Autonomous signal engine
- Automatic simulated TP / SL
- Risk management
- PAPER TRADING ONLY
- REAL AUTOMATIC ORDERS DISABLED
"""

import os
import time
import threading
import textwrap
from datetime import datetime, timezone

import streamlit as st
import pandas as pd
import streamlit.components.v1 as components

from market_data import get_ticker, get_candles
from signal_engine import generate_signal
from risk_manager import calculate_trade_plan, validate_trade_plan
from paper_trader import PaperTrader


# ============================================================
# PAGE CONFIG
# ============================================================

st.set_page_config(
    page_title="PRO AI QUANT TERMINAL",
    page_icon="⚡",
    layout="wide",
    initial_sidebar_state="collapsed",
)


# ============================================================
# HTML HELPER
# ============================================================

def html(content):
    """
    Render HTML using Streamlit native HTML renderer.
    This prevents <div> / <span> code from appearing as text.
    """
    st.html(
        textwrap.dedent(content).strip()
    )


# ============================================================
# ENVIRONMENT CONFIG
# ============================================================

PAPER_TRADING = (
    os.environ.get("PAPER_TRADING", "true").lower() == "true"
)

PAPER_SYMBOL = os.environ.get(
    "SYMBOL",
    "BTCUSDT",
).upper()

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


# ============================================================
# MARKETS
# ============================================================

TOP_SYMBOLS = [
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


# ============================================================
# SESSION STATE
# ============================================================

if "selected_pair" not in st.session_state:
    st.session_state.selected_pair = PAPER_SYMBOL

if "display_exchange" not in st.session_state:
    st.session_state.display_exchange = "Coinbase"


# ============================================================
# CSS
# ============================================================

html(
    """
    <style>

    #MainMenu,
    footer,
    header {
        visibility: hidden;
    }

    .block-container {
        padding-top: 0.25rem !important;
        padding-bottom: 1rem !important;
        padding-left: 0.55rem !important;
        padding-right: 0.55rem !important;
        max-width: 100% !important;
    }

    .stApp {
        background:
            radial-gradient(
                circle at 50% 0%,
                #151b24 0%,
                #090d12 42%,
                #05070a 100%
            );
        color: #dce5ef;
    }

    div[data-testid="stMetric"] {
        background: #0a0f15;
        border: 1px solid #26303a;
        border-radius: 3px;
        padding: 8px 10px;
    }

    div[data-testid="stMetric"] label {
        color: #667588 !important;
        font-size: 9px !important;
        text-transform: uppercase;
        letter-spacing: 0.7px;
    }

    div[data-testid="stMetricValue"] {
        font-family: monospace;
        font-size: 20px !important;
    }

    div[data-baseweb="select"] > div {
        background: #0a0f15 !important;
        border-color: #26303a !important;
        color: #ffffff !important;
    }

    .quant-header {
        border: 1px solid #28313b;
        background:
            linear-gradient(
                90deg,
                #0a0f14,
                #111822,
                #090d12
            );
        min-height: 52px;
        display: flex;
        align-items: center;
        padding: 0 13px;
        margin-bottom: 5px;
    }

    .logo-box {
        width: 27px;
        height: 27px;
        background: #f2d332;
        margin-right: 10px;
        box-shadow:
            0 0 15px rgba(242,211,50,.3);
    }

    .terminal-title {
        color: #f0f3f7;
        font-family: monospace;
        font-size: 14px;
        font-weight: 800;
        letter-spacing: .4px;
    }

    .terminal-subtitle {
        color: #697688;
        font-family: monospace;
        font-size: 8px;
        letter-spacing: 1px;
    }

    .live-text {
        color: #00d99a;
        font-family: monospace;
        font-size: 10px;
    }

    .terminal-strip {
        background: #080c11;
        border-top: 1px solid #1d2630;
        border-bottom: 1px solid #1d2630;
        padding: 6px 9px;
        margin-bottom: 6px;
        font-family: monospace;
        font-size: 9px;
        color: #687587;
    }

    .panel-title {
        color: #738194;
        font-family: monospace;
        font-size: 9px;
        letter-spacing: 1px;
        text-transform: uppercase;
        padding-bottom: 5px;
    }

    .panel {
        background: #090d12;
        border: 1px solid #252f3a;
        border-radius: 3px;
        padding: 11px;
    }

    .small-muted {
        color: #647183;
        font-family: monospace;
        font-size: 9px;
        letter-spacing: .4px;
    }

    .paper-equity {
        color: #2be3c1;
        font-family: monospace;
        font-size: 30px;
        padding: 7px 0 12px 0;
    }

    .green {
        color: #00da98;
    }

    .red {
        color: #ff5077;
    }

    .yellow {
        color: #f1d239;
    }

    .cyan {
        color: #28dfcf;
    }

    .purple {
        color: #aa82ff;
    }

    .execution-panel {
        border-left: 2px solid #f1d239;
    }

    .signal-large {
        font-family: monospace;
        font-size: 25px;
        font-weight: 800;
    }

    .score-large {
        color: #f2d43b;
        font-family: monospace;
        font-size: 43px;
        font-weight: 300;
    }

    .tag {
        display: inline-block;
        padding: 4px 7px;
        border: 1px solid #303b47;
        background: #0d131a;
        font-family: monospace;
        font-size: 9px;
        margin-right: 4px;
        margin-bottom: 4px;
    }

    .indicator-grid {
        display: grid;
        grid-template-columns: repeat(6, 1fr);
        gap: 5px;
        margin-top: 6px;
        margin-bottom: 7px;
    }

    .indicator-card {
        background: #090e14;
        border: 1px solid #27313d;
        min-height: 70px;
        padding: 8px;
    }

    .indicator-name {
        color: #697688;
        font-family: monospace;
        font-size: 8px;
        letter-spacing: .7px;
    }

    .indicator-value {
        font-family: monospace;
        font-size: 14px;
        margin-top: 8px;
    }

    .intelligence {
        min-height: 305px;
        position: relative;
        overflow: hidden;
        border: 1px solid #252f3b;
        background:
            radial-gradient(
                circle at center,
                rgba(45,222,205,.07),
                transparent 33%
            ),
            #070a0e;
        margin-top: 4px;
    }

    .intelligence-title {
        position: absolute;
        left: 12px;
        top: 10px;
        color: #6c798b;
        font-family: monospace;
        font-size: 9px;
        z-index: 10;
    }

    .core {
        position: absolute;
        left: calc(50% - 48px);
        top: calc(50% - 48px);
        width: 96px;
        height: 96px;
        border-radius: 50%;
        border: 2px solid #f1d33b;
        background: #15140b;
        color: #f1d33b;
        font-family: monospace;
        font-size: 11px;
        display: flex;
        align-items: center;
        justify-content: center;
        text-align: center;
        box-shadow:
            0 0 16px rgba(241,211,59,.28),
            0 0 45px rgba(241,211,59,.12);
        z-index: 5;
    }

    .node {
        position: absolute;
        width: 68px;
        height: 68px;
        border-radius: 50%;
        background: #0b1016;
        border: 1px solid #303b47;
        font-family: monospace;
        font-size: 9px;
        display: flex;
        align-items: center;
        justify-content: center;
        text-align: center;
        z-index: 4;
    }

    .rsi-node {
        left: 13%;
        top: 21%;
        color: #2ee2c9;
        border-color: #2ee2c9;
    }

    .macd-node {
        right: 13%;
        top: 19%;
        color: #ff547b;
        border-color: #ff547b;
    }

    .trend-node {
        left: 20%;
        bottom: 11%;
        color: #aa82ff;
        border-color: #aa82ff;
    }

    .risk-node {
        right: 20%;
        bottom: 11%;
        color: #f1d33b;
        border-color: #f1d33b;
    }

    .price-node {
        left: 6%;
        top: 52%;
        color: #54aaff;
        border-color: #54aaff;
    }

    .tpsl-node {
        right: 6%;
        top: 52%;
        color: #00da98;
        border-color: #00da98;
    }

    .line {
        position: absolute;
        height: 1px;
        background: #283541;
        transform-origin: left center;
        opacity: .75;
    }

    .line1 {
        left: 21%;
        top: 34%;
        width: 31%;
        transform: rotate(18deg);
    }

    .line2 {
        left: 51%;
        top: 37%;
        width: 31%;
        transform: rotate(-20deg);
    }

    .line3 {
        left: 27%;
        top: 67%;
        width: 26%;
        transform: rotate(-20deg);
    }

    .line4 {
        left: 50%;
        top: 66%;
        width: 28%;
        transform: rotate(22deg);
    }

    .line5 {
        left: 14%;
        top: 56%;
        width: 38%;
    }

    .line6 {
        left: 51%;
        top: 56%;
        width: 38%;
    }

    .safe-notice {
        border: 1px solid #00da98;
        background: #07150f;
        color: #00da98;
        padding: 7px;
        font-family: monospace;
        font-size: 9px;
    }

    @media (max-width: 900px) {

        .indicator-grid {
            grid-template-columns: repeat(3, 1fr);
        }

        .terminal-title {
            font-size: 11px;
        }

        .paper-equity {
            font-size: 23px;
        }

    }

    </style>
    """
)


# ============================================================
# AUTONOMOUS PAPER BOT
# ============================================================

def paper_bot_loop(state, lock):

    trader = PaperTrader(
        starting_balance=PAPER_BALANCE
    )

    day_start_balance = PAPER_BALANCE
    day_start_date = None
    trading_paused = False

    while True:

        try:

            now_utc = datetime.now(
                timezone.utc
            )

            today = now_utc.date()

            balance = trader.get_balance()

            if day_start_date != today:

                day_start_date = today
                day_start_balance = balance
                trading_paused = False

            drawdown_pct = 0.0

            if day_start_balance > 0:

                drawdown_pct = (
                    (
                        day_start_balance
                        - balance
                    )
                    / day_start_balance
                    * 100
                )

                if drawdown_pct >= MAX_DAILY_LOSS_PCT:
                    trading_paused = True

            candles = get_candles(
                exchange="PUBLIC",
                symbol=PAPER_SYMBOL,
                timeframe_minutes=15,
                limit=100,
                api_key="",
                api_secret="",
                use_testnet=False,
            )

            if (
                candles is None
                or len(candles) < 50
            ):

                with lock:

                    state["status"] = (
                        "WAITING FOR MARKET DATA"
                    )

                    state["last_update"] = (
                        now_utc.isoformat()
                    )

                time.sleep(
                    POLL_SECONDS
                )

                continue

            current_price = float(
                candles["close"].iloc[-1]
            )

            existing_position = (
                trader.get_position()
            )

            if existing_position:

                update_result = (
                    trader.update_price(
                        current_price
                    )
                )

                with lock:

                    state["price"] = (
                        current_price
                    )

                    state["balance"] = (
                        trader.get_balance()
                    )

                    state["position"] = (
                        trader.get_position()
                    )

                    state["drawdown"] = (
                        drawdown_pct
                    )

                    state["last_update"] = (
                        now_utc.isoformat()
                    )

                if (
                    update_result
                    and update_result.get(
                        "status"
                    )
                    == "CLOSED"
                ):

                    with lock:

                        state["status"] = (
                            "TRADE CLOSED"
                        )

                        state["last_trade"] = (
                            update_result
                        )

                        state["trade_count"] += 1

                        state["realized_pnl"] += float(
                            update_result.get(
                                "pnl",
                                0,
                            )
                        )

                    print(
                        f"[PAPER BOT] CLOSED "
                        f"{update_result}",
                        flush=True,
                    )

                else:

                    with lock:
                        state["status"] = (
                            "POSITION OPEN"
                        )

                time.sleep(
                    POLL_SECONDS
                )

                continue

            if trading_paused:

                with lock:

                    state["status"] = (
                        "DAILY LOSS LIMIT HIT"
                    )

                    state["price"] = (
                        current_price
                    )

                    state["balance"] = (
                        trader.get_balance()
                    )

                    state["drawdown"] = (
                        drawdown_pct
                    )

                time.sleep(
                    POLL_SECONDS
                )

                continue

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

            reason = signal_data.get(
                "reason",
                "",
            )

            rsi = signal_data.get(
                "rsi",
                0,
            )

            macd = signal_data.get(
                "macd",
                0,
            )

            with lock:

                state["price"] = (
                    current_price
                )

                state["signal"] = (
                    signal
                )

                state["score"] = (
                    score
                )

                state["reason"] = (
                    reason
                )

                state["rsi"] = (
                    rsi
                )

                state["macd"] = (
                    macd
                )

                state["balance"] = (
                    trader.get_balance()
                )

                state["position"] = (
                    None
                )

                state["drawdown"] = (
                    drawdown_pct
                )

                state["last_update"] = (
                    now_utc.isoformat()
                )

            if signal not in (
                "BUY",
                "SELL",
            ):

                with lock:
                    state["status"] = (
                        "SCANNING MARKET"
                    )

                time.sleep(
                    POLL_SECONDS
                )

                continue

            plan = calculate_trade_plan(
                balance=trader.get_balance(),
                entry_price=current_price,
                signal=signal,
                risk_percent=RISK_PCT,
                stop_loss_percent=SL_PCT,
                take_profit_percent=TP_PCT,
            )

            if not validate_trade_plan(
                plan
            ):

                with lock:
                    state["status"] = (
                        "TRADE REJECTED BY RISK MANAGER"
                    )

                time.sleep(
                    POLL_SECONDS
                )

                continue

            result = trader.open_trade(
                symbol=PAPER_SYMBOL,
                signal=signal,
                entry_price=current_price,
                quantity=plan["quantity"],
                take_profit=plan["take_profit"],
                stop_loss=plan["stop_loss"],
            )

            if (
                result.get("status")
                == "EXECUTED"
            ):

                with lock:

                    state["status"] = (
                        "PAPER TRADE OPENED"
                    )

                    state["position"] = (
                        trader.get_position()
                    )

                print(
                    "[PAPER BOT] "
                    f"OPENED {PAPER_SYMBOL} "
                    f"{signal} "
                    f"price={current_price} "
                    f"score={score}",
                    flush=True,
                )

            else:

                with lock:
                    state["status"] = (
                        "TRADE SKIPPED"
                    )

        except Exception as error:

            with lock:

                state["status"] = (
                    "ERROR"
                )

                state["error"] = (
                    str(error)
                )

            print(
                "[PAPER BOT ERROR] "
                f"{error}",
                flush=True,
            )

        time.sleep(
            POLL_SECONDS
        )


# ============================================================
# START BOT ONCE
# ============================================================

@st.cache_resource
def start_paper_bot():

    state = {
        "status": "STARTING",
        "price": None,
        "signal": "NO TRADE",
        "score": 0,
        "reason": "",
        "rsi": None,
        "macd": None,
        "balance": PAPER_BALANCE,
        "position": None,
        "last_trade": None,
        "trade_count": 0,
        "realized_pnl": 0.0,
        "drawdown": 0.0,
        "last_update": None,
        "error": None,
    }

    lock = threading.Lock()

    thread = threading.Thread(
        target=paper_bot_loop,
        args=(
            state,
            lock,
        ),
        daemon=True,
        name="autonomous-paper-bot",
    )

    thread.start()

    return (
        state,
        lock,
        thread,
    )


if PAPER_TRADING:

    (
        bot_state,
        bot_lock,
        bot_thread,
    ) = start_paper_bot()

else:

    bot_state = {
        "status": "DISABLED",
        "price": None,
        "signal": "NO TRADE",
        "score": 0,
        "reason": "",
        "rsi": None,
        "macd": None,
        "balance": PAPER_BALANCE,
        "position": None,
        "last_trade": None,
        "trade_count": 0,
        "realized_pnl": 0.0,
        "drawdown": 0.0,
        "last_update": None,
        "error": None,
    }

    bot_lock = threading.Lock()
    bot_thread = None


# ============================================================
# SNAPSHOT
# ============================================================

def get_bot_snapshot():

    with bot_lock:

        return dict(
            bot_state
        )


snapshot = get_bot_snapshot()


# ============================================================
# HEADER
# ============================================================

utc_now = datetime.now(
    timezone.utc
).strftime(
    "%H:%M:%S UTC"
)


html(
    f"""
    <div class="quant-header">

        <div class="logo-box"></div>

        <div style="flex:1">

            <div class="terminal-title">
                PRO AI • QUANT MARKET TERMINAL
            </div>

            <div class="terminal-subtitle">
                AUTONOMOUS PAPER EXECUTION /
                SIGNAL INTELLIGENCE /
                RISK ENGINE
            </div>

        </div>

        <div class="live-text">
            ● ONLINE &nbsp;&nbsp; {utc_now}
        </div>

    </div>
    """
)


html(
    f"""
    <div class="terminal-strip">

        MARKET FEED: UK PUBLIC DATA

        &nbsp;&nbsp;|&nbsp;&nbsp;

        BOT: {PAPER_SYMBOL}

        &nbsp;&nbsp;|&nbsp;&nbsp;

        MODE: PAPER

        &nbsp;&nbsp;|&nbsp;&nbsp;

        SCAN: {POLL_SECONDS}s

        &nbsp;&nbsp;|&nbsp;&nbsp;

        REAL EXECUTION: OFF

    </div>
    """
)


# ============================================================
# MARKET CONTROLS
# ============================================================

c1, c2, c3 = st.columns(
    [
        1.3,
        1.3,
        4,
    ]
)


with c1:

    selected_pair = st.selectbox(
        "Market",
        TOP_SYMBOLS,
        index=(
            TOP_SYMBOLS.index(
                st.session_state.selected_pair
            )
            if st.session_state.selected_pair
            in TOP_SYMBOLS
            else 0
        ),
    )

    st.session_state.selected_pair = (
        selected_pair
    )


with c2:

    display_exchange = st.selectbox(
        "Chart Feed",
        [
            "Coinbase",
            "Bybit",
            "Binance",
        ],
        index=0,
    )

    st.session_state.display_exchange = (
        display_exchange
    )


with c3:

    html(
        """
        <div style="height:27px"></div>

        <span class="tag green">
            ● PAPER ACTIVE
        </span>

        <span class="tag cyan">
            PUBLIC MARKET DATA
        </span>

        <span class="tag yellow">
            AUTO TP / SL
        </span>

        <span class="tag purple">
            RISK ENGINE
        </span>
        """
    )


# ============================================================
# PUBLIC TICKER
# ============================================================

ticker = get_ticker(
    symbol=selected_pair,
    exchange="PUBLIC",
    api_key="",
    api_secret="",
    use_testnet=False,
)


market_price = 0.0
change_pct = 0.0
high_price = 0.0
low_price = 0.0
volume = 0.0


if ticker:

    market_price = float(
        ticker.get(
            "last",
            0,
        )
    )

    change_pct = float(
        ticker.get(
            "change_pct",
            0,
        )
    )

    high_price = float(
        ticker.get(
            "high",
            0,
        )
    )

    low_price = float(
        ticker.get(
            "low",
            0,
        )
    )

    volume = float(
        ticker.get(
            "volume",
            0,
        )
    )


# ============================================================
# MAIN LAYOUT
# ============================================================

account_col, chart_col, execution_col = (
    st.columns(
        [
            1.05,
            2.8,
            1.25,
        ]
    )
)


# ============================================================
# ACCOUNT PANEL
# ============================================================

with account_col:

    html(
        """
        <div class="panel-title">
            ACCOUNT / BOT STATE
        </div>
        """
    )

    html(
        f"""
        <div class="panel">

            <div class="small-muted">
                PAPER EQUITY
            </div>

            <div class="paper-equity">
                ${snapshot['balance']:,.0f}
            </div>

            <div class="small-muted">
                REALIZED P&L
            </div>

            <div
                class="green"
                style="
                font-family:monospace;
                font-size:19px;
                padding:6px 0 13px 0;
                "
            >
                ${snapshot['realized_pnl']:,.2f}
            </div>

            <div class="small-muted">
                COMPLETED TRADES
            </div>

            <div
                style="
                font-family:monospace;
                font-size:18px;
                padding:6px 0 13px 0;
                "
            >
                {snapshot['trade_count']}
            </div>

            <div class="small-muted">
                DAILY DRAWDOWN
            </div>

            <div
                class="yellow"
                style="
                font-family:monospace;
                font-size:17px;
                padding:6px 0 13px 0;
                "
            >
                {snapshot['drawdown']:.2f}%
            </div>

            <div class="safe-notice">
                PAPER EXECUTION ONLY<br>
                REAL ORDERS DISABLED
            </div>

        </div>
        """
    )


# ============================================================
# CHART PANEL
# ============================================================

with chart_col:

    html(
        """
        <div class="panel-title">
            LIVE PRICE / MARKET STRUCTURE
        </div>
        """
    )

    price_css = (
        "green"
        if change_pct >= 0
        else "red"
    )

    html(
        f"""
        <div class="terminal-strip">

            {selected_pair}

            &nbsp;&nbsp;

            <span class="{price_css}">
                ${market_price:,.2f}
            </span>

            &nbsp;&nbsp;

            <span class="{price_css}">
                {change_pct:+.2f}%
            </span>

            &nbsp;&nbsp;

            HIGH ${high_price:,.2f}

            &nbsp;&nbsp;

            LOW ${low_price:,.2f}

        </div>
        """
    )

    if display_exchange == "Bybit":

        tv_symbol = (
            f"BYBIT:{selected_pair}"
        )

    elif display_exchange == "Binance":

        tv_symbol = (
            f"BINANCE:{selected_pair}"
        )

    else:

        base = selected_pair.replace(
            "USDT",
            "",
        )

        tv_symbol = (
            f"COINBASE:{base}USD"
        )

    tv_widget = f"""
    <div style="
        height:435px;
        width:100%;
        border:1px solid #252f3a;
        background:#070a0e;
    ">

        <div
            id="tv_chart"
            style="
            height:435px;
            width:100%;
            "
        ></div>

        <script
            src="https://s3.tradingview.com/tv.js"
        ></script>

        <script>

        new TradingView.widget({{
            "autosize": true,
            "symbol": "{tv_symbol}",
            "interval": "15",
            "timezone": "Etc/UTC",
            "theme": "dark",
            "style": "1",
            "locale": "en",
            "enable_publishing": false,
            "hide_side_toolbar": false,
            "allow_symbol_change": true,
            "container_id": "tv_chart",
            "backgroundColor": "#070a0e",
            "gridColor": "#151c23"
        }});

        </script>

    </div>
    """

    components.html(
        tv_widget,
        height=440,
    )


# ============================================================
# EXECUTION PANEL
# ============================================================

with execution_col:

    html(
        """
        <div class="panel-title">
            AI EXECUTION ENGINE
        </div>
        """
    )

    signal = snapshot.get(
        "signal",
        "NO TRADE",
    )

    score = int(
        snapshot.get(
            "score",
            0,
        )
    )

    signal_css = (
        "green"
        if signal == "BUY"
        else (
            "red"
            if signal == "SELL"
            else "yellow"
        )
    )

    html(
        f"""
        <div class="panel execution-panel">

            <div class="small-muted">
                LIVE SIGNAL
            </div>

            <div class="signal-large {signal_css}">
                {signal}
            </div>

            <br>

            <div class="small-muted">
                AI SCORE
            </div>

            <div class="score-large">
                {score:+d}
            </div>

            <div class="small-muted">
                BOT STATUS
            </div>

            <div
                style="
                font-family:monospace;
                font-size:11px;
                padding:6px 0 13px 0;
                "
            >
                {snapshot['status']}
            </div>

            <div class="small-muted">
                RISK / TRADE
            </div>

            <div
                class="cyan"
                style="
                font-family:monospace;
                padding:4px 0 10px 0;
                "
            >
                {RISK_PCT:.1f}%
            </div>

            <div class="small-muted">
                TAKE PROFIT
            </div>

            <div
                class="green"
                style="
                font-family:monospace;
                padding:4px 0 10px 0;
                "
            >
                +{TP_PCT:.1f}%
            </div>

            <div class="small-muted">
                STOP LOSS
            </div>

            <div
                class="red"
                style="
                font-family:monospace;
                padding-top:4px;
                "
            >
                -{SL_PCT:.1f}%
            </div>

        </div>
        """
    )


# ============================================================
# INDICATORS
# ============================================================

rsi_value = snapshot.get(
    "rsi"
)

macd_value = snapshot.get(
    "macd"
)


rsi_text = (
    f"{float(rsi_value):.1f}"
    if rsi_value is not None
    else "—"
)


macd_text = (
    f"{float(macd_value):.2f}"
    if macd_value is not None
    else "—"
)


rsi_state = "Neutral"

if rsi_value is not None:

    if float(rsi_value) >= 70:

        rsi_state = (
            "Overbought"
        )

    elif float(rsi_value) <= 30:

        rsi_state = (
            "Oversold"
        )


reason_text = snapshot.get(
    "reason",
    "",
)


if "Bullish trend" in reason_text:

    trend_state = (
        "Bullish"
    )

elif "Bearish trend" in reason_text:

    trend_state = (
        "Bearish"
    )

else:

    trend_state = (
        "Neutral"
    )


html(
    f"""
    <div class="indicator-grid">

        <div class="indicator-card">

            <div class="indicator-name">
                RSI 14
            </div>

            <div class="indicator-value yellow">
                {rsi_text}
            </div>

            <div class="small-muted">
                {rsi_state}
            </div>

        </div>


        <div class="indicator-card">

            <div class="indicator-name">
                MACD
            </div>

            <div class="indicator-value cyan">
                {macd_text}
            </div>

            <div class="small-muted">
                Momentum
            </div>

        </div>


        <div class="indicator-card">

            <div class="indicator-name">
                TREND
            </div>

            <div class="indicator-value green">
                {trend_state}
            </div>

            <div class="small-muted">
                EMA Structure
            </div>

        </div>


        <div class="indicator-card">

            <div class="indicator-name">
                SIGNAL SCORE
            </div>

            <div class="indicator-value yellow">
                {score:+d}
            </div>

            <div class="small-muted">
                Threshold ±4
            </div>

        </div>


        <div class="indicator-card">

            <div class="indicator-name">
                BOT MARKET
            </div>

            <div class="indicator-value purple">
                {PAPER_SYMBOL}
            </div>

            <div class="small-muted">
                Autonomous
            </div>

        </div>


        <div class="indicator-card">

            <div class="indicator-name">
                SCAN RATE
            </div>

            <div class="indicator-value cyan">
                {POLL_SECONDS}s
            </div>

            <div class="small-muted">
                Cycle
            </div>

        </div>

    </div>
    """
)


# ============================================================
# AI INTELLIGENCE NETWORK
# ============================================================

html(
    f"""
    <div class="intelligence">

        <div class="intelligence-title">
            AI MARKET INTELLIGENCE //
            SIGNAL RELATIONSHIP ENGINE
        </div>

        <div class="line line1"></div>
        <div class="line line2"></div>
        <div class="line line3"></div>
        <div class="line line4"></div>
        <div class="line line5"></div>
        <div class="line line6"></div>

        <div class="node rsi-node">
            RSI<br>
            {rsi_text}
        </div>

        <div class="node macd-node">
            MACD<br>
            {macd_text}
        </div>

        <div class="node trend-node">
            EMA<br>
            {trend_state}
        </div>

        <div class="node risk-node">
            RISK<br>
            {RISK_PCT:.1f}%
        </div>

        <div class="node price-node">
            PRICE<br>
            ${market_price:,.0f}
        </div>

        <div class="node tpsl-node">
            TP / SL<br>
            AUTO
        </div>

        <div class="core">
            AI CORE<br>
            SCORE<br>
            {score:+d}
        </div>

    </div>
    """
)


# ============================================================
# BOTTOM ANALYTICS
# ============================================================

left_bottom, middle_bottom, right_bottom = (
    st.columns(
        [
            1.45,
            1.25,
            1,
        ]
    )
)


with left_bottom:

    html(
        """
        <div class="panel-title">
            SIGNAL ANALYSIS
        </div>
        """
    )

    html(
        f"""
        <div class="panel">

            <div class="small-muted">
                CURRENT INTERPRETATION
            </div>

            <div
                style="
                font-family:monospace;
                font-size:11px;
                line-height:1.7;
                padding-top:8px;
                "
            >
                {reason_text or "Waiting for analysis"}
            </div>

            <br>

            <div class="small-muted">
                LAST UPDATE
            </div>

            <div
                style="
                font-family:monospace;
                font-size:9px;
                padding-top:5px;
                "
            >
                {snapshot.get('last_update') or 'Starting'}
            </div>

        </div>
        """
    )


with middle_bottom:

    html(
        """
        <div class="panel-title">
            PERFORMANCE
        </div>
        """
    )

    st.metric(
        "Starting Balance",
        f"${PAPER_BALANCE:,.2f}",
    )

    st.metric(
        "Current Equity",
        f"${snapshot['balance']:,.2f}",
    )

    st.metric(
        "Realized P&L",
        f"${snapshot['realized_pnl']:,.2f}",
    )


with right_bottom:

    html(
        """
        <div class="panel-title">
            RISK CONTROL
        </div>
        """
    )

    st.metric(
        "Max Daily Loss",
        f"{MAX_DAILY_LOSS_PCT:.1f}%",
    )

    st.metric(
        "Current Drawdown",
        f"{snapshot['drawdown']:.2f}%",
    )

    st.metric(
        "Closed Trades",
        snapshot["trade_count"],
    )


# ============================================================
# ACTIVE PAPER POSITION
# ============================================================

position = snapshot.get(
    "position"
)


if position:

    html(
        """
        <div
            class="panel-title"
            style="margin-top:8px;"
        >
            ACTIVE PAPER POSITION
        </div>
        """
    )

    position_df = pd.DataFrame(
        [
            {
                "Mode": "PAPER",
                "Symbol": position.get(
                    "symbol"
                ),
                "Side": position.get(
                    "side"
                ),
                "Quantity": position.get(
                    "quantity"
                ),
                "Entry": position.get(
                    "entry_price"
                ),
                "Take Profit": position.get(
                    "take_profit"
                ),
                "Stop Loss": position.get(
                    "stop_loss"
                ),
                "Opened": position.get(
                    "opened_at"
                ),
            }
        ]
    )

    st.dataframe(
        position_df,
        width="stretch",
        hide_index=True,
    )


# ============================================================
# LAST CLOSED TRADE
# ============================================================

last_trade = snapshot.get(
    "last_trade"
)


if last_trade:

    with st.expander(
        "LAST CLOSED PAPER TRADE"
    ):

        st.json(
            last_trade
        )


# ============================================================
# ERRORS
# ============================================================

if snapshot.get(
    "error"
):

    st.error(
        snapshot["error"]
    )


# ============================================================
# FOOTER
# ============================================================

html(
    """
    <div
        class="terminal-strip"
        style="margin-top:8px;"
    >

        PRO AI QUANT TERMINAL

        &nbsp;&nbsp;•&nbsp;&nbsp;

        AUTONOMOUS PAPER TRADING

        &nbsp;&nbsp;•&nbsp;&nbsp;

        UK PUBLIC MARKET DATA

        &nbsp;&nbsp;•&nbsp;&nbsp;

        REAL ORDER EXECUTION DISABLED

    </div>
    """
)

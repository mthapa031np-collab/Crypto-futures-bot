# Stable working bot logic preserved
# UI redesign: Quant / Institutional AI Terminal

"""
app.py

PRO AI QUANT TERMINAL
Autonomous Paper Trading Dashboard

CORE LOGIC PRESERVED:
- UK-compatible public market data
- Autonomous signal engine
- Risk manager
- Paper trader
- Automatic simulated TP / SL
- Daily loss protection

IMPORTANT:
REAL AUTOMATIC ORDERS ARE DISABLED.
This version remains PAPER TRADING only.
"""

import os
import time
import threading
from datetime import datetime, timezone

import streamlit as st
import pandas as pd
import streamlit.components.v1 as components

from market_data import get_ticker, get_candles
from signal_engine import generate_signal
from risk_manager import calculate_trade_plan, validate_trade_plan
from paper_trader import PaperTrader


# ============================================================
# PAGE
# ============================================================

st.set_page_config(
    page_title="PRO AI QUANT TERMINAL",
    page_icon="⚡",
    layout="wide",
    initial_sidebar_state="collapsed",
)


# ============================================================
# CONFIG
# ============================================================

PAPER_TRADING = (
    os.environ.get("PAPER_TRADING", "true").lower() == "true"
)

PAPER_SYMBOL = os.environ.get(
    "SYMBOL",
    "BTCUSDT",
).upper()

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
# SESSION
# ============================================================

if "selected_pair" not in st.session_state:
    st.session_state.selected_pair = PAPER_SYMBOL

if "display_exchange" not in st.session_state:
    st.session_state.display_exchange = "Coinbase"


# ============================================================
# QUANT TERMINAL CSS
# ============================================================

st.markdown(
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
    padding-left: 0.45rem !important;
    padding-right: 0.45rem !important;
    max-width: 100% !important;
}

.stApp {
    background:
        radial-gradient(circle at 50% 0%, #141821 0%, #080b10 40%, #05070a 100%);
    color: #dce4ec;
}

div[data-testid="stMetric"] {
    background: #0a0e14;
    border: 1px solid #202833;
    border-radius: 4px;
    padding: 8px 10px;
}

div[data-testid="stMetric"] label {
    color: #697789 !important;
    font-size: 10px !important;
    text-transform: uppercase;
    letter-spacing: 0.8px;
}

div[data-testid="stMetricValue"] {
    font-family: monospace;
    font-size: 21px !important;
}

div[data-baseweb="select"] > div {
    background: #0a0e14 !important;
    border-color: #202833 !important;
    color: white !important;
}

.quant-header {
    height: 48px;
    border: 1px solid #242c36;
    background: linear-gradient(90deg, #0b1016, #111720, #090d12);
    display: flex;
    align-items: center;
    padding: 0 14px;
    margin-bottom: 5px;
}

.logo-cube {
    width: 25px;
    height: 25px;
    background: #f5d000;
    margin-right: 10px;
    box-shadow: 0 0 14px rgba(245,208,0,.3);
}

.quant-title {
    color: #edf1f5;
    font-family: monospace;
    font-weight: 800;
    font-size: 14px;
}

.quant-sub {
    color: #647184;
    font-size: 9px;
    letter-spacing: 1.2px;
}

.live-dot {
    color: #00d992;
}

.terminal-strip {
    background: #080c11;
    border-top: 1px solid #1d2530;
    border-bottom: 1px solid #1d2530;
    padding: 5px 9px;
    margin-bottom: 5px;
    font-family: monospace;
    font-size: 10px;
    color: #687587;
}

.panel {
    background: #090d12;
    border: 1px solid #252e39;
    border-radius: 3px;
    padding: 10px;
    height: 100%;
}

.panel-title {
    color: #8290a2;
    font-family: monospace;
    text-transform: uppercase;
    font-size: 10px;
    letter-spacing: 1px;
    margin-bottom: 8px;
}

.big-money {
    font-family: monospace;
    font-size: 31px;
    color: #27e0bd;
    text-shadow: 0 0 12px rgba(39,224,189,.15);
}

.small-muted {
    color: #5e6978;
    font-size: 10px;
}

.green {
    color: #00d992 !important;
}

.red {
    color: #ff4f78 !important;
}

.yellow {
    color: #f6d63a !important;
}

.cyan {
    color: #23e2d0 !important;
}

.purple {
    color: #a981ff !important;
}

.ai-score {
    font-size: 46px;
    font-weight: 300;
    font-family: monospace;
    color: #f3dc3a;
}

.execution-card {
    border-left: 2px solid #f6d63a;
    padding-left: 10px;
}

.indicator-strip {
    display: grid;
    grid-template-columns: repeat(6, 1fr);
    gap: 5px;
    margin-top: 5px;
    margin-bottom: 7px;
}

.indicator-card {
    background: #0b0f15;
    border: 1px solid #28313c;
    min-height: 68px;
    padding: 8px;
    font-family: monospace;
}

.ind-name {
    color: #6d7887;
    font-size: 9px;
    text-transform: uppercase;
}

.ind-value {
    color: #e4e9ef;
    font-size: 14px;
    margin-top: 7px;
}

.intelligence {
    min-height: 290px;
    position: relative;
    overflow: hidden;
    background:
        radial-gradient(circle at center, rgba(37,224,208,.06), transparent 35%),
        #070a0e;
    border: 1px solid #222b36;
}

.intelligence-title {
    position: absolute;
    left: 12px;
    top: 10px;
    font-family: monospace;
    font-size: 10px;
    color: #727f90;
}

.ai-core {
    position: absolute;
    width: 94px;
    height: 94px;
    border-radius: 50%;
    left: calc(50% - 47px);
    top: calc(50% - 47px);
    border: 2px solid #f5d83a;
    background: #14150c;
    box-shadow:
        0 0 15px rgba(245,216,58,.35),
        0 0 45px rgba(245,216,58,.12);
    display: flex;
    align-items: center;
    justify-content: center;
    text-align: center;
    color: #f5d83a;
    font-family: monospace;
    z-index: 5;
}

.node {
    position: absolute;
    width: 68px;
    height: 68px;
    border-radius: 50%;
    background: #0c1117;
    border: 1px solid #27313d;
    display: flex;
    align-items: center;
    justify-content: center;
    text-align: center;
    font-family: monospace;
    font-size: 9px;
    z-index: 4;
}

.n1 {
    left: 13%;
    top: 22%;
    color: #2ae0c4;
    border-color: #2ae0c4;
}

.n2 {
    right: 13%;
    top: 18%;
    color: #ff527a;
    border-color: #ff527a;
}

.n3 {
    left: 20%;
    bottom: 12%;
    color: #a97aff;
    border-color: #a97aff;
}

.n4 {
    right: 19%;
    bottom: 13%;
    color: #f1ce36;
    border-color: #f1ce36;
}

.n5 {
    left: 7%;
    top: 50%;
    color: #45a9ff;
    border-color: #45a9ff;
}

.n6 {
    right: 7%;
    top: 52%;
    color: #00d992;
    border-color: #00d992;
}

.link-line {
    position: absolute;
    height: 1px;
    background: #24303b;
    transform-origin: left center;
    opacity: .8;
}

.l1 {
    left: 22%;
    top: 35%;
    width: 30%;
    transform: rotate(18deg);
}

.l2 {
    left: 51%;
    top: 38%;
    width: 30%;
    transform: rotate(-21deg);
}

.l3 {
    left: 28%;
    top: 67%;
    width: 25%;
    transform: rotate(-20deg);
}

.l4 {
    left: 50%;
    top: 66%;
    width: 28%;
    transform: rotate(22deg);
}

.l5 {
    left: 16%;
    top: 55%;
    width: 35%;
}

.l6 {
    left: 51%;
    top: 56%;
    width: 36%;
}

.signal-pill {
    display: inline-block;
    border: 1px solid #303945;
    background: #11161d;
    padding: 4px 8px;
    margin: 2px;
    font-family: monospace;
    font-size: 10px;
}

.paper-warning {
    border: 1px solid #00d992;
    color: #00d992;
    background: #07150f;
    padding: 6px 8px;
    font-size: 9px;
    font-family: monospace;
}

@media (max-width: 800px) {
    .indicator-strip {
        grid-template-columns: repeat(2, 1fr);
    }

    .ai-score {
        font-size: 30px;
    }
}

</style>
""",
    unsafe_allow_html=True,
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

            if candles is None or len(candles) < 50:

                with lock:
                    state["status"] = "WAITING FOR MARKET DATA"
                    state["last_update"] = now_utc.isoformat()

                time.sleep(POLL_SECONDS)
                continue

            current_price = float(
                candles["close"].iloc[-1]
            )

            existing_position = trader.get_position()

            if existing_position:

                update_result = trader.update_price(
                    current_price
                )

                with lock:
                    state["price"] = current_price
                    state["balance"] = trader.get_balance()
                    state["position"] = trader.get_position()
                    state["drawdown"] = drawdown_pct
                    state["last_update"] = now_utc.isoformat()

                if (
                    update_result
                    and update_result.get("status") == "CLOSED"
                ):

                    with lock:

                        state["status"] = "TRADE CLOSED"
                        state["last_trade"] = update_result
                        state["trade_count"] += 1
                        state["realized_pnl"] += float(
                            update_result.get("pnl", 0)
                        )

                    print(
                        f"[PAPER BOT] CLOSED {update_result}",
                        flush=True,
                    )

                else:

                    with lock:
                        state["status"] = "POSITION OPEN"

                time.sleep(POLL_SECONDS)
                continue

            if trading_paused:

                with lock:
                    state["status"] = "DAILY LOSS LIMIT HIT"
                    state["price"] = current_price
                    state["balance"] = trader.get_balance()
                    state["drawdown"] = drawdown_pct

                time.sleep(POLL_SECONDS)
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

                state["price"] = current_price
                state["signal"] = signal
                state["score"] = score
                state["reason"] = reason
                state["rsi"] = rsi
                state["macd"] = macd
                state["balance"] = trader.get_balance()
                state["position"] = None
                state["drawdown"] = drawdown_pct
                state["last_update"] = now_utc.isoformat()

            if signal not in ("BUY", "SELL"):

                with lock:
                    state["status"] = "SCANNING MARKET"

                time.sleep(POLL_SECONDS)
                continue

            plan = calculate_trade_plan(
                balance=trader.get_balance(),
                entry_price=current_price,
                signal=signal,
                risk_percent=RISK_PCT,
                stop_loss_percent=SL_PCT,
                take_profit_percent=TP_PCT,
            )

            if not validate_trade_plan(plan):

                with lock:
                    state["status"] = (
                        "TRADE REJECTED BY RISK MANAGER"
                    )

                time.sleep(POLL_SECONDS)
                continue

            result = trader.open_trade(
                symbol=PAPER_SYMBOL,
                signal=signal,
                entry_price=current_price,
                quantity=plan["quantity"],
                take_profit=plan["take_profit"],
                stop_loss=plan["stop_loss"],
            )

            if result.get("status") == "EXECUTED":

                with lock:
                    state["status"] = "PAPER TRADE OPENED"
                    state["position"] = trader.get_position()

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
                    state["status"] = "TRADE SKIPPED"

        except Exception as error:

            with lock:
                state["status"] = "ERROR"
                state["error"] = str(error)

            print(
                f"[PAPER BOT ERROR] {error}",
                flush=True,
            )

        time.sleep(POLL_SECONDS)


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
        args=(state, lock),
        daemon=True,
        name="autonomous-paper-bot",
    )

    thread.start()

    return state, lock, thread


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


def get_bot_snapshot():

    with bot_lock:
        return dict(bot_state)


snapshot = get_bot_snapshot()


# ============================================================
# PUBLIC MARKET
# ============================================================

ticker = get_ticker(
    symbol=st.session_state.selected_pair,
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
        ticker.get("last", 0)
    )

    change_pct = float(
        ticker.get("change_pct", 0)
    )

    high_price = float(
        ticker.get("high", 0)
    )

    low_price = float(
        ticker.get("low", 0)
    )

    volume = float(
        ticker.get("volume", 0)
    )


# ============================================================
# HEADER
# ============================================================

utc_now = datetime.now(
    timezone.utc
).strftime("%H:%M:%S UTC")


st.markdown(
    f"""
<div class="quant-header">
    <div class="logo-cube"></div>

    <div style="flex:1;">
        <div class="quant-title">
            PRO AI • QUANT MARKET TERMINAL
        </div>
        <div class="quant-sub">
            AUTONOMOUS PAPER EXECUTION / MARKET INTELLIGENCE
        </div>
    </div>

    <div style="text-align:right;font-family:monospace;">
        <span class="live-dot">● ONLINE</span>
        &nbsp;&nbsp;
        {utc_now}
    </div>
</div>
""",
    unsafe_allow_html=True,
)


st.markdown(
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
""",
    unsafe_allow_html=True,
)


# ============================================================
# MARKET SELECTORS
# ============================================================

scol1, scol2, scol3 = st.columns(
    [1.4, 1.4, 4]
)

with scol1:

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

    st.session_state.selected_pair = selected_pair


with scol2:

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


with scol3:

    st.markdown(
        "<div style='height:28px'></div>",
        unsafe_allow_html=True,
    )

    st.markdown(
        """
<span class="signal-pill green">● PAPER ACTIVE</span>
<span class="signal-pill cyan">PUBLIC MARKET DATA</span>
<span class="signal-pill yellow">AUTO TP/SL</span>
<span class="signal-pill purple">RISK ENGINE</span>
""",
        unsafe_allow_html=True,
    )


# Refresh selected ticker after selection
ticker = get_ticker(
    symbol=selected_pair,
    exchange="PUBLIC",
    api_key="",
    api_secret="",
    use_testnet=False,
)

if ticker:

    market_price = float(
        ticker.get("last", 0)
    )

    change_pct = float(
        ticker.get("change_pct", 0)
    )

    high_price = float(
        ticker.get("high", 0)
    )

    low_price = float(
        ticker.get("low", 0)
    )

    volume = float(
        ticker.get("volume", 0)
    )


# ============================================================
# TOP COMMAND CENTER
# ============================================================

account_col, chart_col, ai_col = st.columns(
    [1.05, 2.8, 1.25]
)


# ============================================================
# LEFT ACCOUNT PANEL
# ============================================================

with account_col:

    st.markdown(
        '<div class="panel-title">ACCOUNT / BOT STATE</div>',
        unsafe_allow_html=True,
    )

    st.markdown(
        f"""
<div class="panel">
    <div class="small-muted">PAPER EQUITY</div>

    <div class="big-money">
        ${snapshot['balance']:,.0f}
    </div>

    <br>

    <div class="small-muted">
        REALIZED P&L
    </div>

    <div class="green"
         style="font-size:20px;font-family:monospace;">
        ${snapshot['realized_pnl']:,.2f}
    </div>

    <hr style="border-color:#202833">

    <div class="small-muted">
        COMPLETED TRADES
    </div>

    <div style="font-size:18px;font-family:monospace;">
        {snapshot['trade_count']}
    </div>

    <br>

    <div class="small-muted">
        DAILY DRAWDOWN
    </div>

    <div class="yellow"
         style="font-size:17px;font-family:monospace;">
        {snapshot['drawdown']:.2f}%
    </div>

    <br>

    <div class="paper-warning">
        PAPER EXECUTION ONLY<br>
        REAL ORDERS DISABLED
    </div>
</div>
""",
        unsafe_allow_html=True,
    )


# ============================================================
# CENTER CHART
# ============================================================

with chart_col:

    st.markdown(
        '<div class="panel-title">LIVE PRICE / STRUCTURE</div>',
        unsafe_allow_html=True,
    )

    price_class = (
        "green"
        if change_pct >= 0
        else "red"
    )

    st.markdown(
        f"""
<div class="terminal-strip">
{selected_pair}
&nbsp;&nbsp;
<span class="{price_class}">
${market_price:,.2f}
</span>
&nbsp;&nbsp;
<span class="{price_class}">
{change_pct:+.2f}%
</span>
&nbsp;&nbsp;
HIGH ${high_price:,.2f}
&nbsp;&nbsp;
LOW ${low_price:,.2f}
</div>
""",
        unsafe_allow_html=True,
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
        border:1px solid #252e39;
        background:#070a0e;
    ">

        <div id="tv_chart"
             style="height:435px;width:100%;">
        </div>

        <script
        src="https://s3.tradingview.com/tv.js">
        </script>

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
            "gridColor": "#151b22"
        }});

        </script>
    </div>
    """

    components.html(
        tv_widget,
        height=440,
    )


# ============================================================
# RIGHT AI EXECUTION
# ============================================================

with ai_col:

    st.markdown(
        '<div class="panel-title">AI EXECUTION ENGINE</div>',
        unsafe_allow_html=True,
    )

    signal = snapshot.get(
        "signal",
        "NO TRADE",
    )

    score = snapshot.get(
        "score",
        0,
    )

    signal_color = (
        "green"
        if signal == "BUY"
        else (
            "red"
            if signal == "SELL"
            else "yellow"
        )
    )

    st.markdown(
        f"""
<div class="panel execution-card">

    <div class="small-muted">
        LIVE SIGNAL
    </div>

    <div class="{signal_color}"
         style="
         font-size:25px;
         font-family:monospace;
         font-weight:bold;
         ">
        {signal}
    </div>

    <br>

    <div class="small-muted">
        AI SCORE
    </div>

    <div class="ai-score">
        {score:+d}
    </div>

    <hr style="border-color:#202833">

    <div class="small-muted">
        BOT STATUS
    </div>

    <div style="
        font-family:monospace;
        font-size:12px;
        color:#dce4ec;">
        {snapshot['status']}
    </div>

    <br>

    <div class="small-muted">
        RISK / TRADE
    </div>

    <div class="cyan"
         style="font-family:monospace;">
        {RISK_PCT:.1f}%
    </div>

    <br>

    <div class="small-muted">
        TAKE PROFIT
    </div>

    <div class="green"
         style="font-family:monospace;">
        +{TP_PCT:.1f}%
    </div>

    <br>

    <div class="small-muted">
        STOP LOSS
    </div>

    <div class="red"
         style="font-family:monospace;">
        -{SL_PCT:.1f}%
    </div>

</div>
""",
        unsafe_allow_html=True,
    )


# ============================================================
# INDICATOR STRIP
# ============================================================

rsi_value = snapshot.get("rsi")
macd_value = snapshot.get("macd")

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
        rsi_state = "Overbought"

    elif float(rsi_value) <= 30:
        rsi_state = "Oversold"


trend_state = (
    "Bullish"
    if "Bullish trend"
    in snapshot.get(
        "reason",
        "",
    )
    else (
        "Bearish"
        if "Bearish trend"
        in snapshot.get(
            "reason",
            "",
        )
        else "Neutral"
    )
)


st.markdown(
    f"""
<div class="indicator-strip">

    <div class="indicator-card">
        <div class="ind-name">
            RSI 14
        </div>
        <div class="ind-value yellow">
            {rsi_text}
        </div>
        <div class="small-muted">
            {rsi_state}
        </div>
    </div>

    <div class="indicator-card">
        <div class="ind-name">
            MACD
        </div>
        <div class="ind-value cyan">
            {macd_text}
        </div>
        <div class="small-muted">
            momentum
        </div>
    </div>

    <div class="indicator-card">
        <div class="ind-name">
            TREND
        </div>
        <div class="ind-value green">
            {trend_state}
        </div>
        <div class="small-muted">
            EMA structure
        </div>
    </div>

    <div class="indicator-card">
        <div class="ind-name">
            SIGNAL SCORE
        </div>
        <div class="ind-value yellow">
            {snapshot.get('score', 0):+d}
        </div>
        <div class="small-muted">
            threshold ±4
        </div>
    </div>

    <div class="indicator-card">
        <div class="ind-name">
            BOT MARKET
        </div>
        <div class="ind-value purple">
            {PAPER_SYMBOL}
        </div>
        <div class="small-muted">
            autonomous
        </div>
    </div>

    <div class="indicator-card">
        <div class="ind-name">
            POLL RATE
        </div>
        <div class="ind-value cyan">
            {POLL_SECONDS}s
        </div>
        <div class="small-muted">
            scan cycle
        </div>
    </div>

</div>
""",
    unsafe_allow_html=True,
)


# ============================================================
# AI INTELLIGENCE NETWORK
# ============================================================

reason_text = snapshot.get(
    "reason",
    "",
)


st.markdown(
    f"""
<div class="intelligence">

    <div class="intelligence-title">
        AI MARKET INTELLIGENCE GRAPH //
        SIGNAL RELATIONSHIP ENGINE
    </div>

    <div class="link-line l1"></div>
    <div class="link-line l2"></div>
    <div class="link-line l3"></div>
    <div class="link-line l4"></div>
    <div class="link-line l5"></div>
    <div class="link-line l6"></div>

    <div class="node n1">
        RSI<br>
        {rsi_text}
    </div>

    <div class="node n2">
        MACD<br>
        {macd_text}
    </div>

    <div class="node n3">
        EMA<br>
        {trend_state}
    </div>

    <div class="node n4">
        RISK<br>
        {RISK_PCT:.1f}%
    </div>

    <div class="node n5">
        PRICE<br>
        ${market_price:,.0f}
    </div>

    <div class="node n6">
        TP/SL<br>
        AUTO
    </div>

    <div class="ai-core">
        AI CORE<br>
        SCORE<br>
        {snapshot.get('score', 0):+d}
    </div>

</div>
""",
    unsafe_allow_html=True,
)


# ============================================================
# BOTTOM ANALYTICS
# ============================================================

bottom_left, bottom_mid, bottom_right = st.columns(
    [1.45, 1.25, 1]
)


with bottom_left:

    st.markdown(
        '<div class="panel-title">SIGNAL ANALYSIS</div>',
        unsafe_allow_html=True,
    )

    st.markdown(
        f"""
<div class="panel">
    <div class="small-muted">
        CURRENT INTERPRETATION
    </div>

    <div style="
        font-family:monospace;
        margin-top:8px;
        line-height:1.7;
        ">
        {reason_text or "Waiting for analysis"}
    </div>

    <hr style="border-color:#202833">

    <div class="small-muted">
        LAST UPDATE
    </div>

    <div style="
        font-family:monospace;
        font-size:10px;
        ">
        {snapshot.get('last_update') or 'Starting'}
    </div>
</div>
""",
        unsafe_allow_html=True,
    )


with bottom_mid:

    st.markdown(
        '<div class="panel-title">PERFORMANCE</div>',
        unsafe_allow_html=True,
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


with bottom_right:

    st.markdown(
        '<div class="panel-title">RISK CONTROL</div>',
        unsafe_allow_html=True,
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
# OPEN POSITION
# ============================================================

position = snapshot.get(
    "position"
)


if position:

    st.markdown(
        '<div class="panel-title">ACTIVE PAPER POSITION</div>',
        unsafe_allow_html=True,
    )

    pos_df = pd.DataFrame(
        [
            {
                "Mode": "PAPER",
                "Symbol": position.get("symbol"),
                "Side": position.get("side"),
                "Quantity": position.get("quantity"),
                "Entry": position.get("entry_price"),
                "Take Profit": position.get("take_profit"),
                "Stop Loss": position.get("stop_loss"),
                "Opened": position.get("opened_at"),
            }
        ]
    )

    st.dataframe(
        pos_df,
        width="stretch",
        hide_index=True,
    )


# ============================================================
# LAST TRADE
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
# ERROR
# ============================================================

if snapshot.get("error"):

    st.error(
        snapshot["error"]
    )


# ============================================================
# FOOTER
# ============================================================

st.markdown(
    """
<div class="terminal-strip"
     style="margin-top:8px;">

PRO AI QUANT TERMINAL
&nbsp;&nbsp;•&nbsp;&nbsp;
AUTONOMOUS PAPER TRADING
&nbsp;&nbsp;•&nbsp;&nbsp;
PUBLIC MARKET FEED
&nbsp;&nbsp;•&nbsp;&nbsp;
REAL ORDER EXECUTION DISABLED

</div>
""",
    unsafe_allow_html=True,
)

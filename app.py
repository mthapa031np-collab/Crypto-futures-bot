"""
app.py

PRO AI TERMINAL
Autonomous Paper Trading Dashboard

Market data:
    UK-friendly public market_data.py provider

Trading logic:
    signal_engine.py
    risk_manager.py
    paper_trader.py

IMPORTANT:
    REAL AUTOMATIC ORDERS ARE DISABLED.
    This version is for autonomous PAPER TRADING only.
"""

import os
import time
import threading
from datetime import datetime, timezone

import streamlit as st
import pandas as pd
import numpy as np
import streamlit.components.v1 as components

from market_data import get_ticker, get_candles
from signal_engine import generate_signal
from risk_manager import calculate_trade_plan, validate_trade_plan
from paper_trader import PaperTrader


# ============================================================
# PAGE CONFIG
# ============================================================

st.set_page_config(
    page_title="PRO AI TERMINAL",
    page_icon="🤖",
    layout="wide",
    initial_sidebar_state="expanded",
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
# AVAILABLE MARKET SYMBOLS
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
    st.session_state.display_exchange = "Bybit"

if "trade_log" not in st.session_state:
    st.session_state.trade_log = []


# ============================================================
# STYLE
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
    padding-top: 0.7rem !important;
    padding-bottom: 1rem !important;
    padding-left: 0.9rem !important;
    padding-right: 0.9rem !important;
    max-width: 100% !important;
}

.stApp {
    background-color: #080a0d;
    color: #e7ebf2;
}

[data-testid="stSidebar"] {
    background-color: #0d1117;
    border-right: 1px solid #1f2937;
}

.hero {
    border: 1px solid #1f2937;
    background: linear-gradient(
        135deg,
        #0d1117,
        #101722
    );
    border-radius: 12px;
    padding: 14px 18px;
    margin-bottom: 12px;
}

.hero-title {
    font-size: 25px;
    font-weight: 800;
    color: #ffffff;
}

.hero-sub {
    font-size: 12px;
    color: #7f8ba3;
}

.safe-box {
    background: #0c2118;
    border: 1px solid #00c076;
    border-radius: 8px;
    padding: 10px;
    color: #8ce8bf;
    font-size: 12px;
}

.warn-box {
    background: #2c1b0d;
    border: 1px solid #ff9500;
    border-radius: 8px;
    padding: 10px;
    color: #ffc26b;
    font-size: 12px;
}

.bot-card {
    background: #0d1117;
    border: 1px solid #202938;
    border-radius: 10px;
    padding: 12px;
}

.status-green {
    color: #00c076;
    font-weight: 700;
}

.status-red {
    color: #ff4d4f;
    font-weight: 700;
}

.status-yellow {
    color: #f5b942;
    font-weight: 700;
}

.small-label {
    font-size: 10px;
    color: #69758b;
    text-transform: uppercase;
}

.market-price {
    font-size: 25px;
    font-weight: 800;
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

            # ------------------------------------------------
            # RESET DAILY RISK STATE
            # ------------------------------------------------

            if day_start_date != today:

                day_start_date = today
                day_start_balance = balance
                trading_paused = False

            # ------------------------------------------------
            # DAILY LOSS CIRCUIT BREAKER
            # ------------------------------------------------

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

                if (
                    drawdown_pct
                    >= MAX_DAILY_LOSS_PCT
                ):
                    trading_paused = True

            # ------------------------------------------------
            # UK-FRIENDLY PUBLIC CANDLES
            # ------------------------------------------------

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

            # ------------------------------------------------
            # EXISTING PAPER POSITION
            # ------------------------------------------------

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

                    state["price"] = current_price
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

                        state[
                            "last_trade"
                        ] = update_result

                        state[
                            "trade_count"
                        ] += 1

                        state[
                            "realized_pnl"
                        ] += float(
                            update_result.get(
                                "pnl",
                                0,
                            )
                        )

                    print(
                        "[PAPER BOT] "
                        f"CLOSED "
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

            # ------------------------------------------------
            # CIRCUIT BREAKER
            # ------------------------------------------------

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

            # ------------------------------------------------
            # SIGNAL ENGINE
            # RSI + MACD + EMA + BOLLINGER + VOLUME
            # ------------------------------------------------

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
                state["balance"] = (
                    trader.get_balance()
                )
                state["position"] = None
                state["drawdown"] = (
                    drawdown_pct
                )
                state["last_update"] = (
                    now_utc.isoformat()
                )

            # ------------------------------------------------
            # WAIT FOR STRONG SIGNAL
            # ------------------------------------------------

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

            # ------------------------------------------------
            # RISK MANAGEMENT
            # ------------------------------------------------

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

            # ------------------------------------------------
            # OPEN PAPER TRADE
            # ------------------------------------------------

            result = trader.open_trade(
                symbol=PAPER_SYMBOL,
                signal=signal,
                entry_price=current_price,
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
                    f"OPENED "
                    f"{PAPER_SYMBOL} "
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

                state["status"] = "ERROR"

                state["error"] = str(
                    error
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
# START BOT ONLY ONCE
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
# BOT SNAPSHOT
# ============================================================

def get_bot_snapshot():

    with bot_lock:
        return dict(
            bot_state
        )


snapshot = get_bot_snapshot()


# ============================================================
# SIDEBAR
# ============================================================

with st.sidebar:

    st.markdown(
        "## 🤖 PRO AI BOT"
    )

    st.markdown(
        """
<div class="safe-box">
✅ AUTONOMOUS PAPER MODE<br>
Real automatic orders are disabled.
</div>
""",
        unsafe_allow_html=True,
    )

    st.divider()

    st.markdown(
        "### 📡 Market Feed"
    )

    st.success(
        "Public UK-compatible feed"
    )

    st.caption(
        "Server-side Bybit/Binance API calls "
        "are disabled in this paper version."
    )

    st.divider()

    st.markdown(
        "### ⚙️ Bot Configuration"
    )

    st.write(
        f"**Bot Pair:** {PAPER_SYMBOL}"
    )

    st.write(
        f"**Poll:** {POLL_SECONDS}s"
    )

    st.write(
        f"**Risk:** {RISK_PCT}%"
    )

    st.write(
        f"**TP:** {TP_PCT}%"
    )

    st.write(
        f"**SL:** {SL_PCT}%"
    )

    st.write(
        f"**Daily Loss Limit:** "
        f"{MAX_DAILY_LOSS_PCT}%"
    )

    st.divider()

    st.markdown(
        "### 💰 Paper Account"
    )

    st.metric(
        "Balance",
        f"${snapshot['balance']:,.2f}",
    )

    st.metric(
        "Realized P&L",
        f"${snapshot['realized_pnl']:,.2f}",
    )

    st.metric(
        "Completed Trades",
        snapshot["trade_count"],
    )


# ============================================================
# HERO
# ============================================================

st.markdown(
    """
<div class="hero">
    <div class="hero-title">
        PRO AI FUTURES TERMINAL
    </div>
    <div class="hero-sub">
        Autonomous signal analysis • Risk engine •
        Paper execution • Automatic TP/SL
    </div>
</div>
""",
    unsafe_allow_html=True,
)


# ============================================================
# MARKET SELECTION
# ============================================================

top_a, top_b = st.columns(
    [
        1,
        1,
    ]
)

with top_a:

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


with top_b:

    display_exchange = st.selectbox(
        "TradingView Chart",
        [
            "Bybit",
            "Binance",
            "Coinbase",
        ],
    )

    st.session_state.display_exchange = (
        display_exchange
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
# MARKET METRICS
# ============================================================

m1, m2, m3, m4, m5 = st.columns(
    5
)

m1.metric(
    selected_pair,
    (
        f"${market_price:,.2f}"
        if market_price > 0
        else "Loading..."
    ),
)

m2.metric(
    "24h Change",
    f"{change_pct:+.2f}%",
)

m3.metric(
    "24h High",
    (
        f"${high_price:,.2f}"
        if high_price > 0
        else "—"
    ),
)

m4.metric(
    "24h Low",
    (
        f"${low_price:,.2f}"
        if low_price > 0
        else "—"
    ),
)

m5.metric(
    "Paper Balance",
    f"${snapshot['balance']:,.2f}",
)


st.divider()


# ============================================================
# AUTONOMOUS BOT STATUS
# ============================================================

st.markdown(
    "## 🧠 Autonomous AI Engine"
)

s1, s2, s3, s4, s5 = st.columns(
    [
        1.4,
        1,
        1,
        1,
        1.4,
    ]
)

s1.metric(
    "Bot Status",
    snapshot["status"],
)

s2.metric(
    "Signal",
    snapshot["signal"],
)

s3.metric(
    "Score",
    snapshot["score"],
)

rsi_value = snapshot.get(
    "rsi"
)

s4.metric(
    "RSI",
    (
        f"{float(rsi_value):.1f}"
        if rsi_value is not None
        else "—"
    ),
)

s5.metric(
    "Bot Market",
    PAPER_SYMBOL,
)


reason = snapshot.get(
    "reason"
)

if reason:

    st.caption(
        f"Signal analysis: {reason}"
    )

if snapshot.get(
    "error"
):

    st.error(
        snapshot["error"]
    )


# ============================================================
# CHART + BOT PANEL
# ============================================================

chart_col, bot_col = st.columns(
    [
        3,
        1.25,
    ]
)


with chart_col:

    # TradingView runs in the browser.
    # It is independent from the server market feed.

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
    <div
        class="tradingview-widget-container"
        style="height:550px;width:100%;"
    >

        <div
            id="tradingview_chart"
            style="height:550px;width:100%;"
        ></div>

        <script
            type="text/javascript"
            src="https://s3.tradingview.com/tv.js"
        ></script>

        <script type="text/javascript">

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
            "container_id": "tradingview_chart",
            "backgroundColor": "#080a0d",
            "gridColor": "#161b26"
        }});

        </script>

    </div>
    """

    components.html(
        tv_widget,
        height=560,
    )


with bot_col:

    st.markdown(
        "### ⚡ AI Execution"
    )

    st.markdown(
        """
<div class="safe-box">
🤖 AUTOMATIC PAPER EXECUTION<br><br>
The bot decides whether to BUY,
SELL or WAIT.<br><br>
TP and SL are calculated automatically.
</div>
""",
        unsafe_allow_html=True,
    )

    st.write("")

    st.metric(
        "Configured Risk",
        f"{RISK_PCT}%",
    )

    st.metric(
        "Take Profit",
        f"{TP_PCT}%",
    )

    st.metric(
        "Stop Loss",
        f"{SL_PCT}%",
    )

    st.metric(
        "Daily Drawdown",
        f"{snapshot['drawdown']:.2f}%",
    )

    st.caption(
        "No manual BUY/SELL button is required "
        "for the autonomous paper bot."
    )


# ============================================================
# CURRENT PAPER POSITION
# ============================================================

st.divider()

st.markdown(
    "## 📌 Current Paper Position"
)

position = snapshot.get(
    "position"
)


if position:

    pos_df = pd.DataFrame(
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
        pos_df,
        width="stretch",
        hide_index=True,
    )

else:

    st.info(
        "No paper position open. "
        "The AI is waiting for a qualifying signal."
    )


# ============================================================
# ANALYSIS + LOGS
# ============================================================

tab1, tab2, tab3 = st.tabs(
    [
        "🧠 Signal Analysis",
        "📊 Bot Statistics",
        "📜 Last Trade",
    ]
)


with tab1:

    st.code(
        f"""
AUTONOMOUS PAPER AI

Market Feed:
UK-compatible public market data

Bot Symbol:
{PAPER_SYMBOL}

Status:
{snapshot.get('status')}

Signal:
{snapshot.get('signal')}

Score:
{snapshot.get('score')}

RSI:
{snapshot.get('rsi')}

MACD:
{snapshot.get('macd')}

Reason:
{snapshot.get('reason')}

Last Update:
{snapshot.get('last_update')}

REAL AUTO ORDERS:
DISABLED
""",
        language="text",
    )


with tab2:

    stats_df = pd.DataFrame(
        [
            {
                "Starting Balance":
                    PAPER_BALANCE,

                "Current Balance":
                    snapshot[
                        "balance"
                    ],

                "Realized P&L":
                    snapshot[
                        "realized_pnl"
                    ],

                "Completed Trades":
                    snapshot[
                        "trade_count"
                    ],

                "Risk Per Trade %":
                    RISK_PCT,

                "TP %":
                    TP_PCT,

                "SL %":
                    SL_PCT,

                "Daily Loss Limit %":
                    MAX_DAILY_LOSS_PCT,
            }
        ]
    )

    st.dataframe(
        stats_df,
        width="stretch",
        hide_index=True,
    )


with tab3:

    last_trade = snapshot.get(
        "last_trade"
    )

    if last_trade:

        st.json(
            last_trade
        )

    else:

        st.info(
            "No completed paper trade yet."
        )


# ============================================================
# FOOTER
# ============================================================

st.divider()

st.caption(
    "PRO AI TERMINAL • Autonomous Paper Trading • "
    "Public market data • Real automatic orders disabled"
)

import os
import time
import threading
from datetime import datetime, timezone

import streamlit as st
import pandas as pd
import numpy as np
import streamlit.components.v1 as components

from exchanges import get_client
from market_data import get_candles
from signal_engine import generate_signal
from risk_manager import calculate_trade_plan, validate_trade_plan
from paper_trader import PaperTrader


# ============================================================
# PAGE CONFIG
# ============================================================

st.set_page_config(
    page_title="PRO AI TERMINAL",
    layout="wide",
    initial_sidebar_state="expanded",
)


# ============================================================
# ENVIRONMENT / PAPER BOT CONFIG
# ============================================================

PAPER_TRADING = (
    os.environ.get("PAPER_TRADING", "true").lower() == "true"
)

PAPER_EXCHANGE = os.environ.get(
    "EXCHANGE",
    "Bybit",
)

PAPER_SYMBOL = os.environ.get(
    "SYMBOL",
    "BTCUSDT",
)

PAPER_BALANCE = float(
    os.environ.get(
        "PAPER_BALANCE",
        "10000",
    )
)

PAPER_RISK_PCT = float(
    os.environ.get(
        "RISK_PCT",
        "1",
    )
)

PAPER_SL_PCT = float(
    os.environ.get(
        "SL_PCT",
        "1",
    )
)

PAPER_TP_PCT = float(
    os.environ.get(
        "TP_PCT",
        "2",
    )
)

PAPER_POLL_SECONDS = int(
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
# SESSION STATE
# ============================================================

if "order_mode" not in st.session_state:
    st.session_state.order_mode = "Limit"

if "use_testnet" not in st.session_state:
    # Important:
    # False prevents the UI from automatically calling
    # Binance/Bybit testnet endpoints.
    st.session_state.use_testnet = False

if "exchange" not in st.session_state:
    st.session_state.exchange = "Bybit"

if "trade_log" not in st.session_state:
    st.session_state.trade_log = []

if "api_key" not in st.session_state:
    st.session_state.api_key = ""

if "api_secret" not in st.session_state:
    st.session_state.api_secret = ""


# ============================================================
# STYLING
# ============================================================

st.markdown(
    """
<style>

#MainMenu, footer, header {
    visibility: hidden;
}

.block-container {
    padding-top: 0.5rem !important;
    padding-bottom: 0rem !important;
    padding-left: 0.8rem !important;
    padding-right: 0.8rem !important;
    max-width: 100% !important;
}

.stApp {
    background-color: #080a0d;
    color: #9097a6;
}

.stat-label {
    font-size: 10px;
    color: #5d6578;
    text-transform: uppercase;
}

.stat-value {
    font-size: 13px;
    font-weight: bold;
    color: #e1e4ea;
}

.val-green {
    color: #00c076 !important;
}

.val-red {
    color: #ff4d4f !important;
}

div[data-baseweb="select"] > div,
div[data-baseweb="input"] > div {
    background-color: #131824 !important;
    border-color: #202738 !important;
    color: #ffffff !important;
}

.ob-header {
    font-size: 11px;
    font-weight: 700;
    color: #60687b;
    text-transform: uppercase;
    margin-bottom: 6px;
}

.rsi-box {
    background: #131824;
    border: 1px solid #202738;
    border-radius: 6px;
    padding: 8px;
    text-align: center;
}

.warn-box {
    background: #2a1810;
    border: 1px solid #ff8a00;
    border-radius: 6px;
    padding: 8px;
    font-size: 12px;
    color: #ffb84d;
}

.safe-box {
    background: #0d2018;
    border: 1px solid #00c076;
    border-radius: 6px;
    padding: 8px;
    font-size: 12px;
    color: #79e8b7;
}

.exch-badge {
    display: inline-block;
    background: #131824;
    border: 1px solid #202738;
    border-radius: 4px;
    padding: 2px 8px;
    font-size: 11px;
    color: #e1e4ea;
}

.paper-card {
    background: #10151f;
    border: 1px solid #202738;
    border-radius: 8px;
    padding: 12px;
    margin-top: 6px;
}

</style>
""",
    unsafe_allow_html=True,
)


# ============================================================
# SYMBOLS
# ============================================================

TOP_SYMBOLS = [
    "BTCUSDT",
    "ETHUSDT",
    "SOLUSDT",
    "BNBUSDT",
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
# LOCAL RSI FOR UI
# ============================================================

def calculate_rsi(
    closes,
    period=14,
):
    delta = closes.diff()

    gain = delta.where(
        delta > 0,
        0.0,
    )

    loss = -delta.where(
        delta < 0,
        0.0,
    )

    avg_gain = gain.rolling(
        period
    ).mean()

    avg_loss = loss.rolling(
        period
    ).mean()

    rs = (
        avg_gain
        / avg_loss.replace(
            0,
            np.nan,
        )
    )

    rsi = 100 - (
        100 / (1 + rs)
    )

    return rsi.fillna(50)


# ============================================================
# POSITION SIZE
# ============================================================

def calc_position_size(
    balance,
    risk_pct,
    entry_price,
    sl_price,
):
    if (
        balance is None
        or entry_price is None
        or sl_price is None
    ):
        return 0.0

    risk_amount = (
        balance
        * (risk_pct / 100)
    )

    sl_distance = abs(
        entry_price - sl_price
    )

    if sl_distance <= 0:
        return 0.0

    return round(
        risk_amount / sl_distance,
        6,
    )


# ============================================================
# AUTONOMOUS PAPER BOT LOOP
# ============================================================

def paper_bot_loop(
    state,
    lock,
):
    trader = PaperTrader(
        starting_balance=PAPER_BALANCE
    )

    day_start_balance = PAPER_BALANCE
    day_start_date = None
    trading_paused = False

    while True:

        try:

            # ------------------------------------------------
            # Daily loss protection
            # ------------------------------------------------

            today = datetime.now(
                timezone.utc
            ).date()

            balance = trader.get_balance()

            if day_start_date != today:

                day_start_date = today
                day_start_balance = balance
                trading_paused = False

            if day_start_balance > 0:

                drawdown_pct = (
                    (day_start_balance - balance)
                    / day_start_balance
                    * 100
                )

                if (
                    drawdown_pct
                    >= MAX_DAILY_LOSS_PCT
                ):
                    trading_paused = True

            # ------------------------------------------------
            # PUBLIC MARKET DATA ONLY
            # No API key is used here.
            # ------------------------------------------------

            candles = get_candles(
                exchange=PAPER_EXCHANGE,
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
                        "Waiting for public market data"
                    )

                time.sleep(
                    PAPER_POLL_SECONDS
                )

                continue

            price = float(
                candles["close"].iloc[-1]
            )

            # ------------------------------------------------
            # Monitor existing simulated position
            # ------------------------------------------------

            existing_position = (
                trader.get_position()
            )

            if existing_position:

                update_result = (
                    trader.update_price(
                        price
                    )
                )

                with lock:

                    state["price"] = price

                    state["balance"] = (
                        trader.get_balance()
                    )

                    state["position"] = (
                        trader.get_position()
                    )

                    if (
                        update_result
                        and update_result.get(
                            "status"
                        )
                        == "CLOSED"
                    ):

                        state[
                            "last_trade"
                        ] = update_result

                        state[
                            "status"
                        ] = (
                            "Paper trade closed: "
                            f"{update_result.get('reason')}"
                        )

                        state[
                            "trade_count"
                        ] += 1

                    else:

                        state[
                            "status"
                        ] = (
                            "Paper position open"
                        )

                time.sleep(
                    PAPER_POLL_SECONDS
                )

                continue

            # ------------------------------------------------
            # Do not open new trade if daily breaker triggered
            # ------------------------------------------------

            if trading_paused:

                with lock:
                    state[
                        "status"
                    ] = (
                        "Paused by daily loss limit"
                    )

                time.sleep(
                    PAPER_POLL_SECONDS
                )

                continue

            # ------------------------------------------------
            # AI SIGNAL ENGINE
            # RSI + MACD + Bollinger + EMA + Volume
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

            signal_rsi = signal_data.get(
                "rsi",
                0,
            )

            with lock:

                state["price"] = price
                state["signal"] = signal
                state["score"] = score
                state["reason"] = reason
                state["rsi"] = signal_rsi
                state["balance"] = (
                    trader.get_balance()
                )
                state["position"] = None

            # ------------------------------------------------
            # No trade unless signal is strong enough
            # ------------------------------------------------

            if signal not in (
                "BUY",
                "SELL",
            ):

                with lock:
                    state[
                        "status"
                    ] = (
                        "Scanning market"
                    )

                time.sleep(
                    PAPER_POLL_SECONDS
                )

                continue

            # ------------------------------------------------
            # Risk Manager
            # ------------------------------------------------

            trade_plan = (
                calculate_trade_plan(
                    balance=trader.get_balance(),
                    entry_price=price,
                    signal=signal,
                    risk_percent=PAPER_RISK_PCT,
                    stop_loss_percent=PAPER_SL_PCT,
                    take_profit_percent=PAPER_TP_PCT,
                )
            )

            if not validate_trade_plan(
                trade_plan
            ):

                with lock:
                    state[
                        "status"
                    ] = (
                        "Signal rejected "
                        "by risk manager"
                    )

                time.sleep(
                    PAPER_POLL_SECONDS
                )

                continue

            # ------------------------------------------------
            # OPEN SIMULATED TRADE
            # ------------------------------------------------

            open_result = (
                trader.open_trade(
                    symbol=PAPER_SYMBOL,
                    signal=signal,
                    entry_price=price,
                    quantity=trade_plan[
                        "quantity"
                    ],
                    take_profit=trade_plan[
                        "take_profit"
                    ],
                    stop_loss=trade_plan[
                        "stop_loss"
                    ],
                )
            )

            with lock:

                state[
                    "position"
                ] = trader.get_position()

                if (
                    open_result.get(
                        "status"
                    )
                    == "EXECUTED"
                ):

                    state[
                        "status"
                    ] = (
                        "Paper trade opened"
                    )

                else:

                    state[
                        "status"
                    ] = (
                        "Paper trade skipped"
                    )

            print(
                "[PAPER BOT] "
                f"{datetime.now(timezone.utc).isoformat()} "
                f"{PAPER_EXCHANGE} "
                f"{PAPER_SYMBOL} "
                f"signal={signal} "
                f"score={score} "
                f"price={price}",
                flush=True,
            )

        except Exception as error:

            with lock:

                state[
                    "status"
                ] = (
                    f"Error: {error}"
                )

            print(
                "[PAPER BOT ERROR] "
                f"{error}",
                flush=True,
            )

        time.sleep(
            PAPER_POLL_SECONDS
        )


# ============================================================
# START PAPER BOT ONCE
# ============================================================

@st.cache_resource
def start_paper_bot():

    state = {
        "status": "Starting",
        "price": None,
        "signal": "NO TRADE",
        "score": 0,
        "reason": "",
        "rsi": None,
        "balance": PAPER_BALANCE,
        "position": None,
        "last_trade": None,
        "trade_count": 0,
    }

    lock = threading.Lock()

    thread = threading.Thread(
        target=paper_bot_loop,
        args=(state, lock),
        daemon=True,
        name="paper-trading-bot",
    )

    thread.start()

    return (
        state,
        lock,
        thread,
    )


if PAPER_TRADING:

    (
        paper_bot_state,
        paper_bot_lock,
        paper_bot_thread,
    ) = start_paper_bot()

else:

    paper_bot_state = {
        "status": "Paper trading disabled",
        "price": None,
        "signal": "NO TRADE",
        "score": 0,
        "reason": "",
        "rsi": None,
        "balance": PAPER_BALANCE,
        "position": None,
        "last_trade": None,
        "trade_count": 0,
    }

    paper_bot_lock = None
    paper_bot_thread = None


# ============================================================
# SIDEBAR
# ============================================================

with st.sidebar:

    st.markdown(
        "### 🤖 Autonomous Paper Bot"
    )

    if PAPER_TRADING:

        st.markdown(
            "<div class='safe-box'>"
            "✅ PAPER MODE ACTIVE<br>"
            "No real automatic orders are sent."
            "</div>",
            unsafe_allow_html=True,
        )

    else:

        st.warning(
            "Paper trading disabled."
        )

    if paper_bot_lock:

        with paper_bot_lock:

            bot_status = (
                paper_bot_state[
                    "status"
                ]
            )

            bot_balance = (
                paper_bot_state[
                    "balance"
                ]
            )

            bot_signal = (
                paper_bot_state[
                    "signal"
                ]
            )

            bot_score = (
                paper_bot_state[
                    "score"
                ]
            )

    else:

        bot_status = (
            paper_bot_state[
                "status"
            ]
        )

        bot_balance = (
            paper_bot_state[
                "balance"
            ]
        )

        bot_signal = (
            paper_bot_state[
                "signal"
            ]
        )

        bot_score = (
            paper_bot_state[
                "score"
            ]
        )

    st.caption(
        f"Bot: {bot_status}"
    )

    st.metric(
        "Paper Balance",
        f"${bot_balance:,.2f}",
    )

    st.metric(
        "AI Signal",
        bot_signal,
    )

    st.caption(
        f"Signal score: {bot_score}"
    )

    st.divider()

    st.markdown(
        "### 📊 Market Display"
    )

    st.session_state.exchange = (
        st.selectbox(
            "Exchange",
            [
                "Bybit",
                "Binance",
            ],
            index=[
                "Bybit",
                "Binance",
            ].index(
                st.session_state.exchange
            ),
        )
    )

    st.session_state.use_testnet = (
        st.toggle(
            "Use Testnet for manual API",
            value=st.session_state.use_testnet,
        )
    )

    st.session_state.api_key = (
        st.text_input(
            "API Key",
            type="password",
            value=st.session_state.get(
                "api_key",
                "",
            ),
        )
    )

    st.session_state.api_secret = (
        st.text_input(
            "API Secret",
            type="password",
            value=st.session_state.get(
                "api_secret",
                "",
            ),
        )
    )

    st.caption(
        "API keys are optional for market display. "
        "The autonomous paper bot does not use them."
    )

    st.divider()

    st.markdown(
        "### 🛡️ Display Risk Settings"
    )

    risk_pct = st.slider(
        "Risk per trade (%)",
        0.5,
        5.0,
        1.0,
        0.5,
    )

    rsi_oversold = st.slider(
        "RSI Oversold",
        10,
        40,
        30,
    )

    rsi_overbought = st.slider(
        "RSI Overbought",
        60,
        90,
        70,
    )


# ============================================================
# PUBLIC MARKET CLIENT
# ============================================================

api_key = st.session_state.get(
    "api_key",
    "",
)

api_secret = st.session_state.get(
    "api_secret",
    "",
)

client = get_client(
    st.session_state.exchange,
    api_key,
    api_secret,
    st.session_state.use_testnet,
)


# ============================================================
# HEADER
# ============================================================

c_sel, c_p, c_ch, c_hi, c_lo, c_bal = (
    st.columns(
        [
            1.5,
            1,
            1,
            1,
            1,
            1.5,
        ]
    )
)


with c_sel:

    selected_pair = st.selectbox(
        "Select Crypto Pair",
        TOP_SYMBOLS,
        index=0,
    )

    environment_label = (
        "TESTNET"
        if st.session_state.use_testnet
        else "PUBLIC"
    )

    st.markdown(
        f"<span class='exch-badge'>"
        f"{st.session_state.exchange} "
        f"{environment_label}"
        f"</span>",
        unsafe_allow_html=True,
    )


# ============================================================
# TICKER
# ============================================================

ticker = client.get_ticker(
    selected_pair
)

last_price = 0.0

if ticker:

    last_price = ticker[
        "last"
    ]

    price_change = ticker[
        "change_pct"
    ]

    change_css = (
        "val-green"
        if price_change >= 0
        else "val-red"
    )

    with c_p:

        st.markdown(
            "<div class='stat-label'>"
            "Market Price"
            "</div>"
            f"<div class='stat-value {change_css}'>"
            f"${last_price:,.2f}"
            "</div>",
            unsafe_allow_html=True,
        )

    with c_ch:

        st.markdown(
            "<div class='stat-label'>"
            "24h Change"
            "</div>"
            f"<div class='stat-value {change_css}'>"
            f"{price_change:+.2f}%"
            "</div>",
            unsafe_allow_html=True,
        )

    with c_hi:

        st.markdown(
            "<div class='stat-label'>"
            "24h High"
            "</div>"
            "<div class='stat-value'>"
            f"${ticker['high']:,.2f}"
            "</div>",
            unsafe_allow_html=True,
        )

    with c_lo:

        st.markdown(
            "<div class='stat-label'>"
            "24h Low"
            "</div>"
            "<div class='stat-value'>"
            f"${ticker['low']:,.2f}"
            "</div>",
            unsafe_allow_html=True,
        )

else:

    with c_p:

        st.markdown(
            "<div class='stat-label'>"
            "Market Price"
            "</div>"
            "<div class='stat-value'>"
            "Connecting..."
            "</div>",
            unsafe_allow_html=True,
        )


# ============================================================
# BALANCE DISPLAY
# ============================================================

if api_key and api_secret:

    live_balance = (
        client.get_balance()
    )

    if live_balance is not None:

        bal_display = (
            f"${live_balance:,.2f} USDT"
        )

    else:

        bal_display = (
            "API unavailable"
        )

else:

    live_balance = None

    bal_display = (
        f"Paper ${bot_balance:,.2f}"
    )


with c_bal:

    st.markdown(
        "<div class='stat-label' "
        "style='text-align:right;'>"
        "Account / Paper Balance"
        "</div>"
        "<div class='stat-value val-green' "
        "style='text-align:right;'>"
        f"{bal_display}"
        "</div>",
        unsafe_allow_html=True,
    )


st.divider()


# ============================================================
# PAPER BOT STATUS BAR
# ============================================================

st.markdown(
    "### 🤖 Autonomous Paper Trading"
)

paper_cols = st.columns(
    [
        1.5,
        1,
        1,
        1,
        2,
    ]
)

if paper_bot_lock:

    with paper_bot_lock:

        p_status = (
            paper_bot_state[
                "status"
            ]
        )

        p_signal = (
            paper_bot_state[
                "signal"
            ]
        )

        p_score = (
            paper_bot_state[
                "score"
            ]
        )

        p_balance = (
            paper_bot_state[
                "balance"
            ]
        )

        p_position = (
            paper_bot_state[
                "position"
            ]
        )

        p_reason = (
            paper_bot_state[
                "reason"
            ]
        )

else:

    p_status = "Disabled"
    p_signal = "NO TRADE"
    p_score = 0
    p_balance = PAPER_BALANCE
    p_position = None
    p_reason = ""


paper_cols[0].metric(
    "Status",
    p_status,
)

paper_cols[1].metric(
    "Signal",
    p_signal,
)

paper_cols[2].metric(
    "Score",
    p_score,
)

paper_cols[3].metric(
    "Paper Balance",
    f"${p_balance:,.2f}",
)

paper_cols[4].markdown(
    f"**Reason:** {p_reason or 'Waiting for signal'}"
)

if p_position:

    st.success(
        f"OPEN PAPER POSITION — "
        f"{p_position['side']} "
        f"{p_position['symbol']} | "
        f"Entry ${p_position['entry_price']:,.2f} | "
        f"TP ${p_position['take_profit']:,.2f} | "
        f"SL ${p_position['stop_loss']:,.2f}"
    )

else:

    st.caption(
        "No paper position currently open."
    )


st.divider()


# ============================================================
# RSI CALCULATION
# ============================================================

klines_df = client.get_klines(
    selected_pair,
    15,
    100,
)

current_rsi = None

if klines_df is not None:

    rsi_series = calculate_rsi(
        klines_df["close"]
    )

    current_rsi = float(
        rsi_series.iloc[-1]
    )


# ============================================================
# MAIN GRID
# ============================================================

col_chart, col_depth, col_exec = (
    st.columns(
        [
            3.0,
            1.2,
            1.4,
        ]
    )
)


# ============================================================
# TRADINGVIEW
# ============================================================

with col_chart:

    tv_prefix = (
        "BYBIT"
        if st.session_state.exchange
        == "Bybit"
        else "BINANCE"
    )

    tv_widget = f"""
    <div class="tradingview-widget-container"
         style="height:520px;width:100%;">

        <div id="tradingview_chart"
             style="height:520px;width:100%;">
        </div>

        <script
        type="text/javascript"
        src="https://s3.tradingview.com/tv.js">
        </script>

        <script type="text/javascript">

        new TradingView.widget({{
            "autosize": true,
            "symbol": "{tv_prefix}:{selected_pair}",
            "interval": "15",
            "timezone": "Etc/UTC",
            "theme": "dark",
            "style": "1",
            "locale": "en",
            "enable_publishing": false,
            "hide_side_toolbar": false,
            "allow_symbol_change": true,
            "container_id": "tradingview_chart",
            "backgroundColor": "#0d1117",
            "gridColor": "#161b26"
        }});

        </script>

    </div>
    """

    components.html(
        tv_widget,
        height=525,
    )

    if current_rsi is not None:

        rsi_css = (
            "val-red"
            if current_rsi
            > rsi_overbought
            else (
                "val-green"
                if current_rsi
                < rsi_oversold
                else ""
            )
        )

        signal_text = (
            "OVERBOUGHT"
            if current_rsi
            > rsi_overbought
            else (
                "OVERSOLD"
                if current_rsi
                < rsi_oversold
                else "Neutral"
            )
        )

        st.markdown(
            "<div class='rsi-box'>"
            "<span class='stat-label'>"
            "RSI (14, 15m)"
            "</span><br>"
            f"<span class='stat-value {rsi_css}' "
            "style='font-size:18px;'>"
            f"{current_rsi:.1f}"
            "</span>"
            f" — {signal_text}"
            "</div>",
            unsafe_allow_html=True,
        )


# ============================================================
# ORDER BOOK DISPLAY
# ============================================================

with col_depth:

    st.markdown(
        "<div class='ob-header'>"
        "📊 Market Depth"
        "</div>",
        unsafe_allow_html=True,
    )

    if last_price > 0:

        step = (
            last_price
            * 0.0003
        )

        asks_df = pd.DataFrame(
            {
                "Price ($)": [
                    round(
                        last_price
                        + (i * step),
                        2,
                    )
                    for i
                    in range(
                        5,
                        0,
                        -1,
                    )
                ],
                "Size": [
                    0.35,
                    1.12,
                    0.08,
                    2.45,
                    0.91,
                ],
            }
        )

        bids_df = pd.DataFrame(
            {
                "Price ($)": [
                    round(
                        last_price
                        - (i * step),
                        2,
                    )
                    for i
                    in range(
                        1,
                        6,
                    )
                ],
                "Size": [
                    1.45,
                    0.62,
                    3.12,
                    0.85,
                    1.10,
                ],
            }
        )

        st.caption(
            "🔴 Illustrative asks"
        )

        st.dataframe(
            asks_df,
            width="stretch",
            height=170,
            hide_index=True,
        )

        st.markdown(
            f"<div style='font-size:14px;"
            "font-weight:bold;"
            "color:#00c076;"
            "text-align:center;"
            "margin:6px 0;'>"
            f"${last_price:,.2f}"
            "</div>",
            unsafe_allow_html=True,
        )

        st.caption(
            "🟢 Illustrative bids"
        )

        st.dataframe(
            bids_df,
            width="stretch",
            height=170,
            hide_index=True,
        )

    else:

        st.info(
            "Loading market..."
        )


# ============================================================
# EXECUTION PANEL
# ============================================================

with col_exec:

    st.markdown(
        "<div class='ob-header'>"
        "⚡ Paper Execution"
        "</div>",
        unsafe_allow_html=True,
    )

    st.success(
        "🤖 Autonomous Paper Mode"
    )

    st.caption(
        "The background AI bot automatically "
        "scans signals and opens simulated trades."
    )

    if last_price > 0:

        demo_tp = (
            last_price
            * (
                1
                + PAPER_TP_PCT
                / 100
            )
        )

        demo_sl = (
            last_price
            * (
                1
                - PAPER_SL_PCT
                / 100
            )
        )

        st.metric(
            "Market",
            f"${last_price:,.2f}",
        )

        st.metric(
            "Configured TP",
            f"{PAPER_TP_PCT}%",
        )

        st.metric(
            "Configured SL",
            f"{PAPER_SL_PCT}%",
        )

        st.metric(
            "Risk",
            f"{PAPER_RISK_PCT}%",
        )

        st.caption(
            f"Example LONG TP "
            f"${demo_tp:,.2f} | "
            f"SL ${demo_sl:,.2f}"
        )

    st.markdown(
        "<div class='safe-box'>"
        "REAL AUTO ORDERS ARE DISABLED.<br>"
        "This stage is for paper testing only."
        "</div>",
        unsafe_allow_html=True,
    )


# ============================================================
# BOTTOM TABS
# ============================================================

st.divider()

st.subheader(
    "📋 AI Bot Positions & Logs"
)

tab_pos, tab_logs = (
    st.tabs(
        [
            "Paper Position",
            "AI Strategy Status",
        ]
    )
)


with tab_pos:

    if paper_bot_lock:

        with paper_bot_lock:

            current_paper_position = (
                paper_bot_state[
                    "position"
                ]
            )

            latest_paper_trade = (
                paper_bot_state[
                    "last_trade"
                ]
            )

    else:

        current_paper_position = None
        latest_paper_trade = None

    if current_paper_position:

        pos_df = pd.DataFrame(
            [
                {
                    "Mode": "PAPER",
                    "Exchange Data": PAPER_EXCHANGE,
                    "Symbol": current_paper_position[
                        "symbol"
                    ],
                    "Side": current_paper_position[
                        "side"
                    ],
                    "Quantity": current_paper_position[
                        "quantity"
                    ],
                    "Entry": current_paper_position[
                        "entry_price"
                    ],
                    "Take Profit": current_paper_position[
                        "take_profit"
                    ],
                    "Stop Loss": current_paper_position[
                        "stop_loss"
                    ],
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
            "No autonomous paper position open."
        )

    if latest_paper_trade:

        st.markdown(
            "#### Last Closed Paper Trade"
        )

        st.json(
            latest_paper_trade
        )


with tab_logs:

    if paper_bot_lock:

        with paper_bot_lock:

            bot_snapshot = dict(
                paper_bot_state
            )

    else:

        bot_snapshot = dict(
            paper_bot_state
        )

    st.code(
        f"""
Mode: PAPER TRADING
Exchange market data: {PAPER_EXCHANGE}
Symbol: {PAPER_SYMBOL}

Bot Status: {bot_snapshot.get('status')}
Signal: {bot_snapshot.get('signal')}
Signal Score: {bot_snapshot.get('score')}
RSI: {bot_snapshot.get('rsi')}
Signal Reason: {bot_snapshot.get('reason')}

Paper Balance: ${bot_snapshot.get('balance', 0):,.2f}
Completed Trades: {bot_snapshot.get('trade_count', 0)}

Risk per Trade: {PAPER_RISK_PCT}%
Take Profit: {PAPER_TP_PCT}%
Stop Loss: {PAPER_SL_PCT}%
Daily Loss Limit: {MAX_DAILY_LOSS_PCT}%

REAL AUTOMATIC ORDERS: DISABLED
""",
        language="text",
    )

import streamlit as st
import pandas as pd
import requests
import streamlit.components.v1 as components
from datetime import datetime


# ============================================================
# PRO AI TRADING TERMINAL
# Version 4.0
# Live Market Data + Futures + Paper Trading
# REAL MONEY TRADING IS DISABLED
# ============================================================

st.set_page_config(
    page_title="Pro AI Trading Terminal",
    page_icon="📊",
    layout="wide",
    initial_sidebar_state="expanded",
)


# ============================================================
# CONFIGURATION
# ============================================================

BYBIT_API = "https://api.bybit.com"
BINANCE_API = "https://api.binance.com"

SYMBOLS = {
    "BTC/USDT": "BTCUSDT",
    "ETH/USDT": "ETHUSDT",
    "SOL/USDT": "SOLUSDT",
    "XRP/USDT": "XRPUSDT",
    "BNB/USDT": "BNBUSDT",
    "DOGE/USDT": "DOGEUSDT",
    "ADA/USDT": "ADAUSDT",
    "LINK/USDT": "LINKUSDT",
}

HEADERS = {
    "User-Agent": "Pro-AI-Trading-Terminal/4.0",
    "Accept": "application/json",
}


# ============================================================
# PROFESSIONAL THEME
# ============================================================

st.markdown(
    """
    <style>

    .stApp {
        background-color: #0b0e11;
        color: #eaecef;
    }

    [data-testid="stSidebar"] {
        background-color: #11161d;
        border-right: 1px solid #2b3139;
    }

    [data-testid="stHeader"] {
        background-color: #0b0e11;
    }

    .block-container {
        max-width: 1600px;
        padding-top: 1.2rem;
        padding-bottom: 2rem;
    }

    h1, h2, h3 {
        color: #f0f2f4 !important;
    }

    .terminal-header {
        padding: 18px 20px;
        border: 1px solid #2b3139;
        border-radius: 14px;
        background: linear-gradient(
            135deg,
            #11161d,
            #161c24
        );
        margin-bottom: 18px;
    }

    .terminal-title {
        font-size: 28px;
        font-weight: 800;
        color: #f0f2f4;
    }

    .terminal-subtitle {
        color: #848e9c;
        margin-top: 5px;
        font-size: 13px;
    }

    .section-title {
        font-size: 19px;
        font-weight: 750;
        color: #f0f2f4;
        margin-top: 18px;
        margin-bottom: 10px;
    }

    .status-online {
        color: #0ecb81;
        font-weight: 700;
    }

    .status-warning {
        color: #f0b90b;
        font-weight: 700;
    }

    .status-offline {
        color: #f6465d;
        font-weight: 700;
    }

    </style>
    """,
    unsafe_allow_html=True,
)


# ============================================================
# SESSION STATE
# ============================================================

if "paper_balance" not in st.session_state:
    st.session_state.paper_balance = 10000.0

if "paper_positions" not in st.session_state:
    st.session_state.paper_positions = []

if "trade_history" not in st.session_state:
    st.session_state.trade_history = []

if "last_refresh" not in st.session_state:
    st.session_state.last_refresh = datetime.now()


# ============================================================
# HELPER
# ============================================================

def safe_float(value, default=0.0):
    try:
        return float(value)
    except Exception:
        return default


# ============================================================
# BYBIT TICKER
# ============================================================

@st.cache_data(ttl=5)
def get_bybit_ticker(symbol):
    try:
        response = requests.get(
            f"{BYBIT_API}/v5/market/tickers",
            params={
                "category": "linear",
                "symbol": symbol,
            },
            headers=HEADERS,
            timeout=8,
        )

        response.raise_for_status()

        data = response.json()

        if data.get("retCode") != 0:
            return None

        items = (
            data.get("result", {})
            .get("list", [])
        )

        if not items:
            return None

        item = items[0]

        return {
            "price": safe_float(
                item.get("lastPrice")
            ),
            "change": safe_float(
                item.get("price24hPcnt")
            ) * 100,
            "high": safe_float(
                item.get("highPrice24h")
            ),
            "low": safe_float(
                item.get("lowPrice24h")
            ),
            "volume": safe_float(
                item.get("turnover24h")
            ),
            "source": "BYBIT",
        }

    except Exception:
        return None


# ============================================================
# BINANCE FALLBACK
# ============================================================

@st.cache_data(ttl=5)
def get_binance_ticker(symbol):
    try:
        response = requests.get(
            f"{BINANCE_API}/api/v3/ticker/24hr",
            params={
                "symbol": symbol,
            },
            headers=HEADERS,
            timeout=8,
        )

        response.raise_for_status()

        data = response.json()

        return {
            "price": safe_float(
                data.get("lastPrice")
            ),
            "change": safe_float(
                data.get("priceChangePercent")
            ),
            "high": safe_float(
                data.get("highPrice")
            ),
            "low": safe_float(
                data.get("lowPrice")
            ),
            "volume": safe_float(
                data.get("quoteVolume")
            ),
            "source": "BINANCE",
        }

    except Exception:
        return None


# ============================================================
# LIVE TICKER
# ============================================================

def get_ticker(symbol):

    data = get_bybit_ticker(symbol)

    if data:
        return data

    return get_binance_ticker(symbol)


# ============================================================
# ORDER BOOK
# ============================================================

@st.cache_data(ttl=3)
def get_orderbook(symbol):

    try:

        response = requests.get(
            f"{BYBIT_API}/v5/market/orderbook",
            params={
                "category": "linear",
                "symbol": symbol,
                "limit": 10,
            },
            headers=HEADERS,
            timeout=8,
        )

        response.raise_for_status()

        data = response.json()

        if data.get("retCode") != 0:
            return None

        result = data.get(
            "result",
            {}
        )

        bids = result.get(
            "b",
            []
        )

        asks = result.get(
            "a",
            []
        )

        return {
            "bids": bids,
            "asks": asks,
        }

    except Exception:
        return None


# ============================================================
# TRADINGVIEW CHART
# ============================================================

def tradingview_chart(
    symbol,
    interval="15",
    height=600,
):

    tv_symbol = f"BINANCE:{symbol}USDT"

    html = f"""
    <div id="tv_chart" style="height:{height}px;width:100%;"></div>

    <script src="https://s3.tradingview.com/tv.js"></script>

    <script>
    new TradingView.widget({{
        "autosize": true,
        "symbol": "{tv_symbol}",
        "interval": "{interval}",
        "timezone": "Etc/UTC",
        "theme": "dark",
        "style": "1",
        "locale": "en",
        "toolbar_bg": "#11161d",
        "enable_publishing": false,
        "hide_side_toolbar": false,
        "allow_symbol_change": true,
        "container_id": "tv_chart"
    }});
    </script>
    """

    return html


# ============================================================
# SIDEBAR
# ============================================================

st.sidebar.title("📊 PRO AI TERMINAL")

st.sidebar.caption(
    "Professional Crypto Trading Dashboard"
)

page = st.sidebar.radio(
    "Navigation",
    [
        "🏠 Dashboard",
        "📈 Markets",
        "⚡ Futures",
        "💼 Portfolio",
        "🧪 Paper Trading",
    ],
)

st.sidebar.divider()

st.sidebar.subheader("System")

st.sidebar.markdown(
    "🟢 **Market Data:** ONLINE"
)

st.sidebar.markdown(
    "🟢 **Chart Engine:** ONLINE"
)

st.sidebar.markdown(
    "🟡 **AI Engine:** READY"
)

st.sidebar.markdown(
    "🔴 **Real Trading:** DISABLED"
)

st.sidebar.divider()

st.sidebar.caption(
    "Paper trading only"
)

st.sidebar.caption(
    f"Updated: "
    f"{st.session_state.last_refresh.strftime('%H:%M:%S')}"
)


# ============================================================
# DASHBOARD
# ============================================================

if page == "🏠 Dashboard":

    st.markdown(
        """
        <div class="terminal-header">

        <div class="terminal-title">
        🚀 Pro AI Trading Terminal
        </div>

        <div class="terminal-subtitle">
        Live Markets • Futures • Portfolio •
        Paper Trading • Market Intelligence
        </div>

        </div>
        """,
        unsafe_allow_html=True,
    )

    refresh_col, info_col = st.columns(
        [1, 5]
    )

    with refresh_col:

        if st.button(
            "🔄 Refresh",
            type="primary",
            use_container_width=True,
        ):

            st.cache_data.clear()

            st.session_state.last_refresh = (
                datetime.now()
            )

            st.rerun()

    with info_col:

        st.caption(
            "Live market data is read-only. "
            "Real exchange orders are disabled."
        )

    # --------------------------------------------------------
    # PORTFOLIO SUMMARY
    # --------------------------------------------------------

    st.markdown(
        '<div class="section-title">'
        'Account Overview'
        '</div>',
        unsafe_allow_html=True,
    )

    c1, c2, c3, c4 = st.columns(4)

    with c1:
        st.metric(
            "Paper Balance",
            f"${st.session_state.paper_balance:,.2f}",
        )

    with c2:
        st.metric(
            "Open Positions",
            len(
                st.session_state.paper_positions
            ),
        )

    with c3:
        st.metric(
            "Paper P&L",
            "$0.00",
        )

    with c4:
        st.metric(
            "Trading Mode",
            "PAPER",
        )

    # --------------------------------------------------------
    # LIVE MARKETS
    # --------------------------------------------------------

    st.markdown(
        '<div class="section-title">'
        '🔥 Live Markets'
        '</div>',
        unsafe_allow_html=True,
    )

    pairs = [
        "BTC/USDT",
        "ETH/USDT",
        "SOL/USDT",
        "XRP/USDT",
    ]

    columns = st.columns(4)

    for index, pair in enumerate(pairs):

        symbol = SYMBOLS[pair]

        data = get_ticker(symbol)

        with columns[index]:

            st.subheader(pair)

            if data:

                price = data["price"]
                change = data["change"]

                st.metric(
                    "Price",
                    f"${price:,.4f}",
                    f"{change:+.2f}%",
                )

                st.caption(
                    f"24H High: "
                    f"${data['high']:,.4f}"
                )

                st.caption(
                    f"24H Low: "
                    f"${data['low']:,.4f}"
                )

                st.caption(
                    f"Source: {data['source']}"
                )

            else:

                st.warning(
                    "Market data unavailable"
                )

    # --------------------------------------------------------
    # MAIN CHART
    # --------------------------------------------------------

    st.markdown(
        '<div class="section-title">'
        '📊 Advanced Chart'
        '</div>',
        unsafe_allow_html=True,
    )

    chart_col, control_col = st.columns(
        [4, 1]
    )

    with control_col:

        chart_pair = st.selectbox(
            "Market",
            list(SYMBOLS.keys()),
        )

        timeframe = st.selectbox(
            "Timeframe",
            [
                "1",
                "5",
                "15",
                "30",
                "60",
                "240",
                "D",
                "W",
            ],
            index=2,
        )

    with chart_col:

        clean_symbol = chart_pair.replace(
            "/USDT",
            ""
        )

        components.html(
            tradingview_chart(
                clean_symbol,
                timeframe,
                600,
            ),
            height=600,
        )

    # --------------------------------------------------------
    # INTELLIGENCE
    # --------------------------------------------------------

    st.markdown(
        '<div class="section-title">'
        '🧠 Market Intelligence'
        '</div>',
        unsafe_allow_html=True,
    )

    i1, i2, i3 = st.columns(3)

    with i1:

        st.info(
            "📡 **Market Regime**\n\n"
            "Live price data is available. "
            "Advanced regime classification "
            "will be added in the AI phase."
        )

    with i2:

        st.info(
            "🧠 **AI Signal Engine**\n\n"
            "The terminal is AI-ready. "
            "A real AI model/API should be "
            "connected before calling signals AI."
        )

    with i3:

        st.info(
            "📰 **News Intelligence**\n\n"
            "News feeds will be connected "
            "as a separate module so the "
            "core trading terminal remains stable."
        )


# ============================================================
# MARKETS
# ============================================================

elif page == "📈 Markets":

    st.title("📈 Markets")

    st.caption(
        "Live cryptocurrency market overview"
    )

    if st.button(
        "🔄 Refresh Market Data",
        type="primary",
    ):

        st.cache_data.clear()
        st.rerun()

    rows = []

    for pair, symbol in SYMBOLS.items():

        data = get_ticker(symbol)

        if data:

            rows.append(
                {
                    "Pair": pair,
                    "Price": data["price"],
                    "24H %": data["change"],
                    "24H High": data["high"],
                    "24H Low": data["low"],
                    "Volume": data["volume"],
                    "Source": data["source"],
                }
            )

    if rows:

        dataframe = pd.DataFrame(rows)

        st.dataframe(
            dataframe,
            use_container_width=True,
            hide_index=True,
        )

    else:

        st.error(
            "No market data available."
        )

    st.subheader(
        "📊 Market Chart"
    )

    pair = st.selectbox(
        "Select market",
        list(SYMBOLS.keys()),
        key="markets_pair",
    )

    timeframe = st.selectbox(
        "Timeframe",
        [
            "1",
            "5",
            "15",
            "30",
            "60",
            "240",
            "D",
            "W",
        ],
        index=2,
        key="markets_timeframe",
    )

    clean_symbol = pair.replace(
        "/USDT",
        ""
    )

    components.html(
        tradingview_chart(
            clean_symbol,
            timeframe,
            620,
        ),
        height=620,
    )


# ============================================================
# FUTURES
# ============================================================

elif page == "⚡ Futures":

    st.title(
        "⚡ Futures Trading Terminal"
    )

    st.caption(
        "Professional futures interface "
        "with paper trading"
    )

    left, center, right = st.columns(
        [1.1, 2.5, 1.1]
    )

    # --------------------------------------------------------
    # ORDER PANEL
    # --------------------------------------------------------

    with left:

        st.subheader(
            "Order Panel"
        )

        pair = st.selectbox(
            "Pair",
            list(SYMBOLS.keys()),
            key="futures_pair",
        )

        direction = st.radio(
            "Direction",
            [
                "LONG",
                "SHORT",
            ],
            horizontal=True,
        )

        order_type = st.selectbox(
            "Order Type",
            [
                "Market",
                "Limit",
            ],
        )

        leverage = st.slider(
            "Leverage",
            min_value=1,
            max_value=50,
            value=5,
        )

        margin = st.number_input(
            "Margin (USDT)",
            min_value=10.0,
            max_value=100000.0,
            value=100.0,
            step=10.0,
        )

        stop_loss = st.number_input(
            "Stop Loss %",
            min_value=0.1,
            max_value=50.0,
            value=1.0,
            step=0.1,
        )

        take_profit = st.number_input(
            "Take Profit %",
            min_value=0.1,
            max_value=100.0,
            value=2.0,
            step=0.1,
        )

        position_value = (
            margin * leverage
        )

        risk_reward = (
            take_profit / stop_loss
        )

        st.divider()

        st.metric(
            "Position Value",
            f"${position_value:,.2f}",
        )

        st.metric(
            "Risk / Reward",
            f"1:{risk_reward:.2f}",
        )

        st.warning(
            "PAPER TRADING ONLY"
        )

        if st.button(
            "🚀 Place Paper Order",
            type="primary",
            use_container_width=True,
        ):

            if margin > st.session_state.paper_balance:

                st.error(
                    "Insufficient paper balance."
                )

            else:

                ticker = get_ticker(
                    SYMBOLS[pair]
                )

                if ticker:

                    entry_price = ticker["price"]

                    position = {
                        "time": datetime.now().strftime(
                            "%Y-%m-%d %H:%M:%S"
                        ),
                        "pair": pair,
                        "side": direction,
                        "entry": entry_price,
                        "margin": margin,
                        "leverage": leverage,
                        "value": position_value,
                        "stop_loss": stop_loss,
                        "take_profit": take_profit,
                    }

                    st.session_state.paper_positions.append(
                        position
                    )

                    st.session_state.paper_balance -= margin

                    st.success(
                        f"Paper {direction} opened "
                        f"at ${entry_price:,.4f}"
                    )

                else:

                    st.error(
                        "Live price unavailable. "
                        "Order was not created."
                    )

    # --------------------------------------------------------
    # CHART
    # --------------------------------------------------------

    with center:

        timeframe = st.selectbox(
            "Chart",
            [
                "1",
                "5",
                "15",
                "30",
                "60",
                "240",
                "D",
            ],
            index=2,
            key="futures_timeframe",
        )

        clean_symbol = pair.replace(
            "/USDT",
            ""
        )

        components.html(
            tradingview_chart(
                clean_symbol,
                timeframe,
                620,
            ),
            height=620,
        )

    # --------------------------------------------------------
    # ORDER BOOK
    # --------------------------------------------------------

    with right:

        st.subheader(
            "📖 Order Book"
        )

        book = get_orderbook(
            SYMBOLS[pair]
        )

        if book:

            ask_rows = []

            for item in book["asks"]:

                ask_rows.append(
                    {
                        "Price": safe_float(
                            item[0]
                        ),
                        "Size": safe_float(
                            item[1]
                        ),
                    }
                )

            bid_rows = []

            for item in book["bids"]:

                bid_rows.append(
                    {
                        "Price": safe_float(
                            item[0]
                        ),
                        "Size": safe_float(
                            item[1]
                        ),
                    }
                )

            st.caption("ASKS")

            st.dataframe(
                pd.DataFrame(
                    ask_rows
                ),
                use_container_width=True,
                hide_index=True,
                height=220,
            )

            st.caption("BIDS")

            st.dataframe(
                pd.DataFrame(
                    bid_rows
                ),
                use_container_width=True,
                hide_index=True,
                height=220,
            )

        else:

            st.warning(
                "Order book unavailable."
            )

    # --------------------------------------------------------
    # POSITIONS
    # --------------------------------------------------------

    st.subheader(
        "📌 Open Paper Positions"
    )

    if st.session_state.paper_positions:

        position_df = pd.DataFrame(
            st.session_state.paper_positions
        )

        st.dataframe(
            position_df,
            use_container_width=True,
            hide_index=True,
        )

    else:

        st.info(
            "No open paper positions."
        )


# ============================================================
# PORTFOLIO
# ============================================================

elif page == "💼 Portfolio":

    st.title(
        "💼 Portfolio"
    )

    st.caption(
        "Paper portfolio and performance"
    )

    c1, c2, c3 = st.columns(3)

    with c1:

        st.metric(
            "Available Balance",
            f"${st.session_state.paper_balance:,.2f}",
        )

    with c2:

        st.metric(
            "Open Positions",
            len(
                st.session_state.paper_positions
            ),
        )

    with c3:

        st.metric(
            "Trading Mode",
            "PAPER",
        )

    st.divider()

    st.subheader(
        "Current Positions"
    )

    if st.session_state.paper_positions:

        df = pd.DataFrame(
            st.session_state.paper_positions
        )

        st.dataframe(
            df,
            use_container_width=True,
            hide_index=True,
        )

    else:

        st.info(
            "Your portfolio is currently empty."
        )


# ============================================================
# PAPER TRADING
# ============================================================

elif page == "🧪 Paper Trading":

    st.title(
        "🧪 Paper Trading"
    )

    st.caption(
        "Practice trading without risking real money"
    )

    c1, c2, c3 = st.columns(3)

    with c1:

        st.metric(
            "Starting Balance",
            "$10,000.00",
        )

    with c2:

        st.metric(
            "Current Balance",
            f"${st.session_state.paper_balance:,.2f}",
        )

    with c3:

        st.metric(
            "Open Trades",
            len(
                st.session_state.paper_positions
            ),
        )

    st.divider()

    st.subheader(
        "Trading Safety"
    )

    st.success(
        "Real exchange trading is disabled."
    )

    st.info(
        "This version only creates paper "
        "positions. API trading keys are not "
        "required."
    )

    st.subheader(
        "Trade History"
    )

    if st.session_state.trade_history:

        history_df = pd.DataFrame(
            st.session_state.trade_history
        )

        st.dataframe(
            history_df,
            use_container_width=True,
            hide_index=True,
        )

    else:

        st.info(
            "No completed paper trades yet."
        )

    st.divider()

    if st.button(
        "🗑️ Reset Paper Account"
    ):

        st.session_state.paper_balance = 10000.0
        st.session_state.paper_positions = []
        st.session_state.trade_history = []

        st.success(
            "Paper account reset."
        )

        st.rerun()


# ============================================================
# FOOTER
# ============================================================

st.divider()

st.caption(
    "Pro AI Trading Terminal • "
    "Live Market Data • "
    "Paper Trading • "
    "Real Trading Disabled"
)

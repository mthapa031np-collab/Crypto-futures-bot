import streamlit as st
import pandas as pd
import requests
import streamlit.components.v1 as components
from datetime import datetime

# ============================================================
# PRO TRADING TERMINAL
# Live Market Data + Futures + Paper Trading
# REAL TRADING DISABLED
# ============================================================

st.set_page_config(
    page_title="Pro Trading Terminal",
    page_icon="📊",
    layout="wide",
    initial_sidebar_state="expanded",
)

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

# ============================================================
# PROFESSIONAL UI
# ============================================================

st.markdown(
    """
<style>

.stApp {
    background: #0b0e11;
    color: #eaecef;
}

[data-testid="stSidebar"] {
    background: #11161d;
    border-right: 1px solid #2b3139;
}

[data-testid="stSidebar"] * {
    color: #eaecef;
}

.block-container {
    padding-top: 1.5rem;
    padding-bottom: 2rem;
}

.main-title {
    font-size: 30px;
    font-weight: 800;
}

.subtitle {
    color: #848e9c;
    font-size: 14px;
    margin-top: 5px;
}

.header-card {
    background: linear-gradient(135deg, #11161d, #181e27);
    border: 1px solid #2b3139;
    border-radius: 14px;
    padding: 22px;
    margin-bottom: 20px;
}

.dashboard-card {
    background: #151a21;
    border: 1px solid #2b3139;
    border-radius: 12px;
    padding: 17px;
    min-height: 115px;
}

.card-label {
    color: #848e9c;
    font-size: 12px;
    font-weight: 600;
}

.card-value {
    color: #f0f2f4;
    font-size: 24px;
    font-weight: 750;
    margin-top: 7px;
}

.green {
    color: #0ecb81 !important;
}

.red {
    color: #f6465d !important;
}

.yellow {
    color: #f0b90b !important;
}

.section-title {
    color: #f0f2f4;
    font-size: 20px;
    font-weight: 700;
    margin-top: 20px;
    margin-bottom: 12px;
}

.market-card {
    background: #151a21;
    border: 1px solid #2b3139;
    border-radius: 12px;
    padding: 15px;
    min-height: 135px;
}

.market-name {
    font-size: 15px;
    font-weight: 700;
}

.market-price {
    font-size: 22px;
    font-weight: 750;
    margin-top: 8px;
}

.live-badge {
    background: #123b2e;
    color: #0ecb81;
    border-radius: 5px;
    padding: 4px 7px;
    font-size: 10px;
    font-weight: 700;
}

.offline-badge {
    background: #3a2025;
    color: #f6465d;
    border-radius: 5px;
    padding: 4px 7px;
    font-size: 10px;
    font-weight: 700;
}

.info-card {
    background: #11161d;
    border: 1px solid #2b3139;
    border-radius: 12px;
    padding: 18px;
}

.small-text {
    color: #848e9c;
    font-size: 12px;
}

.status-online {
    color: #0ecb81;
    font-weight: 700;
}

.status-warning {
    color: #f0b90e;
    font-weight: 700;
}

</style>
""",
    unsafe_allow_html=True,
)

# ============================================================
# LIVE TICKER
# ============================================================

def get_ticker(symbol):

    clean_symbol = symbol.replace("/", "").upper()

    headers = {
        "User-Agent": "Pro-Trading-Terminal/3.0",
        "Accept": "application/json",
    }

    # --------------------------------------------------------
    # BYBIT FUTURES
    # --------------------------------------------------------

    try:

        response = requests.get(
            f"{BYBIT_API}/v5/market/tickers",
            params={
                "category": "linear",
                "symbol": clean_symbol,
            },
            headers=headers,
            timeout=8,
        )

        if response.status_code == 200:

            data = response.json()

            if data.get("retCode") == 0:

                items = data.get(
                    "result", {}
                ).get(
                    "list", []
                )

                if items:

                    ticker = items[0]

                    return {
                        "price": float(
                            ticker.get(
                                "lastPrice", 0
                            )
                        ),
                        "change": float(
                            ticker.get(
                                "price24hPcnt", 0
                            )
                        ) * 100,
                        "volume": float(
                            ticker.get(
                                "turnover24h", 0
                            )
                        ),
                        "high": float(
                            ticker.get(
                                "highPrice24h", 0
                            )
                        ),
                        "low": float(
                            ticker.get(
                                "lowPrice24h", 0
                            )
                        ),
                        "source": "BYBIT",
                    }

    except Exception:
        pass

    # --------------------------------------------------------
    # BINANCE FALLBACK
    # --------------------------------------------------------

    try:

        response = requests.get(
            f"{BINANCE_API}/api/v3/ticker/24hr",
            params={
                "symbol": clean_symbol
            },
            headers=headers,
            timeout=8,
        )

        if response.status_code == 200:

            data = response.json()

            return {
                "price": float(
                    data["lastPrice"]
                ),
                "change": float(
                    data["priceChangePercent"]
                ),
                "volume": float(
                    data["quoteVolume"]
                ),
                "high": float(
                    data["highPrice"]
                ),
                "low": float(
                    data["lowPrice"]
                ),
                "source": "BINANCE",
            }

    except Exception:
        pass

    return None


# ============================================================
# ORDER BOOK
# ============================================================

def get_orderbook(symbol):

    clean_symbol = symbol.replace(
        "/", ""
    ).upper()

    try:

        response = requests.get(
            f"{BYBIT_API}/v5/market/orderbook",
            params={
                "category": "linear",
                "symbol": clean_symbol,
                "limit": 10,
            },
            timeout=8,
        )

        if response.status_code != 200:
            return None

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
# TRADINGVIEW
# ============================================================

def tradingview_chart(
    symbol,
    interval="15",
    height=600,
):

    tv_symbol = (
        f"BINANCE:{symbol}USDT"
    )

    html = f"""
    <div
        id="tradingview_chart"
        style="
            height:{height}px;
            width:100%;
        "
    ></div>

    <script
        src="https://s3.tradingview.com/tv.js">
    </script>

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

        "studies": [
            "RSI@tv-basicstudies",
            "MASimple@tv-basicstudies"
        ],

        "container_id":
            "tradingview_chart"

    }});

    </script>
    """

    return html


# ============================================================
# SIDEBAR
# ============================================================

st.sidebar.markdown(
    """
    <div style="
        font-size:24px;
        font-weight:800;
    ">
        📊 PRO TERMINAL
    </div>

    <div style="
        color:#848e9c;
        font-size:12px;
        margin-top:4px;
        margin-bottom:20px;
    ">
        Advanced Trading Intelligence
    </div>
    """,
    unsafe_allow_html=True,
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

st.sidebar.markdown("---")

st.sidebar.markdown(
    "### ⚙️ System Status"
)

st.sidebar.markdown(
    '<div class="status-online">'
    '🟢 Market Data: ONLINE'
    '</div>',
    unsafe_allow_html=True,
)

st.sidebar.markdown(
    '<div class="status-online">'
    '🟢 Chart Engine: ONLINE'
    '</div>',
    unsafe_allow_html=True,
)

st.sidebar.markdown(
    '<div class="status-warning">'
    '🟡 AI Engine: PHASE 2'
    '</div>',
    unsafe_allow_html=True,
)

st.sidebar.markdown(
    '<div class="status-warning">'
    '🟡 Real Trading: DISABLED'
    '</div>',
    unsafe_allow_html=True,
)

st.sidebar.markdown("---")

st.sidebar.caption(
    "Pro Trading Terminal"
)

st.sidebar.caption(
    "Live Market Data • Paper Trading"
)


# ============================================================
# DASHBOARD
# ============================================================

if page == "🏠 Dashboard":

    st.markdown(
        """
        <div class="header-card">

            <div class="main-title">
                🚀 Pro Trading Terminal
            </div>

            <div class="subtitle">
                Live Markets • Futures • Portfolio
                • Paper Trading • Market Intelligence
            </div>

        </div>
        """,
        unsafe_allow_html=True,
    )

    if st.button(
        "🔄 Refresh Market Data",
        type="primary",
    ):
        st.rerun()

    # --------------------------------------------------------
    # SUMMARY
    # --------------------------------------------------------

    c1, c2, c3, c4 = st.columns(4)

    with c1:

        st.markdown(
            """
            <div class="dashboard-card">

                <div class="card-label">
                    TOTAL PORTFOLIO
                </div>

                <div class="card-value">
                    $10,764.04
                </div>

                <div class="green">
                    ▲ +2.38% Today
                </div>

            </div>
            """,
            unsafe_allow_html=True,
        )

    with c2:

        st.markdown(
            """
            <div class="dashboard-card">

                <div class="card-label">
                    TODAY'S P&L
                </div>

                <div class="card-value green">
                    +$248.62
                </div>

                <div class="green">
                    +2.37%
                </div>

            </div>
            """,
            unsafe_allow_html=True,
        )

    with c3:

        st.markdown(
            """
            <div class="dashboard-card">

                <div class="card-label">
                    AVAILABLE MARGIN
                </div>

                <div class="card-value">
                    $8,420.18
                </div>

                <div class="small-text">
                    78.2% Available
                </div>

            </div>
            """,
            unsafe_allow_html=True,
        )

    with c4:

        st.markdown(
            """
            <div class="dashboard-card">

                <div class="card-label">
                    OPEN POSITIONS
                </div>

                <div class="card-value">
                    3
                </div>

                <div class="yellow">
                    Risk monitored
                </div>

            </div>
            """,
            unsafe_allow_html=True,
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

    market_pairs = [
        "BTC/USDT",
        "ETH/USDT",
        "SOL/USDT",
        "XRP/USDT",
    ]

    cols = st.columns(4)

    for i, pair in enumerate(
        market_pairs
    ):

        data = get_ticker(
            SYMBOLS[pair]
        )

        with cols[i]:

            if data:

                price = data["price"]
                change = data["change"]

                if change >= 0:
                    movement = "green"
                    arrow = "▲"
                else:
                    movement = "red"
                    arrow = "▼"

                st.markdown(
                    f"""
                    <div class="market-card">

                        <div class="market-name">
                            {pair}
                        </div>

                        <div class="market-price">
                            ${price:,.4f}
                        </div>

                        <div class="{movement}">
                            {arrow}
                            {change:.2f}% 24H
                        </div>

                        <br>

                        <span class="live-badge">
                            ● {data["source"]} LIVE
                        </span>

                    </div>
                    """,
                    unsafe_allow_html=True,
                )

            else:

                st.markdown(
                    f"""
                    <div class="market-card">

                        <div class="market-name">
                            {pair}
                        </div>

                        <div class="market-price">
                            Data unavailable
                        </div>

                        <br>

                        <span class="offline-badge">
                            OFFLINE
                        </span>

                    </div>
                    """,
                    unsafe_allow_html=True,
                )

    # --------------------------------------------------------
    # CHART
    # --------------------------------------------------------

    st.markdown(
        '<div class="section-title">'
        '📊 Market Intelligence'
        '</div>',
        unsafe_allow_html=True,
    )

    chart_col, info_col = st.columns(
        [2.6, 1]
    )

    with chart_col:

        selected_pair = st.selectbox(
            "Chart Market",
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

        clean = selected_pair.replace(
            "/USDT",
            ""
        )

        components.html(
            tradingview_chart(
                clean,
                timeframe,
                600,
            ),
            height=600,
        )

    with info_col:

        current = get_ticker(
            SYMBOLS[selected_pair]
        )

        st.markdown(
            """
            <div class="info-card">

                <h3>
                    🤖 Market Intelligence
                </h3>

                <hr>

                <b>Market Status</b>

                <p class="green">
                    ● LIVE
                </p>

                <b>Trend</b>

                <p>
                    Monitoring
                </p>

                <b>Momentum</b>

                <p>
                    Calculating
                </p>

                <b>Market Regime</b>

                <p>
                    Analysis Pending
                </p>

                <b>Risk</b>

                <p class="yellow">
                    Moderate
                </p>

                <span class="small-text">
                    AI analysis will be added
                    in the next phase.
                </span>

            </div>
            """,
            unsafe_allow_html=True,
        )

        if current:

            st.markdown(
                "<br>",
                unsafe_allow_html=True,
            )

            st.markdown(
                f"""
                <div class="info-card">

                    <b>
                        📌 {selected_pair}
                    </b>

                    <br><br>

                    <span class="small-text">
                        24H HIGH
                    </span>

                    <br>

                    ${current["high"]:,.4f}

                    <br><br>

                    <span class="small-text">
                        24H LOW
                    </span>

                    <br>

                    ${current["low"]:,.4f}

                    <br><br>

                    <span class="small-text">
                        24H VOLUME
                    </span>

                    <br>

                    ${current["volume"]:,.0f}

                </div>
                """,
                unsafe_allow_html=True,
            )

    # --------------------------------------------------------
    # NEWS
    # --------------------------------------------------------

    st.markdown(
        '<div class="section-title">'
        '📰 Market Intelligence'
        '</div>',
        unsafe_allow_html=True,
    )

    n1, n2, n3 = st.columns(3)

    n1.info(
        "📰 Crypto News Engine\n\n"
        "News integration will be added "
        "in the next phase."
    )

    n2.info(
        "🏦 Fed / CPI / FOMC\n\n"
        "Economic calendar integration "
        "will be added next."
    )

    n3.info(
        "🤖 AI Sentiment\n\n"
        "AI market sentiment engine "
        "will be added next."
    )


# ============================================================
# MARKETS
# ============================================================

elif page == "📈 Markets":

    st.markdown(
        """
        <div class="header-card">

            <div class="main-title">
                📈 Markets
            </div>

            <div class="subtitle">
                Live cryptocurrency market monitoring
            </div>

        </div>
        """,
        unsafe_allow_html=True,
    )

    if st.button(
        "🔄 Refresh Markets",
        type="primary",
    ):
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
                    "24H Volume": data["volume"],
                    "24H High": data["high"],
                    "24H Low": data["low"],
                    "Source": data["source"],
                }
            )

    if rows:

        df = pd.DataFrame(rows)

        st.dataframe(
            df,
            use_container_width=True,
            hide_index=True,
        )

    else:

        st.error(
            "Market data unavailable."
        )

    st.markdown(
        '<div class="section-title">'
        '📊 Advanced Chart'
        '</div>',
        unsafe_allow_html=True,
    )

    pair = st.selectbox(
        "Select Pair",
        list(SYMBOLS.keys()),
    )

    timeframe = st.selectbox(
        "Chart Timeframe",
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

    clean = pair.replace(
        "/USDT",
        ""
    )

    components.html(
        tradingview_chart(
            clean,
            timeframe,
            650,
        ),
        height=650,
    )


# ============================================================
# FUTURES
# ============================================================

elif page == "⚡ Futures":

    st.markdown(
        """
        <div class="header-card">

            <div class="main-title">
                ⚡ Futures Trading Terminal
            </div>

            <div class="subtitle">
                Professional Futures Interface
                • Paper Trading Mode
            </div>

        </div>
        """,
        unsafe_allow_html=True,
    )

    left, center, right = st.columns(
        [1, 2.5, 1]
    )

    # --------------------------------------------------------
    # ORDER PANEL
    # --------------------------------------------------------

    with left:

        st.markdown(
            '<div class="section-title">'
            '⚙️ Order'
            '</div>',
            unsafe_allow_html=True,
        )

        pair = st.selectbox(
            "Trading Pair",
            [
                "BTC/USDT",
                "ETH/USDT",
                "SOL/USDT",
                "XRP/USDT",
            ],
        )

        side = st.radio(
            "Position",
            [
                "🟢 LONG",
                "🔴 SHORT",
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
            1,
            50,
            5,
        )

        position_size = st.number_input(
            "Position Size (USDT)",
            min_value=10.0,
            value=100.0,
            step=10.0,
        )

        stop_loss = st.number_input(
            "Stop Loss (%)",
            min_value=0.1,
            value=1.0,
            step=0.1,
        )

        take_profit = st.number_input(
            "Take Profit (%)",
            min_value=0.1,
            value=2.0,
            step=0.1,
        )

        risk_reward = (
            take_profit /
            stop_loss
        )

        st.markdown("---")

        st.metric(
            "Leverage",
            f"{leverage}x"
        )

        st.metric(
            "Risk / Trade",
            f"{stop_loss:.1f}%"
        )

        st.metric(
            "Risk / Reward",
            f"1:{risk_reward:.2f}"
        )

        st.warning(
            "Paper Trading only. "
            "Real exchange orders are disabled."
        )

        if st.button(
            "🚀 PLACE PAPER ORDER",
            use_container_width=True,
            type="primary",
        ):

            st.success(
                f"Paper {side} order created "
                f"for {pair}."
            )

    # --------------------------------------------------------
    # CHART
    # --------------------------------------------------------

    with center:

        clean = pair.replace(
            "/USDT",
            ""
        )

        timeframe = st.selectbox(
            "Chart Timeframe",
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
        )

        components.html(
            tradingview_chart(
                clean,
                timeframe,
                620,
            ),
            height=620,
        )

    # --------------------------------------------------------
    # ORDER BOOK
    # --------------------------------------------------------

    with right:

        st.markdown(
            '<div class="section-title">'
            '📖 Order Book'
            '</div>',
            unsafe_allow_html=True,
        )

        book = get_orderbook(
            pair
        )

        if book:

            asks = []

            for item in book["asks"]:

                asks.append(
                    {
                        "Ask": float(item[0]),
                        "Size": float(item[1]),
                    }
                )

            bids = []

            for item in book["bids"]:

                bids.append(
                    {
                        "Bid": float(item[0]),
                        "Size": float(item[1]),
                    }
                )

            st.caption("ASKS")

            if asks:

                st.dataframe(
                    pd.DataFrame(asks),
                    use_container_width=True,
                    hide_index=True,
                    height=220,
                )

            st.caption("BIDS")

            if bids:

                st.dataframe(
                    pd.DataFrame(bids),
                    use_container_width=True,
                    hide_index=True,
                    height=220,
                )

        else:

            st.info(
                "Order book unavailable."
            )

    # --------------------------------------------------------
    # POSITIONS
    # --------------------------------------------------------

    st.markdown(
        '<div class="section-title">'
        '📌 Positions'
        '</div>',
        unsafe_allow_html=True,
    )

    positions = pd.DataFrame(
        {
            "Pair": [
                "BTC/USDT",
                "ETH/USDT",
                "SOL/USDT",
            ],
            "Side": [
                "LONG",
                "LONG",
                "SHORT",
            ],
            "Leverage": [
                "5x",
                "3x",
                "2x",
            ],
            "Mode": [
                "PAPER",
                "PAPER",
                "PAPER",
            ],
            "Status": [
                "Demo",
                "Demo",
                "Demo",
            ],
        }
    )

    st.dataframe(
        positions,
        use_container_width=True,
        hide_index=True,
    )


# ============================================================
# PORTFOLIO
# ============================================================

elif page == "💼 Portfolio":

    st.markdown(
        """
        <div class="header-card">

            <div class="main-title">
                💼 Portfolio
            </div>

            <div class="subtitle">
                Assets • Performance • Positions
            </div>

        </div>
        """,
        unsafe_allow_html=True,
    )

    c1, c2, c3 = st.columns(3)

    c1.metric(
        "Portfolio Value",
        "$10,764.04"
    )

    c2.metric(
        "Total P&L",
        "+$764.04",
        "+7.64%"
    )

    c3.metric(
        "Available",
        "$8,420.18"
    )

    st.markdown(
        '<div class="section-title">'
        '💰 Assets'
        '</div>',
        unsafe_allow_html=True,
    )

    assets = pd.DataFrame(
        {
            "Asset": [
                "USDT",
                "BTC",
                "ETH",
                "SOL",
            ],
            "Allocation": [
                "42%",
                "35%",
                "15%",
                "8%",
            ],
            "Status": [
                "Available",
                "Holding",
                "Holding",
                "Holding",
            ],
        }
    )

    st.dataframe(
        assets,
        use_container_width=True,
        hide_index=True,
    )


# ============================================================
# PAPER TRADING
# ============================================================

elif page == "🧪 Paper Trading":

    st.markdown(
        """
        <div class="header-card">

            <div class="main-title">
                🧪 Paper Trading
            </div>

            <div class="subtitle">
                Test strategies without real money
            </div>

        </div>
        """,
        unsafe_allow_html=True,
    )

    st.success(
        "Paper Trading Engine: READY"
    )

    c1, c2, c3, c4 = st.columns(4)

    c1.metric(
        "Virtual Balance",
        "$10,000"
    )

    c2.metric(
        "Open Trades",
        "0"
    )

    c3.metric(
        "Win Rate",
        "—"
    )

    c4.metric(
        "Total P&L",
        "$0.00"
    )

    st.markdown(
        '<div class="section-title">'
        '📋 Trade History'
        '</div>',
        unsafe_allow_html=True,
    )

    history = pd.DataFrame(
        columns=[
            "Time",
            "Pair",
            "Side",
            "Entry",
            "Exit",
            "P&L",
        ]
    )

    st.dataframe(
        history,
        use_container_width=True,
        hide_index=True,
    )

    st.info(
        "Next upgrades: Backtesting • "
        "Strategy Engine • AI Signals • "
        "Risk Management • News"
    )


# ============================================================
# FOOTER
# ============================================================

st.markdown("---")

st.caption(
    "Pro Trading Terminal • "
    "Live Market Data • "
    "Paper Trading • "
    f"{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
)

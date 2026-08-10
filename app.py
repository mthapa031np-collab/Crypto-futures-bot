import streamlit as st
import pandas as pd
import requests
import streamlit.components.v1 as components
from datetime import datetime

# =========================================================
# PRO TRADING TERMINAL — PHASE 1
# Professional dashboard + live public market prices
# Paper/demo trading only — NO real-money execution
# =========================================================

st.set_page_config(
    page_title="Pro Trading Terminal",
    page_icon="📊",
    layout="wide",
    initial_sidebar_state="expanded",
)

# =========================================================
# PROFESSIONAL DARK UI
# =========================================================

st.markdown("""
<style>

html, body, [class*="css"] {
    font-family: Inter, Arial, sans-serif;
}

.stApp {
    background: #0b0e11;
    color: #eaecef;
}

[data-testid="stSidebar"] {
    background: #11151a;
    border-right: 1px solid #2b3139;
}

[data-testid="stSidebar"] * {
    color: #eaecef;
}

.pro-header {
    background: linear-gradient(135deg, #11161d, #181d25);
    border: 1px solid #2b3139;
    border-radius: 14px;
    padding: 22px 26px;
    margin-bottom: 18px;
}

.pro-title {
    font-size: 28px;
    font-weight: 700;
    margin: 0;
}

.pro-subtitle {
    color: #848e9c;
    margin-top: 5px;
}

.card {
    background: #151a21;
    border: 1px solid #2b3139;
    border-radius: 12px;
    padding: 18px;
    margin-bottom: 15px;
}

.card-title {
    color: #848e9c;
    font-size: 13px;
    margin-bottom: 8px;
}

.card-value {
    color: #f0f2f4;
    font-size: 24px;
    font-weight: 700;
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
    font-size: 19px;
    font-weight: 650;
    margin-top: 12px;
    margin-bottom: 12px;
}

.market-card {
    background: #151a21;
    border: 1px solid #2b3139;
    border-radius: 12px;
    padding: 16px;
    min-height: 120px;
}

.market-symbol {
    font-size: 16px;
    font-weight: 650;
}

.market-price {
    font-size: 22px;
    font-weight: 700;
    margin-top: 8px;
}

.badge {
    display: inline-block;
    padding: 4px 9px;
    border-radius: 6px;
    font-size: 11px;
    background: #202630;
    color: #b7c0cc;
}

.info-box {
    background: #11161d;
    border: 1px solid #2b3139;
    border-radius: 10px;
    padding: 14px;
}

</style>
""", unsafe_allow_html=True)


# =========================================================
# LIVE MARKET DATA
# =========================================================

BINANCE_API = "https://api.binance.com"

SYMBOLS = {
    "BTC/USDT": "BTCUSDT",
    "ETH/USDT": "ETHUSDT",
    "SOL/USDT": "SOLUSDT",
    "BNB/USDT": "BNBUSDT",
    "XRP/USDT": "XRPUSDT",
    "DOGE/USDT": "DOGEUSDT",
}


def get_ticker(symbol):
    """Get public 24h market data."""
    try:
        response = requests.get(
            f"{BINANCE_API}/api/v3/ticker/24hr",
            params={"symbol": symbol},
            timeout=5,
        )

        if response.status_code == 200:
            data = response.json()

            return {
                "price": float(data["lastPrice"]),
                "change": float(data["priceChangePercent"]),
                "volume": float(data["quoteVolume"]),
            }

    except Exception:
        pass

    return None


def create_tradingview_widget(symbol, interval="15", height=620):
    tv_symbol = f"BINANCE:{symbol}USDT"

    html = f"""
    <div style="height:{height}px;width:100%">
        <div id="tv_chart" style="height:100%;width:100%"></div>

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
            "toolbar_bg": "#0b0e11",
            "enable_publishing": false,
            "hide_side_toolbar": false,
            "allow_symbol_change": true,
            "container_id": "tv_chart"
        }});
        </script>
    </div>
    """

    return html


# =========================================================
# SIDEBAR
# =========================================================

st.sidebar.markdown("## 📊 PRO TERMINAL")
st.sidebar.caption("Advanced Trading Intelligence")

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

st.sidebar.markdown("### ⚙️ System")

st.sidebar.write("🟢 Market Data: **ONLINE**")
st.sidebar.write("🟢 Chart Engine: **ONLINE**")
st.sidebar.write("🟡 AI Engine: **PHASE 2**")
st.sidebar.write("🟡 Exchange Trading: **DISABLED**")

st.sidebar.markdown("---")
st.sidebar.caption("Version 2.0 — Phase 1")


# =========================================================
# DASHBOARD
# =========================================================

if page == "🏠 Dashboard":

    st.markdown("""
    <div class="pro-header">
        <div class="pro-title">🚀 Pro Trading Terminal</div>
        <div class="pro-subtitle">
            Market Intelligence • Futures • Portfolio • Paper Trading
        </div>
    </div>
    """, unsafe_allow_html=True)

    # Portfolio overview
    c1, c2, c3, c4 = st.columns(4)

    with c1:
        st.markdown("""
        <div class="card">
            <div class="card-title">TOTAL PORTFOLIO</div>
            <div class="card-value">$10,764.04</div>
            <div class="green">▲ +2.38% Today</div>
        </div>
        """, unsafe_allow_html=True)

    with c2:
        st.markdown("""
        <div class="card">
            <div class="card-title">TODAY'S P&L</div>
            <div class="card-value green">+$248.62</div>
            <div class="green">+2.37%</div>
        </div>
        """, unsafe_allow_html=True)

    with c3:
        st.markdown("""
        <div class="card">
            <div class="card-title">AVAILABLE MARGIN</div>
            <div class="card-value">$8,420.18</div>
            <div>78.2% Available</div>
        </div>
        """, unsafe_allow_html=True)

    with c4:
        st.markdown("""
        <div class="card">
            <div class="card-title">OPEN POSITIONS</div>
            <div class="card-value">3</div>
            <div class="yellow">Risk monitored</div>
        </div>
        """, unsafe_allow_html=True)

    # Markets
    st.markdown('<div class="section-title">🔥 Live Markets</div>',
                unsafe_allow_html=True)

    market_cols = st.columns(3)

    for index, pair in enumerate(["BTC/USDT", "ETH/USDT", "SOL/USDT"]):

        data = get_ticker(SYMBOLS[pair])

        with market_cols[index]:

            if data:

                price = data["price"]
                change = data["change"]

                change_class = "green" if change >= 0 else "red"
                arrow = "▲" if change >= 0 else "▼"

                st.markdown(f"""
                <div class="market-card">
                    <div class="market-symbol">{pair}</div>
                    <div class="market-price">${price:,.4f}</div>
                    <div class="{change_class}">
                        {arrow} {change:.2f}% 24H
                    </div>
                    <br>
                    <span class="badge">LIVE</span>
                </div>
                """, unsafe_allow_html=True)

            else:

                st.markdown(f"""
                <div class="market-card">
                    <div class="market-symbol">{pair}</div>
                    <div class="market-price">Data unavailable</div>
                    <span class="badge">OFFLINE</span>
                </div>
                """, unsafe_allow_html=True)

    # Chart + market intelligence
    st.markdown('<div class="section-title">📊 Market Intelligence</div>',
                unsafe_allow_html=True)

    chart_col, intelligence_col = st.columns([2.5, 1])

    with chart_col:

        selected = st.selectbox(
            "Chart",
            ["BTC/USDT", "ETH/USDT", "SOL/USDT", "BNB/USDT"],
        )

        timeframe = st.selectbox(
            "Timeframe",
            ["5", "15", "30", "60", "240", "D", "W"],
            index=1,
        )

        clean_symbol = selected.replace("/USDT", "")

        components.html(
            create_tradingview_widget(
                clean_symbol,
                timeframe,
                620,
            ),
            height=620,
        )

    with intelligence_col:

        st.markdown("""
        <div class="info-box">
        <b>🤖 MARKET INTELLIGENCE</b><br><br>

        <b>BTC Trend</b><br>
        <span class="green">Bullish</span><br><br>

        <b>Momentum</b><br>
        Strong<br><br>

        <b>Market Regime</b><br>
        Trending<br><br>

        <b>Risk Level</b><br>
        <span class="yellow">Moderate</span><br><br>

        <b>AI Engine</b><br>
        Coming in Phase 2
        </div>
        """, unsafe_allow_html=True)

        st.markdown("<br>", unsafe_allow_html=True)

        st.markdown("""
        <div class="info-box">
        <b>📰 MARKET NEWS</b><br><br>

        Crypto market monitoring active.<br><br>

        <span class="badge">NEWS ENGINE — PHASE 2</span>
        </div>
        """, unsafe_allow_html=True)

    # Positions
    st.markdown('<div class="section-title">📌 Open Positions</div>',
                unsafe_allow_html=True)

    positions = pd.DataFrame({
        "Pair": ["BTC/USDT", "ETH/USDT", "SOL/USDT"],
        "Side": ["LONG", "LONG", "SHORT"],
        "Leverage": ["5x", "3x", "2x"],
        "Entry": ["Demo", "Demo", "Demo"],
        "P&L": ["+$84.20", "+$51.32", "-$12.80"],
        "Status": ["Active", "Active", "Active"],
    })

    st.dataframe(
        positions,
        use_container_width=True,
        hide_index=True,
    )


# =========================================================
# MARKETS
# =========================================================

elif page == "📈 Markets":

    st.markdown("""
    <div class="pro-header">
        <div class="pro-title">📈 Markets</div>
        <div class="pro-subtitle">
            Live cryptocurrency market monitoring
        </div>
    </div>
    """, unsafe_allow_html=True)

    rows = []

    for pair, symbol in SYMBOLS.items():

        data = get_ticker(symbol)

        if data:

            rows.append({
                "Pair": pair,
                "Price": data["price"],
                "24H Change %": data["change"],
                "24H Volume": data["volume"],
                "Status": "LIVE",
            })

    if rows:

        df = pd.DataFrame(rows)

        st.dataframe(
            df,
            use_container_width=True,
            hide_index=True,
        )

    selected_market = st.selectbox(
        "Select Market",
        list(SYMBOLS.keys()),
    )

    clean = selected_market.replace("/USDT", "")

    components.html(
        create_tradingview_widget(clean, "15", 650),
        height=650,
    )


# =========================================================
# FUTURES
# =========================================================

elif page == "⚡ Futures":

    st.markdown("""
    <div class="pro-header">
        <div class="pro-title">⚡ Futures Trading Terminal</div>
        <div class="pro-subtitle">
            Professional futures interface — paper/demo mode
        </div>
    </div>
    """, unsafe_allow_html=True)

    left, center, right = st.columns([1, 2.3, 1])

    with left:

        st.markdown("### ⚙️ Order Configuration")

        pair = st.selectbox(
            "Trading Pair",
            ["BTC/USDT", "ETH/USDT", "SOL/USDT"],
        )

        side = st.radio(
            "Position",
            ["🟢 Long", "🔴 Short"],
            horizontal=True,
        )

        leverage = st.slider(
            "Leverage",
            1,
            50,
            5,
        )

        quantity = st.number_input(
            "Position Size (USDT)",
            min_value=10.0,
            value=100.0,
            step=10.0,
        )

        stop_loss = st.number_input(
            "Stop Loss %",
            min_value=0.1,
            value=1.0,
            step=0.1,
        )

        take_profit = st.number_input(
            "Take Profit %",
            min_value=0.1,
            value=2.0,
            step=0.1,
        )

        st.markdown("---")

        st.info(
            "Paper Trading Mode\n\n"
            "Real exchange execution is disabled."
        )

        st.button(
            "🚀 Place Paper Order",
            use_container_width=True,
        )

    with center:

        clean = pair.replace("/USDT", "")

        components.html(
            create_tradingview_widget(clean, "15", 650),
            height=650,
        )

    with right:

        st.markdown("### 📖 Order Book")

        orderbook = pd.DataFrame({
            "Price": [
                "Live",
                "Live",
                "Live",
                "Live",
                "Live",
            ],
            "Size": [
                "—",
                "—",
                "—",
                "—",
                "—",
            ],
        })

        st.dataframe(
            orderbook,
            use_container_width=True,
            hide_index=True,
        )

        st.markdown("### 🛡️ Risk")

        st.metric("Risk / Trade", f"{stop_loss:.1f}%")
        st.metric("Leverage", f"{leverage}x")
        st.metric("R:R", f"1:{take_profit / stop_loss:.2f}")


# =========================================================
# PORTFOLIO
# =========================================================

elif page == "💼 Portfolio":

    st.markdown("""
    <div class="pro-header">
        <div class="pro-title">💼 Portfolio</div>
        <div class="pro-subtitle">
            Assets, positions and performance
        </div>
    </div>
    """, unsafe_allow_html=True)

    a, b, c = st.columns(3)

    a.metric("Portfolio Value", "$10,764.04")
    b.metric("Total P&L", "+$764.04", "+7.64%")
    c.metric("Available", "$8,420.18")

    st.markdown("### 📊 Asset Allocation")

    assets = pd.DataFrame({
        "Asset": ["USDT", "BTC", "ETH", "SOL"],
        "Allocation": ["42%", "35%", "15%", "8%"],
        "Status": ["Available", "Holding", "Holding", "Holding"],
    })

    st.dataframe(
        assets,
        use_container_width=True,
        hide_index=True,
    )


# =========================================================
# PAPER TRADING
# =========================================================

elif page == "🧪 Paper Trading":

    st.markdown("""
    <div class="pro-header">
        <div class="pro-title">🧪 Paper Trading</div>
        <div class="pro-subtitle">
            Test strategies without real money
        </div>
    </div>
    """, unsafe_allow_html=True)

    st.success("Paper Trading Engine: READY")

    c1, c2, c3, c4 = st.columns(4)

    c1.metric("Virtual Balance", "$10,000")
    c2.metric("Open Trades", "0")
    c3.metric("Win Rate", "—")
    c4.metric("Total P&L", "$0.00")

    st.markdown("### 📋 Trade History")

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
        "Next upgrade: real strategy engine + backtesting + "
        "AI signals + risk management."
    )


# =========================================================
# FOOTER
# =========================================================

st.markdown("---")

st.caption(
    f"Pro Trading Terminal • Phase 1 • "
    f"Updated {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
)

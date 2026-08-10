import streamlit as st
import pandas as pd
import requests
import streamlit.components.v1 as components

# 1. Page Configuration
st.set_page_config(
    page_title="Pro AI Trading Terminal",
    layout="wide",
    initial_sidebar_state="expanded"
)

# 2. Custom CSS for Halaska Dark Theme Layout
st.markdown("""
<style>
    /* Dark Theme Background */
    .stApp {
        background-color: #0b0e14;
        color: #d1d4dc;
    }
    
    /* Top Bar Metric Cards */
    .metric-card {
        background-color: #151924;
        border: 1px solid #2a2e39;
        border-radius: 6px;
        padding: 10px 15px;
        text-align: center;
    }
    .metric-title { font-size: 11px; color: #787b86; text-transform: uppercase; }
    .metric-value-green { font-size: 16px; font-weight: bold; color: #0ecb81; }
    .metric-value-red { font-size: 16px; font-weight: bold; color: #f6465d; }
    .metric-value-normal { font-size: 16px; font-weight: bold; color: #eaebd7; }

    /* Custom Order Book styling */
    .order-book-title {
        font-size: 14px;
        font-weight: 600;
        margin-bottom: 8px;
        color: #848e9c;
    }

    /* Primary Trading Buttons */
    div.stButton > button[data-testid="baseButton-secondary"] {
        background-color: #0ecb81 !important;
        color: #ffffff !important;
        font-weight: bold;
        border: none;
        width: 100%;
        height: 45px;
    }
</style>
""", unsafe_allow_html=True)

# 3. Market Data Fetcher (Binance Public API Fallback for Render)
@st.cache_data(ttl=5)
def fetch_market_ticker(symbol_pair="BTCUSDT"):
    try:
        url = f"https://api.binance.com/api/v3/ticker/24hr?symbol={symbol_pair}"
        res = requests.get(url, timeout=4)
        if res.status_code == 200:
            return res.json()
    except Exception:
        pass
    return None

# --- SIDEBAR CONTROLS ---
st.sidebar.title("⚡ AI TERMINAL")
selected_pair = st.sidebar.selectbox("Select Crypto Pair", ["BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT"], index=0)
timeframe = st.sidebar.selectbox("Timeframe", ["1m", "5m", "15m", "1h", "4h", "1d"], index=2)

tf_map = {"1m": "1", "5m": "5", "15m": "15", "1h": "60", "4h": "240", "1d": "D"}

# Fetch Ticker Data
ticker_data = fetch_market_ticker(selected_pair)

# --- TOP STATS BAR ---
if ticker_data:
    last_p = float(ticker_data['lastPrice'])
    p_change = float(ticker_data['priceChangePercent'])
    high_p = float(ticker_data['highPrice'])
    low_p = float(ticker_data['lowPrice'])
    vol = float(ticker_data['volume'])

    c1, c2, c3, c4, c5 = st.columns(5)
    change_css = "metric-value-green" if p_change >= 0 else "metric-value-red"
    
    with c1:
        st.markdown(f"<div class='metric-card'><div class='metric-title'>{selected_pair} Price</div><div class='{change_css}'>${last_p:,.2f}</div></div>", unsafe_allow_html=True)
    with c2:
        st.markdown(f"<div class='metric-card'><div class='metric-title'>24h Change</div><div class='{change_css}'>{p_change:+.2f}%</div></div>", unsafe_allow_html=True)
    with c3:
        st.markdown(f"<div class='metric-card'><div class='metric-title'>24h High</div><div class='metric-value-normal'>${high_p:,.2f}</div></div>", unsafe_allow_html=True)
    with c4:
        st.markdown(f"<div class='metric-card'><div class='metric-title'>24h Low</div><div class='metric-value-normal'>${low_p:,.2f}</div></div>", unsafe_allow_html=True)
    with c5:
        st.markdown(f"<div class='metric-card'><div class='metric-title'>24h Volume</div><div class='metric-value-normal'>{vol:,.2f}</div></div>", unsafe_allow_html=True)
else:
    st.warning("⚠️ Live Ticker Syncing... Retrying API Connection.")

st.markdown("<br>", unsafe_allow_html=True)

# --- MAIN DASHBOARD (3-COLUMN LAYOUT) ---
col_chart, col_depth, col_trade = st.columns([3, 1.2, 1.2])

with col_chart:
    st.subheader("📈 Live Market Chart")
    tv_interval = tf_map.get(timeframe, "15")
    
    # TradingView Pro Widget Embed
    tv_code = f"""
    <div class="tradingview-widget-container" style="height:540px;width:100%;">
      <div id="tradingview_chart" style="height:540px;width:100%;"></div>
      <script type="text/javascript" src="https://s3.tradingview.com/tv.js"></script>
      <script type="text/javascript">
      new TradingView.widget({{
        "autosize": true,
        "symbol": "BINANCE:{selected_pair}",
        "interval": "{tv_interval}",
        "timezone": "Etc/UTC",
        "theme": "dark",
        "style": "1",
        "locale": "en",
        "enable_publishing": false,
        "hide_side_toolbar": false,
        "allow_symbol_change": true,
        "container_id": "tradingview_chart"
      }});
      </script>
    </div>
    """
    components.html(tv_code, height=550)

with col_depth:
    st.subheader("📊 Order Book")
    if ticker_data:
        curr_price = float(ticker_data['lastPrice'])
        asks_df = pd.DataFrame({
            "Price ($)": [round(curr_price + i*12.5, 2) for i in range(5, 0, -1)],
            "Size": [0.15, 0.82, 1.45, 0.22, 0.65]
        })
        bids_df = pd.DataFrame({
            "Price ($)": [round(curr_price - i*12.5, 2) for i in range(1, 6)],
            "Size": [1.12, 0.45, 2.30, 0.18, 0.95]
        })
        
        st.markdown("<div class='order-book-title'>🔴 Asks (Sell Orders)</div>", unsafe_allow_html=True)
        st.dataframe(asks_df, use_container_width=True, height=160, hide_index=True)
        
        st.markdown("<div class='order-book-title'>🟢 Bids (Buy Orders)</div>", unsafe_allow_html=True)
        st.dataframe(bids_df, use_container_width=True, height=160, hide_index=True)

with col_trade:
    st.subheader("⚡ Execution")
    order_type = st.radio("Order Type", ["Market", "Limit", "Conditional"], horizontal=True)
    margin_mode = st.selectbox("Margin Mode", ["Isolated 20x", "Cross 50x", "Cross 100x"])
    
    trade_amount = st.number_input("Amount (USDT)", min_value=10.0, value=100.0, step=10.0)
    
    st.markdown("<br>", unsafe_allow_html=True)
    btn_buy = st.button("BUY / LONG")
    btn_sell = st.button("SELL / SHORT")

# --- BOTTOM SECTION: POSITIONS & HISTORY ---
st.divider()
st.subheader("📋 Account & Active Trades")
tab1, tab2, tab3 = st.tabs(["Open Positions", "Order History", "Bot AI Logs"])

with tab1:
    st.info("No active open positions currently.")
with tab2:
    st.caption("Recent completed trades will appear here.")
with tab3:
    st.code("System Status: ONLINE\nMarket Data Feed: Binance Public WebSocket/REST\nAI Engine: Ready", language="text")

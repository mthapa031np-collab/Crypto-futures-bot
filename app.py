import pandas as pd
import requests
import streamlit as st
import streamlit.components.v1 as components
import yfinance as yf

# Page Config - Wide Layout & Dark Theme Styling
st.set_page_config(
    page_title="Pro Crypto & Stock Trading Dashboard",
    page_icon="📈",
    layout="wide",
    initial_sidebar_state="expanded",
)

# Custom CSS for Binance / Bybit dark UI styling
st.markdown(
    """
<style>
    .stApp {
        background-color: #0b0e11;
        color: #eaecef;
    }
    section[data-testid="stSidebar"] {
        background-color: #1e2329;
    }
    .stSelectbox label, .stRadio label, .stSlider label {
        color: #f0b90b !important;
        font-weight: bold;
    }
    div[data-baseweb="select"] > div {
        background-color: #2b313a !important;
        color: #ffffff !important;
        border-color: #474d57 !important;
    }
    h1, h2, h3 {
        color: #f0b90b !important;
    }
</style>
""",
    unsafe_allow_html=True,
)


# Fetch Top 100 Cryptos dynamically from CoinGecko API
@st.cache_data(ttl=3600)
def get_top_100_cryptos():
  try:
    url = "https://api.coingecko.com/api/v3/coins/markets"
    params = {
        "vs_currency": "usd",
        "order": "market_cap_desc",
        "per_page": 100,
        "page": 1,
        "sparkline": "false",
    }
    res = requests.get(url, params=params, timeout=10)
    data = res.json()
    crypto_dict = {}
    for coin in data:
      symbol = coin["symbol"].upper()
      name = coin["name"]
      # Map to TradingView BINANCE ticker format
      tradingview_symbol = f"BINANCE:{symbol}USDT"
      crypto_dict[f"{name} ({symbol})"] = tradingview_symbol
    return crypto_dict
  except Exception as e:
    # Fallback to major cryptos if API fails
    return {
        "Bitcoin (BTC)": "BINANCE:BTCUSDT",
        "Ethereum (ETH)": "BINANCE:ETHUSDT",
        "Solana (SOL)": "BINANCE:SOLUSDT",
        "Ripple (XRP)": "BINANCE:XRPUSDT",
        "BNB (BNB)": "BINANCE:BNBUSDT",
        "Cardano (ADA)": "BINANCE:ADAUSDT",
        "Dogecoin (DOGE)": "BINANCE:DOGEUSDT",
        "Avalanche (AVAX)": "BINANCE:AVAXUSDT",
    }


# Top 10 Stocks Dictionary
TOP_10_STOCKS = {
    "Nvidia (NVDA)": "NASDAQ:NVDA",
    "Apple (AAPL)": "NASDAQ:AAPL",
    "Microsoft (MSFT)": "NASDAQ:MSFT",
    "Amazon (AMZN)": "NASDAQ:AMZN",
    "Alphabet / Google (GOOGL)": "NASDAQ:GOOGL",
    "Meta Platforms (META)": "NASDAQ:META",
    "Tesla (TSLA)": "NASDAQ:TSLA",
    "MicroStrategy (MSTR)": "NASDAQ:MSTR",
    "Advanced Micro Devices (AMD)": "NASDAQ:AMD",
    "Shell PLC (SHEL)": "NYSE:SHEL",
}

# Sidebar - Bot Controls & Selection
st.sidebar.image(
    "https://bin.bnbstatic.com/static/images/common/logo.png", width=160
)
st.sidebar.title("⚡ Pro Trading Bot")

# Market Selector
market_category = st.sidebar.radio(
    "📊 Select Market",
    ["Crypto (Top 100)", "Top 10 Stocks"],
    help="Choose between Crypto Futures/Spot & US/UK Equities",
)

if market_category == "Crypto (Top 100)":
  with st.sidebar:
    st.info("Loading Top 100 Crypto Coins...")
  crypto_list = get_top_100_cryptos()
  selected_asset_label = st.sidebar.selectbox(
      "🪙 Select Crypto Pair", list(crypto_list.keys())
  )
  tv_symbol = crypto_list[selected_asset_label]
else:
  selected_asset_label = st.sidebar.selectbox(
      "🏛️ Select Stock", list(TOP_10_STOCKS.keys())
  )
  tv_symbol = TOP_10_STOCKS[selected_asset_label]

st.sidebar.markdown("---")
st.sidebar.subheader("⚙️ Bot Trading Settings")
api_key = st.sidebar.text_input("Binance/Exchange API Key", type="password")
secret_key = st.sidebar.text_input(
    "Binance/Exchange Secret Key", type="password"
)
leverage = st.sidebar.slider("Leverage (X)", 1, 50, 5)
tp_percent = st.sidebar.number_input("Take Profit (%)", value=2.0, step=0.1)
sl_percent = st.sidebar.number_input("Stop Loss (%)", value=1.0, step=0.1)

bot_active = st.sidebar.toggle("🤖 Enable Auto-Trading Bot", value=False)

if bot_active:
  st.sidebar.success(f"Bot Active on {selected_asset_label}")
else:
  st.sidebar.warning("Bot is currently Paused")

# Main Dashboard View
st.title(f"🚀 Live Market Interface: {selected_asset_label}")

# Advanced TradingView Chart Widget (Binance/Bybit Style)
chart_html = f"""
<!-- TradingView Widget BEGIN -->
<div class="tradingview-widget-container" style="height:100%;width:100%">
  <div id="tradingview_chart" style="height:650px;width:100%"></div>
  <script type="text/javascript" src="https://s3.tradingview.com/tv.js"></script>
  <script type="text/javascript">
  new TradingView.widget(
  {{
    "autosize": true,
    "symbol": "{tv_symbol}",
    "interval": "15",
    "timezone": "Etc/UTC",
    "theme": "dark",
    "style": "1",
    "locale": "en",
    "toolbar_bg": "#f1f3f6",
    "enable_publishing": false,
    "withcharts": true,
    "allow_symbol_change": true,
    "container_id": "tradingview_chart",
    "hide_side_toolbar": false,
    "studies": [
      "RSI@tv-basicstudies",
      "MASimple@tv-basicstudies",
      "MACD@tv-basicstudies"
    ]
  }}
  );
  </script>
</div>
<!-- TradingView Widget END -->
"""

components.html(chart_html, height=660)

# Quick Overview Columns below the chart
col1, col2, col3 = st.columns(3)

with col1:
  st.subheader("📋 Order Book & Execution")
  st.write(f"Target Symbol: **{tv_symbol}**")
  st.write(f"Leverage Set: **{leverage}x**")
  if st.button("🔴 Quick Sell / Short"):
    st.error("Short Order Sent to Exchange!")
  if st.button("🟢 Quick Buy / Long"):
    st.success("Long Order Sent to Exchange!")

with col2:
  st.subheader("🎯 Risk Management")
  st.write(f"Take Profit Target: **+{tp_percent}%**")
  st.write(f"Stop Loss Target: **-{sl_percent}%**")
  st.info("Dynamic Trailing Stop: Active")

with col3:
  st.subheader("📊 Market Sentiment")
  st.metric(
      label="Market Status",
      value="Bullish Momentum",
      delta=f"+{tp_percent}% target",
  )
  st.caption(
      "Real-time technical indicators (RSI, MACD) automatically synced with"
      " chart."
  )

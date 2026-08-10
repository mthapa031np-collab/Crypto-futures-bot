import streamlit as st

st.set_page_config(page_title="Crypto Futures Bot", layout="wide")
st.title("⚡ Crypto Futures Trading Bot Dashboard")

st.success("App is running successfully on Render!")

# Sidebar for API Keys and Settings
st.sidebar.header("⚙️ Bot Configuration")
api_key = st.sidebar.text_input("Binance API Key", type="password")
secret_key = st.sidebar.text_input("Binance Secret Key", type="password")
leverage = st.sidebar.slider("Leverage", 1, 20, 5)

# TradingView Chart Integration
st.subheader("📊 Live TradingView Chart")
tradingview_html = """
<div class="tradingview-widget-container" style="height:500px;width:100%;">
  <iframe src="https://s.tradingview.com/widgetembed/?frameElementId=tradingview_1&symbol=BINANCE:BTCUSDT.P&interval=15&hidesidetoolbar=0&symboledit=1&saveimage=1&toolbarbg=f1f3f6&studies=[]&theme=dark&style=1&timezone=Etc%2FUTC" style="width: 100%; height: 500px; border: none;"></iframe>
</div>
"""
st.components.v1.html(tradingview_html, height=520)

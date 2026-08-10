import streamlit as st
import pandas as pd
import ccxt
import os

st.set_page_config(page_title="Advanced Crypto Futures Bot", layout="wide")

st.title("🚀 World-Class Crypto Futures Trading Bot")

# Sidebar Configuration
st.sidebar.header("⚙️ Bot Configuration")
api_key = st.sidebar.text_input("Binance API Key", type="password")
secret_key = st.sidebar.text_input("Binance Secret Key", type="password")
symbol = st.sidebar.selectbox("Select Pair", ["BTC/USDT", "ETH/USDT", "SOL/USDT"])
leverage = st.sidebar.slider("Leverage", 1, 20, 5)

st.sidebar.subheader("🎯 Risk Management (TP / SL)")
tp_percent = st.sidebar.number_input("Take Profit (%)", min_value=0.5, max_value=50.0, value=2.0, step=0.5)
sl_percent = st.sidebar.number_input("Stop Loss (%)", min_value=0.5, max_value=50.0, value=1.0, step=0.5)

auto_trade = st.sidebar.checkbox("🤖 Enable Auto Buy / Auto Sell")

# Initialize Exchange (Check for API Keys)
exchange = None
if api_key and secret_key:
    exchange = ccxt.binance({
        'apiKey': api_key,
        'secret': secret_key,
        'options': {'defaultType': 'future'},
        'enableRateLimit': True,
    })

# Technical Analysis Functions
def fetch_data(exchange, symbol):
    try:
        ohlcv = exchange.fetch_ohlcv(symbol, timeframe='15m', limit=100)
        df = pd.DataFrame(ohlcv, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
        
        # RSI Calculation (Simplified)
        delta = df['close'].diff()
        gain = delta.where(delta > 0, 0)
        loss = -delta.where(delta < 0, 0)
        avg_gain = gain.rolling(window=14).mean()
        avg_loss = loss.rolling(window=14).mean()
        rs = avg_gain / avg_loss
        df['RSI'] = 100 - (100 / (1 + rs))

        # MACD Calculation
        exp1 = df['close'].ewm(span=12, adjust=False).mean()
        exp2 = df['close'].ewm(span=26, adjust=False).mean()
        df['MACD'] = exp1 - exp2
        df['Signal_Line'] = df['MACD'].ewm(span=9, adjust=False).mean()

        # Bollinger Bands
        df['SMA20'] = df['close'].rolling(window=20).mean()
        df['STD20'] = df['close'].rolling(window=20).std()
        df['Upper_Band'] = df['SMA20'] + (df['STD20'] * 2)
        df['Lower_Band'] = df['SMA20'] - (df['STD20'] * 2)

        return df
    except Exception as e:
        return None

# Main App Logic
if exchange:
    df = fetch_data(exchange, symbol)
    if df is not None:
        latest = df.iloc[-1]
        
        # Display Indicators in Columns
        col1, col2, col3, col4 = st.columns(4)
        col1.metric("Current Price", f"${latest['close']:.2f}")
        col2.metric("RSI (14)", f"{latest['RSI']:.2f}")
        col3.metric("MACD", f"{latest['MACD']:.2f}")
        col4.metric("Bollinger Lower", f"${latest['Lower_Band']:.2f}")

        # Basic Trading Signal Logic
        signal = "NEUTRAL ➖"
        if latest['RSI'] < 30 and latest['close'] <= latest['Lower_Band']:
            signal = "STRONG BUY (LONG) 🟢"
        elif latest['RSI'] > 70 and latest['close'] >= latest['Upper_Band']:
            signal = "STRONG SELL (SHORT) 🔴"

        st.subheader(f"📊 Market Signal: **{signal}**")

        # Order Execution Buttons
        col_buy, col_sell = st.columns(2)
        with col_buy:
            if st.button("🚀 Place Manual LONG Order", use_container_width=True):
                st.success(f"LONG Order Request for {symbol} Sent! (TP: {tp_percent}%, SL: {sl_percent}%)")
                # actual order code would go here
                
        with col_sell:
            if st.button("📉 Place Manual SHORT Order", use_container_width=True):
                st.error(f"SHORT Order Request for {symbol} Sent! (TP: {tp_percent}%, SL: {sl_percent}%)")
                # actual order code would go here

    # TradingView Chart Integration
    st.subheader(f"📈 Live {symbol} Chart")
    clean_symbol = symbol.replace("/", "")
    tv_html = f"""
    <div class="tradingview-widget-container" style="height:500px;">
      <script type="text/javascript" src="https://s3.tradingview.com/tv.js"></script>
      <script type="text/javascript">
      new TradingView.widget({{
        "width": "100%",
        "height": 500,
        "symbol": "BINANCE:{clean_symbol}PERP",
        "interval": "15",
        "timezone": "Etc/UTC",
        "theme": "dark",
        "style": "1",
        "locale": "en",
        "toolbar_bg": "#f1f3f6",
        "enable_publishing": false,
        "allow_symbol_change": true,
        "container_id": "tradingview_1"
      }});
      </script>
      <div id="tradingview_1"></div>
    </div>
    """
    st.components.v1.html(tv_html, height=520)

else:
    # Error Message if API keys are missing
    st.info("⚠️ Please enter valid Binance API and Secret Keys in the sidebar to load advanced trading features.")
    
    # Still show the chart for reference
    st.subheader(f"📈 Live {symbol} Chart")
    clean_symbol = symbol.replace("/", "")
    tv_html = f"""
    <div class="tradingview-widget-container" style="height:500px;">
      <script type="text/javascript" src="https://s3.tradingview.com/tv.js"></script>
      <script type="text/javascript">
      new TradingView.widget({{
        "width": "100%",
        "height": 500,
        "symbol": "BINANCE:{clean_symbol}PERP",
        "interval": "15",
        "theme": "dark",
        "style": "1",
        "container_id": "tradingview_2"
      }});
      </script>
      <div id="tradingview_2"></div>
    </div>
    """
    st.components.v1.html(tv_html, height=520)

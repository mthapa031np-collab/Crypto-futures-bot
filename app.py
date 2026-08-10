import streamlit as st
import pandas as pd
import requests
import streamlit.components.v1 as components  # सच्याइएको लाइन
import time

# --- Page Config & Styling ---
st.set_page_config(
    page_title="Pro-Asset Exchange Interface",
    page_icon="💸",
    layout="wide",
    initial_sidebar_state="expanded",
)

# Custom CSS: Binance/Bybit को जस्तो Dark/Professional Theme
st.markdown("""
<style>
    [data-testid="stSidebar"] {
        background-color: #1e2329;
    }
    [data-testid="stSidebar"] label {
        color: #f0b90b !important;
        font-weight: bold;
    }
    .main-header {
        background-color: #0b0e11;
        color: #eaecef;
        padding: 10px;
        text-align: center;
        border-radius: 8px;
    }
    .stMetric {
        background-color: #2b313a;
        padding: 15px;
        border-radius: 10px;
        color: #ffffff;
    }
    .asset-card {
        background-color: #1e2329;
        padding: 20px;
        border-radius: 12px;
        border: 1px solid #474d57;
        margin-bottom: 15px;
    }
    .btn-long { background-color: #0ecb81; color: white; }
    .btn-short { background-color: #f6465d; color: white; }
</style>
""", unsafe_allow_html=True)


# TradingView Widget Generator
def create_tradingview_widget(symbol, height=650):
    tv_symbol = f"BINANCE:{symbol}USDT"
    chart_html = f"""
    <!-- TradingView Widget BEGIN -->
    <div class="tradingview-widget-container" style="height:100%;width:100%">
      <div id="tradingview_chart" style="height:{height}px;width:100%"></div>
      <script type="text/javascript" src="https://s3.tradingview.com/tv.js"></script>
      <script type="text/javascript">
      new TradingView.widget(
      {{
        "autosize": true,
        "symbol": "{tv_symbol}",
        "interval": "15",
        "theme": "dark",
        "style": "1",
        "locale": "en",
        "toolbar_bg": "#f1f3f6",
        "withcharts": true,
        "hide_side_toolbar": false,
        "studies": ["RSI@tv-basicstudies", "MASimple@tv-basicstudies"]
      }}
      );
      </script>
    </div>
    <!-- TradingView Widget END -->
    """
    return chart_html

# --- UI PHASE SELECTION ---
st.sidebar.title("💳 Navigation")
current_phase = st.sidebar.radio(
    "📊 Select Feature",
    ["🏠 Home", "📈 Markets", "🔥 Futures (Leverage)", "💰 Assets/Wallet"]
)

# --- 🏠 PHASE 1: HOME ---
if current_phase == "🏠 Home":
    st.markdown('<div class="main-header"><h2>📊 Exchange & AI Overview</h2></div>', unsafe_allow_html=True)
    st.write("")

    col_val, col_funds = st.columns([3, 1])
    with col_val:
        st.metric(label="Estimated Total Value (USDT)", value="764.04", delta="-1.38 USDT (-0.17%) Today")
    with col_funds:
        st.button("Add Funds 💰", type="primary")

    st.markdown("---")
    st.subheader("💡 Discover (Features & AI Trending)")
    col_r, col_s, col_o, col_m = st.columns(4)
    with col_r: st.button("🎁 Rewards Hub")
    with col_s: st.button("🏦 Simple Earn")
    with col_o: st.button("📝 Orders")
    with col_m: st.button("💎 Megadrop")
    
    col_a, col_p, col_mo, _ = st.columns(4)
    with col_a: st.button("📜 Account Statement")
    with col_p: st.button("🤝 P2P")
    with col_mo: st.button("➕ More")

    st.markdown("---")
    st.subheader("🤖 AI Trending: KOL Mentions")
    ai_col1, ai_col2 = st.columns(2)
    with ai_col1:
        st.write("**GUAUSDT** (KOL Mentions: 165)")
        st.caption("Price: 0.06637 (+85.24%)")
        st.progress(72)
        st.caption("<span style='color:#0ecb81;'>72.4% bullish</span> | <span style='color:#f6465d;'>27.6% bearish</span>", unsafe_allow_html=True)
    with ai_col2:
        st.write("**KUAI** (Countdown: 11H: 28M)")
        st.caption("Starts Soon: Trading Pair")

# --- 📈 PHASE 2: MARKETS ---
elif current_phase == "📈 Markets":
    st.markdown('<div class="main-header"><h2>🌍 Top 100 Crypto & Stocks</h2></div>', unsafe_allow_html=True)
    st.write("")
    
    market_cat = st.radio("Market Type", ["Crypto (Top 100)", "Stocks"], horizontal=True)
    
    if market_cat == "Crypto (Top 100)":
        cryptos = pd.DataFrame({
            "Pair": ["BTC/USDT", "ETH/USDT", "SOL/USDT", "XRP/USDT", "ONDO/USDT", "FET/USDT"],
            "Price ($)": ["65,489.1", "3,520.2", "162.8", "0.58", "0.75", "1.32"],
            "24h Change": ["-0.30%", "+1.2%", "-0.8%", "+3.4%", "+5.1%", "+2.8%"]
        })
        st.dataframe(cryptos, use_container_width=True)
        pair_tv = st.selectbox("Select Pair to View Chart", cryptos["Pair"])
        clean_symbol = pair_tv.replace("/USDT", "").replace("/", "")
        st.write(components.html(create_tradingview_widget(clean_symbol), height=660))
        
    else:
        stocks = pd.DataFrame({
            "Symbol": ["NVDA", "AAPL", "MSTR", "SHEL.L", "MSFT", "AMZN"],
            "Price ($)": ["120.4", "210.5", "1,520.1", "28.5", "440.2", "180.3"],
            "Change": ["+2.1%", "-0.1%", "+4.5%", "+0.7%", "+1.1%", "+0.9%"]
        })
        st.dataframe(stocks, use_container_width=True)

# --- 🔥 PHASE 3: FUTURES (Leverage) ---
elif current_phase == "🔥 Futures (Leverage)":
    st.markdown('<div class="main-header"><h2>⚡ Futures & Leverage Trading Bot</h2></div>', unsafe_allow_html=True)
    st.write("")
    
    col_left, col_right = st.columns([1, 2])
    
    with col_left:
        st.subheader("⚙️ Bot Configuration")
        pair = st.selectbox("Select Pair", ["BTC/USDT", "ETH/USDT", "SOL/USDT"])
        lev_slider = st.slider("Leverage", 1, 50, 5)
        st.markdown(f"**Current Leverage: {lev_slider}x**")
        tp = st.number_input("Take Profit (%)", 2.0, step=0.1)
        sl = st.number_input("Stop Loss (%)", 1.0, step=0.1)
        st.button("Activate Auto Bot 🤖", type="primary")

    with col_right:
        st.subheader("📊 Live Chart")
        clean_pair = pair.replace("/USDT", "")
        st.write(components.html(create_tradingview_widget(clean_pair), height=660))
        
        c1, c2 = st.columns(2)
        with c1: st.button("🟢 Buy/Long", use_container_width=True, type="primary")
        with c2: st.button("🔴 Sell/Short", use_container_width=True, type="primary")

# --- 💰 PHASE 4: ASSETS/WALLET ---
elif current_phase == "💰 Assets/Wallet":
    st.markdown('<div class="main-header"><h2>💰 Asset Wallet Structure</h2></div>', unsafe_allow_html=True)
    st.write("")
    
    st.metric(label="Total Balance (USDT)", value="764.04")
    
    st.markdown("---")
    asset_tabs = st.tabs(["🔒 Funds", "📊 Spot", "📈 Futures"])
    with asset_tabs[0]: st.write("**No Funds Staked Yet**")
    with asset_tabs[1]: st.write("**You hold: 0.01 BTC | 250 USDT**")
    with asset_tabs[2]: st.write("**Open Positions: BTC Long (5x)**")

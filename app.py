import streamlit as st
import pandas as pd
import requests
import streamlit.components.v1 as components

# 1. Page Config Setup
st.set_page_config(
    page_title="PRO AI TERMINAL",
    layout="wide",
    initial_sidebar_state="collapsed"
)

# 2. Inject Pro Dark Theme CSS (Halaska Studio UI)
st.markdown("""
<style>
    /* Global Reset & Base Theme */
    #MainMenu, footer, header { visibility: hidden; }
    .block-container {
        padding-top: 0.5rem !important;
        padding-bottom: 0rem !important;
        padding-left: 1rem !important;
        padding-right: 1rem !important;
        max-width: 100% !important;
    }
    .stApp {
        background-color: #080a0d;
        color: #9097a6;
    }

    /* Top Stats Card Bar */
    .top-bar {
        background-color: #0d1117;
        border: 1px solid #1c212d;
        border-radius: 6px;
        padding: 8px 16px;
        margin-bottom: 10px;
    }
    .stat-label { font-size: 10px; color: #5d6578; text-transform: uppercase; }
    .stat-value { font-size: 14px; font-weight: bold; color: #e1e4ea; }
    .val-green { color: #00c076; }
    .val-red { color: #ff4d4f; }

    /* Custom Input Fields */
    div[data-baseweb="select"] > div, div[data-baseweb="input"] > div {
        background-color: #131824 !important;
        border-color: #202738 !important;
        color: #ffffff !important;
    }
    
    /* Order Book Display */
    .ob-container {
        background-color: #0d1117;
        border: 1px solid #1c212d;
        border-radius: 6px;
        padding: 10px;
    }
    .ob-title { font-size: 11px; font-weight: 700; color: #60687b; text-transform: uppercase; margin-bottom: 6px; }
    
    /* Custom Execution Action Buttons */
    div.stButton > button[key="btn_buy"] {
        background-color: #00c076 !important;
        color: #ffffff !important;
        font-weight: bold;
        border: none;
        width: 100%;
        height: 42px;
        border-radius: 4px;
    }
    div.stButton > button[key="btn_sell"] {
        background-color: #ff4d4f !important;
        color: #ffffff !important;
        font-weight: bold;
        border: none;
        width: 100%;
        height: 42px;
        border-radius: 4px;
    }
</style>
""", unsafe_allow_html=True)

# 3. Dynamic Top 100 Crypto Fetcher
@st.cache_data(ttl=300)
def get_top_100_symbols():
    try:
        url = "https://api.binance.com/api/v3/ticker/24hr"
        res = requests.get(url, timeout=5)
        if res.status_code == 200:
            data = res.json()
            usdt_pairs = [d for d in data if d['symbol'].endswith('USDT') and not d['symbol'].startswith('UP') and not d['symbol'].startswith('DOWN')]
            # Sort by 24h quote volume to get top 100
            sorted_pairs = sorted(usdt_pairs, key=lambda x: float(x['quoteVolume']), reverse=True)[:100]
            return [d['symbol'] for d in sorted_pairs]
    except Exception:
        pass
    return ["BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT", "XRPUSDT", "ADAUSDT", "DOGEUSDT", "AVAXUSDT"]

# 4. Fetch Ticker Data for Selected Symbol
@st.cache_data(ttl=3)
def fetch_ticker_details(symbol):
    try:
        url = f"https://api.binance.com/api/v3/ticker/24hr?symbol={symbol}"
        res = requests.get(url, timeout=3)
        if res.status_code == 200:
            return res.json()
    except Exception:
        pass
    return None

# Top 100 List
top_100_list = get_top_100_symbols()

# --- HEADER CONTROLS & STATS BAR ---
col_sel, col_s1, col_s2, col_s3, col_s4, col_acc = st.columns([1.5, 1, 1, 1, 1, 1.5])

with col_sel:
    selected_symbol = st.selectbox("Search Crypto (Top 100)", top_100_list, index=0)

ticker_info = fetch_ticker_details(selected_symbol)

if ticker_info:
    last_p = float(ticker_info['lastPrice'])
    p_change = float(ticker_info['priceChangePercent'])
    high_p = float(ticker_info['highPrice'])
    low_p = float(ticker_info['lowPrice'])
    
    change_css = "val-green" if p_change >= 0 else "val-red"
    
    with col_s1:
        st.markdown(f"<div class='stat-label'>Price</div><div class='stat-value {change_css}'>${last_p:,.2f}</div>", unsafe_allow_html=True)
    with col_s2:
        st.markdown(f"<div class='stat-label'>24h Change</div><div class='stat-value {change_css}'>{p_change:+.2f}%</div>", unsafe_allow_html=True)
    with col_s3:
        st.markdown(f"<div class='stat-label'>24h High</div><div class='stat-value'>${high_p:,.2f}</div>", unsafe_allow_html=True)
    with col_s4:
        st.markdown(f"<div class='stat-label'>24h Low</div><div class='stat-value'>${low_p:,.2f}</div>", unsafe_allow_html=True)
else:
    with col_s1:
        st.write("Syncing Data...")

with col_acc:
    st.markdown("<div class='stat-label' style='text-align:right;'>Account Balance</div><div class='stat-value val-green' style='text-align:right;'>$27,594.00 USDT</div>", unsafe_allow_html=True)

st.divider()

# --- MAIN TERMINAL GRID (3 COLUMNS) ---
chart_col, depth_col, exec_col = st.columns([3.2, 1.2, 1.2])

# A. CHART PANEL
with chart_col:
    tv_code = f"""
    <div class="tradingview-widget-container" style="height:580px;width:100%;">
      <div id="tradingview_chart" style="height:580px;width:100%;"></div>
      <script type="text/javascript" src="https://s3.tradingview.com/tv.js"></script>
      <script type="text/javascript">
      new TradingView.widget({{
        "autosize": true,
        "symbol": "BINANCE:{selected_symbol}",
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
    components.html(tv_code, height=585)

# B. ORDER BOOK PANEL
with depth_col:
    st.markdown("<div class='ob-title'>📊 Order Book</div>", unsafe_allow_html=True)
    if ticker_info:
        curr_p = float(ticker_info['lastPrice'])
        asks_df = pd.DataFrame({
            "Price ($)": [round(curr_p + (i*curr_p*0.0005), 2) for i in range(5, 0, -1)],
            "Size": [0.42, 1.10, 0.08, 2.45, 0.89]
        })
        bids_df = pd.DataFrame({
            "Price ($)": [round(curr_p - (i*curr_p*0.0005), 2) for i in range(1, 6)],
            "Size": [1.89, 0.32, 5.12, 0.75, 1.20]
        })
        
        st.caption("🔴 Asks (Sell)")
        st.dataframe(asks_df.style.format({"Price ($)": "${:,.2f}", "Size": "{:.2f}"}), use_container_width=True, height=180, hide_index=True)
        
        st.markdown(f"<div style='font-size:14px; font-weight:bold; color:#00c076; text-align:center; margin:4px 0;'>${curr_p:,.2f}</div>", unsafe_allow_html=True)
        
        st.caption("🟢 Bids (Buy)")
        st.dataframe(bids_df.style.format({"Price ($)": "${:,.2f}", "Size": "{:.2f}"}), use_container_width=True, height=180, hide_index=True)

# C. EXECUTION PANEL (Fully Clickable)
with exec_col:
    st.markdown("<div class='ob-title'>⚡ Execution Engine</div>", unsafe_allow_html=True)
    
    # Clickable Order Type Tabs
    order_mode = st.radio("Order Type", ["Limit", "Market", "Pro AI"], horizontal=True, label_visibility="collapsed")
    
    margin_type = st.selectbox("Margin / Leverage", ["Isolated 20x", "Cross 50x", "Cross 100x"])
    
    if order_mode == "Limit":
        entry_price = st.number_input("Order Price ($)", value=float(ticker_info['lastPrice']) if ticker_info else 100.0)
    elif order_mode == "Pro AI":
        st.success("🤖 AI Strategy: Auto Entry/Exit Signals Active")
    
    trade_amt = st.number_input("Amount (USDT)", min_value=10.0, value=100.0, step=10.0)
    tp_sl_toggle = st.checkbox("Take Profit / Stop Loss")
    
    if tp_sl_toggle:
        st.text_input("TP Price ($)", placeholder="Take Profit")
        st.text_input("SL Price ($)", placeholder="Stop Loss")

    st.markdown("<br>", unsafe_allow_html=True)
    
    # Action Buttons
    if st.button("BUY / LONG", key="btn_buy"):
        st.toast(f"✅ Long Order Executed for {selected_symbol}!")

    if st.button("SELL / SHORT", key="btn_sell"):
        st.toast(f"🔻 Short Order Executed for {selected_symbol}!")

# --- BOTTOM PANEL: POSITIONS & LOGS ---
st.divider()
st.subheader("📋 Active Positions & History")
tab_pos, tab_orders, tab_ai = st.tabs(["Open Positions", "Order History", "AI Bot Logs"])

with tab_pos:
    pos_data = pd.DataFrame([
        {"Symbol": "BTCUSDT", "Type": "LONG 20x", "Size": "0.50 BTC", "Entry Price": "$63,950.00", "Mark Price": "$64,108.01", "PNL (ROE%)": "+$790.05 (+24.5%)"},
        {"Symbol": "ETHUSDT", "Type": "SHORT 10x", "Size": "4.00 ETH", "Entry Price": "$3,480.00", "Mark Price": "$3,450.20", "PNL (ROE%)": "+$119.20 (+8.2%)"}
    ])
    st.dataframe(pos_data, use_container_width=True, hide_index=True)

with tab_orders:
    st.caption("No open orders waiting for execution.")

with tab_ai:
    st.code(f"System: Online\nMarket Feed: Binance Public WebSocket Sync\nActive Pair: {selected_symbol}\nAI Strategy: Signal Ready", language="text")

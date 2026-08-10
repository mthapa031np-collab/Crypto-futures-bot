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

# Initialize Session State Variables
if "order_mode" not in st.session_state:
    st.session_state.order_mode = "Limit"

# 2. Ultra-Dark UI Styling
st.markdown("""
<style>
#MainMenu, footer, header { visibility: hidden; }
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
.stat-label { font-size: 10px; color: #5d6578; text-transform: uppercase; }
.stat-value { font-size: 13px; font-weight: bold; color: #e1e4ea; }
.val-green { color: #00c076 !important; }
.val-red { color: #ff4d4f !important; }

/* Custom Form & Order Book Styling */
div[data-baseweb="select"] > div, div[data-baseweb="input"] > div {
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

/* Buttons */
div.stButton > button[key="btn_buy"] {
    background-color: #00c076 !important;
    color: #ffffff !important;
    font-weight: bold;
    border: none;
    width: 100%;
    height: 42px;
}
div.stButton > button[key="btn_sell"] {
    background-color: #ff4d4f !important;
    color: #ffffff !important;
    font-weight: bold;
    border: none;
    width: 100%;
    height: 42px;
}
</style>
""", unsafe_allow_html=True)

# 3. Fast Binance Ticker Fetcher with Fallback
# NOTE: api.binance.com often returns HTTP 451 when called from cloud/datacenter
# IPs (Render, AWS, Heroku, etc). We try multiple base URLs in order until one works.
BINANCE_HOSTS = [
    "https://data-api.binance.vision",  # public market-data mirror, cloud-friendly
    "https://api.binance.com",
    "https://api1.binance.com",
    "https://api2.binance.com",
]

@st.cache_data(ttl=2)
def get_live_ticker(symbol):
    last_error = None
    for host in BINANCE_HOSTS:
        try:
            url = f"{host}/api/v3/ticker/24hr?symbol={symbol}"
            res = requests.get(url, timeout=3, headers={"User-Agent": "Mozilla/5.0"})
            if res.status_code == 200:
                return res.json()
            last_error = f"{host} -> HTTP {res.status_code}"
        except Exception as e:
            last_error = f"{host} -> {e}"
            continue
    st.session_state["last_ticker_error"] = last_error
    return None

# 3b. REAL Order Book Depth Fetcher (NEW - replaces fake data)
@st.cache_data(ttl=1)
def get_order_book(symbol, limit=10):
    """Fetch real live order book (bids/asks) from Binance public API, with fallback hosts."""
    last_error = None
    for host in BINANCE_HOSTS:
        try:
            url = f"{host}/api/v3/depth?symbol={symbol}&limit={limit}"
            res = requests.get(url, timeout=3, headers={"User-Agent": "Mozilla/5.0"})
            if res.status_code == 200:
                return res.json()
            last_error = f"{host} -> HTTP {res.status_code}"
        except Exception as e:
            last_error = f"{host} -> {e}"
            continue
    st.session_state["last_ob_error"] = last_error
    return None

# 3c. Kline (candlestick) fetcher for technical analysis
@st.cache_data(ttl=15)
def get_klines(symbol, interval="15m", limit=100):
    """Fetch recent candlestick data used to compute RSI/EMA signals."""
    for host in BINANCE_HOSTS:
        try:
            url = f"{host}/api/v3/klines?symbol={symbol}&interval={interval}&limit={limit}"
            res = requests.get(url, timeout=3, headers={"User-Agent": "Mozilla/5.0"})
            if res.status_code == 200:
                raw = res.json()
                closes = [float(c[4]) for c in raw]
                highs = [float(c[2]) for c in raw]
                lows = [float(c[3]) for c in raw]
                return closes, highs, lows
        except Exception:
            continue
    return None, None, None


def compute_rsi(closes, period=14):
    """Standard RSI calculation."""
    if len(closes) < period + 1:
        return None
    deltas = [closes[i] - closes[i - 1] for i in range(1, len(closes))]
    gains = [d if d > 0 else 0 for d in deltas]
    losses = [-d if d < 0 else 0 for d in deltas]
    avg_gain = sum(gains[:period]) / period
    avg_loss = sum(losses[:period]) / period
    for i in range(period, len(gains)):
        avg_gain = (avg_gain * (period - 1) + gains[i]) / period
        avg_loss = (avg_loss * (period - 1) + losses[i]) / period
    if avg_loss == 0:
        return 100.0
    rs = avg_gain / avg_loss
    return 100 - (100 / (1 + rs))


def compute_ema(closes, period):
    """Standard EMA calculation."""
    if len(closes) < period:
        return None
    k = 2 / (period + 1)
    ema = sum(closes[:period]) / period
    for price in closes[period:]:
        ema = price * k + ema * (1 - k)
    return ema


def compute_atr(highs, lows, closes, period=14):
    """Average True Range - used to size TP/SL distance based on volatility."""
    if len(closes) < period + 1:
        return None
    trs = []
    for i in range(1, len(closes)):
        tr = max(
            highs[i] - lows[i],
            abs(highs[i] - closes[i - 1]),
            abs(lows[i] - closes[i - 1]),
        )
        trs.append(tr)
    return sum(trs[-period:]) / period


def get_ai_signal(symbol, last_price):
    """
    Combine RSI(14) + EMA(9/21) crossover into a simple directional signal,
    and use ATR(14) to size Take Profit / Stop Loss distances.
    This is a rule-based technical signal generator for the demo terminal -
    NOT financial advice and not guaranteed to be profitable.
    """
    closes, highs, lows = get_klines(symbol, interval="15m", limit=100)
    if not closes or len(closes) < 25:
        return None

    rsi = compute_rsi(closes, 14)
    ema_fast = compute_ema(closes, 9)
    ema_slow = compute_ema(closes, 21)
    atr = compute_atr(highs, lows, closes, 14)

    if rsi is None or ema_fast is None or ema_slow is None or atr is None:
        return None

    # Decide direction from trend (EMA crossover) + momentum (RSI)
    if ema_fast > ema_slow and rsi < 70:
        direction = "LONG"
        confidence = "High" if rsi < 50 else "Medium"
    elif ema_fast < ema_slow and rsi > 30:
        direction = "SHORT"
        confidence = "High" if rsi > 50 else "Medium"
    else:
        direction = "NEUTRAL"
        confidence = "Low"

    # Size TP/SL off ATR (volatility-based, ~1.5x ATR for SL, ~2.5x ATR for TP -> positive risk/reward)
    if direction == "LONG":
        tp = last_price + (atr * 2.5)
        sl = last_price - (atr * 1.5)
    elif direction == "SHORT":
        tp = last_price - (atr * 2.5)
        sl = last_price + (atr * 1.5)
    else:
        tp = last_price + (atr * 2.5)
        sl = last_price - (atr * 1.5)

    return {
        "direction": direction,
        "confidence": confidence,
        "rsi": rsi,
        "ema_fast": ema_fast,
        "ema_slow": ema_slow,
        "atr": atr,
        "tp": round(tp, 4),
        "sl": round(sl, 4),
    }

# Top Major Crypto List
TOP_SYMBOLS = [
    "BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT", "XRPUSDT",
    "ADAUSDT", "DOGEUSDT", "AVAXUSDT", "LINKUSDT", "DOTUSDT",
    "NEARUSDT", "SUIUSDT", "APTUSDT", "MATICUSDT", "LTCUSDT"
]

# --- TOP HEADER BAR ---
c_sel, c_p, c_ch, c_hi, c_lo, c_bal = st.columns([1.5, 1, 1, 1, 1, 1.5])

with c_sel:
    selected_pair = st.selectbox("Select Crypto Pair", TOP_SYMBOLS, index=0)

ticker = get_live_ticker(selected_pair)

if ticker:
    last_price = float(ticker['lastPrice'])
    price_change = float(ticker['priceChangePercent'])
    high_price = float(ticker['highPrice'])
    low_price = float(ticker['lowPrice'])
    change_css = "val-green" if price_change >= 0 else "val-red"

    with c_p:
        st.markdown(f"<div class='stat-label'>Market Price</div><div class='stat-value {change_css}'>${last_price:,.2f}</div>", unsafe_allow_html=True)
    with c_ch:
        st.markdown(f"<div class='stat-label'>24h Change</div><div class='stat-value {change_css}'>{price_change:+.2f}%</div>", unsafe_allow_html=True)
    with c_hi:
        st.markdown(f"<div class='stat-label'>24h High</div><div class='stat-value'>${high_price:,.2f}</div>", unsafe_allow_html=True)
    with c_lo:
        st.markdown(f"<div class='stat-label'>24h Low</div><div class='stat-value'>${low_price:,.2f}</div>", unsafe_allow_html=True)
else:
    last_price = 0.0
    with c_p:
        err = st.session_state.get("last_ticker_error", "")
        st.markdown(f"<div class='stat-label'>Market Price</div><div class='stat-value val-red'>Connecting... {'⚠️' if err else ''}</div>", unsafe_allow_html=True)
        if err:
            st.caption(f"⚠️ {err}")

with c_bal:
    st.markdown("<div class='stat-label' style='text-align:right;'>Account Balance</div><div class='stat-value val-green' style='text-align:right;'>$27,594.00 USDT</div>", unsafe_allow_html=True)

st.divider()

# --- MAIN TERMINAL GRID ---
col_chart, col_depth, col_exec = st.columns([3.2, 1.2, 1.3])

# A. LIVE CHART
with col_chart:
    tv_widget = f"""
    <div class="tradingview-widget-container" style="height:560px;width:100%;">
      <div id="tradingview_chart" style="height:560px;width:100%;"></div>
      <script type="text/javascript" src="https://s3.tradingview.com/tv.js"></script>
      <script type="text/javascript">
      new TradingView.widget({{
        "autosize": true,
        "symbol": "BINANCE:{selected_pair}",
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
    components.html(tv_widget, height=565)

# B. DYNAMIC ORDER BOOK (NOW USING REAL BINANCE DEPTH DATA)
with col_depth:
    st.markdown("<div class='ob-header'>📊 Live Order Book</div>", unsafe_allow_html=True)

    depth = get_order_book(selected_pair, limit=10)

    if depth and depth.get("asks") and depth.get("bids"):
        # Binance depth format: [["price", "quantity"], ...]
        # asks sorted low->high by Binance; we want top 5 closest to market price, shown high->low visually
        asks_raw = depth["asks"][:5]
        bids_raw = depth["bids"][:5]

        asks_df = pd.DataFrame(
            [{"Price ($)": float(p), "Size": float(q)} for p, q in asks_raw]
        ).sort_values("Price ($)", ascending=False).reset_index(drop=True)

        bids_df = pd.DataFrame(
            [{"Price ($)": float(p), "Size": float(q)} for p, q in bids_raw]
        ).sort_values("Price ($)", ascending=False).reset_index(drop=True)

        st.caption("🔴 Sell Orders (Asks)")
        st.dataframe(
            asks_df.style.format({"Price ($)": "${:,.2f}", "Size": "{:.4f}"}),
            use_container_width=True, height=170, hide_index=True
        )

        mid_price = last_price if last_price > 0 else (asks_df["Price ($)"].min() + bids_df["Price ($)"].max()) / 2
        st.markdown(f"<div style='font-size:14px; font-weight:bold; color:#00c076; text-align:center; margin:6px 0;'>${mid_price:,.2f}</div>", unsafe_allow_html=True)

        st.caption("🟢 Buy Orders (Bids)")
        st.dataframe(
            bids_df.style.format({"Price ($)": "${:,.2f}", "Size": "{:.4f}"}),
            use_container_width=True, height=170, hide_index=True
        )
    else:
        st.info("Loading Order Book...")
        ob_err = st.session_state.get("last_ob_error", "")
        if ob_err:
            st.caption(f"⚠️ {ob_err}")

# C. DYNAMIC EXECUTION ENGINE
with col_exec:
    st.markdown("<div class='ob-header'>⚡ Execution Engine</div>", unsafe_allow_html=True)

    # Order Mode Selector
    mode = st.radio("Mode", ["Limit", "Market", "Pro AI"], horizontal=True, key="order_mode")
    margin_mode = st.selectbox("Margin / Leverage", ["Isolated 20x", "Cross 50x", "Cross 100x"])

    # Dynamic Fields based on Selection
    ai_signal = None
    if mode == "Limit":
        order_price = st.number_input("Order Price ($)", value=float(last_price) if last_price > 0 else 100.0, step=0.1)
    elif mode == "Market":
        st.info("⚡ Execution Price: Instant Best Market Fill")
        order_price = last_price
    else:  # Pro AI Mode
        order_price = last_price
        if last_price > 0:
            ai_signal = get_ai_signal(selected_pair, last_price)

        if ai_signal:
            dir_color = "val-green" if ai_signal["direction"] == "LONG" else ("val-red" if ai_signal["direction"] == "SHORT" else "")
            dir_icon = "🟢" if ai_signal["direction"] == "LONG" else ("🔴" if ai_signal["direction"] == "SHORT" else "⚪")
            st.markdown(
                f"<div style='background:#131824;border-radius:6px;padding:10px;margin-bottom:6px;'>"
                f"<div class='stat-label'>AI Signal (RSI + EMA 9/21)</div>"
                f"<div class='stat-value {dir_color}' style='font-size:16px;'>{dir_icon} {ai_signal['direction']} · {ai_signal['confidence']} confidence</div>"
                f"<div class='stat-label' style='margin-top:4px;'>RSI(14): {ai_signal['rsi']:.1f} · EMA9: {ai_signal['ema_fast']:.4f} · EMA21: {ai_signal['ema_slow']:.4f}</div>"
                f"</div>",
                unsafe_allow_html=True
            )
            st.caption("🤖 Rule-based technical signal for this demo terminal — not financial advice, not guaranteed.")
        else:
            st.info("🤖 Calculating AI signal from live market data...")

    amount_usdt = st.number_input("Amount (USDT)", min_value=10.0, value=100.0, step=10.0)

    # Take Profit & Stop Loss Controls
    show_tpsl = st.checkbox("Take Profit / Stop Loss", value=True if mode == "Pro AI" else False)
    if show_tpsl:
        col_tp, col_sl = st.columns(2)
        if mode == "Pro AI" and ai_signal:
            # Auto-filled by the AI signal engine (ATR-based), still editable by the user
            default_tp = ai_signal["tp"]
            default_sl = ai_signal["sl"]
        else:
            default_tp = round(last_price * 1.02, 2) if last_price > 0 else 0.0
            default_sl = round(last_price * 0.98, 2) if last_price > 0 else 0.0
        with col_tp:
            st.number_input("TP Price ($)", value=default_tp, step=0.1, key="tp_price")
        with col_sl:
            st.number_input("SL Price ($)", value=default_sl, step=0.1, key="sl_price")

    st.markdown("<br>", unsafe_allow_html=True)
    btn_l = st.button("BUY / LONG", key="btn_buy")
    btn_s = st.button("SELL / SHORT", key="btn_sell")

    if btn_l:
        st.toast(f"✅ Long Order Placed for {selected_pair} at ${order_price:,.2f}!")
    if btn_s:
        st.toast(f"🔻 Short Order Placed for {selected_pair} at ${order_price:,.2f}!")

# --- BOTTOM PANEL: ACTIVE POSITIONS ---
st.divider()
st.subheader("📋 Account Positions & Trade Logs")
tab_pos, tab_logs = st.tabs(["Active Positions", "AI Strategy Logs"])

with tab_pos:
    if last_price > 0:
        pos_data = pd.DataFrame([
            {
                "Symbol": selected_pair,
                "Type": "LONG 20x",
                "Size": f"{round(1000 / last_price, 3)} {selected_pair.replace('USDT','')}",
                "Entry Price": f"${round(last_price * 0.99, 2):,.2f}",
                "Current Price": f"${last_price:,.2f}",
                "Unrealized PNL": "+$20.40 (+20.4%)"
            }
        ])
        st.dataframe(pos_data, use_container_width=True, hide_index=True)
    else:
        st.info("No active open positions.")

with tab_logs:
    if st.session_state.get("order_mode") == "Pro AI" and last_price > 0:
        sig = get_ai_signal(selected_pair, last_price)
        if sig:
            st.code(
                f"System Status: ONLINE\n"
                f"Pair: {selected_pair}\n"
                f"Market Feed: Active\n"
                f"AI Risk Engine: Enabled (Max 2% Risk per trade)\n"
                f"--- Pro AI Signal ---\n"
                f"Direction: {sig['direction']}  (Confidence: {sig['confidence']})\n"
                f"RSI(14): {sig['rsi']:.2f}\n"
                f"EMA9: {sig['ema_fast']:.4f}  |  EMA21: {sig['ema_slow']:.4f}\n"
                f"ATR(14): {sig['atr']:.4f}\n"
                f"Auto TP: ${sig['tp']:,.4f}  |  Auto SL: ${sig['sl']:,.4f}",
                language="text"
            )
        else:
            st.code(f"System Status: ONLINE\nPair: {selected_pair}\nMarket Feed: Active\nAI Risk Engine: Enabled (Max 2% Risk per trade)\nCalculating signal...", language="text")
    else:
        st.code(f"System Status: ONLINE\nPair: {selected_pair}\nMarket Feed: Active\nAI Risk Engine: Enabled (Max 2% Risk per trade)", language="text")

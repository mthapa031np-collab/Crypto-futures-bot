import streamlit as st
import pandas as pd
import numpy as np
import requests
import hmac
import hashlib
import time
import os
from urllib.parse import urlencode
import streamlit.components.v1 as components

st.set_page_config(page_title="PRO AI TERMINAL", layout="wide", initial_sidebar_state="expanded")

# ============================================================
# SESSION STATE
# ============================================================
if "order_mode" not in st.session_state:
    st.session_state.order_mode = "Limit"
if "use_testnet" not in st.session_state:
    st.session_state.use_testnet = True
if "last_ai_signal_time" not in st.session_state:
    st.session_state.last_ai_signal_time = 0
if "trade_log" not in st.session_state:
    st.session_state.trade_log = []

# ============================================================
# STYLING (unchanged from your original)
# ============================================================
st.markdown("""
<style>
#MainMenu, footer, header { visibility: hidden; }
.block-container { padding-top: 0.5rem !important; padding-bottom: 0rem !important;
    padding-left: 0.8rem !important; padding-right: 0.8rem !important; max-width: 100% !important; }
.stApp { background-color: #080a0d; color: #9097a6; }
.stat-label { font-size: 10px; color: #5d6578; text-transform: uppercase; }
.stat-value { font-size: 13px; font-weight: bold; color: #e1e4ea; }
.val-green { color: #00c076 !important; }
.val-red { color: #ff4d4f !important; }
div[data-baseweb="select"] > div, div[data-baseweb="input"] > div {
    background-color: #131824 !important; border-color: #202738 !important; color: #ffffff !important; }
.ob-header { font-size: 11px; font-weight: 700; color: #60687b; text-transform: uppercase; margin-bottom: 6px; }
div.stButton > button[key="btn_buy"] { background-color: #00c076 !important; color:#fff !important; font-weight:bold; border:none; width:100%; height:42px; }
div.stButton > button[key="btn_sell"] { background-color: #ff4d4f !important; color:#fff !important; font-weight:bold; border:none; width:100%; height:42px; }
.rsi-box { background:#131824; border:1px solid #202738; border-radius:6px; padding:8px; text-align:center; }
.warn-box { background:#2a1810; border:1px solid #ff8a00; border-radius:6px; padding:8px; font-size:12px; color:#ffb84d; }
</style>
""", unsafe_allow_html=True)

# ============================================================
# BINANCE FUTURES API LAYER
# ============================================================
LIVE_BASE = "https://fapi.binance.com"
TESTNET_BASE = "https://testnet.binancefuture.com"


def get_base_url():
    return TESTNET_BASE if st.session_state.use_testnet else LIVE_BASE


def get_api_keys():
    # Keys are read from session (sidebar, never saved to disk) or environment variables.
    # NEVER hardcode real API keys in this file or commit them to GitHub.
    api_key = st.session_state.get("api_key") or os.environ.get("BINANCE_API_KEY", "")
    api_secret = st.session_state.get("api_secret") or os.environ.get("BINANCE_API_SECRET", "")
    return api_key, api_secret


def signed_request(method, path, params=None):
    api_key, api_secret = get_api_keys()
    if not api_key or not api_secret:
        return {"error": "No API key/secret set. Add them in the sidebar first."}
    params = params or {}
    params["timestamp"] = int(time.time() * 1000)
    params["recvWindow"] = 5000
    query = urlencode(params)
    signature = hmac.new(api_secret.encode(), query.encode(), hashlib.sha256).hexdigest()
    params["signature"] = signature
    headers = {"X-MBX-APIKEY": api_key}
    url = get_base_url() + path
    try:
        if method == "GET":
            r = requests.get(url, headers=headers, params=params, timeout=5)
        elif method == "POST":
            r = requests.post(url, headers=headers, params=params, timeout=5)
        elif method == "DELETE":
            r = requests.delete(url, headers=headers, params=params, timeout=5)
        return r.json()
    except Exception as e:
        return {"error": str(e)}


@st.cache_data(ttl=2)
def get_live_ticker(symbol):
    try:
        url = f"https://fapi.binance.com/fapi/v1/ticker/24hr?symbol={symbol}"
        res = requests.get(url, timeout=2.5)
        if res.status_code == 200:
            return res.json()
    except Exception:
        pass
    return None


@st.cache_data(ttl=5)
def get_klines(symbol, interval="15m", limit=100):
    try:
        url = f"https://fapi.binance.com/fapi/v1/klines?symbol={symbol}&interval={interval}&limit={limit}"
        res = requests.get(url, timeout=3)
        if res.status_code == 200:
            df = pd.DataFrame(res.json(), columns=[
                "open_time", "open", "high", "low", "close", "volume",
                "close_time", "qav", "trades", "tbv", "tqv", "ignore"])
            df["close"] = df["close"].astype(float)
            return df
    except Exception:
        pass
    return None


def calculate_rsi(closes, period=14):
    delta = closes.diff()
    gain = delta.where(delta > 0, 0.0)
    loss = -delta.where(delta < 0, 0.0)
    avg_gain = gain.rolling(period).mean()
    avg_loss = loss.rolling(period).mean()
    rs = avg_gain / avg_loss.replace(0, np.nan)
    rsi = 100 - (100 / (1 + rs))
    return rsi.fillna(50)


def get_account_balance():
    data = signed_request("GET", "/fapi/v2/balance")
    if isinstance(data, list):
        for asset in data:
            if asset.get("asset") == "USDT":
                return float(asset.get("availableBalance", 0))
    return None


def get_open_positions(symbol):
    data = signed_request("GET", "/fapi/v2/positionRisk", {"symbol": symbol})
    if isinstance(data, list):
        for p in data:
            if float(p.get("positionAmt", 0)) != 0:
                return p
    return None


def set_leverage(symbol, leverage):
    return signed_request("POST", "/fapi/v1/leverage", {"symbol": symbol, "leverage": leverage})


def place_market_order(symbol, side, quantity):
    return signed_request("POST", "/fapi/v1/order", {
        "symbol": symbol, "side": side, "type": "MARKET", "quantity": quantity})


def place_tp_sl(symbol, position_side_close, quantity, tp_price, sl_price):
    """After a position is open, attach a TAKE_PROFIT_MARKET and STOP_MARKET order that closes it."""
    results = {}
    results["tp"] = signed_request("POST", "/fapi/v1/order", {
        "symbol": symbol, "side": position_side_close, "type": "TAKE_PROFIT_MARKET",
        "stopPrice": round(tp_price, 2), "closePosition": "true", "workingType": "MARK_PRICE"})
    results["sl"] = signed_request("POST", "/fapi/v1/order", {
        "symbol": symbol, "side": position_side_close, "type": "STOP_MARKET",
        "stopPrice": round(sl_price, 2), "closePosition": "true", "workingType": "MARK_PRICE"})
    return results


def calc_position_size(balance, risk_pct, entry_price, sl_price):
    """Position size so that a stop-loss hit only loses risk_pct of balance."""
    if balance is None or entry_price is None or sl_price is None:
        return 0.0
    risk_amount = balance * (risk_pct / 100)
    sl_distance = abs(entry_price - sl_price)
    if sl_distance <= 0:
        return 0.0
    qty = risk_amount / sl_distance
    return round(qty, 3)


TOP_SYMBOLS = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT", "XRPUSDT", "ADAUSDT",
               "DOGEUSDT", "AVAXUSDT", "LINKUSDT", "DOTUSDT", "NEARUSDT", "SUIUSDT"]

# ============================================================
# SIDEBAR: API KEYS + SAFETY SWITCH
# ============================================================
with st.sidebar:
    st.markdown("### 🔑 Binance API")
    st.session_state.use_testnet = st.toggle("Use Testnet (fake money, safe)", value=st.session_state.use_testnet)
    if not st.session_state.use_testnet:
        st.markdown("<div class='warn-box'>⚠️ LIVE MODE — real orders, real money. Double-check leverage and risk % before enabling Pro AI.</div>", unsafe_allow_html=True)
    st.session_state.api_key = st.text_input("API Key", type="password", value=st.session_state.get("api_key", ""))
    st.session_state.api_secret = st.text_input("API Secret", type="password", value=st.session_state.get("api_secret", ""))
    st.caption("Keys are kept only in this browser session — never written to the code or GitHub.")
    st.divider()
    st.markdown("### 🛡️ Risk Settings")
    risk_pct = st.slider("Risk per trade (% of balance)", 0.5, 5.0, 2.0, 0.5)
    rsi_oversold = st.slider("RSI Oversold (buy signal)", 10, 40, 30)
    rsi_overbought = st.slider("RSI Overbought (sell signal)", 60, 90, 70)

# ============================================================
# TOP HEADER
# ============================================================
c_sel, c_p, c_ch, c_hi, c_lo, c_bal = st.columns([1.5, 1, 1, 1, 1, 1.5])

with c_sel:
    selected_pair = st.selectbox("Select Crypto Pair", TOP_SYMBOLS, index=0)

ticker = get_live_ticker(selected_pair)
last_price = 0.0
if ticker:
    last_price = float(ticker["lastPrice"])
    price_change = float(ticker["priceChangePercent"])
    high_price = float(ticker["highPrice"])
    low_price = float(ticker["lowPrice"])
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
    with c_p:
        st.markdown("<div class='stat-label'>Market Price</div><div class='stat-value'>Connecting...</div>", unsafe_allow_html=True)

api_key, api_secret = get_api_keys()
if api_key and api_secret:
    live_balance = get_account_balance()
    bal_display = f"${live_balance:,.2f} USDT" if live_balance is not None else "⚠️ Check API keys"
else:
    live_balance = None
    bal_display = "No API key set"

with c_bal:
    st.markdown(f"<div class='stat-label' style='text-align:right;'>Account Balance {'(Testnet)' if st.session_state.use_testnet else '(LIVE)'}</div><div class='stat-value val-green' style='text-align:right;'>{bal_display}</div>", unsafe_allow_html=True)

st.divider()

# ============================================================
# RSI CALCULATION
# ============================================================
klines_df = get_klines(selected_pair, "15m", 100)
current_rsi = None
if klines_df is not None:
    rsi_series = calculate_rsi(klines_df["close"])
    current_rsi = float(rsi_series.iloc[-1])

# ============================================================
# MAIN GRID
# ============================================================
col_chart, col_depth, col_exec = st.columns([3.0, 1.2, 1.4])

with col_chart:
    tv_widget = f"""
    <div class="tradingview-widget-container" style="height:520px;width:100%;">
    <div id="tradingview_chart" style="height:520px;width:100%;"></div>
    <script type="text/javascript" src="https://s3.tradingview.com/tv.js"></script>
    <script type="text/javascript">
    new TradingView.widget({{
        "autosize": true, "symbol": "BINANCE:{selected_pair}", "interval": "15",
        "timezone": "Etc/UTC", "theme": "dark", "style": "1", "locale": "en",
        "enable_publishing": false, "hide_side_toolbar": false, "allow_symbol_change": true,
        "container_id": "tradingview_chart", "backgroundColor": "#0d1117", "gridColor": "#161b26"
    }});
    </script>
    </div>
    """
    components.html(tv_widget, height=525)

    # RSI readout row
    if current_rsi is not None:
        rsi_css = "val-red" if current_rsi > rsi_overbought else ("val-green" if current_rsi < rsi_oversold else "")
        signal_text = "OVERBOUGHT (sell zone)" if current_rsi > rsi_overbought else ("OVERSOLD (buy zone)" if current_rsi < rsi_oversold else "Neutral")
        st.markdown(f"<div class='rsi-box'><span class='stat-label'>RSI (14, 15m)</span><br><span class='stat-value {rsi_css}' style='font-size:18px;'>{current_rsi:.1f}</span> — {signal_text}</div>", unsafe_allow_html=True)

with col_depth:
    st.markdown("<div class='ob-header'>📊 Live Order Book</div>", unsafe_allow_html=True)
    if last_price > 0:
        step = last_price * 0.0003
        asks_df = pd.DataFrame({"Price ($)": [round(last_price + (i * step), 2) for i in range(5, 0, -1)],
                                 "Size": [0.35, 1.12, 0.08, 2.45, 0.91]})
        bids_df = pd.DataFrame({"Price ($)": [round(last_price - (i * step), 2) for i in range(1, 6)],
                                 "Size": [1.45, 0.62, 3.12, 0.85, 1.10]})
        st.caption("🔴 Sell Orders (Asks) — illustrative depth")
        st.dataframe(asks_df.style.format({"Price ($)": "${:,.2f}", "Size": "{:.2f}"}), width='stretch', height=170, hide_index=True)
        st.markdown(f"<div style='font-size:14px; font-weight:bold; color:#00c076; text-align:center; margin:6px 0;'>${last_price:,.2f}</div>", unsafe_allow_html=True)
        st.caption("🟢 Buy Orders (Bids) — illustrative depth")
        st.dataframe(bids_df.style.format({"Price ($)": "${:,.2f}", "Size": "{:.2f}"}), width='stretch', height=170, hide_index=True)
    else:
        st.info("Loading Order Book...")

with col_exec:
    st.markdown("<div class='ob-header'>⚡ Execution Engine</div>", unsafe_allow_html=True)
    mode = st.radio("Mode", ["Limit", "Market", "Pro AI"], horizontal=True, key="order_mode")
    leverage_choice = st.selectbox("Margin / Leverage", ["Isolated 5x", "Isolated 10x", "Isolated 20x"])
    leverage_val = int(leverage_choice.split()[1].replace("x", ""))

    if mode == "Limit":
        order_price = st.number_input("Order Price ($)", value=float(last_price) if last_price > 0 else 100.0, step=0.1)
    elif mode == "Market":
        st.info("⚡ Execution Price: Instant Best Market Fill")
        order_price = last_price
    else:
        st.success("🤖 AI Mode: RSI-based signal, auto TP/SL, sized by your risk %")
        order_price = last_price

    default_tp = round(last_price * 1.02, 2) if last_price > 0 else 0.0
    default_sl = round(last_price * 0.98, 2) if last_price > 0 else 0.0
    show_tpsl = st.checkbox("Take Profit / Stop Loss", value=True)
    if show_tpsl:
        col_tp, col_sl = st.columns(2)
        with col_tp:
            tp_price = st.number_input("TP Price ($)", value=default_tp, step=0.1)
        with col_sl:
            sl_price = st.number_input("SL Price ($)", value=default_sl, step=0.1)
    else:
        tp_price, sl_price = default_tp, default_sl

    calc_qty = calc_position_size(live_balance, risk_pct, order_price, sl_price) if live_balance else 0.0
    st.caption(f"Sized for {risk_pct}% risk → qty ≈ {calc_qty} {selected_pair.replace('USDT','')}")

    btn_l = st.button("BUY / LONG", key="btn_buy")
    btn_s = st.button("SELL / SHORT", key="btn_sell")

    def execute_trade(side):
        if not (api_key and api_secret):
            st.error("Add your Binance API key/secret in the sidebar first.")
            return
        qty = calc_qty if calc_qty > 0 else 0.001
        set_leverage(selected_pair, leverage_val)
        order_result = place_market_order(selected_pair, side, qty)
        if "error" in order_result or order_result.get("code"):
            st.error(f"Order failed: {order_result}")
            return
        close_side = "SELL" if side == "BUY" else "BUY"
        tpsl_result = place_tp_sl(selected_pair, close_side, qty, tp_price, sl_price)
        st.session_state.trade_log.append(
            f"{time.strftime('%H:%M:%S')} | {side} {qty} {selected_pair} @ ~${last_price:,.2f} | TP {tp_price} / SL {sl_price}")
        st.toast(f"✅ {side} order placed for {selected_pair}, qty {qty}")

    if btn_l:
        execute_trade("BUY")
    if btn_s:
        execute_trade("SELL")

    # --- Pro AI: signal-driven auto trade, runs on each app refresh/visit ---
    if mode == "Pro AI" and current_rsi is not None:
        existing_position = get_open_positions(selected_pair) if (api_key and api_secret) else None
        st.caption(f"Open position on {selected_pair}: {'Yes' if existing_position else 'None'}")
        auto_enabled = st.toggle("Enable auto-trade on RSI signal", value=False)
        st.markdown(
            "<div class='warn-box'>Pro AI here only checks the signal each time this page runs/refreshes — "
            "it is NOT a 24/7 background bot. For unattended trading you need a separate always-on worker script "
            "(ask me and I'll build one).</div>", unsafe_allow_html=True)
        if auto_enabled and not existing_position:
            if current_rsi < rsi_oversold:
                execute_trade("BUY")
            elif current_rsi > rsi_overbought:
                execute_trade("SELL")

# ============================================================
# BOTTOM: POSITIONS & LOGS
# ============================================================
st.divider()
st.subheader("📋 Account Positions & Trade Logs")
tab_pos, tab_logs = st.tabs(["Active Positions", "AI Strategy Logs"])

with tab_pos:
    pos = get_open_positions(selected_pair) if (api_key and api_secret) else None
    if pos:
        pos_df = pd.DataFrame([{
            "Symbol": pos["symbol"],
            "Side": "LONG" if float(pos["positionAmt"]) > 0 else "SHORT",
            "Size": pos["positionAmt"],
            "Entry Price": f"${float(pos['entryPrice']):,.2f}",
            "Mark Price": f"${float(pos['markPrice']):,.2f}",
            "Unrealized PNL": f"${float(pos['unRealizedProfit']):,.2f}",
        }])
        st.dataframe(pos_df, width='stretch', hide_index=True)
    else:
        st.info("No open position on this pair (or API keys not set).")

with tab_logs:
    log_text = "\n".join(st.session_state.trade_log[-20:]) if st.session_state.trade_log else "No trades yet this session."
    rsi_display = f"{current_rsi:.1f}" if current_rsi is not None else "N/A"
    st.code(f"Mode: {'TESTNET' if st.session_state.use_testnet else 'LIVE'}\nPair: {selected_pair}\nRSI(14): {rsi_display}\n\n{log_text}", language="text")

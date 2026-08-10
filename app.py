import streamlit as st
import streamlit.components.v1 as components

# Page Layout Configuration
st.set_page_config(
    page_title="PRO TRADING TERMINAL",
    layout="wide",
    initial_sidebar_state="collapsed"
)

# Hide Streamlit Default UI Elements (Header, Footer, Padding)
st.markdown("""
<style>
    /* Remove padding & Streamlit branding */
    #MainMenu {visibility: hidden;}
    footer {visibility: hidden;}
    header {visibility: hidden;}
    .block-container {
        padding-top: 0rem !important;
        padding-bottom: 0rem !important;
        padding-left: 0rem !important;
        padding-right: 0rem !important;
        max-width: 100% !important;
    }
    .stApp {
        background-color: #080a0f;
    }
</style>
""", unsafe_allow_html=True)

# FULL CUSTOM HTML/CSS/JS ULTRADARK TERMINAL ENGINE (Halaska Studio Design)
terminal_html = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <script src="https://s3.tradingview.com/tv.js"></script>
    <style>
        * {
            box-sizing: border-box;
            margin: 0;
            padding: 0;
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Oxygen, Ubuntu, Cantarell, sans-serif;
            -webkit-font-smoothing: antialiased;
        }

        body {
            background-color: #080a0d;
            color: #9097a6;
            overflow: hidden;
            height: 100vh;
        }

        /* TOP NAVBAR */
        .top-nav {
            height: 48px;
            background-color: #0d1117;
            border-bottom: 1px solid #1c212d;
            display: flex;
            align-items: center;
            justify-content: space-between;
            padding: 0 16px;
            font-size: 12px;
        }

        .nav-left, .nav-center, .nav-right {
            display: flex;
            align-items: center;
            gap: 20px;
        }

        .brand-logo {
            color: #f0b90b;
            font-weight: 800;
            font-size: 14px;
            letter-spacing: 0.5px;
            display: flex;
            align-items: center;
            gap: 6px;
        }

        .pair-select {
            background: #161b26;
            color: #ffffff;
            border: 1px solid #282f3f;
            padding: 4px 10px;
            border-radius: 4px;
            font-weight: 600;
            cursor: pointer;
            outline: none;
        }

        .stat-item {
            display: flex;
            flex-direction: column;
        }

        .stat-label {
            font-size: 10px;
            color: #5d6578;
            text-transform: uppercase;
        }

        .stat-value {
            font-size: 12px;
            font-weight: 600;
            color: #e1e4ea;
        }

        .val-green { color: #00c076; }
        .val-red { color: #ff4d4f; }

        .btn-deposit {
            background-color: #1e2538;
            color: #e1e4ea;
            border: 1px solid #2e374e;
            padding: 5px 12px;
            border-radius: 4px;
            font-weight: 600;
            cursor: pointer;
        }

        /* MAIN TERMINAL GRID */
        .grid-container {
            display: grid;
            grid-template-columns: 1fr 320px 280px;
            grid-template-rows: calc(100vh - 180px) 132px;
            gap: 2px;
            background-color: #121722;
            height: calc(100vh - 48px);
        }

        .panel {
            background-color: #0d1117;
            position: relative;
            overflow: hidden;
        }

        /* CHART PANEL */
        #chart-box {
            grid-column: 1 / 2;
            grid-row: 1 / 2;
        }

        /* ORDER BOOK / DEPTH PANEL */
        .depth-panel {
            grid-column: 2 / 3;
            grid-row: 1 / 2;
            border-left: 1px solid #161b26;
            display: flex;
            flex-direction: column;
            padding: 10px;
        }

        .panel-header {
            font-size: 11px;
            font-weight: 700;
            color: #60687b;
            text-transform: uppercase;
            margin-bottom: 8px;
            display: flex;
            justify-content: space-between;
        }

        .ob-row {
            display: flex;
            justify-content: space-between;
            font-size: 11px;
            padding: 3px 0;
            font-family: monospace;
        }

        .ob-ask { color: #ff4d4f; }
        .ob-bid { color: #00c076; }

        /* EXECUTION PANEL */
        .exec-panel {
            grid-column: 3 / 4;
            grid-row: 1 / 3;
            border-left: 1px solid #161b26;
            padding: 12px;
            display: flex;
            flex-direction: column;
            gap: 12px;
        }

        .trade-tabs {
            display: flex;
            background: #161b26;
            border-radius: 4px;
            padding: 2px;
        }

        .tab-btn {
            flex: 1;
            padding: 6px;
            text-align: center;
            font-size: 11px;
            font-weight: 600;
            border: none;
            background: transparent;
            color: #717b91;
            cursor: pointer;
            border-radius: 3px;
        }

        .tab-btn.active {
            background-color: #212838;
            color: #ffffff;
        }

        .input-group {
            display: flex;
            flex-direction: column;
            gap: 4px;
        }

        .input-label {
            font-size: 10px;
            color: #5d6578;
        }

        .field-input {
            background-color: #131824;
            border: 1px solid #202738;
            border-radius: 4px;
            color: #ffffff;
            padding: 8px;
            font-size: 12px;
            outline: none;
        }

        .btn-buy {
            background-color: #00c076;
            color: #ffffff;
            border: none;
            padding: 10px;
            border-radius: 4px;
            font-weight: 700;
            cursor: pointer;
            margin-top: 6px;
        }

        .btn-sell {
            background-color: #ff4d4f;
            color: #ffffff;
            border: none;
            padding: 10px;
            border-radius: 4px;
            font-weight: 700;
            cursor: pointer;
        }

        /* BOTTOM POSITIONS PANEL */
        .bottom-panel {
            grid-column: 1 / 3;
            grid-row: 2 / 3;
            border-top: 1px solid #161b26;
            padding: 10px;
        }

        .table-pos {
            width: 100%;
            border-collapse: collapse;
            font-size: 11px;
            text-align: left;
        }

        .table-pos th {
            color: #5d6578;
            font-weight: 500;
            padding-bottom: 6px;
        }

        .table-pos td {
            color: #c5c9d3;
            padding: 6px 0;
            border-top: 1px solid #131824;
        }
    </style>
</head>
<body>

    <!-- TOP NAV BAR -->
    <div class="top-nav">
        <div class="nav-left">
            <div class="brand-logo">⚡ INF-TERMINAL</div>
            <select class="pair-select" id="pairSelect" onchange="changeSymbol()">
                <option value="BTCUSDT">BTC/USDT</option>
                <option value="ETHUSDT">ETH/USDT</option>
                <option value="SOLUSDT">SOL/USDT</option>
            </select>
            <div class="stat-item">
                <span class="stat-label">Price</span>
                <span class="stat-value val-green" id="lastPrice">$64,108.01</span>
            </div>
            <div class="stat-item">
                <span class="stat-label">24h Change</span>
                <span class="stat-value val-red" id="priceChange">-1.22%</span>
            </div>
            <div class="stat-item">
                <span class="stat-label">24h High</span>
                <span class="stat-value">$65,400.00</span>
            </div>
            <div class="stat-item">
                <span class="stat-label">24h Low</span>
                <span class="stat-value">$63,800.00</span>
            </div>
        </div>
        <div class="nav-right">
            <div class="stat-item" style="text-align: right;">
                <span class="stat-label">Account Balance</span>
                <span class="stat-value" style="color: #00c076;">$27,594.00 USDT</span>
            </div>
            <button class="btn-deposit">Deposit</button>
        </div>
    </div>

    <!-- MAIN TERMINAL LAYOUT -->
    <div class="grid-container">
        <!-- CHART -->
        <div class="panel" id="chart-box">
            <div id="tv_chart_container" style="height: 100%; width: 100%;"></div>
        </div>

        <!-- DEPTH / ORDER BOOK -->
        <div class="panel depth-panel">
            <div class="panel-header">
                <span>Order Book</span>
                <span>Size (BTC)</span>
            </div>
            <div id="asks" style="margin-bottom: 8px;">
                <div class="ob-row ob-ask"><span>64,120.00</span><span>0.421</span></div>
                <div class="ob-row ob-ask"><span>64,115.50</span><span>1.105</span></div>
                <div class="ob-row ob-ask"><span>64,112.00</span><span>0.080</span></div>
                <div class="ob-row ob-ask"><span>64,110.00</span><span>2.450</span></div>
            </div>
            <div style="padding: 6px 0; font-weight: bold; color: #00c076; font-size: 13px; border-top: 1px solid #1a202c; border-bottom: 1px solid #1a202c; margin-bottom: 8px;">
                $64,108.01 <span style="font-size: 10px; color: #60687b; font-weight: normal;">↑ Market Price</span>
            </div>
            <div id="bids">
                <div class="ob-row ob-bid"><span>64,105.00</span><span>1.890</span></div>
                <div class="ob-row ob-bid"><span>64,102.50</span><span>0.320</span></div>
                <div class="ob-row ob-bid"><span>64,100.00</span><span>5.120</span></div>
                <div class="ob-row ob-bid"><span>64,095.00</span><span>0.750</span></div>
            </div>
        </div>

        <!-- EXECUTION PANEL -->
        <div class="panel exec-panel">
            <div class="trade-tabs">
                <button class="tab-btn active">Limit</button>
                <button class="tab-btn">Market</button>
                <button class="tab-btn">Pro AI</button>
            </div>

            <div class="input-group">
                <span class="input-label">Margin Mode / Leverage</span>
                <input type="text" class field-input value="Cross 20x" readonly style="cursor: pointer; text-align: center; color: #f0b90b;">
            </div>

            <div class="input-group">
                <span class="input-label">Order Price</span>
                <input type="text" class="field-input" value="64,108.01 USDT">
            </div>

            <div class="input-group">
                <span class="input-label">Amount</span>
                <input type="text" class="field-input" placeholder="0.00 BTC">
            </div>

            <div class="input-group">
                <span class="input-label">Take Profit / Stop Loss</span>
                <input type="text" class="field-input" placeholder="TP / SL Price">
            </div>

            <button class="btn-buy">BUY / LONG</button>
            <button class="btn-sell">SELL / SHORT</button>
        </div>

        <!-- POSITIONS & HISTORY -->
        <div class="panel bottom-panel">
            <div class="panel-header">
                <span>Active Positions (3)</span>
                <span style="color: #00c076;">Unrealized PnL: +$487.20</span>
            </div>
            <table class="table-pos">
                <thead>
                    <tr>
                        <th>Symbol</th>
                        <th>Type</th>
                        <th>Size</th>
                        <th>Entry Price</th>
                        <th>Mark Price</th>
                        <th>PNL (ROE%)</th>
                    </tr>
                </thead>
                <tbody>
                    <tr>
                        <td style="color: #ffffff; font-weight: bold;">BTCUSDT</td>
                        <td style="color: #00c076;">LONG 20x</td>
                        <td>0.50 BTC</td>
                        <td>$63,950.00</td>
                        <td>$64,108.01</td>
                        <td style="color: #00c076;">+$790.05 (+24.5%)</td>
                    </tr>
                    <tr>
                        <td style="color: #ffffff; font-weight: bold;">ETHUSDT</td>
                        <td style="color: #ff4d4f;">SHORT 10x</td>
                        <td>4.00 ETH</td>
                        <td>$3,480.00</td>
                        <td>$3,450.20</td>
                        <td style="color: #00c076;">+$119.20 (+8.2%)</td>
                    </tr>
                </tbody>
            </table>
        </div>
    </div>

    <!-- TRADINGVIEW EMBED SCRIPT -->
    <script>
        let widget;
        function loadChart(symbol) {
            document.getElementById('tv_chart_container').innerHTML = '';
            widget = new TradingView.widget({
                "autosize": true,
                "symbol": "BINANCE:" + symbol,
                "interval": "15",
                "timezone": "Etc/UTC",
                "theme": "dark",
                "style": "1",
                "locale": "en",
                "enable_publishing": false,
                "hide_side_toolbar": false,
                "allow_symbol_change": false,
                "container_id": "tv_chart_container",
                "backgroundColor": "#0d1117",
                "gridColor": "#161b26"
            });
        }

        function changeSymbol() {
            const sym = document.getElementById('pairSelect').value;
            loadChart(sym);
        }

        // Initialize Chart
        loadChart("BTCUSDT");
    </script>
</body>
</html>
"""

# Render Fullscreen Component
components.html(terminal_html, height=950, scrolling=False)

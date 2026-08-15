"""
app.py

PRO AI QUANT TERMINAL
Multi-market autonomous PAPER trading dashboard.

Architecture:
- Streamlit fragment runs one cycle every POLL_SECONDS
- PostgreSQL-backed PaperTrader
- Coinbase public market data
- Multi-market scanner
- Strongest confirmed setup selection
- Automatic simulated TP / SL
- One open position at a time

IMPORTANT:
REAL ORDERS ARE DISABLED.
"""

import os
import textwrap
from datetime import datetime, timezone

import pandas as pd
import streamlit as st
import streamlit.components.v1 as components

from market_data import get_ticker, get_candles
from signal_engine import generate_signal
from risk_manager import calculate_trade_plan, validate_trade_plan
from paper_trader import PaperTrader


# ============================================================
# PAGE CONFIG
# ============================================================

st.set_page_config(
    page_title="PRO AI QUANT TERMINAL",
    page_icon="⚡",
    layout="wide",
    initial_sidebar_state="collapsed",
)


# ============================================================
# HTML HELPER
# ============================================================

def html(content):
    st.html(
        textwrap.dedent(content).strip()
    )


# ============================================================
# CONFIG
# ============================================================

PAPER_TRADING = (
    os.environ.get("PAPER_TRADING", "true").lower() == "true"
)

PAPER_BALANCE = float(
    os.environ.get("PAPER_BALANCE", "10000")
)

RISK_PCT = float(
    os.environ.get("RISK_PCT", "1")
)

SL_PCT = float(
    os.environ.get("SL_PCT", "1")
)

TP_PCT = float(
    os.environ.get("TP_PCT", "2")
)

POLL_SECONDS = int(
    os.environ.get("POLL_SECONDS", "60")
)

MAX_DAILY_LOSS_PCT = float(
    os.environ.get("MAX_DAILY_LOSS_PCT", "5")
)

TIMEFRAME_MINUTES = int(
    os.environ.get("TIMEFRAME_MINUTES", "15")
)

CANDLE_LIMIT = int(
    os.environ.get("CANDLE_LIMIT", "100")
)


# ============================================================
# SCAN MARKETS
# ============================================================

SCAN_MARKETS = [
    "BTCUSDT",
    "ETHUSDT",
    "SOLUSDT",
    "XRPUSDT",
    "ADAUSDT",
    "DOGEUSDT",
    "AVAXUSDT",
    "LINKUSDT",
    "DOTUSDT",
    "NEARUSDT",
    "SUIUSDT",
]


# ============================================================
# SESSION STATE
# ============================================================

if "selected_pair" not in st.session_state:
    st.session_state.selected_pair = "BTCUSDT"

if "display_exchange" not in st.session_state:
    st.session_state.display_exchange = "Coinbase"

if "paper_trader" not in st.session_state:
    st.session_state.paper_trader = PaperTrader(
        starting_balance=PAPER_BALANCE
    )

if "bot_status" not in st.session_state:
    st.session_state.bot_status = "STARTING"

if "bot_signal" not in st.session_state:
    st.session_state.bot_signal = "NO TRADE"

if "bot_score" not in st.session_state:
    st.session_state.bot_score = 0

if "bot_reason" not in st.session_state:
    st.session_state.bot_reason = ""

if "bot_rsi" not in st.session_state:
    st.session_state.bot_rsi = None

if "bot_macd" not in st.session_state:
    st.session_state.bot_macd = None

if "bot_price" not in st.session_state:
    st.session_state.bot_price = None

if "bot_market" not in st.session_state:
    st.session_state.bot_market = "—"

if "bot_position" not in st.session_state:
    st.session_state.bot_position = None

if "scanner_results" not in st.session_state:
    st.session_state.scanner_results = []

if "last_trade" not in st.session_state:
    st.session_state.last_trade = None

if "trade_count" not in st.session_state:
    st.session_state.trade_count = 0

if "realized_pnl" not in st.session_state:
    st.session_state.realized_pnl = 0.0

if "drawdown" not in st.session_state:
    st.session_state.drawdown = 0.0

if "last_update" not in st.session_state:
    st.session_state.last_update = None

if "bot_error" not in st.session_state:
    st.session_state.bot_error = None

if "day_start_date" not in st.session_state:
    st.session_state.day_start_date = None

if "day_start_balance" not in st.session_state:
    st.session_state.day_start_balance = PAPER_BALANCE

if "trading_paused" not in st.session_state:
    st.session_state.trading_paused = False


# ============================================================
# STYLE
# ============================================================

html(
    """
    <style>

    #MainMenu,
    footer,
    header {
        visibility: hidden;
    }

    .block-container {
        padding-top: 0.25rem !important;
        padding-bottom: 1rem !important;
        padding-left: 0.55rem !important;
        padding-right: 0.55rem !important;
        max-width: 100% !important;
    }

    .stApp {
        background:
            radial-gradient(
                circle at 50% 0%,
                #151b24 0%,
                #090d12 42%,
                #05070a 100%
            );
        color: #dce5ef;
    }

    div[data-testid="stMetric"] {
        background: #0a0f15;
        border: 1px solid #26303a;
        border-radius: 4px;
        padding: 8px 10px;
    }

    div[data-testid="stMetric"] label {
        color: #667588 !important;
        font-size: 9px !important;
        text-transform: uppercase;
        letter-spacing: 0.7px;
    }

    div[data-testid="stMetricValue"] {
        font-family: monospace;
        font-size: 20px !important;
    }

    div[data-baseweb="select"] > div {
        background: #0a0f15 !important;
        border-color: #26303a !important;
        color: white !important;
    }

    .quant-header {
        border: 1px solid #28313b;
        background:
            linear-gradient(
                90deg,
                #0a0f14,
                #111822,
                #090d12
            );
        min-height: 52px;
        display: flex;
        align-items: center;
        padding: 0 13px;
        margin-bottom: 5px;
    }

    .logo-box {
        width: 27px;
        height: 27px;
        background: #f2d332;
        margin-right: 10px;
        box-shadow:
            0 0 15px rgba(242,211,50,.3);
    }

    .terminal-title {
        color: #f0f3f7;
        font-family: monospace;
        font-size: 14px;
        font-weight: 800;
        letter-spacing: .4px;
    }

    .terminal-subtitle {
        color: #697688;
        font-family: monospace;
        font-size: 8px;
        letter-spacing: 1px;
    }

    .live-text {
        color: #00d99a;
        font-family: monospace;
        font-size: 10px;
    }

    .terminal-strip {
        background: #080c11;
        border-top: 1px solid #1d2630;
        border-bottom: 1px solid #1d2630;
        padding: 6px 9px;
        margin-bottom: 6px;
        font-family: monospace;
        font-size: 9px;
        color: #687587;
    }

    .panel-title {
        color: #738194;
        font-family: monospace;
        font-size: 9px;
        letter-spacing: 1px;
        text-transform: uppercase;
        padding-bottom: 5px;
    }

    .panel {
        background: #090d12;
        border: 1px solid #252f3a;
        border-radius: 3px;
        padding: 11px;
    }

    .small-muted {
        color: #647183;
        font-family: monospace;
        font-size: 9px;
        letter-spacing: .4px;
    }

    .paper-equity {
        color: #2be3c1;
        font-family: monospace;
        font-size: 30px;
        padding: 7px 0 12px 0;
    }

    .green {
        color: #00da98;
    }

    .red {
        color: #ff5077;
    }

    .yellow {
        color: #f1d239;
    }

    .cyan {
        color: #28dfcf;
    }

    .purple {
        color: #aa82ff;
    }

    .execution-panel {
        border-left: 2px solid #f1d239;
    }

    .signal-large {
        font-family: monospace;
        font-size: 25px;
        font-weight: 800;
    }

    .score-large {
        color: #f2d43b;
        font-family: monospace;
        font-size: 43px;
        font-weight: 300;
    }

    .tag {
        display: inline-block;
        padding: 4px 7px;
        border: 1px solid #303b47;
        background: #0d131a;
        font-family: monospace;
        font-size: 9px;
        margin-right: 4px;
    }

    .indicator-grid {
        display: grid;
        grid-template-columns: repeat(6, 1fr);
        gap: 5px;
        margin-top: 6px;
        margin-bottom: 7px;
    }

    .indicator-card {
        background: #090e14;
        border: 1px solid #27313d;
        min-height: 70px;
        padding: 8px;
    }

    .indicator-name {
        color: #697688;
        font-family: monospace;
        font-size: 8px;
        letter-spacing: .7px;
    }

    .indicator-value {
        font-family: monospace;
        font-size: 14px;
        margin-top: 8px;
    }

    .safe-notice {
        border: 1px solid #00da98;
        background: #07150f;
        color: #00da98;
        padding: 7px;
        font-family: monospace;
        font-size: 9px;
    }

    </style>
    """
)


# ============================================================
# MARKET ANALYSIS
# ============================================================

def analyse_market(symbol):

    candles = get_candles(
        exchange="PUBLIC",
        symbol=symbol,
        timeframe_minutes=TIMEFRAME_MINUTES,
        limit=CANDLE_LIMIT,
        api_key="",
        api_secret="",
        use_testnet=False,
    )

    if candles is None or len(candles) < 50:
        return None

    current_price = float(
        candles["close"].iloc[-1]
    )

    signal_data = generate_signal(
        candles
    )

    return {
        "symbol": symbol,
        "price": current_price,
        "signal": signal_data.get(
            "signal",
            "NO TRADE",
        ),
        "score": float(
            signal_data.get(
                "score",
                0,
            )
        ),
        "rsi": signal_data.get(
            "rsi",
            None,
        ),
        "macd": signal_data.get(
            "macd",
            None,
        ),
        "reason": signal_data.get(
            "reason",
            "",
        ),
    }


def scan_markets():

    results = []

    for symbol in SCAN_MARKETS:

        try:

            result = analyse_market(
                symbol
            )

            if result:
                results.append(
                    result
                )

        except Exception as error:

            print(
                f"[SCAN ERROR] "
                f"{symbol}: {error}",
                flush=True,
            )

    return results


def select_best_setup(results):

    confirmed = []

    for item in results:

        if item["signal"] not in (
            "BUY",
            "SELL",
        ):
            continue

        item["absolute_score"] = abs(
            float(
                item["score"]
            )
        )

        confirmed.append(
            item
        )

    if not confirmed:
        return None

    confirmed.sort(
        key=lambda item: (
            item[
                "absolute_score"
            ]
        ),
        reverse=True,
    )

    return confirmed[0]


# ============================================================
# PAPER CYCLE
# ============================================================

def run_paper_cycle():

    now_utc = datetime.now(
        timezone.utc
    )

    trader = st.session_state.paper_trader

    try:

        balance = trader.get_balance()

        today = now_utc.date()

        if st.session_state.day_start_date != today:

            st.session_state.day_start_date = today
            st.session_state.day_start_balance = balance
            st.session_state.trading_paused = False

        day_start_balance = (
            st.session_state.day_start_balance
        )

        drawdown_pct = 0.0

        if day_start_balance > 0:

            drawdown_pct = (
                (
                    day_start_balance
                    - balance
                )
                / day_start_balance
                * 100
            )

        st.session_state.drawdown = (
            drawdown_pct
        )

        if (
            drawdown_pct
            >= MAX_DAILY_LOSS_PCT
        ):
            st.session_state.trading_paused = True

        # ====================================================
        # EXISTING POSITION HAS FIRST PRIORITY
        # ====================================================

        existing_position = (
            trader.get_position()
        )

        if existing_position:

            position_symbol = (
                existing_position[
                    "symbol"
                ]
            )

            st.session_state.bot_market = (
                position_symbol
            )

            candles = get_candles(
                exchange="PUBLIC",
                symbol=position_symbol,
                timeframe_minutes=TIMEFRAME_MINUTES,
                limit=CANDLE_LIMIT,
                api_key="",
                api_secret="",
                use_testnet=False,
            )

            if candles is None:

                st.session_state.bot_status = (
                    "WAITING FOR POSITION DATA"
                )

                st.session_state.last_update = (
                    now_utc.isoformat()
                )

                return

            current_price = float(
                candles["close"].iloc[-1]
            )

            result = trader.update_price(
                current_price
            )

            current_position = (
                trader.get_position()
            )

            st.session_state.bot_position = (
                current_position
            )

            st.session_state.bot_price = (
                current_price
            )

            if (
                result
                and result.get(
                    "status"
                )
                == "CLOSED"
            ):

                st.session_state.bot_status = (
                    "TRADE CLOSED"
                )

                st.session_state.last_trade = (
                    result
                )

                st.session_state.trade_count += 1

                st.session_state.realized_pnl += float(
                    result.get(
                        "pnl",
                        0,
                    )
                )

                st.session_state.bot_position = None

            else:

                st.session_state.bot_status = (
                    "POSITION OPEN"
                )

            st.session_state.last_update = (
                now_utc.isoformat()
            )

            st.session_state.bot_error = None

            return

        # ====================================================
        # DAILY LOSS BLOCK
        # ====================================================

        if st.session_state.trading_paused:

            st.session_state.bot_status = (
                "DAILY LOSS LIMIT HIT"
            )

            st.session_state.last_update = (
                now_utc.isoformat()
            )

            return

        # ====================================================
        # MULTI-MARKET SCAN
        # ====================================================

        st.session_state.bot_status = (
            f"SCANNING {len(SCAN_MARKETS)} MARKETS"
        )

        results = scan_markets()

        st.session_state.scanner_results = (
            results
        )

        if not results:

            st.session_state.bot_status = (
                "NO MARKET DATA"
            )

            st.session_state.last_update = (
                now_utc.isoformat()
            )

            return

        best_setup = select_best_setup(
            results
        )

        # Use strongest absolute score for dashboard
        strongest_visible = sorted(
            results,
            key=lambda x: abs(
                float(
                    x["score"]
                )
            ),
            reverse=True,
        )[0]

        st.session_state.bot_market = (
            strongest_visible[
                "symbol"
            ]
        )

        st.session_state.bot_signal = (
            strongest_visible[
                "signal"
            ]
        )

        st.session_state.bot_score = (
            strongest_visible[
                "score"
            ]
        )

        st.session_state.bot_reason = (
            strongest_visible[
                "reason"
            ]
        )

        st.session_state.bot_rsi = (
            strongest_visible[
                "rsi"
            ]
        )

        st.session_state.bot_macd = (
            strongest_visible[
                "macd"
            ]
        )

        st.session_state.bot_price = (
            strongest_visible[
                "price"
            ]
        )

        if best_setup is None:

            st.session_state.bot_status = (
                "NO QUALIFYING TRADE"
            )

            st.session_state.last_update = (
                now_utc.isoformat()
            )

            st.session_state.bot_error = None

            return

        # ====================================================
        # OPEN STRONGEST CONFIRMED SETUP
        # ====================================================

        signal = best_setup[
            "signal"
        ]

        symbol = best_setup[
            "symbol"
        ]

        entry_price = float(
            best_setup[
                "price"
            ]
        )

        plan = calculate_trade_plan(
            balance=trader.get_balance(),
            entry_price=entry_price,
            signal=signal,
            risk_percent=RISK_PCT,
            stop_loss_percent=SL_PCT,
            take_profit_percent=TP_PCT,
        )

        if not validate_trade_plan(
            plan
        ):

            st.session_state.bot_status = (
                "TRADE REJECTED"
            )

            st.session_state.last_update = (
                now_utc.isoformat()
            )

            return

        result = trader.open_trade(
            symbol=symbol,
            signal=signal,
            entry_price=entry_price,
            quantity=plan[
                "quantity"
            ],
            take_profit=plan[
                "take_profit"
            ],
            stop_loss=plan[
                "stop_loss"
            ],
        )

        st.session_state.bot_market = symbol
        st.session_state.bot_signal = signal
        st.session_state.bot_score = (
            best_setup[
                "score"
            ]
        )
        st.session_state.bot_reason = (
            best_setup[
                "reason"
            ]
        )
        st.session_state.bot_rsi = (
            best_setup[
                "rsi"
            ]
        )
        st.session_state.bot_macd = (
            best_setup[
                "macd"
            ]
        )
        st.session_state.bot_price = (
            entry_price
        )

        if (
            result.get(
                "status"
            )
            == "EXECUTED"
        ):

            st.session_state.bot_status = (
                "PAPER TRADE OPENED"
            )

            st.session_state.bot_position = (
                trader.get_position()
            )

        else:

            st.session_state.bot_status = (
                "TRADE SKIPPED"
            )

        st.session_state.last_update = (
            now_utc.isoformat()
        )

        st.session_state.bot_error = None

    except Exception as error:

        st.session_state.bot_status = (
            "ERROR"
        )

        st.session_state.bot_error = (
            str(error)
        )

        st.session_state.last_update = (
            now_utc.isoformat()
        )


# ============================================================
# UI
# ============================================================

def render_terminal():

    trader = st.session_state.paper_trader

    balance = trader.get_balance()

    position = trader.get_position()

    st.session_state.bot_position = (
        position
    )

    utc_now = datetime.now(
        timezone.utc
    ).strftime(
        "%H:%M:%S UTC"
    )

    signal = st.session_state.bot_signal

    score = int(
        st.session_state.bot_score
        or 0
    )

    reason_text = (
        st.session_state.bot_reason
    )

    rsi_value = (
        st.session_state.bot_rsi
    )

    macd_value = (
        st.session_state.bot_macd
    )

    bot_market = (
        st.session_state.bot_market
    )

    html(
        f"""
        <div class="quant-header">

            <div class="logo-box"></div>

            <div style="flex:1">

                <div class="terminal-title">
                    PRO AI • QUANT MARKET TERMINAL
                </div>

                <div class="terminal-subtitle">
                    MULTI-MARKET PAPER EXECUTION /
                    SIGNAL INTELLIGENCE /
                    RISK ENGINE
                </div>

            </div>

            <div class="live-text">
                ● ONLINE &nbsp;&nbsp; {utc_now}
            </div>

        </div>
        """
    )

    html(
        f"""
        <div class="terminal-strip">
            MARKET FEED: COINBASE PUBLIC DATA
            &nbsp; | &nbsp;
            SCANNER: {len(SCAN_MARKETS)} MARKETS
            &nbsp; | &nbsp;
            BOT MARKET: {bot_market}
            &nbsp; | &nbsp;
            MODE: PAPER
            &nbsp; | &nbsp;
            SCAN: {POLL_SECONDS}s
        </div>
        """
    )

    # ========================================================
    # CHART CONTROLS
    # ========================================================

    c1, c2, c3 = st.columns(
        [
            1.3,
            1.3,
            4,
        ]
    )

    with c1:

        selected_pair = st.selectbox(
            "Chart Market",
            SCAN_MARKETS,
            index=(
                SCAN_MARKETS.index(
                    st.session_state.selected_pair
                )
                if st.session_state.selected_pair
                in SCAN_MARKETS
                else 0
            ),
        )

        st.session_state.selected_pair = (
            selected_pair
        )

    with c2:

        display_exchange = st.selectbox(
            "Chart Feed",
            [
                "Coinbase",
                "Bybit",
                "Binance",
            ],
            index=0,
        )

        st.session_state.display_exchange = (
            display_exchange
        )

    with c3:

        html(
            """
            <div style="height:27px"></div>

            <span class="tag green">
                ● PAPER ACTIVE
            </span>

            <span class="tag cyan">
                MULTI-MARKET SCANNER
            </span>

            <span class="tag yellow">
                AUTO TP / SL
            </span>

            <span class="tag purple">
                POSTGRES STATE
            </span>
            """
        )

    # ========================================================
    # SELECTED TICKER
    # ========================================================

    ticker = get_ticker(
        symbol=selected_pair,
        exchange="PUBLIC",
        api_key="",
        api_secret="",
        use_testnet=False,
    )

    market_price = 0.0
    change_pct = 0.0
    high_price = 0.0
    low_price = 0.0

    if ticker:

        market_price = float(
            ticker.get(
                "last",
                0,
            )
        )

        change_pct = float(
            ticker.get(
                "change_pct",
                0,
            )
        )

        high_price = float(
            ticker.get(
                "high",
                0,
            )
        )

        low_price = float(
            ticker.get(
                "low",
                0,
            )
        )

    # ========================================================
    # MAIN PANELS
    # ========================================================

    account_col, chart_col, execution_col = (
        st.columns(
            [
                1.05,
                2.8,
                1.25,
            ]
        )
    )

    with account_col:

        html(
            f"""
            <div class="panel">

                <div class="small-muted">
                    PAPER EQUITY
                </div>

                <div class="paper-equity">
                    ${balance:,.2f}
                </div>

                <div class="small-muted">
                    REALIZED P&L
                </div>

                <div class="green"
                     style="
                     font-family:monospace;
                     font-size:19px;
                     padding:6px 0 13px 0;">
                    ${st.session_state.realized_pnl:,.2f}
                </div>

                <div class="small-muted">
                    COMPLETED TRADES
                </div>

                <div style="
                     font-family:monospace;
                     font-size:18px;
                     padding:6px 0 13px 0;">
                    {st.session_state.trade_count}
                </div>

                <div class="small-muted">
                    DAILY DRAWDOWN
                </div>

                <div class="yellow"
                     style="
                     font-family:monospace;
                     font-size:17px;
                     padding:6px 0 13px 0;">
                    {st.session_state.drawdown:.2f}%
                </div>

                <div class="safe-notice">
                    ONE POSITION MAX<br>
                    REAL ORDERS DISABLED
                </div>

            </div>
            """
        )

    with chart_col:

        price_css = (
            "green"
            if change_pct >= 0
            else "red"
        )

        html(
            f"""
            <div class="terminal-strip">

                {selected_pair}

                &nbsp;&nbsp;

                <span class="{price_css}">
                    ${market_price:,.2f}
                </span>

                &nbsp;&nbsp;

                <span class="{price_css}">
                    {change_pct:+.2f}%
                </span>

                &nbsp;&nbsp;

                HIGH ${high_price:,.2f}

                &nbsp;&nbsp;

                LOW ${low_price:,.2f}

            </div>
            """
        )

        if display_exchange == "Bybit":

            tv_symbol = (
                f"BYBIT:{selected_pair}"
            )

        elif display_exchange == "Binance":

            tv_symbol = (
                f"BINANCE:{selected_pair}"
            )

        else:

            base = selected_pair.replace(
                "USDT",
                "",
            )

            tv_symbol = (
                f"COINBASE:{base}USD"
            )

        tv_widget = f"""
        <div style="
            height:435px;
            width:100%;
            border:1px solid #252f3a;
            background:#070a0e;
        ">

            <div
                id="tv_chart"
                style="
                height:435px;
                width:100%;
                "
            ></div>

            <script
                src="https://s3.tradingview.com/tv.js">
            </script>

            <script>

            new TradingView.widget({{
                "autosize": true,
                "symbol": "{tv_symbol}",
                "interval": "15",
                "timezone": "Etc/UTC",
                "theme": "dark",
                "style": "1",
                "locale": "en",
                "enable_publishing": false,
                "hide_side_toolbar": false,
                "allow_symbol_change": true,
                "container_id": "tv_chart",
                "backgroundColor": "#070a0e",
                "gridColor": "#151c23"
            }});

            </script>

        </div>
        """

        components.html(
            tv_widget,
            height=440,
        )

    with execution_col:

        signal_css = (
            "green"
            if signal == "BUY"
            else (
                "red"
                if signal == "SELL"
                else "yellow"
            )
        )

        html(
            f"""
            <div class="panel execution-panel">

                <div class="small-muted">
                    BOT MARKET
                </div>

                <div
                    class="purple"
                    style="
                    font-family:monospace;
                    font-size:16px;">
                    {bot_market}
                </div>

                <br>

                <div class="small-muted">
                    LIVE SIGNAL
                </div>

                <div class="signal-large {signal_css}">
                    {signal}
                </div>

                <br>

                <div class="small-muted">
                    AI SCORE
                </div>

                <div class="score-large">
                    {score:+d}
                </div>

                <div class="small-muted">
                    STATUS
                </div>

                <div style="
                    font-family:monospace;
                    font-size:11px;
                    padding:6px 0 13px 0;">
                    {st.session_state.bot_status}
                </div>

                <div class="small-muted">
                    RISK
                </div>

                <div class="cyan">
                    {RISK_PCT:.1f}%
                </div>

                <br>

                <div class="small-muted">
                    TP / SL
                </div>

                <div class="green">
                    +{TP_PCT:.1f}%
                </div>

                <div class="red">
                    -{SL_PCT:.1f}%
                </div>

            </div>
            """
        )

    # ========================================================
    # SCANNER TABLE
    # ========================================================

    st.subheader(
        "🔎 Multi-Market AI Scanner"
    )

    scanner_results = (
        st.session_state.scanner_results
    )

    if scanner_results:

        scanner_df = pd.DataFrame(
            [
                {
                    "Symbol": item[
                        "symbol"
                    ],
                    "Price": round(
                        float(
                            item[
                                "price"
                            ]
                        ),
                        6,
                    ),
                    "Signal": item[
                        "signal"
                    ],
                    "Score": item[
                        "score"
                    ],
                    "RSI": (
                        round(
                            float(
                                item[
                                    "rsi"
                                ]
                            ),
                            2,
                        )
                        if item[
                            "rsi"
                        ]
                        is not None
                        else None
                    ),
                    "MACD": (
                        round(
                            float(
                                item[
                                    "macd"
                                ]
                            ),
                            4,
                        )
                        if item[
                            "macd"
                        ]
                        is not None
                        else None
                    ),
                    "Reason": item[
                        "reason"
                    ],
                }
                for item
                in scanner_results
            ]
        )

        scanner_df = scanner_df.sort_values(
            by="Score",
            key=lambda series: (
                series.abs()
            ),
            ascending=False,
        )

        st.dataframe(
            scanner_df,
            width="stretch",
            hide_index=True,
        )

    else:

        if position:

            st.info(
                "Scanner paused while an existing paper "
                "position is being managed."
            )

        else:

            st.info(
                "Waiting for the first multi-market scan."
            )

    # ========================================================
    # ACTIVE POSITION
    # ========================================================

    if position:

        st.subheader(
            "📌 ACTIVE PAPER POSITION"
        )

        position_df = pd.DataFrame(
            [
                {
                    "Mode": "PAPER",
                    "Symbol": position.get(
                        "symbol"
                    ),
                    "Side": position.get(
                        "side"
                    ),
                    "Quantity": position.get(
                        "quantity"
                    ),
                    "Entry": position.get(
                        "entry_price"
                    ),
                    "Take Profit": position.get(
                        "take_profit"
                    ),
                    "Stop Loss": position.get(
                        "stop_loss"
                    ),
                    "Opened": position.get(
                        "opened_at"
                    ),
                }
            ]
        )

        st.dataframe(
            position_df,
            width="stretch",
            hide_index=True,
        )

    # ========================================================
    # ANALYSIS
    # ========================================================

    st.subheader(
        "🧠 Current AI Analysis"
    )

    st.code(
        f"""
Bot Market: {bot_market}
Status: {st.session_state.bot_status}
Signal: {signal}
Score: {score}
RSI: {rsi_value}
MACD: {macd_value}

Reason:
{reason_text or "Waiting for analysis"}

Last Update:
{st.session_state.last_update or "Starting"}
""",
        language="text",
    )

    # ========================================================
    # LAST CLOSED TRADE
    # ========================================================

    if st.session_state.last_trade:

        with st.expander(
            "LAST CLOSED PAPER TRADE"
        ):

            st.json(
                st.session_state.last_trade
            )

    if st.session_state.bot_error:

        st.error(
            st.session_state.bot_error
        )

    html(
        """
        <div
            class="terminal-strip"
            style="margin-top:8px;">

            PRO AI QUANT TERMINAL
            &nbsp; • &nbsp;
            MULTI-MARKET PAPER SCANNER
            &nbsp; • &nbsp;
            POSTGRESQL STATE
            &nbsp; • &nbsp;
            REAL EXECUTION DISABLED

        </div>
        """
    )


# ============================================================
# AUTO CYCLE
# ============================================================

@st.fragment(
    run_every=f"{POLL_SECONDS}s"
)
def autonomous_terminal():

    if PAPER_TRADING:

        run_paper_cycle()

    render_terminal()


autonomous_terminal()

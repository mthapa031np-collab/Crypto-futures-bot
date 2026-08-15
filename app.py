"""
app.py

PRO AI QUANT TERMINAL V2

Final modular paper-trading dashboard.

Architecture:
- settings.py
- scanner.py
- strategy_engine.py
- trade_engine.py
- risk_manager.py
- paper_trader.py
- market_data.py

Features:
- Multi-market scanning
- Multi-timeframe confirmation
- PostgreSQL state persistence
- Automatic paper TP / SL
- Manual paper close
- Pause / resume
- Force scan
- Trade history
- Risk dashboard

IMPORTANT:
REAL ORDERS ARE DISABLED.
"""

import textwrap
from datetime import datetime, timezone

import pandas as pd
import streamlit as st
import streamlit.components.v1 as components

from settings import (
    PAPER_TRADING,
    PAPER_BALANCE,
    RISK_PCT,
    TP_PCT,
    SL_PCT,
    POLL_SECONDS,
    MAX_DAILY_LOSS_PCT,
    SCAN_MARKETS,
    TEST_MODE,
)

from scanner import (
    scan_markets,
    scanner_summary,
    rank_markets,
)

from strategy_engine import (
    confirm_scanner_setup,
)

from trade_engine import (
    monitor_open_position,
    open_approved_trade,
    manual_close_position,
    trade_management_snapshot,
)

from paper_trader import PaperTrader
from market_data import get_ticker


# ============================================================
# PAGE CONFIG
# ============================================================

st.set_page_config(
    page_title="PRO AI QUANT TERMINAL V2",
    page_icon="⚡",
    layout="wide",
    initial_sidebar_state="collapsed",
)


# ============================================================
# HTML HELPER
# ============================================================

def html(content):

    st.html(
        textwrap.dedent(
            content
        ).strip()
    )


# ============================================================
# SESSION STATE
# ============================================================

if "paper_trader" not in st.session_state:

    st.session_state.paper_trader = PaperTrader(
        starting_balance=PAPER_BALANCE
    )


if "bot_paused" not in st.session_state:

    st.session_state.bot_paused = False


if "force_scan" not in st.session_state:

    st.session_state.force_scan = False


if "scanner_results" not in st.session_state:

    st.session_state.scanner_results = []


if "strategy_result" not in st.session_state:

    st.session_state.strategy_result = None


if "bot_status" not in st.session_state:

    st.session_state.bot_status = "STARTING"


if "bot_market" not in st.session_state:

    st.session_state.bot_market = "—"


if "bot_signal" not in st.session_state:

    st.session_state.bot_signal = "NO TRADE"


if "bot_score" not in st.session_state:

    st.session_state.bot_score = 0


if "bot_confidence" not in st.session_state:

    st.session_state.bot_confidence = 0.0


if "bot_reason" not in st.session_state:

    st.session_state.bot_reason = ""


if "last_update" not in st.session_state:

    st.session_state.last_update = None


if "bot_error" not in st.session_state:

    st.session_state.bot_error = None


if "selected_pair" not in st.session_state:

    st.session_state.selected_pair = "BTCUSDT"


if "display_exchange" not in st.session_state:

    st.session_state.display_exchange = "Coinbase"


if "day_start_date" not in st.session_state:

    st.session_state.day_start_date = None


if "day_start_balance" not in st.session_state:

    st.session_state.day_start_balance = PAPER_BALANCE


if "trading_paused_by_risk" not in st.session_state:

    st.session_state.trading_paused_by_risk = False


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
        padding-top: 0.3rem !important;
        padding-bottom: 1rem !important;
        padding-left: 0.7rem !important;
        padding-right: 0.7rem !important;
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
        border-radius: 5px;
        padding: 8px 10px;
    }

    div[data-testid="stMetric"] label {
        color: #667588 !important;
        font-size: 9px !important;
        text-transform: uppercase;
        letter-spacing: .7px;
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
        min-height: 58px;
        display: flex;
        align-items: center;
        padding: 0 14px;
        margin-bottom: 5px;
    }

    .logo-box {
        width: 30px;
        height: 30px;
        background: #f2d332;
        margin-right: 11px;
        box-shadow:
            0 0 18px rgba(242,211,50,.35);
    }

    .terminal-title {
        color: #f0f3f7;
        font-family: monospace;
        font-size: 15px;
        font-weight: 800;
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
        padding: 7px 9px;
        margin-bottom: 7px;
        font-family: monospace;
        font-size: 9px;
        color: #687587;
    }

    .panel {
        background: #090d12;
        border: 1px solid #252f3a;
        border-radius: 5px;
        padding: 11px;
    }

    .small-muted {
        color: #647183;
        font-family: monospace;
        font-size: 9px;
        letter-spacing: .4px;
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

    .tag {
        display: inline-block;
        padding: 4px 7px;
        border: 1px solid #303b47;
        background: #0d131a;
        font-family: monospace;
        font-size: 9px;
        margin-right: 4px;
        margin-bottom: 4px;
    }

    .signal-large {
        font-family: monospace;
        font-size: 25px;
        font-weight: 800;
    }

    .score-large {
        font-family: monospace;
        font-size: 38px;
        color: #f1d239;
    }

    </style>
    """
)


# ============================================================
# DAILY RISK CHECK
# ============================================================

def update_daily_risk():

    trader = st.session_state.paper_trader

    balance = trader.get_balance()

    today = datetime.now(
        timezone.utc
    ).date()

    if (
        st.session_state.day_start_date
        != today
    ):

        st.session_state.day_start_date = (
            today
        )

        st.session_state.day_start_balance = (
            balance
        )

        st.session_state.trading_paused_by_risk = (
            False
        )

    start_balance = (
        st.session_state.day_start_balance
    )

    drawdown_pct = 0.0

    if start_balance > 0:

        drawdown_pct = (
            (
                start_balance
                - balance
            )
            / start_balance
            * 100
        )

    if (
        drawdown_pct
        >= MAX_DAILY_LOSS_PCT
    ):

        st.session_state.trading_paused_by_risk = (
            True
        )

    return drawdown_pct


# ============================================================
# ONE BOT CYCLE
# ============================================================

def run_bot_cycle():

    trader = (
        st.session_state.paper_trader
    )

    now = datetime.now(
        timezone.utc
    )

    try:

        st.session_state.bot_error = None

        drawdown = update_daily_risk()

        # ----------------------------------------------------
        # EXISTING POSITION FIRST
        # ----------------------------------------------------

        existing_position = (
            trader.get_position()
        )

        if existing_position:

            result = monitor_open_position(
                trader
            )

            st.session_state.bot_market = (
                existing_position.get(
                    "symbol",
                    "—",
                )
            )

            st.session_state.bot_status = (
                "POSITION OPEN"
            )

            if (
                result.get(
                    "status"
                )
                == "CLOSED"
            ):

                st.session_state.bot_status = (
                    "TRADE CLOSED"
                )

            st.session_state.last_update = (
                now.isoformat()
            )

            return

        # ----------------------------------------------------
        # USER PAUSE
        # ----------------------------------------------------

        if st.session_state.bot_paused:

            st.session_state.bot_status = (
                "PAUSED BY USER"
            )

            st.session_state.last_update = (
                now.isoformat()
            )

            return

        # ----------------------------------------------------
        # RISK PAUSE
        # ----------------------------------------------------

        if (
            st.session_state
            .trading_paused_by_risk
        ):

            st.session_state.bot_status = (
                "DAILY LOSS LIMIT HIT"
            )

            st.session_state.last_update = (
                now.isoformat()
            )

            return

        # ----------------------------------------------------
        # SCAN
        # ----------------------------------------------------

        st.session_state.bot_status = (
            f"SCANNING "
            f"{len(SCAN_MARKETS)} MARKETS"
        )

        results = scan_markets()

        st.session_state.scanner_results = (
            results
        )

        summary = scanner_summary(
            results
        )

        best_setup = summary.get(
            "best_setup"
        )

        strongest_market = summary.get(
            "strongest_market"
        )

        if strongest_market:

            st.session_state.bot_market = (
                strongest_market.get(
                    "symbol",
                    "—",
                )
            )

            st.session_state.bot_signal = (
                strongest_market.get(
                    "signal",
                    "NO TRADE",
                )
            )

            st.session_state.bot_score = (
                strongest_market.get(
                    "score",
                    0,
                )
            )

            st.session_state.bot_reason = (
                strongest_market.get(
                    "reason",
                    "",
                )
            )

        # ----------------------------------------------------
        # NO CONFIRMED SCANNER SETUP
        # ----------------------------------------------------

        if best_setup is None:

            st.session_state.bot_status = (
                "NO QUALIFYING TRADE"
            )

            st.session_state.bot_confidence = (
                0.0
            )

            st.session_state.strategy_result = (
                None
            )

            st.session_state.last_update = (
                now.isoformat()
            )

            return

        # ----------------------------------------------------
        # MULTI-TIMEFRAME CONFIRMATION
        # ----------------------------------------------------

        confirmation = (
            confirm_scanner_setup(
                best_setup
            )
        )

        st.session_state.strategy_result = (
            confirmation
        )

        st.session_state.bot_market = (
            best_setup.get(
                "symbol",
                "—",
            )
        )

        st.session_state.bot_signal = (
            best_setup.get(
                "signal",
                "NO TRADE",
            )
        )

        st.session_state.bot_score = (
            best_setup.get(
                "score",
                0,
            )
        )

        st.session_state.bot_confidence = (
            confirmation.get(
                "confidence",
                0.0,
            )
        )

        st.session_state.bot_reason = (
            confirmation.get(
                "reason",
                "",
            )
        )

        if not confirmation.get(
            "approved",
            False,
        ):

            st.session_state.bot_status = (
                "WAITING FOR MTF CONFIRMATION"
            )

            st.session_state.last_update = (
                now.isoformat()
            )

            return

        # ----------------------------------------------------
        # EXECUTION
        # ----------------------------------------------------

        execution_setup = dict(
            best_setup
        )

        result = open_approved_trade(
            trader=trader,
            setup=execution_setup,
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

        else:

            st.session_state.bot_status = (
                "TRADE SKIPPED"
            )

        st.session_state.last_update = (
            now.isoformat()
        )

    except Exception as error:

        st.session_state.bot_status = (
            "ERROR"
        )

        st.session_state.bot_error = (
            str(error)
        )

        st.session_state.last_update = (
            now.isoformat()
        )


# ============================================================
# HEADER
# ============================================================

def render_header():

    utc_now = datetime.now(
        timezone.utc
    ).strftime(
        "%H:%M:%S UTC"
    )

    html(
        f"""
        <div class="quant-header">

            <div class="logo-box"></div>

            <div style="flex:1">

                <div class="terminal-title">
                    PRO AI • QUANT TERMINAL V2
                </div>

                <div class="terminal-subtitle">
                    MULTI-MARKET /
                    MULTI-TIMEFRAME /
                    PAPER EXECUTION /
                    POSTGRES STATE
                </div>

            </div>

            <div class="live-text">
                ● ONLINE &nbsp;&nbsp;
                {utc_now}
            </div>

        </div>
        """
    )


# ============================================================
# CONTROL BAR
# ============================================================

def render_controls():

    trader = (
        st.session_state.paper_trader
    )

    c1, c2, c3, c4 = st.columns(
        [
            1,
            1,
            1,
            2.5,
        ]
    )

    with c1:

        if st.session_state.bot_paused:

            if st.button(
                "▶ Resume Bot",
                width="stretch",
            ):

                st.session_state.bot_paused = (
                    False
                )

                st.rerun()

        else:

            if st.button(
                "⏸ Pause Bot",
                width="stretch",
            ):

                st.session_state.bot_paused = (
                    True
                )

                st.rerun()

    with c2:

        if st.button(
            "🔎 Force Scan",
            width="stretch",
        ):

            st.session_state.force_scan = (
                True
            )

            run_bot_cycle()

            st.session_state.force_scan = (
                False
            )

            st.rerun()

    with c3:

        position = (
            trader.get_position()
        )

        close_disabled = (
            position is None
        )

        if st.button(
            "✖ Close Paper Trade",
            disabled=close_disabled,
            width="stretch",
        ):

            result = manual_close_position(
                trader
            )

            if (
                result.get(
                    "status"
                )
                == "CLOSED"
            ):

                st.success(
                    "Paper position closed."
                )

            else:

                st.warning(
                    str(
                        result.get(
                            "reason",
                            result,
                        )
                    )
                )

            st.rerun()

    with c4:

        mode_text = (
            "FAST TEST MODE"
            if TEST_MODE
            else "STANDARD PAPER MODE"
        )

        html(
            f"""
            <div style="height:8px"></div>

            <span class="tag green">
                PAPER ONLY
            </span>

            <span class="tag cyan">
                {mode_text}
            </span>

            <span class="tag purple">
                POSTGRESQL STATE
            </span>

            <span class="tag yellow">
                MTF CONFIRMATION
            </span>
            """
        )


# ============================================================
# TERMINAL
# ============================================================

def render_terminal():

    trader = (
        st.session_state.paper_trader
    )

    balance = trader.get_balance()

    position = trader.get_position()

    history = trader.get_trade_history()

    drawdown = update_daily_risk()

    management = (
        trade_management_snapshot(
            trader
        )
    )

    render_header()

    html(
        f"""
        <div class="terminal-strip">

            COINBASE PUBLIC DATA

            &nbsp; | &nbsp;

            SCANNER:
            {len(SCAN_MARKETS)} MARKETS

            &nbsp; | &nbsp;

            BOT MARKET:
            {st.session_state.bot_market}

            &nbsp; | &nbsp;

            STATUS:
            {st.session_state.bot_status}

            &nbsp; | &nbsp;

            POLL:
            {POLL_SECONDS}s

        </div>
        """
    )

    render_controls()

    # ========================================================
    # ACCOUNT / BOT METRICS
    # ========================================================

    m1, m2, m3, m4, m5, m6 = st.columns(
        6
    )

    m1.metric(
        "Paper Equity",
        f"${balance:,.2f}",
    )

    total_pnl = sum(
        float(
            trade.get(
                "pnl",
                0,
            )
        )
        for trade in history
    )

    m2.metric(
        "Realized P&L",
        f"${total_pnl:,.2f}",
    )

    m3.metric(
        "Closed Trades",
        len(history),
    )

    m4.metric(
        "Daily Drawdown",
        f"{drawdown:.2f}%",
    )

    m5.metric(
        "AI Score",
        f"{float(st.session_state.bot_score):+.1f}",
    )

    m6.metric(
        "MTF Confidence",
        f"{st.session_state.bot_confidence:.1f}%",
    )

    # ========================================================
    # CHART CONTROLS
    # ========================================================

    c1, c2 = st.columns(
        [
            1,
            1,
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

    ticker = get_ticker(
        symbol=selected_pair,
        exchange="PUBLIC",
        api_key="",
        api_secret="",
        use_testnet=False,
    )

    last = 0.0
    change_pct = 0.0
    high = 0.0
    low = 0.0

    if ticker:

        last = float(
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

        high = float(
            ticker.get(
                "high",
                0,
            )
        )

        low = float(
            ticker.get(
                "low",
                0,
            )
        )

    chart_col, engine_col = st.columns(
        [
            3,
            1.25,
        ]
    )

    # ========================================================
    # CHART
    # ========================================================

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
                    ${last:,.2f}
                </span>

                &nbsp;&nbsp;

                <span class="{price_css}">
                    {change_pct:+.2f}%
                </span>

                &nbsp;&nbsp;

                HIGH ${high:,.2f}

                &nbsp;&nbsp;

                LOW ${low:,.2f}

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
            height:460px;
            width:100%;
            border:1px solid #252f3a;
            background:#070a0e;
        ">

            <div
                id="tv_chart"
                style="
                height:460px;
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
            height=465,
        )

    # ========================================================
    # AI ENGINE
    # ========================================================

    with engine_col:

        signal = (
            st.session_state.bot_signal
        )

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
            <div class="panel">

                <div class="small-muted">
                    BOT MARKET
                </div>

                <div class="purple"
                     style="
                     font-family:monospace;
                     font-size:16px;">
                    {st.session_state.bot_market}
                </div>

                <br>

                <div class="small-muted">
                    SIGNAL
                </div>

                <div class="signal-large {signal_css}">
                    {signal}
                </div>

                <br>

                <div class="small-muted">
                    AI SCORE
                </div>

                <div class="score-large">
                    {float(st.session_state.bot_score):+.1f}
                </div>

                <div class="small-muted">
                    MTF CONFIDENCE
                </div>

                <div class="cyan"
                     style="
                     font-family:monospace;
                     font-size:18px;">
                    {st.session_state.bot_confidence:.1f}%
                </div>

                <br>

                <div class="small-muted">
                    STATUS
                </div>

                <div style="
                    font-family:monospace;
                    font-size:11px;">
                    {st.session_state.bot_status}
                </div>

                <br>

                <div class="small-muted">
                    ACTIVE RISK
                </div>

                <div class="cyan">
                    {management['risk_pct']}%
                </div>

                <div class="small-muted">
                    TP
                </div>

                <div class="green">
                    +{management['active_tp_pct']}%
                </div>

                <div class="small-muted">
                    SL
                </div>

                <div class="red">
                    -{management['active_sl_pct']}%
                </div>

            </div>
            """
        )

    # ========================================================
    # SCANNER TABLE
    # ========================================================

    st.subheader(
        "🔎 Multi-Market Scanner"
    )

    results = (
        st.session_state.scanner_results
    )

    if results:

        ranked = rank_markets(
            results,
            limit=len(
                results
            ),
        )

        table_rows = []

        for item in ranked:

            table_rows.append(
                {
                    "Symbol":
                        item.get(
                            "symbol"
                        ),

                    "Price":
                        item.get(
                            "price"
                        ),

                    "Signal":
                        item.get(
                            "signal"
                        ),

                    "Score":
                        item.get(
                            "score"
                        ),

                    "Confirmed":
                        item.get(
                            "confirmed"
                        ),

                    "RSI":
                        item.get(
                            "rsi"
                        ),

                    "MACD":
                        item.get(
                            "macd"
                        ),

                    "24h %":
                        item.get(
                            "change_pct"
                        ),

                    "Reason":
                        item.get(
                            "reason"
                        ),
                }
            )

        scanner_df = pd.DataFrame(
            table_rows
        )

        st.dataframe(
            scanner_df,
            width="stretch",
            hide_index=True,
        )

    else:

        if position:

            st.info(
                "Scanner waits while the current "
                "paper position is being managed."
            )

        else:

            st.info(
                "Waiting for scanner cycle."
            )

    # ========================================================
    # STRATEGY DETAILS
    # ========================================================

    strategy = (
        st.session_state.strategy_result
    )

    with st.expander(
        "🧠 Multi-Timeframe Strategy Details"
    ):

        if strategy:

            st.json(
                strategy
            )

        else:

            st.info(
                "No active multi-timeframe "
                "confirmation yet."
            )

    # ========================================================
    # ACTIVE POSITION
    # ========================================================

    st.subheader(
        "📌 Paper Position"
    )

    if position:

        position_df = pd.DataFrame(
            [
                {
                    "Symbol":
                        position.get(
                            "symbol"
                        ),

                    "Side":
                        position.get(
                            "side"
                        ),

                    "Quantity":
                        position.get(
                            "quantity"
                        ),

                    "Entry":
                        position.get(
                            "entry_price"
                        ),

                    "Take Profit":
                        position.get(
                            "take_profit"
                        ),

                    "Stop Loss":
                        position.get(
                            "stop_loss"
                        ),

                    "Opened":
                        position.get(
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

    else:

        st.info(
            "No open paper position."
        )

    # ========================================================
    # TRADE HISTORY + ANALYTICS
    # ========================================================

    st.subheader(
        "📊 Trading Analytics"
    )

    if history:

        wins = [
            trade
            for trade in history
            if float(
                trade.get(
                    "pnl",
                    0,
                )
            ) > 0
        ]

        losses = [
            trade
            for trade in history
            if float(
                trade.get(
                    "pnl",
                    0,
                )
            ) < 0
        ]

        win_rate = (
            len(wins)
            / len(history)
            * 100
        )

        gross_profit = sum(
            float(
                trade.get(
                    "pnl",
                    0,
                )
            )
            for trade in wins
        )

        gross_loss = abs(
            sum(
                float(
                    trade.get(
                        "pnl",
                        0,
                    )
                )
                for trade in losses
            )
        )

        profit_factor = (
            gross_profit
            / gross_loss
            if gross_loss > 0
            else 0.0
        )

        a1, a2, a3, a4 = st.columns(
            4
        )

        a1.metric(
            "Win Rate",
            f"{win_rate:.1f}%",
        )

        a2.metric(
            "Profit Factor",
            f"{profit_factor:.2f}",
        )

        a3.metric(
            "Winning Trades",
            len(wins),
        )

        a4.metric(
            "Losing Trades",
            len(losses),
        )

        history_df = pd.DataFrame(
            history
        )

        st.dataframe(
            history_df,
            width="stretch",
            hide_index=True,
        )

    else:

        st.info(
            "No completed paper trades yet."
        )

    # ========================================================
    # ANALYSIS
    # ========================================================

    st.subheader(
        "🧠 AI Analysis"
    )

    st.code(
        f"""
BOT STATUS:
{st.session_state.bot_status}

BOT MARKET:
{st.session_state.bot_market}

SIGNAL:
{st.session_state.bot_signal}

AI SCORE:
{st.session_state.bot_score}

MULTI-TIMEFRAME CONFIDENCE:
{st.session_state.bot_confidence}%

REASON:
{st.session_state.bot_reason}

LAST UPDATE:
{st.session_state.last_update}

TEST MODE:
{TEST_MODE}

REAL ORDERS:
DISABLED
""",
        language="text",
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

            PRO AI QUANT TERMINAL V2
            &nbsp; • &nbsp;
            MULTI-MARKET
            &nbsp; • &nbsp;
            MULTI-TIMEFRAME
            &nbsp; • &nbsp;
            POSTGRESQL PERSISTENCE
            &nbsp; • &nbsp;
            PAPER EXECUTION ONLY

        </div>
        """
    )


# ============================================================
# AUTO REFRESH
# ============================================================

@st.fragment(
    run_every=f"{POLL_SECONDS}s"
)
def autonomous_terminal():

    if PAPER_TRADING:

        run_bot_cycle()

    render_terminal()


autonomous_terminal()

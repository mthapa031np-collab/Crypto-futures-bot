"""
ui_v3.py

PRO AI QUANT TERMINAL V3
Institutional dashboard presentation layer.

IMPORTANT:
- UI ONLY
- Does not place trades
- Does not modify database
- Does not change scanner / strategy / risk logic
"""

import textwrap
from typing import Dict, List, Optional

import pandas as pd
import streamlit as st


# ============================================================
# HTML HELPER
# ============================================================

def html(content: str):

    st.html(
        textwrap.dedent(
            content
        ).strip()
    )


# ============================================================
# V3 GLOBAL STYLE
# ============================================================

def inject_v3_css():

    html(
        """
        <style>

        #MainMenu,
        footer,
        header {
            visibility: hidden;
        }

        .block-container {
            padding-top: .35rem !important;
            padding-bottom: 1rem !important;
            padding-left: .7rem !important;
            padding-right: .7rem !important;
            max-width: 100% !important;
        }

        .stApp {
            background:
                radial-gradient(
                    circle at 45% 0%,
                    #131a22 0%,
                    #080c11 44%,
                    #040609 100%
                );
            color: #dce6ef;
        }

        .v3-header {
            min-height: 58px;
            padding: 8px 12px;

            display: flex;
            align-items: center;

            border: 1px solid #28323d;

            background:
                linear-gradient(
                    90deg,
                    #080c11,
                    #111820,
                    #080c11
                );

            margin-bottom: 5px;
        }

        .v3-logo {
            width: 30px;
            height: 30px;

            margin-right: 11px;

            background: #f2d43b;

            box-shadow:
                0 0 18px
                rgba(242,212,59,.30);
        }

        .v3-title {
            font-family: monospace;
            font-size: 15px;
            font-weight: 900;

            color: #f5f7fa;

            letter-spacing: .5px;
        }

        .v3-subtitle {
            margin-top: 2px;

            font-family: monospace;
            font-size: 8px;

            color: #687789;

            letter-spacing: 1px;
        }

        .v3-online {
            font-family: monospace;
            font-size: 10px;

            color: #00d99a;
        }

        .v3-strip {
            border-top: 1px solid #202a34;
            border-bottom: 1px solid #202a34;

            background: #070b10;

            padding: 6px 9px;

            font-family: monospace;
            font-size: 9px;

            color: #718094;

            margin-bottom: 6px;
        }

        .v3-panel {
            background:
                linear-gradient(
                    180deg,
                    #0b1016,
                    #080c11
                );

            border: 1px solid #25303b;

            border-radius: 4px;

            padding: 10px;

            height: 100%;
        }

        .v3-panel-title {
            font-family: monospace;
            font-size: 9px;

            color: #718095;

            text-transform: uppercase;

            letter-spacing: 1px;

            margin-bottom: 8px;
        }

        .v3-metric-label {
            font-family: monospace;
            font-size: 8px;

            color: #647184;

            text-transform: uppercase;
        }

        .v3-metric {
            font-family: monospace;
            font-size: 24px;

            font-weight: 700;

            margin-top: 4px;
        }

        .v3-small {
            font-family: monospace;
            font-size: 9px;

            color: #708095;
        }

        .green {
            color: #00d99a;
        }

        .red {
            color: #ff5275;
        }

        .yellow {
            color: #f2d43b;
        }

        .cyan {
            color: #2ee0d0;
        }

        .purple {
            color: #aa82ff;
        }

        .blue {
            color: #58aaff;
        }

        .v3-card-grid {
            display: grid;

            grid-template-columns:
                repeat(6, 1fr);

            gap: 5px;

            margin-bottom: 7px;
        }

        .v3-card {
            background: #090e14;

            border: 1px solid #26313d;

            padding: 9px;

            min-height: 75px;
        }

        .v3-card-value {
            font-family: monospace;
            font-size: 18px;

            margin-top: 8px;
        }

        .v3-ai-core {
            position: relative;

            min-height: 280px;

            overflow: hidden;

            background:
                radial-gradient(
                    circle at center,
                    rgba(46,224,208,.08),
                    transparent 36%
                ),
                #070a0e;

            border: 1px solid #26303b;
        }

        .v3-core-circle {
            position: absolute;

            left: calc(50% - 52px);
            top: calc(50% - 52px);

            width: 104px;
            height: 104px;

            border-radius: 50%;

            border: 2px solid #f2d43b;

            background: #15140b;

            display: flex;
            align-items: center;
            justify-content: center;

            text-align: center;

            font-family: monospace;
            font-size: 11px;

            color: #f2d43b;

            box-shadow:
                0 0 20px
                rgba(242,212,59,.25);
        }

        .v3-node {
            position: absolute;

            width: 72px;
            height: 72px;

            border-radius: 50%;

            background: #0a0f15;

            border: 1px solid #364250;

            display: flex;
            align-items: center;
            justify-content: center;

            text-align: center;

            font-family: monospace;
            font-size: 9px;
        }

        .node-a {
            left: 10%;
            top: 18%;
        }

        .node-b {
            right: 10%;
            top: 18%;
        }

        .node-c {
            left: 18%;
            bottom: 10%;
        }

        .node-d {
            right: 18%;
            bottom: 10%;
        }

        .node-e {
            left: 4%;
            top: 51%;
        }

        .node-f {
            right: 4%;
            top: 51%;
        }

        div[data-testid="stMetric"] {
            background: #090e14;

            border: 1px solid #27323e;

            border-radius: 4px;

            padding: 8px;
        }

        div[data-testid="stMetric"] label {
            font-size: 9px !important;

            color: #718095 !important;

            text-transform: uppercase;
        }

        div[data-testid="stMetricValue"] {
            font-family: monospace;

            font-size: 19px !important;
        }

        div[data-baseweb="select"] > div {
            background: #090e14 !important;

            border-color: #26313d !important;
        }

        </style>
        """
    )


# ============================================================
# HEADER
# ============================================================

def render_header(
    utc_time: str,
):

    html(
        f"""
        <div class="v3-header">

            <div class="v3-logo"></div>

            <div style="flex:1">

                <div class="v3-title">
                    PRO AI • QUANT TERMINAL V3
                </div>

                <div class="v3-subtitle">
                    MULTI-ASSET /
                    QUANT INTELLIGENCE /
                    PORTFOLIO RISK /
                    AUTONOMOUS PAPER ENGINE
                </div>

            </div>

            <div class="v3-online">
                ● ONLINE
                &nbsp;&nbsp;
                {utc_time}
            </div>

        </div>
        """
    )


# ============================================================
# MARKET STRIP
# ============================================================

def render_market_strip(
    scanner_count: int,
    bot_market: str,
    bot_status: str,
    poll_seconds: int,
):

    html(
        f"""
        <div class="v3-strip">

            PUBLIC MARKET DATA

            &nbsp; | &nbsp;

            SCANNER:
            {scanner_count} MARKETS

            &nbsp; | &nbsp;

            BOT MARKET:
            {bot_market}

            &nbsp; | &nbsp;

            STATUS:
            {bot_status}

            &nbsp; | &nbsp;

            POLL:
            {poll_seconds}s

            &nbsp; | &nbsp;

            REAL EXECUTION:
            OFF

        </div>
        """
    )


# ============================================================
# TOP METRICS
# ============================================================

def render_top_metrics(
    equity: float,
    realized_pnl: float,
    closed_trades: int,
    drawdown: float,
    ai_score: float,
    mtf_confidence: float,
):

    columns = st.columns(6)

    values = [
        (
            "Paper Equity",
            f"${equity:,.2f}",
        ),
        (
            "Realized P&L",
            f"${realized_pnl:,.2f}",
        ),
        (
            "Closed Trades",
            str(closed_trades),
        ),
        (
            "Daily Drawdown",
            f"{drawdown:.2f}%",
        ),
        (
            "AI Score",
            f"{ai_score:+.1f}",
        ),
        (
            "MTF Confidence",
            f"{mtf_confidence:.1f}%",
        ),
    ]

    for column, item in zip(
        columns,
        values,
    ):

        with column:

            st.metric(
                item[0],
                item[1],
            )


# ============================================================
# INSTITUTIONAL INTELLIGENCE CARDS
# ============================================================

def render_intelligence_cards(
    regime: str,
    trend: str,
    atr_pct: float,
    momentum: float,
    bullish_pct: float,
    bearish_pct: float,
):

    html(
        f"""
        <div class="v3-card-grid">

            <div class="v3-card">
                <div class="v3-metric-label">
                    MARKET REGIME
                </div>

                <div class=
                    "v3-card-value yellow">
                    {regime}
                </div>
            </div>

            <div class="v3-card">
                <div class="v3-metric-label">
                    TREND
                </div>

                <div class=
                    "v3-card-value cyan">
                    {trend}
                </div>
            </div>

            <div class="v3-card">
                <div class="v3-metric-label">
                    ATR VOLATILITY
                </div>

                <div class=
                    "v3-card-value purple">
                    {atr_pct:.2f}%
                </div>
            </div>

            <div class="v3-card">
                <div class="v3-metric-label">
                    MOMENTUM
                </div>

                <div class=
                    "v3-card-value blue">
                    {momentum:+.2f}%
                </div>
            </div>

            <div class="v3-card">
                <div class="v3-metric-label">
                    BULLISH BREADTH
                </div>

                <div class=
                    "v3-card-value green">
                    {bullish_pct:.1f}%
                </div>
            </div>

            <div class="v3-card">
                <div class="v3-metric-label">
                    BEARISH BREADTH
                </div>

                <div class=
                    "v3-card-value red">
                    {bearish_pct:.1f}%
                </div>
            </div>

        </div>
        """
    )


# ============================================================
# AI CORE VISUAL
# ============================================================

def render_ai_core(
    score: float,
    mtf_confidence: float,
    regime: str,
    trend: str,
    risk_pct: float,
    position_state: str,
):

    html(
        f"""
        <div class="v3-ai-core">

            <div
                class="v3-small"
                style="
                position:absolute;
                left:12px;
                top:10px;
                "
            >
                AI MARKET INTELLIGENCE //
                RELATIONSHIP ENGINE
            </div>

            <div class=
                "v3-node node-a cyan">
                MTF<br>
                {mtf_confidence:.1f}%
            </div>

            <div class=
                "v3-node node-b yellow">
                REGIME<br>
                {regime}
            </div>

            <div class=
                "v3-node node-c purple">
                TREND<br>
                {trend}
            </div>

            <div class=
                "v3-node node-d cyan">
                RISK<br>
                {risk_pct:.1f}%
            </div>

            <div class=
                "v3-node node-e blue">
                POSITION<br>
                {position_state}
            </div>

            <div class=
                "v3-node node-f green">
                TP / SL<br>
                AUTO
            </div>

            <div class="v3-core-circle">

                AI CORE<br>

                SCORE<br>

                {score:+.1f}

            </div>

        </div>
        """
    )


# ============================================================
# SCANNER TABLE
# ============================================================

def render_scanner(
    scanner_results: List[Dict],
):

    st.subheader(
        "🔎 Multi-Market Intelligence Scanner"
    )

    if not scanner_results:

        st.info(
            "No scanner results available."
        )

        return

    rows = []

    for item in scanner_results:

        rows.append(
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
                        "signal",
                        "NO TRADE",
                    ),

                "Score":
                    item.get(
                        "score",
                        0,
                    ),

                "Confirmed":
                    item.get(
                        "confirmed",
                        False,
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
                        "reason",
                        "",
                    ),
            }
        )

    dataframe = pd.DataFrame(
        rows
    )

    st.dataframe(
        dataframe,
        width="stretch",
        hide_index=True,
    )


# ============================================================
# ACTIVE POSITION
# ============================================================

def render_position(
    position: Optional[Dict],
    progress: Optional[Dict] = None,
):

    st.subheader(
        "📌 Active Paper Position"
    )

    if not position:

        st.info(
            "No open paper position."
        )

        return

    row = {
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

    if progress:

        row[
            "Unrealized %"
        ] = progress.get(
            "pnl_pct",
            0,
        )

        row[
            "TP Distance"
        ] = progress.get(
            "tp_distance"
        )

        row[
            "SL Distance"
        ] = progress.get(
            "sl_distance"
        )

    st.dataframe(
        pd.DataFrame(
            [row]
        ),
        width="stretch",
        hide_index=True,
    )


# ============================================================
# TRADING ANALYTICS
# ============================================================

def render_trade_analytics(
    statistics: Dict,
    trade_history: List[Dict],
):

    st.subheader(
        "📊 Trading Analytics"
    )

    c1, c2, c3, c4 = (
        st.columns(4)
    )

    c1.metric(
        "Win Rate",
        f"{statistics.get('win_rate', 0):.1f}%",
    )

    c2.metric(
        "Profit Factor",
        f"{statistics.get('profit_factor', 0):.2f}",
    )

    c3.metric(
        "Expectancy",
        f"${statistics.get('expectancy', 0):.2f}",
    )

    c4.metric(
        "Net P&L",
        f"${statistics.get('net_pnl', 0):.2f}",
    )

    if trade_history:

        history_df = pd.DataFrame(
            trade_history
        )

        st.dataframe(
            history_df,
            width="stretch",
            hide_index=True,
        )


# ============================================================
# MULTI-ASSET NAVIGATION
# ============================================================

def render_asset_navigation():

    return st.tabs(
        [
            "⚡ Overview",
            "₿ Crypto",
            "📈 Stocks",
            "🥇 Metals",
            "🌐 Indices",
            "💼 Portfolio",
            "🧠 AI Intelligence",
        ]
    )


# ============================================================
# FUTURE MODULE PLACEHOLDER
# ============================================================

def render_future_module(
    title: str,
    message: str,
):

    html(
        f"""
        <div class="v3-panel">

            <div class=
                "v3-panel-title">
                {title}
            </div>

            <div
                style="
                font-family:monospace;
                font-size:11px;
                line-height:1.8;
                color:#9aa8b8;
                "
            >
                {message}
            </div>

        </div>
        """
    )

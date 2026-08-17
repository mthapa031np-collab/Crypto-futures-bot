"""
app.py

PRO AI QUANT TERMINAL V3
Institutional multi-asset paper-trading controller.

Backend:
- scanner.py
- strategy_engine.py
- trade_engine.py
- risk_manager.py
- paper_trader.py
- market_data.py
- settings.py

V3:
- analytics_engine.py
- asset_registry.py
- ui_v3.py

IMPORTANT:
REAL ORDERS ARE DISABLED.
"""

from datetime import datetime, timezone

import pandas as pd
import streamlit as st
import streamlit.components.v1 as components

from settings import (
    PAPER_TRADING,
    PAPER_BALANCE,
    RISK_PCT,
    POLL_SECONDS,
    MAX_DAILY_LOSS_PCT,
    SCAN_MARKETS,
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
    get_current_price,
)

from paper_trader import PaperTrader
from market_data import (
    get_ticker,
    get_candles,
)

from analytics_engine import (
    detect_market_regime,
    calculate_momentum,
    scanner_intelligence,
    trade_statistics,
    position_progress,
)

from asset_registry import (
    get_assets_by_class,
    ASSET_CRYPTO,
    ASSET_STOCK,
    ASSET_METAL,
    ASSET_INDEX,
    ASSET_ETF,
)

from ui_v3 import (
    inject_v3_css,
    render_header,
    render_market_strip,
    render_top_metrics,
    render_intelligence_cards,
    render_ai_core,
    render_scanner,
    render_position,
    render_trade_analytics,
    render_future_module,
)


# ============================================================
# PAGE
# ============================================================

st.set_page_config(
    page_title="PRO AI QUANT TERMINAL V3",
    page_icon="⚡",
    layout="wide",
    initial_sidebar_state="collapsed",
)

inject_v3_css()


# ============================================================
# SESSION STATE
# ============================================================

if "paper_trader" not in st.session_state:
    st.session_state.paper_trader = PaperTrader(
        starting_balance=PAPER_BALANCE
    )

if "bot_paused" not in st.session_state:
    st.session_state.bot_paused = False

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
    st.session_state.bot_score = 0.0

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


trader = st.session_state.paper_trader


# ============================================================
# DAILY RISK
# ============================================================

def update_daily_risk():

    balance = trader.get_balance()

    today = datetime.now(
        timezone.utc
    ).date()

    if st.session_state.day_start_date != today:

        st.session_state.day_start_date = today
        st.session_state.day_start_balance = balance
        st.session_state.trading_paused_by_risk = False

    start_balance = (
        st.session_state.day_start_balance
    )

    if start_balance <= 0:
        return 0.0

    drawdown = (
        (start_balance - balance)
        / start_balance
        * 100
    )

    if drawdown >= MAX_DAILY_LOSS_PCT:

        st.session_state.trading_paused_by_risk = True

    return drawdown


# ============================================================
# BOT CYCLE
# ============================================================

def run_bot_cycle():

    now = datetime.now(
        timezone.utc
    )

    try:

        st.session_state.bot_error = None

        update_daily_risk()

        # ----------------------------------------------------
        # EXISTING POSITION
        # ----------------------------------------------------

        position = trader.get_position()

        if position:

            result = monitor_open_position(
                trader
            )

            st.session_state.bot_market = (
                position.get(
                    "symbol",
                    "—",
                )
            )

            st.session_state.bot_status = (
                "POSITION OPEN"
            )

            if (
                result.get("status")
                == "CLOSED"
            ):

                st.session_state.bot_status = (
                    "TRADE CLOSED"
                )

                st.session_state.bot_signal = (
                    "NO TRADE"
                )

                st.session_state.bot_score = 0.0
                st.session_state.bot_confidence = 0.0

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
        # MULTI-MARKET SCAN
        # ----------------------------------------------------

        st.session_state.bot_status = (
            f"SCANNING {len(SCAN_MARKETS)} MARKETS"
        )

        results = scan_markets()

        st.session_state.scanner_results = (
            results
        )

        summary = scanner_summary(
            results
        )

        strongest = summary.get(
            "strongest_market"
        )

        best_setup = summary.get(
            "best_setup"
        )

        if strongest:

            st.session_state.bot_market = (
                strongest.get(
                    "symbol",
                    "—",
                )
            )

            st.session_state.bot_signal = (
                strongest.get(
                    "signal",
                    "NO TRADE",
                )
            )

            st.session_state.bot_score = float(
                strongest.get(
                    "score",
                    0,
                )
            )

            st.session_state.bot_reason = (
                strongest.get(
                    "reason",
                    "",
                )
            )

        # ----------------------------------------------------
        # NO BASE SIGNAL
        # ----------------------------------------------------

        if best_setup is None:

            st.session_state.bot_status = (
                "NO QUALIFYING TRADE"
            )

            st.session_state.bot_confidence = (
                0.0
            )

            st.session_state.strategy_result = None

            st.session_state.last_update = (
                now.isoformat()
            )

            return

        # ----------------------------------------------------
        # MTF CONFIRMATION
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

        st.session_state.bot_score = float(
            best_setup.get(
                "score",
                0,
            )
        )

        st.session_state.bot_confidence = float(
            confirmation.get(
                "confidence",
                0,
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

        execution = open_approved_trade(
            trader=trader,
            setup=best_setup,
        )

        if (
            execution.get("status")
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

        st.session_state.bot_status = "ERROR"

        st.session_state.bot_error = str(
            error
        )

        st.session_state.last_update = (
            now.isoformat()
        )


# ============================================================
# STATIC HEADER
# Kept outside the auto-refresh fragment to reduce flicker.
# ============================================================

utc_now = datetime.now(
    timezone.utc
).strftime(
    "%H:%M:%S UTC"
)

render_header(
    utc_now
)


# ============================================================
# MULTI-ASSET NAVIGATION
# ============================================================

overview_tab, crypto_tab, stocks_tab, metals_tab, indices_tab, portfolio_tab, intelligence_tab = st.tabs(
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
# OVERVIEW
# ============================================================

with overview_tab:

    # Controls remain outside auto fragment where possible.

    c1, c2, c3, c4 = st.columns(
        [1, 1, 1, 2.5]
    )

    with c1:

        if st.session_state.bot_paused:

            if st.button(
                "▶ Resume Bot",
                width="stretch",
            ):

                st.session_state.bot_paused = False
                st.rerun()

        else:

            if st.button(
                "⏸ Pause Bot",
                width="stretch",
            ):

                st.session_state.bot_paused = True
                st.rerun()

    with c2:

        if st.button(
            "🔎 Force Scan",
            width="stretch",
        ):

            run_bot_cycle()
            st.rerun()

    with c3:

        current_position = (
            trader.get_position()
        )

        if st.button(
            "✖ Close Paper Trade",
            disabled=(
                current_position is None
            ),
            width="stretch",
        ):

            result = manual_close_position(
                trader
            )

            if (
                result.get("status")
                == "CLOSED"
            ):

                st.success(
                    "Paper trade closed."
                )

            else:

                st.warning(
                    str(result)
                )

            st.rerun()

    with c4:

        st.caption(
            "PAPER MODE • MTF • POSTGRES • "
            "MULTI-MARKET • REAL EXECUTION OFF"
        )


    # ========================================================
    # LIVE V3 AREA
    # Only this section auto-reruns.
    # ========================================================

    @st.fragment(
        run_every=f"{POLL_SECONDS}s"
    )
    def live_overview():

        if PAPER_TRADING:

            run_bot_cycle()

        balance = trader.get_balance()

        position = trader.get_position()

        history = (
            trader.get_trade_history()
        )

        drawdown = (
            update_daily_risk()
        )

        scanner_results = (
            st.session_state.scanner_results
        )

        # --------------------------------------------
        # Analytics
        # --------------------------------------------

        intelligence = (
            scanner_intelligence(
                scanner_results
            )
        )

        breadth = intelligence.get(
            "breadth",
            {},
        )

        bot_market = (
            st.session_state.bot_market
        )

        analytics_symbol = (
            position.get("symbol")
            if position
            else (
                bot_market
                if bot_market
                in SCAN_MARKETS
                else "BTCUSDT"
            )
        )

        regime = {
            "regime": "WAITING",
            "trend": "UNKNOWN",
            "atr_pct": 0.0,
        }

        momentum = 0.0

        try:

            candles = get_candles(
                exchange="PUBLIC",
                symbol=analytics_symbol,
                timeframe_minutes=15,
                limit=100,
                api_key="",
                api_secret="",
                use_testnet=False,
            )

            if (
                candles is not None
                and len(candles) >= 55
            ):

                regime = detect_market_regime(
                    candles
                )

                momentum = calculate_momentum(
                    candles
                )

        except Exception:
            pass

        statistics = trade_statistics(
            history
        )

        current_price = 0.0

        if position:

            current_price = (
                get_current_price(
                    position.get("symbol")
                )
                or 0.0
            )

        progress = position_progress(
            position,
            current_price,
        )

        # --------------------------------------------
        # Status strip
        # --------------------------------------------

        render_market_strip(
            scanner_count=len(
                SCAN_MARKETS
            ),
            bot_market=(
                st.session_state.bot_market
            ),
            bot_status=(
                st.session_state.bot_status
            ),
            poll_seconds=(
                POLL_SECONDS
            ),
        )

        # --------------------------------------------
        # Top metrics
        # --------------------------------------------

        render_top_metrics(
            equity=balance,
            realized_pnl=(
                statistics.get(
                    "net_pnl",
                    0,
                )
            ),
            closed_trades=(
                statistics.get(
                    "total_trades",
                    0,
                )
            ),
            drawdown=drawdown,
            ai_score=(
                float(
                    st.session_state.bot_score
                )
            ),
            mtf_confidence=(
                float(
                    st.session_state
                    .bot_confidence
                )
            ),
        )

        render_intelligence_cards(
            regime=regime.get(
                "regime",
                "UNKNOWN",
            ),
            trend=regime.get(
                "trend",
                "UNKNOWN",
            ),
            atr_pct=float(
                regime.get(
                    "atr_pct",
                    0,
                )
            ),
            momentum=momentum,
            bullish_pct=float(
                breadth.get(
                    "bullish_pct",
                    0,
                )
            ),
            bearish_pct=float(
                breadth.get(
                    "bearish_pct",
                    0,
                )
            ),
        )

        # --------------------------------------------
        # Main V3 layout
        # --------------------------------------------

        left, middle, right = st.columns(
            [1.1, 2.4, 1.25]
        )

        with left:

            render_ai_core(
                score=float(
                    st.session_state.bot_score
                ),
                mtf_confidence=float(
                    st.session_state
                    .bot_confidence
                ),
                regime=regime.get(
                    "regime",
                    "UNKNOWN",
                ),
                trend=regime.get(
                    "trend",
                    "UNKNOWN",
                ),
                risk_pct=RISK_PCT,
                position_state=(
                    "OPEN"
                    if position
                    else "FLAT"
                ),
            )

        with middle:

            selected_pair = (
                st.session_state
                .selected_pair
            )

            ticker = get_ticker(
                symbol=selected_pair,
                exchange="PUBLIC",
                api_key="",
                api_secret="",
                use_testnet=False,
            )

            last = 0.0
            change = 0.0

            if ticker:

                last = float(
                    ticker.get(
                        "last",
                        0,
                    )
                )

                change = float(
                    ticker.get(
                        "change_pct",
                        0,
                    )
                )

            st.metric(
                selected_pair,
                f"${last:,.4f}",
                f"{change:+.2f}%",
            )

            base = selected_pair.replace(
                "USDT",
                "",
            )

            tv_symbol = (
                f"COINBASE:{base}USD"
            )

            tv_widget = f"""
            <div style="
                height:390px;
                width:100%;
                border:1px solid #26303b;
                background:#070a0e;
            ">

                <div
                    id="tv_chart"
                    style="
                    height:390px;
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
                height=395,
            )

        with right:

            st.metric(
                "Bot Market",
                st.session_state.bot_market,
            )

            st.metric(
                "Signal",
                st.session_state.bot_signal,
            )

            st.metric(
                "AI Score",
                f"{float(st.session_state.bot_score):+.1f}",
            )

            st.metric(
                "MTF",
                f"{float(st.session_state.bot_confidence):.1f}%",
            )

            st.caption(
                st.session_state.bot_status
            )

        render_position(
            position=position,
            progress=progress,
        )

        if scanner_results:

            ranked = rank_markets(
                scanner_results,
                limit=len(
                    scanner_results
                ),
            )

            render_scanner(
                ranked
            )

        elif position:

            st.info(
                "Scanner waits while the active "
                "paper position is managed."
            )

        render_trade_analytics(
            statistics=statistics,
            trade_history=history,
        )

        with st.expander(
            "🧠 Strategy / AI Details"
        ):

            st.write(
                "Status:",
                st.session_state.bot_status,
            )

            st.write(
                "Market:",
                st.session_state.bot_market,
            )

            st.write(
                "Signal:",
                st.session_state.bot_signal,
            )

            st.write(
                "Score:",
                st.session_state.bot_score,
            )

            st.write(
                "MTF Confidence:",
                st.session_state
                .bot_confidence,
            )

            st.write(
                "Reason:",
                st.session_state.bot_reason,
            )

            if (
                st.session_state
                .strategy_result
            ):

                st.json(
                    st.session_state
                    .strategy_result
                )

        if st.session_state.bot_error:

            st.error(
                st.session_state.bot_error
            )


    live_overview()


# ============================================================
# CRYPTO
# ============================================================

with crypto_tab:

    st.subheader(
        "₿ Crypto Intelligence"
    )

    crypto_assets = get_assets_by_class(
        ASSET_CRYPTO
    )

    st.write(
        "Enabled crypto universe:",
        ", ".join(
            crypto_assets
        ),
    )

    st.caption(
        "Current autonomous paper trading "
        "engine operates in this asset class."
    )


# ============================================================
# STOCKS
# ============================================================

with stocks_tab:

    render_future_module(
        "STOCK MARKET MODULE",
        (
            "V3 architecture recognizes stocks. "
            "Live stock market-data provider, "
            "market-hours logic, relative volume, "
            "VWAP, earnings/event filters and "
            "stock-specific risk rules will be "
            "connected in the next multi-asset phase."
        ),
    )

    st.write(
        get_assets_by_class(
            ASSET_STOCK
        )
    )


# ============================================================
# METALS
# ============================================================

with metals_tab:

    render_future_module(
        "METALS MODULE",
        (
            "Gold (XAUUSD) and Silver (XAGUSD) "
            "are registered but trading remains "
            "disabled until a proper metals data "
            "provider, session logic and volatility "
            "rules are connected."
        ),
    )

    st.write(
        get_assets_by_class(
            ASSET_METAL
        )
    )


# ============================================================
# INDICES
# ============================================================

with indices_tab:

    render_future_module(
        "INDICES MODULE",
        (
            "S&P 500, Nasdaq and Dow architecture "
            "is reserved for market-regime and "
            "future index analysis."
        ),
    )

    st.write(
        get_assets_by_class(
            ASSET_INDEX
        )
    )


# ============================================================
# PORTFOLIO
# ============================================================

with portfolio_tab:

    history = trader.get_trade_history()

    statistics = trade_statistics(
        history
    )

    render_trade_analytics(
        statistics,
        history,
    )


# ============================================================
# AI INTELLIGENCE
# ============================================================

with intelligence_tab:

    st.subheader(
        "🧠 AI Intelligence"
    )

    st.write(
        "Current Market:",
        st.session_state.bot_market,
    )

    st.write(
        "Signal:",
        st.session_state.bot_signal,
    )

    st.write(
        "AI Score:",
        st.session_state.bot_score,
    )

    st.write(
        "MTF Confidence:",
        st.session_state
        .bot_confidence,
    )

    st.write(
        "Reason:",
        st.session_state.bot_reason,
    )

    st.caption(
        "Future V3 phases will add correlation, "
        "portfolio intelligence, Gold/Stocks data, "
        "news/event analysis and regime-aware routing."
    )

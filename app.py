"""
app.py

PRO AI QUANT TERMINAL V3.5

CRYPTO + METALS PARALLEL PAPER TRADING PLATFORM
WITH V3 CENTRAL CONTROL CENTER

Architecture
------------
CRYPTO_MAIN
    - Autonomous crypto scanner
    - Multi-timeframe confirmation
    - Maximum 1 Crypto position

METALS_MAIN
    - Gold XAUUSD
    - Silver XAGUSD
    - 15m / 1h / 4h MTF
    - ATR-based TP / SL
    - Maximum 1 Metals position

CONTROL CENTER
    - Persistent PostgreSQL-backed settings
    - Crypto / Metals controls
    - Risk configuration
    - Scanner configuration
    - System health
    - API readiness
    - Live execution hard lock

TOTAL MAX POSITIONS
    1 Crypto + 1 Metal

IMPORTANT
---------
PAPER TRADING ONLY
REAL ORDERS DISABLED
"""

from datetime import datetime, timezone

import pandas as pd
import streamlit as st


# ============================================================
# CORE SETTINGS
# ============================================================

from settings import (
    PAPER_TRADING,
    PAPER_BALANCE,
    RISK_PCT,
    POLL_SECONDS,
    MAX_DAILY_LOSS_PCT,
    SCAN_MARKETS,
    TEST_MODE,
)


# ============================================================
# CRYPTO DATA / ENGINE
# ============================================================

from market_data import (
    get_ticker,
    get_candles,
)

from scanner import (
    scan_markets,
    scanner_summary,
)

from strategy_engine import (
    confirm_scanner_setup,
)

from trade_engine import (
    monitor_open_position,
    open_approved_trade,
    get_current_price,
)


# ============================================================
# PAPER PORTFOLIO
# ============================================================

from paper_trader import (
    PaperTrader,
    CRYPTO_SLOT,
    METALS_SLOT,
)


# ============================================================
# V3 ANALYTICS
# ============================================================

from analytics_engine import (
    detect_market_regime,
    calculate_momentum,
    correlation_matrix,
    scanner_intelligence,
    trade_statistics,
)


# ============================================================
# V3 UI
# ============================================================

from ui_v3 import (
    inject_v3_css,
    render_header,
    render_market_strip,
    render_top_metrics,
    render_intelligence_cards,
    render_ai_core,
    render_scanner,
    render_trade_analytics,
)


# ============================================================
# METALS
# ============================================================

from metals_dashboard import (
    render_metals_dashboard,
)

from metals_trade_engine import (
    run_metals_cycle,
    get_metals_current_price,
)


# ============================================================
# V3 CONTROL CENTER
# ============================================================

from control_center_ui import (
    render_control_center,
)


# ============================================================
# PAGE CONFIG
# ============================================================

st.set_page_config(
    page_title="PRO AI QUANT TERMINAL V3.5",
    page_icon="⚡",
    layout="wide",
    initial_sidebar_state="collapsed",
)

inject_v3_css()


# ============================================================
# PLATFORM CONSTANTS
# ============================================================

METALS_SCAN_SECONDS = 300


NAV_ITEMS = [
    "Overview",
    "Crypto",
    "Metals",
    "Positions",
    "Scanner",
    "Analytics",
    "Settings",
]


# ============================================================
# SESSION STATE
# ============================================================

def init_state():

    defaults = {
        # Navigation
        "selected_asset_class": "Overview",
        "chart_pair": "BTCUSDT",

        # Legacy/runtime pause
        "bot_paused": False,

        # Crypto engine
        "crypto_scanner_results": [],
        "crypto_strategy_result": None,
        "crypto_status": "STARTING",
        "crypto_market": "—",
        "crypto_signal": "NO TRADE",
        "crypto_score": 0.0,
        "crypto_confidence": 0.0,
        "crypto_reason": "",

        # Metals engine
        "metals_status": "STARTING",
        "metals_scanner_results": [],
        "metals_best_setup": None,
        "metals_last_scan_at": None,

        # General
        "last_update": None,
        "bot_error": None,

        # Daily risk state
        "day_start_date": None,
        "day_start_balance": PAPER_BALANCE,
        "trading_paused_by_risk": False,
        "current_drawdown": 0.0,
    }

    for key, value in defaults.items():

        if key not in st.session_state:

            st.session_state[
                key
            ] = value

    if "paper_trader" not in st.session_state:

        st.session_state.paper_trader = (
            PaperTrader(
                starting_balance=PAPER_BALANCE
            )
        )


init_state()


# ============================================================
# HELPERS
# ============================================================

def utc_now():

    return datetime.now(
        timezone.utc
    )


def safe_float(
    value,
    default=0.0,
):

    try:

        if value is None:
            return default

        return float(
            value
        )

    except (
        TypeError,
        ValueError,
    ):

        return default


# ============================================================
# DAILY PORTFOLIO RISK
# ============================================================

def update_daily_risk():

    trader = (
        st.session_state.paper_trader
    )

    balance = (
        trader.get_balance()
    )

    today = (
        utc_now().date()
    )

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

    start_balance = safe_float(
        st.session_state.day_start_balance,
        PAPER_BALANCE,
    )

    drawdown = 0.0

    if start_balance > 0:

        drawdown = (
            (
                start_balance
                - balance
            )
            / start_balance
            * 100
        )

    st.session_state.current_drawdown = (
        drawdown
    )

    if (
        drawdown
        >= MAX_DAILY_LOSS_PCT
    ):

        st.session_state.trading_paused_by_risk = (
            True
        )

    return drawdown


# ============================================================
# CRYPTO MARKET ANALYTICS
# ============================================================

def get_regime_data(
    symbol,
):

    try:

        candles = get_candles(
            exchange="PUBLIC",
            symbol=symbol,
            timeframe_minutes=15,
            limit=100,
            api_key="",
            api_secret="",
            use_testnet=False,
        )

        if (
            candles is None
            or len(candles) < 50
        ):

            return {
                "regime": "UNKNOWN",
                "trend": "UNKNOWN",
                "atr_pct": 0.0,
                "momentum": 0.0,
            }

        regime = (
            detect_market_regime(
                candles
            )
        )

        momentum = (
            calculate_momentum(
                candles
            )
        )

        return {
            "regime":
                regime.get(
                    "regime",
                    "UNKNOWN",
                ),

            "trend":
                regime.get(
                    "trend",
                    "UNKNOWN",
                ),

            "atr_pct":
                safe_float(
                    regime.get(
                        "atr_pct"
                    )
                ),

            "momentum":
                safe_float(
                    momentum
                ),
        }

    except Exception as error:

        print(
            "[REGIME ERROR] "
            f"{symbol}: {error}",
            flush=True,
        )

        return {
            "regime": "UNKNOWN",
            "trend": "UNKNOWN",
            "atr_pct": 0.0,
            "momentum": 0.0,
        }


# ============================================================
# CRYPTO CORRELATION
# ============================================================

@st.cache_data(
    ttl=900,
    show_spinner=False,
)
def build_crypto_correlation():

    candle_map = {}

    for symbol in SCAN_MARKETS:

        try:

            candles = get_candles(
                exchange="PUBLIC",
                symbol=symbol,
                timeframe_minutes=15,
                limit=80,
                api_key="",
                api_secret="",
                use_testnet=False,
            )

            if candles is not None:

                candle_map[
                    symbol
                ] = candles

        except Exception:

            continue

    return correlation_matrix(
        candle_map
    )


# ============================================================
# CRYPTO BOT CYCLE
# ============================================================

def run_crypto_cycle():

    trader = (
        st.session_state.paper_trader
    )

    now = (
        utc_now()
    )

    try:

        # ----------------------------------------------------
        # MANAGE EXISTING CRYPTO POSITION FIRST
        # ----------------------------------------------------

        crypto_position = (
            trader.get_position(
                CRYPTO_SLOT
            )
        )

        if crypto_position:

            st.session_state.crypto_market = (
                crypto_position.get(
                    "symbol",
                    "—",
                )
            )

            result = (
                monitor_open_position(
                    trader
                )
            )

            if result is None:

                st.session_state.crypto_status = (
                    "POSITION MONITORING"
                )

            else:

                status = (
                    result.get(
                        "status"
                    )
                )

                if status == "CLOSED":

                    st.session_state.crypto_status = (
                        "TRADE CLOSED"
                    )

                    st.session_state.crypto_signal = (
                        "NO TRADE"
                    )

                    st.session_state.crypto_score = (
                        0.0
                    )

                    st.session_state.crypto_confidence = (
                        0.0
                    )

                elif status == "OPEN":

                    st.session_state.crypto_status = (
                        "POSITION OPEN"
                    )

                else:

                    st.session_state.crypto_status = (
                        status
                        or "POSITION MONITORING"
                    )

            return

        # ----------------------------------------------------
        # PAUSE
        # ----------------------------------------------------

        if st.session_state.bot_paused:

            st.session_state.crypto_status = (
                "PAUSED"
            )

            return

        # ----------------------------------------------------
        # DAILY LOSS PROTECTION
        # ----------------------------------------------------

        if (
            st.session_state
            .trading_paused_by_risk
        ):

            st.session_state.crypto_status = (
                "DAILY LOSS LIMIT HIT"
            )

            return

        # ----------------------------------------------------
        # MULTI-MARKET SCANNER
        # ----------------------------------------------------

        st.session_state.crypto_status = (
            f"SCANNING "
            f"{len(SCAN_MARKETS)} MARKETS"
        )

        results = (
            scan_markets()
        )

        st.session_state.crypto_scanner_results = (
            results
        )

        summary = scanner_summary(
            results
        )

        strongest = (
            summary.get(
                "strongest_market"
            )
        )

        best_setup = (
            summary.get(
                "best_setup"
            )
        )

        # ----------------------------------------------------
        # STRONGEST MARKET INFO
        # ----------------------------------------------------

        if strongest:

            st.session_state.crypto_market = (
                strongest.get(
                    "symbol",
                    "—",
                )
            )

            st.session_state.crypto_signal = (
                strongest.get(
                    "signal",
                    "NO TRADE",
                )
            )

            st.session_state.crypto_score = (
                safe_float(
                    strongest.get(
                        "score"
                    )
                )
            )

            st.session_state.crypto_reason = (
                strongest.get(
                    "reason",
                    "",
                )
            )

        # ----------------------------------------------------
        # NO SETUP
        # ----------------------------------------------------

        if best_setup is None:

            st.session_state.crypto_status = (
                "NO QUALIFYING TRADE"
            )

            st.session_state.crypto_confidence = (
                0.0
            )

            st.session_state.crypto_strategy_result = (
                None
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

        st.session_state.crypto_strategy_result = (
            confirmation
        )

        st.session_state.crypto_market = (
            best_setup.get(
                "symbol",
                "—",
            )
        )

        st.session_state.crypto_signal = (
            best_setup.get(
                "signal",
                "NO TRADE",
            )
        )

        st.session_state.crypto_score = (
            safe_float(
                best_setup.get(
                    "score"
                )
            )
        )

        st.session_state.crypto_confidence = (
            safe_float(
                confirmation.get(
                    "confidence"
                )
            )
        )

        st.session_state.crypto_reason = (
            confirmation.get(
                "reason",
                "",
            )
        )

        if not confirmation.get(
            "approved",
            False,
        ):

            st.session_state.crypto_status = (
                "WAITING FOR MTF CONFIRMATION"
            )

            return

        # ----------------------------------------------------
        # PAPER EXECUTION
        # ----------------------------------------------------

        execution = (
            open_approved_trade(
                trader=trader,
                setup=dict(
                    best_setup
                ),
            )
        )

        status = (
            execution.get(
                "status",
                "UNKNOWN",
            )
        )

        if status == "EXECUTED":

            st.session_state.crypto_status = (
                "PAPER TRADE OPENED"
            )

        elif status == "REJECTED":

            st.session_state.crypto_status = (
                "TRADE REJECTED BY RISK"
            )

        else:

            st.session_state.crypto_status = (
                "TRADE SKIPPED"
            )

    except Exception as error:

        st.session_state.crypto_status = (
            "ERROR"
        )

        st.session_state.bot_error = (
            f"Crypto: {error}"
        )

    finally:

        st.session_state.last_update = (
            now.isoformat()
        )


# ============================================================
# METALS SCAN TIMING
# ============================================================

def metals_scan_due():

    last_value = (
        st.session_state
        .metals_last_scan_at
    )

    if not last_value:

        return True

    try:

        last = (
            datetime.fromisoformat(
                last_value
            )
        )

        age = (
            utc_now()
            - last
        ).total_seconds()

        return (
            age
            >= METALS_SCAN_SECONDS
        )

    except Exception:

        return True


# ============================================================
# PARALLEL METALS CYCLE
# ============================================================

def run_parallel_metals_cycle():

    trader = (
        st.session_state.paper_trader
    )

    # --------------------------------------------------------
    # EXISTING METALS POSITION
    # --------------------------------------------------------

    metals_position = (
        trader.get_position(
            METALS_SLOT
        )
    )

    if metals_position:

        result = run_metals_cycle(
            trader=trader,
            risk_pct=1.0,
        )

        st.session_state.metals_status = (
            result.get(
                "status",
                "MANAGING_POSITION",
            )
        )

        return

    # --------------------------------------------------------
    # PAUSE
    # --------------------------------------------------------

    if st.session_state.bot_paused:

        st.session_state.metals_status = (
            "PAUSED"
        )

        return

    # --------------------------------------------------------
    # DAILY LOSS PROTECTION
    # --------------------------------------------------------

    if (
        st.session_state
        .trading_paused_by_risk
    ):

        st.session_state.metals_status = (
            "DAILY LOSS LIMIT HIT"
        )

        return

    # --------------------------------------------------------
    # WAIT UNTIL NEXT METALS SCAN
    # --------------------------------------------------------

    if not metals_scan_due():

        st.session_state.metals_status = (
            "WAITING FOR NEXT METALS SCAN"
        )

        return

    # --------------------------------------------------------
    # SCAN + EXECUTE
    # --------------------------------------------------------

    try:

        result = run_metals_cycle(
            trader=trader,
            risk_pct=1.0,
        )

        st.session_state.metals_last_scan_at = (
            utc_now().isoformat()
        )

        st.session_state.metals_status = (
            result.get(
                "status",
                "UNKNOWN",
            )
        )

        st.session_state.metals_scanner_results = (
            result.get(
                "scanner_results",
                [],
            )
        )

        st.session_state.metals_best_setup = (
            result.get(
                "best_setup"
            )
        )

    except Exception as error:

        st.session_state.metals_status = (
            "ERROR"
        )

        st.session_state.bot_error = (
            f"Metals: {error}"
        )


# ============================================================
# HEADER
# ============================================================

render_header(
    utc_now().strftime(
        "%H:%M:%S UTC"
    )
)


# ============================================================
# MAIN NAVIGATION
# ============================================================

selected_page = st.radio(
    "Navigation",
    NAV_ITEMS,
    key="selected_asset_class",
    horizontal=True,
    label_visibility="collapsed",
)


# ============================================================
# STABLE CRYPTO CHART
# ============================================================

@st.fragment
def stable_crypto_chart():

    if selected_page not in (
        "Overview",
        "Crypto",
    ):

        return

    left, right = (
        st.columns(
            [
                1,
                3,
            ]
        )
    )

    with left:

        symbol = st.selectbox(
            "Crypto Market",
            SCAN_MARKETS,
            key="chart_pair",
        )

        st.caption(
            "Isolated chart • "
            "does not refresh with bot cycle"
        )

    ticker = get_ticker(
        symbol=symbol,
        exchange="PUBLIC",
        api_key="",
        api_secret="",
        use_testnet=False,
    )

    last = 0.0
    change = 0.0
    high = 0.0
    low = 0.0

    if ticker:

        last = safe_float(
            ticker.get(
                "last"
            )
        )

        change = safe_float(
            ticker.get(
                "change_pct"
            )
        )

        high = safe_float(
            ticker.get(
                "high"
            )
        )

        low = safe_float(
            ticker.get(
                "low"
            )
        )

    with right:

        st.caption(
            f"{symbol} • "
            f"${last:,.6f} • "
            f"{change:+.2f}% • "
            f"H ${high:,.6f} • "
            f"L ${low:,.6f}"
        )

    base = (
        symbol.replace(
            "USDT",
            "",
        )
    )

    tv_symbol = (
        f"COINBASE:{base}USD"
    )

    chart_html = f"""
    <!DOCTYPE html>

    <html>

    <head>

        <meta charset="UTF-8">

        <style>

            html,
            body {{
                margin: 0;
                padding: 0;
                width: 100%;
                height: 100%;
                overflow: hidden;
                background: #070a0e;
            }}

            #tv {{
                width: 100%;
                height: 100%;
            }}

        </style>

    </head>

    <body>

        <div id="tv"></div>

        <script
            src="https://s3.tradingview.com/tv.js">
        </script>

        <script>

        new TradingView.widget({{

            "autosize": true,

            "symbol":
                "{tv_symbol}",

            "interval":
                "15",

            "timezone":
                "Etc/UTC",

            "theme":
                "dark",

            "style":
                "1",

            "locale":
                "en",

            "enable_publishing":
                false,

            "hide_side_toolbar":
                false,

            "allow_symbol_change":
                true,

            "save_image":
                false,

            "container_id":
                "tv",

            "backgroundColor":
                "#070a0e",

            "gridColor":
                "#151c23"

        }});

        </script>

    </body>

    </html>
    """

    st.iframe(
        chart_html,
        height=440,
        width="stretch",
    )


stable_crypto_chart()


# ============================================================
# QUICK ENGINE CONTROLS
# ============================================================

c1, c2, c3, c4 = (
    st.columns(
        [
            1,
            1,
            1,
            2,
        ]
    )
)


with c1:

    if st.session_state.bot_paused:

        if st.button(
            "▶ Resume Engines",
            width="stretch",
        ):

            st.session_state.bot_paused = (
                False
            )

            st.rerun()

    else:

        if st.button(
            "⏸ Pause Engines",
            width="stretch",
        ):

            st.session_state.bot_paused = (
                True
            )

            st.rerun()


with c2:

    if st.button(
        "🔎 Force Crypto Scan",
        width="stretch",
    ):

        run_crypto_cycle()

        st.rerun()


with c3:

    if st.button(
        "🥇 Force Metals Scan",
        width="stretch",
    ):

        st.session_state.metals_last_scan_at = (
            None
        )

        run_parallel_metals_cycle()

        st.rerun()


with c4:

    portfolio = (
        st.session_state
        .paper_trader
        .get_portfolio_snapshot()
    )

    st.caption(
        "PAPER ONLY • "
        f"OPEN POSITIONS "
        f"{portfolio['open_position_count']}/2 • "
        "1 CRYPTO + 1 METAL • "
        "REAL EXECUTION OFF"
    )


# ============================================================
# LIVE DUAL-ENGINE FRAGMENT
# ============================================================

@st.fragment(
    run_every=f"{POLL_SECONDS}s"
)
def live_engine():

    trader = (
        st.session_state.paper_trader
    )

    st.session_state.bot_error = (
        None
    )

    update_daily_risk()

    # --------------------------------------------------------
    # RUN BOTH ENGINES
    # --------------------------------------------------------

    if PAPER_TRADING:

        run_crypto_cycle()

        run_parallel_metals_cycle()

    # --------------------------------------------------------
    # ACCOUNT / POSITIONS
    # --------------------------------------------------------

    balance = (
        trader.get_balance()
    )

    crypto_position = (
        trader.get_position(
            CRYPTO_SLOT
        )
    )

    metals_position = (
        trader.get_position(
            METALS_SLOT
        )
    )

    history = (
        trader.get_trade_history()
    )

    drawdown = (
        st.session_state
        .current_drawdown
    )

    total_pnl = sum(
        safe_float(
            trade.get(
                "pnl"
            )
        )
        for trade in history
    )

    # --------------------------------------------------------
    # TOP STATUS
    # --------------------------------------------------------

    render_market_strip(
        scanner_count=len(
            SCAN_MARKETS
        ),

        bot_market=(
            st.session_state
            .crypto_market
        ),

        bot_status=(
            "CRYPTO: "
            f"{st.session_state.crypto_status}"
            " | METALS: "
            f"{st.session_state.metals_status}"
        ),

        poll_seconds=POLL_SECONDS,
    )

    render_top_metrics(
        equity=balance,

        realized_pnl=total_pnl,

        closed_trades=len(
            history
        ),

        drawdown=drawdown,

        ai_score=(
            st.session_state
            .crypto_score
        ),

        mtf_confidence=(
            st.session_state
            .crypto_confidence
        ),
    )

    # ========================================================
    # OVERVIEW
    # ========================================================

    if selected_page == "Overview":

        st.subheader(
            "⚡ Dual-Engine Status"
        )

        left, right = (
            st.columns(
                2
            )
        )

        # ----------------------------------------------------
        # CRYPTO ENGINE
        # ----------------------------------------------------

        with left:

            st.markdown(
                "### ₿ Crypto Engine"
            )

            st.metric(
                "Status",
                st.session_state
                .crypto_status,
            )

            st.metric(
                "AI Score",
                (
                    f"{st.session_state.crypto_score:+.1f}"
                ),
            )

            st.metric(
                "MTF Confidence",
                (
                    f"{st.session_state.crypto_confidence:.1f}%"
                ),
            )

            if crypto_position:

                st.success(
                    f"{crypto_position['symbol']} "
                    f"{crypto_position['side']} "
                    "is OPEN"
                )

            else:

                st.info(
                    "Crypto slot is available."
                )

        # ----------------------------------------------------
        # METALS ENGINE
        # ----------------------------------------------------

        with right:

            st.markdown(
                "### 🥇 Metals Engine"
            )

            st.metric(
                "Status",
                st.session_state
                .metals_status,
            )

            best = (
                st.session_state
                .metals_best_setup
            )

            if best:

                st.metric(
                    "Best Metal",
                    best.get(
                        "symbol",
                        "—",
                    ),
                )

                st.metric(
                    "Metal Signal",
                    best.get(
                        "signal",
                        "NO TRADE",
                    ),
                )

                st.metric(
                    "Metal MTF",
                    (
                        f"{safe_float(best.get('mtf_confidence')):.1f}%"
                    ),
                )

            if metals_position:

                st.success(
                    f"{metals_position['symbol']} "
                    f"{metals_position['side']} "
                    "is OPEN"
                )

            else:

                st.info(
                    "Metals slot is available."
                )


    # ========================================================
    # CRYPTO
    # ========================================================

    elif selected_page == "Crypto":

        if crypto_position:

            analytics_symbol = (
                crypto_position.get(
                    "symbol"
                )
            )

        elif (
            st.session_state.crypto_market
            not in (
                "",
                "—",
            )
        ):

            analytics_symbol = (
                st.session_state.crypto_market
            )

        else:

            analytics_symbol = (
                st.session_state.chart_pair
            )

        regime = (
            get_regime_data(
                analytics_symbol
            )
        )

        intelligence = (
            scanner_intelligence(
                st.session_state
                .crypto_scanner_results
            )
        )

        breadth = (
            intelligence.get(
                "breadth",
                {},
            )
        )

        render_intelligence_cards(
            regime=regime[
                "regime"
            ],

            trend=regime[
                "trend"
            ],

            atr_pct=regime[
                "atr_pct"
            ],

            momentum=regime[
                "momentum"
            ],

            bullish_pct=safe_float(
                breadth.get(
                    "bullish_pct"
                )
            ),

            bearish_pct=safe_float(
                breadth.get(
                    "bearish_pct"
                )
            ),
        )

        render_ai_core(
            score=(
                st.session_state
                .crypto_score
            ),

            mtf_confidence=(
                st.session_state
                .crypto_confidence
            ),

            regime=regime[
                "regime"
            ],

            trend=regime[
                "trend"
            ],

            risk_pct=RISK_PCT,

            position_state=(
                crypto_position.get(
                    "side"
                )
                if crypto_position
                else "FLAT"
            ),
        )

        if crypto_position:

            st.info(
                "Crypto scanner waits while "
                "CRYPTO_MAIN is occupied."
            )

        else:

            render_scanner(
                st.session_state
                .crypto_scanner_results
            )

        st.subheader(
            "🧬 Crypto Correlation"
        )

        corr = (
            build_crypto_correlation()
        )

        if (
            corr is not None
            and not corr.empty
        ):

            st.dataframe(
                corr.round(
                    2
                ),
                width="stretch",
            )

        else:

            st.info(
                "Correlation data is building."
            )


    # ========================================================
    # METALS
    # ========================================================

    elif selected_page == "Metals":

        # ----------------------------------------------------
        # LIVE GOLD / SILVER QUOTES
        # ----------------------------------------------------

        render_metals_dashboard()

        st.subheader(
            "🥇 Gold / Silver AI Scanner"
        )

        metals_results = (
            st.session_state
            .metals_scanner_results
        )

        if metals_results:

            rows = []

            for item in metals_results:

                rows.append(
                    {
                        "Market":
                            item.get(
                                "symbol"
                            ),

                        "Signal":
                            item.get(
                                "signal"
                            ),

                        "Score":
                            item.get(
                                "score"
                            ),

                        "MTF %":
                            item.get(
                                "mtf_confidence"
                            ),

                        "1H + 4H":
                            item.get(
                                "higher_tf_confirmed"
                            ),

                        "Approved":
                            item.get(
                                "approved"
                            ),

                        "Entry":
                            item.get(
                                "entry_price"
                            ),

                        "Reason":
                            item.get(
                                "reason"
                            ),
                    }
                )

            st.dataframe(
                pd.DataFrame(
                    rows
                ),
                width="stretch",
                hide_index=True,
            )

        else:

            if metals_position:

                st.info(
                    "METALS_MAIN position is "
                    "currently being managed."
                )

            else:

                st.info(
                    "Waiting for Metals scanner cycle."
                )

        if (
            st.session_state
            .metals_best_setup
        ):

            with st.expander(
                "Metals MTF Details"
            ):

                st.json(
                    st.session_state
                    .metals_best_setup
                )


    # ========================================================
    # POSITIONS
    # ========================================================

    elif selected_page == "Positions":

        st.subheader(
            "📌 Open Paper Positions"
        )

        positions = (
            trader.get_positions()
        )

        if positions:

            rows = []

            for position in positions:

                symbol = (
                    position.get(
                        "symbol"
                    )
                )

                if (
                    position.get(
                        "slot"
                    )
                    == METALS_SLOT
                ):

                    current = (
                        get_metals_current_price(
                            symbol
                        )
                    )

                else:

                    current = (
                        get_current_price(
                            symbol
                        )
                    )

                pnl_pct = 0.0

                if (
                    current
                    and position.get(
                        "entry_price"
                    )
                ):

                    entry = (
                        safe_float(
                            position.get(
                                "entry_price"
                            )
                        )
                    )

                    if (
                        position.get(
                            "side"
                        )
                        == "LONG"
                    ):

                        pnl_pct = (
                            (
                                current
                                - entry
                            )
                            / entry
                            * 100
                        )

                    else:

                        pnl_pct = (
                            (
                                entry
                                - current
                            )
                            / entry
                            * 100
                        )

                rows.append(
                    {
                        "Slot":
                            position.get(
                                "slot"
                            ),

                        "Asset":
                            position.get(
                                "asset_class"
                            ),

                        "Symbol":
                            symbol,

                        "Side":
                            position.get(
                                "side"
                            ),

                        "Entry":
                            position.get(
                                "entry_price"
                            ),

                        "Current":
                            current,

                        "PnL %":
                            round(
                                pnl_pct,
                                3,
                            ),

                        "TP":
                            position.get(
                                "take_profit"
                            ),

                        "SL":
                            position.get(
                                "stop_loss"
                            ),

                        "Quantity":
                            position.get(
                                "quantity"
                            ),

                        "Opened":
                            position.get(
                                "opened_at"
                            ),
                    }
                )

            st.dataframe(
                pd.DataFrame(
                    rows
                ),
                width="stretch",
                hide_index=True,
            )

        else:

            st.info(
                "No open paper positions."
            )


    # ========================================================
    # SCANNER
    # ========================================================

    elif selected_page == "Scanner":

        st.subheader(
            "🔎 Crypto Scanner"
        )

        render_scanner(
            st.session_state
            .crypto_scanner_results
        )

        st.subheader(
            "🥇 Metals Scanner"
        )

        if (
            st.session_state
            .metals_scanner_results
        ):

            metal_rows = []

            for item in (
                st.session_state
                .metals_scanner_results
            ):

                metal_rows.append(
                    {
                        "Market":
                            item.get(
                                "symbol"
                            ),

                        "Signal":
                            item.get(
                                "signal"
                            ),

                        "Score":
                            item.get(
                                "score"
                            ),

                        "MTF %":
                            item.get(
                                "mtf_confidence"
                            ),

                        "Approved":
                            item.get(
                                "approved"
                            ),

                        "Reason":
                            item.get(
                                "reason"
                            ),
                    }
                )

            st.dataframe(
                pd.DataFrame(
                    metal_rows
                ),
                width="stretch",
                hide_index=True,
            )

        else:

            st.info(
                "No Metals scanner result yet."
            )


    # ========================================================
    # ANALYTICS
    # ========================================================

    elif selected_page == "Analytics":

        statistics = (
            trade_statistics(
                history
            )
        )

        render_trade_analytics(
            statistics=statistics,
            trade_history=history,
        )

        crypto_history = (
            trader.get_trade_history(
                asset_class="CRYPTO"
            )
        )

        metal_history = (
            trader.get_trade_history(
                asset_class="METAL"
            )
        )

        a1, a2 = (
            st.columns(
                2
            )
        )

        with a1:

            st.metric(
                "Crypto Closed Trades",
                len(
                    crypto_history
                ),
            )

        with a2:

            st.metric(
                "Metals Closed Trades",
                len(
                    metal_history
                ),
            )


    # ========================================================
    # SETTINGS / V3 CONTROL CENTER
    # ========================================================

    elif selected_page == "Settings":

        render_control_center()


    # ========================================================
    # ERROR
    # ========================================================

    if st.session_state.bot_error:

        st.error(
            st.session_state.bot_error
        )


# ============================================================
# START LIVE ENGINE
# ============================================================

live_engine()


# ============================================================
# V3.8 METALS HISTORICAL BOOTSTRAP CONTROL
# ============================================================

try:
    from metals_bootstrap import (
        run_bootstrap_cycle,
        bootstrap_status,
        metals_bootstrap_health,
    )

    st.markdown("---")
    st.subheader("🧱 Metals Historical Bootstrap")

    bootstrap_health = metals_bootstrap_health()
    bootstrap_state = bootstrap_status()

    col1, col2, col3 = st.columns(3)

    with col1:
        st.metric(
            "Bootstrap Engine",
            "ONLINE"
            if bootstrap_health.get("ok")
            else "ERROR",
        )

    with col2:
        st.metric(
            "Requests Used / Hour",
            bootstrap_state.get(
                "requests_used_last_hour",
                0,
            ),
        )

    with col3:
        st.metric(
            "Hourly Safety Budget",
            bootstrap_state.get(
                "hourly_budget",
                0,
            ),
        )

    markets = bootstrap_state.get(
        "markets",
        {},
    )

    for symbol in (
        "XAUUSD",
        "XAGUSD",
    ):

        st.markdown(f"### {symbol}")

        tf_data = markets.get(
            symbol,
            {},
        )

        c1, c2, c3 = st.columns(3)

        for col, timeframe in zip(
            (c1, c2, c3),
            ("15m", "1h", "4h"),
        ):
            info = tf_data.get(
                timeframe,
                {},
            )

            with col:
                st.metric(
                    timeframe,
                    (
                        f"{info.get('candles', 0)}"
                        f"/{info.get('target', 60)}"
                    ),
                )

    if bootstrap_state.get(
        "ready",
        False,
    ):
        st.success(
            "Metals historical bootstrap is complete."
        )

    else:
        st.info(
            "Historical candles are still building. "
            "Run one safe bootstrap cycle at a time."
        )

        if st.button(
            "🚀 Run Safe Metals Bootstrap",
            use_container_width=True,
        ):
            with st.spinner(
                "Fetching real historical Gold/Silver OHLC..."
            ):
                result = run_bootstrap_cycle(
                    max_requests=4
                )

            if result.get("ok"):
                st.success(
                    "Bootstrap cycle completed."
                )
            else:
                st.error(
                    result.get(
                        "reason",
                        "Bootstrap cycle failed.",
                    )
                )

            st.rerun()

except Exception as bootstrap_ui_error:

    st.warning(
        "Metals bootstrap control unavailable: "
        f"{bootstrap_ui_error}"
    )

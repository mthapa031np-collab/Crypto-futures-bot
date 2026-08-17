"""
app.py

PRO AI QUANT TERMINAL V3
FLICKER DIAGNOSTIC VERSION

Purpose:
- Preserve existing V3 trading/backend architecture
- Temporarily disable TradingView
- Test whether embedded TradingView causes dim/bright flicker

IMPORTANT:
- PAPER TRADING ONLY
- REAL ORDERS DISABLED
- PostgreSQL paper state preserved
"""

from datetime import datetime, timezone

import streamlit as st

from settings import (
    PAPER_TRADING,
    PAPER_BALANCE,
    RISK_PCT,
    POLL_SECONDS,
    MAX_DAILY_LOSS_PCT,
    SCAN_MARKETS,
    TEST_MODE,
)

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
    manual_close_position,
    trade_management_snapshot,
    get_current_price,
)

from paper_trader import PaperTrader

from analytics_engine import (
    detect_market_regime,
    calculate_momentum,
    correlation_matrix,
    scanner_intelligence,
    trade_statistics,
    position_progress,
)

from asset_registry import (
    get_assets_by_class,
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
# PAGE CONFIG
# ============================================================

st.set_page_config(
    page_title="PRO AI QUANT TERMINAL V3",
    page_icon="⚡",
    layout="wide",
    initial_sidebar_state="collapsed",
)

inject_v3_css()


# ============================================================
# FLICKER DIAGNOSTIC MODE
# ============================================================

TRADINGVIEW_ENABLED = False


# ============================================================
# SESSION STATE
# ============================================================

def init_state():

    defaults = {
        "bot_paused": False,
        "scanner_results": [],
        "strategy_result": None,
        "bot_status": "STARTING",
        "bot_market": "—",
        "bot_signal": "NO TRADE",
        "bot_score": 0.0,
        "bot_confidence": 0.0,
        "bot_reason": "",
        "last_update": None,
        "bot_error": None,
        "selected_pair": "BTCUSDT",
        "day_start_date": None,
        "day_start_balance": PAPER_BALANCE,
        "trading_paused_by_risk": False,
        "current_drawdown": 0.0,
    }

    for key, value in defaults.items():

        if key not in st.session_state:
            st.session_state[key] = value

    if "paper_trader" not in st.session_state:

        st.session_state.paper_trader = PaperTrader(
            starting_balance=PAPER_BALANCE
        )


init_state()


# ============================================================
# DAILY RISK
# ============================================================

def update_daily_risk():

    trader = st.session_state.paper_trader

    balance = trader.get_balance()

    today = datetime.now(
        timezone.utc
    ).date()

    if st.session_state.day_start_date != today:

        st.session_state.day_start_date = today

        st.session_state.day_start_balance = balance

        st.session_state.trading_paused_by_risk = False

    start_balance = float(
        st.session_state.day_start_balance
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

    st.session_state.current_drawdown = drawdown

    if drawdown >= MAX_DAILY_LOSS_PCT:

        st.session_state.trading_paused_by_risk = True

    return drawdown


# ============================================================
# MARKET ANALYTICS
# ============================================================

def get_regime_data(symbol):

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

        if candles is None or len(candles) < 50:

            return {
                "regime": "UNKNOWN",
                "trend": "UNKNOWN",
                "atr_pct": 0.0,
                "momentum": 0.0,
            }

        regime = detect_market_regime(
            candles
        )

        momentum = calculate_momentum(
            candles
        )

        return {
            "regime": regime.get(
                "regime",
                "UNKNOWN",
            ),
            "trend": regime.get(
                "trend",
                "UNKNOWN",
            ),
            "atr_pct": float(
                regime.get(
                    "atr_pct",
                    0.0,
                )
            ),
            "momentum": float(
                momentum
            ),
        }

    except Exception as error:

        print(
            f"[REGIME ERROR] {symbol}: {error}",
            flush=True,
        )

        return {
            "regime": "UNKNOWN",
            "trend": "UNKNOWN",
            "atr_pct": 0.0,
            "momentum": 0.0,
        }


# ============================================================
# CORRELATION
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
# BOT CYCLE
# ============================================================

def run_bot_cycle():

    trader = st.session_state.paper_trader

    now = datetime.now(
        timezone.utc
    )

    try:

        st.session_state.bot_error = None

        update_daily_risk()

        # ----------------------------------------------------
        # EXISTING POSITION FIRST
        # ----------------------------------------------------

        position = trader.get_position()

        if position:

            symbol = position.get(
                "symbol",
                "—",
            )

            st.session_state.bot_market = symbol

            result = monitor_open_position(
                trader
            )

            if result.get("status") == "CLOSED":

                st.session_state.bot_status = (
                    "TRADE CLOSED"
                )

                st.session_state.bot_signal = (
                    "NO TRADE"
                )

                st.session_state.bot_score = 0.0

                st.session_state.bot_confidence = 0.0

            elif result.get("status") == "OPEN":

                st.session_state.bot_status = (
                    "POSITION OPEN"
                )

            else:

                st.session_state.bot_status = (
                    result.get(
                        "status",
                        "POSITION MONITORING",
                    )
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
        # DAILY LOSS PROTECTION
        # ----------------------------------------------------

        if st.session_state.trading_paused_by_risk:

            st.session_state.bot_status = (
                "DAILY LOSS LIMIT HIT"
            )

            st.session_state.last_update = (
                now.isoformat()
            )

            return

        # ----------------------------------------------------
        # MULTI-MARKET SCANNER
        # ----------------------------------------------------

        st.session_state.bot_status = (
            f"SCANNING {len(SCAN_MARKETS)} MARKETS"
        )

        results = scan_markets()

        st.session_state.scanner_results = results

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
                    0.0,
                )
            )

            st.session_state.bot_reason = (
                strongest.get(
                    "reason",
                    "",
                )
            )

        if best_setup is None:

            st.session_state.bot_status = (
                "NO QUALIFYING TRADE"
            )

            st.session_state.bot_confidence = 0.0

            st.session_state.strategy_result = None

            st.session_state.last_update = (
                now.isoformat()
            )

            return

        # ----------------------------------------------------
        # MTF CONFIRMATION
        # ----------------------------------------------------

        confirmation = confirm_scanner_setup(
            best_setup
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
                0.0,
            )
        )

        st.session_state.bot_confidence = float(
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
        # PAPER EXECUTION
        # ----------------------------------------------------

        execution_result = open_approved_trade(
            trader=trader,
            setup=dict(
                best_setup
            ),
        )

        status = execution_result.get(
            "status",
            "UNKNOWN",
        )

        if status == "EXECUTED":

            st.session_state.bot_status = (
                "PAPER TRADE OPENED"
            )

        elif status == "REJECTED":

            st.session_state.bot_status = (
                "TRADE REJECTED BY RISK"
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

        st.session_state.bot_error = str(
            error
        )

        st.session_state.last_update = (
            now.isoformat()
        )


# ============================================================
# HEADER
# ============================================================

utc_time = datetime.now(
    timezone.utc
).strftime(
    "%H:%M:%S UTC"
)

render_header(
    utc_time
)


# ============================================================
# NAVIGATION
# ============================================================

nav_left, nav_right = st.columns(
    [
        2.2,
        1,
    ]
)

with nav_left:

    selected_asset_class = st.radio(
        "Asset Class",
        [
            "Overview",
            "Crypto",
            "Stocks",
            "Metals",
            "Indices",
            "ETFs",
            "Portfolio",
            "AI Intelligence",
        ],
        horizontal=True,
        label_visibility="collapsed",
    )


with nav_right:

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

    st.session_state.selected_pair = selected_pair


# ============================================================
# TRADINGVIEW FLICKER TEST
# ============================================================

if selected_asset_class in (
    "Overview",
    "Crypto",
):

    ticker = get_ticker(
        symbol=selected_pair,
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

        last = float(
            ticker.get(
                "last",
                0.0,
            )
        )

        change = float(
            ticker.get(
                "change_pct",
                0.0,
            )
        )

        high = float(
            ticker.get(
                "high",
                0.0,
            )
        )

        low = float(
            ticker.get(
                "low",
                0.0,
            )
        )

    st.caption(
        f"{selected_pair}  •  "
        f"${last:,.6f}  •  "
        f"{change:+.2f}%  •  "
        f"High ${high:,.6f}  •  "
        f"Low ${low:,.6f}"
    )

    if not TRADINGVIEW_ENABLED:

        st.info(
            "🧪 V3 FLICKER TEST ACTIVE — "
            "TradingView chart is temporarily disabled. "
            "Please keep this page open for 1–2 minutes "
            "and check whether the dim/bright effect stops."
        )


# ============================================================
# CONTROLS
# ============================================================

control_1, control_2, control_3, control_4 = (
    st.columns(
        [
            1,
            1,
            1,
            2,
        ]
    )
)

with control_1:

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


with control_2:

    if st.button(
        "🔎 Force Scan",
        width="stretch",
    ):

        run_bot_cycle()

        st.rerun()


with control_3:

    current_position = (
        st.session_state.paper_trader
        .get_position()
    )

    if st.button(
        "✖ Close Paper Trade",
        disabled=(
            current_position is None
        ),
        width="stretch",
    ):

        result = manual_close_position(
            st.session_state.paper_trader
        )

        if result.get(
            "status"
        ) == "CLOSED":

            st.success(
                "Paper position closed."
            )

        else:

            st.warning(
                str(result)
            )

        st.rerun()


with control_4:

    management = trade_management_snapshot(
        st.session_state.paper_trader
    )

    st.caption(
        "PAPER ONLY  •  "
        f"Risk {management['risk_pct']}%  •  "
        f"TP {management['active_tp_pct']}%  •  "
        f"SL {management['active_sl_pct']}%  •  "
        f"TEST MODE {TEST_MODE}"
    )


# ============================================================
# DYNAMIC V3
# ============================================================

@st.fragment(
    run_every=f"{POLL_SECONDS}s"
)
def dynamic_v3_terminal():

    if PAPER_TRADING:

        run_bot_cycle()

    trader = (
        st.session_state.paper_trader
    )

    balance = trader.get_balance()

    position = trader.get_position()

    history = trader.get_trade_history()

    drawdown = update_daily_risk()

    total_pnl = sum(
        float(
            trade.get(
                "pnl",
                0.0,
            )
        )
        for trade in history
    )

    # --------------------------------------------------------
    # MARKET STRIP
    # --------------------------------------------------------

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
        poll_seconds=POLL_SECONDS,
    )

    # --------------------------------------------------------
    # TOP METRICS
    # --------------------------------------------------------

    render_top_metrics(
        equity=balance,
        realized_pnl=total_pnl,
        closed_trades=len(
            history
        ),
        drawdown=drawdown,
        ai_score=float(
            st.session_state.bot_score
        ),
        mtf_confidence=float(
            st.session_state.bot_confidence
        ),
    )

    # --------------------------------------------------------
    # ACTIVE ANALYTICS SYMBOL
    # --------------------------------------------------------

    if position:

        analytics_symbol = position.get(
            "symbol"
        )

    elif (
        st.session_state.bot_market
        not in (
            "",
            "—",
        )
    ):

        analytics_symbol = (
            st.session_state.bot_market
        )

    else:

        analytics_symbol = (
            selected_pair
        )

    # --------------------------------------------------------
    # REGIME
    # --------------------------------------------------------

    regime_data = get_regime_data(
        analytics_symbol
    )

    intelligence = scanner_intelligence(
        st.session_state.scanner_results
    )

    breadth = intelligence.get(
        "breadth",
        {},
    )

    render_intelligence_cards(
        regime=regime_data[
            "regime"
        ],
        trend=regime_data[
            "trend"
        ],
        atr_pct=regime_data[
            "atr_pct"
        ],
        momentum=regime_data[
            "momentum"
        ],
        bullish_pct=float(
            breadth.get(
                "bullish_pct",
                0.0,
            )
        ),
        bearish_pct=float(
            breadth.get(
                "bearish_pct",
                0.0,
            )
        ),
    )

    # --------------------------------------------------------
    # OVERVIEW / CRYPTO
    # --------------------------------------------------------

    if selected_asset_class in (
        "Overview",
        "Crypto",
    ):

        left_ai, right_ai = st.columns(
            [
                1.15,
                1,
            ]
        )

        with left_ai:

            render_ai_core(
                score=float(
                    st.session_state.bot_score
                ),
                mtf_confidence=float(
                    st.session_state.bot_confidence
                ),
                regime=regime_data[
                    "regime"
                ],
                trend=regime_data[
                    "trend"
                ],
                risk_pct=RISK_PCT,
                position_state=(
                    position.get(
                        "side",
                        "OPEN",
                    )
                    if position
                    else "FLAT"
                ),
            )

        with right_ai:

            st.subheader(
                "🧠 AI Decision State"
            )

            st.code(
                f"""
MARKET:
{st.session_state.bot_market}

STATUS:
{st.session_state.bot_status}

SIGNAL:
{st.session_state.bot_signal}

AI SCORE:
{st.session_state.bot_score}

MTF CONFIDENCE:
{st.session_state.bot_confidence}%

REGIME:
{regime_data['regime']}

TREND:
{regime_data['trend']}

ATR:
{regime_data['atr_pct']}%

MOMENTUM:
{regime_data['momentum']}%

REASON:
{st.session_state.bot_reason}

LAST UPDATE:
{st.session_state.last_update}
""",
                language="text",
            )

        # Scanner only shown when no position is open.
        if position:

            st.info(
                "Scanner waits while the active "
                "paper position is managed."
            )

        else:

            render_scanner(
                st.session_state.scanner_results
            )

        # ----------------------------------------------------
        # CORRELATION
        # ----------------------------------------------------

        st.subheader(
            "🧬 Crypto Correlation Matrix"
        )

        corr = build_crypto_correlation()

        if (
            corr is not None
            and not corr.empty
        ):

            st.dataframe(
                corr.round(2),
                width="stretch",
            )

        else:

            st.info(
                "Correlation data is building."
            )

    # --------------------------------------------------------
    # POSITION
    # --------------------------------------------------------

    current_price = None
    progress = None

    if position:

        current_price = get_current_price(
            position.get(
                "symbol"
            )
        )

        if current_price is not None:

            progress = position_progress(
                position,
                current_price,
            )

    render_position(
        position=position,
        progress=progress,
    )

    # --------------------------------------------------------
    # TRADE ANALYTICS
    # --------------------------------------------------------

    stats = trade_statistics(
        history
    )

    render_trade_analytics(
        statistics=stats,
        trade_history=history,
    )

    # --------------------------------------------------------
    # STOCKS
    # --------------------------------------------------------

    if selected_asset_class == "Stocks":

        stocks = get_assets_by_class(
            ASSET_STOCK
        )

        render_future_module(
            "STOCK MARKET ENGINE",
            (
                f"Registered assets: "
                f"{', '.join(stocks)}"
                "<br><br>"
                "Stock-market data and execution "
                "remain disabled during V3 integration."
            ),
        )

    # --------------------------------------------------------
    # METALS
    # --------------------------------------------------------

    elif selected_asset_class == "Metals":

        metals = get_assets_by_class(
            ASSET_METAL
        )

        render_future_module(
            "METALS ENGINE",
            (
                f"Registered assets: "
                f"{', '.join(metals)}"
                "<br><br>"
                "Gold and Silver are registered. "
                "Dedicated metals data/risk engine "
                "will be connected later."
            ),
        )

    # --------------------------------------------------------
    # INDICES
    # --------------------------------------------------------

    elif selected_asset_class == "Indices":

        indices = get_assets_by_class(
            ASSET_INDEX
        )

        render_future_module(
            "INDEX INTELLIGENCE",
            (
                f"Registered indices: "
                f"{', '.join(indices)}"
            ),
        )

    # --------------------------------------------------------
    # ETFs
    # --------------------------------------------------------

    elif selected_asset_class == "ETFs":

        etfs = get_assets_by_class(
            ASSET_ETF
        )

        render_future_module(
            "ETF ENGINE",
            (
                f"Registered ETFs: "
                f"{', '.join(etfs)}"
            ),
        )

    # --------------------------------------------------------
    # PORTFOLIO
    # --------------------------------------------------------

    elif selected_asset_class == "Portfolio":

        render_future_module(
            "PORTFOLIO INTELLIGENCE",
            (
                "Future portfolio layer for "
                "multi-position exposure, "
                "correlation-adjusted risk and "
                "cross-asset allocation."
            ),
        )

    # --------------------------------------------------------
    # AI INTELLIGENCE
    # --------------------------------------------------------

    elif selected_asset_class == "AI Intelligence":

        render_future_module(
            "AI INTELLIGENCE LAYER",
            (
                "Scanner score, multi-timeframe "
                "confirmation, market regime, "
                "momentum, volatility and risk "
                "intelligence."
            ),
        )

    # --------------------------------------------------------
    # ERROR
    # --------------------------------------------------------

    if st.session_state.bot_error:

        st.error(
            st.session_state.bot_error
        )


dynamic_v3_terminal()

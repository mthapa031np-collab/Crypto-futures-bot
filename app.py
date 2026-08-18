"""
app.py

PRO AI QUANT TERMINAL V5.0
Institutional multi-asset paper-trading terminal.

Design goals
------------
- Preserve existing crypto + metals paper engines.
- Preserve PostgreSQL-backed PaperTrader state.
- Preserve Metals bootstrap / OHLC architecture.
- Run Metals bootstrap inside the EXISTING Render Web Service.
- No additional paid Render Background Worker is required.
- Keep all real execution hard-disabled.
- Provide a dense, iPad-friendly institutional quant UI.

IMPORTANT
---------
PAPER TRADING ONLY.
REAL ORDERS DISABLED.
"""

from __future__ import annotations

import html as html_lib
import os
import threading
import time
from datetime import datetime, timezone
from typing import Any, Dict, Optional

import pandas as pd
import psycopg
import streamlit as st

# ============================================================
# PAGE CONFIG — must be the first Streamlit command
# ============================================================

st.set_page_config(
    page_title="PRO AI QUANT TERMINAL V5",
    page_icon="⚡",
    layout="wide",
    initial_sidebar_state="collapsed",
)

# ============================================================
# EXISTING PROJECT CONTRACTS
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

from market_data import get_ticker, get_candles
from scanner import scan_markets, scanner_summary
from strategy_engine import confirm_scanner_setup
from trade_engine import monitor_open_position, open_approved_trade, get_current_price
from paper_trader import PaperTrader, CRYPTO_SLOT, METALS_SLOT
from analytics_engine import (
    detect_market_regime,
    calculate_momentum,
    correlation_matrix,
    scanner_intelligence,
    trade_statistics,
)
from metals_dashboard import render_metals_dashboard
from metals_trade_engine import run_metals_cycle, get_metals_current_price
from control_center_ui import render_control_center

# ============================================================
# OPTIONAL SYSTEM HEALTH ADAPTER
# ============================================================

SYSTEM_HEALTH_AVAILABLE = False
_health_module = None

try:
    import system_health as _health_module
    SYSTEM_HEALTH_AVAILABLE = True
except Exception as _health_import_error:
    print(
        "[V5 HEALTH] system_health unavailable: "
        f"{_health_import_error}",
        flush=True,
    )

# ============================================================
# PLATFORM CONSTANTS
# ============================================================

PLATFORM_VERSION = "V5.0"
PAPER_ONLY = True
REAL_EXECUTION_ENABLED = False
METALS_SCAN_SECONDS = 300
CORE_TICKERS = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "XRPUSDT"]
NAV_ITEMS = [
    "Command",
    "Crypto",
    "Metals",
    "Positions",
    "Scanner",
    "Risk",
    "Analytics",
    "Settings",
]

# ============================================================
# V5 INSTITUTIONAL CSS
# ============================================================

def inject_v5_css() -> None:
    st.markdown(
        """
        <style>
        :root {
            --bg0:#05080c;
            --bg1:#080d12;
            --bg2:#0b1118;
            --line:#202b35;
            --line2:#2b3946;
            --text:#d8e0e7;
            --muted:#71808e;
            --green:#4bd69e;
            --red:#ef7984;
            --amber:#e5b84f;
            --blue:#79a9ff;
        }

        html, body, [class*="css"] {
            font-family: Inter, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
        }

        .stApp {
            background:
                radial-gradient(circle at 50% -10%, rgba(46,76,107,.12), transparent 27%),
                var(--bg0);
            color:var(--text);
        }

        .block-container {
            max-width: 1900px;
            padding-top:.55rem;
            padding-bottom:2.5rem;
            padding-left:.8rem;
            padding-right:.8rem;
        }

        #MainMenu, footer {visibility:hidden;}

        ::-webkit-scrollbar {width:7px;height:7px;}
        ::-webkit-scrollbar-track {background:#070b10;}
        ::-webkit-scrollbar-thumb {background:#283642;border-radius:10px;}

        .q-header {
            border:1px solid var(--line2);
            background:linear-gradient(180deg,#10171f,#080c11);
            padding:10px 13px;
            margin-bottom:6px;
            box-shadow:0 9px 28px rgba(0,0,0,.28);
        }

        .q-header-row {display:flex;justify-content:space-between;align-items:center;gap:12px;}
        .q-brand {display:flex;align-items:center;gap:10px;}
        .q-mark {width:17px;height:17px;background:var(--amber);box-shadow:0 0 16px rgba(229,184,79,.24);}
        .q-title {font-size:14px;font-weight:850;letter-spacing:1.5px;color:#eef3f7;}
        .q-sub {font-size:7.5px;letter-spacing:1.25px;color:#687887;margin-top:2px;}
        .q-status {text-align:right;font-family:ui-monospace,SFMono-Regular,Menlo,monospace;}
        .q-online {color:var(--green);font-size:9px;font-weight:800;}
        .q-clock {color:#8d9ba7;font-size:8px;margin-top:2px;}

        .q-strip {
            border:1px solid #1b252e;
            background:#070b10;
            padding:6px 9px;
            margin-bottom:7px;
            overflow-x:auto;
            white-space:nowrap;
            font-family:ui-monospace,SFMono-Regular,Menlo,monospace;
            font-size:8px;
            letter-spacing:.35px;
            color:#85939f;
        }
        .q-strip span {margin-right:18px;}
        .pos {color:var(--green)!important;}
        .neg {color:var(--red)!important;}
        .warn {color:var(--amber)!important;}
        .info {color:var(--blue)!important;}

        .section-title {
            margin:10px 0 5px 1px;
            color:#81909d;
            font-size:8px;
            letter-spacing:1.2px;
            text-transform:uppercase;
            font-family:ui-monospace,SFMono-Regular,Menlo,monospace;
            font-weight:800;
        }

        .panel {
            border:1px solid var(--line);
            background:linear-gradient(180deg,#0b1117,#070b10);
            padding:10px;
            min-height:84px;
        }
        .panel-title {
            color:#7b8a98;
            font-size:7.5px;
            letter-spacing:1px;
            text-transform:uppercase;
            font-family:ui-monospace,SFMono-Regular,Menlo,monospace;
            margin-bottom:7px;
        }

        .kpi {
            border:1px solid var(--line);
            background:#080d12;
            padding:8px 9px;
            min-height:68px;
        }
        .kpi-label {
            color:#697987;
            font-size:7px;
            letter-spacing:.9px;
            text-transform:uppercase;
            font-family:ui-monospace,SFMono-Regular,Menlo,monospace;
        }
        .kpi-value {
            color:#e9eef2;
            font-size:17px;
            font-weight:850;
            margin-top:4px;
            font-family:ui-monospace,SFMono-Regular,Menlo,monospace;
        }
        .kpi-sub {color:#62717d;font-size:7.5px;margin-top:2px;}

        .badge {
            display:inline-block;
            padding:3px 6px;
            margin:0 4px 4px 0;
            border:1px solid #2a3742;
            background:#0a1015;
            color:#8f9ca7;
            font-size:7.5px;
            font-family:ui-monospace,SFMono-Regular,Menlo,monospace;
        }
        .badge-green {color:var(--green);border-color:#285d4a;background:rgba(45,119,91,.10);}
        .badge-red {color:var(--red);border-color:#693a41;background:rgba(132,55,65,.10);}
        .badge-amber {color:var(--amber);border-color:#6c5728;background:rgba(140,105,27,.09);}
        .badge-blue {color:var(--blue);border-color:#365070;background:rgba(53,86,128,.10);}

        div[data-testid="stMetric"] {
            border:1px solid var(--line);
            background:#080d12;
            padding:8px 10px;
            border-radius:0;
        }
        div[data-testid="stMetricLabel"] {color:#71818f;font-size:9px;}
        div[data-testid="stMetricValue"] {font-family:ui-monospace,SFMono-Regular,Menlo,monospace;}
        div[data-testid="stDataFrame"] {border:1px solid var(--line);}
        div[data-baseweb="select"] > div {background:#080d12;border-color:#24313b;}

        .stButton > button {
            width:100%;
            min-height:33px;
            border-radius:0;
            border:1px solid #293742;
            background:linear-gradient(180deg,#111922,#0a1016);
            color:#cbd4db;
            font-size:9px;
        }
        .stButton > button:hover {border-color:#4a6277;color:white;}
        div[role="radiogroup"] {background:#070b10;border:1px solid #1e2932;padding:3px 6px;border-radius:0;}

        @media (max-width:1050px) {
            .block-container {padding-left:.45rem;padding-right:.45rem;}
            .q-title {font-size:12px;}
            .q-sub {display:none;}
            .kpi-value {font-size:13px;}
            .q-strip {font-size:7px;}
        }
        </style>
        """,
        unsafe_allow_html=True,
    )

inject_v5_css()

# ============================================================
# SESSION STATE
# ============================================================

def init_state() -> None:
    defaults = {
        "selected_asset_class": "Command",
        "chart_pair": "BTCUSDT",
        "bot_paused": False,
        "crypto_scanner_results": [],
        "crypto_strategy_result": None,
        "crypto_status": "STARTING",
        "crypto_market": "—",
        "crypto_signal": "NO TRADE",
        "crypto_score": 0.0,
        "crypto_confidence": 0.0,
        "crypto_reason": "",
        "metals_status": "STARTING",
        "metals_scanner_results": [],
        "metals_best_setup": None,
        "metals_last_scan_at": None,
        "last_update": None,
        "bot_error": None,
        "day_start_date": None,
        "day_start_balance": PAPER_BALANCE,
        "trading_paused_by_risk": False,
        "current_drawdown": 0.0,
    }

    for key, value in defaults.items():
        if key not in st.session_state:
            st.session_state[key] = value

    if "paper_trader" not in st.session_state:
        st.session_state.paper_trader = PaperTrader(starting_balance=PAPER_BALANCE)

init_state()

# ============================================================
# GENERIC HELPERS
# ============================================================

def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def safe_float(value: Any, default: float = 0.0) -> float:
    try:
        if value is None:
            return default
        number = float(value)
        return default if number != number else number
    except (TypeError, ValueError):
        return default


def safe_int(value: Any, default: int = 0) -> int:
    try:
        if value is None:
            return default
        return int(value)
    except (TypeError, ValueError):
        return default


def escape(value: Any) -> str:
    return html_lib.escape(str(value if value is not None else ""))


def render_section(text: str) -> None:
    st.markdown(f'<div class="section-title">{escape(text)}</div>', unsafe_allow_html=True)


def render_kpi(label: str, value: Any, sub: str = "") -> None:
    st.markdown(
        f"""
        <div class="kpi">
            <div class="kpi-label">{escape(label)}</div>
            <div class="kpi-value">{escape(value)}</div>
            <div class="kpi-sub">{escape(sub)}</div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def badge_class(text: Any) -> str:
    value = str(text or "").upper()
    if any(x in value for x in ("ERROR", "OFFLINE", "REJECT", "LOSS", "BLOCK", "DISABLED")):
        return "badge-red"
    if any(x in value for x in ("READY", "ONLINE", "OPEN", "EXECUTED", "ACTIVE", "HEALTHY")):
        return "badge-green"
    if any(x in value for x in ("WAIT", "WARM", "RATE", "PAUSE", "START", "PAPER")):
        return "badge-amber"
    return "badge-blue"


def badge(text: Any) -> str:
    return f'<span class="badge {badge_class(text)}">{escape(text)}</span>'

# ============================================================
# HEALTH COMPATIBILITY WRAPPERS
# ============================================================

def _health_call(name: str, *args: Any, **kwargs: Any) -> Any:
    if not SYSTEM_HEALTH_AVAILABLE or _health_module is None:
        return None
    fn = getattr(_health_module, name, None)
    if not callable(fn):
        return None
    try:
        return fn(*args, **kwargs)
    except Exception as error:
        print(f"[V5 HEALTH] {name} failed: {error}", flush=True)
        return None


def safe_system_health() -> Dict[str, Any]:
    for name in ("get_system_health_snapshot", "system_health_snapshot", "get_health_snapshot"):
        result = _health_call(name)
        if isinstance(result, dict):
            return result
    return {
        "overall_status": "UNAVAILABLE" if not SYSTEM_HEALTH_AVAILABLE else "UNKNOWN",
        "safe_to_trade": False,
        "components": {},
    }


def publish_web_heartbeat() -> None:
    if not SYSTEM_HEALTH_AVAILABLE or _health_module is None:
        return
    component = getattr(_health_module, "COMPONENT_WEB", "WEB")
    _health_call(
        "heartbeat",
        component,
        message="V5 Streamlit terminal alive.",
        payload={
            "version": PLATFORM_VERSION,
            "paper_only": True,
            "real_execution": False,
        },
    )

# ============================================================
# DAILY PORTFOLIO RISK
# ============================================================

def update_daily_risk() -> float:
    trader = st.session_state.paper_trader
    balance = trader.get_balance()
    today = utc_now().date()

    if st.session_state.day_start_date != today:
        st.session_state.day_start_date = today
        st.session_state.day_start_balance = balance
        st.session_state.trading_paused_by_risk = False

    start_balance = safe_float(st.session_state.day_start_balance, PAPER_BALANCE)
    drawdown = 0.0
    if start_balance > 0:
        drawdown = (start_balance - balance) / start_balance * 100

    st.session_state.current_drawdown = drawdown
    if drawdown >= MAX_DAILY_LOSS_PCT:
        st.session_state.trading_paused_by_risk = True

    return drawdown

# ============================================================
# CRYPTO ANALYTICS
# ============================================================

def get_regime_data(symbol: str) -> Dict[str, Any]:
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
            return {"regime": "UNKNOWN", "trend": "UNKNOWN", "atr_pct": 0.0, "momentum": 0.0}

        regime = detect_market_regime(candles)
        momentum = calculate_momentum(candles)
        return {
            "regime": regime.get("regime", "UNKNOWN"),
            "trend": regime.get("trend", "UNKNOWN"),
            "atr_pct": safe_float(regime.get("atr_pct")),
            "momentum": safe_float(momentum),
        }
    except Exception as error:
        print(f"[V5 REGIME ERROR] {symbol}: {error}", flush=True)
        return {"regime": "UNKNOWN", "trend": "UNKNOWN", "atr_pct": 0.0, "momentum": 0.0}


@st.cache_data(ttl=900, show_spinner=False)
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
                candle_map[symbol] = candles
        except Exception:
            continue
    return correlation_matrix(candle_map)


@st.cache_data(ttl=20, show_spinner=False)
def get_market_strip() -> list[Dict[str, Any]]:
    output = []
    for symbol in CORE_TICKERS:
        try:
            ticker = get_ticker(
                symbol=symbol,
                exchange="PUBLIC",
                api_key="",
                api_secret="",
                use_testnet=False,
            )
            output.append(
                {
                    "symbol": symbol,
                    "last": safe_float(ticker.get("last") if ticker else 0),
                    "change": safe_float(ticker.get("change_pct") if ticker else 0),
                }
            )
        except Exception:
            output.append({"symbol": symbol, "last": 0.0, "change": 0.0})
    return output

# ============================================================
# CRYPTO ENGINE
# ============================================================

def run_crypto_cycle() -> None:
    trader = st.session_state.paper_trader
    now = utc_now()

    try:
        crypto_position = trader.get_position(CRYPTO_SLOT)

        if crypto_position:
            st.session_state.crypto_market = crypto_position.get("symbol", "—")
            result = monitor_open_position(trader)
            if result is None:
                st.session_state.crypto_status = "POSITION MONITORING"
            else:
                status = result.get("status")
                if status == "CLOSED":
                    st.session_state.crypto_status = "TRADE CLOSED"
                    st.session_state.crypto_signal = "NO TRADE"
                    st.session_state.crypto_score = 0.0
                    st.session_state.crypto_confidence = 0.0
                elif status == "OPEN":
                    st.session_state.crypto_status = "POSITION OPEN"
                else:
                    st.session_state.crypto_status = status or "POSITION MONITORING"
            return

        if st.session_state.bot_paused:
            st.session_state.crypto_status = "PAUSED"
            return

        if st.session_state.trading_paused_by_risk:
            st.session_state.crypto_status = "DAILY LOSS LIMIT HIT"
            return

        st.session_state.crypto_status = f"SCANNING {len(SCAN_MARKETS)} MARKETS"
        results = scan_markets()
        st.session_state.crypto_scanner_results = results
        summary = scanner_summary(results)
        strongest = summary.get("strongest_market")
        best_setup = summary.get("best_setup")

        if strongest:
            st.session_state.crypto_market = strongest.get("symbol", "—")
            st.session_state.crypto_signal = strongest.get("signal", "NO TRADE")
            st.session_state.crypto_score = safe_float(strongest.get("score"))
            st.session_state.crypto_reason = strongest.get("reason", "")

        if best_setup is None:
            st.session_state.crypto_status = "NO QUALIFYING TRADE"
            st.session_state.crypto_confidence = 0.0
            st.session_state.crypto_strategy_result = None
            return

        confirmation = confirm_scanner_setup(best_setup)
        st.session_state.crypto_strategy_result = confirmation
        st.session_state.crypto_market = best_setup.get("symbol", "—")
        st.session_state.crypto_signal = best_setup.get("signal", "NO TRADE")
        st.session_state.crypto_score = safe_float(best_setup.get("score"))
        st.session_state.crypto_confidence = safe_float(confirmation.get("confidence"))
        st.session_state.crypto_reason = confirmation.get("reason", "")

        if not confirmation.get("approved", False):
            st.session_state.crypto_status = "WAITING FOR MTF CONFIRMATION"
            return

        execution = open_approved_trade(trader=trader, setup=dict(best_setup))
        status = execution.get("status", "UNKNOWN")
        if status == "EXECUTED":
            st.session_state.crypto_status = "PAPER TRADE OPENED"
        elif status == "REJECTED":
            st.session_state.crypto_status = "TRADE REJECTED BY RISK"
        else:
            st.session_state.crypto_status = "TRADE SKIPPED"

    except Exception as error:
        st.session_state.crypto_status = "ERROR"
        st.session_state.bot_error = f"Crypto: {error}"
        print(f"[CRYPTO ENGINE ERROR] {error}", flush=True)
    finally:
        st.session_state.last_update = now.isoformat()

# ============================================================
# METALS ENGINE
# ============================================================

def metals_scan_due() -> bool:
    last_value = st.session_state.metals_last_scan_at
    if not last_value:
        return True
    try:
        last = datetime.fromisoformat(last_value)
        return (utc_now() - last).total_seconds() >= METALS_SCAN_SECONDS
    except Exception:
        return True


def run_parallel_metals_cycle() -> None:
    trader = st.session_state.paper_trader
    metals_position = trader.get_position(METALS_SLOT)

    try:
        if metals_position:
            result = run_metals_cycle(trader=trader, risk_pct=1.0)
            st.session_state.metals_status = result.get("status", "MANAGING POSITION")
            return

        if st.session_state.bot_paused:
            st.session_state.metals_status = "PAUSED"
            return

        if st.session_state.trading_paused_by_risk:
            st.session_state.metals_status = "DAILY LOSS LIMIT HIT"
            return

        if not metals_scan_due():
            st.session_state.metals_status = "WAITING FOR NEXT METALS SCAN"
            return

        result = run_metals_cycle(trader=trader, risk_pct=1.0)
        st.session_state.metals_last_scan_at = utc_now().isoformat()
        st.session_state.metals_status = result.get("status", "UNKNOWN")
        st.session_state.metals_scanner_results = result.get("scanner_results", [])
        st.session_state.metals_best_setup = result.get("best_setup")

    except Exception as error:
        st.session_state.metals_status = "ERROR"
        st.session_state.bot_error = f"Metals: {error}"
        print(f"[METALS ENGINE ERROR] {error}", flush=True)

# ============================================================
# HEADER / MARKET STRIP
# ============================================================

def render_terminal_header() -> None:
    health = safe_system_health()
    overall = health.get("overall_status", "ONLINE")
    st.markdown(
        f"""
        <div class="q-header">
            <div class="q-header-row">
                <div class="q-brand">
                    <div class="q-mark"></div>
                    <div>
                        <div class="q-title">PRO AI · QUANT TERMINAL V5</div>
                        <div class="q-sub">MULTI-ASSET / QUANT INTELLIGENCE / PORTFOLIO RISK / AUTONOMOUS PAPER ENGINE</div>
                    </div>
                </div>
                <div class="q-status">
                    <div class="q-online">● {escape(overall)}</div>
                    <div class="q-clock">{utc_now().strftime('%H:%M:%S')} UTC</div>
                </div>
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def render_market_strip() -> None:
    pieces = []
    for item in get_market_strip():
        change = safe_float(item.get("change"))
        css = "pos" if change >= 0 else "neg"
        pieces.append(
            f'<span>{escape(item["symbol"].replace("USDT", ""))} '
            f'<b>${safe_float(item["last"]):,.2f}</b> '
            f'<span class="{css}">{change:+.2f}%</span></span>'
        )
    pieces.append('<span>MODE <b class="warn">PAPER</b></span>')
    pieces.append('<span>REAL EXECUTION <b class="neg">OFF</b></span>')
    st.markdown(f'<div class="q-strip">{"".join(pieces)}</div>', unsafe_allow_html=True)

render_terminal_header()
render_market_strip()

# ============================================================
# NAVIGATION + QUICK CONTROLS
# ============================================================

selected_page = st.radio(
    "Navigation",
    NAV_ITEMS,
    key="selected_asset_class",
    horizontal=True,
    label_visibility="collapsed",
)

c1, c2, c3, c4 = st.columns([1, 1, 1, 2.2])
with c1:
    if st.session_state.bot_paused:
        if st.button("▶ RESUME ENGINES", width="stretch"):
            st.session_state.bot_paused = False
            st.rerun()
    else:
        if st.button("Ⅱ PAUSE ENGINES", width="stretch"):
            st.session_state.bot_paused = True
            st.rerun()

with c2:
    if st.button("◉ FORCE CRYPTO SCAN", width="stretch"):
        run_crypto_cycle()
        st.rerun()

with c3:
    if st.button("◉ FORCE METALS SCAN", width="stretch"):
        st.session_state.metals_last_scan_at = None
        run_parallel_metals_cycle()
        st.rerun()

with c4:
    p = st.session_state.paper_trader.get_portfolio_snapshot()
    st.markdown(
        f'<div class="panel" style="min-height:33px;padding:7px 9px;">'
        f'{badge("PAPER ONLY")}{badge(f"POSITIONS {p.get("open_position_count",0)}/2")}'
        f'{badge("1 CRYPTO + 1 METAL")}{badge("REAL EXECUTION OFF")}</div>',
        unsafe_allow_html=True,
    )

# ============================================================
# CHART
# ============================================================

def render_quant_chart(symbol: str) -> None:
    base = symbol.replace("USDT", "")
    tv_symbol = f"COINBASE:{base}USD"
    chart_html = f"""
    <!DOCTYPE html>
    <html>
    <head>
      <meta charset="UTF-8">
      <style>
        html,body{{margin:0;padding:0;width:100%;height:100%;overflow:hidden;background:#070b10;}}
        #tv{{width:100%;height:100%;}}
      </style>
    </head>
    <body>
      <div id="tv"></div>
      <script src="https://s3.tradingview.com/tv.js"></script>
      <script>
        new TradingView.widget({{
          "autosize":true,
          "symbol":"{tv_symbol}",
          "interval":"15",
          "timezone":"Etc/UTC",
          "theme":"dark",
          "style":"1",
          "locale":"en",
          "hide_top_toolbar":false,
          "hide_side_toolbar":false,
          "allow_symbol_change":true,
          "save_image":false,
          "backgroundColor":"#070b10",
          "gridColor":"#15202a",
          "container_id":"tv"
        }});
      </script>
    </body>
    </html>
    """
    st.iframe(chart_html, height=370, width="stretch")

# ============================================================
# POSITIONS
# ============================================================

def build_position_rows(trader: PaperTrader) -> list[Dict[str, Any]]:
    rows = []
    for position in trader.get_positions():
        symbol = position.get("symbol")
        try:
            current = (
                get_metals_current_price(symbol)
                if position.get("slot") == METALS_SLOT
                else get_current_price(symbol)
            )
        except Exception:
            current = None

        entry = safe_float(position.get("entry_price"))
        pnl_pct = 0.0
        if current and entry > 0:
            current_f = safe_float(current)
            if position.get("side") == "LONG":
                pnl_pct = (current_f - entry) / entry * 100
            else:
                pnl_pct = (entry - current_f) / entry * 100

        rows.append(
            {
                "Slot": position.get("slot"),
                "Asset": position.get("asset_class"),
                "Symbol": symbol,
                "Side": position.get("side"),
                "Entry": position.get("entry_price"),
                "Current": current,
                "PnL %": round(pnl_pct, 3),
                "TP": position.get("take_profit"),
                "SL": position.get("stop_loss"),
                "Quantity": position.get("quantity"),
                "Opened": position.get("opened_at"),
            }
        )
    return rows

# ============================================================
# LIVE UI FRAGMENT
# ============================================================

@st.fragment(run_every=f"{POLL_SECONDS}s")
def live_terminal() -> None:
    trader = st.session_state.paper_trader
    st.session_state.bot_error = None
    update_daily_risk()
    publish_web_heartbeat()

    if PAPER_TRADING:
        run_crypto_cycle()
        run_parallel_metals_cycle()

    balance = safe_float(trader.get_balance())
    history = trader.get_trade_history()
    crypto_position = trader.get_position(CRYPTO_SLOT)
    metals_position = trader.get_position(METALS_SLOT)
    total_pnl = sum(safe_float(trade.get("pnl")) for trade in history)
    drawdown = safe_float(st.session_state.current_drawdown)
    portfolio = trader.get_portfolio_snapshot()

    render_section("Portfolio Command / Risk / Model State")
    k1, k2, k3, k4, k5, k6 = st.columns(6)
    with k1:
        render_kpi("Paper Equity", f"${balance:,.2f}", "Live paper portfolio")
    with k2:
        render_kpi("Realized PnL", f"${total_pnl:+,.2f}", f"{len(history)} closed trades")
    with k3:
        render_kpi("Daily Drawdown", f"{drawdown:.2f}%", f"Limit {MAX_DAILY_LOSS_PCT:.2f}%")
    with k4:
        render_kpi("Crypto Score", f"{safe_float(st.session_state.crypto_score):+.1f}", st.session_state.crypto_signal)
    with k5:
        render_kpi("MTF Confidence", f"{safe_float(st.session_state.crypto_confidence):.1f}%", st.session_state.crypto_market)
    with k6:
        render_kpi("Open Slots", f"{portfolio.get('open_position_count',0)}/2", "1 Crypto + 1 Metal")

    if selected_page == "Command":
        render_section("Quant Command Matrix")
        left, right = st.columns([1.65, 1])

        with left:
            row1, row2 = st.columns([2, 1])
            with row1:
                chart_symbol = st.selectbox("Primary Market", SCAN_MARKETS, key="chart_pair", label_visibility="collapsed")
            with row2:
                try:
                    ticker = get_ticker(
                        symbol=chart_symbol,
                        exchange="PUBLIC",
                        api_key="",
                        api_secret="",
                        use_testnet=False,
                    )
                    if ticker:
                        st.caption(
                            f"{chart_symbol}  ${safe_float(ticker.get('last')):,.4f}  "
                            f"{safe_float(ticker.get('change_pct')):+.2f}%"
                        )
                except Exception:
                    st.caption(chart_symbol)
            render_quant_chart(chart_symbol)

        with right:
            analytic_symbol = (
                st.session_state.crypto_market
                if st.session_state.crypto_market not in ("", "—")
                else st.session_state.chart_pair
            )
            regime = get_regime_data(analytic_symbol)
            intelligence = scanner_intelligence(st.session_state.crypto_scanner_results)
            breadth = intelligence.get("breadth", {}) if isinstance(intelligence, dict) else {}

            a1, a2 = st.columns(2)
            with a1:
                render_kpi("Regime", regime.get("regime", "UNKNOWN"), regime.get("trend", "UNKNOWN"))
            with a2:
                render_kpi("ATR", f"{safe_float(regime.get('atr_pct')):.2f}%", "15m volatility")
            a3, a4 = st.columns(2)
            with a3:
                render_kpi("Momentum", f"{safe_float(regime.get('momentum')):+.2f}", "Directional impulse")
            with a4:
                render_kpi(
                    "Breadth",
                    f"{safe_float(breadth.get('bullish_pct')):.0f}/{safe_float(breadth.get('bearish_pct')):.0f}",
                    "Bull / Bear %",
                )

            reason = escape(st.session_state.crypto_reason or "Awaiting current scanner decision.")
            st.markdown(
                f"""
                <div class="panel" style="margin-top:8px;">
                    <div class="panel-title">CRYPTO DECISION CORE</div>
                    {badge(st.session_state.crypto_status)}
                    {badge(st.session_state.crypto_signal)}
                    <div style="margin-top:8px;color:#8a98a5;font-size:9px;line-height:1.55;">{reason}</div>
                </div>
                """,
                unsafe_allow_html=True,
            )

        render_section("Engine Flow / Position State")
        e1, e2, e3 = st.columns([1, 1, 1.15])
        with e1:
            st.markdown(
                f"""
                <div class="panel">
                  <div class="panel-title">CRYPTO ENGINE</div>
                  {badge(st.session_state.crypto_status)}<br><br>
                  <b>{escape(st.session_state.crypto_market)}</b>
                  <div style="color:#71808d;font-size:8px;margin-top:6px;">
                  Score {safe_float(st.session_state.crypto_score):+.1f} · MTF {safe_float(st.session_state.crypto_confidence):.1f}%
                  </div>
                </div>
                """,
                unsafe_allow_html=True,
            )
        with e2:
            best = st.session_state.metals_best_setup or {}
            st.markdown(
                f"""
                <div class="panel">
                  <div class="panel-title">METALS ENGINE</div>
                  {badge(st.session_state.metals_status)}<br><br>
                  <b>{escape(best.get('symbol','XAU / XAG'))}</b>
                  <div style="color:#71808d;font-size:8px;margin-top:6px;">
                  Signal {escape(best.get('signal','NO TRADE'))} · MTF {safe_float(best.get('mtf_confidence')):.1f}%
                  </div>
                </div>
                """,
                unsafe_allow_html=True,
            )
        with e3:
            health = safe_system_health()
            overall = health.get("overall_status", "UNKNOWN")
            st.markdown(
                f"""
                <div class="panel">
                  <div class="panel-title">SYSTEM HEALTH GATE</div>
                  {badge(overall)} {badge('PAPER LOCKED')}
                  <div style="margin-top:8px;color:#71808d;font-size:8px;">
                  Runtime, DB and bootstrap observability are isolated from execution safety.
                  </div>
                </div>
                """,
                unsafe_allow_html=True,
            )

        render_section("Signal Matrix")
        results = st.session_state.crypto_scanner_results
        if results:
            rows = [
                {
                    "Market": item.get("symbol"),
                    "Signal": item.get("signal"),
                    "Score": item.get("score"),
                    "Reason": item.get("reason"),
                }
                for item in results
            ]
            st.dataframe(pd.DataFrame(rows), width="stretch", hide_index=True, height=275)
        else:
            st.info("Signal matrix warming up.")

    elif selected_page == "Crypto":
        render_section("Crypto Intelligence")
        analytics_symbol = (
            crypto_position.get("symbol")
            if crypto_position
            else (
                st.session_state.crypto_market
                if st.session_state.crypto_market not in ("", "—")
                else st.session_state.chart_pair
            )
        )
        regime = get_regime_data(analytics_symbol)
        intelligence = scanner_intelligence(st.session_state.crypto_scanner_results)
        breadth = intelligence.get("breadth", {}) if isinstance(intelligence, dict) else {}

        m1, m2, m3, m4, m5, m6 = st.columns(6)
        with m1:
            render_kpi("Market", analytics_symbol, "Primary scanner asset")
        with m2:
            render_kpi("Regime", regime.get("regime", "UNKNOWN"), regime.get("trend", "UNKNOWN"))
        with m3:
            render_kpi("ATR", f"{safe_float(regime.get('atr_pct')):.2f}%", "Volatility")
        with m4:
            render_kpi("Momentum", f"{safe_float(regime.get('momentum')):+.2f}", "Impulse")
        with m5:
            render_kpi("Bull Breadth", f"{safe_float(breadth.get('bullish_pct')):.1f}%", "Scanner")
        with m6:
            render_kpi("Bear Breadth", f"{safe_float(breadth.get('bearish_pct')):.1f}%", "Scanner")

        chart_col, model_col = st.columns([1.7, 1])
        with chart_col:
            render_quant_chart(analytics_symbol)
        with model_col:
            render_kpi("AI Score", f"{safe_float(st.session_state.crypto_score):+.1f}", st.session_state.crypto_signal)
            st.markdown("<br>", unsafe_allow_html=True)
            render_kpi("MTF Confidence", f"{safe_float(st.session_state.crypto_confidence):.1f}%", st.session_state.crypto_status)

        render_section("Crypto Scanner")
        if st.session_state.crypto_scanner_results:
            st.dataframe(pd.DataFrame(st.session_state.crypto_scanner_results), width="stretch", hide_index=True)
        else:
            st.info("Crypto scanner is warming.")

        render_section("Correlation Matrix")
        corr = build_crypto_correlation()
        if corr is not None and not corr.empty:
            st.dataframe(corr.round(2), width="stretch")
        else:
            st.info("Correlation data is building.")

    elif selected_page == "Metals":
        render_section("Precious Metals Intelligence")
        render_metals_dashboard()
        render_section("Gold / Silver MTF Signal Grid")
        results = st.session_state.metals_scanner_results
        if results:
            rows = [
                {
                    "Market": item.get("symbol"),
                    "Signal": item.get("signal"),
                    "Score": item.get("score"),
                    "MTF %": item.get("mtf_confidence"),
                    "1H + 4H": item.get("higher_tf_confirmed"),
                    "Approved": item.get("approved"),
                    "Entry": item.get("entry_price"),
                    "Reason": item.get("reason"),
                }
                for item in results
            ]
            st.dataframe(pd.DataFrame(rows), width="stretch", hide_index=True)
        else:
            st.info("Metals scanner warming.")

        if st.session_state.metals_best_setup:
            with st.expander("Metals Model Diagnostics"):
                st.json(st.session_state.metals_best_setup)

    elif selected_page == "Positions":
        render_section("Position Flow / Exposure")
        rows = build_position_rows(trader)
        if rows:
            st.dataframe(pd.DataFrame(rows), width="stretch", hide_index=True)
        else:
            st.info("Portfolio is currently flat.")

    elif selected_page == "Scanner":
        render_section("Multi-Asset Scanner")
        crypto_col, metal_col = st.columns([1.6, 1])
        with crypto_col:
            st.markdown("#### Crypto")
            if st.session_state.crypto_scanner_results:
                st.dataframe(pd.DataFrame(st.session_state.crypto_scanner_results), width="stretch", hide_index=True)
            else:
                st.info("Crypto scanner warming.")
        with metal_col:
            st.markdown("#### Metals")
            if st.session_state.metals_scanner_results:
                st.dataframe(pd.DataFrame(st.session_state.metals_scanner_results), width="stretch", hide_index=True)
            else:
                st.info("Metals scanner warming.")

    elif selected_page == "Risk":
        render_section("Portfolio Risk Command")
        start_balance = safe_float(st.session_state.day_start_balance, PAPER_BALANCE)
        remaining_loss_budget = max(0.0, MAX_DAILY_LOSS_PCT - drawdown)
        r1, r2, r3, r4 = st.columns(4)
        with r1:
            render_kpi("Day Start Equity", f"${start_balance:,.2f}", "UTC session anchor")
        with r2:
            render_kpi("Current Equity", f"${balance:,.2f}", "Paper portfolio")
        with r3:
            render_kpi("Drawdown", f"{drawdown:.2f}%", f"Max {MAX_DAILY_LOSS_PCT:.2f}%")
        with r4:
            render_kpi(
                "Loss Budget Left",
                f"{remaining_loss_budget:.2f}%",
                "BLOCKED" if st.session_state.trading_paused_by_risk else "AVAILABLE",
            )
        st.markdown("<br>", unsafe_allow_html=True)
        st.json(safe_system_health(), expanded=False)

    elif selected_page == "Analytics":
        render_section("Performance Analytics")
        statistics = trade_statistics(history)
        st.json(statistics, expanded=False)
        crypto_history = trader.get_trade_history(asset_class="CRYPTO")
        metal_history = trader.get_trade_history(asset_class="METAL")
        a1, a2, a3 = st.columns(3)
        with a1:
            render_kpi("Crypto Trades", len(crypto_history), "Closed")
        with a2:
            render_kpi("Metals Trades", len(metal_history), "Closed")
        with a3:
            render_kpi("Total Trades", len(history), "All assets")
        if history:
            st.dataframe(pd.DataFrame(history), width="stretch", hide_index=True)

    elif selected_page == "Settings":
        render_section("Central Control Center")
        render_control_center()

    if st.session_state.bot_error:
        st.error(st.session_state.bot_error)

live_terminal()

# ============================================================
# METALS BOOTSTRAP STATUS UI
# ============================================================

try:
    from metals_bootstrap import run_bootstrap_cycle, bootstrap_status, metals_bootstrap_health

    if selected_page in ("Metals", "Risk", "Settings"):
        render_section("Metals Historical Data Pipeline")
        bootstrap_health = metals_bootstrap_health()
        bootstrap_state = bootstrap_status()

        b1, b2, b3, b4 = st.columns(4)
        with b1:
            render_kpi("Bootstrap", "ONLINE" if bootstrap_health.get("ok") else "ERROR", "Gold-API historical")
        with b2:
            render_kpi("Requests / Hour", bootstrap_state.get("requests_used_last_hour", 0), "Quota usage")
        with b3:
            render_kpi("Safety Budget", bootstrap_state.get("hourly_budget", 0), "Internal ceiling")
        with b4:
            render_kpi("Progress", f"{safe_float(bootstrap_state.get('progress_pct')):.1f}%", "Historical warm-up")

        markets = bootstrap_state.get("markets", {})
        rows = []
        for symbol in ("XAUUSD", "XAGUSD"):
            for timeframe in ("15m", "1h", "4h"):
                info = markets.get(symbol, {}).get(timeframe, {})
                rows.append(
                    {
                        "Market": symbol,
                        "Timeframe": timeframe,
                        "Candles": info.get("candles", 0),
                        "Target": info.get("target", 60),
                        "Remaining": info.get("remaining", 60),
                        "Ready": info.get("ready", False),
                    }
                )
        st.dataframe(pd.DataFrame(rows), width="stretch", hide_index=True)

        if bootstrap_state.get("ready", False):
            st.success("Gold/Silver historical bootstrap complete.")
        else:
            st.caption("Automatic embedded bootstrap is active. Manual run is available only when needed.")
            if st.button("RUN ONE SAFE BOOTSTRAP CYCLE", width="stretch"):
                result = run_bootstrap_cycle(max_requests=1)
                if result.get("ok"):
                    st.success("Safe historical cycle completed.")
                else:
                    st.warning(result.get("reason", "Cycle could not complete."))
                st.rerun()

except Exception as bootstrap_ui_error:
    if selected_page in ("Metals", "Risk", "Settings"):
        st.warning(f"Historical bootstrap UI unavailable: {bootstrap_ui_error}")

# ============================================================
# V5 EMBEDDED METALS AUTO BOOTSTRAP
# Existing Render Web Service only — no new paid worker
# ============================================================

@st.cache_resource
def start_metals_auto_bootstrap():
    """
    Start one quota-safe Metals bootstrap daemon thread per Streamlit process.

    Important:
    - The worker thread never calls Streamlit APIs.
    - PostgreSQL advisory locking guarantees one active owner across processes.
    - All bootstrap progress remains persistent in PostgreSQL.
    - Health publishing is optional and never blocks the bootstrap engine.
    """

    from metals_bootstrap import bootstrap_status, fetch_gold_api_ohlc, requests_used_last_hour

    database_url = os.environ.get("DATABASE_URL", "").strip()
    advisory_lock_id = 93739001
    internal_hourly_limit = 8
    request_interval_seconds = 480
    budget_wait_seconds = 600
    ready_sleep_seconds = 3600
    error_sleep_seconds = 120
    heartbeat_seconds = 120

    if not database_url:
        print("[METALS AUTO BOOTSTRAP] DATABASE_URL is not configured.", flush=True)
        return None

    def log(message: Any) -> None:
        print(f"[METALS AUTO BOOTSTRAP] {message}", flush=True)

    def health_component() -> Any:
        if _health_module is None:
            return "METALS_BOOTSTRAP"
        return getattr(_health_module, "COMPONENT_METALS_BOOTSTRAP", "METALS_BOOTSTRAP")

    def health_payload(status: Optional[Dict[str, Any]] = None, **extra: Any) -> Dict[str, Any]:
        if not isinstance(status, dict):
            try:
                status = bootstrap_status()
            except Exception:
                status = {}
        payload = {
            "runtime": "EMBEDDED_WEB_SERVICE",
            "version": "V5.0",
            "paid_worker_required": False,
            "paper_only": True,
            "real_execution": False,
            "ready": bool(status.get("ready", False)),
            "progress_pct": safe_float(status.get("progress_pct")),
            "requests_used_last_hour": safe_int(status.get("requests_used_last_hour")),
            "hourly_budget": safe_int(status.get("hourly_budget"), internal_hourly_limit),
        }
        payload.update(extra)
        return payload

    def publish(name: str, status: Optional[Dict[str, Any]], message: str, **extra: Any) -> None:
        if not SYSTEM_HEALTH_AVAILABLE or _health_module is None:
            return
        fn = getattr(_health_module, name, None)
        if not callable(fn):
            return
        try:
            fn(
                health_component(),
                message=message,
                payload=health_payload(status, **extra),
            )
        except TypeError:
            # Older health implementations may use a smaller signature.
            try:
                fn(health_component(), message=message)
            except Exception:
                pass
        except Exception:
            pass

    def publish_ready(status: Dict[str, Any]) -> None:
        if not SYSTEM_HEALTH_AVAILABLE or _health_module is None:
            return
        fn = getattr(_health_module, "update_runtime_state", None)
        if not callable(fn):
            return
        healthy = getattr(_health_module, "STATUS_HEALTHY", "HEALTHY")
        try:
            fn(
                health_component(),
                status=healthy,
                success=True,
                message="Historical metals bootstrap READY.",
                payload=health_payload(status, bootstrap_complete=True),
            )
        except Exception:
            pass

    def runtime_sleep(seconds: int, status: Optional[Dict[str, Any]], reason: str) -> None:
        deadline = time.monotonic() + max(1, int(seconds))
        last_hb = time.monotonic()
        while time.monotonic() < deadline:
            remaining = deadline - time.monotonic()
            time.sleep(min(10.0, max(0.1, remaining)))
            now_m = time.monotonic()
            if now_m - last_hb >= heartbeat_seconds:
                publish("heartbeat", status, f"Embedded bootstrap alive while {reason}.")
                last_hb = now_m

    def select_next_market(status: Dict[str, Any]) -> Optional[Dict[str, str]]:
        markets = status.get("markets", {})
        candidates = []
        timeframe_rank = {"4h": 0, "1h": 1, "15m": 2}
        symbol_rank = {"XAUUSD": 0, "XAGUSD": 1}

        for symbol in ("XAUUSD", "XAGUSD"):
            symbol_data = markets.get(symbol, {})
            for timeframe in ("4h", "1h", "15m"):
                info = symbol_data.get(timeframe, {})
                candles = safe_int(info.get("candles"))
                target = safe_int(info.get("target", 60), 60)
                if candles >= target:
                    continue
                completion = candles / target if target > 0 else 1.0
                candidates.append(
                    (
                        completion,
                        candles,
                        timeframe_rank[timeframe],
                        symbol_rank[symbol],
                        symbol,
                        timeframe,
                    )
                )

        if not candidates:
            return None
        candidates.sort()
        selected = candidates[0]
        return {"symbol": selected[4], "timeframe": selected[5]}

    def worker_loop() -> None:
        lock_connection = None
        try:
            lock_connection = psycopg.connect(
                database_url,
                autocommit=True,
                connect_timeout=10,
            )
            with lock_connection.cursor() as cur:
                cur.execute("SELECT pg_try_advisory_lock(%s)", (advisory_lock_id,))
                row = cur.fetchone()

            if not bool(row and row[0]):
                log("Another bootstrap runtime owns the PostgreSQL lock. This runtime is idle.")
                return

            log("Automatic bootstrap lock acquired.")

            while True:
                try:
                    status = bootstrap_status()

                    if status.get("ready", False):
                        log("Historical bootstrap READY. No historical API call required.")
                        publish_ready(status)
                        runtime_sleep(ready_sleep_seconds, status, "READY idle")
                        continue

                    used = safe_int(requests_used_last_hour())
                    if used >= internal_hourly_limit:
                        message = f"Hourly historical budget reached: {used}/{internal_hourly_limit}. Waiting safely."
                        log(message)
                        publish("report_rate_limited", status, message, limit_type="INTERNAL")
                        runtime_sleep(budget_wait_seconds, status, "internal quota wait")
                        continue

                    selected = select_next_market(status)
                    if selected is None:
                        log("No missing historical series.")
                        publish_ready(status)
                        runtime_sleep(ready_sleep_seconds, status, "no missing history")
                        continue

                    symbol = selected["symbol"]
                    timeframe = selected["timeframe"]
                    log(f"Fetching next historical candle: {symbol} {timeframe}")
                    publish(
                        "report_warming_up",
                        status,
                        f"Fetching historical candle {symbol} {timeframe}.",
                        symbol=symbol,
                        timeframe=timeframe,
                    )

                    result = fetch_gold_api_ohlc(symbol, timeframe)

                    if result.get("ok", False):
                        log(f"Historical candle stored: {symbol} {timeframe}")
                        try:
                            current_status = bootstrap_status()
                        except Exception:
                            current_status = status
                        publish(
                            "report_warming_up",
                            current_status,
                            f"Historical candle stored {symbol} {timeframe}.",
                            symbol=symbol,
                            timeframe=timeframe,
                            result_type="STORED",
                        )
                        runtime_sleep(request_interval_seconds, current_status, "normal historical interval")
                        continue

                    if result.get("rate_limited_locally", False):
                        log("Local historical API budget reached.")
                        publish("report_rate_limited", status, "Local historical API budget reached.", limit_type="LOCAL")
                        runtime_sleep(budget_wait_seconds, status, "local quota wait")
                        continue

                    if result.get("provider_rate_limited", False):
                        log("Gold-API rate limit reached. Waiting safely.")
                        publish(
                            "report_rate_limited",
                            status,
                            "Gold-API rate limit reached. Waiting safely.",
                            provider="Gold-API",
                            limit_type="PROVIDER",
                        )
                        runtime_sleep(budget_wait_seconds, status, "provider quota wait")
                        continue

                    if result.get("skipped_interval", False):
                        log(f"Historical interval skipped: {symbol} {timeframe}")
                    else:
                        log(f"Historical request returned no usable candle: {result}")

                    runtime_sleep(request_interval_seconds, status, "normal historical interval")

                except Exception as error:
                    log(f"Runtime cycle error: {error}")
                    publish(
                        "report_error",
                        None,
                        f"Embedded bootstrap cycle error: {error}",
                        error_type=type(error).__name__,
                    )
                    runtime_sleep(error_sleep_seconds, None, "error retry")

        except Exception as error:
            log(f"Runtime startup error: {error}")
            publish(
                "report_error",
                None,
                f"Embedded bootstrap startup error: {error}",
                phase="STARTUP",
            )
        finally:
            if lock_connection is not None:
                try:
                    with lock_connection.cursor() as cur:
                        cur.execute("SELECT pg_advisory_unlock(%s)", (advisory_lock_id,))
                except Exception:
                    pass
                try:
                    lock_connection.close()
                except Exception:
                    pass

    thread = threading.Thread(
        target=worker_loop,
        name="metals-auto-bootstrap-v5",
        daemon=True,
    )
    thread.start()
    return thread


_metals_auto_bootstrap_thread = start_metals_auto_bootstrap()

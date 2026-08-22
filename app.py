"""
app.py

PRO AI QUANT TERMINAL V5.4 ASYNC RUNTIME
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
import json
import os
import threading
import time
import textwrap
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
from trade_lifecycle_engine import (
    RECOMMENDED_CYCLE_SECONDS as LIFECYCLE_CYCLE_SECONDS,
    acquire_lifecycle_runtime_lock,
    release_lifecycle_runtime_lock,
    run_lifecycle_cycle,
)

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

# V5.10 UI PERFORMANCE OPTIMIZATION: read-path only; trading logic unchanged.
PLATFORM_VERSION = "V5.13-COMPACT-PRO-UI"
PAPER_ONLY = True
REAL_EXECUTION_ENABLED = False
METALS_SCAN_SECONDS = 300
CRYPTO_SCAN_SECONDS = max(30, int(os.environ.get("CRYPTO_SCAN_SECONDS", "60")))
UI_REFRESH_SECONDS = max(45, int(os.environ.get("UI_REFRESH_SECONDS", "60")))
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
# SAFE HTML RENDERER
# ============================================================

def render_html(value: str) -> None:
    """
    Render HTML without Markdown treating indented HTML as a code block.
    This prevents raw <div> tags from appearing on the dashboard.
    """
    st.markdown(
        textwrap.dedent(value).strip(),
        unsafe_allow_html=True,
    )


# ============================================================
# V5 INSTITUTIONAL CSS
# ============================================================

def inject_v5_css() -> None:
    """Compact professional UI skin. Presentation-only; trading logic unchanged."""
    render_html("""
    <style>
    :root{--bg0:#05080c;--line:#1d2933;--line2:#2b3a46;--text:#e7edf2;--green:#43d59d;--red:#ef6f7d;--amber:#e6b84d;--blue:#72a7ff;}
    html,body,[class*="css"]{font-family:Inter,-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif;}
    .stApp{background:radial-gradient(circle at 50% -12%,rgba(54,88,122,.14),transparent 26%),var(--bg0);color:var(--text);}
    .block-container{max-width:1920px;padding-top:.35rem;padding-bottom:2rem;padding-left:.55rem;padding-right:.55rem;}
    #MainMenu,footer{visibility:hidden;}::-webkit-scrollbar{width:6px;height:6px;}::-webkit-scrollbar-track{background:#070b10;}::-webkit-scrollbar-thumb{background:#283744;border-radius:10px;}
    .q-header{border:1px solid var(--line2);background:linear-gradient(180deg,#0d151d,#080c11);padding:8px 11px;margin-bottom:4px;box-shadow:0 8px 24px rgba(0,0,0,.28);}
    .q-header-row{display:flex;justify-content:space-between;align-items:center;gap:10px}.q-brand{display:flex;align-items:center;gap:9px}.q-mark{width:14px;height:14px;background:var(--amber);box-shadow:0 0 14px rgba(229,184,79,.24)}
    .q-title{font-size:12.5px;font-weight:850;letter-spacing:1.3px;color:#f0f4f7}.q-sub{font-size:6.8px;letter-spacing:1.05px;color:#687887;margin-top:2px}.q-status{text-align:right;font-family:ui-monospace,SFMono-Regular,Menlo,monospace}.q-online{color:var(--green);font-size:8px;font-weight:800}.q-clock{color:#8d9ba7;font-size:7px;margin-top:1px}
    .q-strip{border:1px solid #18232c;background:#070b10;padding:4px 8px;margin-bottom:5px;overflow-x:auto;white-space:nowrap;font-family:ui-monospace,SFMono-Regular,Menlo,monospace;font-size:7.2px;letter-spacing:.25px;color:#85939f}.q-strip span{margin-right:15px}.pos{color:var(--green)!important}.neg{color:var(--red)!important}.warn{color:var(--amber)!important}.info{color:var(--blue)!important}
    .section-title{margin:7px 0 4px 1px;color:#7f8f9c;font-size:7px;letter-spacing:1.05px;text-transform:uppercase;font-family:ui-monospace,SFMono-Regular,Menlo,monospace;font-weight:800}
    .panel{border:1px solid var(--line);background:linear-gradient(180deg,#0b1218,#070b10);padding:8px;min-height:70px}.panel-title{color:#7a8a98;font-size:6.7px;letter-spacing:.9px;text-transform:uppercase;font-family:ui-monospace,SFMono-Regular,Menlo,monospace;margin-bottom:5px}
    .kpi{border:1px solid var(--line);background:#080d12;padding:6px 8px;min-height:57px}.kpi-label{color:#697987;font-size:6.2px;letter-spacing:.8px;text-transform:uppercase;font-family:ui-monospace,SFMono-Regular,Menlo,monospace}.kpi-value{color:#edf2f5;font-size:14px;font-weight:850;margin-top:3px;line-height:1.05;font-family:ui-monospace,SFMono-Regular,Menlo,monospace}.kpi-sub{color:#62717d;font-size:6.5px;margin-top:2px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
    .badge{display:inline-block;padding:2px 5px;margin:0 3px 3px 0;border:1px solid #2a3742;background:#0a1015;color:#8f9ca7;font-size:6.7px;font-family:ui-monospace,SFMono-Regular,Menlo,monospace}.badge-green{color:var(--green);border-color:#285d4a}.badge-red{color:var(--red);border-color:#693a41}.badge-amber{color:var(--amber);border-color:#6c5728}.badge-blue{color:var(--blue);border-color:#365070}
    div[data-testid="stMetric"]{border:1px solid var(--line);background:#080d12;padding:6px 8px;border-radius:0}div[data-testid="stMetricLabel"]{color:#71818f;font-size:8px}div[data-testid="stMetricValue"]{font-family:ui-monospace,SFMono-Regular,Menlo,monospace;font-size:1rem}div[data-testid="stDataFrame"]{border:1px solid var(--line)}div[data-baseweb="select"]>div{background:#080d12;border-color:#24313b;min-height:30px}
    .stButton>button{width:100%;min-height:30px;border-radius:0;border:1px solid #293742;background:linear-gradient(180deg,#111922,#0a1016);color:#cbd4db;font-size:8px;padding:.25rem .45rem}.stButton>button:hover{border-color:#4a6277;color:white}div[role="radiogroup"]{background:#070b10;border:1px solid #1e2932;padding:2px 5px;border-radius:0}div[role="radiogroup"] label{font-size:8px!important}
    .compact-title{font-size:8px;color:#8b99a5;letter-spacing:1px;text-transform:uppercase;margin-bottom:4px;font-weight:800}.activity-row{display:flex;justify-content:space-between;gap:8px;border-bottom:1px solid #17222b;padding:5px 0;font-size:7.5px;color:#a7b3bd}.activity-row:last-child{border-bottom:none}.activity-time{color:#647581;font-family:ui-monospace,SFMono-Regular,Menlo,monospace}.signal-buy{color:var(--green);font-weight:800}.signal-sell{color:var(--red);font-weight:800}.signal-flat{color:#8b98a3;font-weight:800}
    @media(max-width:1050px){.block-container{padding-left:.35rem;padding-right:.35rem}.q-title{font-size:11px}.q-sub{display:none}.kpi-value{font-size:12px}.q-strip{font-size:6.6px}}
    </style>
    """)

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
        "crypto_last_scan_at": None,
        "crypto_runtime_updated_at": None,
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
    render_html(f'<div class="section-title">{escape(text)}</div>')


def render_kpi(label: str, value: Any, sub: str = "") -> None:
    render_html(
        f"""
        <div class="kpi">
            <div class="kpi-label">{escape(label)}</div>
            <div class="kpi-value">{escape(value)}</div>
            <div class="kpi-sub">{escape(sub)}</div>
        </div>
        """
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

def update_daily_risk(balance: Optional[float] = None) -> float:
    trader = st.session_state.paper_trader
    if balance is None:
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
# V5.3 PERSISTENT RUNTIME STATE
# PostgreSQL-backed UI/engine handoff
# ============================================================

RUNTIME_STATE_TABLE = "pro_ai_runtime_state"
# PostgreSQL advisory-lock registry:
#   93739001 = Metals bootstrap runtime
#   93739002 = Trade lifecycle runtime
#   93739003 = Crypto autonomous scanner runtime
# Keep these IDs unique: sharing an ID makes unrelated runtimes block each other.
CRYPTO_RUNTIME_LOCK_ID = 93739003
CRYPTO_RUNTIME_POLL_SECONDS = max(
    30,
    int(os.environ.get("CRYPTO_RUNTIME_POLL_SECONDS", "60")),
)
CRYPTO_RUNTIME_IDLE_CHECK_SECONDS = 2


def _json_safe(value: Any) -> Any:
    """
    Convert common Python / pandas / numpy values into JSON-safe values.
    """
    if value is None or isinstance(value, (str, int, float, bool)):
        return value

    if isinstance(value, datetime):
        return value.isoformat()

    if isinstance(value, dict):
        return {
            str(key): _json_safe(item)
            for key, item in value.items()
        }

    if isinstance(value, (list, tuple, set)):
        return [_json_safe(item) for item in value]

    item_method = getattr(value, "item", None)
    if callable(item_method):
        try:
            return _json_safe(item_method())
        except Exception:
            pass

    iso_method = getattr(value, "isoformat", None)
    if callable(iso_method):
        try:
            return iso_method()
        except Exception:
            pass

    return str(value)


def _runtime_db_connect():
    database_url = os.environ.get("DATABASE_URL", "").strip()

    if not database_url:
        raise RuntimeError("DATABASE_URL is not configured")

    return psycopg.connect(
        database_url,
        autocommit=True,
        connect_timeout=10,
    )


def ensure_runtime_state_schema() -> bool:
    """
    Idempotent schema creation. Safe across deploys and process restarts.
    """
    try:
        with _runtime_db_connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    f"""
                    CREATE TABLE IF NOT EXISTS {RUNTIME_STATE_TABLE} (
                        state_key TEXT PRIMARY KEY,
                        payload JSONB NOT NULL,
                        updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                    )
                    """
                )
        return True

    except Exception as error:
        print(
            f"[V5.3 RUNTIME STATE] Schema error: {error}",
            flush=True,
        )
        return False


def write_runtime_state(
    state_key: str,
    payload: Dict[str, Any],
) -> bool:
    """
    Persist runtime state.

    Self-healing behavior:
    if the runtime table is missing after a fresh deploy/database,
    create it and retry once automatically.
    """
    safe_payload = _json_safe(payload)
    encoded = json.dumps(
        safe_payload,
        separators=(",", ":"),
        ensure_ascii=False,
    )

    for attempt in range(2):
        try:
            with _runtime_db_connect() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        f"""
                        INSERT INTO {RUNTIME_STATE_TABLE}
                            (state_key, payload, updated_at)
                        VALUES
                            (%s, %s::jsonb, NOW())
                        ON CONFLICT (state_key)
                        DO UPDATE SET
                            payload = EXCLUDED.payload,
                            updated_at = NOW()
                        """,
                        (
                            str(state_key),
                            encoded,
                        ),
                    )

            return True

        except psycopg.errors.UndefinedTable:
            if attempt == 0 and ensure_runtime_state_schema():
                continue

            print(
                f"[V5.3.1 RUNTIME STATE] "
                f"Write {state_key} failed because schema is unavailable.",
                flush=True,
            )
            return False

        except Exception as error:
            print(
                f"[V5.3.1 RUNTIME STATE] Write {state_key} failed: {error}",
                flush=True,
            )
            return False

    return False


def read_runtime_state(
    state_key: str,
    default: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """
    Read runtime state with automatic first-deploy schema recovery.
    """
    fallback = dict(default or {})

    for attempt in range(2):
        try:
            with _runtime_db_connect() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        f"""
                        SELECT payload, updated_at
                        FROM {RUNTIME_STATE_TABLE}
                        WHERE state_key = %s
                        """,
                        (str(state_key),),
                    )

                    row = cur.fetchone()

            if not row:
                return fallback

            payload = row[0]

            if isinstance(payload, str):
                payload = json.loads(payload)

            if not isinstance(payload, dict):
                return fallback

            result = dict(payload)

            if row[1] is not None:
                result["_updated_at"] = row[1].isoformat()

            return result

        except psycopg.errors.UndefinedTable:
            if attempt == 0 and ensure_runtime_state_schema():
                continue

            print(
                f"[V5.3.1 RUNTIME STATE] "
                f"Read {state_key} failed because schema is unavailable.",
                flush=True,
            )
            return fallback

        except Exception as error:
            print(
                f"[V5.3.1 RUNTIME STATE] Read {state_key} failed: {error}",
                flush=True,
            )
            return fallback

    return fallback


def get_crypto_control() -> Dict[str, Any]:
    return read_runtime_state(
        "crypto_control",
        {
            "paused": False,
            "force_nonce": "",
        },
    )


def set_crypto_paused(paused: bool) -> None:
    current = get_crypto_control()

    write_runtime_state(
        "crypto_control",
        {
            "paused": bool(paused),
            "force_nonce": current.get("force_nonce", ""),
        },
    )


def request_crypto_force_scan() -> None:
    current = get_crypto_control()

    write_runtime_state(
        "crypto_control",
        {
            "paused": bool(current.get("paused", False)),
            "force_nonce": utc_now().isoformat(),
        },
    )


def sync_crypto_runtime_snapshot() -> None:
    """
    Cheap UI-side synchronization from PostgreSQL.
    No market API requests and no strategy calculations occur here.
    """
    snapshot = read_runtime_state(
        "crypto_runtime",
        {},
    )

    if not snapshot:
        return

    st.session_state.crypto_status = snapshot.get(
        "status",
        st.session_state.crypto_status,
    )
    st.session_state.crypto_market = snapshot.get(
        "market",
        st.session_state.crypto_market,
    )
    st.session_state.crypto_signal = snapshot.get(
        "signal",
        st.session_state.crypto_signal,
    )
    st.session_state.crypto_score = safe_float(
        snapshot.get(
            "score",
            st.session_state.crypto_score,
        )
    )
    st.session_state.crypto_confidence = safe_float(
        snapshot.get(
            "confidence",
            st.session_state.crypto_confidence,
        )
    )
    st.session_state.crypto_reason = snapshot.get(
        "reason",
        st.session_state.crypto_reason,
    )

    scanner_results = snapshot.get(
        "scanner_results",
        st.session_state.crypto_scanner_results,
    )

    if isinstance(scanner_results, list):
        st.session_state.crypto_scanner_results = scanner_results

    st.session_state.crypto_runtime_updated_at = snapshot.get(
        "updated_at",
        snapshot.get("_updated_at", st.session_state.crypto_runtime_updated_at),
    )

    strategy = snapshot.get("strategy")

    if isinstance(strategy, dict):
        st.session_state.crypto_strategy_result = strategy


# Initialize persistent runtime state before any UI control reads it.
# Safe and idempotent because the table is created with IF NOT EXISTS.
_RUNTIME_STATE_SCHEMA_READY = ensure_runtime_state_schema()


# ============================================================
# CRYPTO ANALYTICS
# ============================================================

@st.cache_data(ttl=90, show_spinner=False)
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


@st.cache_data(ttl=30, show_spinner=False)
def get_cached_ticker(symbol: str) -> Dict[str, Any]:
    """Fast UI ticker cache; autonomous trading does not depend on it."""
    try:
        ticker = get_ticker(
            symbol=symbol,
            exchange="PUBLIC",
            api_key="",
            api_secret="",
            use_testnet=False,
        )
        return dict(ticker or {})
    except Exception as error:
        print(f"[V5.4 UI CACHE] ticker {symbol} failed: {error}", flush=True)
        return {}


@st.cache_data(ttl=120, show_spinner=False)
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
# CRYPTO SCAN CADENCE
# ============================================================

def crypto_scan_due() -> bool:
    last_value = st.session_state.crypto_last_scan_at

    if not last_value:
        return True

    try:
        last = datetime.fromisoformat(last_value)
        return (
            utc_now() - last
        ).total_seconds() >= CRYPTO_SCAN_SECONDS
    except Exception:
        return True


# ============================================================
# CRYPTO ENGINE
# ============================================================

def run_crypto_cycle(force_scan: bool = False) -> None:
    trader = st.session_state.paper_trader
    now = utc_now()

    try:
        crypto_position = trader.get_position(CRYPTO_SLOT)

        if crypto_position:
            # Open positions are managed by the autonomous lifecycle runtime.
            # The UI must not duplicate TP/SL/lifecycle price polling.
            st.session_state.crypto_market = crypto_position.get("symbol", "—")
            st.session_state.crypto_status = "POSITION OPEN · LIFECYCLE MANAGED"
            return

        if st.session_state.bot_paused:
            st.session_state.crypto_status = "PAUSED"
            return

        if st.session_state.trading_paused_by_risk:
            st.session_state.crypto_status = "DAILY LOSS LIMIT HIT"
            return

        if not force_scan and not crypto_scan_due():
            st.session_state.crypto_status = "WAITING FOR NEXT CRYPTO SCAN"
            return

        st.session_state.crypto_status = f"SCANNING {len(SCAN_MARKETS)} MARKETS"
        st.session_state.crypto_last_scan_at = utc_now().isoformat()
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
    render_html(
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
        """
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
    render_html(f'<div class="q-strip">{"".join(pieces)}</div>')

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
    crypto_control = get_crypto_control()
    crypto_paused = bool(crypto_control.get("paused", False))
    st.session_state.bot_paused = crypto_paused

    if crypto_paused:
        if st.button("▶ RESUME CRYPTO ENGINE", width="stretch"):
            set_crypto_paused(False)
            st.session_state.bot_paused = False
            st.rerun()
    else:
        if st.button("Ⅱ PAUSE CRYPTO ENGINE", width="stretch"):
            set_crypto_paused(True)
            st.session_state.bot_paused = True
            st.rerun()

with c2:
    if st.button("◉ FORCE CRYPTO SCAN", width="stretch"):
        request_crypto_force_scan()
        st.session_state.crypto_status = "FORCE SCAN REQUESTED"
        st.rerun()

with c3:
    if st.button("◉ FORCE METALS SCAN", width="stretch"):
        st.session_state.metals_last_scan_at = None
        run_parallel_metals_cycle()
        st.rerun()

with c4:
    quick_positions = st.session_state.paper_trader.get_positions()
    quick_position_count = len(quick_positions)
    render_html(
        f'<div class="panel" style="min-height:33px;padding:7px 9px;">'
        f'{badge("PAPER ONLY")}{badge(f"POSITIONS {quick_position_count}/2")}'
        f'{badge("1 CRYPTO + 1 METAL")}{badge("REAL EXECUTION OFF")}</div>'
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

def build_position_rows(
    trader: PaperTrader,
    positions: Optional[list[Dict[str, Any]]] = None,
) -> list[Dict[str, Any]]:
    rows = []
    if positions is None:
        positions = trader.get_positions()
    for position in positions:
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

@st.fragment(run_every=f"{UI_REFRESH_SECONDS}s")
def live_terminal() -> None:
    """V5.13 compact professional dashboard. UI-only refactor."""
    trader = st.session_state.paper_trader
    st.session_state.bot_error = None
    publish_web_heartbeat()

    balance = safe_float(trader.get_balance())
    positions = trader.get_positions()
    history = trader.get_trade_history()
    update_daily_risk(balance)
    sync_crypto_runtime_snapshot()

    position_by_slot = {
        str(position.get("slot")): position
        for position in positions
        if isinstance(position, dict)
    }
    crypto_position = position_by_slot.get(CRYPTO_SLOT)
    metals_position = position_by_slot.get(METALS_SLOT)
    total_pnl = sum(safe_float(trade.get("pnl")) for trade in history)
    drawdown = safe_float(st.session_state.current_drawdown)
    open_count = len(positions)

    k1, k2, k3, k4, k5 = st.columns([1.15, 1, 1, 1, .8])
    with k1:
        render_kpi("Total Balance", f"${balance:,.2f}", f"PnL {total_pnl:+,.2f}")
    with k2:
        render_kpi("Open Positions", open_count, "Crypto + Metals")
    with k3:
        risk_used = max(0.0, drawdown)
        render_kpi("Risk Used", f"{risk_used:.2f}%", f"Limit {MAX_DAILY_LOSS_PCT:.2f}%")
    with k4:
        render_kpi("Markets Scanned", len(st.session_state.crypto_scanner_results), f"Universe {len(SCAN_MARKETS)}")
    with k5:
        render_kpi("AI Signal", st.session_state.crypto_signal, f"{safe_float(st.session_state.crypto_confidence):.1f}%")

    if selected_page == "Command":
        render_section("Compact Professional Command")
        left, center, right = st.columns([1.75, .85, .8])

        with left:
            row1, row2 = st.columns([1.55, .9])
            with row1:
                chart_symbol = st.selectbox("Primary Market", SCAN_MARKETS, key="chart_pair", label_visibility="collapsed")
            with row2:
                ticker = get_cached_ticker(chart_symbol)
                if ticker:
                    change = safe_float(ticker.get("change_pct"))
                    st.caption(f"{chart_symbol}  ${safe_float(ticker.get('last')):,.4f}  {change:+.2f}%")
                else:
                    st.caption(chart_symbol)
            render_quant_chart(chart_symbol)

        with center:
            render_html('<div class="compact-title">Recent Activity</div>')
            recent = list(history[-5:]) if history else []
            if recent:
                activity = []
                for trade in reversed(recent):
                    symbol = escape(trade.get("symbol", "—"))
                    reason = escape(trade.get("reason", "CLOSED"))
                    pnl = safe_float(trade.get("pnl"))
                    cls = "signal-buy" if pnl >= 0 else "signal-sell"
                    activity.append(f'<div class="activity-row"><span>{symbol}<br><span class="{cls}">{pnl:+.2f}</span></span><span class="activity-time">{reason}</span></div>')
                render_html('<div class="panel">' + ''.join(activity) + '</div>')
            else:
                render_html('<div class="panel">No closed activity yet.</div>')

            render_html('<div class="compact-title" style="margin-top:7px;">Decision Core</div>')
            reason = escape(st.session_state.crypto_reason or "Awaiting current scanner decision.")
            render_html(f"""<div class="panel">{badge(st.session_state.crypto_status)} {badge(st.session_state.crypto_signal)}<div style="margin-top:6px;font-size:8px;color:#8c99a4;line-height:1.45;">{reason}</div></div>""")

        with right:
            render_html('<div class="compact-title">Active Positions</div>')
            if positions:
                pos_rows = []
                for p in positions:
                    sym = escape(p.get("symbol", "—"))
                    side = escape(p.get("side", "—"))
                    side_cls = "signal-buy" if str(side).upper() == "LONG" else "signal-sell"
                    pos_rows.append(f'<div class="activity-row"><span>{sym}<br><span class="{side_cls}">{side}</span></span><span class="activity-time">OPEN</span></div>')
                render_html('<div class="panel">' + ''.join(pos_rows) + '</div>')
            else:
                render_html('<div class="panel">Portfolio flat.</div>')

            render_html('<div class="compact-title" style="margin-top:7px;">Risk Overview</div>')
            remaining = max(0.0, MAX_DAILY_LOSS_PCT - drawdown)
            render_html(f"""<div class="panel"><div class="activity-row"><span>Daily Drawdown</span><span>{drawdown:.2f}%</span></div><div class="activity-row"><span>Loss Budget Left</span><span>{remaining:.2f}%</span></div><div class="activity-row"><span>Open Slots</span><span>{open_count}/2</span></div><div class="activity-row"><span>Execution</span><span class="signal-flat">PAPER</span></div></div>""")

        render_section("Scanner Signals / Portfolio Allocation / Performance")
        scan_col, alloc_col, perf_col = st.columns([1.5, .75, .75])
        with scan_col:
            results = st.session_state.crypto_scanner_results
            if results:
                sig_rows = []
                for item in results:
                    signal = str(item.get("signal", "NO TRADE"))
                    if signal == "NO TRADE":
                        continue
                    sig_rows.append({"Symbol": item.get("symbol"), "Signal": signal, "Score": item.get("score"), "Price": item.get("price"), "Action": "CANDIDATE"})
                if sig_rows:
                    st.dataframe(pd.DataFrame(sig_rows[:10]), width="stretch", hide_index=True, height=245)
                else:
                    st.info("No active scanner signals. Quality filters are holding.")
            else:
                st.info("Scanner state warming.")

        with alloc_col:
            crypto_count = 1 if crypto_position else 0
            metal_count = 1 if metals_position else 0
            render_html(f"""<div class="panel" style="min-height:245px;"><div class="panel-title">PORTFOLIO ALLOCATION</div><div class="activity-row"><span>Crypto Slot</span><span>{'OPEN' if crypto_count else 'FREE'}</span></div><div class="activity-row"><span>Metals Slot</span><span>{'OPEN' if metal_count else 'FREE'}</span></div><div class="activity-row"><span>Paper Equity</span><span>${balance:,.0f}</span></div><div class="activity-row"><span>Realized PnL</span><span>{total_pnl:+,.0f}</span></div><div style="margin-top:18px;color:#687987;font-size:8px;line-height:1.45;">Two isolated asset-class slots. Real execution remains hard-disabled.</div></div>""")

        with perf_col:
            wins = sum(1 for t in history if safe_float(t.get("pnl")) > 0)
            losses = sum(1 for t in history if safe_float(t.get("pnl")) < 0)
            closed = len(history)
            win_rate = (wins / closed * 100.0) if closed else 0.0
            render_html(f"""<div class="panel" style="min-height:245px;"><div class="panel-title">PERFORMANCE</div><div class="activity-row"><span>Closed Trades</span><span>{closed}</span></div><div class="activity-row"><span>Wins / Losses</span><span>{wins} / {losses}</span></div><div class="activity-row"><span>Win Rate</span><span>{win_rate:.1f}%</span></div><div class="activity-row"><span>Realized PnL</span><span>{total_pnl:+,.2f}</span></div><div class="activity-row"><span>Daily DD</span><span>{drawdown:.2f}%</span></div></div>""")

    elif selected_page == "Crypto":
        render_section("Crypto Intelligence")
        analytics_symbol = crypto_position.get("symbol") if crypto_position else (st.session_state.crypto_market if st.session_state.crypto_market not in ("", "—") else st.session_state.get("chart_pair", "BTCUSDT"))
        regime = get_regime_data(analytics_symbol)
        intelligence = scanner_intelligence(st.session_state.crypto_scanner_results)
        breadth = intelligence.get("breadth", {}) if isinstance(intelligence, dict) else {}
        m1, m2, m3, m4, m5, m6 = st.columns(6)
        with m1: render_kpi("Market", analytics_symbol, "Primary scanner asset")
        with m2: render_kpi("Regime", regime.get("regime", "UNKNOWN"), regime.get("trend", "UNKNOWN"))
        with m3: render_kpi("ATR", f"{safe_float(regime.get('atr_pct')):.2f}%", "Volatility")
        with m4: render_kpi("Momentum", f"{safe_float(regime.get('momentum')):+.2f}", "Impulse")
        with m5: render_kpi("Bull Breadth", f"{safe_float(breadth.get('bullish_pct')):.1f}%", "Scanner")
        with m6: render_kpi("Bear Breadth", f"{safe_float(breadth.get('bearish_pct')):.1f}%", "Scanner")
        chart_col, model_col = st.columns([2.15, .85])
        with chart_col:
            render_quant_chart(analytics_symbol)
        with model_col:
            render_kpi("AI Score", f"{safe_float(st.session_state.crypto_score):+.1f}", st.session_state.crypto_signal)
            st.markdown("<br>", unsafe_allow_html=True)
            confidence = safe_float(st.session_state.crypto_confidence)
            render_kpi("MTF Confidence", f"{confidence:.1f}%" if confidence > 0 else "—", st.session_state.crypto_status)
        render_section("Crypto Scanner")
        if st.session_state.crypto_scanner_results:
            st.dataframe(pd.DataFrame(st.session_state.crypto_scanner_results), width="stretch", hide_index=True, height=320)
        else:
            runtime_status = str(st.session_state.crypto_status or "STARTING")
            st.info(f"Crypto scanner runtime: {runtime_status}." if runtime_status not in {"STARTING", "WARMING", ""} else "Crypto scanner is warming.")
        show_correlation = st.toggle("Load correlation matrix", value=False, key="show_crypto_correlation", help="On-demand only, to keep the terminal responsive.")
        if show_correlation:
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
            rows = [{"Market": item.get("symbol"), "Signal": item.get("signal"), "Score": item.get("score"), "MTF %": item.get("mtf_confidence"), "1H + 4H": item.get("higher_tf_confirmed"), "Approved": item.get("approved"), "Entry": item.get("entry_price"), "Reason": item.get("reason")} for item in results]
            st.dataframe(pd.DataFrame(rows), width="stretch", hide_index=True)
        else:
            st.info("Metals scanner warming.")
        if st.session_state.metals_best_setup:
            with st.expander("Metals Model Diagnostics"):
                st.json(st.session_state.metals_best_setup)

    elif selected_page == "Positions":
        render_section("Position Flow / Exposure")
        rows = build_position_rows(trader, positions)
        if rows:
            st.dataframe(pd.DataFrame(rows), width="stretch", hide_index=True)
        else:
            st.info("Portfolio is currently flat.")

    elif selected_page == "Scanner":
        render_section("Multi-Asset Scanner")
        crypto_col, metal_col = st.columns([1.75, 1])
        with crypto_col:
            st.markdown("#### Crypto")
            if st.session_state.crypto_scanner_results:
                st.dataframe(pd.DataFrame(st.session_state.crypto_scanner_results), width="stretch", hide_index=True, height=420)
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
        with r1: render_kpi("Day Start Equity", f"${start_balance:,.2f}", "UTC session anchor")
        with r2: render_kpi("Current Equity", f"${balance:,.2f}", "Paper portfolio")
        with r3: render_kpi("Drawdown", f"{drawdown:.2f}%", f"Max {MAX_DAILY_LOSS_PCT:.2f}%")
        with r4: render_kpi("Loss Budget Left", f"{remaining_loss_budget:.2f}%", "BLOCKED" if st.session_state.trading_paused_by_risk else "AVAILABLE")
        st.markdown("<br>", unsafe_allow_html=True)
        st.json(safe_system_health(), expanded=False)

    elif selected_page == "Analytics":
        render_section("Performance Analytics")
        statistics = trade_statistics(history)
        st.json(statistics, expanded=False)
        crypto_history = [t for t in history if str(t.get("asset_class", "")).upper() == "CRYPTO"]
        metal_history = [t for t in history if str(t.get("asset_class", "")).upper() == "METAL"]
        a1, a2, a3 = st.columns(3)
        with a1: render_kpi("Crypto Trades", len(crypto_history), "Closed")
        with a2: render_kpi("Metals Trades", len(metal_history), "Closed")
        with a3: render_kpi("Total Trades", len(history), "All assets")
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
# V5.3 AUTONOMOUS CRYPTO SCANNER / ENTRY RUNTIME
# PostgreSQL advisory lock + persistent snapshot
# No Streamlit API calls inside worker thread
# ============================================================

@st.cache_resource
def start_crypto_autonomous_runtime():
    """
    One autonomous crypto scanner/entry runtime per deployed service.

    Architecture
    ------------
    Background thread
        -> PostgreSQL advisory lock
        -> scan_markets()
        -> confirm_scanner_setup()
        -> open_approved_trade()
        -> PostgreSQL runtime snapshot

    The Streamlit UI only reads the snapshot.
    """

    database_url = os.environ.get(
        "DATABASE_URL",
        "",
    ).strip()

    state = {
        "started": False,
        "thread_alive": False,
        "lock_acquired": False,
        "last_error": None,
        "last_scan_at": None,
        "runtime_version": "V5.7",
    }

    if not database_url:
        state["last_error"] = "DATABASE_URL is not configured"
        print(
            "[CRYPTO AUTONOMOUS] DATABASE_URL is not configured.",
            flush=True,
        )
        return state

    def log(message: Any) -> None:
        print(
            f"[CRYPTO AUTONOMOUS] {message}",
            flush=True,
        )

    def publish_snapshot(
        *,
        status: str,
        market: str = "—",
        signal: str = "NO TRADE",
        score: float = 0.0,
        confidence: float = 0.0,
        reason: str = "",
        scanner_results: Optional[list] = None,
        strategy: Optional[Dict[str, Any]] = None,
        execution: Optional[Dict[str, Any]] = None,
    ) -> None:
        # V5.11: status-only updates (PAUSED / SCANNING / POSITION OPEN) must
        # not erase the last good scanner matrix.  The previous implementation
        # wrote [] whenever scanner_results was omitted, which made a healthy
        # background scanner look like it was permanently "warming" in a new
        # Streamlit session.  Preserve the durable PostgreSQL snapshot instead.
        previous = read_runtime_state("crypto_runtime", {})
        previous_results = previous.get("scanner_results", []) if isinstance(previous, dict) else []
        previous_strategy = previous.get("strategy", {}) if isinstance(previous, dict) else {}
        previous_execution = previous.get("execution", {}) if isinstance(previous, dict) else {}

        durable_results = (
            scanner_results
            if isinstance(scanner_results, list)
            else previous_results if isinstance(previous_results, list) else []
        )
        durable_strategy = (
            strategy
            if isinstance(strategy, dict)
            else previous_strategy if isinstance(previous_strategy, dict) else {}
        )
        durable_execution = (
            execution
            if isinstance(execution, dict)
            else previous_execution if isinstance(previous_execution, dict) else {}
        )

        write_runtime_state(
            "crypto_runtime",
            {
                "runtime_version": "V5.11",
                "status": status,
                "market": market,
                "signal": signal,
                "score": safe_float(score),
                "confidence": safe_float(confidence),
                "reason": str(reason or ""),
                "scanner_results": durable_results,
                "strategy": durable_strategy,
                "execution": durable_execution,
                "scanner_rows": len(durable_results),
                "paper_only": True,
                "real_execution": False,
                "updated_at": utc_now().isoformat(),
            },
        )

    def run_one_scan(
        trader: PaperTrader,
    ) -> None:
        control = get_crypto_control()

        if bool(control.get("paused", False)):
            publish_snapshot(
                status="PAUSED",
                reason="Crypto autonomous runtime paused by operator.",
            )
            return

        position = trader.get_position(
            CRYPTO_SLOT
        )

        if position:
            publish_snapshot(
                status="POSITION OPEN · LIFECYCLE MANAGED",
                market=position.get("symbol", "—"),
                signal=position.get("signal", position.get("side", "NO TRADE")),
                reason=(
                    "Open Crypto position is managed by "
                    "the autonomous lifecycle runtime."
                ),
            )
            return

        scan_started_m = time.monotonic()

        publish_snapshot(
            status="SCANNING",
            reason=(
                f"Autonomous scanner is evaluating "
                f"{len(SCAN_MARKETS)} crypto markets."
            ),
        )

        log(
            f"Scanning {len(SCAN_MARKETS)} crypto markets."
        )

        results = scan_markets()

        scan_seconds = time.monotonic() - scan_started_m

        if not isinstance(results, list):
            results = []

        log(
            f"Scan completed | markets={len(SCAN_MARKETS)} | "
            f"results={len(results)} | duration={scan_seconds:.2f}s"
        )

        summary = scanner_summary(results) or {}

        strongest = summary.get(
            "strongest_market"
        ) or {}

        best_setup = summary.get(
            "best_setup"
        )

        market = strongest.get(
            "symbol",
            "—",
        )

        signal = strongest.get(
            "signal",
            "NO TRADE",
        )

        score = safe_float(
            strongest.get(
                "score"
            )
        )

        reason = strongest.get(
            "reason",
            "",
        )

        if best_setup is None:
            publish_snapshot(
                status="NO QUALIFYING TRADE",
                market=market,
                signal=signal,
                score=score,
                confidence=0.0,
                reason=reason or "Scanner found no qualifying setup.",
                scanner_results=results,
            )
            log(
                f"Cycle completed | market={market} | signal={signal} | "
                f"score={score:+.1f} | status=NO QUALIFYING TRADE"
            )
            return

        confirmation = confirm_scanner_setup(
            best_setup
        ) or {}

        market = best_setup.get(
            "symbol",
            market,
        )

        signal = best_setup.get(
            "signal",
            signal,
        )

        score = safe_float(
            best_setup.get(
                "score",
                score,
            )
        )

        confidence = safe_float(
            confirmation.get(
                "confidence"
            )
        )

        reason = confirmation.get(
            "reason",
            reason,
        )

        if not confirmation.get(
            "approved",
            False,
        ):
            publish_snapshot(
                status="WAITING FOR V5 CONFIRMATION",
                market=market,
                signal=signal,
                score=score,
                confidence=confidence,
                reason=reason,
                scanner_results=results,
                strategy=confirmation,
            )
            diagnostic_reason = str(reason or "V5 strategy did not approve this scanner candidate.").replace("\n", " ").strip()
            strategy_signal = str(confirmation.get("strategy_signal", "NO TRADE"))
            quality = str(confirmation.get("quality", "REJECT"))

            log(
                f"Cycle completed | market={market} | scanner_signal={signal} | "
                f"strategy_signal={strategy_signal} | score={score:+.1f} | "
                f"confidence={confidence:.1f}% | quality={quality} | "
                f"status=WAITING FOR V5 CONFIRMATION | reason={diagnostic_reason}"
            )
            return

        execution_setup = dict(
            best_setup
        )

        execution_setup[
            "strategy_confirmation"
        ] = confirmation

        execution = open_approved_trade(
            trader=trader,
            setup=execution_setup,
        )

        if not isinstance(
            execution,
            dict,
        ):
            execution = {
                "status": "ERROR",
                "reason": "Execution engine returned invalid result.",
            }

        execution_status = str(
            execution.get(
                "status",
                "UNKNOWN",
            )
        ).upper()

        execution_reason = str(
            execution.get(
                "reason",
                reason,
            )
            or reason
        )

        if execution_status == "EXECUTED":
            ui_status = "PAPER TRADE OPENED"

        elif execution_status in (
            "RISK_BLOCKED",
            "RISK_PLAN_REJECTED",
            "REJECTED",
        ):
            ui_status = "TRADE REJECTED BY RISK"

        elif execution_status == "STRATEGY_REJECTED":
            ui_status = "WAITING FOR V5 STRATEGY"

        elif execution_status == "STALE_ENTRY":
            ui_status = "STALE ENTRY SKIPPED"

        elif execution_status == "SKIPPED":
            ui_status = "TRADE SKIPPED"

        elif execution_status == "ERROR":
            ui_status = "ERROR"

        else:
            ui_status = execution_status

        publish_snapshot(
            status=ui_status,
            market=market,
            signal=signal,
            score=score,
            confidence=confidence,
            reason=execution_reason,
            scanner_results=results,
            strategy=confirmation,
            execution=execution,
        )

        log(
            f"{market} | {signal} | "
            f"confidence={confidence:.1f}% | "
            f"execution={execution_status}"
        )

    def worker_loop() -> None:
        lock_connection = None
        trader = None
        state["thread_alive"] = True

        try:
            lock_connection = psycopg.connect(
                database_url,
                autocommit=True,
                connect_timeout=10,
            )

            # Render performs rolling deploys, so the previous web process may
            # legitimately keep the advisory lock for a short handoff window.
            # Do NOT exit permanently when that happens.  Wait and retry until
            # the old owner releases the session-level PostgreSQL lock.  This
            # preserves single-owner execution while preventing the new
            # deployment from becoming permanently idle.
            lock_wait_started = time.monotonic()
            last_wait_log = 0.0

            while True:
                with lock_connection.cursor() as cur:
                    cur.execute(
                        "SELECT pg_try_advisory_lock(%s)",
                        (CRYPTO_RUNTIME_LOCK_ID,),
                    )
                    row = cur.fetchone()

                if bool(row and row[0]):
                    break

                state["last_error"] = "WAITING_FOR_RUNTIME_LOCK"
                waited_seconds = time.monotonic() - lock_wait_started

                # Keep logs useful without flooding Render.
                if last_wait_log <= 0.0 or (
                    time.monotonic() - last_wait_log >= 30.0
                ):
                    log(
                        "Another Crypto runtime currently owns the PostgreSQL "
                        f"advisory lock; waiting for deploy handoff "
                        f"({waited_seconds:.0f}s)."
                    )
                    last_wait_log = time.monotonic()

                time.sleep(5)

            state["lock_acquired"] = True
            state["last_error"] = None
            log(
                "PostgreSQL advisory lock acquired; autonomous scanning active."
            )

            trader = PaperTrader(
                starting_balance=PAPER_BALANCE
            )

            last_scan_monotonic = 0.0
            last_force_nonce = ""

            while True:
                try:
                    control = get_crypto_control()
                    force_nonce = str(
                        control.get(
                            "force_nonce",
                            "",
                        )
                        or ""
                    )

                    paused = bool(
                        control.get(
                            "paused",
                            False,
                        )
                    )

                    now_m = time.monotonic()

                    force_requested = (
                        bool(force_nonce)
                        and force_nonce != last_force_nonce
                    )

                    regular_due = (
                        last_scan_monotonic <= 0
                        or (
                            now_m - last_scan_monotonic
                            >= CRYPTO_RUNTIME_POLL_SECONDS
                        )
                    )

                    if paused:
                        publish_snapshot(
                            status="PAUSED",
                            reason=(
                                "Crypto autonomous runtime "
                                "paused by operator."
                            ),
                        )

                        if force_requested:
                            last_force_nonce = force_nonce

                        time.sleep(
                            CRYPTO_RUNTIME_IDLE_CHECK_SECONDS
                        )
                        continue

                    if force_requested or regular_due:
                        # Anchor cadence before scan so a slow scan does not
                        # add another full poll interval after it completes.
                        last_scan_monotonic = time.monotonic()

                        run_one_scan(
                            trader
                        )

                        state["last_scan_at"] = utc_now().isoformat()
                        state["last_error"] = None

                        if force_requested:
                            last_force_nonce = force_nonce

                    time.sleep(
                        CRYPTO_RUNTIME_IDLE_CHECK_SECONDS
                    )

                except Exception as error:
                    state["last_error"] = str(error)

                    log(
                        f"Cycle error: {error}"
                    )

                    publish_snapshot(
                        status="ERROR",
                        reason=f"Crypto autonomous runtime error: {error}",
                    )

                    time.sleep(10)

        except Exception as error:
            state["last_error"] = str(error)

            log(
                f"Startup error: {error}"
            )

            publish_snapshot(
                status="ERROR",
                reason=f"Crypto autonomous startup error: {error}",
            )

        finally:
            if lock_connection is not None:
                try:
                    with lock_connection.cursor() as cur:
                        cur.execute(
                            "SELECT pg_advisory_unlock(%s)",
                            (CRYPTO_RUNTIME_LOCK_ID,),
                        )
                except Exception:
                    pass

                try:
                    lock_connection.close()
                except Exception:
                    pass

            state["lock_acquired"] = False
            state["thread_alive"] = False

            log("Runtime stopped.")

    ensure_runtime_state_schema()

    # Initialize persistent controls exactly once.
    existing_control = read_runtime_state(
        "crypto_control",
        {},
    )

    if not existing_control:
        write_runtime_state(
            "crypto_control",
            {
                "paused": False,
                "force_nonce": "",
            },
        )

    thread = threading.Thread(
        target=worker_loop,
        name="crypto-autonomous-v5-3",
        daemon=True,
    )

    thread.start()

    state["started"] = True

    return state


_crypto_autonomous_runtime_state = (
    start_crypto_autonomous_runtime()
)


# ============================================================
# V5.5 AUTONOMOUS MULTI-ASSET TRADE LIFECYCLE RUNTIME
# Canonical manager for all already-open PAPER positions
# Existing Render Web Service only — no new paid worker
# ============================================================

@st.cache_resource
def start_trade_lifecycle_runtime():
    """
    Start exactly one durable lifecycle scheduler across deployed processes.

    Responsibilities
    ----------------
    - Manage already-open CRYPTO_MAIN and METALS_MAIN paper positions.
    - Run existing PaperTrader TP/SL checks first.
    - Enforce lifecycle max-hold, break-even, trailing and stale exits.
    - Use the lifecycle engine's PostgreSQL advisory lock so multiple
      Streamlit processes cannot become competing lifecycle authorities.
    - Never call Streamlit APIs from the worker thread.
    - Never open a trade and never place a real order.
    """

    state = {
        "started": False,
        "thread_alive": False,
        "lock_acquired": False,
        "last_cycle_at": None,
        "last_status": "STARTING",
        "last_error": None,
        "runtime_version": "V5.5-LIFECYCLE",
        "cycle_seconds": int(LIFECYCLE_CYCLE_SECONDS),
        "paper_only": True,
    }

    if not os.environ.get("DATABASE_URL", "").strip():
        state["last_status"] = "DISABLED"
        state["last_error"] = "DATABASE_URL is not configured"
        print(
            "[LIFECYCLE RUNTIME] DATABASE_URL is not configured.",
            flush=True,
        )
        return state

    def log(message: Any) -> None:
        print(f"[LIFECYCLE RUNTIME] {message}", flush=True)

    def worker_loop() -> None:
        lock_connection = None
        state["thread_alive"] = True

        try:
            lock_connection = acquire_lifecycle_runtime_lock()

            if lock_connection is None:
                state["last_status"] = "STANDBY"
                state["last_error"] = "LOCK_NOT_ACQUIRED"
                log(
                    "Another deployed process owns the lifecycle lock; "
                    "this process remains standby."
                )
                return

            state["lock_acquired"] = True
            state["last_status"] = "RUNNING"
            state["last_error"] = None
            log("PostgreSQL advisory lock acquired.")

            trader = PaperTrader(starting_balance=PAPER_BALANCE)

            while True:
                cycle_started = time.monotonic()

                try:
                    result = run_lifecycle_cycle(trader)
                    state["last_cycle_at"] = utc_now().isoformat()
                    state["last_status"] = str(result.get("status", "UNKNOWN"))
                    state["last_error"] = None

                    if result.get("positions_evaluated", 0):
                        log(
                            "cycle | "
                            f"status={result.get('status')} | "
                            f"evaluated={result.get('positions_evaluated', 0)} | "
                            f"closed={result.get('positions_closed', 0)}"
                        )

                except Exception as error:
                    state["last_status"] = "ERROR"
                    state["last_error"] = str(error)
                    log(f"Cycle error: {error}")

                elapsed = time.monotonic() - cycle_started
                sleep_seconds = max(
                    1.0,
                    float(LIFECYCLE_CYCLE_SECONDS) - elapsed,
                )
                time.sleep(sleep_seconds)

        except Exception as error:
            state["last_status"] = "ERROR"
            state["last_error"] = str(error)
            log(f"Startup error: {error}")

        finally:
            if lock_connection is not None:
                release_lifecycle_runtime_lock(lock_connection)

            state["lock_acquired"] = False
            state["thread_alive"] = False
            log("Runtime stopped.")

    thread = threading.Thread(
        target=worker_loop,
        name="trade-lifecycle-v5-5",
        daemon=True,
    )
    thread.start()
    state["started"] = True
    state["thread"] = thread
    return state


_trade_lifecycle_runtime_state = start_trade_lifecycle_runtime()


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
    # Gold-API Free allows 10 historical/OHLC requests per hour.
    # Use 9/hour to preserve one-request safety headroom for retries/manual diagnostics.
    internal_hourly_limit = 9
    # 405s spacing => at most 9 automatic requests in a rolling hour.
    request_interval_seconds = 405
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

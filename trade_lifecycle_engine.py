"""
trade_lifecycle_engine.py

PRO AI QUANT TERMINAL V5
AUTONOMOUS MULTI-ASSET TRADE LIFECYCLE ENGINE V1.1

Canonical lifecycle authority for already-open PAPER positions.

Core behavior
-------------
- Existing PaperTrader TP/SL check first.
- Hard max hold: 24h by default.
- Break-even protection in R-multiples.
- Risk-normalized trailing stop.
- Stale/no-progress exit.
- Persistent MFE/MAE lifecycle state in PostgreSQL.
- Important lifecycle events audited in PostgreSQL.
- Runtime PaperTrader signature introspection; no blind method guessing.
- PostgreSQL advisory-lock helpers for exactly-one scheduler runtime.
- Optional strategy invalidation callback for future upgrades.
- PAPER ONLY. REAL EXECUTION HARD DISABLED.

This engine NEVER opens trades.
"""

from __future__ import annotations

import inspect
import math
import os
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Optional, Tuple

import psycopg
from psycopg.rows import dict_row


ENGINE_VERSION = "V1.2 Hold-Time Integrity Lifecycle Engine"
PAPER_ONLY = True
REAL_EXECUTION_ENABLED = False
DATABASE_URL = os.environ.get("DATABASE_URL", "").strip()
LIFECYCLE_RUNTIME_LOCK_ID = 93739002

if REAL_EXECUTION_ENABLED:
    raise RuntimeError("REAL_EXECUTION_ENABLED must remain False.")


def _env_float(name: str, default: float, minimum=None, maximum=None) -> float:
    try:
        value = float(os.environ.get(name, str(default)))
    except (TypeError, ValueError):
        value = float(default)
    if not math.isfinite(value):
        value = float(default)
    if minimum is not None:
        value = max(minimum, value)
    if maximum is not None:
        value = min(maximum, value)
    return value


def _env_int(name: str, default: int, minimum=None, maximum=None) -> int:
    try:
        value = int(os.environ.get(name, str(default)))
    except (TypeError, ValueError):
        value = int(default)
    if minimum is not None:
        value = max(minimum, value)
    if maximum is not None:
        value = min(maximum, value)
    return value


def _env_bool(name: str, default: bool) -> bool:
    raw = os.environ.get(name, "true" if default else "false")
    return raw.strip().lower() in {"1", "true", "yes", "on"}


# ============================================================
# HOLD-TIME INTEGRITY POLICY
# ============================================================
# Strategy modules may use a much shorter *target* hold (for example 3h),
# but that must never be confused with the lifecycle HARD safety ceiling.
#
# The previous V1.1 implementation allowed TRADE_MAX_HOLD_HOURS to reduce
# the hard ceiling all the way to 1h. That made an accidental Render env
# value such as 3 close a perfectly valid intraday position after ~3h and
# label it LIFECYCLE_MAX_HOLD_EXIT.
#
# V1.2 keeps the environment value for diagnostics, but the hard lifecycle
# ceiling is deliberately fixed at 24h. Trades can still close earlier via
# TP, SL, break-even/trailing, stale/no-progress or signal invalidation.
CONFIGURED_MAX_HOLD_HOURS = _env_float(
    "TRADE_MAX_HOLD_HOURS",
    24.0,
    1.0,
    168.0,
)
HARD_MAX_HOLD_HOURS = 24.0
MAX_HOLD_HOURS = HARD_MAX_HOLD_HOURS

if abs(CONFIGURED_MAX_HOLD_HOURS - HARD_MAX_HOLD_HOURS) > 1e-9:
    print(
        "[LIFECYCLE CONFIG] "
        f"TRADE_MAX_HOLD_HOURS={CONFIGURED_MAX_HOLD_HOURS:.2f}h "
        f"does not override the hard safety ceiling; "
        f"effective max hold={HARD_MAX_HOLD_HOURS:.2f}h.",
        flush=True,
    )
BREAK_EVEN_TRIGGER_R = _env_float("TRADE_BREAK_EVEN_TRIGGER_R", 0.75, 0.10, 10.0)
BREAK_EVEN_BUFFER_R = _env_float("TRADE_BREAK_EVEN_BUFFER_R", 0.05, 0.0, 2.0)
TRAILING_TRIGGER_R = _env_float("TRADE_TRAILING_TRIGGER_R", 1.25, 0.20, 20.0)
TRAILING_DISTANCE_R = _env_float("TRADE_TRAILING_DISTANCE_R", 0.75, 0.10, 10.0)
STALE_EXIT_ENABLED = _env_bool("TRADE_STALE_EXIT_ENABLED", True)
STALE_MIN_AGE_HOURS = _env_float("TRADE_STALE_MIN_AGE_HOURS", 8.0, 1.0, 72.0)
STALE_NO_PROGRESS_HOURS = _env_float("TRADE_STALE_NO_PROGRESS_HOURS", 4.0, 1.0, 72.0)
STALE_MAX_MFE_R = _env_float("TRADE_STALE_MAX_MFE_R", 0.40, 0.0, 10.0)
STALE_MAX_CURRENT_R = _env_float("TRADE_STALE_MAX_CURRENT_R", 0.15, -10.0, 10.0)
PROGRESS_EPSILON_R = _env_float("TRADE_PROGRESS_EPSILON_R", 0.05, 0.001, 5.0)
RECOMMENDED_CYCLE_SECONDS = _env_int("TRADE_LIFECYCLE_CYCLE_SECONDS", 60, 15, 900)


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError):
        return default
    return number if math.isfinite(number) else default


def _positive(value: Any, default: float = 0.0) -> float:
    number = _safe_float(value, default)
    return number if number > 0 else default


def _parse_dt(value: Any) -> Optional[datetime]:
    if not value:
        return None
    if isinstance(value, datetime):
        dt = value
    else:
        try:
            dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        except Exception:
            return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _symbol(value: Any) -> str:
    return str(value or "").upper().replace("/", "").replace("-", "").replace(" ", "").strip()


def _asset(value: Any) -> str:
    text = str(value or "").upper().strip()
    aliases = {"METALS": "METAL", "FOREX": "FX", "EQUITIES": "STOCK", "EQUITY": "STOCK", "INDICES": "INDEX", "FUTURE": "FUTURES"}
    return aliases.get(text, text)


def _side(value: Any) -> Optional[str]:
    text = str(value or "").upper().strip()
    return {"BUY": "LONG", "LONG": "LONG", "SELL": "SHORT", "SHORT": "SHORT"}.get(text)


def _position_side(position: Dict[str, Any]) -> Optional[str]:
    return _side(position.get("side") or position.get("signal") or position.get("direction"))


def _position_slot(position: Dict[str, Any]) -> str:
    return str(position.get("slot") or position.get("position_slot") or "").strip()


def _position_opened_at(position: Dict[str, Any]) -> Optional[datetime]:
    for key in ("opened_at", "open_time", "entry_time", "created_at"):
        dt = _parse_dt(position.get(key))
        if dt is not None:
            return dt
    return None


def _connect():
    if not DATABASE_URL:
        raise RuntimeError("DATABASE_URL is required for durable lifecycle management.")
    return psycopg.connect(DATABASE_URL, row_factory=dict_row, connect_timeout=10)


def ensure_lifecycle_tables():
    with _connect() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                CREATE TABLE IF NOT EXISTS trade_lifecycle_state (
                    lifecycle_key TEXT PRIMARY KEY,
                    slot TEXT NOT NULL,
                    asset_class TEXT,
                    symbol TEXT NOT NULL,
                    side TEXT,
                    entry_price DOUBLE PRECISION,
                    original_stop DOUBLE PRECISION,
                    initial_risk_per_unit DOUBLE PRECISION,
                    virtual_stop DOUBLE PRECISION,
                    best_price DOUBLE PRECISION,
                    worst_price DOUBLE PRECISION,
                    mfe_r DOUBLE PRECISION NOT NULL DEFAULT 0,
                    mae_r DOUBLE PRECISION NOT NULL DEFAULT 0,
                    first_seen_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    opened_at TIMESTAMPTZ,
                    last_progress_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    last_evaluated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    break_even_active BOOLEAN NOT NULL DEFAULT FALSE,
                    trailing_active BOOLEAN NOT NULL DEFAULT FALSE,
                    status TEXT NOT NULL DEFAULT 'OPEN',
                    last_action TEXT,
                    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                )
            """)
            cur.execute("""
                CREATE TABLE IF NOT EXISTS trade_lifecycle_events (
                    id BIGSERIAL PRIMARY KEY,
                    lifecycle_key TEXT,
                    slot TEXT,
                    asset_class TEXT,
                    symbol TEXT,
                    side TEXT,
                    event_type TEXT NOT NULL,
                    reason TEXT,
                    price DOUBLE PRECISION,
                    current_r DOUBLE PRECISION,
                    mfe_r DOUBLE PRECISION,
                    mae_r DOUBLE PRECISION,
                    virtual_stop DOUBLE PRECISION,
                    hold_hours DOUBLE PRECISION,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                )
            """)
            cur.execute("CREATE INDEX IF NOT EXISTS idx_trade_lifecycle_events_time ON trade_lifecycle_events (created_at DESC)")
            cur.execute("CREATE INDEX IF NOT EXISTS idx_trade_lifecycle_events_symbol ON trade_lifecycle_events (symbol, created_at DESC)")
            cur.execute("CREATE INDEX IF NOT EXISTS idx_trade_lifecycle_state_status ON trade_lifecycle_state (status, updated_at DESC)")
        conn.commit()


def acquire_lifecycle_runtime_lock():
    if not DATABASE_URL:
        raise RuntimeError("DATABASE_URL is not configured.")
    connection = psycopg.connect(DATABASE_URL, autocommit=True, connect_timeout=10)
    try:
        with connection.cursor() as cur:
            cur.execute("SELECT pg_try_advisory_lock(%s)", (LIFECYCLE_RUNTIME_LOCK_ID,))
            row = cur.fetchone()
        if not (row and row[0]):
            connection.close()
            return None
        return connection
    except Exception:
        try:
            connection.close()
        except Exception:
            pass
        raise


def release_lifecycle_runtime_lock(connection):
    if connection is None:
        return
    try:
        with connection.cursor() as cur:
            cur.execute("SELECT pg_advisory_unlock(%s)", (LIFECYCLE_RUNTIME_LOCK_ID,))
    except Exception:
        pass
    try:
        connection.close()
    except Exception:
        pass


_SEMANTIC_ALIASES = {
    "slot": ("slot", "position_slot"),
    "symbol": ("symbol", "market", "ticker", "pair"),
    "price": ("current_price", "exit_price", "price", "market_price"),
    "reason": ("reason", "close_reason", "exit_reason"),
}


def _parameters(callable_obj) -> Optional[Dict[str, inspect.Parameter]]:
    try:
        return dict(inspect.signature(callable_obj).parameters)
    except (TypeError, ValueError):
        return None


def _call_adapter(obj: Any, method_name: str, semantic_values: Dict[str, Any]) -> Dict[str, Any]:
    method = getattr(obj, method_name, None)
    if not callable(method):
        return {"ok": False, "status": "METHOD_UNAVAILABLE", "reason": f"{method_name} is unavailable."}

    parameters = _parameters(method)
    if parameters is None:
        return {"ok": False, "status": "SIGNATURE_UNAVAILABLE", "reason": f"Cannot inspect {method_name} safely."}

    accepts_kwargs = any(p.kind == inspect.Parameter.VAR_KEYWORD for p in parameters.values())
    kwargs: Dict[str, Any] = {}
    consumed = set()

    for semantic, value in semantic_values.items():
        if value is None or value == "":
            continue
        aliases = _SEMANTIC_ALIASES.get(semantic, (semantic,))
        matched = False
        for alias in aliases:
            if alias in parameters:
                kwargs[alias] = value
                consumed.add(alias)
                matched = True
                break
        if not matched and accepts_kwargs:
            kwargs[aliases[0]] = value
            consumed.add(aliases[0])

    unresolved = []
    for name, parameter in parameters.items():
        if name in consumed or name in {"self", "cls"}:
            continue
        if parameter.kind in {inspect.Parameter.VAR_POSITIONAL, inspect.Parameter.VAR_KEYWORD}:
            continue
        if parameter.default is not inspect.Parameter.empty:
            continue
        unresolved.append(name)

    if unresolved:
        return {"ok": False, "status": "ADAPTER_BLOCKED", "reason": "Required parameters could not be resolved safely.", "unresolved_required": unresolved}

    try:
        return {"ok": True, "status": "CALLED", "result": method(**kwargs), "kwargs": kwargs}
    except Exception as error:
        return {"ok": False, "status": "CALL_ERROR", "reason": str(error), "error_type": type(error).__name__}


def paper_trader_capabilities(trader) -> Dict[str, Any]:
    output = {}
    for name in ("get_positions", "get_position", "update_price", "close_trade", "get_trade_history"):
        method = getattr(trader, name, None)
        output[name] = {"available": callable(method), "parameters": list(_parameters(method) or {}) if callable(method) else []}
    return {"engine": ENGINE_VERSION, "methods": output}


def _position_key(position: Dict[str, Any]) -> str:
    for key in ("trade_id", "position_id", "id"):
        identity = position.get(key)
        if identity not in (None, ""):
            return f"ID|{key}|{identity}"
    slot = _position_slot(position)
    symbol = _symbol(position.get("symbol"))
    opened_at = _position_opened_at(position)
    if opened_at is not None:
        return f"POS|{slot}|{symbol}|{opened_at.isoformat()}"
    entry = _positive(position.get("entry_price"))
    return f"LEGACY|{slot}|{symbol}|{entry:.12g}"


def _record_event(lifecycle_key: str, position: Dict[str, Any], event_type: str, reason: str = "", price=None, current_r=None, mfe_r=None, mae_r=None, virtual_stop=None, hold_hours=None):
    try:
        ensure_lifecycle_tables()
        with _connect() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    INSERT INTO trade_lifecycle_events (
                        lifecycle_key, slot, asset_class, symbol, side,
                        event_type, reason, price, current_r, mfe_r, mae_r,
                        virtual_stop, hold_hours
                    ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                """, (
                    lifecycle_key,
                    _position_slot(position),
                    _asset(position.get("asset_class")),
                    _symbol(position.get("symbol")),
                    _position_side(position),
                    event_type,
                    reason,
                    price,
                    current_r,
                    mfe_r,
                    mae_r,
                    virtual_stop,
                    hold_hours,
                ))
            conn.commit()
    except Exception:
        pass


def _load_state(key: str) -> Optional[Dict[str, Any]]:
    ensure_lifecycle_tables()
    with _connect() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT * FROM trade_lifecycle_state WHERE lifecycle_key=%s", (key,))
            row = cur.fetchone()
    return dict(row) if row else None


def _save_state(state: Dict[str, Any]):
    ensure_lifecycle_tables()
    with _connect() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO trade_lifecycle_state (
                    lifecycle_key, slot, asset_class, symbol, side,
                    entry_price, original_stop, initial_risk_per_unit,
                    virtual_stop, best_price, worst_price, mfe_r, mae_r,
                    first_seen_at, opened_at, last_progress_at,
                    last_evaluated_at, break_even_active, trailing_active,
                    status, last_action, updated_at
                ) VALUES (
                    %s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,NOW()
                )
                ON CONFLICT (lifecycle_key) DO UPDATE SET
                    virtual_stop=EXCLUDED.virtual_stop,
                    best_price=EXCLUDED.best_price,
                    worst_price=EXCLUDED.worst_price,
                    mfe_r=EXCLUDED.mfe_r,
                    mae_r=EXCLUDED.mae_r,
                    last_progress_at=EXCLUDED.last_progress_at,
                    last_evaluated_at=EXCLUDED.last_evaluated_at,
                    break_even_active=EXCLUDED.break_even_active,
                    trailing_active=EXCLUDED.trailing_active,
                    status=EXCLUDED.status,
                    last_action=EXCLUDED.last_action,
                    updated_at=NOW()
            """, (
                state["lifecycle_key"], state["slot"], state["asset_class"], state["symbol"], state["side"],
                state["entry_price"], state["original_stop"], state["initial_risk_per_unit"], state["virtual_stop"],
                state["best_price"], state["worst_price"], state["mfe_r"], state["mae_r"], state["first_seen_at"],
                state["opened_at"], state["last_progress_at"], state["last_evaluated_at"], state["break_even_active"],
                state["trailing_active"], state["status"], state["last_action"],
            ))
        conn.commit()


def _ensure_state(position: Dict[str, Any]) -> Dict[str, Any]:
    key = _position_key(position)
    existing = _load_state(key)
    if existing:
        return existing

    now = _utc_now()
    entry = _positive(position.get("entry_price"))
    stop = _positive(position.get("stop_loss"))
    opened_at = _position_opened_at(position) or now
    state = {
        "lifecycle_key": key,
        "slot": _position_slot(position),
        "asset_class": _asset(position.get("asset_class")),
        "symbol": _symbol(position.get("symbol")),
        "side": _position_side(position),
        "entry_price": entry,
        "original_stop": stop,
        "initial_risk_per_unit": abs(entry - stop),
        "virtual_stop": stop,
        "best_price": entry,
        "worst_price": entry,
        "mfe_r": 0.0,
        "mae_r": 0.0,
        "first_seen_at": now,
        "opened_at": opened_at,
        "last_progress_at": now,
        "last_evaluated_at": now,
        "break_even_active": False,
        "trailing_active": False,
        "status": "OPEN",
        "last_action": "INITIALIZED",
    }
    _save_state(state)
    _record_event(key, position, "INITIALIZED", "Lifecycle state created.")
    return state


def _get_current_price(position: Dict[str, Any]) -> Optional[float]:
    symbol = _symbol(position.get("symbol"))
    asset_class = _asset(position.get("asset_class"))
    try:
        if asset_class == "METAL":
            from metals_trade_engine import get_metals_current_price
            price = get_metals_current_price(symbol)
        else:
            from trade_engine import get_current_price
            price = get_current_price(symbol)
    except Exception:
        return None
    price = _positive(price)
    return price if price > 0 else None


def _hold_clock(position: Dict[str, Any], state: Dict[str, Any]) -> Dict[str, Any]:
    """
    Return a trustworthy UTC hold clock.

    Authority order:
      1. PaperTrader's current persisted position.opened_at (source of truth)
      2. lifecycle state's persisted opened_at
      3. lifecycle first_seen_at fallback

    This prevents stale lifecycle state or a recycled state row from making a
    newly-opened position appear older than it really is.
    """
    now = _utc_now()
    position_opened = _position_opened_at(position)
    state_opened = _parse_dt(state.get("opened_at"))
    first_seen = _parse_dt(state.get("first_seen_at"))

    opened_at = position_opened or state_opened or first_seen
    source = (
        "PAPER_POSITION_OPENED_AT" if position_opened is not None
        else "LIFECYCLE_STATE_OPENED_AT" if state_opened is not None
        else "LIFECYCLE_FIRST_SEEN" if first_seen is not None
        else "UNAVAILABLE"
    )

    if opened_at is None:
        return {
            "hours": 0.0,
            "opened_at": None,
            "source": source,
            "valid": False,
        }

    # A future timestamp should never trigger a close. Treat it as invalid
    # clock data instead of silently manufacturing an age.
    delta_seconds = (now - opened_at).total_seconds()
    if delta_seconds < -60.0:
        return {
            "hours": 0.0,
            "opened_at": opened_at,
            "source": source,
            "valid": False,
            "reason": "opened_at is in the future",
        }

    return {
        "hours": max(0.0, delta_seconds / 3600.0),
        "opened_at": opened_at,
        "source": source,
        "valid": True,
    }


def _age_hours(state: Dict[str, Any]) -> float:
    # Backward-compatible helper used by stale logic. Lifecycle state is safe
    # here because manage_position refreshes it from the live position clock.
    opened_at = _parse_dt(state.get("opened_at")) or _parse_dt(state.get("first_seen_at"))
    if opened_at is None:
        return 0.0
    return max(0.0, (_utc_now() - opened_at).total_seconds() / 3600.0)


def _current_r(side: str, entry: float, price: float, risk: float) -> float:
    if risk <= 0:
        return 0.0
    if side == "LONG":
        return (price - entry) / risk
    if side == "SHORT":
        return (entry - price) / risk
    return 0.0


def _update_excursions(state: Dict[str, Any], price: float) -> Dict[str, Any]:
    now = _utc_now()
    side = state.get("side")
    entry = _positive(state.get("entry_price"))
    risk = _positive(state.get("initial_risk_per_unit"))
    best = _positive(state.get("best_price"), entry)
    worst = _positive(state.get("worst_price"), entry)
    previous_mfe = _safe_float(state.get("mfe_r"))

    if side == "LONG":
        best = max(best, price)
        worst = min(worst, price)
        mfe_r = (best - entry) / risk if risk > 0 else 0.0
        mae_r = (entry - worst) / risk if risk > 0 else 0.0
    elif side == "SHORT":
        best = min(best, price)
        worst = max(worst, price)
        mfe_r = (entry - best) / risk if risk > 0 else 0.0
        mae_r = (worst - entry) / risk if risk > 0 else 0.0
    else:
        mfe_r = mae_r = 0.0

    mfe_r = max(0.0, mfe_r)
    mae_r = max(0.0, mae_r)
    last_progress = state.get("last_progress_at")
    if mfe_r >= previous_mfe + PROGRESS_EPSILON_R:
        last_progress = now

    state.update({
        "best_price": best,
        "worst_price": worst,
        "mfe_r": mfe_r,
        "mae_r": mae_r,
        "last_progress_at": last_progress,
        "last_evaluated_at": now,
    })
    return state


def _virtual_stop(state: Dict[str, Any]) -> Tuple[float, bool, bool]:
    side = state.get("side")
    entry = _positive(state.get("entry_price"))
    risk = _positive(state.get("initial_risk_per_unit"))
    original_stop = _positive(state.get("original_stop"))
    best = _positive(state.get("best_price"), entry)
    mfe_r = _safe_float(state.get("mfe_r"))
    stop = _positive(state.get("virtual_stop"), original_stop)
    be = bool(state.get("break_even_active"))
    trailing = bool(state.get("trailing_active"))

    if entry <= 0 or risk <= 0 or original_stop <= 0 or side not in {"LONG", "SHORT"}:
        return stop, be, trailing

    if mfe_r >= BREAK_EVEN_TRIGGER_R:
        be = True
        candidate = entry + BREAK_EVEN_BUFFER_R * risk if side == "LONG" else entry - BREAK_EVEN_BUFFER_R * risk
        stop = max(stop, candidate) if side == "LONG" else min(stop, candidate)

    if mfe_r >= TRAILING_TRIGGER_R:
        trailing = True
        candidate = best - TRAILING_DISTANCE_R * risk if side == "LONG" else best + TRAILING_DISTANCE_R * risk
        stop = max(stop, candidate) if side == "LONG" else min(stop, candidate)

    return stop, be, trailing


def _stop_hit(side: str, price: float, stop: float) -> bool:
    if price <= 0 or stop <= 0:
        return False
    return price <= stop if side == "LONG" else price >= stop if side == "SHORT" else False


def _stale_due(state: Dict[str, Any], current_r: float) -> Dict[str, Any]:
    if not STALE_EXIT_ENABLED or _age_hours(state) < STALE_MIN_AGE_HOURS:
        return {"exit": False}
    last_progress = _parse_dt(state.get("last_progress_at"))
    if last_progress is None:
        return {"exit": False}
    no_progress = (_utc_now() - last_progress).total_seconds() / 3600.0
    mfe_r = _safe_float(state.get("mfe_r"))
    exit_due = no_progress >= STALE_NO_PROGRESS_HOURS and mfe_r <= STALE_MAX_MFE_R and current_r <= STALE_MAX_CURRENT_R
    return {"exit": exit_due, "no_progress_hours": no_progress, "mfe_r": mfe_r, "current_r": current_r}


def _strategy_exit(evaluator: Optional[Callable], position: Dict[str, Any], price: float) -> Dict[str, Any]:
    if evaluator is None:
        return {"exit": False}
    try:
        result = evaluator(position, price)
    except Exception as error:
        return {"exit": False, "error": str(error)}
    if not isinstance(result, dict):
        return {"exit": False}
    return {"exit": bool(result.get("exit", False)), "reason": str(result.get("reason", "Strategy invalidated trade.")), "raw": result}


def _base_tp_sl_check(trader, position: Dict[str, Any], price: float) -> Dict[str, Any]:
    adapter = _call_adapter(trader, "update_price", {
        "slot": _position_slot(position),
        "symbol": _symbol(position.get("symbol")),
        "price": price,
    })
    if not adapter["ok"]:
        return {"checked": False, "closed": False, "adapter": adapter}
    result = adapter.get("result")
    closed = isinstance(result, dict) and str(result.get("status", "")).upper() == "CLOSED"
    return {"checked": True, "closed": closed, "result": result, "adapter": adapter}


def _close_position(trader, position: Dict[str, Any], price: float, reason: str) -> Dict[str, Any]:
    if not PAPER_ONLY or REAL_EXECUTION_ENABLED:
        return {"ok": False, "status": "HARD_LOCK", "reason": "Real execution is disabled."}
    adapter = _call_adapter(trader, "close_trade", {
        "slot": _position_slot(position),
        "symbol": _symbol(position.get("symbol")),
        "price": price,
        "reason": reason,
    })
    if not adapter["ok"]:
        return {"ok": False, "status": adapter.get("status", "ADAPTER_BLOCKED"), "reason": adapter.get("reason", "Unable to close safely."), "adapter": adapter}
    return {"ok": True, "status": "CALLED", "raw": adapter.get("result"), "adapter": adapter}


def _mark_closed(state: Dict[str, Any], action: str):
    state["status"] = "CLOSED"
    state["last_action"] = action
    state["last_evaluated_at"] = _utc_now()
    _save_state(state)


def manage_position(trader, position: Dict[str, Any], strategy_invalidation_evaluator: Optional[Callable] = None) -> Dict[str, Any]:
    key = _position_key(position)
    state = _ensure_state(position)

    # Reconcile lifecycle time with the authoritative PaperTrader position on
    # every cycle. This is intentionally narrow: only opened_at is refreshed.
    # Entry/SL/TP/risk geometry remains untouched.
    authoritative_opened_at = _position_opened_at(position)
    if authoritative_opened_at is not None:
        persisted_opened_at = _parse_dt(state.get("opened_at"))
        if (
            persisted_opened_at is None
            or abs((persisted_opened_at - authoritative_opened_at).total_seconds()) > 1.0
        ):
            state["opened_at"] = authoritative_opened_at
            _save_state(state)
            _record_event(
                key,
                position,
                "HOLD_CLOCK_RECONCILED",
                "Lifecycle opened_at reconciled to PaperTrader position opened_at.",
            )

    side = _position_side(position) or _side(state.get("side"))
    entry = _positive(position.get("entry_price") or state.get("entry_price"))
    original_stop = _positive(position.get("stop_loss") or state.get("original_stop"))
    risk = _positive(state.get("initial_risk_per_unit"))

    if side not in {"LONG", "SHORT"} or entry <= 0 or original_stop <= 0 or risk <= 0:
        return {"status": "INVALID_POSITION", "symbol": _symbol(position.get("symbol")), "reason": "Cannot determine side/entry/stop/risk safely."}

    price = _get_current_price(position)
    if price is None:
        return {"status": "WAITING_FOR_PRICE", "symbol": _symbol(position.get("symbol"))}

    base = _base_tp_sl_check(trader, position, price)
    if base.get("closed"):
        _mark_closed(state, "BASE_TP_SL_CLOSE")
        _record_event(key, position, "BASE_TP_SL_CLOSE", "Existing PaperTrader TP/SL closed trade.", price=price)
        return {"status": "CLOSED", "action": "BASE_TP_SL_CLOSE", "result": base}

    state = _update_excursions(state, price)
    current_r = _current_r(side, entry, price, risk)

    hold_clock = _hold_clock(position, state)
    hold_hours = _safe_float(hold_clock.get("hours"))

    # HARD time exit is permitted only from a valid clock and only at the
    # fixed 24h lifecycle ceiling. Shorter strategy target-hold values are
    # informational and must not become hard forced exits.
    if hold_clock.get("valid") and hold_hours >= HARD_MAX_HOLD_HOURS:
        result = _close_position(trader, position, price, "LIFECYCLE_MAX_HOLD_EXIT")
        if result["ok"]:
            _mark_closed(state, "TIME_EXIT")
        _record_event(
            key,
            position,
            "TIME_EXIT",
            (
                f"Hard maximum hold {HARD_MAX_HOLD_HOURS:.1f}h reached "
                f"using {hold_clock.get('source')}."
            ),
            price,
            current_r,
            state.get("mfe_r"),
            state.get("mae_r"),
            state.get("virtual_stop"),
            hold_hours,
        )
        return {
            "status": "CLOSED" if result["ok"] else "CLOSE_BLOCKED",
            "action": "TIME_EXIT",
            "result": result,
            "hold_hours": hold_hours,
            "max_hold_hours": HARD_MAX_HOLD_HOURS,
            "hold_clock_source": hold_clock.get("source"),
            "opened_at": (
                hold_clock.get("opened_at").isoformat()
                if hold_clock.get("opened_at") is not None
                else None
            ),
        }

    invalidation = _strategy_exit(strategy_invalidation_evaluator, position, price)
    if invalidation.get("exit"):
        result = _close_position(trader, position, price, "LIFECYCLE_SIGNAL_INVALIDATION")
        if result["ok"]:
            _mark_closed(state, "SIGNAL_INVALIDATION")
        _record_event(key, position, "SIGNAL_INVALIDATION", invalidation.get("reason", "Strategy invalidated trade."), price, current_r, state.get("mfe_r"), state.get("mae_r"), state.get("virtual_stop"), hold_hours)
        return {"status": "CLOSED" if result["ok"] else "CLOSE_BLOCKED", "action": "SIGNAL_INVALIDATION", "result": result}

    old_stop = _positive(state.get("virtual_stop"), original_stop)
    new_stop, be, trailing = _virtual_stop(state)
    state["virtual_stop"] = new_stop
    state["break_even_active"] = be
    state["trailing_active"] = trailing

    if abs(new_stop - old_stop) > 1e-12:
        action = "TRAIL" if trailing else "BREAK_EVEN" if be else "STOP_UPDATE"
        state["last_action"] = action
        _record_event(key, position, action, "Virtual lifecycle stop tightened.", price, current_r, state.get("mfe_r"), state.get("mae_r"), new_stop, hold_hours)

    if _stop_hit(side, price, new_stop):
        action = "LIFECYCLE_TRAILING_EXIT" if trailing else "LIFECYCLE_BREAK_EVEN_EXIT" if be else "LIFECYCLE_VIRTUAL_STOP_EXIT"
        result = _close_position(trader, position, price, action)
        if result["ok"]:
            _mark_closed(state, action)
        _record_event(key, position, action, "Virtual lifecycle stop reached.", price, current_r, state.get("mfe_r"), state.get("mae_r"), new_stop, hold_hours)
        return {"status": "CLOSED" if result["ok"] else "CLOSE_BLOCKED", "action": action, "result": result}

    stale = _stale_due(state, current_r)
    if stale.get("exit"):
        result = _close_position(trader, position, price, "LIFECYCLE_STALE_EXIT")
        if result["ok"]:
            _mark_closed(state, "STALE_EXIT")
        _record_event(key, position, "STALE_EXIT", "Insufficient favorable progress.", price, current_r, state.get("mfe_r"), state.get("mae_r"), new_stop, hold_hours)
        return {"status": "CLOSED" if result["ok"] else "CLOSE_BLOCKED", "action": "STALE_EXIT", "result": result, "stale": stale}

    state["status"] = "OPEN"
    state["last_action"] = "HOLD"
    _save_state(state)
    return {
        "status": "OPEN",
        "action": "HOLD",
        "symbol": state["symbol"],
        "slot": state["slot"],
        "side": side,
        "entry_price": entry,
        "current_price": price,
        "current_r": current_r,
        "mfe_r": state["mfe_r"],
        "mae_r": state["mae_r"],
        "virtual_stop": new_stop,
        "break_even_active": be,
        "trailing_active": trailing,
        "hold_hours": hold_hours,
        "max_hold_hours": HARD_MAX_HOLD_HOURS,
        "configured_max_hold_hours": CONFIGURED_MAX_HOLD_HOURS,
        "hold_clock_source": hold_clock.get("source"),
        "hold_clock_valid": bool(hold_clock.get("valid")),
        "base_tp_sl_checked": base.get("checked"),
        "paper_only": True,
    }


def _get_positions(trader) -> List[Dict[str, Any]]:
    method = getattr(trader, "get_positions", None)
    if not callable(method):
        return []
    try:
        positions = method()
    except Exception:
        return []
    if isinstance(positions, dict):
        positions = positions.get("open_positions") or positions.get("positions") or []
    return [item for item in positions if isinstance(item, dict)] if isinstance(positions, list) else []


def reconcile_lifecycle_states(trader) -> Dict[str, Any]:
    ensure_lifecycle_tables()
    positions = _get_positions(trader)
    open_keys = {_position_key(position) for position in positions}
    closed = []
    with _connect() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT lifecycle_key FROM trade_lifecycle_state WHERE status='OPEN'")
            for row in cur.fetchall():
                key = row["lifecycle_key"]
                if key not in open_keys:
                    cur.execute("UPDATE trade_lifecycle_state SET status='CLOSED', last_action='RECONCILED_CLOSED', last_evaluated_at=NOW(), updated_at=NOW() WHERE lifecycle_key=%s", (key,))
                    closed.append(key)
        conn.commit()
    return {"ok": True, "open_position_count": len(positions), "reconciled_closed_count": len(closed)}


def run_lifecycle_cycle(trader, strategy_invalidation_evaluator: Optional[Callable] = None) -> Dict[str, Any]:
    if not PAPER_ONLY or REAL_EXECUTION_ENABLED:
        return {"ok": False, "status": "HARD_LOCK", "reason": "Real execution disabled."}
    try:
        ensure_lifecycle_tables()
    except Exception as error:
        return {"ok": False, "status": "DATABASE_ERROR", "reason": str(error)}

    positions = _get_positions(trader)
    results = []
    errors = []

    for position in positions:
        try:
            result = manage_position(trader, position, strategy_invalidation_evaluator)
        except Exception as error:
            result = {"status": "ERROR", "symbol": position.get("symbol"), "reason": str(error), "error_type": type(error).__name__}
        results.append(result)
        if result.get("status") in {"ERROR", "INVALID_POSITION", "CLOSE_BLOCKED"}:
            errors.append(result)

    try:
        reconciliation = reconcile_lifecycle_states(trader)
    except Exception:
        reconciliation = None

    return {
        "ok": not errors,
        "status": "FLAT" if not positions else "OK" if not errors else "DEGRADED",
        "positions_evaluated": len(positions),
        "positions_closed": sum(1 for item in results if item.get("status") == "CLOSED"),
        "positions_open": sum(1 for item in results if item.get("status") == "OPEN"),
        "errors": errors,
        "results": results,
        "reconciliation": reconciliation,
        "timestamp": _utc_now().isoformat(),
        "paper_only": True,
        "real_execution": False,
    }


def get_lifecycle_snapshot(limit: int = 100) -> Dict[str, Any]:
    ensure_lifecycle_tables()
    limit = max(1, min(int(limit), 500))
    with _connect() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT * FROM trade_lifecycle_state ORDER BY updated_at DESC LIMIT %s", (limit,))
            states = cur.fetchall()
            cur.execute("SELECT * FROM trade_lifecycle_events ORDER BY created_at DESC LIMIT %s", (limit,))
            events = cur.fetchall()
    return {"ok": True, "engine": ENGINE_VERSION, "states": [dict(row) for row in states], "events": [dict(row) for row in events], "paper_only": True}


def trade_lifecycle_health(trader=None) -> Dict[str, Any]:
    result = {
        "ok": True,
        "engine": ENGINE_VERSION,
        "paper_only": True,
        "real_execution_locked": True,
        "max_hold_hours": HARD_MAX_HOLD_HOURS,
        "configured_max_hold_hours": CONFIGURED_MAX_HOLD_HOURS,
        "hard_max_hold_locked": True,
        "hold_clock_authority": "PaperTrader position.opened_at",
        "break_even_trigger_r": BREAK_EVEN_TRIGGER_R,
        "break_even_buffer_r": BREAK_EVEN_BUFFER_R,
        "trailing_trigger_r": TRAILING_TRIGGER_R,
        "trailing_distance_r": TRAILING_DISTANCE_R,
        "stale_exit_enabled": STALE_EXIT_ENABLED,
        "stale_min_age_hours": STALE_MIN_AGE_HOURS,
        "stale_no_progress_hours": STALE_NO_PROGRESS_HOURS,
        "recommended_cycle_seconds": RECOMMENDED_CYCLE_SECONDS,
        "runtime_lock_id": LIFECYCLE_RUNTIME_LOCK_ID,
        "adapter_safe": True,
        "signature_introspection": True,
        "mfe_tracking": True,
        "mae_tracking": True,
        "strategy_invalidation_hook": True,
        "restart_safe": bool(DATABASE_URL),
    }
    try:
        ensure_lifecycle_tables()
        result["database"] = "ONLINE"
    except Exception as error:
        result["ok"] = False
        result["database"] = "ERROR"
        result["reason"] = str(error)
    if trader is not None:
        result["paper_trader"] = paper_trader_capabilities(trader)
    return result

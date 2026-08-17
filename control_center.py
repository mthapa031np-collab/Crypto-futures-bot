"""
PRO AI QUANT TERMINAL V3
Central Control Center

Purpose
-------
One central, safe configuration layer for:
- Crypto engine
- Metals engine
- Paper/live execution protection
- Risk controls
- Scanner controls
- MTF thresholds
- Runtime status
- Environment/API readiness
- PostgreSQL health
- Persistent settings

IMPORTANT:
This module does NOT place trades.
It only manages configuration and system/control state.
"""

from __future__ import annotations

import json
import os
import threading
from copy import deepcopy
from dataclasses import asdict, dataclass, fields
from datetime import datetime, timezone
from typing import Any, Dict, Optional


# ============================================================
# HELPERS
# ============================================================

_LOCK = threading.RLock()


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _env_bool(name: str, default: bool) -> bool:
    value = os.getenv(name)

    if value is None:
        return default

    return value.strip().lower() in {
        "1",
        "true",
        "yes",
        "y",
        "on",
        "enabled",
    }


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, str(default)))
    except (TypeError, ValueError):
        return default


def _env_float(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, str(default)))
    except (TypeError, ValueError):
        return default


def _clamp(value: float, minimum: float, maximum: float) -> float:
    return max(minimum, min(maximum, value))


def _mask_secret(value: Optional[str]) -> str:
    if not value:
        return "NOT SET"

    value = str(value).strip()

    if len(value) <= 6:
        return "SET"

    return f"{value[:3]}***{value[-3:]}"


# ============================================================
# CENTRAL V3 SETTINGS MODEL
# ============================================================

@dataclass
class V3Settings:

    # --------------------------------------------------------
    # MASTER CONTROL
    # --------------------------------------------------------
    global_pause: bool = False

    crypto_enabled: bool = True
    metals_enabled: bool = True

    # Hard safety architecture:
    # Paper mode stays ON by default.
    paper_trading: bool = True

    # Real execution is intentionally disabled by default.
    real_execution_enabled: bool = False

    # Extra hard lock.
    # Even if real_execution_enabled is accidentally changed,
    # execution remains blocked while this is True.
    live_trading_hard_lock: bool = True

    # --------------------------------------------------------
    # POSITION CONTROL
    # --------------------------------------------------------
    max_open_positions: int = 2
    max_crypto_positions: int = 1
    max_metals_positions: int = 1

    # --------------------------------------------------------
    # RISK CONTROL
    # --------------------------------------------------------
    crypto_risk_pct: float = 1.0
    metals_risk_pct: float = 0.50

    max_daily_loss_pct: float = 3.0
    max_total_drawdown_pct: float = 10.0

    # Stop opening new trades after consecutive losses.
    max_consecutive_losses: int = 3

    # --------------------------------------------------------
    # CRYPTO SCANNER
    # --------------------------------------------------------
    crypto_scan_seconds: int = 60

    crypto_min_score: float = 65.0
    crypto_min_mtf_confidence: float = 60.0

    # --------------------------------------------------------
    # METALS SCANNER
    # --------------------------------------------------------
    metals_scan_seconds: int = 60

    metals_min_score: float = 65.0
    metals_min_mtf_confidence: float = 65.0

    # --------------------------------------------------------
    # DYNAMIC METALS RISK
    # --------------------------------------------------------
    metals_atr_stop_multiplier: float = 1.5
    metals_atr_target_multiplier: float = 2.5

    metals_break_even_rr: float = 1.0
    metals_trailing_start_rr: float = 1.5
    metals_trailing_atr_multiplier: float = 1.0

    # --------------------------------------------------------
    # CRYPTO POSITION MANAGEMENT
    # --------------------------------------------------------
    crypto_break_even_rr: float = 1.0
    crypto_trailing_start_rr: float = 1.5

    # --------------------------------------------------------
    # DATA / ENGINE SAFETY
    # --------------------------------------------------------
    require_fresh_market_data: bool = True
    max_market_data_age_seconds: int = 120

    require_mtf_confirmation: bool = True

    # Prevent scanner from instantly opening another trade
    # after a position has just closed.
    trade_cooldown_seconds: int = 300

    # --------------------------------------------------------
    # UI / CONTROL
    # --------------------------------------------------------
    ui_refresh_seconds: int = 15

    show_advanced_diagnostics: bool = True

    # --------------------------------------------------------
    # METADATA
    # --------------------------------------------------------
    config_version: str = "V3.1"
    updated_at: str = ""


# ============================================================
# DEFAULT SETTINGS
# ============================================================

def default_settings() -> V3Settings:
    """
    Build safe defaults.

    Existing Render environment variables can still influence
    initial defaults, but saved Control Center settings take
    priority once persistence is available.
    """

    paper_mode = _env_bool("PAPER_TRADING", True)

    settings = V3Settings(
        global_pause=False,

        crypto_enabled=True,
        metals_enabled=True,

        paper_trading=paper_mode,

        # NEVER automatically enable live execution from a
        # generic environment variable.
        real_execution_enabled=False,
        live_trading_hard_lock=True,

        max_open_positions=2,
        max_crypto_positions=1,
        max_metals_positions=1,

        crypto_risk_pct=_env_float(
            "RISK_PCT",
            1.0,
        ),

        metals_risk_pct=_env_float(
            "METALS_RISK_PCT",
            0.50,
        ),

        max_daily_loss_pct=_env_float(
            "MAX_DAILY_LOSS_PCT",
            3.0,
        ),

        crypto_scan_seconds=_env_int(
            "POLL_SECONDS",
            60,
        ),

        metals_scan_seconds=_env_int(
            "METALS_POLL_SECONDS",
            60,
        ),
    )

    return validate_settings(settings)


# ============================================================
# VALIDATION
# ============================================================

def validate_settings(settings: V3Settings) -> V3Settings:
    """
    Normalize and validate every important setting.

    This protects the engine against unsafe or malformed values
    coming from UI, environment variables or database records.
    """

    s = deepcopy(settings)

    # ---------------------------
    # Position limits
    # ---------------------------

    s.max_open_positions = int(
        _clamp(
            int(s.max_open_positions),
            1,
            10,
        )
    )

    s.max_crypto_positions = int(
        _clamp(
            int(s.max_crypto_positions),
            0,
            s.max_open_positions,
        )
    )

    s.max_metals_positions = int(
        _clamp(
            int(s.max_metals_positions),
            0,
            s.max_open_positions,
        )
    )

    # ---------------------------
    # Risk limits
    # ---------------------------

    s.crypto_risk_pct = round(
        _clamp(
            float(s.crypto_risk_pct),
            0.10,
            5.00,
        ),
        2,
    )

    s.metals_risk_pct = round(
        _clamp(
            float(s.metals_risk_pct),
            0.10,
            3.00,
        ),
        2,
    )

    s.max_daily_loss_pct = round(
        _clamp(
            float(s.max_daily_loss_pct),
            0.50,
            20.00,
        ),
        2,
    )

    s.max_total_drawdown_pct = round(
        _clamp(
            float(s.max_total_drawdown_pct),
            1.00,
            50.00,
        ),
        2,
    )

    s.max_consecutive_losses = int(
        _clamp(
            int(s.max_consecutive_losses),
            1,
            20,
        )
    )

    # ---------------------------
    # Scanner timing
    # ---------------------------

    s.crypto_scan_seconds = int(
        _clamp(
            int(s.crypto_scan_seconds),
            15,
            3600,
        )
    )

    s.metals_scan_seconds = int(
        _clamp(
            int(s.metals_scan_seconds),
            15,
            3600,
        )
    )

    # ---------------------------
    # Signal thresholds
    # ---------------------------

    s.crypto_min_score = round(
        _clamp(
            float(s.crypto_min_score),
            0,
            100,
        ),
        1,
    )

    s.crypto_min_mtf_confidence = round(
        _clamp(
            float(s.crypto_min_mtf_confidence),
            0,
            100,
        ),
        1,
    )

    s.metals_min_score = round(
        _clamp(
            float(s.metals_min_score),
            0,
            100,
        ),
        1,
    )

    s.metals_min_mtf_confidence = round(
        _clamp(
            float(s.metals_min_mtf_confidence),
            0,
            100,
        ),
        1,
    )

    # ---------------------------
    # ATR / position management
    # ---------------------------

    s.metals_atr_stop_multiplier = round(
        _clamp(
            float(s.metals_atr_stop_multiplier),
            0.50,
            5.00,
        ),
        2,
    )

    s.metals_atr_target_multiplier = round(
        _clamp(
            float(s.metals_atr_target_multiplier),
            0.50,
            10.00,
        ),
        2,
    )

    s.metals_break_even_rr = round(
        _clamp(
            float(s.metals_break_even_rr),
            0.25,
            5.00,
        ),
        2,
    )

    s.metals_trailing_start_rr = round(
        _clamp(
            float(s.metals_trailing_start_rr),
            0.50,
            10.00,
        ),
        2,
    )

    s.metals_trailing_atr_multiplier = round(
        _clamp(
            float(s.metals_trailing_atr_multiplier),
            0.25,
            5.00,
        ),
        2,
    )

    s.crypto_break_even_rr = round(
        _clamp(
            float(s.crypto_break_even_rr),
            0.25,
            5.00,
        ),
        2,
    )

    s.crypto_trailing_start_rr = round(
        _clamp(
            float(s.crypto_trailing_start_rr),
            0.50,
            10.00,
        ),
        2,
    )

    # ---------------------------
    # Data freshness
    # ---------------------------

    s.max_market_data_age_seconds = int(
        _clamp(
            int(s.max_market_data_age_seconds),
            15,
            3600,
        )
    )

    s.trade_cooldown_seconds = int(
        _clamp(
            int(s.trade_cooldown_seconds),
            0,
            86400,
        )
    )

    s.ui_refresh_seconds = int(
        _clamp(
            int(s.ui_refresh_seconds),
            5,
            300,
        )
    )

    # ---------------------------
    # CRITICAL LIVE SAFETY
    # ---------------------------

    if s.paper_trading:
        s.real_execution_enabled = False

    if s.live_trading_hard_lock:
        s.real_execution_enabled = False

    s.updated_at = utc_now_iso()

    return s


# ============================================================
# SERIALIZATION
# ============================================================

def settings_to_dict(settings: V3Settings) -> Dict[str, Any]:
    return asdict(settings)


def settings_from_dict(data: Dict[str, Any]) -> V3Settings:
    """
    Safely load only fields that actually exist in V3Settings.

    This means future/old database records do not crash the app.
    """

    allowed = {field.name for field in fields(V3Settings)}

    clean = {
        key: value
        for key, value in data.items()
        if key in allowed
    }

    defaults = asdict(default_settings())
    defaults.update(clean)

    return validate_settings(
        V3Settings(**defaults)
    )


# ============================================================
# DATABASE SUPPORT
# ============================================================

def _database_url() -> str:
    return os.getenv("DATABASE_URL", "").strip()


def _connect_database():
    """
    Supports psycopg v3 first and psycopg2 as fallback.
    """

    url = _database_url()

    if not url:
        raise RuntimeError(
            "DATABASE_URL is not configured."
        )

    try:
        import psycopg

        return psycopg.connect(url)

    except ImportError:
        try:
            import psycopg2

            return psycopg2.connect(url)

        except ImportError as exc:
            raise RuntimeError(
                "PostgreSQL driver not installed."
            ) from exc


def ensure_control_table() -> bool:
    """
    Create one-row V3 control table if it does not exist.
    """

    if not _database_url():
        return False

    conn = None

    try:
        conn = _connect_database()

        with conn.cursor() as cur:
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS v3_control_center (
                    id INTEGER PRIMARY KEY,
                    settings_json TEXT NOT NULL,
                    updated_at TIMESTAMPTZ NOT NULL
                )
                """
            )

        conn.commit()
        return True

    except Exception:
        if conn:
            try:
                conn.rollback()
            except Exception:
                pass

        return False

    finally:
        if conn:
            try:
                conn.close()
            except Exception:
                pass


# ============================================================
# IN-MEMORY CACHE
# ============================================================

_SETTINGS_CACHE: Optional[V3Settings] = None


# ============================================================
# LOAD SETTINGS
# ============================================================

def load_settings(
    force_reload: bool = False,
) -> V3Settings:

    global _SETTINGS_CACHE

    with _LOCK:

        if (
            _SETTINGS_CACHE is not None
            and not force_reload
        ):
            return deepcopy(_SETTINGS_CACHE)

        fallback = default_settings()

        if not _database_url():
            _SETTINGS_CACHE = fallback
            return deepcopy(fallback)

        if not ensure_control_table():
            _SETTINGS_CACHE = fallback
            return deepcopy(fallback)

        conn = None

        try:
            conn = _connect_database()

            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT settings_json
                    FROM v3_control_center
                    WHERE id = 1
                    """
                )

                row = cur.fetchone()

            if not row:
                save_settings(fallback)
                _SETTINGS_CACHE = fallback
                return deepcopy(fallback)

            raw = row[0]

            if isinstance(raw, str):
                data = json.loads(raw)
            else:
                data = raw

            loaded = settings_from_dict(data)

            _SETTINGS_CACHE = loaded

            return deepcopy(loaded)

        except Exception:
            _SETTINGS_CACHE = fallback
            return deepcopy(fallback)

        finally:
            if conn:
                try:
                    conn.close()
                except Exception:
                    pass


# ============================================================
# SAVE SETTINGS
# ============================================================

def save_settings(
    settings: V3Settings,
) -> V3Settings:

    global _SETTINGS_CACHE

    with _LOCK:

        validated = validate_settings(settings)

        _SETTINGS_CACHE = validated

        if not _database_url():
            return deepcopy(validated)

        if not ensure_control_table():
            return deepcopy(validated)

        payload = json.dumps(
            settings_to_dict(validated),
            separators=(",", ":"),
        )

        conn = None

        try:
            conn = _connect_database()

            with conn.cursor() as cur:

                cur.execute(
                    """
                    INSERT INTO v3_control_center (
                        id,
                        settings_json,
                        updated_at
                    )
                    VALUES (
                        1,
                        %s,
                        NOW()
                    )
                    ON CONFLICT (id)
                    DO UPDATE SET
                        settings_json = EXCLUDED.settings_json,
                        updated_at = NOW()
                    """,
                    (payload,),
                )

            conn.commit()

        except Exception:
            if conn:
                try:
                    conn.rollback()
                except Exception:
                    pass

        finally:
            if conn:
                try:
                    conn.close()
                except Exception:
                    pass

        return deepcopy(validated)


# ============================================================
# UPDATE SELECTED SETTINGS
# ============================================================

def update_settings(
    **changes: Any,
) -> V3Settings:

    current = load_settings()

    allowed = {
        field.name
        for field in fields(V3Settings)
    }

    for key, value in changes.items():

        if key not in allowed:
            raise ValueError(
                f"Unknown V3 setting: {key}"
            )

        setattr(
            current,
            key,
            value,
        )

    return save_settings(current)


# ============================================================
# MASTER ENGINE CONTROL
# ============================================================

def pause_all_engines() -> V3Settings:
    return update_settings(
        global_pause=True,
    )


def resume_all_engines() -> V3Settings:
    return update_settings(
        global_pause=False,
    )


def enable_crypto() -> V3Settings:
    return update_settings(
        crypto_enabled=True,
    )


def disable_crypto() -> V3Settings:
    return update_settings(
        crypto_enabled=False,
    )


def enable_metals() -> V3Settings:
    return update_settings(
        metals_enabled=True,
    )


def disable_metals() -> V3Settings:
    return update_settings(
        metals_enabled=False,
    )


# ============================================================
# EXECUTION SAFETY
# ============================================================

def live_execution_allowed(
    settings: Optional[V3Settings] = None,
) -> bool:

    s = settings or load_settings()

    return bool(
        not s.global_pause
        and not s.paper_trading
        and s.real_execution_enabled
        and not s.live_trading_hard_lock
    )


def paper_execution_allowed(
    settings: Optional[V3Settings] = None,
) -> bool:

    s = settings or load_settings()

    return bool(
        not s.global_pause
        and s.paper_trading
    )


# ============================================================
# ENGINE READINESS
# ============================================================

def crypto_engine_allowed(
    settings: Optional[V3Settings] = None,
) -> bool:

    s = settings or load_settings()

    return bool(
        not s.global_pause
        and s.crypto_enabled
    )


def metals_engine_allowed(
    settings: Optional[V3Settings] = None,
) -> bool:

    s = settings or load_settings()

    return bool(
        not s.global_pause
        and s.metals_enabled
    )


# ============================================================
# ENVIRONMENT READINESS
# ============================================================

def environment_status() -> Dict[str, Any]:

    database_url = os.getenv(
        "DATABASE_URL",
        "",
    )

    twelve_key = (
        os.getenv("TWELVE_DATA_API_KEY")
        or os.getenv("METALS_API_KEY")
        or ""
    )

    exchange = os.getenv(
        "EXCHANGE",
        "",
    )

    api_key = (
        os.getenv("API_KEY")
        or os.getenv("BYBIT_API_KEY")
        or ""
    )

    api_secret = (
        os.getenv("API_SECRET")
        or os.getenv("BYBIT_API_SECRET")
        or ""
    )

    return {
        "database": {
            "configured": bool(database_url),
            "status": (
                "CONFIGURED"
                if database_url
                else "NOT SET"
            ),
        },

        "metals_data": {
            "configured": bool(twelve_key),
            "provider": (
                "Twelve Data / Metals Provider"
            ),
            "api_key": _mask_secret(
                twelve_key
            ),
        },

        "exchange": {
            "name": exchange or "NOT SET",
            "api_key": _mask_secret(
                api_key
            ),
            "api_secret": (
                "SET"
                if api_secret
                else "NOT SET"
            ),
        },
    }


# ============================================================
# DATABASE HEALTH
# ============================================================

def database_health() -> Dict[str, Any]:

    if not _database_url():
        return {
            "ok": False,
            "status": "NOT CONFIGURED",
            "message": (
                "DATABASE_URL is missing."
            ),
        }

    conn = None

    try:
        conn = _connect_database()

        with conn.cursor() as cur:
            cur.execute("SELECT 1")
            result = cur.fetchone()

        ok = bool(
            result
            and result[0] == 1
        )

        return {
            "ok": ok,
            "status": (
                "ONLINE"
                if ok
                else "ERROR"
            ),
            "message": (
                "PostgreSQL responding."
                if ok
                else "Unexpected database response."
            ),
        }

    except Exception as exc:

        return {
            "ok": False,
            "status": "ERROR",
            "message": str(exc)[:250],
        }

    finally:
        if conn:
            try:
                conn.close()
            except Exception:
                pass


# ============================================================
# COMPLETE CONTROL CENTER SNAPSHOT
# ============================================================

def control_center_snapshot() -> Dict[str, Any]:

    settings = load_settings()

    db = database_health()
    env = environment_status()

    return {
        "timestamp": utc_now_iso(),

        "version": settings.config_version,

        "mode": (
            "PAPER"
            if settings.paper_trading
            else "LIVE-ARMED"
        ),

        "global_pause": (
            settings.global_pause
        ),

        "crypto_engine": {
            "enabled": settings.crypto_enabled,
            "allowed": crypto_engine_allowed(
                settings
            ),
            "risk_pct": (
                settings.crypto_risk_pct
            ),
            "scan_seconds": (
                settings.crypto_scan_seconds
            ),
            "min_score": (
                settings.crypto_min_score
            ),
            "min_mtf": (
                settings.crypto_min_mtf_confidence
            ),
        },

        "metals_engine": {
            "enabled": settings.metals_enabled,
            "allowed": metals_engine_allowed(
                settings
            ),
            "risk_pct": (
                settings.metals_risk_pct
            ),
            "scan_seconds": (
                settings.metals_scan_seconds
            ),
            "min_score": (
                settings.metals_min_score
            ),
            "min_mtf": (
                settings.metals_min_mtf_confidence
            ),
        },

        "execution": {
            "paper_allowed": (
                paper_execution_allowed(
                    settings
                )
            ),
            "live_allowed": (
                live_execution_allowed(
                    settings
                )
            ),
            "hard_lock": (
                settings.live_trading_hard_lock
            ),
        },

        "risk": {
            "daily_loss_limit_pct": (
                settings.max_daily_loss_pct
            ),
            "total_drawdown_limit_pct": (
                settings.max_total_drawdown_pct
            ),
            "max_positions": (
                settings.max_open_positions
            ),
            "max_crypto_positions": (
                settings.max_crypto_positions
            ),
            "max_metals_positions": (
                settings.max_metals_positions
            ),
            "max_consecutive_losses": (
                settings.max_consecutive_losses
            ),
        },

        "database": db,
        "environment": env,

        "updated_at": settings.updated_at,
    }


# ============================================================
# SAFE RESET
# ============================================================

def reset_to_safe_defaults() -> V3Settings:
    """
    Reset V3 Control Center only.

    Does NOT delete:
    - positions
    - trade history
    - paper balance
    - analytics
    """

    safe = default_settings()

    safe.paper_trading = True
    safe.real_execution_enabled = False
    safe.live_trading_hard_lock = True
    safe.global_pause = False

    return save_settings(safe)


# ============================================================
# DEBUG / LOCAL CHECK
# ============================================================

if __name__ == "__main__":

    settings = load_settings()

    print(
        json.dumps(
            control_center_snapshot(),
            indent=2,
            default=str,
        )
    )

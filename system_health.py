"""
system_health.py

PRO AI QUANT TERMINAL V5.0
UNIFIED SYSTEM HEALTH & RUNTIME OBSERVABILITY ENGINE

Purpose
-------
One central health authority for:

- PostgreSQL
- Crypto paper execution
- Metals paper execution
- Portfolio Risk Governor
- Metals bootstrap
- Metals OHLC engine
- Runtime heartbeats
- Scanner state
- Provider/API state
- Future AI Decision Fusion
- Future OpenTelemetry / OTLP integration

Design
------
Every engine can publish runtime state here.

The dashboard and future AI engine can ask:

    Is the system healthy?
    Is data fresh?
    Is a worker alive?
    Is bootstrap rate-limited?
    Is trading allowed?
    Which subsystem is degraded?
    When did it last succeed?

This module DOES NOT place trades.

PAPER ONLY.
REAL EXECUTION DISABLED.
"""

from __future__ import annotations

import json
import os
import socket
import time
from datetime import datetime, timezone
from typing import Any, Dict, Optional

import psycopg
from psycopg.rows import dict_row


# ============================================================
# CONFIG
# ============================================================

DATABASE_URL = os.environ.get(
    "DATABASE_URL",
    "",
).strip()


SERVICE_NAME = os.environ.get(
    "RENDER_SERVICE_NAME",
    os.environ.get(
        "SERVICE_NAME",
        "pro-ai-quant-terminal",
    ),
).strip()


SERVICE_ID = os.environ.get(
    "RENDER_SERVICE_ID",
    "",
).strip()


INSTANCE_ID = (
    os.environ.get(
        "RENDER_INSTANCE_ID",
        "",
    ).strip()
    or socket.gethostname()
)


DEPLOY_COMMIT = os.environ.get(
    "RENDER_GIT_COMMIT",
    "",
).strip()


ENVIRONMENT = os.environ.get(
    "ENVIRONMENT",
    "production",
).strip()


# ============================================================
# HEALTH THRESHOLDS
# ============================================================

WORKER_STALE_SECONDS = int(
    os.environ.get(
        "WORKER_STALE_SECONDS",
        "300",
    )
)

SCANNER_STALE_SECONDS = int(
    os.environ.get(
        "SCANNER_STALE_SECONDS",
        "300",
    )
)

PROVIDER_STALE_SECONDS = int(
    os.environ.get(
        "PROVIDER_STALE_SECONDS",
        "180",
    )
)

DATABASE_TIMEOUT_SECONDS = int(
    os.environ.get(
        "DATABASE_HEALTH_TIMEOUT_SECONDS",
        "5",
    )
)


# ============================================================
# HARD SAFETY
# ============================================================

PAPER_ONLY = True
REAL_EXECUTION_ENABLED = False


# ============================================================
# COMPONENT NAMES
# ============================================================

COMPONENT_WEB = "WEB"
COMPONENT_CRYPTO_ENGINE = "CRYPTO_ENGINE"
COMPONENT_METALS_ENGINE = "METALS_ENGINE"
COMPONENT_METALS_BOOTSTRAP = "METALS_BOOTSTRAP"
COMPONENT_METALS_SCANNER = "METALS_SCANNER"
COMPONENT_CRYPTO_SCANNER = "CRYPTO_SCANNER"
COMPONENT_METALS_PROVIDER = "METALS_PROVIDER"
COMPONENT_CRYPTO_PROVIDER = "CRYPTO_PROVIDER"
COMPONENT_RISK_GOVERNOR = "PORTFOLIO_RISK_GOVERNOR"
COMPONENT_AI_FUSION = "AI_DECISION_FUSION"


# ============================================================
# STATUS LEVELS
# ============================================================

STATUS_HEALTHY = "HEALTHY"
STATUS_DEGRADED = "DEGRADED"
STATUS_BLOCKED = "BLOCKED"
STATUS_OFFLINE = "OFFLINE"
STATUS_WARMING_UP = "WARMING_UP"
STATUS_RATE_LIMITED = "RATE_LIMITED"
STATUS_UNKNOWN = "UNKNOWN"


# ============================================================
# BASIC HELPERS
# ============================================================

def _utc_now() -> datetime:
    return datetime.now(
        timezone.utc
    )


def _iso_now() -> str:
    return _utc_now().isoformat()


def _safe_float(
    value,
    default=0.0,
):

    try:
        if value is None:
            return default

        number = float(value)

        if number != number:
            return default

        return number

    except (
        TypeError,
        ValueError,
    ):
        return default


def _safe_int(
    value,
    default=0,
):

    try:
        if value is None:
            return default

        return int(value)

    except (
        TypeError,
        ValueError,
    ):
        return default


def _parse_datetime(
    value,
) -> Optional[datetime]:

    if not value:
        return None

    if isinstance(
        value,
        datetime,
    ):
        dt = value

    else:

        try:

            dt = datetime.fromisoformat(
                str(value).replace(
                    "Z",
                    "+00:00",
                )
            )

        except Exception:
            return None

    if dt.tzinfo is None:

        dt = dt.replace(
            tzinfo=timezone.utc
        )

    return dt


def _age_seconds(
    value,
) -> Optional[float]:

    dt = _parse_datetime(
        value
    )

    if dt is None:
        return None

    return max(
        0.0,
        (
            _utc_now()
            - dt
        ).total_seconds(),
    )


def _json_dumps(
    value,
) -> str:

    return json.dumps(
        value,
        default=str,
        separators=(
            ",",
            ":",
        ),
    )


# ============================================================
# DATABASE
# ============================================================

def _connect():

    if not DATABASE_URL:

        raise RuntimeError(
            "DATABASE_URL is not configured."
        )

    return psycopg.connect(
        DATABASE_URL,
        row_factory=dict_row,
        connect_timeout=DATABASE_TIMEOUT_SECONDS,
    )


# ============================================================
# SCHEMA
# ============================================================

def ensure_system_health_tables():
    """
    Idempotent runtime-state schema.

    Safe across repeated deploys.
    Existing data is preserved.
    """

    with _connect() as conn:

        with conn.cursor() as cur:

            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS runtime_state (
                    component TEXT PRIMARY KEY,

                    status TEXT NOT NULL
                        DEFAULT 'UNKNOWN',

                    message TEXT,

                    payload JSONB NOT NULL
                        DEFAULT '{}'::jsonb,

                    success BOOLEAN NOT NULL
                        DEFAULT FALSE,

                    last_success_at TIMESTAMPTZ,

                    last_error_at TIMESTAMPTZ,

                    heartbeat_at TIMESTAMPTZ NOT NULL
                        DEFAULT NOW(),

                    updated_at TIMESTAMPTZ NOT NULL
                        DEFAULT NOW(),

                    instance_id TEXT,

                    service_name TEXT,

                    deploy_commit TEXT
                )
                """
            )

            cur.execute(
                """
                CREATE INDEX IF NOT EXISTS
                idx_runtime_state_heartbeat

                ON runtime_state (
                    heartbeat_at
                )
                """
            )

            cur.execute(
                """
                CREATE INDEX IF NOT EXISTS
                idx_runtime_state_status

                ON runtime_state (
                    status
                )
                """
            )

            # ---------------------------------------------
            # RUNTIME EVENTS
            # ---------------------------------------------

            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS runtime_events (
                    id BIGSERIAL PRIMARY KEY,

                    component TEXT NOT NULL,

                    event_type TEXT NOT NULL,

                    severity TEXT NOT NULL,

                    message TEXT,

                    payload JSONB NOT NULL
                        DEFAULT '{}'::jsonb,

                    created_at TIMESTAMPTZ NOT NULL
                        DEFAULT NOW(),

                    instance_id TEXT,

                    deploy_commit TEXT
                )
                """
            )

            cur.execute(
                """
                CREATE INDEX IF NOT EXISTS
                idx_runtime_events_component_time

                ON runtime_events (
                    component,
                    created_at DESC
                )
                """
            )

            cur.execute(
                """
                CREATE INDEX IF NOT EXISTS
                idx_runtime_events_time

                ON runtime_events (
                    created_at DESC
                )
                """
            )

        conn.commit()


# ============================================================
# DATABASE HEALTH
# ============================================================

def database_health() -> Dict:

    started = time.perf_counter()

    try:

        ensure_system_health_tables()

        with _connect() as conn:

            with conn.cursor() as cur:

                cur.execute(
                    """
                    SELECT
                        NOW() AS database_time,
                        current_database() AS database_name
                    """
                )

                row = cur.fetchone()

        latency_ms = (
            time.perf_counter()
            - started
        ) * 1000

        return {
            "ok":
                True,

            "status":
                STATUS_HEALTHY,

            "latency_ms":
                round(
                    latency_ms,
                    2,
                ),

            "database_time":
                (
                    row["database_time"].isoformat()
                    if row
                    and row.get(
                        "database_time"
                    )
                    else None
                ),

            "database_name":
                (
                    row.get(
                        "database_name"
                    )
                    if row
                    else None
                ),
        }

    except Exception as error:

        return {
            "ok":
                False,

            "status":
                STATUS_OFFLINE,

            "reason":
                str(error),
        }


# ============================================================
# EVENT LOGGING
# ============================================================

def record_runtime_event(
    component: str,
    event_type: str,
    *,
    severity: str = "INFO",
    message: str = "",
    payload: Optional[Dict] = None,
) -> Dict:

    component = (
        str(component)
        .upper()
        .strip()
    )

    event_type = (
        str(event_type)
        .upper()
        .strip()
    )

    severity = (
        str(severity)
        .upper()
        .strip()
    )

    payload = (
        payload
        if isinstance(
            payload,
            dict,
        )
        else {}
    )

    try:

        ensure_system_health_tables()

        with _connect() as conn:

            with conn.cursor() as cur:

                cur.execute(
                    """
                    INSERT INTO runtime_events (
                        component,
                        event_type,
                        severity,
                        message,
                        payload,
                        created_at,
                        instance_id,
                        deploy_commit
                    )

                    VALUES (
                        %s,
                        %s,
                        %s,
                        %s,
                        %s::jsonb,
                        NOW(),
                        %s,
                        %s
                    )
                    """,
                    (
                        component,
                        event_type,
                        severity,
                        str(message),
                        _json_dumps(
                            payload
                        ),
                        INSTANCE_ID,
                        DEPLOY_COMMIT,
                    ),
                )

            conn.commit()

        return {
            "ok":
                True,
        }

    except Exception as error:

        print(
            "[SYSTEM HEALTH EVENT ERROR] "
            f"{component}: {error}",
            flush=True,
        )

        return {
            "ok":
                False,

            "reason":
                str(error),
        }


# ============================================================
# RUNTIME STATE UPDATE
# ============================================================

def update_runtime_state(
    component: str,
    *,
    status: str,
    success: bool,
    message: str = "",
    payload: Optional[Dict] = None,
) -> Dict:

    component = (
        str(component)
        .upper()
        .strip()
    )

    status = (
        str(status)
        .upper()
        .strip()
    )

    payload = (
        payload
        if isinstance(
            payload,
            dict,
        )
        else {}
    )

    now = _utc_now()

    last_success_at = (
        now
        if success
        else None
    )

    last_error_at = (
        now
        if not success
        else None
    )

    try:

        ensure_system_health_tables()

        with _connect() as conn:

            with conn.cursor() as cur:

                cur.execute(
                    """
                    INSERT INTO runtime_state (
                        component,
                        status,
                        message,
                        payload,
                        success,
                        last_success_at,
                        last_error_at,
                        heartbeat_at,
                        updated_at,
                        instance_id,
                        service_name,
                        deploy_commit
                    )

                    VALUES (
                        %s,
                        %s,
                        %s,
                        %s::jsonb,
                        %s,
                        %s,
                        %s,
                        %s,
                        %s,
                        %s,
                        %s,
                        %s
                    )

                    ON CONFLICT (
                        component
                    )

                    DO UPDATE SET

                        status =
                            EXCLUDED.status,

                        message =
                            EXCLUDED.message,

                        payload =
                            EXCLUDED.payload,

                        success =
                            EXCLUDED.success,

                        last_success_at =
                            CASE
                                WHEN EXCLUDED.success
                                THEN EXCLUDED.last_success_at
                                ELSE runtime_state.last_success_at
                            END,

                        last_error_at =
                            CASE
                                WHEN EXCLUDED.success
                                THEN runtime_state.last_error_at
                                ELSE EXCLUDED.last_error_at
                            END,

                        heartbeat_at =
                            EXCLUDED.heartbeat_at,

                        updated_at =
                            EXCLUDED.updated_at,

                        instance_id =
                            EXCLUDED.instance_id,

                        service_name =
                            EXCLUDED.service_name,

                        deploy_commit =
                            EXCLUDED.deploy_commit
                    """,
                    (
                        component,
                        status,
                        str(message),
                        _json_dumps(
                            payload
                        ),
                        bool(success),
                        last_success_at,
                        last_error_at,
                        now,
                        now,
                        INSTANCE_ID,
                        SERVICE_NAME,
                        DEPLOY_COMMIT,
                    ),
                )

            conn.commit()

        return {
            "ok":
                True,

            "component":
                component,

            "status":
                status,

            "heartbeat_at":
                now.isoformat(),
        }

    except Exception as error:

        print(
            "[SYSTEM HEALTH STATE ERROR] "
            f"{component}: {error}",
            flush=True,
        )

        return {
            "ok":
                False,

            "reason":
                str(error),
        }


# ============================================================
# SIMPLE HEARTBEAT
# ============================================================

def heartbeat(
    component: str,
    *,
    message: str = "alive",
    payload: Optional[Dict] = None,
) -> Dict:

    return update_runtime_state(
        component,
        status=STATUS_HEALTHY,
        success=True,
        message=message,
        payload=payload,
    )


# ============================================================
# FAILURE / DEGRADED HELPERS
# ============================================================

def report_degraded(
    component: str,
    *,
    message: str,
    payload: Optional[Dict] = None,
) -> Dict:

    result = update_runtime_state(
        component,
        status=STATUS_DEGRADED,
        success=False,
        message=message,
        payload=payload,
    )

    record_runtime_event(
        component,
        "DEGRADED",
        severity="WARNING",
        message=message,
        payload=payload,
    )

    return result


def report_error(
    component: str,
    *,
    message: str,
    payload: Optional[Dict] = None,
) -> Dict:

    result = update_runtime_state(
        component,
        status=STATUS_OFFLINE,
        success=False,
        message=message,
        payload=payload,
    )

    record_runtime_event(
        component,
        "ERROR",
        severity="ERROR",
        message=message,
        payload=payload,
    )

    return result


def report_rate_limited(
    component: str,
    *,
    message: str,
    payload: Optional[Dict] = None,
) -> Dict:

    result = update_runtime_state(
        component,
        status=STATUS_RATE_LIMITED,
        success=False,
        message=message,
        payload=payload,
    )

    record_runtime_event(
        component,
        "RATE_LIMITED",
        severity="WARNING",
        message=message,
        payload=payload,
    )

    return result


def report_warming_up(
    component: str,
    *,
    message: str,
    payload: Optional[Dict] = None,
) -> Dict:

    return update_runtime_state(
        component,
        status=STATUS_WARMING_UP,
        success=True,
        message=message,
        payload=payload,
    )


# ============================================================
# READ COMPONENT STATE
# ============================================================

def get_runtime_state(
    component: str,
) -> Optional[Dict]:

    ensure_system_health_tables()

    component = (
        str(component)
        .upper()
        .strip()
    )

    with _connect() as conn:

        with conn.cursor() as cur:

            cur.execute(
                """
                SELECT
                    component,
                    status,
                    message,
                    payload,
                    success,
                    last_success_at,
                    last_error_at,
                    heartbeat_at,
                    updated_at,
                    instance_id,
                    service_name,
                    deploy_commit

                FROM runtime_state

                WHERE component = %s
                """,
                (
                    component,
                ),
            )

            row = cur.fetchone()

    if not row:
        return None

    return {
        "component":
            row["component"],

        "status":
            row["status"],

        "message":
            row["message"],

        "payload":
            row["payload"]
            or {},

        "success":
            bool(
                row["success"]
            ),

        "last_success_at":
            (
                row[
                    "last_success_at"
                ].isoformat()
                if row[
                    "last_success_at"
                ]
                else None
            ),

        "last_error_at":
            (
                row[
                    "last_error_at"
                ].isoformat()
                if row[
                    "last_error_at"
                ]
                else None
            ),

        "heartbeat_at":
            (
                row[
                    "heartbeat_at"
                ].isoformat()
                if row[
                    "heartbeat_at"
                ]
                else None
            ),

        "updated_at":
            (
                row[
                    "updated_at"
                ].isoformat()
                if row[
                    "updated_at"
                ]
                else None
            ),

        "instance_id":
            row[
                "instance_id"
            ],

        "service_name":
            row[
                "service_name"
            ],

        "deploy_commit":
            row[
                "deploy_commit"
            ],
    }


# ============================================================
# ALL STATES
# ============================================================

def get_all_runtime_states() -> Dict:

    ensure_system_health_tables()

    with _connect() as conn:

        with conn.cursor() as cur:

            cur.execute(
                """
                SELECT
                    component,
                    status,
                    message,
                    payload,
                    success,
                    last_success_at,
                    last_error_at,
                    heartbeat_at,
                    updated_at,
                    instance_id,
                    service_name,
                    deploy_commit

                FROM runtime_state

                ORDER BY component ASC
                """
            )

            rows = cur.fetchall()

    result = {}

    for row in rows:

        component = row[
            "component"
        ]

        heartbeat_at = row[
            "heartbeat_at"
        ]

        age = _age_seconds(
            heartbeat_at
        )

        result[
            component
        ] = {
            "status":
                row[
                    "status"
                ],

            "message":
                row[
                    "message"
                ],

            "payload":
                row[
                    "payload"
                ]
                or {},

            "success":
                bool(
                    row[
                        "success"
                    ]
                ),

            "heartbeat_at":
                (
                    heartbeat_at.isoformat()
                    if heartbeat_at
                    else None
                ),

            "heartbeat_age_seconds":
                (
                    round(
                        age,
                        1,
                    )
                    if age is not None
                    else None
                ),

            "last_success_at":
                (
                    row[
                        "last_success_at"
                    ].isoformat()
                    if row[
                        "last_success_at"
                    ]
                    else None
                ),

            "last_error_at":
                (
                    row[
                        "last_error_at"
                    ].isoformat()
                    if row[
                        "last_error_at"
                    ]
                    else None
                ),

            "instance_id":
                row[
                    "instance_id"
                ],

            "service_name":
                row[
                    "service_name"
                ],

            "deploy_commit":
                row[
                    "deploy_commit"
                ],
        }

    return result


# ============================================================
# RECENT EVENTS
# ============================================================

def get_recent_runtime_events(
    limit: int = 50,
) -> list:

    ensure_system_health_tables()

    limit = max(
        1,
        min(
            _safe_int(
                limit,
                50,
            ),
            500,
        ),
    )

    with _connect() as conn:

        with conn.cursor() as cur:

            cur.execute(
                """
                SELECT
                    id,
                    component,
                    event_type,
                    severity,
                    message,
                    payload,
                    created_at,
                    instance_id,
                    deploy_commit

                FROM runtime_events

                ORDER BY created_at DESC

                LIMIT %s
                """,
                (
                    limit,
                ),
            )

            rows = cur.fetchall()

    return [
        {
            "id":
                row[
                    "id"
                ],

            "component":
                row[
                    "component"
                ],

            "event_type":
                row[
                    "event_type"
                ],

            "severity":
                row[
                    "severity"
                ],

            "message":
                row[
                    "message"
                ],

            "payload":
                row[
                    "payload"
                ]
                or {},

            "created_at":
                row[
                    "created_at"
                ].isoformat(),

            "instance_id":
                row[
                    "instance_id"
                ],

            "deploy_commit":
                row[
                    "deploy_commit"
                ],
        }

        for row in rows
    ]


# ============================================================
# STALENESS RULES
# ============================================================

def _component_stale_limit(
    component: str,
) -> int:

    component = (
        str(component)
        .upper()
    )

    if "SCANNER" in component:
        return SCANNER_STALE_SECONDS

    if "PROVIDER" in component:
        return PROVIDER_STALE_SECONDS

    return WORKER_STALE_SECONDS


def evaluate_component_health(
    state: Optional[Dict],
) -> Dict:

    if not state:

        return {
            "effective_status":
                STATUS_UNKNOWN,

            "healthy":
                False,

            "reason":
                "No runtime state recorded.",
        }

    component = state.get(
        "component",
        "UNKNOWN",
    )

    stored_status = str(
        state.get(
            "status",
            STATUS_UNKNOWN,
        )
    ).upper()

    heartbeat_at = state.get(
        "heartbeat_at"
    )

    age = _age_seconds(
        heartbeat_at
    )

    stale_limit = (
        _component_stale_limit(
            component
        )
    )

    if age is None:

        return {
            "effective_status":
                STATUS_UNKNOWN,

            "healthy":
                False,

            "reason":
                "Missing heartbeat timestamp.",
        }

    if age > stale_limit:

        return {
            "effective_status":
                STATUS_OFFLINE,

            "healthy":
                False,

            "reason":
                (
                    f"Heartbeat stale: "
                    f"{int(age)}s > "
                    f"{stale_limit}s"
                ),

            "heartbeat_age_seconds":
                round(
                    age,
                    1,
                ),

            "stale_limit_seconds":
                stale_limit,
        }

    healthy_states = {
        STATUS_HEALTHY,
        STATUS_WARMING_UP,
        STATUS_RATE_LIMITED,
    }

    return {
        "effective_status":
            stored_status,

        "healthy":
            stored_status
            in healthy_states,

        "heartbeat_age_seconds":
            round(
                age,
                1,
            ),

        "stale_limit_seconds":
            stale_limit,
    }


# ============================================================
# SYSTEM SNAPSHOT
# ============================================================

def get_system_health_snapshot() -> Dict:

    db = database_health()

    if not db.get(
        "ok",
        False,
    ):

        return {
            "ok":
                False,

            "overall_status":
                STATUS_OFFLINE,

            "safe_to_trade":
                False,

            "database":
                db,

            "paper_only":
                True,

            "real_execution":
                False,

            "timestamp":
                _iso_now(),
        }

    states = get_all_runtime_states()

    evaluated = {}

    hard_failures = []
    degraded = []
    warming = []
    rate_limited = []

    for component, state in (
        states.items()
    ):

        expanded = {
            "component":
                component,

            **state,
        }

        health = (
            evaluate_component_health(
                expanded
            )
        )

        evaluated[
            component
        ] = {
            **state,
            **health,
        }

        status = health.get(
            "effective_status"
        )

        if status in {
            STATUS_OFFLINE,
            STATUS_BLOCKED,
        }:

            hard_failures.append(
                component
            )

        elif status == STATUS_DEGRADED:

            degraded.append(
                component
            )

        elif status == STATUS_WARMING_UP:

            warming.append(
                component
            )

        elif status == STATUS_RATE_LIMITED:

            rate_limited.append(
                component
            )

    if hard_failures:

        overall = STATUS_BLOCKED

    elif degraded:

        overall = STATUS_DEGRADED

    elif warming:

        overall = STATUS_WARMING_UP

    elif rate_limited:

        overall = STATUS_RATE_LIMITED

    else:

        overall = STATUS_HEALTHY

    # --------------------------------------------------------
    # SAFE-TO-TRADE GATE
    #
    # Rate limited bootstrap is NOT itself a trading failure.
    # Warming scanner is not ready for entries.
    # --------------------------------------------------------

    trading_blockers = list(
        hard_failures
    )

    critical_runtime_components = {
        COMPONENT_RISK_GOVERNOR,
    }

    for component in (
        critical_runtime_components
    ):

        state = evaluated.get(
            component
        )

        if state:

            effective = state.get(
                "effective_status"
            )

            if effective not in {
                STATUS_HEALTHY,
            }:

                trading_blockers.append(
                    component
                )

    safe_to_trade = (
        len(
            set(
                trading_blockers
            )
        )
        == 0
    )

    return {
        "ok":
            True,

        "engine":
            "V5.0 Unified System Health",

        "overall_status":
            overall,

        "safe_to_trade":
            safe_to_trade,

        "trading_blockers":
            sorted(
                set(
                    trading_blockers
                )
            ),

        "hard_failures":
            hard_failures,

        "degraded_components":
            degraded,

        "warming_components":
            warming,

        "rate_limited_components":
            rate_limited,

        "components":
            evaluated,

        "database":
            db,

        "service":
            {
                "name":
                    SERVICE_NAME,

                "service_id":
                    SERVICE_ID,

                "instance_id":
                    INSTANCE_ID,

                "environment":
                    ENVIRONMENT,

                "deploy_commit":
                    DEPLOY_COMMIT,
            },

        "paper_only":
            True,

        "real_execution":
            False,

        "timestamp":
            _iso_now(),
    }


# ============================================================
# SIMPLE RENDER HEALTH CHECK
# ============================================================

def render_health_check() -> Dict:
    """
    Lightweight health payload suitable for a future HTTP
    health endpoint.

    Render expects the actual endpoint to return 2xx when
    healthy.

    This function only creates the payload.
    """

    snapshot = (
        get_system_health_snapshot()
    )

    return {
        "ok":
            snapshot.get(
                "ok",
                False,
            ),

        "status":
            snapshot.get(
                "overall_status",
                STATUS_UNKNOWN,
            ),

        "database_ok":
            snapshot.get(
                "database",
                {},
            ).get(
                "ok",
                False,
            ),

        "service":
            SERVICE_NAME,

        "instance":
            INSTANCE_ID,

        "commit":
            DEPLOY_COMMIT,

        "timestamp":
            snapshot.get(
                "timestamp"
            ),
    }


# ============================================================
# STRUCTURED LOG EVENT
# ============================================================

def structured_log(
    component: str,
    event: str,
    *,
    level: str = "INFO",
    message: str = "",
    payload: Optional[Dict] = None,
):
    """
    JSON log format designed to remain compatible with future
    OpenTelemetry / OTLP log collection.
    """

    record = {
        "timestamp":
            _iso_now(),

        "service":
            SERVICE_NAME,

        "instance":
            INSTANCE_ID,

        "commit":
            DEPLOY_COMMIT,

        "component":
            str(component).upper(),

        "event":
            str(event).upper(),

        "level":
            str(level).upper(),

        "message":
            str(message),

        "payload":
            payload
            if isinstance(
                payload,
                dict,
            )
            else {},

        "paper_only":
            True,
    }

    print(
        _json_dumps(
            record
        ),
        flush=True,
    )

    return record


# ============================================================
# HEALTH
# ============================================================

def system_health_engine_health() -> Dict:

    try:

        db = database_health()

        return {
            "ok":
                db.get(
                    "ok",
                    False,
                ),

            "engine":
                "V5.0 Unified System Health",

            "database":
                db,

            "runtime_state":
                True,

            "runtime_events":
                True,

            "heartbeat_monitoring":
                True,

            "staleness_detection":
                True,

            "structured_json_logs":
                True,

            "opentelemetry_ready":
                True,

            "otlp_ready":
                True,

            "render_health_ready":
                True,

            "paper_only":
                True,

            "real_execution_locked":
                True,
        }

    except Exception as error:

        return {
            "ok":
                False,

            "engine":
                "V5.0 Unified System Health",

            "reason":
                str(error),

            "paper_only":
                True,

            "real_execution_locked":
                True,
        }

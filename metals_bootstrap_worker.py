"""
metals_bootstrap_worker.py

PRO AI QUANT TERMINAL V5.0
OBSERVABLE QUOTA-SAFE METALS HISTORICAL BOOTSTRAP WORKER

Purpose
-------
Continuously and safely backfill missing Gold/Silver historical
candles using metals_bootstrap.py while publishing runtime
health into the V5 Unified System Health Engine.

Architecture
------------
Gold-API OHLC
    ↓
metals_bootstrap.py V4.3.1+
    ↓
PostgreSQL metals_seed_candles
    ↓
metals_ohlc_store.py V4.3+
    ↓
15m / 1h / 4h hybrid candles
    ↓
metals_scanner.py
    ↓
metals_trade_engine.py
    ↓
Portfolio Risk Governor

Observability
-------------
Worker
    ↓
system_health.py
    ↓
PostgreSQL runtime_state
    ↓
runtime_events
    ↓
Future System Health Control Center
    ↓
Future OpenTelemetry / OTLP

Safety
------
- PostgreSQL advisory lock prevents duplicate workers
- Maximum internal historical API usage remains quota-safe
- Persistent PostgreSQL bootstrap progress
- Restart-safe
- Exponential error backoff
- Rate-limit awareness
- Health heartbeat publishing
- Warm-up progress publishing
- Error event publishing
- Graceful shutdown
- PAPER ONLY
- NO REAL ORDERS
"""

from __future__ import annotations

import os
import signal
import sys
import time
import traceback
from datetime import datetime, timezone
from typing import Dict, Optional

import psycopg

from metals_bootstrap import (
    bootstrap_status,
    metals_bootstrap_health,
    requests_used_last_hour,
    run_bootstrap_cycle,
)

from system_health import (
    COMPONENT_METALS_BOOTSTRAP,
    STATUS_HEALTHY,
    heartbeat,
    record_runtime_event,
    report_degraded,
    report_error,
    report_rate_limited,
    report_warming_up,
    structured_log,
    update_runtime_state,
)


# ============================================================
# CONFIG
# ============================================================

DATABASE_URL = os.environ.get(
    "DATABASE_URL",
    "",
).strip()


REQUESTS_PER_CYCLE = int(
    os.environ.get(
        "METALS_BOOTSTRAP_REQUESTS_PER_CYCLE",
        "2",
    )
)


NORMAL_SLEEP_SECONDS = int(
    os.environ.get(
        "METALS_BOOTSTRAP_INTERVAL_SECONDS",
        "900",
    )
)


BUDGET_SLEEP_SECONDS = int(
    os.environ.get(
        "METALS_BOOTSTRAP_BUDGET_SLEEP_SECONDS",
        "900",
    )
)


READY_SLEEP_SECONDS = int(
    os.environ.get(
        "METALS_BOOTSTRAP_READY_SLEEP_SECONDS",
        "3600",
    )
)


# Heartbeat while sleeping for long periods.
HEARTBEAT_INTERVAL_SECONDS = int(
    os.environ.get(
        "METALS_BOOTSTRAP_HEARTBEAT_SECONDS",
        "120",
    )
)


ERROR_SLEEP_INITIAL = int(
    os.environ.get(
        "METALS_BOOTSTRAP_ERROR_SLEEP_INITIAL",
        "60",
    )
)


ERROR_SLEEP_MAX = int(
    os.environ.get(
        "METALS_BOOTSTRAP_ERROR_SLEEP_MAX",
        "1800",
    )
)


INTERNAL_HOURLY_LIMIT = 8


# Fixed PostgreSQL advisory-lock identifier.
WORKER_LOCK_ID = 93739001


WORKER_VERSION = "V5.0"


# ============================================================
# HARD SAFETY
# ============================================================

PAPER_ONLY = True
REAL_EXECUTION_ENABLED = False


# ============================================================
# GLOBAL STATE
# ============================================================

_SHUTDOWN = False

_LOCK_CONNECTION: Optional[
    psycopg.Connection
] = None

_LAST_HEARTBEAT_MONOTONIC = 0.0

_LAST_KNOWN_STATUS: Dict = {}


# ============================================================
# TIME / LOGGING
# ============================================================

def _utc_now_iso() -> str:

    return datetime.now(
        timezone.utc
    ).isoformat()


def _log(
    message: str,
):

    print(
        f"[METALS BOOTSTRAP WORKER] "
        f"{_utc_now_iso()} | "
        f"{message}",
        flush=True,
    )


def _structured(
    event: str,
    *,
    level: str = "INFO",
    message: str = "",
    payload: Optional[Dict] = None,
):

    try:

        structured_log(
            COMPONENT_METALS_BOOTSTRAP,
            event,
            level=level,
            message=message,
            payload=payload,
        )

    except Exception:

        # Observability must never kill the worker.
        pass


# ============================================================
# SAFE VALUES
# ============================================================

def _safe_int(
    value,
    default=0,
) -> int:

    try:

        return int(
            value
        )

    except (
        TypeError,
        ValueError,
    ):

        return default


def _safe_float(
    value,
    default=0.0,
) -> float:

    try:

        number = float(
            value
        )

        if number != number:

            return default

        return number

    except (
        TypeError,
        ValueError,
    ):

        return default


# ============================================================
# SHUTDOWN HANDLING
# ============================================================

def _handle_shutdown(
    signum,
    frame,
):

    global _SHUTDOWN

    _SHUTDOWN = True

    message = (
        f"Shutdown signal received: "
        f"{signum}"
    )

    _log(
        message
    )

    _structured(
        "SHUTDOWN_SIGNAL",
        message=message,
        payload={
            "signal":
                signum,

            "worker_version":
                WORKER_VERSION,
        },
    )


signal.signal(
    signal.SIGTERM,
    _handle_shutdown,
)

signal.signal(
    signal.SIGINT,
    _handle_shutdown,
)


# ============================================================
# POSTGRESQL ADVISORY LOCK
# ============================================================

def _acquire_worker_lock() -> bool:

    global _LOCK_CONNECTION

    if not DATABASE_URL:

        raise RuntimeError(
            "DATABASE_URL is not configured."
        )

    _LOCK_CONNECTION = (
        psycopg.connect(
            DATABASE_URL,
            autocommit=True,
            connect_timeout=10,
        )
    )

    with _LOCK_CONNECTION.cursor() as cur:

        cur.execute(
            """
            SELECT pg_try_advisory_lock(%s)
            """,
            (
                WORKER_LOCK_ID,
            ),
        )

        row = cur.fetchone()

    acquired = bool(
        row
        and row[0]
    )

    if not acquired:

        try:

            _LOCK_CONNECTION.close()

        except Exception:

            pass

        _LOCK_CONNECTION = None

    return acquired


def _release_worker_lock():

    global _LOCK_CONNECTION

    if _LOCK_CONNECTION is None:

        return

    try:

        with _LOCK_CONNECTION.cursor() as cur:

            cur.execute(
                """
                SELECT pg_advisory_unlock(%s)
                """,
                (
                    WORKER_LOCK_ID,
                ),
            )

    except Exception:

        pass

    try:

        _LOCK_CONNECTION.close()

    except Exception:

        pass

    _LOCK_CONNECTION = None


# ============================================================
# STATUS HELPERS
# ============================================================

def _safe_status() -> Dict:

    try:

        status = bootstrap_status()

        if isinstance(
            status,
            dict,
        ):

            return status

    except Exception as error:

        return {
            "ready":
                False,

            "error":
                str(
                    error
                ),
        }

    return {
        "ready":
            False,

        "error":
            "Invalid bootstrap status response.",
    }


def _remaining_total(
    status: Dict,
) -> int:

    markets = status.get(
        "markets",
        {},
    )

    remaining = 0

    for symbol_data in (
        markets.values()
    ):

        if not isinstance(
            symbol_data,
            dict,
        ):

            continue

        for timeframe_data in (
            symbol_data.values()
        ):

            if not isinstance(
                timeframe_data,
                dict,
            ):

                continue

            remaining += _safe_int(
                timeframe_data.get(
                    "remaining",
                    0,
                ),
                0,
            )

    return max(
        0,
        remaining,
    )


def _stored_total(
    status: Dict,
) -> int:

    markets = status.get(
        "markets",
        {},
    )

    total = 0

    for symbol_data in (
        markets.values()
    ):

        if not isinstance(
            symbol_data,
            dict,
        ):

            continue

        for timeframe_data in (
            symbol_data.values()
        ):

            if not isinstance(
                timeframe_data,
                dict,
            ):

                continue

            total += _safe_int(
                timeframe_data.get(
                    "candles",
                    0,
                ),
                0,
            )

    return max(
        0,
        total,
    )


def _target_total(
    status: Dict,
) -> int:

    markets = status.get(
        "markets",
        {},
    )

    total = 0

    for symbol_data in (
        markets.values()
    ):

        if not isinstance(
            symbol_data,
            dict,
        ):

            continue

        for timeframe_data in (
            symbol_data.values()
        ):

            if not isinstance(
                timeframe_data,
                dict,
            ):

                continue

            total += _safe_int(
                timeframe_data.get(
                    "target",
                    60,
                ),
                60,
            )

    return max(
        0,
        total,
    )


def _progress_pct(
    status: Dict,
) -> float:

    supplied = _safe_float(
        status.get(
            "progress_pct"
        ),
        -1.0,
    )

    if supplied >= 0:

        return round(
            supplied,
            2,
        )

    target = _target_total(
        status
    )

    if target <= 0:

        return 0.0

    stored = _stored_total(
        status
    )

    return round(
        min(
            100.0,
            (
                stored
                / target
                * 100.0
            ),
        ),
        2,
    )


def _progress_summary(
    status: Dict,
) -> str:

    markets = status.get(
        "markets",
        {},
    )

    parts = []

    for symbol in (
        "XAUUSD",
        "XAGUSD",
    ):

        symbol_data = markets.get(
            symbol,
            {},
        )

        tf_parts = []

        for timeframe in (
            "15m",
            "1h",
            "4h",
        ):

            info = symbol_data.get(
                timeframe,
                {},
            )

            candles = _safe_int(
                info.get(
                    "candles",
                    0,
                ),
                0,
            )

            target = _safe_int(
                info.get(
                    "target",
                    60,
                ),
                60,
            )

            tf_parts.append(
                (
                    f"{timeframe}="
                    f"{candles}/{target}"
                )
            )

        parts.append(
            (
                f"{symbol}["
                + ", ".join(
                    tf_parts
                )
                + "]"
            )
        )

    return " | ".join(
        parts
    )


def _health_payload(
    status: Optional[Dict] = None,
    **extra,
) -> Dict:

    if not isinstance(
        status,
        dict,
    ):

        status = _safe_status()

    payload = {
        "worker_version":
            WORKER_VERSION,

        "paper_only":
            True,

        "real_execution":
            False,

        "advisory_lock_id":
            WORKER_LOCK_ID,

        "progress_pct":
            _progress_pct(
                status
            ),

        "candles_stored":
            _stored_total(
                status
            ),

        "candles_remaining":
            _remaining_total(
                status
            ),

        "target_total":
            _target_total(
                status
            ),

        "ready":
            bool(
                status.get(
                    "ready",
                    False,
                )
            ),

        "requests_used_last_hour":
            _safe_int(
                status.get(
                    "requests_used_last_hour",
                    0,
                ),
                0,
            ),

        "hourly_budget":
            _safe_int(
                status.get(
                    "hourly_budget",
                    INTERNAL_HOURLY_LIMIT,
                ),
                INTERNAL_HOURLY_LIMIT,
            ),

        "progress":
            _progress_summary(
                status
            ),

        "bootstrap_mode":
            status.get(
                "bootstrap_mode"
            ),

        "post_bootstrap_mode":
            status.get(
                "post_bootstrap_mode"
            ),
    }

    payload.update(
        extra
    )

    return payload


# ============================================================
# HEALTH PUBLISHING
# ============================================================

def _publish_alive(
    *,
    status: Optional[Dict] = None,
    message: str = "Worker alive",
):

    global _LAST_HEARTBEAT_MONOTONIC
    global _LAST_KNOWN_STATUS

    if status is None:

        status = (
            _LAST_KNOWN_STATUS
            or _safe_status()
        )

    if isinstance(
        status,
        dict,
    ):

        _LAST_KNOWN_STATUS = status

    payload = _health_payload(
        status
    )

    try:

        heartbeat(
            COMPONENT_METALS_BOOTSTRAP,
            message=message,
            payload=payload,
        )

        _LAST_HEARTBEAT_MONOTONIC = (
            time.monotonic()
        )

    except Exception as error:

        _log(
            "Health heartbeat publish failed: "
            f"{error}"
        )


def _publish_warming(
    status: Dict,
    *,
    message: str,
    extra: Optional[Dict] = None,
):

    global _LAST_HEARTBEAT_MONOTONIC
    global _LAST_KNOWN_STATUS

    _LAST_KNOWN_STATUS = status

    payload = _health_payload(
        status
    )

    if isinstance(
        extra,
        dict,
    ):

        payload.update(
            extra
        )

    try:

        report_warming_up(
            COMPONENT_METALS_BOOTSTRAP,
            message=message,
            payload=payload,
        )

        _LAST_HEARTBEAT_MONOTONIC = (
            time.monotonic()
        )

    except Exception as error:

        _log(
            "Warm-up health publish failed: "
            f"{error}"
        )


def _publish_rate_limited(
    status: Dict,
    *,
    message: str,
    extra: Optional[Dict] = None,
):

    global _LAST_HEARTBEAT_MONOTONIC
    global _LAST_KNOWN_STATUS

    _LAST_KNOWN_STATUS = status

    payload = _health_payload(
        status
    )

    if isinstance(
        extra,
        dict,
    ):

        payload.update(
            extra
        )

    try:

        report_rate_limited(
            COMPONENT_METALS_BOOTSTRAP,
            message=message,
            payload=payload,
        )

        _LAST_HEARTBEAT_MONOTONIC = (
            time.monotonic()
        )

    except Exception as error:

        _log(
            "Rate-limit health publish failed: "
            f"{error}"
        )


def _publish_error(
    message: str,
    *,
    status: Optional[Dict] = None,
    extra: Optional[Dict] = None,
):

    global _LAST_HEARTBEAT_MONOTONIC

    payload = _health_payload(
        status
    )

    if isinstance(
        extra,
        dict,
    ):

        payload.update(
            extra
        )

    try:

        report_error(
            COMPONENT_METALS_BOOTSTRAP,
            message=message,
            payload=payload,
        )

        _LAST_HEARTBEAT_MONOTONIC = (
            time.monotonic()
        )

    except Exception as error:

        _log(
            "Error health publish failed: "
            f"{error}"
        )


def _publish_ready(
    status: Dict,
):

    global _LAST_HEARTBEAT_MONOTONIC
    global _LAST_KNOWN_STATUS

    _LAST_KNOWN_STATUS = status

    payload = _health_payload(
        status,
        historical_bootstrap_complete=True,
    )

    try:

        update_runtime_state(
            COMPONENT_METALS_BOOTSTRAP,
            status=STATUS_HEALTHY,
            success=True,
            message=(
                "Historical metals bootstrap READY."
            ),
            payload=payload,
        )

        _LAST_HEARTBEAT_MONOTONIC = (
            time.monotonic()
        )

    except Exception as error:

        _log(
            "Ready health publish failed: "
            f"{error}"
        )


# ============================================================
# INTERRUPTIBLE SLEEP + PERIODIC HEARTBEAT
# ============================================================

def _safe_sleep(
    seconds: int,
    *,
    status: Optional[Dict] = None,
    sleep_reason: str = "idle",
):

    global _LAST_HEARTBEAT_MONOTONIC

    seconds = max(
        1,
        _safe_int(
            seconds,
            1,
        ),
    )

    deadline = (
        time.monotonic()
        + seconds
    )

    while (
        not _SHUTDOWN
        and time.monotonic()
        < deadline
    ):

        remaining = max(
            0.0,
            deadline
            - time.monotonic(),
        )

        chunk = min(
            10.0,
            remaining,
        )

        if chunk <= 0:

            break

        time.sleep(
            chunk
        )

        since_heartbeat = (
            time.monotonic()
            - _LAST_HEARTBEAT_MONOTONIC
        )

        if (
            since_heartbeat
            >= HEARTBEAT_INTERVAL_SECONDS
        ):

            _publish_alive(
                status=status,
                message=(
                    "Worker alive while "
                    f"{sleep_reason}."
                ),
            )


# ============================================================
# PROVIDER RATE-LIMIT DETECTION
# ============================================================

def _raw_has_provider_rate_limit(
    result: Dict,
) -> bool:

    raw = result.get(
        "raw",
        {},
    )

    if not isinstance(
        raw,
        dict,
    ):

        return False

    results = raw.get(
        "results",
        [],
    )

    if not isinstance(
        results,
        list,
    ):

        return False

    for item in results:

        if not isinstance(
            item,
            dict,
        ):

            continue

        if item.get(
            "provider_rate_limited",
            False,
        ):

            return True

        reason = str(
            item.get(
                "reason",
                "",
            )
        ).lower()

        if (
            "rate limit"
            in reason
        ):

            return True

    return False


# ============================================================
# ONE AUTOMATIC CYCLE
# ============================================================

def run_worker_cycle() -> Dict:

    health = (
        metals_bootstrap_health()
    )

    if not health.get(
        "ok",
        False,
    ):

        return {
            "ok":
                False,

            "reason":
                health.get(
                    "reason",
                    (
                        "Bootstrap health "
                        "check failed."
                    ),
                ),
        }

    status_before = (
        _safe_status()
    )

    if status_before.get(
        "error"
    ):

        return {
            "ok":
                False,

            "reason":
                status_before.get(
                    "error"
                ),

            "status":
                status_before,
        }

    if status_before.get(
        "ready",
        False,
    ):

        return {
            "ok":
                True,

            "ready":
                True,

            "status":
                status_before,
        }

    used = _safe_int(
        requests_used_last_hour(),
        0,
    )

    remaining_budget = max(
        0,
        INTERNAL_HOURLY_LIMIT
        - used,
    )

    if remaining_budget <= 0:

        return {
            "ok":
                True,

            "ready":
                False,

            "budget_exhausted":
                True,

            "requests_used_last_hour":
                used,

            "status":
                status_before,
        }

    request_count = min(
        max(
            1,
            REQUESTS_PER_CYCLE,
        ),
        remaining_budget,
    )

    result = (
        run_bootstrap_cycle(
            max_requests=request_count
        )
    )

    if not isinstance(
        result,
        dict,
    ):

        return {
            "ok":
                False,

            "reason":
                (
                    "Bootstrap engine returned "
                    "invalid response."
                ),

            "status":
                status_before,
        }

    status_after = (
        result.get(
            "status"
        )
        or _safe_status()
    )

    provider_rate_limited = (
        _raw_has_provider_rate_limit(
            {
                "raw":
                    result,
            }
        )
    )

    return {
        "ok":
            bool(
                result.get(
                    "ok",
                    True,
                )
            ),

        "ready":
            bool(
                status_after.get(
                    "ready",
                    False,
                )
            ),

        "budget_exhausted":
            bool(
                result.get(
                    "budget_exhausted",
                    False,
                )
            ),

        "provider_rate_limited":
            provider_rate_limited,

        "requests_made":
            _safe_int(
                result.get(
                    "requests_made",
                    0,
                ),
                0,
            ),

        "requests_used_last_hour":
            _safe_int(
                result.get(
                    "requests_used_last_hour",
                    requests_used_last_hour(),
                ),
                0,
            ),

        "status":
            status_after,

        "raw":
            result,
    }


# ============================================================
# MAIN LOOP
# ============================================================

def main():

    global _SHUTDOWN

    _log(
        (
            "Starting V5.0 observable "
            "automatic metals bootstrap worker."
        )
    )

    _structured(
        "WORKER_STARTING",
        message=(
            "Metals bootstrap worker starting."
        ),
        payload={
            "worker_version":
                WORKER_VERSION,

            "lock_id":
                WORKER_LOCK_ID,

            "requests_per_cycle":
                REQUESTS_PER_CYCLE,

            "normal_sleep_seconds":
                NORMAL_SLEEP_SECONDS,

            "paper_only":
                True,
        },
    )

    # ========================================================
    # SINGLE-WORKER PROTECTION
    # ========================================================

    try:

        acquired = (
            _acquire_worker_lock()
        )

    except Exception as error:

        message = (
            "Could not acquire PostgreSQL "
            f"advisory lock: {error}"
        )

        _log(
            message
        )

        _publish_error(
            message,
            extra={
                "phase":
                    "LOCK_ACQUISITION",
            },
        )

        sys.exit(
            1
        )

    if not acquired:

        message = (
            "Another metals bootstrap worker "
            "already owns the advisory lock. "
            "Exiting safely."
        )

        _log(
            message
        )

        try:

            report_degraded(
                COMPONENT_METALS_BOOTSTRAP,
                message=message,
                payload={
                    "duplicate_worker":
                        True,

                    "lock_id":
                        WORKER_LOCK_ID,

                    "worker_version":
                        WORKER_VERSION,
                },
            )

        except Exception:

            pass

        sys.exit(
            0
        )

    _log(
        "PostgreSQL worker lock acquired."
    )

    _structured(
        "WORKER_LOCK_ACQUIRED",
        message=(
            "PostgreSQL advisory lock acquired."
        ),
        payload={
            "lock_id":
                WORKER_LOCK_ID,
        },
    )

    try:

        record_runtime_event(
            COMPONENT_METALS_BOOTSTRAP,
            "WORKER_STARTED",
            severity="INFO",
            message=(
                "Observable metals bootstrap "
                "worker started."
            ),
            payload={
                "version":
                    WORKER_VERSION,

                "lock_id":
                    WORKER_LOCK_ID,

                "paper_only":
                    True,
            },
        )

    except Exception:

        pass

    initial_status = (
        _safe_status()
    )

    if initial_status.get(
        "ready",
        False,
    ):

        _publish_ready(
            initial_status
        )

    else:

        _publish_warming(
            initial_status,
            message=(
                "Historical metals bootstrap "
                "is warming up."
            ),
        )

    error_sleep = (
        ERROR_SLEEP_INITIAL
    )

    try:

        while not _SHUTDOWN:

            try:

                # --------------------------------------------
                # Publish cycle heartbeat before doing work.
                # --------------------------------------------

                _publish_alive(
                    status=(
                        _LAST_KNOWN_STATUS
                        or None
                    ),
                    message=(
                        "Starting bootstrap cycle."
                    ),
                )

                result = (
                    run_worker_cycle()
                )

                status = (
                    result.get(
                        "status",
                        {},
                    )
                )

                if not isinstance(
                    status,
                    dict,
                ):

                    status = {}

                # --------------------------------------------
                # HARD CYCLE FAILURE
                # --------------------------------------------

                if not result.get(
                    "ok",
                    False,
                ):

                    reason = str(
                        result.get(
                            "reason",
                            "Unknown worker error",
                        )
                    )

                    _log(
                        f"Cycle failed: {reason}"
                    )

                    _publish_error(
                        (
                            "Bootstrap cycle failed: "
                            f"{reason}"
                        ),
                        status=status,
                        extra={
                            "error_backoff_seconds":
                                error_sleep,
                        },
                    )

                    _structured(
                        "CYCLE_FAILED",
                        level="ERROR",
                        message=reason,
                        payload={
                            "error_backoff_seconds":
                                error_sleep,
                        },
                    )

                    _safe_sleep(
                        error_sleep,
                        status=status,
                        sleep_reason=(
                            "error backoff"
                        ),
                    )

                    error_sleep = min(
                        error_sleep * 2,
                        ERROR_SLEEP_MAX,
                    )

                    continue

                # Successful worker logic resets backoff.
                error_sleep = (
                    ERROR_SLEEP_INITIAL
                )

                _log(
                    (
                        "Progress: "
                        + _progress_summary(
                            status
                        )
                    )
                )

                # =================================================
                # FULLY READY
                # =================================================

                if result.get(
                    "ready",
                    False,
                ):

                    message = (
                        "Historical bootstrap is "
                        "fully READY. No more "
                        "historical calls required."
                    )

                    _log(
                        message
                    )

                    _publish_ready(
                        status
                    )

                    _structured(
                        "BOOTSTRAP_READY",
                        message=message,
                        payload=_health_payload(
                            status
                        ),
                    )

                    _safe_sleep(
                        READY_SLEEP_SECONDS,
                        status=status,
                        sleep_reason=(
                            "READY idle"
                        ),
                    )

                    continue

                # =================================================
                # PROVIDER RATE LIMITED
                # =================================================

                if result.get(
                    "provider_rate_limited",
                    False,
                ):

                    used = _safe_int(
                        result.get(
                            "requests_used_last_hour",
                            0,
                        ),
                        0,
                    )

                    message = (
                        "Gold-API historical rate "
                        "limit reached. "
                        "Waiting safely."
                    )

                    _log(
                        message
                    )

                    _publish_rate_limited(
                        status,
                        message=message,
                        extra={
                            "provider":
                                "Gold-API",

                            "requests_used_last_hour":
                                used,

                            "wait_seconds":
                                BUDGET_SLEEP_SECONDS,
                        },
                    )

                    _safe_sleep(
                        BUDGET_SLEEP_SECONDS,
                        status=status,
                        sleep_reason=(
                            "provider rate-limit wait"
                        ),
                    )

                    continue

                # =================================================
                # INTERNAL HOURLY BUDGET EXHAUSTED
                # =================================================

                if result.get(
                    "budget_exhausted",
                    False,
                ):

                    used = _safe_int(
                        result.get(
                            "requests_used_last_hour",
                            0,
                        ),
                        0,
                    )

                    message = (
                        "Internal historical API "
                        f"budget reached "
                        f"({used}/"
                        f"{INTERNAL_HOURLY_LIMIT}). "
                        "Waiting safely."
                    )

                    _log(
                        message
                    )

                    _publish_rate_limited(
                        status,
                        message=message,
                        extra={
                            "limit_type":
                                "INTERNAL_BUDGET",

                            "requests_used_last_hour":
                                used,

                            "hourly_limit":
                                INTERNAL_HOURLY_LIMIT,

                            "wait_seconds":
                                BUDGET_SLEEP_SECONDS,
                        },
                    )

                    _safe_sleep(
                        BUDGET_SLEEP_SECONDS,
                        status=status,
                        sleep_reason=(
                            "internal quota wait"
                        ),
                    )

                    continue

                # =================================================
                # SUCCESSFUL BACKFILL CYCLE / STILL WARMING
                # =================================================

                requests_made = _safe_int(
                    result.get(
                        "requests_made",
                        0,
                    ),
                    0,
                )

                total_remaining = (
                    _remaining_total(
                        status
                    )
                )

                progress = (
                    _progress_pct(
                        status
                    )
                )

                message = (
                    f"Bootstrap warming up. "
                    f"Requests made="
                    f"{requests_made}. "
                    f"Candles remaining="
                    f"{total_remaining}. "
                    f"Progress="
                    f"{progress:.2f}%."
                )

                _log(
                    (
                        "Cycle completed. "
                        f"Requests made="
                        f"{requests_made}. "
                        f"Candles remaining="
                        f"{total_remaining}."
                    )
                )

                _publish_warming(
                    status,
                    message=message,
                    extra={
                        "requests_made":
                            requests_made,

                        "sleep_seconds":
                            NORMAL_SLEEP_SECONDS,
                    },
                )

                _structured(
                    "CYCLE_COMPLETED",
                    message=message,
                    payload=_health_payload(
                        status,
                        requests_made=
                            requests_made,
                    ),
                )

                _safe_sleep(
                    NORMAL_SLEEP_SECONDS,
                    status=status,
                    sleep_reason=(
                        "normal bootstrap interval"
                    ),
                )

            except Exception as error:

                reason = str(
                    error
                )

                _log(
                    (
                        "Unhandled cycle "
                        f"exception: {reason}"
                    )
                )

                traceback.print_exc()

                _publish_error(
                    (
                        "Unhandled bootstrap worker "
                        f"exception: {reason}"
                    ),
                    status=(
                        _LAST_KNOWN_STATUS
                        or None
                    ),
                    extra={
                        "exception_type":
                            type(
                                error
                            ).__name__,

                        "error_backoff_seconds":
                            error_sleep,
                    },
                )

                _structured(
                    "UNHANDLED_EXCEPTION",
                    level="ERROR",
                    message=reason,
                    payload={
                        "exception_type":
                            type(
                                error
                            ).__name__,

                        "backoff_seconds":
                            error_sleep,
                    },
                )

                _safe_sleep(
                    error_sleep,
                    status=(
                        _LAST_KNOWN_STATUS
                        or None
                    ),
                    sleep_reason=(
                        "exception backoff"
                    ),
                )

                error_sleep = min(
                    error_sleep * 2,
                    ERROR_SLEEP_MAX,
                )

    finally:

        _release_worker_lock()

        message = (
            "Worker stopped cleanly."
        )

        _log(
            message
        )

        try:

            update_runtime_state(
                COMPONENT_METALS_BOOTSTRAP,
                status="OFFLINE",
                success=False,
                message=message,
                payload={
                    "worker_version":
                        WORKER_VERSION,

                    "graceful_shutdown":
                        True,

                    "paper_only":
                        True,
                },
            )

            record_runtime_event(
                COMPONENT_METALS_BOOTSTRAP,
                "WORKER_STOPPED",
                severity="INFO",
                message=message,
                payload={
                    "version":
                        WORKER_VERSION,

                    "graceful_shutdown":
                        True,
                },
            )

        except Exception:

            pass


# ============================================================
# ENTRYPOINT
# ============================================================

if __name__ == "__main__":

    main()

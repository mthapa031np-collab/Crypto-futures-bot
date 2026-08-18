"""
metals_bootstrap_worker.py

PRO AI QUANT TERMINAL V3.9
AUTOMATIC QUOTA-SAFE METALS HISTORICAL BOOTSTRAP WORKER

Purpose
-------
Continuously and safely backfill missing Gold/Silver historical
candles using the existing metals_bootstrap.py engine.

Architecture
------------
Gold-API OHLC
    ↓
metals_bootstrap.py
    ↓
PostgreSQL metals_seed_candles
    ↓
metals_ohlc_store.py
    ↓
15m / 1h / 4h unified candles
    ↓
metals_scanner.py

Safety
------
- Maximum internal usage: 8 historical requests/hour
- Gold-API free plan ceiling remains below 10/hour
- Persistent PostgreSQL progress
- No duplicate candle generation
- Restart-safe
- Exponential error backoff
- PostgreSQL advisory lock prevents duplicate workers
- Automatically slows when hourly budget is exhausted
- Automatically idles when all history is ready
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


# ============================================================
# CONFIG
# ============================================================

DATABASE_URL = os.environ.get(
    "DATABASE_URL",
    "",
).strip()


# One worker cycle will use at most this many historical calls.
REQUESTS_PER_CYCLE = int(
    os.environ.get(
        "METALS_BOOTSTRAP_REQUESTS_PER_CYCLE",
        "2",
    )
)


# Normal interval while API budget remains.
NORMAL_SLEEP_SECONDS = int(
    os.environ.get(
        "METALS_BOOTSTRAP_INTERVAL_SECONDS",
        "900",
    )
)


# When hourly budget is exhausted, wait longer.
BUDGET_SLEEP_SECONDS = int(
    os.environ.get(
        "METALS_BOOTSTRAP_BUDGET_SLEEP_SECONDS",
        "900",
    )
)


# If history is fully ready, worker remains alive but quiet.
READY_SLEEP_SECONDS = int(
    os.environ.get(
        "METALS_BOOTSTRAP_READY_SLEEP_SECONDS",
        "3600",
    )
)


# Error retry controls.
ERROR_SLEEP_INITIAL = 60
ERROR_SLEEP_MAX = 1800


# Keep worker aligned with metals_bootstrap.py internal safety.
INTERNAL_HOURLY_LIMIT = 8


# PostgreSQL advisory lock ID.
# Must stay fixed and unique to this worker.
WORKER_LOCK_ID = 93739001


# ============================================================
# GLOBAL STATE
# ============================================================

_SHUTDOWN = False
_LOCK_CONNECTION: Optional[psycopg.Connection] = None


# ============================================================
# LOGGING
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


# ============================================================
# SHUTDOWN HANDLING
# ============================================================

def _handle_shutdown(
    signum,
    frame,
):

    global _SHUTDOWN

    _SHUTDOWN = True

    _log(
        f"Shutdown signal received: {signum}"
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

    _LOCK_CONNECTION = psycopg.connect(
        DATABASE_URL,
        autocommit=True,
        connect_timeout=10,
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

        return bootstrap_status()

    except Exception as error:

        return {
            "ready": False,
            "error": str(
                error
            ),
        }


def _remaining_total(
    status: Dict,
) -> int:

    markets = status.get(
        "markets",
        {},
    )

    remaining = 0

    for symbol_data in markets.values():

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

            remaining += int(
                timeframe_data.get(
                    "remaining",
                    0,
                )
                or 0
            )

    return remaining


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

            candles = int(
                info.get(
                    "candles",
                    0,
                )
                or 0
            )

            target = int(
                info.get(
                    "target",
                    60,
                )
                or 60
            )

            tf_parts.append(
                f"{timeframe}={candles}/{target}"
            )

        parts.append(
            f"{symbol}["
            + ", ".join(
                tf_parts
            )
            + "]"
        )

    return " | ".join(
        parts
    )


# ============================================================
# INTERRUPTIBLE SLEEP
# ============================================================

def _safe_sleep(
    seconds: int,
):

    seconds = max(
        1,
        int(
            seconds
        ),
    )

    slept = 0

    while (
        slept < seconds
        and not _SHUTDOWN
    ):

        chunk = min(
            10,
            seconds - slept,
        )

        time.sleep(
            chunk
        )

        slept += chunk


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
            "ok": False,
            "reason": health.get(
                "reason",
                "Bootstrap health check failed.",
            ),
        }

    status_before = (
        _safe_status()
    )

    if status_before.get(
        "ready",
        False,
    ):

        return {
            "ok": True,
            "ready": True,
            "status": status_before,
        }

    used = int(
        requests_used_last_hour()
        or 0
    )

    remaining_budget = max(
        0,
        INTERNAL_HOURLY_LIMIT
        - used,
    )

    if remaining_budget <= 0:

        return {
            "ok": True,
            "ready": False,
            "budget_exhausted": True,
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

    status_after = (
        result.get(
            "status"
        )
        or _safe_status()
    )

    return {
        "ok": True,
        "ready": status_after.get(
            "ready",
            False,
        ),
        "budget_exhausted": False,
        "requests_made":
            result.get(
                "requests_made",
                0,
            ),
        "requests_used_last_hour":
            result.get(
                "requests_used_last_hour",
                requests_used_last_hour(),
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
        "Starting V3.9 automatic metals bootstrap worker."
    )

    # --------------------------------------------------------
    # SINGLE-WORKER PROTECTION
    # --------------------------------------------------------

    try:

        acquired = (
            _acquire_worker_lock()
        )

    except Exception as error:

        _log(
            "Could not acquire PostgreSQL advisory lock: "
            f"{error}"
        )

        sys.exit(
            1
        )

    if not acquired:

        _log(
            "Another metals bootstrap worker "
            "already owns the database lock. "
            "Exiting safely."
        )

        sys.exit(
            0
        )

    _log(
        "PostgreSQL worker lock acquired."
    )

    error_sleep = (
        ERROR_SLEEP_INITIAL
    )

    try:

        while not _SHUTDOWN:

            try:

                result = (
                    run_worker_cycle()
                )

                if not result.get(
                    "ok",
                    False,
                ):

                    reason = (
                        result.get(
                            "reason",
                            "Unknown worker error",
                        )
                    )

                    _log(
                        f"Cycle failed: {reason}"
                    )

                    _safe_sleep(
                        error_sleep
                    )

                    error_sleep = min(
                        error_sleep * 2,
                        ERROR_SLEEP_MAX,
                    )

                    continue

                # Reset backoff after successful cycle.
                error_sleep = (
                    ERROR_SLEEP_INITIAL
                )

                status = (
                    result.get(
                        "status",
                        {},
                    )
                )

                _log(
                    "Progress: "
                    + _progress_summary(
                        status
                    )
                )

                # ------------------------------------------------
                # FULLY READY
                # ------------------------------------------------

                if result.get(
                    "ready",
                    False,
                ):

                    _log(
                        "Historical bootstrap is fully READY. "
                        "No more historical calls required."
                    )

                    _safe_sleep(
                        READY_SLEEP_SECONDS
                    )

                    continue

                # ------------------------------------------------
                # HOURLY BUDGET EXHAUSTED
                # ------------------------------------------------

                if result.get(
                    "budget_exhausted",
                    False,
                ):

                    used = result.get(
                        "requests_used_last_hour",
                        0,
                    )

                    _log(
                        "Internal hourly historical API budget "
                        f"reached ({used}/{INTERNAL_HOURLY_LIMIT}). "
                        "Waiting safely."
                    )

                    _safe_sleep(
                        BUDGET_SLEEP_SECONDS
                    )

                    continue

                # ------------------------------------------------
                # SUCCESSFUL BACKFILL CYCLE
                # ------------------------------------------------

                requests_made = (
                    result.get(
                        "requests_made",
                        0,
                    )
                )

                total_remaining = (
                    _remaining_total(
                        status
                    )
                )

                _log(
                    f"Cycle completed. "
                    f"Requests made={requests_made}. "
                    f"Candles remaining={total_remaining}."
                )

                _safe_sleep(
                    NORMAL_SLEEP_SECONDS
                )

            except Exception as error:

                _log(
                    "Unhandled cycle exception: "
                    f"{error}"
                )

                traceback.print_exc()

                _safe_sleep(
                    error_sleep
                )

                error_sleep = min(
                    error_sleep * 2,
                    ERROR_SLEEP_MAX,
                )

    finally:

        _release_worker_lock()

        _log(
            "Worker stopped cleanly."
        )


# ============================================================
# ENTRYPOINT
# ============================================================

if __name__ == "__main__":

    main()

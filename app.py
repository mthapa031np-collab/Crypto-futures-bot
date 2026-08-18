# ============================================================
# V5.1 AUTOMATIC METALS BOOTSTRAP RUNTIME
# Existing Render Web Service
# NO additional paid Background Worker required
# ============================================================

import os
import threading
import time

import psycopg


@st.cache_resource
def start_metals_auto_bootstrap():
    """
    PRO AI QUANT TERMINAL V5.1
    WEB-SERVICE EMBEDDED METALS BOOTSTRAP RUNTIME

    Design
    ------
    - Runs inside the EXISTING Render Web Service.
    - Does NOT require another Render Background Worker.
    - PostgreSQL advisory lock guarantees one active
      bootstrap owner across processes.
    - Persistent database cursor survives deploy/restart.
    - Gold-API historical budget remains protected.
    - Publishes health into system_health.py.
    - Publishes heartbeat during long sleep periods.
    - Health/observability failure can NEVER stop bootstrap.
    - No Streamlit API is called from the worker thread.
    - PAPER ONLY.
    - REAL EXECUTION DISABLED.
    """

    # --------------------------------------------------------
    # BOOTSTRAP ENGINE
    # --------------------------------------------------------

    from metals_bootstrap import (
        bootstrap_status,
        fetch_gold_api_ohlc,
        requests_used_last_hour,
    )

    # --------------------------------------------------------
    # V5 HEALTH BUS
    # --------------------------------------------------------
    #
    # Keep health optional/fault-tolerant.
    # Bootstrap must continue even if observability fails.
    # --------------------------------------------------------

    try:
        from system_health import (
            COMPONENT_METALS_BOOTSTRAP,
            STATUS_HEALTHY,
            heartbeat,
            record_runtime_event,
            report_error,
            report_rate_limited,
            report_warming_up,
            structured_log,
            update_runtime_state,
        )

        HEALTH_AVAILABLE = True

    except Exception as health_import_error:

        HEALTH_AVAILABLE = False

        print(
            "[METALS AUTO BOOTSTRAP] "
            "V5 health module unavailable: "
            f"{health_import_error}",
            flush=True,
        )

    # --------------------------------------------------------
    # ENVIRONMENT
    # --------------------------------------------------------

    DATABASE_URL = os.environ.get(
        "DATABASE_URL",
        "",
    ).strip()

    # --------------------------------------------------------
    # FIXED DISTRIBUTED LOCK
    # --------------------------------------------------------

    ADVISORY_LOCK_ID = 93739001

    # --------------------------------------------------------
    # API SAFETY
    # --------------------------------------------------------

    INTERNAL_HOURLY_LIMIT = 8

    # One historical request approximately every 8 minutes.
    REQUEST_INTERVAL_SECONDS = 480

    # Local/provider quota cooldown.
    BUDGET_WAIT_SECONDS = 600

    # Bootstrap complete idle.
    READY_SLEEP_SECONDS = 3600

    # Temporary error retry.
    ERROR_SLEEP_SECONDS = 120

    # Critical:
    # system_health default stale limit is shorter than
    # 480 / 600 / 3600 second sleeps.
    # Keep publishing heartbeat while sleeping.
    HEARTBEAT_INTERVAL_SECONDS = 120

    RUNTIME_VERSION = "V5.1"

    # --------------------------------------------------------
    # SHARED RESOURCE STATE
    # --------------------------------------------------------

    state = {
        "started": False,
        "lock_acquired": False,
        "thread_alive": False,
        "last_result": None,
        "last_error": None,
        "last_action": None,
        "last_heartbeat": None,
        "runtime_version": RUNTIME_VERSION,
    }

    if not DATABASE_URL:

        state["last_error"] = (
            "DATABASE_URL is not configured."
        )

        return state

    # ========================================================
    # LOGGING
    # ========================================================

    def log(message):

        print(
            "[METALS AUTO BOOTSTRAP] "
            + str(message),
            flush=True,
        )

    # ========================================================
    # SAFE HELPERS
    # ========================================================

    def safe_int(
        value,
        default=0,
    ):

        try:
            return int(value)

        except (
            TypeError,
            ValueError,
        ):
            return default

    def get_progress_payload(
        status=None,
        **extra,
    ):

        if not isinstance(
            status,
            dict,
        ):

            try:
                status = bootstrap_status()

            except Exception:
                status = {}

        markets = status.get(
            "markets",
            {},
        )

        total_candles = 0
        total_target = 0
        total_remaining = 0

        progress_rows = {}

        for symbol in (
            "XAUUSD",
            "XAGUSD",
        ):

            symbol_data = markets.get(
                symbol,
                {},
            )

            progress_rows[
                symbol
            ] = {}

            for timeframe in (
                "15m",
                "1h",
                "4h",
            ):

                info = symbol_data.get(
                    timeframe,
                    {},
                )

                candles = safe_int(
                    info.get(
                        "candles",
                        0,
                    )
                )

                target = safe_int(
                    info.get(
                        "target",
                        60,
                    ),
                    60,
                )

                remaining = max(
                    0,
                    target - candles,
                )

                total_candles += candles
                total_target += target
                total_remaining += remaining

                progress_rows[
                    symbol
                ][
                    timeframe
                ] = {
                    "candles":
                        candles,

                    "target":
                        target,

                    "remaining":
                        remaining,

                    "ready":
                        candles >= target,
                }

        progress_pct = 0.0

        if total_target > 0:

            progress_pct = min(
                100.0,
                (
                    total_candles
                    / total_target
                    * 100.0
                ),
            )

        payload = {
            "runtime_version":
                RUNTIME_VERSION,

            "runtime_mode":
                "EMBEDDED_WEB_SERVICE",

            "paid_background_worker_required":
                False,

            "paper_only":
                True,

            "real_execution":
                False,

            "ready":
                bool(
                    status.get(
                        "ready",
                        False,
                    )
                ),

            "progress_pct":
                round(
                    progress_pct,
                    2,
                ),

            "total_candles":
                total_candles,

            "total_target":
                total_target,

            "total_remaining":
                total_remaining,

            "requests_used_last_hour":
                safe_int(
                    status.get(
                        "requests_used_last_hour",
                        0,
                    )
                ),

            "hourly_budget":
                safe_int(
                    status.get(
                        "hourly_budget",
                        INTERNAL_HOURLY_LIMIT,
                    ),
                    INTERNAL_HOURLY_LIMIT,
                ),

            "markets":
                progress_rows,

            "advisory_lock_id":
                ADVISORY_LOCK_ID,
        }

        payload.update(
            extra
        )

        return payload

    # ========================================================
    # HEALTH WRAPPERS
    # ========================================================

    def publish_structured(
        event,
        message="",
        level="INFO",
        payload=None,
    ):

        if not HEALTH_AVAILABLE:
            return

        try:

            structured_log(
                COMPONENT_METALS_BOOTSTRAP,
                event,
                level=level,
                message=message,
                payload=(
                    payload
                    if isinstance(
                        payload,
                        dict,
                    )
                    else {}
                ),
            )

        except Exception:
            pass

    def publish_heartbeat(
        status=None,
        message="Embedded bootstrap runtime alive.",
    ):

        if not HEALTH_AVAILABLE:
            return

        try:

            payload = get_progress_payload(
                status
            )

            heartbeat(
                COMPONENT_METALS_BOOTSTRAP,
                message=message,
                payload=payload,
            )

            state[
                "last_heartbeat"
            ] = time.time()

        except Exception as error:

            log(
                "Health heartbeat failed: "
                f"{error}"
            )

    def publish_warming(
        status,
        message,
        **extra,
    ):

        if not HEALTH_AVAILABLE:
            return

        try:

            report_warming_up(
                COMPONENT_METALS_BOOTSTRAP,
                message=message,
                payload=get_progress_payload(
                    status,
                    **extra,
                ),
            )

            state[
                "last_heartbeat"
            ] = time.time()

        except Exception as error:

            log(
                "Health warm-up publish failed: "
                f"{error}"
            )

    def publish_rate_limit(
        status,
        message,
        **extra,
    ):

        if not HEALTH_AVAILABLE:
            return

        try:

            report_rate_limited(
                COMPONENT_METALS_BOOTSTRAP,
                message=message,
                payload=get_progress_payload(
                    status,
                    **extra,
                ),
            )

            state[
                "last_heartbeat"
            ] = time.time()

        except Exception as error:

            log(
                "Health rate-limit publish failed: "
                f"{error}"
            )

    def publish_error(
        message,
        status=None,
        **extra,
    ):

        if not HEALTH_AVAILABLE:
            return

        try:

            report_error(
                COMPONENT_METALS_BOOTSTRAP,
                message=message,
                payload=get_progress_payload(
                    status,
                    **extra,
                ),
            )

            state[
                "last_heartbeat"
            ] = time.time()

        except Exception as error:

            log(
                "Health error publish failed: "
                f"{error}"
            )

    def publish_ready(
        status,
    ):

        if not HEALTH_AVAILABLE:
            return

        try:

            update_runtime_state(
                COMPONENT_METALS_BOOTSTRAP,
                status=STATUS_HEALTHY,
                success=True,
                message=(
                    "Metals historical bootstrap READY."
                ),
                payload=get_progress_payload(
                    status,
                    bootstrap_complete=True,
                ),
            )

            state[
                "last_heartbeat"
            ] = time.time()

        except Exception as error:

            log(
                "Health READY publish failed: "
                f"{error}"
            )

    # ========================================================
    # INTERRUPTIBLE / HEARTBEAT-AWARE SLEEP
    # ========================================================

    def heartbeat_sleep(
        seconds,
        status=None,
        reason="idle",
    ):

        seconds = max(
            1,
            safe_int(
                seconds,
                1,
            ),
        )

        deadline = (
            time.monotonic()
            + seconds
        )

        last_hb = 0.0

        while (
            time.monotonic()
            < deadline
        ):

            remaining = (
                deadline
                - time.monotonic()
            )

            time.sleep(
                min(
                    10.0,
                    max(
                        0.1,
                        remaining,
                    ),
                )
            )

            now_monotonic = (
                time.monotonic()
            )

            if (
                now_monotonic
                - last_hb
                >= HEARTBEAT_INTERVAL_SECONDS
            ):

                publish_heartbeat(
                    status=status,
                    message=(
                        "Embedded metals bootstrap alive "
                        f"while {reason}."
                    ),
                )

                last_hb = (
                    now_monotonic
                )

    # ========================================================
    # FAIR MARKET SELECTION
    # ========================================================

    def select_next_market(
        status,
    ):

        """
        Least-complete series wins.

        Prevents one symbol or timeframe consuming the entire
        historical quota.
        """

        markets = status.get(
            "markets",
            {},
        )

        candidates = []

        timeframe_rank = {
            "4h": 0,
            "1h": 1,
            "15m": 2,
        }

        symbol_rank = {
            "XAUUSD": 0,
            "XAGUSD": 1,
        }

        for symbol in (
            "XAUUSD",
            "XAGUSD",
        ):

            symbol_data = markets.get(
                symbol,
                {},
            )

            for timeframe in (
                "4h",
                "1h",
                "15m",
            ):

                info = symbol_data.get(
                    timeframe,
                    {},
                )

                candles = safe_int(
                    info.get(
                        "candles",
                        0,
                    )
                )

                target = safe_int(
                    info.get(
                        "target",
                        60,
                    ),
                    60,
                )

                if candles >= target:
                    continue

                completion_ratio = (
                    candles / target
                    if target > 0
                    else 1.0
                )

                candidates.append(
                    (
                        completion_ratio,
                        candles,
                        timeframe_rank[
                            timeframe
                        ],
                        symbol_rank[
                            symbol
                        ],
                        symbol,
                        timeframe,
                    )
                )

        if not candidates:
            return None

        candidates.sort()

        selected = candidates[0]

        return {
            "symbol":
                selected[4],

            "timeframe":
                selected[5],
        }

    # ========================================================
    # WORKER LOOP
    # ========================================================

    def worker_loop():

        lock_connection = None

        state[
            "thread_alive"
        ] = True

        try:

            # ------------------------------------------------
            # SESSION-LEVEL DISTRIBUTED LOCK
            # ------------------------------------------------

            lock_connection = (
                psycopg.connect(
                    DATABASE_URL,
                    autocommit=True,
                    connect_timeout=10,
                )
            )

            with (
                lock_connection.cursor()
            ) as cur:

                cur.execute(
                    """
                    SELECT pg_try_advisory_lock(%s)
                    """,
                    (
                        ADVISORY_LOCK_ID,
                    ),
                )

                row = cur.fetchone()

            lock_acquired = bool(
                row
                and row[0]
            )

            state[
                "lock_acquired"
            ] = lock_acquired

            if not lock_acquired:

                message = (
                    "Another metals bootstrap runtime "
                    "already owns the PostgreSQL lock. "
                    "This embedded runtime is disabled."
                )

                log(
                    message
                )

                publish_structured(
                    "LOCK_NOT_ACQUIRED",
                    message=message,
                    level="WARNING",
                    payload={
                        "lock_id":
                            ADVISORY_LOCK_ID,
                    },
                )

                return

            # ------------------------------------------------
            # LOCK ACQUIRED
            # ------------------------------------------------

            log(
                "Automatic bootstrap lock acquired."
            )

            state[
                "last_action"
            ] = "LOCK_ACQUIRED"

            publish_structured(
                "RUNTIME_STARTED",
                message=(
                    "Embedded metals bootstrap runtime started."
                ),
                payload={
                    "runtime_version":
                        RUNTIME_VERSION,

                    "mode":
                        "EMBEDDED_WEB_SERVICE",

                    "lock_id":
                        ADVISORY_LOCK_ID,
                },
            )

            if HEALTH_AVAILABLE:

                try:

                    record_runtime_event(
                        COMPONENT_METALS_BOOTSTRAP,
                        "RUNTIME_STARTED",
                        severity="INFO",
                        message=(
                            "Embedded Web Service metals "
                            "bootstrap runtime started."
                        ),
                        payload={
                            "version":
                                RUNTIME_VERSION,

                            "paid_worker":
                                False,
                        },
                    )

                except Exception:
                    pass

            # =================================================
            # MAIN LOOP
            # =================================================

            while True:

                try:

                    status = (
                        bootstrap_status()
                    )

                    # -----------------------------------------
                    # BOOTSTRAP COMPLETE
                    # -----------------------------------------

                    if status.get(
                        "ready",
                        False,
                    ):

                        state[
                            "last_action"
                        ] = "READY"

                        log(
                            "Historical bootstrap READY. "
                            "No API request required."
                        )

                        publish_ready(
                            status
                        )

                        heartbeat_sleep(
                            READY_SLEEP_SECONDS,
                            status=status,
                            reason=(
                                "bootstrap READY idle"
                            ),
                        )

                        continue

                    # -----------------------------------------
                    # INTERNAL HOURLY BUDGET
                    # -----------------------------------------

                    used = safe_int(
                        requests_used_last_hour(),
                        0,
                    )

                    if (
                        used
                        >= INTERNAL_HOURLY_LIMIT
                    ):

                        state[
                            "last_action"
                        ] = "LOCAL_RATE_LIMIT"

                        message = (
                            "Hourly historical budget reached: "
                            f"{used}/"
                            f"{INTERNAL_HOURLY_LIMIT}. "
                            "Waiting safely."
                        )

                        log(
                            message
                        )

                        publish_rate_limit(
                            status,
                            message,
                            limit_type=(
                                "INTERNAL_HISTORICAL_BUDGET"
                            ),
                            requests_used=used,
                            wait_seconds=(
                                BUDGET_WAIT_SECONDS
                            ),
                        )

                        heartbeat_sleep(
                            BUDGET_WAIT_SECONDS,
                            status=status,
                            reason=(
                                "internal quota wait"
                            ),
                        )

                        continue

                    # -----------------------------------------
                    # SELECT LEAST-COMPLETE SERIES
                    # -----------------------------------------

                    selected = (
                        select_next_market(
                            status
                        )
                    )

                    if selected is None:

                        state[
                            "last_action"
                        ] = "NO_MISSING_SERIES"

                        log(
                            "No missing historical series."
                        )

                        publish_ready(
                            status
                        )

                        heartbeat_sleep(
                            READY_SLEEP_SECONDS,
                            status=status,
                            reason=(
                                "no missing series"
                            ),
                        )

                        continue

                    symbol = selected[
                        "symbol"
                    ]

                    timeframe = selected[
                        "timeframe"
                    ]

                    state[
                        "last_action"
                    ] = (
                        f"FETCH_{symbol}_{timeframe}"
                    )

                    log(
                        "Fetching next historical candle: "
                        f"{symbol} {timeframe}"
                    )

                    publish_warming(
                        status,
                        (
                            "Fetching historical "
                            f"{symbol} {timeframe}."
                        ),
                        current_symbol=symbol,
                        current_timeframe=timeframe,
                    )

                    # -----------------------------------------
                    # EXACTLY ONE HISTORICAL API REQUEST
                    # -----------------------------------------

                    result = (
                        fetch_gold_api_ohlc(
                            symbol,
                            timeframe,
                        )
                    )

                    state[
                        "last_result"
                    ] = result

                    state[
                        "last_error"
                    ] = None

                    # -----------------------------------------
                    # SUCCESS
                    # -----------------------------------------

                    if result.get(
                        "ok",
                        False,
                    ):

                        state[
                            "last_action"
                        ] = "CANDLE_STORED"

                        log(
                            "Historical candle stored: "
                            f"{symbol} {timeframe}"
                        )

                        try:

                            refreshed_status = (
                                bootstrap_status()
                            )

                        except Exception:

                            refreshed_status = (
                                status
                            )

                        publish_warming(
                            refreshed_status,
                            (
                                "Historical candle stored: "
                                f"{symbol} {timeframe}."
                            ),
                            last_symbol=symbol,
                            last_timeframe=timeframe,
                            last_result="STORED",
                        )

                        publish_structured(
                            "HISTORICAL_CANDLE_STORED",
                            message=(
                                f"{symbol} {timeframe}"
                            ),
                            payload={
                                "symbol":
                                    symbol,

                                "timeframe":
                                    timeframe,
                            },
                        )

                    # -----------------------------------------
                    # LOCAL BUDGET REACHED
                    # -----------------------------------------

                    elif result.get(
                        "rate_limited_locally",
                        False,
                    ):

                        state[
                            "last_action"
                        ] = "LOCAL_RATE_LIMIT"

                        message = (
                            "Local historical API "
                            "budget reached."
                        )

                        log(
                            message
                        )

                        publish_rate_limit(
                            status,
                            message,
                            limit_type="LOCAL",
                            wait_seconds=(
                                BUDGET_WAIT_SECONDS
                            ),
                        )

                        heartbeat_sleep(
                            BUDGET_WAIT_SECONDS,
                            status=status,
                            reason=(
                                "local API budget wait"
                            ),
                        )

                        continue

                    # -----------------------------------------
                    # PROVIDER RATE LIMIT
                    # -----------------------------------------

                    elif result.get(
                        "provider_rate_limited",
                        False,
                    ):

                        state[
                            "last_action"
                        ] = "PROVIDER_RATE_LIMIT"

                        message = (
                            "Gold-API historical rate "
                            "limit reached. Waiting safely."
                        )

                        log(
                            message
                        )

                        publish_rate_limit(
                            status,
                            message,
                            provider="Gold-API",
                            limit_type="PROVIDER",
                            wait_seconds=(
                                BUDGET_WAIT_SECONDS
                            ),
                        )

                        heartbeat_sleep(
                            BUDGET_WAIT_SECONDS,
                            status=status,
                            reason=(
                                "Gold-API rate-limit wait"
                            ),
                        )

                        continue

                    # -----------------------------------------
                    # CLOSED SESSION / NO USABLE CANDLE
                    # -----------------------------------------

                    elif result.get(
                        "skipped_interval",
                        False,
                    ):

                        state[
                            "last_action"
                        ] = "INTERVAL_SKIPPED"

                        message = (
                            "Historical interval skipped: "
                            f"{symbol} {timeframe}."
                        )

                        log(
                            message
                        )

                        publish_warming(
                            status,
                            message,
                            current_symbol=symbol,
                            current_timeframe=timeframe,
                            result_type=(
                                "SKIPPED_INTERVAL"
                            ),
                        )

                    # -----------------------------------------
                    # NON-FATAL PROVIDER RESPONSE
                    # -----------------------------------------

                    else:

                        state[
                            "last_action"
                        ] = "NO_USABLE_CANDLE"

                        message = (
                            "Historical request returned "
                            "no usable candle: "
                            f"{result}"
                        )

                        log(
                            message
                        )

                        publish_warming(
                            status,
                            message,
                            current_symbol=symbol,
                            current_timeframe=timeframe,
                            result_type=(
                                "NO_USABLE_CANDLE"
                            ),
                        )

                    # -----------------------------------------
                    # NORMAL QUOTA-SAFE INTERVAL
                    # -----------------------------------------

                    heartbeat_sleep(
                        REQUEST_INTERVAL_SECONDS,
                        status=(
                            refreshed_status
                            if (
                                result.get(
                                    "ok",
                                    False,
                                )
                                and "refreshed_status"
                                in locals()
                            )
                            else status
                        ),
                        reason=(
                            "normal historical request interval"
                        ),
                    )

                except Exception as error:

                    state[
                        "last_error"
                    ] = str(
                        error
                    )

                    state[
                        "last_action"
                    ] = "CYCLE_ERROR"

                    message = (
                        "Runtime cycle error: "
                        f"{error}"
                    )

                    log(
                        message
                    )

                    publish_error(
                        message,
                        error_type=(
                            type(
                                error
                            ).__name__
                        ),
                        retry_seconds=(
                            ERROR_SLEEP_SECONDS
                        ),
                    )

                    publish_structured(
                        "RUNTIME_CYCLE_ERROR",
                        message=str(
                            error
                        ),
                        level="ERROR",
                        payload={
                            "error_type":
                                type(
                                    error
                                ).__name__,
                        },
                    )

                    heartbeat_sleep(
                        ERROR_SLEEP_SECONDS,
                        reason=(
                            "runtime error retry"
                        ),
                    )

        except Exception as error:

            state[
                "last_error"
            ] = str(
                error
            )

            state[
                "last_action"
            ] = "STARTUP_ERROR"

            message = (
                "Runtime startup error: "
                f"{error}"
            )

            log(
                message
            )

            publish_error(
                message,
                error_type=(
                    type(
                        error
                    ).__name__
                ),
                phase="STARTUP",
            )

        finally:

            # ------------------------------------------------
            # RELEASE ADVISORY LOCK
            # ------------------------------------------------

            if (
                lock_connection
                is not None
            ):

                try:

                    with (
                        lock_connection.cursor()
                    ) as cur:

                        cur.execute(
                            """
                            SELECT pg_advisory_unlock(%s)
                            """,
                            (
                                ADVISORY_LOCK_ID,
                            ),
                        )

                except Exception:
                    pass

                try:

                    lock_connection.close()

                except Exception:
                    pass

            state[
                "lock_acquired"
            ] = False

            state[
                "thread_alive"
            ] = False

            if HEALTH_AVAILABLE:

                try:

                    update_runtime_state(
                        COMPONENT_METALS_BOOTSTRAP,
                        status="OFFLINE",
                        success=False,
                        message=(
                            "Embedded metals bootstrap "
                            "runtime stopped."
                        ),
                        payload={
                            "runtime_version":
                                RUNTIME_VERSION,

                            "runtime_mode":
                                "EMBEDDED_WEB_SERVICE",

                            "paper_only":
                                True,
                        },
                    )

                except Exception:
                    pass

    # ========================================================
    # START DAEMON THREAD
    # ========================================================

    thread = threading.Thread(
        target=worker_loop,
        name="metals-auto-bootstrap-v5",
        daemon=True,
    )

    thread.start()

    state[
        "started"
    ] = True

    state[
        "thread_name"
    ] = thread.name

    return state


# ============================================================
# START EXISTING-WEB-SERVICE BOOTSTRAP
# ============================================================

_metals_auto_bootstrap_state = (
    start_metals_auto_bootstrap()
)

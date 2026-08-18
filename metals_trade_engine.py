"""
metals_trade_engine.py

PRO AI QUANT TERMINAL V4.0
INSTITUTIONAL-SAFE METALS PAPER EXECUTION ENGINE

Markets
-------
XAUUSD
XAGUSD

Purpose
-------
- Scan Gold / Silver
- Accept only fully approved READY scanner setups
- Enforce MTF, freshness, ATR and risk/reward safety
- Open maximum ONE metals paper position
- Preserve independent Crypto position
- Monitor metals TP / SL using fresh live prices
- Apply cooldown after metals trade closes
- Block duplicate / stale / warming-up execution
- PAPER TRADING ONLY
- REAL METALS ORDERS HARD-LOCKED

Compatibility
-------------
Designed for:
- metals_scanner.py V3.8+
- metals_provider.py Gold-API layer
- metals_ohlc_store.py V3.9
- PaperTrader multi-slot PostgreSQL engine
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Dict, Optional

from metals_scanner import (
    scan_metals,
    get_best_metals_setup,
    calculate_metals_position_size,
)

from metals_provider import (
    get_metal_quote,
)

from paper_trader import (
    METALS_SLOT,
)


# ============================================================
# CONFIG
# ============================================================

DEFAULT_METALS_RISK_PCT = 0.50

MIN_METALS_MTF_CONFIDENCE = 66.0
MIN_METALS_RISK_REWARD = 1.25

MAX_METALS_RISK_PCT = 1.00

METALS_TRADE_COOLDOWN_SECONDS = 900

SUPPORTED_METALS = {
    "XAUUSD",
    "XAGUSD",
}


# ============================================================
# ABSOLUTE REAL-ORDER HARD LOCK
# ============================================================

REAL_METALS_ORDERS_ENABLED = False
PAPER_ONLY = True


# ============================================================
# SAFE HELPERS
# ============================================================

def _safe_float(
    value,
    default=None,
):

    try:

        if value is None:
            return default

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


def _normalize_symbol(
    symbol,
):

    return (
        str(symbol)
        .upper()
        .replace("/", "")
        .replace("-", "")
        .replace(" ", "")
        .strip()
    )


def _utc_now():

    return datetime.now(
        timezone.utc
    )


def _parse_datetime(
    value,
):

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


# ============================================================
# LIVE QUOTE SAFETY
# ============================================================

def _quote_is_safe(
    quote: Optional[Dict],
) -> bool:

    if not quote:

        return False

    price = _safe_float(
        quote.get(
            "last"
        )
    )

    if (
        price is None
        or price <= 0
    ):

        return False

    if quote.get(
        "stale",
        False,
    ):

        return False

    if quote.get(
        "data_fresh",
        True,
    ) is False:

        return False

    if quote.get(
        "tradable_data",
        True,
    ) is False:

        return False

    return True


def get_safe_metals_quote(
    symbol: str,
) -> Optional[Dict]:

    symbol = _normalize_symbol(
        symbol
    )

    if symbol not in SUPPORTED_METALS:

        return None

    try:

        quote = get_metal_quote(
            symbol
        )

    except Exception as error:

        print(
            "[METALS V4 QUOTE ERROR] "
            f"{symbol}: {error}",
            flush=True,
        )

        return None

    if not _quote_is_safe(
        quote
    ):

        return None

    return quote


def get_metals_current_price(
    symbol: str,
) -> Optional[float]:

    quote = get_safe_metals_quote(
        symbol
    )

    if not quote:

        return None

    return _safe_float(
        quote.get(
            "last"
        )
    )


# ============================================================
# SCANNER TIMEFRAME VALIDATION
# ============================================================

def _all_scanner_timeframes_valid(
    setup: Dict,
) -> bool:

    timeframes = setup.get(
        "timeframes",
        {},
    )

    if not isinstance(
        timeframes,
        dict,
    ):

        return False

    for timeframe in (
        "15m",
        "1h",
        "4h",
    ):

        info = timeframes.get(
            timeframe,
            {},
        )

        if not info.get(
            "valid",
            False,
        ):

            return False

    return True


# ============================================================
# COOLDOWN
# ============================================================

def get_metals_cooldown_status(
    trader,
) -> Dict:

    try:

        history = trader.get_trade_history(
            asset_class="METAL",
            slot=METALS_SLOT,
        )

    except Exception as error:

        return {
            "cooldown_active":
                True,

            "reason":
                (
                    "Could not validate metals "
                    f"trade history: {error}"
                ),

            "seconds_remaining":
                METALS_TRADE_COOLDOWN_SECONDS,
        }

    if not history:

        return {
            "cooldown_active":
                False,

            "seconds_remaining":
                0,
        }

    latest = history[
        0
    ]

    closed_at = _parse_datetime(
        latest.get(
            "closed_at"
        )
    )

    if closed_at is None:

        return {
            "cooldown_active":
                True,

            "reason":
                "Latest metals trade has invalid closed_at",

            "seconds_remaining":
                METALS_TRADE_COOLDOWN_SECONDS,
        }

    elapsed = (
        _utc_now()
        - closed_at
    ).total_seconds()

    remaining = max(
        0,
        METALS_TRADE_COOLDOWN_SECONDS
        - int(
            elapsed
        ),
    )

    return {
        "cooldown_active":
            remaining > 0,

        "seconds_remaining":
            remaining,

        "latest_closed_at":
            closed_at.isoformat(),

        "latest_symbol":
            latest.get(
                "symbol"
            ),

        "latest_pnl":
            latest.get(
                "pnl"
            ),
    }


# ============================================================
# MONITOR OPEN METALS POSITION
# ============================================================

def monitor_metals_position(
    trader,
) -> Dict:

    position = trader.get_position(
        METALS_SLOT
    )

    if not position:

        return {
            "status":
                "NO_POSITION",

            "real_orders":
                False,
        }

    symbol = _normalize_symbol(
        position.get(
            "symbol"
        )
    )

    if symbol not in SUPPORTED_METALS:

        return {
            "status":
                "POSITION_ERROR",

            "reason":
                "Unsupported symbol in METALS_MAIN",

            "position":
                position,

            "real_orders":
                False,
        }

    quote = get_safe_metals_quote(
        symbol
    )

    if quote is None:

        return {
            "status":
                "PRICE_UNAVAILABLE",

            "reason":
                (
                    "Fresh metals quote unavailable. "
                    "TP/SL evaluation skipped safely."
                ),

            "position":
                position,

            "tp_sl_updated":
                False,

            "real_orders":
                False,
        }

    current_price = _safe_float(
        quote.get(
            "last"
        )
    )

    if (
        current_price is None
        or current_price <= 0
    ):

        return {
            "status":
                "PRICE_UNAVAILABLE",

            "reason":
                "Invalid live metals price",

            "position":
                position,

            "tp_sl_updated":
                False,

            "real_orders":
                False,
        }

    result = trader.update_price(
        current_price=current_price,
        slot=METALS_SLOT,
    )

    if result is None:

        return {
            "status":
                "NO_POSITION",

            "real_orders":
                False,
        }

    result[
        "current_price"
    ] = current_price

    result[
        "quote_source"
    ] = quote.get(
        "source"
    )

    result[
        "quote_fresh"
    ] = True

    result[
        "tp_sl_updated"
    ] = True

    result[
        "paper_only"
    ] = True

    result[
        "real_orders"
    ] = False

    return result


# ============================================================
# FULL SCANNER SETUP VALIDATION
# ============================================================

def validate_metals_setup(
    setup: Optional[Dict],
) -> Dict:

    if not setup:

        return {
            "valid":
                False,

            "reason":
                "No metals setup available",
        }

    symbol = _normalize_symbol(
        setup.get(
            "symbol"
        )
    )

    signal = str(
        setup.get(
            "signal",
            ""
        )
    ).upper().strip()

    # --------------------------------------------------------
    # SYMBOL
    # --------------------------------------------------------

    if symbol not in SUPPORTED_METALS:

        return {
            "valid":
                False,

            "reason":
                "Unsupported metals symbol",
        }

    # --------------------------------------------------------
    # SCANNER STATE
    # --------------------------------------------------------

    scanner_state = str(
        setup.get(
            "scanner_state",
            ""
        )
    ).upper()

    if scanner_state != "READY":

        return {
            "valid":
                False,

            "reason":
                (
                    "Scanner not READY: "
                    f"{scanner_state or 'UNKNOWN'}"
                ),
        }

    if not setup.get(
        "history_ready",
        False,
    ):

        return {
            "valid":
                False,

            "reason":
                "Historical MTF candles not ready",
        }

    # --------------------------------------------------------
    # SIGNAL APPROVAL
    # --------------------------------------------------------

    if signal not in (
        "BUY",
        "SELL",
    ):

        return {
            "valid":
                False,

            "reason":
                "Scanner signal is not BUY/SELL",
        }

    if not setup.get(
        "approved",
        False,
    ):

        return {
            "valid":
                False,

            "reason":
                "Scanner setup not approved",
        }

    if not setup.get(
        "safety_gate",
        False,
    ):

        return {
            "valid":
                False,

            "reason":
                "Scanner safety gate failed",
        }

    # --------------------------------------------------------
    # DATA FRESHNESS
    # --------------------------------------------------------

    if not setup.get(
        "quote_fresh",
        False,
    ):

        return {
            "valid":
                False,

            "reason":
                "Scanner quote is not fresh",
        }

    if not setup.get(
        "candles_fresh",
        False,
    ):

        return {
            "valid":
                False,

            "reason":
                "Scanner candles are not fresh",
        }

    if not _all_scanner_timeframes_valid(
        setup
    ):

        return {
            "valid":
                False,

            "reason":
                "15m/1h/4h scanner data not fully valid",
        }

    # --------------------------------------------------------
    # HIGHER TIMEFRAME CONFIRMATION
    # --------------------------------------------------------

    if not setup.get(
        "higher_tf_confirmed",
        False,
    ):

        return {
            "valid":
                False,

            "reason":
                "1h + 4h confirmation missing",
        }

    mtf_confidence = _safe_float(
        setup.get(
            "mtf_confidence"
        ),
        0.0,
    )

    if (
        mtf_confidence
        < MIN_METALS_MTF_CONFIDENCE
    ):

        return {
            "valid":
                False,

            "reason":
                (
                    "MTF confidence below "
                    f"{MIN_METALS_MTF_CONFIDENCE:.1f}%"
                ),
        }

    # --------------------------------------------------------
    # TRADE PARAMETERS
    # --------------------------------------------------------

    scanner_entry = _safe_float(
        setup.get(
            "entry_price"
        )
    )

    targets = setup.get(
        "targets",
        {},
    )

    take_profit = _safe_float(
        targets.get(
            "take_profit"
        )
    )

    stop_loss = _safe_float(
        targets.get(
            "stop_loss"
        )
    )

    risk_reward = _safe_float(
        setup.get(
            "risk_reward",
            targets.get(
                "risk_reward"
            ),
        ),
        0.0,
    )

    if (
        scanner_entry is None
        or scanner_entry <= 0
        or take_profit is None
        or take_profit <= 0
        or stop_loss is None
        or stop_loss <= 0
    ):

        return {
            "valid":
                False,

            "reason":
                "Incomplete metals entry/TP/SL",
        }

    if (
        risk_reward
        < MIN_METALS_RISK_REWARD
    ):

        return {
            "valid":
                False,

            "reason":
                (
                    "Risk/reward below "
                    f"{MIN_METALS_RISK_REWARD:.2f}"
                ),
        }

    # --------------------------------------------------------
    # TP / SL STRUCTURE
    # --------------------------------------------------------

    if signal == "BUY":

        valid_structure = (
            stop_loss
            < scanner_entry
            < take_profit
        )

    else:

        valid_structure = (
            take_profit
            < scanner_entry
            < stop_loss
        )

    if not valid_structure:

        return {
            "valid":
                False,

            "reason":
                "Invalid metals TP/SL structure",
        }

    # --------------------------------------------------------
    # FINAL LIVE EXECUTION QUOTE
    # --------------------------------------------------------

    quote = get_safe_metals_quote(
        symbol
    )

    if quote is None:

        return {
            "valid":
                False,

            "reason":
                "Fresh execution quote unavailable",
        }

    live_price = _safe_float(
        quote.get(
            "last"
        )
    )

    if (
        live_price is None
        or live_price <= 0
    ):

        return {
            "valid":
                False,

            "reason":
                "Invalid live execution price",
        }

    return {
        "valid":
            True,

        "reason":
            "Metals V4 execution safety passed",

        "symbol":
            symbol,

        "signal":
            signal,

        "scanner_entry":
            scanner_entry,

        "live_price":
            live_price,

        "take_profit":
            take_profit,

        "stop_loss":
            stop_loss,

        "risk_reward":
            risk_reward,

        "mtf_confidence":
            mtf_confidence,

        "quote":
            quote,
    }


# ============================================================
# REBUILD TARGETS FROM LIVE EXECUTION PRICE
# ============================================================

def _rebuild_targets_from_live_price(
    validation: Dict,
) -> Dict:

    signal = validation[
        "signal"
    ]

    scanner_entry = validation[
        "scanner_entry"
    ]

    live_price = validation[
        "live_price"
    ]

    scanner_tp = validation[
        "take_profit"
    ]

    scanner_sl = validation[
        "stop_loss"
    ]

    tp_distance = abs(
        scanner_tp
        - scanner_entry
    )

    sl_distance = abs(
        scanner_entry
        - scanner_sl
    )

    if (
        tp_distance <= 0
        or sl_distance <= 0
    ):

        return {
            "valid":
                False,

            "reason":
                "Invalid TP/SL distance",
        }

    if signal == "BUY":

        take_profit = (
            live_price
            + tp_distance
        )

        stop_loss = (
            live_price
            - sl_distance
        )

    else:

        take_profit = (
            live_price
            - tp_distance
        )

        stop_loss = (
            live_price
            + sl_distance
        )

    risk_distance = abs(
        live_price
        - stop_loss
    )

    reward_distance = abs(
        take_profit
        - live_price
    )

    if risk_distance <= 0:

        return {
            "valid":
                False,

            "reason":
                "Invalid live risk distance",
        }

    rr = (
        reward_distance
        / risk_distance
    )

    if rr < MIN_METALS_RISK_REWARD:

        return {
            "valid":
                False,

            "reason":
                "Live-price risk/reward degraded below minimum",
        }

    return {
        "valid":
            True,

        "entry_price":
            live_price,

        "take_profit":
            take_profit,

        "stop_loss":
            stop_loss,

        "risk_reward":
            rr,
    }


# ============================================================
# OPEN APPROVED METALS PAPER TRADE
# ============================================================

def open_metals_trade(
    trader,
    setup: Dict,
    risk_pct: float = DEFAULT_METALS_RISK_PCT,
) -> Dict:

    # --------------------------------------------------------
    # HARD REAL ORDER LOCK
    # --------------------------------------------------------

    if (
        REAL_METALS_ORDERS_ENABLED
        or not PAPER_ONLY
    ):

        return {
            "status":
                "BLOCKED",

            "reason":
                "Real metals execution is hard-locked",

            "real_orders":
                False,
        }

    # --------------------------------------------------------
    # EXISTING POSITION
    # --------------------------------------------------------

    if not trader.slot_available(
        METALS_SLOT
    ):

        return {
            "status":
                "SKIPPED",

            "reason":
                "METALS_MAIN already occupied",

            "position":
                trader.get_position(
                    METALS_SLOT
                ),

            "real_orders":
                False,
        }

    # --------------------------------------------------------
    # COOLDOWN
    # --------------------------------------------------------

    cooldown = get_metals_cooldown_status(
        trader
    )

    if cooldown.get(
        "cooldown_active",
        False,
    ):

        return {
            "status":
                "COOLDOWN",

            "reason":
                (
                    "Metals trade cooldown active"
                ),

            "cooldown":
                cooldown,

            "real_orders":
                False,
        }

    # --------------------------------------------------------
    # VALIDATE SCANNER SETUP
    # --------------------------------------------------------

    validation = validate_metals_setup(
        setup
    )

    if not validation.get(
        "valid",
        False,
    ):

        return {
            "status":
                "SKIPPED",

            "reason":
                validation.get(
                    "reason",
                    "Metals safety validation failed",
                ),

            "real_orders":
                False,
        }

    # --------------------------------------------------------
    # LIVE TARGET REBUILD
    # --------------------------------------------------------

    rebuilt = _rebuild_targets_from_live_price(
        validation
    )

    if not rebuilt.get(
        "valid",
        False,
    ):

        return {
            "status":
                "SKIPPED",

            "reason":
                rebuilt.get(
                    "reason"
                ),

            "real_orders":
                False,
        }

    symbol = validation[
        "symbol"
    ]

    signal = validation[
        "signal"
    ]

    entry_price = rebuilt[
        "entry_price"
    ]

    take_profit = rebuilt[
        "take_profit"
    ]

    stop_loss = rebuilt[
        "stop_loss"
    ]

    # --------------------------------------------------------
    # RISK PERCENTAGE
    # --------------------------------------------------------

    risk_pct = _safe_float(
        risk_pct
    )

    if (
        risk_pct is None
        or risk_pct <= 0
    ):

        return {
            "status":
                "SKIPPED",

            "reason":
                "Invalid metals risk percentage",

            "real_orders":
                False,
        }

    risk_pct = min(
        risk_pct,
        MAX_METALS_RISK_PCT,
    )

    # --------------------------------------------------------
    # ACCOUNT BALANCE
    # --------------------------------------------------------

    balance = _safe_float(
        trader.get_balance()
    )

    if (
        balance is None
        or balance <= 0
    ):

        return {
            "status":
                "SKIPPED",

            "reason":
                "Invalid paper account balance",

            "real_orders":
                False,
        }

    # --------------------------------------------------------
    # POSITION SIZE
    # --------------------------------------------------------

    quantity = calculate_metals_position_size(
        account_balance=balance,
        risk_pct=risk_pct,
        entry_price=entry_price,
        stop_loss=stop_loss,
    )

    if quantity <= 0:

        return {
            "status":
                "SKIPPED",

            "reason":
                "Invalid metals position size",

            "real_orders":
                False,
        }

    # --------------------------------------------------------
    # FINAL SLOT RECHECK
    # --------------------------------------------------------

    if not trader.slot_available(
        METALS_SLOT
    ):

        return {
            "status":
                "SKIPPED",

            "reason":
                "METALS_MAIN became occupied before execution",

            "real_orders":
                False,
        }

    # --------------------------------------------------------
    # PAPER EXECUTION ONLY
    # --------------------------------------------------------

    result = trader.open_trade(
        symbol=symbol,
        signal=signal,
        entry_price=entry_price,
        quantity=quantity,
        take_profit=take_profit,
        stop_loss=stop_loss,
        slot=METALS_SLOT,
    )

    if result is None:

        return {
            "status":
                "ERROR",

            "reason":
                "Paper trader returned no result",

            "real_orders":
                False,
        }

    result[
        "risk_pct"
    ] = risk_pct

    result[
        "risk_reward"
    ] = rebuilt[
        "risk_reward"
    ]

    result[
        "mtf_confidence"
    ] = validation[
        "mtf_confidence"
    ]

    result[
        "score"
    ] = setup.get(
        "score",
        0.0,
    )

    result[
        "scanner_state"
    ] = setup.get(
        "scanner_state"
    )

    result[
        "history_ready"
    ] = setup.get(
        "history_ready",
        False,
    )

    result[
        "higher_tf_confirmed"
    ] = setup.get(
        "higher_tf_confirmed",
        False,
    )

    result[
        "safety_gate"
    ] = True

    result[
        "paper_trade"
    ] = True

    result[
        "paper_only"
    ] = True

    result[
        "real_order"
    ] = False

    result[
        "real_orders"
    ] = False

    return result


# ============================================================
# AUTONOMOUS METALS CYCLE
# ============================================================

def run_metals_cycle(
    trader,
    risk_pct: float = DEFAULT_METALS_RISK_PCT,
) -> Dict:

    # --------------------------------------------------------
    # 1. MANAGE EXISTING POSITION FIRST
    # --------------------------------------------------------

    existing = trader.get_position(
        METALS_SLOT
    )

    if existing:

        monitor_result = monitor_metals_position(
            trader
        )

        return {
            "status":
                "MANAGING_POSITION",

            "position":
                trader.get_position(
                    METALS_SLOT
                ),

            "monitor":
                monitor_result,

            "scanner_results":
                [],

            "best_setup":
                None,

            "paper_only":
                True,

            "real_orders":
                False,
        }

    # --------------------------------------------------------
    # 2. COOLDOWN
    # --------------------------------------------------------

    cooldown = get_metals_cooldown_status(
        trader
    )

    if cooldown.get(
        "cooldown_active",
        False,
    ):

        return {
            "status":
                "COOLDOWN",

            "position":
                None,

            "cooldown":
                cooldown,

            "scanner_results":
                [],

            "best_setup":
                None,

            "paper_only":
                True,

            "real_orders":
                False,
        }

    # --------------------------------------------------------
    # 3. SCAN GOLD + SILVER
    # --------------------------------------------------------

    results = scan_metals()

    # --------------------------------------------------------
    # 4. DETECT WARM-UP
    # --------------------------------------------------------

    warming = [
        item
        for item in results
        if str(
            item.get(
                "scanner_state",
                ""
            )
        ).upper()
        == "WARMING_UP"
    ]

    ready = [
        item
        for item in results
        if str(
            item.get(
                "scanner_state",
                ""
            )
        ).upper()
        == "READY"
    ]

    if (
        warming
        and not ready
    ):

        return {
            "status":
                "WARMING_UP",

            "position":
                None,

            "scanner_results":
                results,

            "best_setup":
                None,

            "paper_only":
                True,

            "real_orders":
                False,
        }

    # --------------------------------------------------------
    # 5. FIND BEST APPROVED SETUP
    # --------------------------------------------------------

    best_setup = get_best_metals_setup(
        results
    )

    if best_setup is None:

        return {
            "status":
                "NO_QUALIFYING_METALS_TRADE",

            "position":
                None,

            "scanner_results":
                results,

            "best_setup":
                None,

            "paper_only":
                True,

            "real_orders":
                False,
        }

    # --------------------------------------------------------
    # 6. FINAL EXECUTION VALIDATION
    # --------------------------------------------------------

    validation = validate_metals_setup(
        best_setup
    )

    if not validation.get(
        "valid",
        False,
    ):

        return {
            "status":
                "SAFETY_BLOCKED",

            "reason":
                validation.get(
                    "reason"
                ),

            "position":
                None,

            "scanner_results":
                results,

            "best_setup":
                best_setup,

            "paper_only":
                True,

            "real_orders":
                False,
        }

    # --------------------------------------------------------
    # 7. OPEN PAPER POSITION
    # --------------------------------------------------------

    execution = open_metals_trade(
        trader=trader,
        setup=best_setup,
        risk_pct=risk_pct,
    )

    return {
        "status":
            execution.get(
                "status",
                "UNKNOWN",
            ),

        "position":
            trader.get_position(
                METALS_SLOT
            ),

        "scanner_results":
            results,

        "best_setup":
            best_setup,

        "execution":
            execution,

        "paper_only":
            True,

        "real_orders":
            False,
    }


# ============================================================
# SAFE STATUS SNAPSHOT
# ============================================================

def get_metals_trade_status(
    trader,
) -> Dict:

    position = trader.get_position(
        METALS_SLOT
    )

    cooldown = get_metals_cooldown_status(
        trader
    )

    if position:

        symbol = position.get(
            "symbol"
        )

        quote = get_safe_metals_quote(
            symbol
        )

        current_price = None

        if quote:

            current_price = _safe_float(
                quote.get(
                    "last"
                )
            )

        return {
            "status":
                "POSITION_OPEN",

            "position":
                position,

            "current_price":
                current_price,

            "price_fresh":
                quote is not None,

            "cooldown":
                cooldown,

            "paper_only":
                True,

            "real_orders":
                False,
        }

    return {
        "status":
            (
                "COOLDOWN"
                if cooldown.get(
                    "cooldown_active",
                    False,
                )
                else "FLAT"
            ),

        "position":
            None,

        "current_price":
            None,

        "price_fresh":
            False,

        "cooldown":
            cooldown,

        "paper_only":
            True,

        "real_orders":
            False,
    }


# ============================================================
# HEALTH
# ============================================================

def metals_trade_engine_health(
    trader=None,
) -> Dict:

    result = {
        "ok":
            True,

        "engine":
            "V4.0 Metals Paper Execution",

        "paper_only":
            True,

        "real_orders":
            False,

        "real_execution_locked":
            True,

        "max_metals_positions":
            1,

        "slot":
            METALS_SLOT,

        "min_mtf_confidence":
            MIN_METALS_MTF_CONFIDENCE,

        "min_risk_reward":
            MIN_METALS_RISK_REWARD,

        "default_risk_pct":
            DEFAULT_METALS_RISK_PCT,

        "max_risk_pct":
            MAX_METALS_RISK_PCT,

        "cooldown_seconds":
            METALS_TRADE_COOLDOWN_SECONDS,
    }

    if trader is not None:

        try:

            result[
                "status"
            ] = get_metals_trade_status(
                trader
            )

        except Exception as error:

            result[
                "ok"
            ] = False

            result[
                "reason"
            ] = str(
                error
            )

    return result

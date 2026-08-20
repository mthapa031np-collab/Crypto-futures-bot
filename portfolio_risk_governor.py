"""
portfolio_risk_governor.py

PRO AI QUANT TERMINAL V5.2
UNIFIED MULTI-ASSET PORTFOLIO RISK GOVERNOR
WITH AUTOMATIC LOSS-STREAK RECOVERY

Purpose
-------
Central account-level PAPER risk authority for:
- CRYPTO
- METALS
- future STOCK / FX / INDEX / FUTURES adapters

Key V5.2 change
---------------
V5.2 adds precision-safe percentage limit comparisons so microscopic
floating-point/quantity-rounding noise at an exact configured risk
boundary does not falsely reject a trade. A genuine excess above the
tolerance remains blocked.

The old V5.0 logic permanently blocked new entries once
MAX_CONSECUTIVE_LOSSES was reached. Because no new trade could
open, the streak could never be broken by a later winning trade.

V5.1 keeps the protection but converts it into a timed recovery:
- After the configured loss streak is reached, entries pause.
- After LOSS_STREAK_RECOVERY_SECONDS, the next qualifying PAPER
  trade may proceed.
- If that trade wins, the consecutive-loss count resets naturally.
- If it loses, the latest close time moves forward and a new
  recovery cooldown starts.

All other safety gates remain active:
- daily loss
- total drawdown
- total portfolio risk
- per-asset risk
- position / slot limits
- duplicate-symbol protection
- global cooldown
- side-aware stop validation
- PostgreSQL audit/state
- PAPER ONLY
- REAL EXECUTION HARD LOCKED
"""

from __future__ import annotations

import math
import os
from datetime import datetime, timezone
from typing import Dict, List, Optional

import psycopg
from psycopg.rows import dict_row

from paper_trader import (
    CRYPTO_SLOT,
    METALS_SLOT,
)


# ============================================================
# VERSION / HARD SAFETY
# ============================================================

ENGINE_VERSION = "V5.2 Portfolio Risk Governor"

PAPER_ONLY = True
REAL_EXECUTION_ENABLED = False

if REAL_EXECUTION_ENABLED:
    raise RuntimeError(
        "REAL_EXECUTION_ENABLED must remain False."
    )


# ============================================================
# DATABASE
# ============================================================

DATABASE_URL = os.environ.get(
    "DATABASE_URL",
    "",
).strip()


# ============================================================
# ENV HELPERS
# ============================================================

def _env_float(
    name: str,
    default: float,
    *,
    minimum: Optional[float] = None,
    maximum: Optional[float] = None,
) -> float:

    raw = os.environ.get(
        name,
        str(default),
    )

    try:
        value = float(raw)
    except (
        TypeError,
        ValueError,
    ):
        value = float(default)

    if not math.isfinite(value):
        value = float(default)

    if minimum is not None:
        value = max(
            minimum,
            value,
        )

    if maximum is not None:
        value = min(
            maximum,
            value,
        )

    return value


def _env_int(
    name: str,
    default: int,
    *,
    minimum: Optional[int] = None,
    maximum: Optional[int] = None,
) -> int:

    raw = os.environ.get(
        name,
        str(default),
    )

    try:
        value = int(raw)
    except (
        TypeError,
        ValueError,
    ):
        value = int(default)

    if minimum is not None:
        value = max(
            minimum,
            value,
        )

    if maximum is not None:
        value = min(
            maximum,
            value,
        )

    return value


# ============================================================
# CONFIG
# ============================================================

MAX_DAILY_LOSS_PCT = _env_float(
    "MAX_DAILY_LOSS_PCT",
    5.0,
    minimum=0.1,
    maximum=100.0,
)

MAX_TOTAL_DRAWDOWN_PCT = _env_float(
    "MAX_TOTAL_DRAWDOWN_PCT",
    10.0,
    minimum=0.1,
    maximum=100.0,
)

MAX_PORTFOLIO_RISK_PCT = _env_float(
    "MAX_PORTFOLIO_RISK_PCT",
    3.0,
    minimum=0.1,
    maximum=100.0,
)

MAX_TOTAL_OPEN_POSITIONS = _env_int(
    "MAX_TOTAL_OPEN_POSITIONS",
    2,
    minimum=1,
)

MAX_CRYPTO_POSITIONS = _env_int(
    "MAX_CRYPTO_POSITIONS",
    1,
    minimum=0,
)

MAX_METALS_POSITIONS = _env_int(
    "MAX_METALS_POSITIONS",
    1,
    minimum=0,
)

MAX_CONSECUTIVE_LOSSES = _env_int(
    "MAX_CONSECUTIVE_LOSSES",
    3,
    minimum=1,
)

GLOBAL_TRADE_COOLDOWN_SECONDS = _env_int(
    "GLOBAL_TRADE_COOLDOWN_SECONDS",
    300,
    minimum=0,
)

# V5.1: loss streak is no longer a permanent deadlock.
LOSS_STREAK_RECOVERY_SECONDS = _env_int(
    "LOSS_STREAK_RECOVERY_SECONDS",
    1800,
    minimum=60,
    maximum=86400,
)

MAX_CRYPTO_RISK_PCT = _env_float(
    "MAX_CRYPTO_RISK_PCT",
    1.0,
    minimum=0.01,
    maximum=100.0,
)

MAX_METALS_RISK_PCT = _env_float(
    "MAX_METALS_RISK_PCT",
    1.0,
    minimum=0.01,
    maximum=100.0,
)

MAX_STOCK_RISK_PCT = _env_float(
    "MAX_STOCK_RISK_PCT",
    1.0,
    minimum=0.01,
    maximum=100.0,
)

MAX_FX_RISK_PCT = _env_float(
    "MAX_FX_RISK_PCT",
    1.0,
    minimum=0.01,
    maximum=100.0,
)

MAX_INDEX_RISK_PCT = _env_float(
    "MAX_INDEX_RISK_PCT",
    1.0,
    minimum=0.01,
    maximum=100.0,
)

MAX_FUTURES_RISK_PCT = _env_float(
    "MAX_FUTURES_RISK_PCT",
    1.0,
    minimum=0.01,
    maximum=100.0,
)

# V5.2: percentage-point tolerance used only for boundary comparisons.
# Default 1e-6 means 0.000001 percentage points (not 0.000001 as a fraction).
# This absorbs harmless IEEE-754 / quantity-rounding noise while preserving
# every material configured risk limit.
RISK_COMPARISON_EPSILON_PCT = _env_float(
    "RISK_COMPARISON_EPSILON_PCT",
    1e-6,
    minimum=0.0,
    maximum=0.01,
)


# ============================================================
# ASSET SUPPORT
# ============================================================

ASSET_SLOT_MAP = {
    "CRYPTO": CRYPTO_SLOT,
    "METAL": METALS_SLOT,
    "METALS": METALS_SLOT,
}

ASSET_RISK_LIMITS = {
    "CRYPTO": MAX_CRYPTO_RISK_PCT,
    "METAL": MAX_METALS_RISK_PCT,
    "STOCK": MAX_STOCK_RISK_PCT,
    "FX": MAX_FX_RISK_PCT,
    "INDEX": MAX_INDEX_RISK_PCT,
    "FUTURES": MAX_FUTURES_RISK_PCT,
}


# ============================================================
# BASIC HELPERS
# ============================================================

def _utc_now() -> datetime:
    return datetime.now(
        timezone.utc
    )


def _safe_float(
    value,
    default=0.0,
):

    try:
        if value is None:
            return default

        number = float(value)

        if not math.isfinite(number):
            return default

        return number

    except (
        TypeError,
        ValueError,
        OverflowError,
    ):
        return default




def _risk_pct_exceeds_limit(
    value_pct,
    limit_pct,
) -> bool:
    """Precision-safe strict risk-limit comparison in percentage points."""

    value = _safe_float(
        value_pct,
        default=float("inf"),
    )
    limit = _safe_float(
        limit_pct,
        default=float("-inf"),
    )

    return value > (
        limit
        + RISK_COMPARISON_EPSILON_PCT
    )

def _safe_positive_float(
    value,
    default=0.0,
):

    number = _safe_float(
        value,
        default,
    )

    if number <= 0:
        return default

    return number


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

    return dt.astimezone(
        timezone.utc
    )


def _normalize_symbol(
    symbol,
) -> str:

    return (
        str(
            symbol
            or ""
        )
        .upper()
        .replace("/", "")
        .replace("-", "")
        .replace(" ", "")
        .strip()
    )


def _normalize_asset_class(
    asset_class,
) -> str:

    value = (
        str(
            asset_class
            or ""
        )
        .upper()
        .strip()
    )

    aliases = {
        "METALS": "METAL",
        "EQUITY": "STOCK",
        "EQUITIES": "STOCK",
        "FOREX": "FX",
        "INDICES": "INDEX",
        "FUTURE": "FUTURES",
    }

    return aliases.get(
        value,
        value,
    )


def _normalize_side(
    side,
) -> Optional[str]:

    if side is None:
        return None

    value = (
        str(side)
        .upper()
        .strip()
    )

    aliases = {
        "BUY": "LONG",
        "LONG": "LONG",
        "SELL": "SHORT",
        "SHORT": "SHORT",
    }

    return aliases.get(
        value
    )


def _asset_slot(
    asset_class,
):

    return ASSET_SLOT_MAP.get(
        _normalize_asset_class(
            asset_class
        )
    )


# ============================================================
# DATABASE CONNECTION / TABLES
# ============================================================

def _connect():

    if not DATABASE_URL:
        raise RuntimeError(
            "DATABASE_URL is not configured."
        )

    return psycopg.connect(
        DATABASE_URL,
        row_factory=dict_row,
        connect_timeout=10,
    )


def ensure_risk_governor_tables():

    if not DATABASE_URL:
        return

    with _connect() as conn:
        with conn.cursor() as cur:

            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS
                portfolio_risk_state (
                    state_key TEXT PRIMARY KEY,
                    utc_date DATE,
                    day_start_equity DOUBLE PRECISION,
                    high_water_equity DOUBLE PRECISION,
                    last_balance DOUBLE PRECISION,
                    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                )
                """
            )

            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS
                portfolio_risk_decisions (
                    id BIGSERIAL PRIMARY KEY,
                    decided_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    approved BOOLEAN NOT NULL,
                    status TEXT NOT NULL,
                    reason TEXT,
                    asset_class TEXT,
                    symbol TEXT,
                    side TEXT,
                    entry_price DOUBLE PRECISION,
                    stop_loss DOUBLE PRECISION,
                    quantity DOUBLE PRECISION,
                    proposed_risk_amount DOUBLE PRECISION,
                    proposed_risk_pct DOUBLE PRECISION,
                    projected_portfolio_risk_pct DOUBLE PRECISION,
                    balance DOUBLE PRECISION
                )
                """
            )

            cur.execute(
                """
                CREATE INDEX IF NOT EXISTS
                idx_portfolio_risk_decisions_time
                ON portfolio_risk_decisions (
                    decided_at DESC
                )
                """
            )

        conn.commit()


# ============================================================
# PERSISTENT ACCOUNT STATE
# ============================================================

def _load_risk_state() -> Optional[Dict]:

    if not DATABASE_URL:
        return None

    ensure_risk_governor_tables()

    with _connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT
                    state_key,
                    utc_date,
                    day_start_equity,
                    high_water_equity,
                    last_balance,
                    updated_at
                FROM portfolio_risk_state
                WHERE state_key = 'GLOBAL'
                """
            )

            return cur.fetchone()


def _save_risk_state(
    *,
    utc_date,
    day_start_equity,
    high_water_equity,
    last_balance,
):

    if not DATABASE_URL:
        return

    ensure_risk_governor_tables()

    with _connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO portfolio_risk_state (
                    state_key,
                    utc_date,
                    day_start_equity,
                    high_water_equity,
                    last_balance,
                    updated_at
                )
                VALUES (
                    'GLOBAL',
                    %s,
                    %s,
                    %s,
                    %s,
                    NOW()
                )
                ON CONFLICT (state_key)
                DO UPDATE SET
                    utc_date = EXCLUDED.utc_date,
                    day_start_equity = EXCLUDED.day_start_equity,
                    high_water_equity = EXCLUDED.high_water_equity,
                    last_balance = EXCLUDED.last_balance,
                    updated_at = NOW()
                """,
                (
                    utc_date,
                    day_start_equity,
                    high_water_equity,
                    last_balance,
                ),
            )

        conn.commit()


def get_account_baseline(
    trader,
) -> Dict:

    balance = _safe_float(
        trader.get_balance()
    )

    starting_balance = _safe_float(
        getattr(
            trader,
            "starting_balance",
            0.0,
        )
    )

    if starting_balance <= 0:
        starting_balance = balance

    today = _utc_now().date()

    try:
        state = _load_risk_state()
    except Exception:
        state = None

    if not state:
        day_start_equity = balance
        high_water_equity = max(
            starting_balance,
            balance,
        )

    else:
        stored_date = state.get(
            "utc_date"
        )

        stored_day_start = _safe_float(
            state.get(
                "day_start_equity"
            )
        )

        stored_high_water = _safe_float(
            state.get(
                "high_water_equity"
            )
        )

        if stored_date != today:
            day_start_equity = balance
        else:
            day_start_equity = (
                stored_day_start
                if stored_day_start > 0
                else balance
            )

        high_water_equity = max(
            stored_high_water,
            starting_balance,
            balance,
        )

    try:
        _save_risk_state(
            utc_date=today,
            day_start_equity=
                day_start_equity,
            high_water_equity=
                high_water_equity,
            last_balance=
                balance,
        )
    except Exception:
        pass

    return {
        "balance": balance,
        "starting_balance": starting_balance,
        "day_start_equity": day_start_equity,
        "high_water_equity": high_water_equity,
        "utc_date": today.isoformat(),
    }


# ============================================================
# TRADE HISTORY
# ============================================================

def _history(
    trader,
) -> List[Dict]:

    try:
        history = trader.get_trade_history()
    except Exception:
        return []

    if not isinstance(
        history,
        list,
    ):
        return []

    def sort_key(
        trade,
    ):
        closed = _parse_datetime(
            trade.get(
                "closed_at"
            )
        )

        if closed is None:
            return datetime.min.replace(
                tzinfo=timezone.utc
            )

        return closed

    return sorted(
        history,
        key=sort_key,
        reverse=True,
    )


def get_daily_realized_pnl(
    trader,
) -> Dict:

    today = _utc_now().date()
    total = 0.0
    trades = 0

    for trade in _history(
        trader
    ):
        closed_at = _parse_datetime(
            trade.get(
                "closed_at"
            )
        )

        if (
            closed_at is None
            or closed_at.date() != today
        ):
            continue

        total += _safe_float(
            trade.get(
                "pnl"
            )
        )
        trades += 1

    return {
        "date": today.isoformat(),
        "realized_pnl": total,
        "closed_trades": trades,
    }


def get_consecutive_losses(
    trader,
) -> int:

    losses = 0

    for trade in _history(
        trader
    ):
        pnl = _safe_float(
            trade.get(
                "pnl"
            )
        )

        if pnl < 0:
            losses += 1
        else:
            break

    return losses


def get_last_closed_trade(
    trader,
) -> Optional[Dict]:

    history = _history(
        trader
    )

    if not history:
        return None

    return history[0]


# ============================================================
# GLOBAL COOLDOWN
# ============================================================

def get_global_cooldown(
    trader,
) -> Dict:

    latest = get_last_closed_trade(
        trader
    )

    if latest is None:
        return {
            "active": False,
            "seconds_remaining": 0,
        }

    closed_at = _parse_datetime(
        latest.get(
            "closed_at"
        )
    )

    if closed_at is None:
        return {
            "active": True,
            "seconds_remaining":
                GLOBAL_TRADE_COOLDOWN_SECONDS,
            "reason":
                "Latest trade has invalid closed_at",
        }

    elapsed = (
        _utc_now()
        - closed_at
    ).total_seconds()

    remaining = max(
        0,
        GLOBAL_TRADE_COOLDOWN_SECONDS
        - int(elapsed),
    )

    return {
        "active":
            remaining > 0,
        "seconds_remaining":
            remaining,
        "last_closed_at":
            closed_at.isoformat(),
        "last_symbol":
            latest.get("symbol"),
        "last_pnl":
            latest.get("pnl"),
    }


# ============================================================
# V5.1 LOSS-STREAK AUTO RECOVERY
# ============================================================

def get_loss_streak_recovery(
    trader,
) -> Dict:

    consecutive_losses = get_consecutive_losses(
        trader
    )

    result = {
        "active": False,
        "seconds_remaining": 0,
        "consecutive_losses":
            consecutive_losses,
        "threshold":
            MAX_CONSECUTIVE_LOSSES,
        "recovery_seconds":
            LOSS_STREAK_RECOVERY_SECONDS,
    }

    if (
        consecutive_losses
        < MAX_CONSECUTIVE_LOSSES
    ):
        return result

    latest_trade = get_last_closed_trade(
        trader
    )

    if not isinstance(
        latest_trade,
        dict,
    ):
        result.update(
            {
                "active": True,
                "seconds_remaining":
                    LOSS_STREAK_RECOVERY_SECONDS,
                "reason":
                    "Latest closed trade unavailable",
            }
        )
        return result

    latest_closed_at = _parse_datetime(
        latest_trade.get(
            "closed_at"
        )
    )

    if latest_closed_at is None:
        result.update(
            {
                "active": True,
                "seconds_remaining":
                    LOSS_STREAK_RECOVERY_SECONDS,
                "reason":
                    "Latest closed_at unavailable",
            }
        )
        return result

    elapsed = max(
        0,
        int(
            (
                _utc_now()
                - latest_closed_at
            ).total_seconds()
        ),
    )

    remaining = max(
        0,
        LOSS_STREAK_RECOVERY_SECONDS
        - elapsed,
    )

    result.update(
        {
            "active":
                remaining > 0,
            "seconds_remaining":
                remaining,
            "last_closed_at":
                latest_closed_at.isoformat(),
            "last_symbol":
                latest_trade.get(
                    "symbol"
                ),
            "last_pnl":
                latest_trade.get(
                    "pnl"
                ),
        }
    )

    return result


# ============================================================
# RISK MATH
# ============================================================

def calculate_contract_risk_amount(
    *,
    entry_price,
    stop_loss,
    quantity,
    contract_multiplier=1.0,
    point_value=1.0,
    fx_rate=1.0,
) -> float:

    entry_price = _safe_positive_float(
        entry_price
    )
    stop_loss = _safe_positive_float(
        stop_loss
    )
    quantity = _safe_positive_float(
        quantity
    )
    contract_multiplier = (
        _safe_positive_float(
            contract_multiplier,
            1.0,
        )
    )
    point_value = (
        _safe_positive_float(
            point_value,
            1.0,
        )
    )
    fx_rate = (
        _safe_positive_float(
            fx_rate,
            1.0,
        )
    )

    if (
        entry_price <= 0
        or stop_loss <= 0
        or quantity <= 0
    ):
        return 0.0

    risk_amount = (
        abs(
            entry_price - stop_loss
        )
        * quantity
        * contract_multiplier
        * point_value
        * fx_rate
    )

    if not math.isfinite(
        risk_amount
    ):
        return 0.0

    return max(
        0.0,
        risk_amount,
    )


def calculate_position_risk_amount(
    position: Dict,
) -> float:

    if not position:
        return 0.0

    return calculate_contract_risk_amount(
        entry_price=
            position.get(
                "entry_price"
            ),
        stop_loss=
            position.get(
                "stop_loss"
            ),
        quantity=
            position.get(
                "quantity"
            ),
        contract_multiplier=
            position.get(
                "contract_multiplier",
                1.0,
            ),
        point_value=
            position.get(
                "point_value",
                1.0,
            ),
        fx_rate=
            position.get(
                "fx_rate",
                1.0,
            ),
    )


def get_open_portfolio_risk(
    trader,
) -> Dict:

    try:
        snapshot = trader.get_portfolio_snapshot()
    except Exception:
        snapshot = {
            "open_positions": [],
        }

    positions = (
        snapshot.get(
            "open_positions",
            [],
        )
        or []
    )

    total_risk = 0.0
    details = []

    for position in positions:
        risk_amount = calculate_position_risk_amount(
            position
        )

        total_risk += risk_amount

        details.append(
            {
                "slot": position.get("slot"),
                "asset_class":
                    position.get("asset_class"),
                "symbol":
                    position.get("symbol"),
                "side":
                    position.get("side"),
                "risk_amount":
                    risk_amount,
            }
        )

    balance = _safe_float(
        trader.get_balance()
    )

    risk_pct = 0.0

    if balance > 0:
        risk_pct = (
            total_risk
            / balance
            * 100.0
        )

    return {
        "risk_amount": total_risk,
        "risk_pct": risk_pct,
        "positions": details,
    }


def calculate_proposed_trade_risk(
    entry_price,
    stop_loss,
    quantity,
    *,
    contract_multiplier=1.0,
    point_value=1.0,
    fx_rate=1.0,
) -> float:

    return calculate_contract_risk_amount(
        entry_price=
            entry_price,
        stop_loss=
            stop_loss,
        quantity=
            quantity,
        contract_multiplier=
            contract_multiplier,
        point_value=
            point_value,
        fx_rate=
            fx_rate,
    )


# ============================================================
# DRAWDOWN / DAILY LOSS
# ============================================================

def get_account_drawdown(
    trader,
) -> Dict:

    baseline = get_account_baseline(
        trader
    )

    high_water = baseline[
        "high_water_equity"
    ]
    balance = baseline[
        "balance"
    ]

    drawdown_amount = max(
        0.0,
        high_water - balance,
    )

    drawdown_pct = 0.0

    if high_water > 0:
        drawdown_pct = (
            drawdown_amount
            / high_water
            * 100.0
        )

    return {
        "starting_balance":
            baseline[
                "starting_balance"
            ],
        "high_water_equity":
            high_water,
        "balance":
            balance,
        "drawdown_amount":
            drawdown_amount,
        "drawdown_pct":
            drawdown_pct,
    }


def get_daily_loss_status(
    trader,
) -> Dict:

    realized = get_daily_realized_pnl(
        trader
    )

    baseline = get_account_baseline(
        trader
    )

    balance = baseline[
        "balance"
    ]
    day_start_equity = baseline[
        "day_start_equity"
    ]

    realized_loss_amount = max(
        0.0,
        -realized[
            "realized_pnl"
        ],
    )

    realized_loss_pct = 0.0

    if day_start_equity > 0:
        realized_loss_pct = (
            realized_loss_amount
            / day_start_equity
            * 100.0
        )

    equity_loss_amount = max(
        0.0,
        day_start_equity - balance,
    )

    equity_loss_pct = 0.0

    if day_start_equity > 0:
        equity_loss_pct = (
            equity_loss_amount
            / day_start_equity
            * 100.0
        )

    effective_loss_pct = max(
        realized_loss_pct,
        equity_loss_pct,
    )

    return {
        "date":
            baseline[
                "utc_date"
            ],
        "day_start_equity":
            day_start_equity,
        "current_balance":
            balance,
        "realized_pnl":
            realized[
                "realized_pnl"
            ],
        "closed_trades":
            realized[
                "closed_trades"
            ],
        "realized_loss_amount":
            realized_loss_amount,
        "realized_loss_pct":
            realized_loss_pct,
        "equity_loss_amount":
            equity_loss_amount,
        "equity_loss_pct":
            equity_loss_pct,
        "loss_pct":
            effective_loss_pct,
        "limit_pct":
            MAX_DAILY_LOSS_PCT,
        "blocked":
            effective_loss_pct
            >= MAX_DAILY_LOSS_PCT,
    }


# ============================================================
# STRUCTURAL STOP VALIDATION
# ============================================================

def validate_stop_structure(
    *,
    side,
    entry_price,
    stop_loss,
) -> Dict:

    normalized_side = _normalize_side(
        side
    )

    entry = _safe_positive_float(
        entry_price
    )
    stop = _safe_positive_float(
        stop_loss
    )

    if (
        entry <= 0
        or stop <= 0
    ):
        return {
            "valid": False,
            "reason":
                "Invalid entry or stop",
        }

    if normalized_side is None:
        return {
            "valid": True,
            "side": None,
            "reason":
                "Side not supplied; structural validation skipped",
        }

    if (
        normalized_side == "LONG"
        and stop >= entry
    ):
        return {
            "valid": False,
            "side": normalized_side,
            "reason":
                "LONG stop loss must be below entry",
        }

    if (
        normalized_side == "SHORT"
        and stop <= entry
    ):
        return {
            "valid": False,
            "side": normalized_side,
            "reason":
                "SHORT stop loss must be above entry",
        }

    return {
        "valid": True,
        "side": normalized_side,
        "reason": "Stop structure valid",
    }


# ============================================================
# DUPLICATE / POSITION LIMITS
# ============================================================

def symbol_already_open(
    trader,
    symbol,
) -> bool:

    symbol = _normalize_symbol(
        symbol
    )

    try:
        positions = trader.get_positions()
    except Exception:
        return False

    for position in positions:
        if (
            _normalize_symbol(
                position.get(
                    "symbol"
                )
            )
            == symbol
        ):
            return True

    return False


def _position_limits(
    trader,
    asset_class,
) -> Dict:

    asset_class = _normalize_asset_class(
        asset_class
    )

    try:
        snapshot = trader.get_portfolio_snapshot()
    except Exception:
        snapshot = {
            "open_positions": [],
        }

    positions = (
        snapshot.get(
            "open_positions",
            [],
        )
        or []
    )

    total_count = len(
        positions
    )

    crypto_count = sum(
        1
        for position in positions
        if _normalize_asset_class(
            position.get(
                "asset_class"
            )
        ) == "CRYPTO"
    )

    metals_count = sum(
        1
        for position in positions
        if _normalize_asset_class(
            position.get(
                "asset_class"
            )
        ) == "METAL"
    )

    blocked = False
    reason = None

    if (
        total_count
        >= MAX_TOTAL_OPEN_POSITIONS
    ):
        blocked = True
        reason = (
            "Maximum total open positions reached"
        )

    elif (
        asset_class == "CRYPTO"
        and crypto_count
        >= MAX_CRYPTO_POSITIONS
    ):
        blocked = True
        reason = (
            "Maximum Crypto positions reached"
        )

    elif (
        asset_class == "METAL"
        and metals_count
        >= MAX_METALS_POSITIONS
    ):
        blocked = True
        reason = (
            "Maximum Metals positions reached"
        )

    return {
        "blocked": blocked,
        "reason": reason,
        "total": total_count,
        "crypto": crypto_count,
        "metals": metals_count,
    }


# ============================================================
# AUDIT
# ============================================================

def _audit_decision(
    result: Dict,
):

    if not DATABASE_URL:
        return

    try:
        ensure_risk_governor_tables()

        with _connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO portfolio_risk_decisions (
                        approved,
                        status,
                        reason,
                        asset_class,
                        symbol,
                        side,
                        entry_price,
                        stop_loss,
                        quantity,
                        proposed_risk_amount,
                        proposed_risk_pct,
                        projected_portfolio_risk_pct,
                        balance
                    )
                    VALUES (
                        %s,%s,%s,%s,%s,%s,%s,
                        %s,%s,%s,%s,%s,%s
                    )
                    """,
                    (
                        bool(
                            result.get(
                                "approved",
                                False,
                            )
                        ),
                        result.get("status"),
                        result.get("reason"),
                        result.get("asset_class"),
                        result.get("symbol"),
                        result.get("side"),
                        result.get("entry_price"),
                        result.get("stop_loss"),
                        result.get("quantity"),
                        result.get(
                            "proposed_risk_amount"
                        ),
                        result.get(
                            "proposed_risk_pct"
                        ),
                        result.get(
                            "projected_portfolio_risk_pct"
                        ),
                        result.get("balance"),
                    ),
                )

            conn.commit()

    except Exception:
        pass


def _decision(
    *,
    approved: bool,
    status: str,
    reason: str,
    **extra,
) -> Dict:

    result = {
        "approved": bool(approved),
        "status": str(status),
        "reason": str(reason),
        "engine": ENGINE_VERSION,
        "paper_only": True,
        "real_execution": False,
        "decided_at":
            _utc_now().isoformat(),
    }

    result.update(
        extra
    )

    _audit_decision(
        result
    )

    return result


# ============================================================
# MASTER ENTRY AUTHORIZATION
# ============================================================

def authorize_trade(
    trader,
    *,
    asset_class: str,
    symbol: str,
    entry_price: float,
    stop_loss: float,
    quantity: float,
    risk_pct: Optional[float] = None,
    side: Optional[str] = None,
    contract_multiplier: float = 1.0,
    point_value: float = 1.0,
    fx_rate: float = 1.0,
) -> Dict:

    if (
        not PAPER_ONLY
        or REAL_EXECUTION_ENABLED
    ):
        return _decision(
            approved=False,
            status="HARD_LOCK",
            reason=(
                "Real execution is disabled by "
                "Portfolio Risk Governor"
            ),
        )

    asset_class = _normalize_asset_class(
        asset_class
    )
    symbol = _normalize_symbol(
        symbol
    )
    normalized_side = _normalize_side(
        side
    )
    slot = _asset_slot(
        asset_class
    )

    if slot is None:
        return _decision(
            approved=False,
            status=
                "UNSUPPORTED_ASSET_CLASS",
            reason=(
                "Unsupported active asset class: "
                f"{asset_class}"
            ),
            asset_class=
                asset_class,
            symbol=
                symbol,
        )

    entry_price = _safe_positive_float(
        entry_price
    )
    stop_loss = _safe_positive_float(
        stop_loss
    )
    quantity = _safe_positive_float(
        quantity
    )
    contract_multiplier = (
        _safe_positive_float(
            contract_multiplier,
            1.0,
        )
    )
    point_value = (
        _safe_positive_float(
            point_value,
            1.0,
        )
    )
    fx_rate = (
        _safe_positive_float(
            fx_rate,
            1.0,
        )
    )

    if (
        entry_price <= 0
        or stop_loss <= 0
        or quantity <= 0
    ):
        return _decision(
            approved=False,
            status="INVALID_TRADE",
            reason=
                "Invalid entry/stop/quantity",
            asset_class=
                asset_class,
            symbol=
                symbol,
            side=
                normalized_side,
        )

    stop_validation = validate_stop_structure(
        side=
            normalized_side,
        entry_price=
            entry_price,
        stop_loss=
            stop_loss,
    )

    if not stop_validation[
        "valid"
    ]:
        return _decision(
            approved=False,
            status=
                "INVALID_STOP_STRUCTURE",
            reason=
                stop_validation[
                    "reason"
                ],
            asset_class=
                asset_class,
            symbol=
                symbol,
            side=
                normalized_side,
            entry_price=
                entry_price,
            stop_loss=
                stop_loss,
            quantity=
                quantity,
        )

    if not trader.slot_available(
        slot
    ):
        return _decision(
            approved=False,
            status="SLOT_OCCUPIED",
            reason=(
                f"{slot} already has "
                "an open position"
            ),
            asset_class=
                asset_class,
            symbol=
                symbol,
            side=
                normalized_side,
        )

    if symbol_already_open(
        trader,
        symbol,
    ):
        return _decision(
            approved=False,
            status=
                "DUPLICATE_SYMBOL",
            reason=(
                f"{symbol} is already open"
            ),
            asset_class=
                asset_class,
            symbol=
                symbol,
            side=
                normalized_side,
        )

    position_limits = _position_limits(
        trader,
        asset_class,
    )

    if position_limits[
        "blocked"
    ]:
        return _decision(
            approved=False,
            status=
                "POSITION_LIMIT",
            reason=
                position_limits[
                    "reason"
                ],
            asset_class=
                asset_class,
            symbol=
                symbol,
            side=
                normalized_side,
            position_limits=
                position_limits,
        )

    baseline = get_account_baseline(
        trader
    )
    balance = baseline[
        "balance"
    ]

    if balance <= 0:
        return _decision(
            approved=False,
            status=
                "INVALID_BALANCE",
            reason=
                "Invalid paper account balance",
            asset_class=
                asset_class,
            symbol=
                symbol,
            side=
                normalized_side,
        )

    daily = get_daily_loss_status(
        trader
    )

    if daily[
        "blocked"
    ]:
        return _decision(
            approved=False,
            status=
                "DAILY_LOSS_LOCK",
            reason=
                "Maximum daily loss limit reached",
            asset_class=
                asset_class,
            symbol=
                symbol,
            side=
                normalized_side,
            daily_loss=
                daily,
            balance=
                balance,
        )

    drawdown = get_account_drawdown(
        trader
    )

    if (
        drawdown[
            "drawdown_pct"
        ]
        >= MAX_TOTAL_DRAWDOWN_PCT
    ):
        return _decision(
            approved=False,
            status=
                "DRAWDOWN_LOCK",
            reason=
                "Maximum account drawdown reached",
            asset_class=
                asset_class,
            symbol=
                symbol,
            side=
                normalized_side,
            drawdown=
                drawdown,
            balance=
                balance,
        )

    # --------------------------------------------------------
    # V5.1 LOSS-STREAK RECOVERY
    # --------------------------------------------------------

    consecutive_losses = get_consecutive_losses(
        trader
    )

    loss_streak_recovery = (
        get_loss_streak_recovery(
            trader
        )
    )

    if loss_streak_recovery[
        "active"
    ]:
        return _decision(
            approved=False,
            status=
                "LOSS_STREAK_RECOVERY_WAIT",
            reason=
                "Loss-streak recovery cooldown active",
            asset_class=
                asset_class,
            symbol=
                symbol,
            side=
                normalized_side,
            consecutive_losses=
                consecutive_losses,
            loss_streak_recovery=
                loss_streak_recovery,
            balance=
                balance,
        )

    if (
        consecutive_losses
        >= MAX_CONSECUTIVE_LOSSES
    ):
        print(
            "[PORTFOLIO RISK] "
            "Loss-streak recovery completed | "
            f"losses={consecutive_losses} | "
            f"symbol={symbol} | "
            "next qualifying PAPER trade allowed.",
            flush=True,
        )

    # --------------------------------------------------------
    # GLOBAL COOLDOWN
    # --------------------------------------------------------

    cooldown = get_global_cooldown(
        trader
    )

    if cooldown[
        "active"
    ]:
        return _decision(
            approved=False,
            status=
                "GLOBAL_COOLDOWN",
            reason=
                "Portfolio cooldown is active",
            asset_class=
                asset_class,
            symbol=
                symbol,
            side=
                normalized_side,
            cooldown=
                cooldown,
            balance=
                balance,
        )

    # --------------------------------------------------------
    # PROPOSED RISK
    # --------------------------------------------------------

    proposed_risk_amount = (
        calculate_proposed_trade_risk(
            entry_price,
            stop_loss,
            quantity,
            contract_multiplier=
                contract_multiplier,
            point_value=
                point_value,
            fx_rate=
                fx_rate,
        )
    )

    if proposed_risk_amount <= 0:
        return _decision(
            approved=False,
            status=
                "INVALID_RISK",
            reason=
                "Calculated proposed risk is invalid",
            asset_class=
                asset_class,
            symbol=
                symbol,
            side=
                normalized_side,
            balance=
                balance,
        )

    proposed_risk_pct = (
        proposed_risk_amount
        / balance
        * 100.0
    )

    asset_risk_limit = (
        ASSET_RISK_LIMITS.get(
            asset_class
        )
    )

    if asset_risk_limit is None:
        return _decision(
            approved=False,
            status=
                "NO_ASSET_RISK_LIMIT",
            reason=(
                "No configured risk limit "
                f"for {asset_class}"
            ),
            asset_class=
                asset_class,
            symbol=
                symbol,
            side=
                normalized_side,
        )

    if _risk_pct_exceeds_limit(
        proposed_risk_pct,
        asset_risk_limit,
    ):
        return _decision(
            approved=False,
            status=
                "TRADE_RISK_TOO_HIGH",
            reason=(
                f"{asset_class} proposed risk "
                f"{proposed_risk_pct:.2f}% "
                f"exceeds "
                f"{asset_risk_limit:.2f}%"
            ),
            asset_class=
                asset_class,
            symbol=
                symbol,
            side=
                normalized_side,
            entry_price=
                entry_price,
            stop_loss=
                stop_loss,
            quantity=
                quantity,
            proposed_risk_amount=
                proposed_risk_amount,
            proposed_risk_pct=
                proposed_risk_pct,
            asset_risk_limit=
                asset_risk_limit,
            balance=
                balance,
        )

    if risk_pct is not None:
        requested_risk_pct = _safe_float(
            risk_pct
        )

        if requested_risk_pct < 0:
            return _decision(
                approved=False,
                status=
                    "INVALID_REQUESTED_RISK",
                reason=
                    "Requested risk percentage is invalid",
                asset_class=
                    asset_class,
                symbol=
                    symbol,
                side=
                    normalized_side,
            )

        if _risk_pct_exceeds_limit(
            requested_risk_pct,
            asset_risk_limit,
        ):
            return _decision(
                approved=False,
                status=
                    "REQUESTED_RISK_TOO_HIGH",
                reason=
                    "Requested risk percentage exceeds asset risk limit",
                asset_class=
                    asset_class,
                symbol=
                    symbol,
                side=
                    normalized_side,
                proposed_risk_pct=
                    proposed_risk_pct,
                requested_risk_pct=
                    requested_risk_pct,
                asset_risk_limit=
                    asset_risk_limit,
                balance=
                    balance,
            )

    portfolio_risk = get_open_portfolio_risk(
        trader
    )

    projected_risk_amount = (
        portfolio_risk[
            "risk_amount"
        ]
        + proposed_risk_amount
    )

    projected_risk_pct = (
        projected_risk_amount
        / balance
        * 100.0
    )

    if _risk_pct_exceeds_limit(
        projected_risk_pct,
        MAX_PORTFOLIO_RISK_PCT,
    ):
        return _decision(
            approved=False,
            status=
                "PORTFOLIO_RISK_LIMIT",
            reason=
                "Projected portfolio risk exceeds maximum",
            asset_class=
                asset_class,
            symbol=
                symbol,
            side=
                normalized_side,
            entry_price=
                entry_price,
            stop_loss=
                stop_loss,
            quantity=
                quantity,
            proposed_risk_amount=
                proposed_risk_amount,
            proposed_risk_pct=
                proposed_risk_pct,
            current_portfolio_risk_pct=
                portfolio_risk[
                    "risk_pct"
                ],
            projected_portfolio_risk_pct=
                projected_risk_pct,
            limit_pct=
                MAX_PORTFOLIO_RISK_PCT,
            balance=
                balance,
        )

    return _decision(
        approved=True,
        status="APPROVED",
        reason=
            "Portfolio Risk Governor approved trade",
        asset_class=
            asset_class,
        slot=
            slot,
        symbol=
            symbol,
        side=
            normalized_side,
        entry_price=
            entry_price,
        stop_loss=
            stop_loss,
        quantity=
            quantity,
        contract_multiplier=
            contract_multiplier,
        point_value=
            point_value,
        fx_rate=
            fx_rate,
        balance=
            balance,
        proposed_risk_amount=
            proposed_risk_amount,
        proposed_risk_pct=
            proposed_risk_pct,
        current_portfolio_risk_pct=
            portfolio_risk[
                "risk_pct"
            ],
        projected_portfolio_risk_pct=
            projected_risk_pct,
        daily_loss_pct=
            daily[
                "loss_pct"
            ],
        drawdown_pct=
            drawdown[
                "drawdown_pct"
            ],
        high_water_equity=
            drawdown[
                "high_water_equity"
            ],
        day_start_equity=
            daily[
                "day_start_equity"
            ],
        consecutive_losses=
            consecutive_losses,
        loss_streak_recovery=
            loss_streak_recovery,
        cooldown=
            cooldown,
        risk_model=
            "V5.1_CONTRACT_AWARE_AUTO_RECOVERY",
    )


# ============================================================
# SNAPSHOT
# ============================================================

def get_portfolio_risk_snapshot(
    trader,
) -> Dict:

    baseline = get_account_baseline(
        trader
    )
    daily = get_daily_loss_status(
        trader
    )
    drawdown = get_account_drawdown(
        trader
    )
    open_risk = get_open_portfolio_risk(
        trader
    )
    cooldown = get_global_cooldown(
        trader
    )
    consecutive_losses = get_consecutive_losses(
        trader
    )
    loss_streak_recovery = (
        get_loss_streak_recovery(
            trader
        )
    )

    try:
        portfolio = trader.get_portfolio_snapshot()
    except Exception:
        portfolio = {}

    locked_reasons = []

    if daily[
        "blocked"
    ]:
        locked_reasons.append(
            "DAILY_LOSS"
        )

    if (
        drawdown[
            "drawdown_pct"
        ]
        >= MAX_TOTAL_DRAWDOWN_PCT
    ):
        locked_reasons.append(
            "TOTAL_DRAWDOWN"
        )

    if loss_streak_recovery[
        "active"
    ]:
        locked_reasons.append(
            "LOSS_STREAK_RECOVERY"
        )

    if cooldown[
        "active"
    ]:
        locked_reasons.append(
            "GLOBAL_COOLDOWN"
        )

    if (
        open_risk[
            "risk_pct"
        ]
        >= MAX_PORTFOLIO_RISK_PCT
    ):
        locked_reasons.append(
            "PORTFOLIO_RISK"
        )

    return {
        "engine": ENGINE_VERSION,
        "paper_only": True,
        "real_execution": False,
        "entry_locked":
            bool(
                locked_reasons
            ),
        "locked_reasons":
            locked_reasons,
        "balance":
            baseline[
                "balance"
            ],
        "starting_balance":
            baseline[
                "starting_balance"
            ],
        "day_start_equity":
            baseline[
                "day_start_equity"
            ],
        "high_water_equity":
            baseline[
                "high_water_equity"
            ],
        "daily": daily,
        "drawdown": drawdown,
        "open_risk": open_risk,
        "consecutive_losses":
            consecutive_losses,
        "loss_streak_recovery":
            loss_streak_recovery,
        "cooldown": cooldown,
        "portfolio": portfolio,
        "risk_model": {
            "version": "V5.1",
            "peak_equity_drawdown": True,
            "persistent_day_start":
                bool(
                    DATABASE_URL
                ),
            "persistent_high_water":
                bool(
                    DATABASE_URL
                ),
            "contract_aware": True,
            "side_aware": True,
            "decision_audit":
                bool(
                    DATABASE_URL
                ),
            "loss_streak_auto_recovery":
                True,
        },
        "limits": {
            "max_daily_loss_pct":
                MAX_DAILY_LOSS_PCT,
            "max_total_drawdown_pct":
                MAX_TOTAL_DRAWDOWN_PCT,
            "max_portfolio_risk_pct":
                MAX_PORTFOLIO_RISK_PCT,
            "max_total_positions":
                MAX_TOTAL_OPEN_POSITIONS,
            "max_crypto_positions":
                MAX_CRYPTO_POSITIONS,
            "max_metals_positions":
                MAX_METALS_POSITIONS,
            "max_consecutive_losses":
                MAX_CONSECUTIVE_LOSSES,
            "loss_streak_recovery_seconds":
                LOSS_STREAK_RECOVERY_SECONDS,
            "global_cooldown_seconds":
                GLOBAL_TRADE_COOLDOWN_SECONDS,
            "max_crypto_risk_pct":
                MAX_CRYPTO_RISK_PCT,
            "max_metals_risk_pct":
                MAX_METALS_RISK_PCT,
            "max_stock_risk_pct":
                MAX_STOCK_RISK_PCT,
            "max_fx_risk_pct":
                MAX_FX_RISK_PCT,
            "max_index_risk_pct":
                MAX_INDEX_RISK_PCT,
            "max_futures_risk_pct":
                MAX_FUTURES_RISK_PCT,
        },
    }


# ============================================================
# HEALTH
# ============================================================

def portfolio_risk_governor_health(
    trader=None,
) -> Dict:

    result = {
        "ok": True,
        "engine": ENGINE_VERSION,
        "paper_only": True,
        "real_execution_locked": True,
        "database_state_persistence":
            bool(
                DATABASE_URL
            ),
        "decision_audit":
            bool(
                DATABASE_URL
            ),
        "high_water_drawdown": True,
        "daily_equity_baseline": True,
        "finite_number_validation": True,
        "side_aware_stop_validation": True,
        "contract_aware_risk": True,
        "loss_streak_auto_recovery": True,
        "loss_streak_recovery_seconds":
            LOSS_STREAK_RECOVERY_SECONDS,
        "supported_active_asset_classes": [
            "CRYPTO",
            "METAL",
        ],
        "future_risk_models_ready": [
            "STOCK",
            "FX",
            "INDEX",
            "FUTURES",
        ],
        "future_asset_ready": True,
    }

    if DATABASE_URL:
        try:
            ensure_risk_governor_tables()
            result[
                "database"
            ] = "ONLINE"
        except Exception as error:
            result[
                "ok"
            ] = False
            result[
                "database"
            ] = "ERROR"
            result[
                "reason"
            ] = str(error)
    else:
        result[
            "database"
        ] = "NOT_CONFIGURED"

    if trader is not None:
        try:
            result[
                "snapshot"
            ] = get_portfolio_risk_snapshot(
                trader
            )
        except Exception as error:
            result[
                "ok"
            ] = False
            result[
                "reason"
            ] = str(error)

    return result

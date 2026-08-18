"""
portfolio_risk_governor.py

PRO AI QUANT TERMINAL V4.0
UNIFIED MULTI-ASSET PORTFOLIO RISK GOVERNOR

Purpose
-------
Central account-level risk authority for:
    - CRYPTO
    - METALS
    - Future STOCKS / INDICES / FX modules

Architecture
------------
Scanner / Strategy
        ↓
Trade Engine
        ↓
Portfolio Risk Governor
        ↓
PaperTrader

The governor DOES NOT place trades.
It only answers:
    APPROVED
    or
    BLOCKED

Safety goals
------------
- PAPER ONLY
- Real execution hard locked
- Max total positions
- Slot protection
- Daily realized loss protection
- Total account drawdown protection
- Portfolio open-risk cap
- Per-trade risk cap
- Consecutive-loss circuit breaker
- Trade cooldown
- Duplicate symbol protection
- Invalid TP/SL protection
- Persistent state derived from PostgreSQL-backed PaperTrader
- Future asset classes supported without core redesign
"""

from __future__ import annotations

import os
from datetime import datetime, timezone
from typing import Dict, Optional

from paper_trader import (
    CRYPTO_SLOT,
    METALS_SLOT,
)


# ============================================================
# HARD SAFETY MODE
# ============================================================

PAPER_ONLY = True
REAL_EXECUTION_ENABLED = False


# ============================================================
# CONFIG
# ============================================================

MAX_DAILY_LOSS_PCT = float(
    os.environ.get(
        "MAX_DAILY_LOSS_PCT",
        "5.0",
    )
)

MAX_TOTAL_DRAWDOWN_PCT = float(
    os.environ.get(
        "MAX_TOTAL_DRAWDOWN_PCT",
        "10.0",
    )
)

MAX_PORTFOLIO_RISK_PCT = float(
    os.environ.get(
        "MAX_PORTFOLIO_RISK_PCT",
        "3.0",
    )
)

MAX_TOTAL_OPEN_POSITIONS = int(
    os.environ.get(
        "MAX_TOTAL_OPEN_POSITIONS",
        "2",
    )
)

MAX_CRYPTO_POSITIONS = int(
    os.environ.get(
        "MAX_CRYPTO_POSITIONS",
        "1",
    )
)

MAX_METALS_POSITIONS = int(
    os.environ.get(
        "MAX_METALS_POSITIONS",
        "1",
    )
)

MAX_CONSECUTIVE_LOSSES = int(
    os.environ.get(
        "MAX_CONSECUTIVE_LOSSES",
        "3",
    )
)

GLOBAL_TRADE_COOLDOWN_SECONDS = int(
    os.environ.get(
        "GLOBAL_TRADE_COOLDOWN_SECONDS",
        "300",
    )
)

MAX_CRYPTO_RISK_PCT = float(
    os.environ.get(
        "MAX_CRYPTO_RISK_PCT",
        "1.0",
    )
)

MAX_METALS_RISK_PCT = float(
    os.environ.get(
        "MAX_METALS_RISK_PCT",
        "1.0",
    )
)


# ============================================================
# SUPPORTED ASSET CLASSES
# ============================================================

ASSET_SLOT_MAP = {
    "CRYPTO":
        CRYPTO_SLOT,

    "METAL":
        METALS_SLOT,

    "METALS":
        METALS_SLOT,
}


# ============================================================
# HELPERS
# ============================================================

def _safe_float(
    value,
    default=0.0,
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
                str(
                    value
                ).replace(
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


def _normalize_symbol(
    symbol,
):

    return (
        str(
            symbol
        )
        .upper()
        .replace("/", "")
        .replace("-", "")
        .replace(" ", "")
        .strip()
    )


def _normalize_asset_class(
    asset_class,
):

    value = (
        str(
            asset_class
        )
        .upper()
        .strip()
    )

    if value == "METALS":
        return "METAL"

    return value


def _asset_slot(
    asset_class,
):

    normalized = _normalize_asset_class(
        asset_class
    )

    return ASSET_SLOT_MAP.get(
        normalized
    )


# ============================================================
# ACCOUNT BASELINE
# ============================================================

def get_account_baseline(
    trader,
) -> Dict:

    """
    Uses persistent PaperTrader account state.

    Current balance is available through trader.get_balance().
    Starting balance is retained by PaperTrader itself.
    """

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

    return {
        "balance":
            balance,

        "starting_balance":
            starting_balance,
    }


# ============================================================
# TRADE HISTORY
# ============================================================

def _history(
    trader,
):

    try:

        history = (
            trader.get_trade_history()
        )

    except Exception:

        return []

    if not isinstance(
        history,
        list,
    ):

        return []

    return history


# ============================================================
# DAILY REALIZED PNL
# ============================================================

def get_daily_realized_pnl(
    trader,
) -> Dict:

    today = (
        _utc_now()
        .date()
    )

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
            or closed_at.date()
            != today
        ):

            continue

        total += _safe_float(
            trade.get(
                "pnl"
            )
        )

        trades += 1

    return {
        "date":
            today.isoformat(),

        "realized_pnl":
            total,

        "closed_trades":
            trades,
    }


# ============================================================
# CONSECUTIVE LOSSES
# ============================================================

def get_consecutive_losses(
    trader,
) -> int:

    losses = 0

    history = _history(
        trader
    )

    # get_trade_history() is newest first.
    for trade in history:

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


# ============================================================
# LAST CLOSED TRADE
# ============================================================

def get_last_closed_trade(
    trader,
) -> Optional[Dict]:

    history = _history(
        trader
    )

    if not history:

        return None

    return history[
        0
    ]


# ============================================================
# GLOBAL COOLDOWN
# ============================================================

def get_global_cooldown(
    trader,
) -> Dict:

    latest = (
        get_last_closed_trade(
            trader
        )
    )

    if latest is None:

        return {
            "active":
                False,

            "seconds_remaining":
                0,
        }

    closed_at = _parse_datetime(
        latest.get(
            "closed_at"
        )
    )

    if closed_at is None:

        return {
            "active":
                True,

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
        - int(
            elapsed
        ),
    )

    return {
        "active":
            remaining > 0,

        "seconds_remaining":
            remaining,

        "last_closed_at":
            closed_at.isoformat(),

        "last_symbol":
            latest.get(
                "symbol"
            ),

        "last_pnl":
            latest.get(
                "pnl"
            ),
    }


# ============================================================
# POSITION RISK
# ============================================================

def calculate_position_risk_amount(
    position: Dict,
) -> float:

    if not position:

        return 0.0

    entry = _safe_float(
        position.get(
            "entry_price"
        )
    )

    stop = _safe_float(
        position.get(
            "stop_loss"
        )
    )

    quantity = _safe_float(
        position.get(
            "quantity"
        )
    )

    if (
        entry <= 0
        or stop <= 0
        or quantity <= 0
    ):

        return 0.0

    distance = abs(
        entry
        - stop
    )

    return (
        distance
        * quantity
    )


# ============================================================
# OPEN PORTFOLIO RISK
# ============================================================

def get_open_portfolio_risk(
    trader,
) -> Dict:

    try:

        snapshot = (
            trader.get_portfolio_snapshot()
        )

    except Exception:

        snapshot = {
            "open_positions":
                [],
        }

    positions = (
        snapshot.get(
            "open_positions",
            []
        )
        or []
    )

    total_risk = 0.0
    details = []

    for position in positions:

        risk_amount = (
            calculate_position_risk_amount(
                position
            )
        )

        total_risk += (
            risk_amount
        )

        details.append(
            {
                "slot":
                    position.get(
                        "slot"
                    ),

                "asset_class":
                    position.get(
                        "asset_class"
                    ),

                "symbol":
                    position.get(
                        "symbol"
                    ),

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
            * 100
        )

    return {
        "risk_amount":
            total_risk,

        "risk_pct":
            risk_pct,

        "positions":
            details,
    }


# ============================================================
# DRAWDOWN
# ============================================================

def get_account_drawdown(
    trader,
) -> Dict:

    baseline = (
        get_account_baseline(
            trader
        )
    )

    starting = baseline[
        "starting_balance"
    ]

    balance = baseline[
        "balance"
    ]

    drawdown_amount = max(
        0.0,
        starting
        - balance,
    )

    drawdown_pct = 0.0

    if starting > 0:

        drawdown_pct = (
            drawdown_amount
            / starting
            * 100
        )

    return {
        "starting_balance":
            starting,

        "balance":
            balance,

        "drawdown_amount":
            drawdown_amount,

        "drawdown_pct":
            drawdown_pct,
    }


# ============================================================
# DAILY LOSS %
# ============================================================

def get_daily_loss_status(
    trader,
) -> Dict:

    pnl_info = (
        get_daily_realized_pnl(
            trader
        )
    )

    balance_info = (
        get_account_baseline(
            trader
        )
    )

    starting_balance = (
        balance_info[
            "starting_balance"
        ]
    )

    realized_pnl = (
        pnl_info[
            "realized_pnl"
        ]
    )

    loss_amount = max(
        0.0,
        -realized_pnl,
    )

    loss_pct = 0.0

    if starting_balance > 0:

        loss_pct = (
            loss_amount
            / starting_balance
            * 100
        )

    return {
        "realized_pnl":
            realized_pnl,

        "loss_amount":
            loss_amount,

        "loss_pct":
            loss_pct,

        "limit_pct":
            MAX_DAILY_LOSS_PCT,

        "blocked":
            loss_pct
            >= MAX_DAILY_LOSS_PCT,
    }


# ============================================================
# PROPOSED TRADE RISK
# ============================================================

def calculate_proposed_trade_risk(
    entry_price,
    stop_loss,
    quantity,
) -> float:

    entry_price = _safe_float(
        entry_price
    )

    stop_loss = _safe_float(
        stop_loss
    )

    quantity = _safe_float(
        quantity
    )

    if (
        entry_price <= 0
        or stop_loss <= 0
        or quantity <= 0
    ):

        return 0.0

    return (
        abs(
            entry_price
            - stop_loss
        )
        * quantity
    )


# ============================================================
# DUPLICATE SYMBOL CHECK
# ============================================================

def symbol_already_open(
    trader,
    symbol,
) -> bool:

    symbol = _normalize_symbol(
        symbol
    )

    try:

        positions = (
            trader.get_positions()
        )

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


# ============================================================
# POSITION LIMIT CHECK
# ============================================================

def _position_limits(
    trader,
    asset_class,
) -> Dict:

    asset_class = (
        _normalize_asset_class(
            asset_class
        )
    )

    try:

        snapshot = (
            trader.get_portfolio_snapshot()
        )

    except Exception:

        snapshot = {
            "open_positions":
                [],
            "open_position_count":
                0,
        }

    positions = (
        snapshot.get(
            "open_positions",
            []
        )
        or []
    )

    total_count = len(
        positions
    )

    crypto_count = sum(
        1
        for position in positions
        if (
            _normalize_asset_class(
                position.get(
                    "asset_class"
                )
            )
            == "CRYPTO"
        )
    )

    metals_count = sum(
        1
        for position in positions
        if (
            _normalize_asset_class(
                position.get(
                    "asset_class"
                )
            )
            == "METAL"
        )
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
        "blocked":
            blocked,

        "reason":
            reason,

        "total":
            total_count,

        "crypto":
            crypto_count,

        "metals":
            metals_count,
    }


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
) -> Dict:

    """
    MASTER SAFETY GATE.

    Every future trade engine should call this BEFORE
    trader.open_trade().
    """

    # --------------------------------------------------------
    # ABSOLUTE EXECUTION LOCK
    # --------------------------------------------------------

    if (
        not PAPER_ONLY
        or REAL_EXECUTION_ENABLED
    ):

        return {
            "approved":
                False,

            "status":
                "HARD_LOCK",

            "reason":
                "Real execution is disabled by Portfolio Risk Governor",
        }

    asset_class = (
        _normalize_asset_class(
            asset_class
        )
    )

    symbol = (
        _normalize_symbol(
            symbol
        )
    )

    slot = (
        _asset_slot(
            asset_class
        )
    )

    if slot is None:

        return {
            "approved":
                False,

            "status":
                "UNSUPPORTED_ASSET_CLASS",

            "reason":
                (
                    f"Unsupported asset class: "
                    f"{asset_class}"
                ),
        }

    # --------------------------------------------------------
    # VALID TRADE PARAMETERS
    # --------------------------------------------------------

    entry_price = _safe_float(
        entry_price
    )

    stop_loss = _safe_float(
        stop_loss
    )

    quantity = _safe_float(
        quantity
    )

    if (
        entry_price <= 0
        or stop_loss <= 0
        or quantity <= 0
    ):

        return {
            "approved":
                False,

            "status":
                "INVALID_TRADE",

            "reason":
                "Invalid entry/stop/quantity",
        }

    # --------------------------------------------------------
    # SLOT AVAILABILITY
    # --------------------------------------------------------

    if not trader.slot_available(
        slot
    ):

        return {
            "approved":
                False,

            "status":
                "SLOT_OCCUPIED",

            "reason":
                f"{slot} already has an open position",
        }

    # --------------------------------------------------------
    # DUPLICATE SYMBOL
    # --------------------------------------------------------

    if symbol_already_open(
        trader,
        symbol,
    ):

        return {
            "approved":
                False,

            "status":
                "DUPLICATE_SYMBOL",

            "reason":
                f"{symbol} is already open",
        }

    # --------------------------------------------------------
    # POSITION LIMITS
    # --------------------------------------------------------

    position_limits = (
        _position_limits(
            trader,
            asset_class,
        )
    )

    if position_limits[
        "blocked"
    ]:

        return {
            "approved":
                False,

            "status":
                "POSITION_LIMIT",

            "reason":
                position_limits[
                    "reason"
                ],

            "position_limits":
                position_limits,
        }

    # --------------------------------------------------------
    # DAILY LOSS CIRCUIT BREAKER
    # --------------------------------------------------------

    daily = (
        get_daily_loss_status(
            trader
        )
    )

    if daily[
        "blocked"
    ]:

        return {
            "approved":
                False,

            "status":
                "DAILY_LOSS_LOCK",

            "reason":
                (
                    "Maximum daily loss limit reached"
                ),

            "daily_loss":
                daily,
        }

    # --------------------------------------------------------
    # TOTAL DRAWDOWN CIRCUIT BREAKER
    # --------------------------------------------------------

    drawdown = (
        get_account_drawdown(
            trader
        )
    )

    if (
        drawdown[
            "drawdown_pct"
        ]
        >= MAX_TOTAL_DRAWDOWN_PCT
    ):

        return {
            "approved":
                False,

            "status":
                "DRAWDOWN_LOCK",

            "reason":
                "Maximum account drawdown reached",

            "drawdown":
                drawdown,
        }

    # --------------------------------------------------------
    # CONSECUTIVE LOSS CIRCUIT BREAKER
    # --------------------------------------------------------

    consecutive_losses = (
        get_consecutive_losses(
            trader
        )
    )

    if (
        consecutive_losses
        >= MAX_CONSECUTIVE_LOSSES
    ):

        return {
            "approved":
                False,

            "status":
                "LOSS_STREAK_LOCK",

            "reason":
                (
                    "Maximum consecutive losses reached"
                ),

            "consecutive_losses":
                consecutive_losses,
        }

    # --------------------------------------------------------
    # GLOBAL COOLDOWN
    # --------------------------------------------------------

    cooldown = (
        get_global_cooldown(
            trader
        )
    )

    if cooldown[
        "active"
    ]:

        return {
            "approved":
                False,

            "status":
                "GLOBAL_COOLDOWN",

            "reason":
                "Portfolio cooldown is active",

            "cooldown":
                cooldown,
        }

    # --------------------------------------------------------
    # PROPOSED TRADE RISK
    # --------------------------------------------------------

    proposed_risk_amount = (
        calculate_proposed_trade_risk(
            entry_price,
            stop_loss,
            quantity,
        )
    )

    balance = _safe_float(
        trader.get_balance()
    )

    if balance <= 0:

        return {
            "approved":
                False,

            "status":
                "INVALID_BALANCE",

            "reason":
                "Invalid paper account balance",
        }

    proposed_risk_pct = (
        proposed_risk_amount
        / balance
        * 100
    )

    # --------------------------------------------------------
    # PER-ASSET TRADE RISK CAP
    # --------------------------------------------------------

    asset_risk_limit = (
        MAX_METALS_RISK_PCT
        if asset_class == "METAL"
        else MAX_CRYPTO_RISK_PCT
    )

    if (
        proposed_risk_pct
        > asset_risk_limit
    ):

        return {
            "approved":
                False,

            "status":
                "TRADE_RISK_TOO_HIGH",

            "reason":
                (
                    f"{asset_class} proposed risk "
                    f"{proposed_risk_pct:.2f}% "
                    f"exceeds {asset_risk_limit:.2f}%"
                ),

            "proposed_risk_pct":
                proposed_risk_pct,

            "asset_risk_limit":
                asset_risk_limit,
        }

    # --------------------------------------------------------
    # OPTIONAL CALLER RISK CONSISTENCY
    # --------------------------------------------------------

    if risk_pct is not None:

        requested_risk_pct = (
            _safe_float(
                risk_pct
            )
        )

        if (
            requested_risk_pct
            > asset_risk_limit
        ):

            return {
                "approved":
                    False,

                "status":
                    "REQUESTED_RISK_TOO_HIGH",

                "reason":
                    (
                        "Requested risk percentage "
                        "exceeds asset risk limit"
                    ),
            }

    # --------------------------------------------------------
    # PORTFOLIO OPEN-RISK CAP
    # --------------------------------------------------------

    portfolio_risk = (
        get_open_portfolio_risk(
            trader
        )
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
        * 100
    )

    if (
        projected_risk_pct
        > MAX_PORTFOLIO_RISK_PCT
    ):

        return {
            "approved":
                False,

            "status":
                "PORTFOLIO_RISK_LIMIT",

            "reason":
                (
                    "Projected portfolio risk "
                    "exceeds maximum"
                ),

            "current_risk_pct":
                portfolio_risk[
                    "risk_pct"
                ],

            "projected_risk_pct":
                projected_risk_pct,

            "limit_pct":
                MAX_PORTFOLIO_RISK_PCT,
        }

    # --------------------------------------------------------
    # FINAL APPROVAL
    # --------------------------------------------------------

    return {
        "approved":
            True,

        "status":
            "APPROVED",

        "reason":
            "Portfolio Risk Governor approved trade",

        "asset_class":
            asset_class,

        "slot":
            slot,

        "symbol":
            symbol,

        "balance":
            balance,

        "proposed_risk_amount":
            proposed_risk_amount,

        "proposed_risk_pct":
            proposed_risk_pct,

        "current_portfolio_risk_pct":
            portfolio_risk[
                "risk_pct"
            ],

        "projected_portfolio_risk_pct":
            projected_risk_pct,

        "daily_loss_pct":
            daily[
                "loss_pct"
            ],

        "drawdown_pct":
            drawdown[
                "drawdown_pct"
            ],

        "consecutive_losses":
            consecutive_losses,

        "paper_only":
            True,

        "real_execution":
            False,
    }


# ============================================================
# PORTFOLIO GOVERNOR SNAPSHOT
# ============================================================

def get_portfolio_risk_snapshot(
    trader,
) -> Dict:

    baseline = (
        get_account_baseline(
            trader
        )
    )

    daily = (
        get_daily_loss_status(
            trader
        )
    )

    drawdown = (
        get_account_drawdown(
            trader
        )
    )

    open_risk = (
        get_open_portfolio_risk(
            trader
        )
    )

    cooldown = (
        get_global_cooldown(
            trader
        )
    )

    consecutive_losses = (
        get_consecutive_losses(
            trader
        )
    )

    try:

        portfolio = (
            trader.get_portfolio_snapshot()
        )

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

    if (
        consecutive_losses
        >= MAX_CONSECUTIVE_LOSSES
    ):

        locked_reasons.append(
            "LOSS_STREAK"
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
        "engine":
            "V4.0 Portfolio Risk Governor",

        "paper_only":
            True,

        "real_execution":
            False,

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

        "daily":
            daily,

        "drawdown":
            drawdown,

        "open_risk":
            open_risk,

        "consecutive_losses":
            consecutive_losses,

        "cooldown":
            cooldown,

        "portfolio":
            portfolio,

        "limits":
            {
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

                "global_cooldown_seconds":
                    GLOBAL_TRADE_COOLDOWN_SECONDS,

                "max_crypto_risk_pct":
                    MAX_CRYPTO_RISK_PCT,

                "max_metals_risk_pct":
                    MAX_METALS_RISK_PCT,
            },
    }


# ============================================================
# HEALTH
# ============================================================

def portfolio_risk_governor_health(
    trader=None,
) -> Dict:

    result = {
        "ok":
            True,

        "engine":
            "V4.0 Portfolio Risk Governor",

        "paper_only":
            True,

        "real_execution_locked":
            True,

        "supported_asset_classes":
            [
                "CRYPTO",
                "METAL",
            ],

        "future_asset_ready":
            True,
    }

    if trader is not None:

        try:

            result[
                "snapshot"
            ] = (
                get_portfolio_risk_snapshot(
                    trader
                )
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

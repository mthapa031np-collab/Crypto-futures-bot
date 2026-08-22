"""
settings.py

Central configuration for PRO AI QUANT TERMINAL V2.

All important bot settings live here so app.py,
scanner.py, trade_engine.py and bot_worker.py
do not need repeated manual edits.

PAPER TRADING ONLY for now.
"""

import os


# ============================================================
# MODE
# ============================================================

PAPER_TRADING = (
    os.environ.get("PAPER_TRADING", "true").lower() == "true"
)

REAL_TRADING_ENABLED = False


# ============================================================
# PAPER ACCOUNT
# ============================================================

PAPER_BALANCE = float(
    os.environ.get("PAPER_BALANCE", "10000")
)


# ============================================================
# RISK
# ============================================================

RISK_PCT = float(
    os.environ.get("RISK_PCT", "1")
)

MAX_DAILY_LOSS_PCT = float(
    os.environ.get("MAX_DAILY_LOSS_PCT", "5")
)

MAX_OPEN_POSITIONS = int(
    os.environ.get("MAX_OPEN_POSITIONS", "1")
)

MAX_PORTFOLIO_RISK_PCT = float(
    os.environ.get("MAX_PORTFOLIO_RISK_PCT", "3")
)


# ============================================================
# TRADE MANAGEMENT
# ============================================================

TP_PCT = float(
    os.environ.get("TP_PCT", "2")
)

SL_PCT = float(
    os.environ.get("SL_PCT", "1")
)

TRAILING_STOP_ENABLED = (
    os.environ.get(
        "TRAILING_STOP_ENABLED",
        "false",
    ).lower()
    == "true"
)

TRAILING_STOP_PCT = float(
    os.environ.get(
        "TRAILING_STOP_PCT",
        "0.7",
    )
)

BREAK_EVEN_ENABLED = (
    os.environ.get(
        "BREAK_EVEN_ENABLED",
        "false",
    ).lower()
    == "true"
)

BREAK_EVEN_TRIGGER_PCT = float(
    os.environ.get(
        "BREAK_EVEN_TRIGGER_PCT",
        "1",
    )
)


# ============================================================
# SCANNER
# ============================================================

POLL_SECONDS = int(
    os.environ.get("POLL_SECONDS", "60")
)

TIMEFRAME_MINUTES = int(
    os.environ.get(
        "TIMEFRAME_MINUTES",
        "15",
    )
)

CANDLE_LIMIT = int(
    os.environ.get(
        "CANDLE_LIMIT",
        "100",
    )
)


# ============================================================
# CORE MARKETS
# ============================================================

# V5.12 canonical crypto scan universe.
#
# Design goals:
# - Expand opportunity coverage from 11 to 30 liquid, established markets.
# - Keep the current Coinbase USD market-data path and V5 strategy/risk/lifecycle
#   architecture unchanged.
# - Exclude stablecoins, wrapped duplicates, and very small/illiquid assets.
# - A market-data failure for any individual symbol remains isolated by scanner.py.
SCAN_MARKETS = [
    "BTCUSDT",
    "ETHUSDT",
    "SOLUSDT",
    "XRPUSDT",
    "ADAUSDT",
    "DOGEUSDT",
    "AVAXUSDT",
    "LINKUSDT",
    "DOTUSDT",
    "NEARUSDT",
    "SUIUSDT",
    "LTCUSDT",
    "BCHUSDT",
    "UNIUSDT",
    "AAVEUSDT",
    "ATOMUSDT",
    "FILUSDT",
    "ICPUSDT",
    "ETCUSDT",
    "XLMUSDT",
    "HBARUSDT",
    "ALGOUSDT",
    "APTUSDT",
    "ARBUSDT",
    "OPUSDT",
    "INJUSDT",
    "SEIUSDT",
    "SHIBUSDT",
    "PEPEUSDT",
    "BONKUSDT",
]


# ============================================================
# SIGNAL REQUIREMENTS
# ============================================================

MIN_BUY_SCORE = int(
    os.environ.get(
        "MIN_BUY_SCORE",
        "4",
    )
)

MAX_SELL_SCORE = int(
    os.environ.get(
        "MAX_SELL_SCORE",
        "-4",
    )
)


# ============================================================
# TESTING CONTROLS
# ============================================================

TEST_MODE = (
    os.environ.get(
        "TEST_MODE",
        "false",
    ).lower()
    == "true"
)

TEST_TP_PCT = float(
    os.environ.get(
        "TEST_TP_PCT",
        "0.5",
    )
)

TEST_SL_PCT = float(
    os.environ.get(
        "TEST_SL_PCT",
        "0.3",
    )
)


# ============================================================
# DATABASE
# ============================================================

DATABASE_URL = os.environ.get(
    "DATABASE_URL",
    "",
).strip()

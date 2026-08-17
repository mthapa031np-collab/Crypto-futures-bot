"""
asset_registry.py

PRO AI QUANT TERMINAL V3

Central multi-asset registry.

Purpose:
- Keep all supported markets in one place
- Separate Crypto / Stocks / Metals / Indices / ETFs
- Make future expansion cleaner
- Avoid hardcoding symbols across app.py / scanner.py / UI
- Allow per-asset metadata and feature flags

IMPORTANT:
- Registry only
- No order execution
- No API secrets
"""

from typing import Dict, List, Optional


# ============================================================
# ASSET CLASS CONSTANTS
# ============================================================

ASSET_CRYPTO = "CRYPTO"
ASSET_STOCK = "STOCK"
ASSET_METAL = "METAL"
ASSET_INDEX = "INDEX"
ASSET_ETF = "ETF"


# ============================================================
# CRYPTO UNIVERSE
# ============================================================

CRYPTO_ASSETS: Dict[str, Dict] = {
    "BTCUSDT": {
        "name": "Bitcoin",
        "base": "BTC",
        "quote": "USDT",
        "asset_class": ASSET_CRYPTO,
        "enabled": True,
        "scanner_enabled": True,
        "tradable": True,
        "reference_symbol": "BTC-USD",
        "chart_symbol": "BTCUSDT",
        "liquidity_tier": "A",
    },
    "ETHUSDT": {
        "name": "Ethereum",
        "base": "ETH",
        "quote": "USDT",
        "asset_class": ASSET_CRYPTO,
        "enabled": True,
        "scanner_enabled": True,
        "tradable": True,
        "reference_symbol": "ETH-USD",
        "chart_symbol": "ETHUSDT",
        "liquidity_tier": "A",
    },
    "SOLUSDT": {
        "name": "Solana",
        "base": "SOL",
        "quote": "USDT",
        "asset_class": ASSET_CRYPTO,
        "enabled": True,
        "scanner_enabled": True,
        "tradable": True,
        "reference_symbol": "SOL-USD",
        "chart_symbol": "SOLUSDT",
        "liquidity_tier": "A",
    },
    "XRPUSDT": {
        "name": "XRP",
        "base": "XRP",
        "quote": "USDT",
        "asset_class": ASSET_CRYPTO,
        "enabled": True,
        "scanner_enabled": True,
        "tradable": True,
        "reference_symbol": "XRP-USD",
        "chart_symbol": "XRPUSDT",
        "liquidity_tier": "A",
    },
    "ADAUSDT": {
        "name": "Cardano",
        "base": "ADA",
        "quote": "USDT",
        "asset_class": ASSET_CRYPTO,
        "enabled": True,
        "scanner_enabled": True,
        "tradable": True,
        "reference_symbol": "ADA-USD",
        "chart_symbol": "ADAUSDT",
        "liquidity_tier": "B",
    },
    "DOGEUSDT": {
        "name": "Dogecoin",
        "base": "DOGE",
        "quote": "USDT",
        "asset_class": ASSET_CRYPTO,
        "enabled": True,
        "scanner_enabled": True,
        "tradable": True,
        "reference_symbol": "DOGE-USD",
        "chart_symbol": "DOGEUSDT",
        "liquidity_tier": "A",
    },
    "AVAXUSDT": {
        "name": "Avalanche",
        "base": "AVAX",
        "quote": "USDT",
        "asset_class": ASSET_CRYPTO,
        "enabled": True,
        "scanner_enabled": True,
        "tradable": True,
        "reference_symbol": "AVAX-USD",
        "chart_symbol": "AVAXUSDT",
        "liquidity_tier": "B",
    },
    "LINKUSDT": {
        "name": "Chainlink",
        "base": "LINK",
        "quote": "USDT",
        "asset_class": ASSET_CRYPTO,
        "enabled": True,
        "scanner_enabled": True,
        "tradable": True,
        "reference_symbol": "LINK-USD",
        "chart_symbol": "LINKUSDT",
        "liquidity_tier": "A",
    },
    "DOTUSDT": {
        "name": "Polkadot",
        "base": "DOT",
        "quote": "USDT",
        "asset_class": ASSET_CRYPTO,
        "enabled": True,
        "scanner_enabled": True,
        "tradable": True,
        "reference_symbol": "DOT-USD",
        "chart_symbol": "DOTUSDT",
        "liquidity_tier": "B",
    },
    "NEARUSDT": {
        "name": "NEAR Protocol",
        "base": "NEAR",
        "quote": "USDT",
        "asset_class": ASSET_CRYPTO,
        "enabled": True,
        "scanner_enabled": True,
        "tradable": True,
        "reference_symbol": "NEAR-USD",
        "chart_symbol": "NEARUSDT",
        "liquidity_tier": "B",
    },
    "SUIUSDT": {
        "name": "Sui",
        "base": "SUI",
        "quote": "USDT",
        "asset_class": ASSET_CRYPTO,
        "enabled": True,
        "scanner_enabled": True,
        "tradable": True,
        "reference_symbol": "SUI-USD",
        "chart_symbol": "SUIUSDT",
        "liquidity_tier": "B",
    },
}


# ============================================================
# STOCK UNIVERSE
# ============================================================

STOCK_ASSETS: Dict[str, Dict] = {
    "AAPL": {
        "name": "Apple",
        "asset_class": ASSET_STOCK,
        "enabled": True,
        "scanner_enabled": False,
        "tradable": False,
        "exchange": "NASDAQ",
        "currency": "USD",
        "sector": "Technology",
    },
    "MSFT": {
        "name": "Microsoft",
        "asset_class": ASSET_STOCK,
        "enabled": True,
        "scanner_enabled": False,
        "tradable": False,
        "exchange": "NASDAQ",
        "currency": "USD",
        "sector": "Technology",
    },
    "NVDA": {
        "name": "NVIDIA",
        "asset_class": ASSET_STOCK,
        "enabled": True,
        "scanner_enabled": False,
        "tradable": False,
        "exchange": "NASDAQ",
        "currency": "USD",
        "sector": "Technology",
    },
    "TSLA": {
        "name": "Tesla",
        "asset_class": ASSET_STOCK,
        "enabled": True,
        "scanner_enabled": False,
        "tradable": False,
        "exchange": "NASDAQ",
        "currency": "USD",
        "sector": "Consumer Discretionary",
    },
    "AMZN": {
        "name": "Amazon",
        "asset_class": ASSET_STOCK,
        "enabled": True,
        "scanner_enabled": False,
        "tradable": False,
        "exchange": "NASDAQ",
        "currency": "USD",
        "sector": "Consumer Discretionary",
    },
    "META": {
        "name": "Meta Platforms",
        "asset_class": ASSET_STOCK,
        "enabled": True,
        "scanner_enabled": False,
        "tradable": False,
        "exchange": "NASDAQ",
        "currency": "USD",
        "sector": "Communication Services",
    },
    "GOOGL": {
        "name": "Alphabet",
        "asset_class": ASSET_STOCK,
        "enabled": True,
        "scanner_enabled": False,
        "tradable": False,
        "exchange": "NASDAQ",
        "currency": "USD",
        "sector": "Communication Services",
    },
}


# ============================================================
# METALS
# ============================================================

METAL_ASSETS: Dict[str, Dict] = {
    "XAUUSD": {
        "name": "Gold",
        "asset_class": ASSET_METAL,
        "enabled": True,
        "scanner_enabled": False,
        "tradable": False,
        "currency": "USD",
        "symbol_family": "XAU/USD",
    },
    "XAGUSD": {
        "name": "Silver",
        "asset_class": ASSET_METAL,
        "enabled": True,
        "scanner_enabled": False,
        "tradable": False,
        "currency": "USD",
        "symbol_family": "XAG/USD",
    },
}


# ============================================================
# INDICES
# ============================================================

INDEX_ASSETS: Dict[str, Dict] = {
    "SPX": {
        "name": "S&P 500",
        "asset_class": ASSET_INDEX,
        "enabled": True,
        "scanner_enabled": False,
        "tradable": False,
        "currency": "USD",
    },
    "NDX": {
        "name": "Nasdaq 100",
        "asset_class": ASSET_INDEX,
        "enabled": True,
        "scanner_enabled": False,
        "tradable": False,
        "currency": "USD",
    },
    "DJI": {
        "name": "Dow Jones Industrial Average",
        "asset_class": ASSET_INDEX,
        "enabled": True,
        "scanner_enabled": False,
        "tradable": False,
        "currency": "USD",
    },
}


# ============================================================
# ETFs
# ============================================================

ETF_ASSETS: Dict[str, Dict] = {
    "SPY": {
        "name": "SPDR S&P 500 ETF",
        "asset_class": ASSET_ETF,
        "enabled": True,
        "scanner_enabled": False,
        "tradable": False,
        "currency": "USD",
    },
    "QQQ": {
        "name": "Invesco QQQ",
        "asset_class": ASSET_ETF,
        "enabled": True,
        "scanner_enabled": False,
        "tradable": False,
        "currency": "USD",
    },
    "GLD": {
        "name": "SPDR Gold Shares",
        "asset_class": ASSET_ETF,
        "enabled": True,
        "scanner_enabled": False,
        "tradable": False,
        "currency": "USD",
    },
}


# ============================================================
# MASTER REGISTRY
# ============================================================

ASSET_REGISTRY: Dict[str, Dict] = {}

ASSET_REGISTRY.update(CRYPTO_ASSETS)
ASSET_REGISTRY.update(STOCK_ASSETS)
ASSET_REGISTRY.update(METAL_ASSETS)
ASSET_REGISTRY.update(INDEX_ASSETS)
ASSET_REGISTRY.update(ETF_ASSETS)


# ============================================================
# HELPERS
# ============================================================

def get_asset(symbol: str) -> Optional[Dict]:
    return ASSET_REGISTRY.get(
        str(symbol).upper()
    )


def get_assets_by_class(
    asset_class: str,
) -> List[str]:

    asset_class = (
        str(asset_class)
        .upper()
        .strip()
    )

    return [
        symbol
        for symbol, info in ASSET_REGISTRY.items()
        if info.get("asset_class") == asset_class
        and info.get("enabled", False)
    ]


def get_enabled_assets() -> List[str]:

    return [
        symbol
        for symbol, info in ASSET_REGISTRY.items()
        if info.get("enabled", False)
    ]


def get_scanner_assets(
    asset_class: Optional[str] = None,
) -> List[str]:

    symbols = []

    for symbol, info in ASSET_REGISTRY.items():

        if not info.get(
            "enabled",
            False,
        ):
            continue

        if not info.get(
            "scanner_enabled",
            False,
        ):
            continue

        if asset_class:

            if (
                info.get("asset_class")
                != str(asset_class).upper()
            ):
                continue

        symbols.append(symbol)

    return symbols


def get_tradable_assets(
    asset_class: Optional[str] = None,
) -> List[str]:

    symbols = []

    for symbol, info in ASSET_REGISTRY.items():

        if not info.get(
            "enabled",
            False,
        ):
            continue

        if not info.get(
            "tradable",
            False,
        ):
            continue

        if asset_class:

            if (
                info.get("asset_class")
                != str(asset_class).upper()
            ):
                continue

        symbols.append(symbol)

    return symbols


def is_supported(symbol: str) -> bool:

    return (
        str(symbol).upper()
        in ASSET_REGISTRY
    )


def asset_classes() -> List[str]:

    return [
        ASSET_CRYPTO,
        ASSET_STOCK,
        ASSET_METAL,
        ASSET_INDEX,
        ASSET_ETF,
    ]


# ============================================================
# SAFE FEATURE FLAGS
# ============================================================

def enable_scanner(
    symbol: str,
    enabled: bool = True,
) -> bool:

    symbol = str(
        symbol
    ).upper()

    if symbol not in ASSET_REGISTRY:
        return False

    ASSET_REGISTRY[
        symbol
    ]["scanner_enabled"] = bool(
        enabled
    )

    return True


def enable_trading(
    symbol: str,
    enabled: bool = True,
) -> bool:

    symbol = str(
        symbol
    ).upper()

    if symbol not in ASSET_REGISTRY:
        return False

    ASSET_REGISTRY[
        symbol
    ]["tradable"] = bool(
        enabled
    )

    return True

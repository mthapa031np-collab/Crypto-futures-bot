"""
metals_dashboard.py

PRO AI QUANT TERMINAL V3
Metals dashboard presentation layer.

Provides:
- Gold live quote
- Silver live quote
- Bid / Ask / Spread
- High / Low
- Change %
- Metals provider health
- Safe handling when provider is unavailable

NO REAL ORDER EXECUTION.
"""

import streamlit as st

from metals_provider import (
    get_gold_quote,
    get_silver_quote,
    metals_provider_health,
)


# ============================================================
# HELPERS
# ============================================================

def _number(
    value,
    decimals=2,
):

    if value is None:
        return "—"

    try:
        return f"{float(value):,.{decimals}f}"

    except (
        TypeError,
        ValueError,
    ):
        return "—"


def _percent(
    value,
):

    if value is None:
        return "—"

    try:
        return f"{float(value):+.2f}%"

    except (
        TypeError,
        ValueError,
    ):
        return "—"


# ============================================================
# PROVIDER STATUS
# ============================================================

@st.cache_data(
    ttl=60,
    show_spinner=False,
)
def cached_provider_health():

    return metals_provider_health()


@st.cache_data(
    ttl=60,
    show_spinner=False,
)
def cached_gold_quote():

    return get_gold_quote()


@st.cache_data(
    ttl=60,
    show_spinner=False,
)
def cached_silver_quote():

    return get_silver_quote()


# ============================================================
# ONE METAL CARD
# ============================================================

def render_metal_card(
    title,
    symbol,
    quote,
):

    st.subheader(
        f"{title} • {symbol}"
    )

    if not quote:

        st.warning(
            f"{title} data is currently unavailable."
        )

        return

    last = quote.get(
        "last"
    )

    bid = quote.get(
        "bid"
    )

    ask = quote.get(
        "ask"
    )

    high = quote.get(
        "high"
    )

    low = quote.get(
        "low"
    )

    change_pct = quote.get(
        "change_pct"
    )

    spread_pct = quote.get(
        "spread_pct"
    )

    c1, c2, c3 = st.columns(
        3
    )

    with c1:

        st.metric(
            "Spot Price",
            f"${_number(last, 2)}",
            delta=(
                _percent(
                    change_pct
                )
                if change_pct is not None
                else None
            ),
        )

    with c2:

        st.metric(
            "Bid",
            (
                f"${_number(bid, 2)}"
                if bid is not None
                else "—"
            ),
        )

    with c3:

        st.metric(
            "Ask",
            (
                f"${_number(ask, 2)}"
                if ask is not None
                else "—"
            ),
        )

    c4, c5, c6 = st.columns(
        3
    )

    with c4:

        st.metric(
            "High",
            (
                f"${_number(high, 2)}"
                if high is not None
                else "—"
            ),
        )

    with c5:

        st.metric(
            "Low",
            (
                f"${_number(low, 2)}"
                if low is not None
                else "—"
            ),
        )

    with c6:

        st.metric(
            "Spread",
            (
                _percent(
                    spread_pct
                )
                if spread_pct is not None
                else "—"
            ),
        )

    st.caption(
        "Source: "
        f"{quote.get('source', 'Metals.Dev')} "
        "• USD per troy ounce"
    )


# ============================================================
# MAIN METALS DASHBOARD
# ============================================================

def render_metals_dashboard():

    st.markdown(
        "## 🥇 Metals Intelligence"
    )

    health = (
        cached_provider_health()
    )

    if not health.get(
        "ok",
        False,
    ):

        st.error(
            "Metals data provider is not ready."
        )

        st.code(
            str(
                health.get(
                    "reason",
                    "Unknown provider error",
                )
            )
        )

        st.info(
            "Check that METALS_API_KEY "
            "exists in Render Environment "
            "and redeploy the service."
        )

        return

    st.success(
        "● Metals data provider online"
    )

    gold = (
        cached_gold_quote()
    )

    silver = (
        cached_silver_quote()
    )

    gold_col, silver_col = (
        st.columns(
            2
        )
    )

    with gold_col:

        render_metal_card(
            title="Gold",
            symbol="XAUUSD",
            quote=gold,
        )

    with silver_col:

        render_metal_card(
            title="Silver",
            symbol="XAGUSD",
            quote=silver,
        )

    st.divider()

    st.markdown(
        "### Metals Engine Status"
    )

    e1, e2, e3, e4 = (
        st.columns(
            4
        )
    )

    with e1:

        st.metric(
            "Live Quotes",
            "ACTIVE",
        )

    with e2:

        st.metric(
            "Gold",
            "XAUUSD",
        )

    with e3:

        st.metric(
            "Silver",
            "XAGUSD",
        )

    with e4:

        st.metric(
            "Real Orders",
            "DISABLED",
        )

    st.info(
        "Current Metals phase provides "
        "live Gold and Silver spot intelligence only. "
        "Automatic metals trading remains disabled "
        "until intraday candles, MTF confirmation, "
        "metals-specific risk rules and paper execution "
        "are validated."
    )

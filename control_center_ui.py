"""
PRO AI QUANT TERMINAL V3
Control Center UI

Purpose
-------
Professional Settings / Control Center for:
- Crypto engine
- Metals engine
- Risk controls
- Scanner controls
- MTF thresholds
- System health
- Environment readiness
- PostgreSQL health
- Safe persistent settings

This module does NOT place trades.
"""

from __future__ import annotations

import streamlit as st

from control_center import (
    V3Settings,
    control_center_snapshot,
    load_settings,
    pause_all_engines,
    reset_to_safe_defaults,
    resume_all_engines,
    save_settings,
)


# ============================================================
# HELPERS
# ============================================================

def _status_badge(
    label: str,
    ok: bool,
):
    if ok:
        st.success(
            f"● {label}: ONLINE"
        )
    else:
        st.error(
            f"● {label}: ERROR"
        )


def _section_title(
    title: str,
    caption: str | None = None,
):
    st.markdown(
        f"### {title}"
    )

    if caption:
        st.caption(
            caption
        )


# ============================================================
# CONTROL CENTER HEADER
# ============================================================

def render_control_center_header():
    st.markdown(
        "## ⚙️ V3 Control Center"
    )

    st.caption(
        "Central configuration, risk, engine control, "
        "health monitoring and persistent runtime settings."
    )


# ============================================================
# MASTER CONTROL
# ============================================================

def render_master_controls(
    settings: V3Settings,
):

    _section_title(
        "Master Engine Control",
        "Global safety and engine state."
    )

    c1, c2, c3, c4 = st.columns(
        4
    )

    with c1:
        if settings.global_pause:

            if st.button(
                "▶ Resume All",
                width="stretch",
            ):
                resume_all_engines()
                st.rerun()

        else:

            if st.button(
                "⏸ Pause All",
                width="stretch",
            ):
                pause_all_engines()
                st.rerun()

    with c2:
        st.metric(
            "Crypto Engine",
            (
                "ON"
                if settings.crypto_enabled
                else "OFF"
            ),
        )

    with c3:
        st.metric(
            "Metals Engine",
            (
                "ON"
                if settings.metals_enabled
                else "OFF"
            ),
        )

    with c4:
        st.metric(
            "Execution Mode",
            (
                "PAPER"
                if settings.paper_trading
                else "LIVE"
            ),
        )

    if settings.live_trading_hard_lock:
        st.success(
            "Live Trading Hard Lock: ENABLED"
        )
    else:
        st.warning(
            "Live Trading Hard Lock: DISABLED"
        )


# ============================================================
# ENGINE SETTINGS FORM
# ============================================================

def render_engine_settings(
    settings: V3Settings,
):

    _section_title(
        "Engine Configuration",
        "Persistent Crypto and Metals runtime controls."
    )

    with st.form(
        "v3_engine_settings_form"
    ):

        left, right = st.columns(
            2
        )

        with left:

            st.markdown(
                "#### ₿ Crypto Engine"
            )

            crypto_enabled = st.toggle(
                "Crypto Engine Enabled",
                value=settings.crypto_enabled,
            )

            crypto_risk_pct = st.number_input(
                "Crypto Risk % / Trade",
                min_value=0.10,
                max_value=5.00,
                value=float(
                    settings.crypto_risk_pct
                ),
                step=0.10,
            )

            crypto_scan_seconds = st.number_input(
                "Crypto Scan Interval (seconds)",
                min_value=15,
                max_value=3600,
                value=int(
                    settings.crypto_scan_seconds
                ),
                step=15,
            )

            crypto_min_score = st.number_input(
                "Crypto Minimum AI Score",
                min_value=0.0,
                max_value=100.0,
                value=float(
                    settings.crypto_min_score
                ),
                step=1.0,
            )

            crypto_min_mtf = st.number_input(
                "Crypto Minimum MTF Confidence %",
                min_value=0.0,
                max_value=100.0,
                value=float(
                    settings.crypto_min_mtf_confidence
                ),
                step=1.0,
            )

        with right:

            st.markdown(
                "#### 🥇 Metals Engine"
            )

            metals_enabled = st.toggle(
                "Metals Engine Enabled",
                value=settings.metals_enabled,
            )

            metals_risk_pct = st.number_input(
                "Metals Risk % / Trade",
                min_value=0.10,
                max_value=3.00,
                value=float(
                    settings.metals_risk_pct
                ),
                step=0.10,
            )

            metals_scan_seconds = st.number_input(
                "Metals Scan Interval (seconds)",
                min_value=15,
                max_value=3600,
                value=int(
                    settings.metals_scan_seconds
                ),
                step=15,
            )

            metals_min_score = st.number_input(
                "Metals Minimum AI Score",
                min_value=0.0,
                max_value=100.0,
                value=float(
                    settings.metals_min_score
                ),
                step=1.0,
            )

            metals_min_mtf = st.number_input(
                "Metals Minimum MTF Confidence %",
                min_value=0.0,
                max_value=100.0,
                value=float(
                    settings.metals_min_mtf_confidence
                ),
                step=1.0,
            )

        st.divider()

        st.markdown(
            "#### Portfolio Risk"
        )

        r1, r2, r3 = st.columns(
            3
        )

        with r1:

            max_daily_loss_pct = st.number_input(
                "Max Daily Loss %",
                min_value=0.50,
                max_value=20.00,
                value=float(
                    settings.max_daily_loss_pct
                ),
                step=0.25,
            )

        with r2:

            max_total_drawdown_pct = st.number_input(
                "Max Total Drawdown %",
                min_value=1.00,
                max_value=50.00,
                value=float(
                    settings.max_total_drawdown_pct
                ),
                step=0.50,
            )

        with r3:

            max_consecutive_losses = st.number_input(
                "Max Consecutive Losses",
                min_value=1,
                max_value=20,
                value=int(
                    settings.max_consecutive_losses
                ),
                step=1,
            )

        p1, p2, p3 = st.columns(
            3
        )

        with p1:

            max_open_positions = st.number_input(
                "Max Total Open Positions",
                min_value=1,
                max_value=10,
                value=int(
                    settings.max_open_positions
                ),
                step=1,
            )

        with p2:

            max_crypto_positions = st.number_input(
                "Max Crypto Positions",
                min_value=0,
                max_value=10,
                value=int(
                    settings.max_crypto_positions
                ),
                step=1,
            )

        with p3:

            max_metals_positions = st.number_input(
                "Max Metals Positions",
                min_value=0,
                max_value=10,
                value=int(
                    settings.max_metals_positions
                ),
                step=1,
            )

        submitted = st.form_submit_button(
            "💾 Save Engine Settings",
            width="stretch",
        )

        if submitted:

            updated = V3Settings(
                global_pause=settings.global_pause,

                crypto_enabled=crypto_enabled,
                metals_enabled=metals_enabled,

                paper_trading=settings.paper_trading,
                real_execution_enabled=False,
                live_trading_hard_lock=True,

                max_open_positions=max_open_positions,
                max_crypto_positions=max_crypto_positions,
                max_metals_positions=max_metals_positions,

                crypto_risk_pct=crypto_risk_pct,
                metals_risk_pct=metals_risk_pct,

                max_daily_loss_pct=max_daily_loss_pct,
                max_total_drawdown_pct=max_total_drawdown_pct,
                max_consecutive_losses=max_consecutive_losses,

                crypto_scan_seconds=crypto_scan_seconds,
                crypto_min_score=crypto_min_score,
                crypto_min_mtf_confidence=crypto_min_mtf,

                metals_scan_seconds=metals_scan_seconds,
                metals_min_score=metals_min_score,
                metals_min_mtf_confidence=metals_min_mtf,

                metals_atr_stop_multiplier=(
                    settings.metals_atr_stop_multiplier
                ),

                metals_atr_target_multiplier=(
                    settings.metals_atr_target_multiplier
                ),

                metals_break_even_rr=(
                    settings.metals_break_even_rr
                ),

                metals_trailing_start_rr=(
                    settings.metals_trailing_start_rr
                ),

                metals_trailing_atr_multiplier=(
                    settings.metals_trailing_atr_multiplier
                ),

                crypto_break_even_rr=(
                    settings.crypto_break_even_rr
                ),

                crypto_trailing_start_rr=(
                    settings.crypto_trailing_start_rr
                ),

                require_fresh_market_data=(
                    settings.require_fresh_market_data
                ),

                max_market_data_age_seconds=(
                    settings.max_market_data_age_seconds
                ),

                require_mtf_confirmation=(
                    settings.require_mtf_confirmation
                ),

                trade_cooldown_seconds=(
                    settings.trade_cooldown_seconds
                ),

                ui_refresh_seconds=(
                    settings.ui_refresh_seconds
                ),

                show_advanced_diagnostics=(
                    settings.show_advanced_diagnostics
                ),

                config_version=(
                    settings.config_version
                ),

                updated_at=(
                    settings.updated_at
                ),
            )

            save_settings(
                updated
            )

            st.success(
                "V3 Control Center settings saved."
            )

            st.rerun()


# ============================================================
# ADVANCED RISK MANAGEMENT
# ============================================================

def render_advanced_risk(
    settings: V3Settings,
):

    _section_title(
        "Advanced Position Management",
        "Break-even, trailing and ATR-based Metals controls."
    )

    with st.form(
        "v3_advanced_risk_form"
    ):

        left, right = st.columns(
            2
        )

        with left:

            st.markdown(
                "#### 🥇 Metals Dynamic Risk"
            )

            metals_atr_stop_multiplier = (
                st.number_input(
                    "ATR Stop Multiplier",
                    min_value=0.50,
                    max_value=5.00,
                    value=float(
                        settings
                        .metals_atr_stop_multiplier
                    ),
                    step=0.10,
                )
            )

            metals_atr_target_multiplier = (
                st.number_input(
                    "ATR Target Multiplier",
                    min_value=0.50,
                    max_value=10.00,
                    value=float(
                        settings
                        .metals_atr_target_multiplier
                    ),
                    step=0.10,
                )
            )

            metals_break_even_rr = (
                st.number_input(
                    "Move To Break-Even At R",
                    min_value=0.25,
                    max_value=5.00,
                    value=float(
                        settings
                        .metals_break_even_rr
                    ),
                    step=0.25,
                )
            )

            metals_trailing_start_rr = (
                st.number_input(
                    "Start Trailing At R",
                    min_value=0.50,
                    max_value=10.00,
                    value=float(
                        settings
                        .metals_trailing_start_rr
                    ),
                    step=0.25,
                )
            )

            metals_trailing_atr_multiplier = (
                st.number_input(
                    "Trailing ATR Multiplier",
                    min_value=0.25,
                    max_value=5.00,
                    value=float(
                        settings
                        .metals_trailing_atr_multiplier
                    ),
                    step=0.10,
                )
            )

        with right:

            st.markdown(
                "#### ₿ Crypto Management"
            )

            crypto_break_even_rr = (
                st.number_input(
                    "Crypto Break-Even At R",
                    min_value=0.25,
                    max_value=5.00,
                    value=float(
                        settings.crypto_break_even_rr
                    ),
                    step=0.25,
                )
            )

            crypto_trailing_start_rr = (
                st.number_input(
                    "Crypto Trailing Start At R",
                    min_value=0.50,
                    max_value=10.00,
                    value=float(
                        settings.crypto_trailing_start_rr
                    ),
                    step=0.25,
                )
            )

            require_mtf_confirmation = (
                st.toggle(
                    "Require MTF Confirmation",
                    value=settings
                    .require_mtf_confirmation,
                )
            )

            require_fresh_market_data = (
                st.toggle(
                    "Require Fresh Market Data",
                    value=settings
                    .require_fresh_market_data,
                )
            )

            max_market_data_age_seconds = (
                st.number_input(
                    "Maximum Market Data Age (seconds)",
                    min_value=15,
                    max_value=3600,
                    value=int(
                        settings
                        .max_market_data_age_seconds
                    ),
                    step=15,
                )
            )

            trade_cooldown_seconds = (
                st.number_input(
                    "Trade Cooldown (seconds)",
                    min_value=0,
                    max_value=86400,
                    value=int(
                        settings
                        .trade_cooldown_seconds
                    ),
                    step=60,
                )
            )

        save_advanced = (
            st.form_submit_button(
                "💾 Save Advanced Risk Settings",
                width="stretch",
            )
        )

        if save_advanced:

            settings.metals_atr_stop_multiplier = (
                metals_atr_stop_multiplier
            )

            settings.metals_atr_target_multiplier = (
                metals_atr_target_multiplier
            )

            settings.metals_break_even_rr = (
                metals_break_even_rr
            )

            settings.metals_trailing_start_rr = (
                metals_trailing_start_rr
            )

            settings.metals_trailing_atr_multiplier = (
                metals_trailing_atr_multiplier
            )

            settings.crypto_break_even_rr = (
                crypto_break_even_rr
            )

            settings.crypto_trailing_start_rr = (
                crypto_trailing_start_rr
            )

            settings.require_mtf_confirmation = (
                require_mtf_confirmation
            )

            settings.require_fresh_market_data = (
                require_fresh_market_data
            )

            settings.max_market_data_age_seconds = (
                max_market_data_age_seconds
            )

            settings.trade_cooldown_seconds = (
                trade_cooldown_seconds
            )

            save_settings(
                settings
            )

            st.success(
                "Advanced risk settings saved."
            )

            st.rerun()


# ============================================================
# SYSTEM HEALTH
# ============================================================

def render_system_health():

    _section_title(
        "System Health",
        "Live readiness snapshot."
    )

    snapshot = (
        control_center_snapshot()
    )

    database = snapshot.get(
        "database",
        {},
    )

    environment = snapshot.get(
        "environment",
        {},
    )

    execution = snapshot.get(
        "execution",
        {},
    )

    h1, h2, h3, h4 = st.columns(
        4
    )

    with h1:

        _status_badge(
            "PostgreSQL",
            bool(
                database.get(
                    "ok",
                    False,
                )
            ),
        )

    with h2:

        metals_data = (
            environment.get(
                "metals_data",
                {}
            )
        )

        _status_badge(
            "Metals Data",
            bool(
                metals_data.get(
                    "configured",
                    False,
                )
            ),
        )

    with h3:

        _status_badge(
            "Paper Execution",
            bool(
                execution.get(
                    "paper_allowed",
                    False,
                )
            ),
        )

    with h4:

        live_allowed = bool(
            execution.get(
                "live_allowed",
                False,
            )
        )

        if live_allowed:
            st.error(
                "● Real Execution: ARMED"
            )
        else:
            st.success(
                "● Real Execution: LOCKED"
            )

    st.divider()

    s1, s2 = st.columns(
        2
    )

    with s1:

        st.markdown(
            "#### Environment"
        )

        st.json(
            environment
        )

    with s2:

        st.markdown(
            "#### Execution Safety"
        )

        st.json(
            execution
        )

    if database.get(
        "message"
    ):

        st.caption(
            database.get(
                "message"
            )
        )


# ============================================================
# CURRENT CONFIG
# ============================================================

def render_current_configuration(
    settings: V3Settings,
):

    _section_title(
        "Current Runtime Configuration"
    )

    c1, c2, c3, c4 = st.columns(
        4
    )

    with c1:
        st.metric(
            "Crypto Risk",
            f"{settings.crypto_risk_pct:.2f}%",
        )

    with c2:
        st.metric(
            "Metals Risk",
            f"{settings.metals_risk_pct:.2f}%",
        )

    with c3:
        st.metric(
            "Daily Loss Limit",
            f"{settings.max_daily_loss_pct:.2f}%",
        )

    with c4:
        st.metric(
            "Max Positions",
            settings.max_open_positions,
        )

    st.caption(
        f"Configuration version: "
        f"{settings.config_version} "
        f"• Updated: "
        f"{settings.updated_at or 'Not yet persisted'}"
    )


# ============================================================
# RESET / SAFETY ZONE
# ============================================================

def render_safety_zone():

    _section_title(
        "Safety Zone",
        "Control Center reset only. "
        "Does not delete positions or trade history."
    )

    st.warning(
        "Reset restores safe paper-trading defaults "
        "and keeps the live-trading hard lock enabled."
    )

    confirm = st.checkbox(
        "I understand this resets Control Center settings only."
    )

    if st.button(
        "↺ Reset Control Center To Safe Defaults",
        disabled=not confirm,
        width="stretch",
    ):

        reset_to_safe_defaults()

        st.success(
            "Control Center reset to safe defaults."
        )

        st.rerun()


# ============================================================
# MAIN RENDER FUNCTION
# ============================================================

def render_control_center():

    render_control_center_header()

    settings = load_settings(
        force_reload=False
    )

    render_current_configuration(
        settings
    )

    st.divider()

    render_master_controls(
        settings
    )

    st.divider()

    render_engine_settings(
        settings
    )

    st.divider()

    render_advanced_risk(
        settings
    )

    st.divider()

    render_system_health()

    st.divider()

    render_safety_zone()

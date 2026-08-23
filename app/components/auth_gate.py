"""
Authentication gate (issue #30 A).

Router model: Home.py checks is_authenticated() and only registers the
protected pages in st.navigation once signed in - pre-auth, the sidebar has
nothing to list. render_login() draws the sign-in screen and drops a
sanitizer-safe marker div; app/assets/style.css scopes cosmetic hiding off
that marker (body:has([data-preauth])) because Streamlit strips inline
<style> tags from st.markdown.
"""

import logging

import streamlit as st

from core.config import Config
from core.security import password_matches

log = logging.getLogger(__name__)


def is_authenticated() -> bool:
    val = st.session_state.get("authenticated")
    log.debug("is_authenticated=%s", val)
    return bool(val)


def _password_ok(candidate: str) -> bool:
    expected = Config.APP_PASSWORD
    return password_matches(candidate, expected)


def render_login():
    """Sign-in screen. Call instead of navigating to protected pages."""
    # Open access: warn but do NOT emit the data-preauth marker — the
    # marker hides the sidebar, and hiding navigation from a user who
    # was never asked for a password makes the app unusable (#37).
    if st.session_state.get("_login_rendered"):
        return                                    # already warned this run
    st.session_state["_login_rendered"] = True

    if not Config.APP_PASSWORD:
        st.warning(
            "🔓 **No APP_PASSWORD is set.** Anyone who can reach this app "
            "can read your pricing data, vendor sessions and settings. "
            "Set `APP_PASSWORD` in `.env` to lock it down.",
            icon="⚠️"
        )
        return                                    # open access: nav stays visible

    # Gated mode: emit the sidebar-hiding marker ONLY when we are actually
    # demanding sign-in. A plain div with a data attribute survives
    # Streamlit's HTML sanitization (<style> does not).
    st.markdown('<div data-preauth hidden></div>', unsafe_allow_html=True)

    st.title("🔐 Kitchen Order Guide")
    st.caption("Enter the app password to continue.")

    with st.form("login_form", clear_on_submit=False):
        candidate = st.text_input("Password", type="password")
        submitted = st.form_submit_button(
            "Sign in", type="primary", use_container_width=True)

        if submitted:
            if _password_ok(candidate):
                st.session_state["authenticated"] = True
                st.rerun()
            else:
                st.error("Incorrect password.")

    st.stop()


def gate_or_stop():
    """Per-page guard: no-op when signed in; otherwise render the login
    gate and stop. Deep-linked routes execute their page file without the
    entry script, so every protected page keeps its own gate."""
    if not is_authenticated():
        render_login()


def require_login() -> bool:
    """
    Legacy entry point retained for any page run outside the router.
    Preferred flow: Home.py checks is_authenticated() and registers pages.
    """
    render_login()
    return False  # unreachable; render_login stops execution

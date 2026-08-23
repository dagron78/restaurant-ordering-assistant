"""
Authentication gate (issue #30 A; roles per Phase A · issue #50).

Router model: Home.py checks is_authenticated() and only registers the
protected pages in st.navigation once signed in - pre-auth, the sidebar has
nothing to list. render_login() draws the sign-in screen and drops a
sanitizer-safe marker div; app/assets/style.css scopes cosmetic hiding off
that marker (body:has([data-preauth])) because Streamlit strips inline
<style> tags from st.markdown.

Phase A: two passwords. The session carries a ROLE ("admin" or "app").
Configuration surfaces call require_admin(), which fails closed with an
explicit refusal screen. When no admin password exists at all the app
routes to first-run setup instead of issue #37's open-access warning —
a deliberate supersession recorded in docs/SPEC.md and the PR.
"""

import logging

import streamlit as st

from core import auth
from core.database import Database

log = logging.getLogger(__name__)

ROLE_KEY = "role"


def current_role() -> str:
    """The signed-in role: 'admin', 'app', or '' when signed out."""
    return st.session_state.get(ROLE_KEY) or ""


def is_authenticated() -> bool:
    val = current_role()
    log.debug("current_role=%s", val)
    return val in ("admin", "app")


def is_admin() -> bool:
    return current_role() == "admin"


def sign_out() -> None:
    st.session_state.pop(ROLE_KEY, None)


def _try_sign_in(candidate: str, db=None) -> bool:
    role = auth.authenticate(candidate, db=db)
    if role is None:
        return False
    st.session_state[ROLE_KEY] = role
    return True


def require_admin() -> bool:
    """
    Guard for configuration surfaces. Fails CLOSED: renders a refusal
    screen and stops unless an admin is signed in.
    """
    if is_admin():
        return True
    if not is_authenticated():
        render_login()
        return False                      # unreachable; render_login stops
    st.title("🔒 Admin access required")
    st.error(
        "You are signed in with the **app password**, which grants the "
        "ordering round only. Configuration requires the **admin "
        "password**.",
        icon="🚫",
    )
    st.markdown('<div data-admin-refused hidden></div>', unsafe_allow_html=True)
    with st.form("admin_reauth_form"):
        candidate = st.text_input("Admin password", type="password")
        if st.form_submit_button("Sign in as admin", type="primary"):
            if _try_sign_in(candidate):
                st.rerun()
            else:
                st.error("Incorrect admin password.")
    st.stop()


def render_login():
    """Sign-in screen. Routes to first-run setup while unconfigured.

    INVARIANT: this function NEVER returns while the session is
    unauthenticated — every path ends in st.stop() or st.rerun(). The
    pre-Phase-A guard returned silently on re-entry, letting the router
    fall through and render the whole app to a signed-out session: the
    bypass the Phase A regression test pins, exposed wide open by
    first-run, where any submit rerun reached the dashboard with no
    password configured at all.
    """
    if st.session_state.get("_login_rendered"):
        st.stop()                     # drawn earlier: never fall through
    st.session_state["_login_rendered"] = True

    db = Database()
    if not auth.is_configured(db=db):
        from app.components.first_run import render_setup

        render_setup(db=db)                       # fail closed into setup
        st.stop()

    # Gated mode: emit the sidebar-hiding marker ONLY when we are actually
    # demanding sign-in. A plain div with a data attribute survives
    # Streamlit's HTML sanitization (<style> does not).
    st.markdown('<div data-preauth hidden></div>', unsafe_allow_html=True)

    st.title("🔐 Kitchen Order Guide")
    st.caption("Enter the app password — or the admin password for "
               "configuration access.")

    with st.form("login_form", clear_on_submit=False):
        candidate = st.text_input("Password", type="password")
        submitted = st.form_submit_button(
            "Sign in", type="primary", use_container_width=True)

        if submitted:
            if _try_sign_in(candidate, db=db):
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

"""
First-run setup (Phase A · issue #50).

Shown exactly while the app has no admin password. Offers to set both
passwords and, optionally, the Gemini API key — in the app, never by
editing a file. This replaces issue #37's open-access-with-warning
behaviour: an unconfigured app now fails closed into guided setup,
because the spec makes LAN exposure a requirement and the password the
security model.

Deliberately a single clear page, not a wizard: the install bar is "a
reasonably technical person, possibly with AI help".
"""

import logging

import streamlit as st

from core import auth
from core.settings import set_settings

log = logging.getLogger(__name__)


def render_setup(db=None) -> None:
    st.title("🍳 Welcome — first-run setup")
    st.markdown(
        "Set the two passwords for this restaurant's app. "
        "**Admin** unlocks configuration as well; **app** is the everyday "
        "password for the ordering round."
    )
    st.caption(
        "🔒 Trusted-LAN note: this app is meant to be reached from phones "
        "on the restaurant's own wifi. These passwords are its security "
        "model — choose them accordingly."
    )

    with st.form("first_run_form", clear_on_submit=False):
        admin1 = st.text_input(
            "Admin password", type="password",
            help="Full access, including configuration.")
        admin2 = st.text_input("Repeat admin password", type="password")
        app1 = st.text_input(
            "App password (optional — leave blank to use the same)",
            type="password",
            help="Everyday access for the ordering round.")
        app2 = st.text_input("Repeat app password", type="password")
        api_key = st.text_input(
            "Gemini API key (optional)", type="password",
            help="Needed for AI parsing of price sheets and rules. "
                 "Can be added later under Settings → Configuration.")
        submitted = st.form_submit_button(
            "Finish setup", type="primary", use_container_width=True)

    if submitted:
        if not admin1:
            st.error("An admin password is required.")
            return
        if admin1 != admin2:
            st.error("Admin passwords do not match.")
            return
        effective_app = app1 or admin1
        if app1 and app1 != app2:
            st.error("App passwords do not match.")
            return
        try:
            auth.set_password("admin", admin1, db=db)
            auth.set_password("app", effective_app, db=db)
            updates = {}
            if api_key:
                updates["GOOGLE_API_KEY"] = api_key.strip()
            if updates:
                set_settings(updates, db=db)
        except Exception as e:
            log.error("First-run setup failed: %s", e)
            st.error(f"Setup failed: {e}")
            return
        st.session_state["role"] = "admin"
        st.success("✅ Setup complete — you are signed in as admin.")
        st.rerun()

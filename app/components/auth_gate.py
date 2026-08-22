"""
Authentication gate for the Streamlit UI.

Single shared-password model, sized for a homelab/restaurant deployment:
set APP_PASSWORD in .env and every page requires it before rendering.
Without APP_PASSWORD the app stays open but warns loudly on every page.

Import note: lives under app/components because it needs streamlit;
core/ must stay UI-free.
"""

import os

import streamlit as st

from core.security import password_matches


def require_login() -> bool:
    """
    Gate a page behind APP_PASSWORD when one is configured.

    Call at the top of app/main.py and every page in app/pages/.
    Returns True once access is allowed (and renders the login form,
    stopping execution, until the correct password is submitted).
    """
    expected = os.getenv('APP_PASSWORD', '')
    
    if not expected:
        st.warning(
            "🔓 **No APP_PASSWORD is set.** Anyone who can reach this app "
            "can read your pricing data, vendor sessions and settings. "
            "Set `APP_PASSWORD` in `.env` to lock it down.",
            icon="⚠️"
        )
        return True
    
    if st.session_state.get('authenticated'):
        return True
    
    st.title("🔐 Restaurant Ordering Assistant")
    st.caption("Enter the app password to continue.")
    
    with st.form("login_form", clear_on_submit=False):
        candidate = st.text_input("Password", type="password")
        submitted = st.form_submit_button("Sign in", type="primary", use_container_width=True)
        
        if submitted:
            if password_matches(candidate, expected):
                st.session_state['authenticated'] = True
                st.rerun()
            else:
                st.error("Incorrect password.")
    
    st.stop()
    return False  # unreachable; st.stop() halts

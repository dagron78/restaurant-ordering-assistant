"""
Cached app resources (Phase A · issue #50).

Single home for the @st.cache_resource factories so views, tests and the
cache-staleness guard all exercise the SAME objects.

Staleness contract: these factories may cache, but a settings write goes
through core.settings.set_settings(), which clears every
cache_resource/cache_data entry in the process. A config change is
therefore visible on the next acquisition — pinned by
tests/test_phase_a_ui.py::test_setting_change_visible_through_cached_resource_after_save.
"""

import streamlit as st

from core.config import Config
from core.database import Database


@st.cache_resource
def get_database() -> Database:
    """Get cached database instance."""
    db = Database()
    if not Config.DATABASE_PATH.exists():
        db.init_database()
    return db


@st.cache_resource
def get_engine():
    """Get cached recommendation engine.

    The engine's AI handle is lazy inside RecommendationEngine; combined
    with set_settings() invalidation this keeps API-key changes effective
    without a restart.
    """
    from core.recommendation import RecommendationEngine

    return RecommendationEngine(db=get_database())

"""Probe page for the Phase A cache-staleness guard.

Runs under AppTest from tests/test_phase_a_ui.py. Exercises the REAL
cached factories and the REAL settings save path, and records what the
engine's AI construction observed before and after a settings write.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

import streamlit as st

import core.ai_engine as ai_engine_module
from core.config import Config
from core.settings import set_settings
from app.components.resources import get_engine

# Instrument construction: record the key each GeminiEngine build saw,
# without touching production code or SDK internals.
_seen = {}
_real_init = ai_engine_module.GeminiEngine.__init__


def _spy_init(self):
    _real_init(self)
    _seen["key"] = Config.GOOGLE_API_KEY


ai_engine_module.GeminiEngine.__init__ = _spy_init
try:
    engine1 = get_engine()
    ai1 = engine1.ai                      # forces construction: initial key
    before = _seen.get("key")

    # The same write path the admin Configuration tab uses.
    set_settings({"GOOGLE_API_KEY": "rotated-key"})

    engine2 = get_engine()                # must NOT be the stale cache
    rebuilt = engine2 is not engine1
    ai2 = engine2.ai                      # fresh construction
    after = _seen.get("key")
finally:
    ai_engine_module.GeminiEngine.__init__ = _real_init

st.session_state["probe"] = {
    "before": str(before),
    "after": str(after),
    "rebuilt": bool(rebuilt),
}
st.caption("cache probe complete")

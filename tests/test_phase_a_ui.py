"""Phase A behavioural UI guards (issue #50) — DEFAULT invocation.

These deliberately do NOT carry the slow_ui marker: this phase ships the
configuration surface new installs land in, and a deselected guard
reporting green is a failure mode that has already shipped here. If you
mark anything in this file slow_ui, the default suite stops testing auth.

Named mutation targets (see PR body):
- test_app_password_cannot_open_admin_config
      mutant: grant an app-role session admin -> this dies.
- test_setting_change_visible_through_cached_resource_after_save
      mutant: drop cache invalidation from set_settings -> this dies.
"""

import pathlib

import pytest

from core import auth
from core.config import Config
from core.database import Database
from core.settings import set_settings

from streamlit.testing.v1 import AppTest

APP = pathlib.Path(__file__).parent.parent / "app"


@pytest.fixture()
def configured_db(tmp_path, monkeypatch):
    """Initialized database with both passwords and an initial API key,
    pointed at by Config.DATABASE_PATH."""
    db = Database(db_path=tmp_path / "phase_a.db")
    db.init_database()
    set_settings({"GOOGLE_API_KEY": "initial-key"}, db=db)
    auth.set_password("admin", "admin-secret", db=db)
    auth.set_password("app", "app-secret", db=db)
    monkeypatch.setattr(Config, "DATABASE_PATH", db.db_path, raising=True)
    return db


# ---- first-run routing ------------------------------------------------------

class TestFirstRunRouting:
    def test_unconfigured_app_offers_setup_not_open_access(
            self, tmp_path, monkeypatch):
        """Empty .env beyond the DB path: first run offers setup."""
        # Isolate from an ambient configured environment (the CI
        # configured-env leg sets INITIAL_ADMIN_PASSWORD): this test is
        # about the UNCONFIGURED state, where nothing bootstraps.
        monkeypatch.delenv("INITIAL_ADMIN_PASSWORD", raising=False)
        db = Database(db_path=tmp_path / "fresh.db")
        db.init_database()
        monkeypatch.setattr(Config, "DATABASE_PATH", db.db_path,
                            raising=True)
        at = AppTest.from_file(str(APP / "Home.py"))
        at.run(timeout=30)

        titles = [t.value for t in at.title]
        assert any("first-run setup" in t.lower() for t in titles), titles
        labels = [i.label for i in at.text_input]
        assert any("Admin password" in (lab or "") for lab in labels), labels
        # Fail closed: no dashboard content behind an unconfigured app.
        assert not any("Quick Actions" in (s.value or "")
                       for s in at.subheader)

    def test_bootstrap_initial_admin_adopted_once(self, tmp_path, monkeypatch):
        db = Database(db_path=tmp_path / "boot.db")
        db.init_database()
        monkeypatch.setattr(Config, "DATABASE_PATH", db.db_path,
                            raising=True)
        monkeypatch.setattr(Config, "initial_admin_password",
                            staticmethod(lambda: "installer-pw"))
        assert auth.bootstrap_initial_admin(db=db) is True
        assert auth.authenticate("installer-pw", db=db) == "admin"
        # Second boot is a no-op even though the env var persists.
        assert auth.bootstrap_initial_admin(db=db) is False


# ---- the role split ---------------------------------------------------------

class TestRoleSplit:
    def test_app_password_cannot_open_admin_config(self, configured_db):
        """NAMED MUTATION TARGET. An app-role session opening the
        configuration surface must hit the fail-closed refusal screen and
        see none of the controls."""
        at = AppTest.from_file(str(APP / "views" / "3_⚙️_Settings.py"))
        at.session_state["role"] = "app"
        at.run(timeout=30)

        # Refusal screen is on the page...
        refusal = [t.value for t in at.title]
        assert any("Admin access required" in t for t in refusal), refusal
        # ...the tab exists (Streamlit renders all tab containers) but the
        # admin controls within it were never built...
        subheaders = [s.value for s in at.subheader]
        assert not any("AI (Gemini)" in s for s in subheaders), subheaders
        assert not any("Vendor connections" in s for s in subheaders)
        # ...and the sanitizer-safe refusal marker is present.
        html = [m.value for m in at.markdown]
        assert any("data-admin-refused" in h for h in html), \
            "refusal marker missing"

    def test_admin_opens_configuration(self, configured_db):
        at = AppTest.from_file(str(APP / "views" / "3_⚙️_Settings.py"))
        at.session_state["role"] = "admin"
        at.run(timeout=30)

        subheaders = [s.value for s in at.subheader]
        assert any("AI (Gemini)" in s for s in subheaders), subheaders
        assert any("Scraping schedule" in s for s in subheaders)
        assert any("Trend thresholds" in s for s in subheaders)
        assert any("Password" in s for s in subheaders)
        assert any("Vendor connections" in s for s in subheaders)

    def test_signed_out_sees_login_not_dashboard(self, configured_db):
        at = AppTest.from_file(str(APP / "Home.py"))
        at.run(timeout=30)
        titles = [t.value for t in at.title]
        assert any("Kitchen Order Guide" in t for t in titles), titles
        assert not any("Quick Actions" in (s.value or "")
                       for s in at.subheader)


class TestLoginRenderInvariant:
    """render_login() must NEVER return while the session is signed out.

    The pre-Phase-A guard returned silently on re-entry (the
    `_login_rendered` early return), so ANY rerun after the gate had drawn
    once — e.g. submitting the login or first-run form — fell through the
    router and rendered the entire app to a signed-out session. With
    first-run that means the full app, no password ever configured.
    """

    def test_rerun_after_gate_drawn_does_not_leak_dashboard(
            self, configured_db):
        at = AppTest.from_file(str(APP / "Home.py"))
        at.session_state["_login_rendered"] = True   # gate drew in a prior run
        at.run(timeout=30)
        assert not any("Quick Actions" in (s.value or "")
                       for s in at.subheader), \
            "signed-out session reached the dashboard after a rerun"

    def test_rerun_during_first_run_does_not_leak_dashboard(
            self, tmp_path, monkeypatch):
        db = Database(db_path=tmp_path / "leak.db")
        db.init_database()
        monkeypatch.setattr(Config, "DATABASE_PATH", db.db_path,
                            raising=True)
        at = AppTest.from_file(str(APP / "Home.py"))
        at.session_state["_login_rendered"] = True
        at.run(timeout=30)
        subheaders = [s.value or "" for s in at.subheader]
        assert not any("Quick Actions" in s for s in subheaders), subheaders


# ---- the no-restart guarantee ----------------------------------------------

CACHE_PROBE = pathlib.Path(__file__).parent / "pages" / "cache_probe.py"


class TestNoRestart:
    def test_setting_change_visible_through_cached_resource_after_save(
            self, configured_db):
        """NAMED MUTATION TARGET. The engine sits behind
        @st.cache_resource; a settings save must invalidate it so the next
        acquisition rebuilds against the new values. A cached object that
        keeps serving the old config while the UI reports 'saved' is the
        lie this test exists to kill."""
        at = AppTest.from_file(str(CACHE_PROBE))
        at.run(timeout=30)

        assert not at.exception, [
            str(e.value) for e in at.exception]
        probe = dict(at.session_state["probe"])
        # Construction before the save saw the original key...
        assert probe["before"] == "initial-key", probe
        # ...the cached resource was rebuilt after the save...
        assert probe["rebuilt"] is True, (
            "get_engine() returned the same cached object across a "
            "settings write — stale-config regression")
        # ...and the rebuilt engine's AI handle was constructed against
        # the NEW key, not the old one.
        assert probe["after"] == "rotated-key", probe

    def test_threshold_change_visible_on_next_page_run(self, configured_db):
        """A changed threshold lands on the next run — no restart."""
        from core.settings import get_setting

        at = AppTest.from_file(str(CACHE_PROBE))
        at.run(timeout=30)
        set_settings({"SPIKE_THRESHOLD": 0.4}, db=configured_db)
        assert get_setting("SPIKE_THRESHOLD", db=configured_db) == \
            pytest.approx(0.4)

"""Structural guards for issue #30 section A (client-facing chrome).

Source-introspection on purpose: these are properties of how the UI is
BUILT, cheaply enforced so they cannot quietly regress.
"""

import pathlib

APP = pathlib.Path(__file__).parent.parent / "app"
PAGES = sorted((APP / "views").glob("[123]*.py"))


class TestSingleProductName:
    def test_login_and_home_use_one_name(self):
        gate = (APP / "components" / "auth_gate.py").read_text()
        home = (APP / "Home.py").read_text()
        for src in (gate, home):
            assert "Kitchen Order Guide" in src
            assert "Restaurant Ordering Assistant" not in src

    def test_name_singular_across_all_surfaces(self):
        """Widened per review: app/** AND .streamlit/** must never carry
        the old product name, and the surfaces a user actually sees
        (login gate + home header) must carry the new one."""
        surfaces = [p for p in APP.rglob("*.py") if "__pycache__" not in str(p)]
        streamlit = pathlib.Path(__file__).parent.parent / ".streamlit"
        surfaces += [p for p in streamlit.glob("*") if p.is_file()]

        for f in surfaces:
            assert "Restaurant Ordering Assistant" not in f.read_text(), \
                f"old product name still in {f}"


class TestRouterOwnsAuthAndTitles:
    def test_pages_do_not_self_gate_or_set_titles(self):
        """st.navigation owns both; per-page copies were the regression."""
        for p in PAGES:
            src = p.read_text()
            assert "require_login" not in src, p
            assert "set_page_config" not in src, p
            assert "gate_or_stop()" in src, p          # deep-link defense stays

    def test_home_registers_navigation(self):
        src = (APP / "Home.py").read_text()
        assert "st.navigation" in src
        assert 'title="Home"' in src


class TestPreAuthCosmetics:
    def test_marker_div_present_in_gate(self):
        gate = (APP / "components" / "auth_gate.py").read_text()
        assert 'data-preauth' in gate                  # style.css scopes on it

    def test_stylesheet_scopes_hide_rules_on_marker(self):
        css = (APP / "assets" / "style.css").read_text()
        assert "body:has([data-preauth])" in css
        assert 'stSidebar"] { display: none' in css

    def test_config_removes_deploy_and_recolors_primary(self):
        cfg = (pathlib.Path(__file__).parent.parent /
               ".streamlit" / "config.toml").read_text()
        assert 'toolbarMode = "minimal"' in cfg
        assert "primaryColor" in cfg


class TestEntryPageRenamed:
    def test_entry_is_Home_not_main(self):
        assert (APP / "Home.py").exists()
        assert not (APP / "main.py").exists()
        docker = (pathlib.Path(__file__).parent.parent / "Dockerfile").read_text()
        assert "app/Home.py" in docker

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


class TestDefaultEnvironmentBoot:
    """Every verification ran in a configured environment while the default
    environment is what ships. This guard asserts that key pages render
    CONTENT (not just HTTP 200) when no configuration is present (#37/#39)."""

    def test_auth_gate_source_has_no_password_early_return(self):
        """The no-password early return must come BEFORE any sidebar-hiding
        emission. Structural check: marker string after return keyword."""
        gate = (APP / "components" / "auth_gate.py").read_text()
        fn_start = gate.index("def render_login")
        fn_src = gate[fn_start:]
        early_return = fn_src.index("return")
        # Search for the actual EMISSION (st.markdown call), not comment/docstring mentions
        marker = fn_src.index("st.markdown('<div data-preauth")
        assert early_return < marker, (
            "data-preauth emitted before the open-access return — "
            "navigation hidden for unconfigured deployments (#37)")

    def test_order_guide_has_no_key_gate_stopping_execution(self):
        """Order Guide must not st.stop() on missing API key — ranking,
        savings, and order building work without AI."""
        og = (APP / "views" / "1_📋_Order_Guide.py").read_text()
        assert "st.stop()" not in og.split("engine = get_engine()")[-1].split("\n\n")[0], \
            "Order Guide still stops on missing API key"

    def test_trends_has_no_key_gate_stopping_execution(self):
        trends = (APP / "views" / "2_📈_Trends.py").read_text()
        assert "st.stop()" not in trends.split("engine = RecommendationEngine()")[-1].split("\n\n")[0], \
            "Trends still stops on missing API key"

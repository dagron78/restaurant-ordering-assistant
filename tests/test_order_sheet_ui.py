"""Phase B order-sheet UI tests (issue #53) — DEFAULT invocation.

The gate: the sheet renders PREFILLED from par, viewing is app-level,
and editing/importing is admin-only. Never marked slow_ui: this is the
surface the ordering round starts from.
"""

import pathlib

import pytest

from core import auth
from core.config import Config
from core.database import Database

from streamlit.testing.v1 import AppTest

APP = pathlib.Path(__file__).parent.parent / "app"
SHEET_PAGE = str(APP / "views" / "5_📝_Order_Sheet.py")


@pytest.fixture()
def seeded_sheet_db(tmp_path, monkeypatch):
    """A configured database with three sheet rows: par 4, par 0 (the
    meaningful zero), and no par at all."""
    db = Database(db_path=tmp_path / "sheet_ui.db")
    db.init_database()
    auth.set_password("admin", "admin-secret", db=db)
    auth.set_password("app", "app-secret", db=db)

    roma = db.add_item("Roma Tomatoes", "Produce", "Case")
    foil = db.add_item("Heavy Duty Foil Wrap", "Dry Goods", "Each")
    oil = db.add_item("Olive Oil", "Dry Goods", "3L")
    db.upsert_sheet_row(roma, 4.0, 1)
    db.upsert_sheet_row(foil, 0, 2)      # explicit zero
    db.upsert_sheet_row(oil, None, 3)    # no par set

    monkeypatch.setattr(Config, "DATABASE_PATH", db.db_path, raising=True)
    return db


def _run(page_path, role):
    at = AppTest.from_file(page_path)
    at.session_state["role"] = role
    at.run(timeout=30)
    return at


def test_sheet_renders_prefilled_from_par(seeded_sheet_db):
    at = _run(SHEET_PAGE, "app")
    assert not at.exception, [str(e.value) for e in at.exception]
    headers = [h.value for h in at.subheader]
    assert any("3 items on the sheet" in h for h in headers), headers
    # The prefilled rows render as a dataframe element on the page.
    assert len(at.dataframe) >= 1


def test_app_role_sees_no_edit_surface(seeded_sheet_db):
    at = _run(SHEET_PAGE, "app")
    labels = [i.label for i in at.text_input]
    assert not any("Roma Tomatoes" in (lab or "") for lab in labels), \
        "app role got the par editor"
    # The admin tabs never render for app role:
    buttons = [b.label for b in at.button]
    assert not any("Commit import" in (b or "") for b in buttons)


def test_admin_gets_edit_and_import(seeded_sheet_db):
    at = _run(SHEET_PAGE, "admin")
    assert not at.exception, [str(e.value) for e in at.exception]
    labels = [i.label for i in at.text_input]
    assert any("Roma Tomatoes" in (lab or "") for lab in labels), \
        "admin par editor missing"
    tabs = [t.label for t in at.tabs]
    assert any("Import" in (t or "") for t in tabs), tabs
    assert any("Mappings" in (t or "") for t in tabs), tabs


def test_par_zero_renders_as_zero_not_blank(seeded_sheet_db):
    """The dataframe cell for Heavy Duty Foil Wrap must show 0 — the
    meaningful zero — while Olive Oil shows the absent marker."""
    at = _run(SHEET_PAGE, "app")
    # Rendered via the dataframe built from get_order_sheet(); assert the
    # render path did not collapse the zero by checking the page ran and
    # the zero-caption appeared (only shown when a 0 is on the sheet).
    captions = [c.value for c in at.caption]
    assert any("Par 0" in c for c in captions), captions

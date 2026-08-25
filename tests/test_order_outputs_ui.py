"""Phase D outputs, in the app — DEFAULT invocation (issue #57).

A stored order has to be placeable: read aloud to a rep, pasted into a mail
client, or printed. And reachable again later — a manager cut off mid-call
needs the same call sheet back, not a rebuilt one.

Named mutation targets:
- test_history_renders_call_sheet_for_each_stored_vendor
      mutant: group by the engine's pick instead of the stored vendor -> dies.
- test_history_figures_are_as_confirmed_not_live
      mutant: rebuild outputs from live prices -> dies.
"""
import pathlib

import pytest
from streamlit.testing.v1 import AppTest

from core import auth
from core.config import Config
from core.database import Database

APP = pathlib.Path(__file__).parent.parent / "app"
HISTORY_PAGE = str(APP / "views" / "6_📚_Order_History.py")


@pytest.fixture()
def placed_db(tmp_path, monkeypatch):
    """A confirmed order: one engine pick, one deliberate manager override
    onto the DEARER vendor."""
    db = Database(db_path=tmp_path / "outputs_ui.db")
    db.init_database()
    auth.set_password("admin", "admin-secret", db=db)
    auth.set_password("app", "app-secret", db=db)

    toms = db.add_item("Roma Tomatoes", "Produce", "Case")
    foil = db.add_item("Heavy Duty Foil Wrap", "Dry Goods", "Each")
    sysco = db.get_or_create_vendor("Sysco")
    usf = db.get_or_create_vendor("US Foods")
    db.add_price("Roma Tomatoes", "Sysco", 22.00, "Case")
    db.add_price("Roma Tomatoes", "US Foods", 25.00, "Case")
    db.add_price("Heavy Duty Foil Wrap", "Sysco", 8.00, "Each")
    db.add_price("Heavy Duty Foil Wrap", "US Foods", 10.50, "Each")

    result = db.create_order([
        {"item_id": toms, "vendor_id": sysco, "quantity": 4,
         "unit_price": 22.00, "unit": "Case", "chosen_by": "engine"},
        {"item_id": foil, "vendor_id": usf, "quantity": 2,
         "unit_price": 10.50, "unit": "Each", "chosen_by": "manager"},
    ], status="completed")

    monkeypatch.setattr(Config, "DATABASE_PATH", db.db_path, raising=True)
    db.order_id = result["order_id"]
    return db


def _open_history(role="app"):
    at = AppTest.from_file(HISTORY_PAGE)
    at.session_state["role"] = role
    at.run(timeout=45)
    return at


def _all_text(at) -> str:
    parts = []
    for attr in ("markdown", "code", "caption", "title", "subheader", "info",
                 "warning", "success", "text"):
        parts += [str(getattr(e, "value", "")) for e in getattr(at, attr, [])]
    return "\n".join(parts)


def test_history_page_opens_without_exception(placed_db):
    at = _open_history()
    assert not at.exception, [str(e) for e in at.exception]


def test_history_renders_call_sheet_for_each_stored_vendor(placed_db):
    """NAMED MUTATION TARGET. The foil was taken from US Foods deliberately;
    grouping it under the engine's cheaper Sysco pick misdirects the call."""
    text = _all_text(_open_history())
    assert "CALL SHEET" in text
    assert "Roma Tomatoes" in text and "Heavy Duty Foil Wrap" in text
    # the dearer, manager-chosen price is the one that must appear
    assert "10.50" in text


def test_history_figures_are_as_confirmed_not_live(placed_db):
    """NAMED MUTATION TARGET. Rebuild from live prices and this dies: the
    manager approved 10.50, and the market moving afterwards is irrelevant."""
    placed_db.add_price("Heavy Duty Foil Wrap", "US Foods", 4.00, "Each")
    text = _all_text(_open_history())
    assert "10.50" in text
    assert "4.00" not in text


def test_history_states_that_prices_were_not_requeried(placed_db):
    assert "as confirmed" in _all_text(_open_history())

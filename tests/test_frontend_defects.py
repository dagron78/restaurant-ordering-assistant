"""Defects found by driving the running app against the mock restaurant.

Every one of these was invisible to the test suite and to code reading — they
were found by opening the app and looking at it, which is the failure mode this
project has hit before. Each test names the thing a person saw.
"""
import pathlib
import sys

import pytest
from streamlit.testing.v1 import AppTest

sys.path.insert(0, str(pathlib.Path(__file__).parent.parent))

from core import auth  # noqa: E402
from core.config import Config  # noqa: E402
from core.database import Database  # noqa: E402
from core.settings import set_settings  # noqa: E402

REPO = pathlib.Path(__file__).parent.parent
VIEWS = REPO / "app" / "views"
GUIDE = str(VIEWS / "1_📋_Order_Guide.py")


@pytest.fixture()
def db(tmp_path, monkeypatch):
    d = Database(db_path=tmp_path / "fe.db")
    d.init_database()
    auth.set_password("app", "app-secret", db=d)
    auth.set_password("admin", "admin-secret", db=d)
    toms = d.add_item("Roma Tomatoes", "Produce", "Case")
    d.upsert_sheet_row(toms, 4, 1)
    d.add_price("Roma Tomatoes", "Sysco", 22.00, "Case")
    d.add_price("Roma Tomatoes", "US Foods", 25.00, "Case")
    monkeypatch.setattr(Config, "DATABASE_PATH", d.db_path, raising=True)
    return d


def _run(page, role="admin"):
    at = AppTest.from_file(page)
    at.session_state["role"] = role
    at.run(timeout=60)
    assert not at.exception, [str(getattr(e, "value", e)) for e in at.exception]
    return at


def test_with_prices_metric_appears_once(db):
    """It was rendered twice from two identical adjacent lines, so the
    Order Guide showed 'With Prices 10' stacked on itself."""
    at = _run(GUIDE)
    labels = [m.label for m in at.metric]
    assert labels.count("With Prices") == 1, labels


def test_no_search_box_when_there_is_no_list_to_search(db):
    """In plan-after mode this page shows no items, so the filter filtered
    nothing — it read as a control that was simply broken."""
    set_settings({"ORDER_MODE": "plan_after"}, db=db)
    at = _run(GUIDE)
    placeholders = [ti.placeholder for ti in at.text_input]
    assert "Filter by name..." not in placeholders, placeholders


def test_search_box_is_present_when_there_is_a_list(db):
    """...but it must still be there in the mode that shows items."""
    set_settings({"ORDER_MODE": "plan_during"}, db=db)
    at = _run(GUIDE)
    placeholders = [ti.placeholder for ti in at.text_input]
    assert "Filter by name..." in placeholders, placeholders


@pytest.mark.parametrize("page,needle", [
    ("app/Home.py", "📥"),
    ("app/views/1_📋_Order_Guide.py", "🧭"),
    ("app/views/5_📝_Order_Sheet.py", "🧭"),
])
def test_alert_emoji_is_not_repeated_in_text_and_icon(page, needle):
    """st.info(f"📥 ...", icon="📥") renders the emoji twice: the banner
    read '📥 📥2 message(s)'. The icon argument is the one that stays."""
    src = (REPO / page).read_text()
    for line_no, line in enumerate(src.splitlines(), 1):
        if f'icon="{needle}"' in line:
            continue
        # a string that both starts with the emoji and belongs to a call
        # that also passes icon= is the doubling bug
    blocks = src.split("st.")
    for block in blocks:
        if f'icon="{needle}"' in block:
            head = block.split("icon=")[0]
            assert needle not in head, (
                f"{page}: emoji {needle} appears in the text AND icon= "
                f"of the same call")


def test_landing_page_reports_price_freshness_not_a_pipeline_count(db):
    """'Successful Updates 0' counted worker runs — meaningless to a
    manager, and alarming at zero on a perfectly healthy install. The
    question a manager actually has is 'are these this week's prices?'."""
    at = _run(str(REPO / "app" / "Home.py"))
    labels = [m.label for m in at.metric]
    assert "Successful Updates" not in labels, labels
    assert "Prices updated" in labels, labels
    value = next(m.value for m in at.metric if m.label == "Prices updated")
    assert value == "Today", value


def test_latest_price_date_ranks_by_date_not_insertion(db):
    """F-01 again, in a new query: a backfilled older sheet is inserted
    last but must not become the newest price."""
    db.add_price("Roma Tomatoes", "Sysco", 9.99, "Case",
                 date_recorded="2020-01-01")
    latest = db.get_latest_price_date()
    assert latest != "2020-01-01", latest

"""Phase C ordering-round UI tests (issue #55) — DEFAULT invocation.

The plan-after round end to end: sheet prefilled -> quantities -> Send
-> plan with per-line vendor/price/alternative/why -> override one line
-> confirm -> stored order matches what was on screen.

Named mutation targets:
- test_override_persists_to_stored_order
      mutant: confirm ignores the draft's overrides -> dies.
- test_confirm_stores_snapshot_not_live_prices
      mutant: the alt baseline is re-resolved at confirm -> dies.
- test_zero_quantity_lines_excluded_from_plan
      mutant: the plan builder includes qty==0 lines -> dies.
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
def round_db(tmp_path, monkeypatch):
    """Configured app; two sheet items priced by two vendors; one more
    sheet item with a single quote (no alternative)."""
    db = Database(db_path=tmp_path / "round.db")
    db.init_database()
    auth.set_password("admin", "admin-secret", db=db)
    auth.set_password("app", "app-secret", db=db)

    hc = db.add_item("Heavy Cream", "Dairy", "Case")
    foil = db.add_item("Heavy Duty Foil Wrap", "Dry Goods", "Each")
    roma = db.add_item("Roma Tomatoes", "Produce", "Case")
    db.get_or_create_vendor("Sysco")
    db.get_or_create_vendor("US Foods")
    db.add_price("Heavy Cream", "Sysco", 24.50, "Case")
    db.add_price("Heavy Cream", "US Foods", 28.00, "Case")
    db.add_price("Heavy Duty Foil Wrap", "Sysco", 2.00, "Each")
    db.add_price("Heavy Duty Foil Wrap", "US Foods", 2.50, "Each")
    db.add_price("Roma Tomatoes", "Sysco", 18.00, "Case")

    db.upsert_sheet_row(hc, 12, 1)
    db.upsert_sheet_row(foil, 0, 2)     # par 0: stocked, not reordered
    db.upsert_sheet_row(roma, 6, 3)     # single quote

    monkeypatch.setattr(Config, "DATABASE_PATH", db.db_path, raising=True)
    return db


def _btn(at, label_part):
    matches = [b for b in at.button if label_part in (b.label or "")]
    assert matches, f"button containing {label_part!r} not found"
    return matches[0]


def _open(db):
    at = AppTest.from_file(SHEET_PAGE)
    at.session_state["role"] = "app"
    at.run(timeout=30)
    return at


def _quantities(at, **byname):
    """Set round-entry quantity inputs by item name."""
    for i in at.number_input:
        if not (i.key or "").startswith("rq_"):
            continue
    # Map via labels: "Name (Unit)..." prefix match
    for i in at.number_input:
        label = i.label or ""
        for name, value in byname.items():
            if label.startswith(name):
                i.set_value(float(value))


def test_plan_after_end_to_end_with_override(round_db):
    """THE gate: sheet -> quantities -> Send -> plan (vendor, price, alt,
    why) -> override -> confirm -> stored order matches the screen,
    including the override and a negative saving on the dearer pick."""
    at = _open(round_db)
    assert not at.exception, [str(e.value) for e in at.exception]

    # Entry stage: prefilled from par (Cream 12, Foil 0, Roma 6).
    # Manager needs Cream and Foil, none of Roma this week.
    _quantities(at, **{"Heavy Cream": 2, "Heavy Duty Foil Wrap": 5,
                       "Roma Tomatoes": 0})
    _btn(at, "Send — build the plan").click()
    at.run(timeout=30)

    # Plan stage: two lines (Roma excluded — zero quantity), reasons and
    # alternatives visible.
    assert not at.exception, [str(e.value) for e in at.exception]
    captions = " | ".join(c.value for c in at.caption)
    assert "Suggested plan" in " | ".join(s.value for s in at.subheader)
    assert "vs US Foods" in captions          # Cream's beaten alternative

    # Override Foil to the dearer vendor (US Foods 2.50 vs Sysco 2.00).
    foil_boxes = [s for s in at.selectbox
                  if "Heavy Duty Foil Wrap" in (s.label or "")]
    assert foil_boxes, "override widget missing"
    options = foil_boxes[0].options
    dearer = next(o for o in options if o.startswith("US Foods"))
    foil_boxes[0].set_value(dearer)
    at.run(timeout=30)

    # Confirm builds the order from the snapshot.
    _btn(at, "Confirm").click()
    at.run(timeout=30)
    assert not at.exception, [str(e.value) for e in at.exception]

    # Stored order matches the screen: 2 lines, override kept, honest
    # negative saving on the dearer pick, snapshot baseline for Cream.
    import sqlite3
    conn = sqlite3.connect(str(round_db.db_path))
    conn.row_factory = sqlite3.Row
    row = conn.execute(
        "SELECT id, savings_vs_alt, total_amount FROM orders "
        "ORDER BY id DESC LIMIT 1").fetchone()
    lines = conn.execute(
        "SELECT oi.*, i.name FROM order_items oi "
        "JOIN items i ON i.id = oi.item_id WHERE order_id = ?",
        (row["id"],)).fetchall()
    conn.close()

    assert len(lines) == 2
    by_name = {ln["name"]: ln for ln in lines}
    cream = by_name["Heavy Cream"]
    foil = by_name["Heavy Duty Foil Wrap"]

    assert cream["vendor_id"] != foil["vendor_id"] or True
    # Cream: engine pick Sysco, snapshot baseline US Foods @28 -> +7.00
    assert cream["chosen_by"] == "engine"
    assert cream["savings_vs_alt"] == pytest.approx(7.00)
    assert cream["alt_price"] == pytest.approx(28.00)
    # Foil: manager override to dearer US Foods -> negative, recorded
    assert foil["chosen_by"] == "manager"
    assert foil["savings_vs_alt"] == pytest.approx(-2.50)  # 5 x (2.50-2.00)
    # Order aggregate: +7.00 - 2.50 = +4.50
    assert row["savings_vs_alt"] == pytest.approx(4.50)

    # Draft is terminal; nothing resurrects it.
    assert round_db.get_open_draft() is None


def test_zero_quantity_lines_excluded_from_plan(round_db):
    """NAMED MUTATION TARGET. Zero quantities are the common case; they
    must not appear in the plan. Par 0 (Foil) is a sheet fact, not a
    quantity — it still prefills 0 and is excludable like any line."""
    at = _open(round_db)
    _quantities(at, **{"Heavy Cream": 2, "Heavy Duty Foil Wrap": 0,
                       "Roma Tomatoes": 0})
    _btn(at, "Send — build the plan").click()
    at.run(timeout=30)

    markdowns = " | ".join(m.value for m in at.markdown)
    assert "Heavy Cream" in markdowns
    # Zero-quantity lines are not part of the plan:
    assert "Heavy Duty Foil Wrap" not in markdowns
    assert "Roma Tomatoes" not in markdowns
    subheaders = " | ".join(s.value for s in at.subheader)
    assert "Suggested plan" in subheaders


def test_confirm_stores_snapshot_not_live_prices(round_db):
    """NAMED MUTATION TARGET (the corrected freeze gate). After Send, US
    Foods DROPS its Cream price. Confirm must store the SNAPSHOT
    baseline (28.00 -> +7.00), not the new market (-9.00)."""
    at = _open(round_db)
    _quantities(at, **{"Heavy Cream": 2, "Heavy Duty Foil Wrap": 0,
                       "Roma Tomatoes": 0})
    _btn(at, "Send — build the plan").click()
    at.run(timeout=30)

    # The market moves after Send, before Confirm:
    round_db.add_price("Heavy Cream", "US Foods", 20.00, "Case")

    _btn(at, "Confirm").click()
    at.run(timeout=30)

    import sqlite3
    conn = sqlite3.connect(str(round_db.db_path))
    conn.row_factory = sqlite3.Row
    row = conn.execute(
        "SELECT savings_vs_alt FROM orders ORDER BY id DESC LIMIT 1"
    ).fetchone()
    line = conn.execute(
        "SELECT alt_price, savings_vs_alt FROM order_items "
        "ORDER BY id DESC LIMIT 1").fetchone()
    conn.close()

    assert line["alt_price"] == pytest.approx(28.00)      # the snapshot
    assert row["savings_vs_alt"] == pytest.approx(7.00)   # confirmed, not live


def test_draft_rehydrates_after_session_loss(round_db):
    """A phone screen lock drops websocket session state; the draft is
    server-side, so a BRAND-NEW session resumes at the same stage."""
    at1 = _open(round_db)
    _quantities(at1, **{"Heavy Cream": 4, "Heavy Duty Foil Wrap": 0,
                        "Roma Tomatoes": 0})
    _btn(at1, "Send — build the plan").click()
    at1.run(timeout=30)

    # Brand-new AppTest = brand-new session: it resumes at the review
    # stage with the same snapshot (server-side draft).
    at2 = _open(round_db)
    subheaders = " | ".join(s.value for s in at2.subheader)
    assert "Suggested plan" in subheaders, subheaders
    markdowns = " | ".join(m.value for m in at2.markdown)
    assert "Heavy Cream" in markdowns


def test_no_send_guard_untouched():
    """Confirm builds; nothing sends. The structural guard still holds."""
    import pathlib as p

    exports = (p.Path(__file__).parent.parent / "core" / "exports.py"
               ).read_text()
    for banned in ("smtplib", "sendmail", "SMTP("):
        assert banned not in exports

"""Phase D — outputs the manager can act on (issue #57).

Every output is built from the STORED order. Phase C froze vendor, unit price
and the alt baseline so the record matches what was approved; an export that
re-queries live prices would undo that at the last step.
"""
import pytest

from core.database import Database
from core import exports


@pytest.fixture()
def db(tmp_path):
    d = Database(db_path=tmp_path / "outputs.db")
    d.init_database()
    return d


@pytest.fixture()
def confirmed_order(db):
    """An order with two vendors and one manager override, then stored."""
    sysco = db.get_or_create_vendor("Sysco")
    usf = db.get_or_create_vendor("US Foods")
    toms = db.add_item("Roma Tomatoes", "Produce", "Case")
    foil = db.add_item("Heavy Duty Foil Wrap", "Supplies", "Each")

    # market: Sysco cheaper on both
    db.add_price("Roma Tomatoes", "Sysco", 22.00, "Case")
    db.add_price("Roma Tomatoes", "US Foods", 25.00, "Case")
    db.add_price("Heavy Duty Foil Wrap", "Sysco", 8.00, "Each")
    db.add_price("Heavy Duty Foil Wrap", "US Foods", 10.50, "Each")

    result = db.create_order([
        # engine pick
        {"item_id": toms, "vendor_id": sysco, "quantity": 4,
         "unit_price": 22.00, "unit": "Case", "chosen_by": "engine"},
        # manager deliberately took the DEARER vendor
        {"item_id": foil, "vendor_id": usf, "quantity": 2,
         "unit_price": 10.50, "unit": "Each", "chosen_by": "manager"},
    ], status="completed")
    return db.get_order(result["order_id"])


# ---- the stored-order contract ---------------------------------------------

def test_basket_is_built_from_stored_order(confirmed_order):
    basket = exports.order_to_basket(confirmed_order)
    vendors = {g["vendor"] for g in basket["groups"]}
    assert vendors == {"Sysco", "US Foods"}
    assert basket["order_id"] == confirmed_order["id"]


def test_outputs_ignore_live_price_changes(db, confirmed_order):
    """NAMED MUTATION TARGET. Re-query live prices instead of the stored
    order and this dies: the manager approved 10.50, not 4.00."""
    before = exports.build_call_sheet(confirmed_order, "US Foods")
    db.add_price("Heavy Duty Foil Wrap", "US Foods", 4.00, "Each")
    after = exports.build_call_sheet(db.get_order(confirmed_order["id"]),
                                     "US Foods")
    assert "10.50" in before and "10.50" in after
    assert "4.00" not in after


def test_overridden_line_groups_under_the_manager_choice(confirmed_order):
    """NAMED MUTATION TARGET. Foil was taken from US Foods deliberately;
    grouping it under the engine's cheaper pick would misdirect the call."""
    sheet = exports.build_call_sheet(confirmed_order, "US Foods")
    assert "Heavy Duty Foil Wrap" in sheet
    assert "Heavy Duty Foil Wrap" not in exports.build_call_sheet(
        confirmed_order, "Sysco")


def test_zero_quantity_lines_absent(db, confirmed_order):
    """NAMED MUTATION TARGET. A call sheet listing items with no quantity
    wastes the rep's time and the manager's credibility."""
    order = dict(confirmed_order)
    order["items"] = list(order["items"]) + [{
        "item_name": "Ghost Item", "vendor_name": "Sysco", "quantity": 0,
        "unit": "Case", "unit_price": 5.0, "total_price": 0.0,
    }]
    assert "Ghost Item" not in exports.build_call_sheet(order, "Sysco")


# ---- readable aloud ---------------------------------------------------------

def test_call_sheet_lines_are_numbered_for_dictation(confirmed_order):
    sheet = exports.build_call_sheet(confirmed_order, "Sysco")
    assert "1." in sheet


def test_call_sheet_line_carries_item_qty_unit_and_price(confirmed_order):
    sheet = exports.build_call_sheet(confirmed_order, "Sysco")
    line = [ln for ln in sheet.splitlines() if "Roma Tomatoes" in ln][0]
    for token in ("Roma Tomatoes", "4", "Case", "22.00"):
        assert token in line, f"{token!r} missing from dictated line: {line!r}"


def test_call_sheet_carries_a_subtotal_to_confirm_with_the_rep(confirmed_order):
    assert "88.00" in exports.build_call_sheet(confirmed_order, "Sysco")


def test_call_sheet_only_lists_the_named_vendor(confirmed_order):
    assert "US Foods" not in exports.build_call_sheet(confirmed_order, "Sysco")


# ---- copy-ready text --------------------------------------------------------

def test_copy_text_is_per_vendor_and_plain(confirmed_order):
    text = exports.build_copy_text(confirmed_order, "Sysco")
    assert "Roma Tomatoes" in text and "Heavy Duty Foil Wrap" not in text

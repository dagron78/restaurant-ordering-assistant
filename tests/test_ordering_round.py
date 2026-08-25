"""Phase C ordering-round core tests (issue #55) — DEFAULT invocation.

Named mutation targets (see PR body):
- test_supplied_baseline_stored_not_reresolved
      a.k.a. the freeze test: change the ALTERNATIVE vendor's price
      between Send and Confirm; the stored savings must match the plan
      snapshot, not the live market. Mutant: create_order re-resolves a
      supplied baseline -> dies.
- test_chosen_by_records_manager_override
      Mutant: create_order ignores chosen_by -> dies.
- test_zero_quantity_lines_excluded_from_plan
      Mutant: plan builder includes qty==0 lines -> dies.

create_order's Phase 2 behaviour is unchanged for callers that do not
supply a baseline: existing tests (test_savings*, three-vendor, parity)
are the guard.
"""

import importlib

import pytest

from core.database import Database, pick_cheapest_alternative

plan_mod = importlib.import_module("core.plan")


@pytest.fixture()
def db(tmp_path):
    database = Database(db_path=tmp_path / "plan.db")
    database.init_database()
    return database


@pytest.fixture()
def priced_world(db):
    """Heavy Cream quoted by two vendors; Roma by one only.

    Sysco 24.50 / US Foods 28.00 on Heavy Cream — Sysco cheaper, alt
    baseline 28.00. Roma: Sysco only (no alternative -> excluded)."""
    hc = db.add_item("Heavy Cream", "Dairy", "Case")
    roma = db.add_item("Roma Tomatoes", "Produce", "Case")
    sysco = db.get_or_create_vendor("Sysco")
    usf = db.get_or_create_vendor("US Foods")
    db.add_price("Heavy Cream", "Sysco", 24.50, "Case")
    db.add_price("Heavy Cream", "US Foods", 28.00, "Case")
    db.add_price("Roma Tomatoes", "Sysco", 18.00, "Case")
    return {"db": db, "hc": hc, "roma": roma,
            "sysco": sysco, "usf": usf}


# ---- the freeze gate --------------------------------------------------------

def test_supplied_baseline_stored_not_reresolved(priced_world, db):
    """NAMED MUTATION TARGET (the corrected freeze gate). The plan
    snapshot said: Sysco 24.50, alt = US Foods @ 28.00 -> saves 3.50/case.
    US Foods then DROPS to 20.00 before confirm. The stored order must
    record the confirmed savings (vs 28.00), not the live market
    (vs 20.00 would show a negative). The market has ALREADY moved when
    create_order runs — that is what makes the test discriminate a
    stored snapshot from a live re-resolution."""
    # The market moves after Send, before Confirm:
    db.add_price("Heavy Cream", "US Foods", 20.00, "Case")

    line = {"item_id": priced_world["hc"], "vendor_id": priced_world["sysco"],
            "quantity": 2, "unit": "Case", "unit_price": 24.50,
            "alt_vendor_id": priced_world["usf"], "alt_price": 28.00}
    result = db.create_order([line], status="completed")
    order = db.get_order(result["order_id"])
    assert order["savings_vs_alt"] == pytest.approx(7.00)   # 2 x (28 - 24.50)

    # The same call WITHOUT a supplied baseline re-resolves live:
    live = dict(line)
    live.pop("alt_vendor_id"), live.pop("alt_price")
    result2 = db.create_order([live], status="completed")
    order2 = db.get_order(result2["order_id"])
    assert order2["savings_vs_alt"] == pytest.approx(-9.00)  # 2 x (20 - 24.50)


def test_chosen_by_records_manager_override(priced_world, db):
    """NAMED MUTATION TARGET. The manager deliberately picks the dearer
    vendor: the line records chosen_by='manager' and a NEGATIVE saving —
    never silently re-optimised."""
    line = {"item_id": priced_world["hc"], "vendor_id": priced_world["usf"],
            "quantity": 1, "unit": "Case", "unit_price": 28.00,
            "chosen_by": "manager"}
    result = db.create_order([line], status="completed")
    order = db.get_order(result["order_id"])
    line_row = order["items"][0]
    assert line_row["chosen_by"] == "manager"
    assert line_row["vendor_id"] == priced_world["usf"]
    assert order["savings_vs_alt"] == pytest.approx(-3.50)  # dearer on purpose


def test_chosen_by_defaults_to_engine(priced_world, db):
    line = {"item_id": priced_world["hc"], "vendor_id": priced_world["sysco"],
            "quantity": 1, "unit_price": 24.50}
    result = db.create_order([line], status="completed")
    assert db.get_order(result["order_id"])["items"][0]["chosen_by"] == \
        "engine"


def test_chosen_by_rejects_unknown_value(priced_world, db):
    line = {"item_id": priced_world["hc"], "vendor_id": priced_world["sysco"],
            "quantity": 1, "unit_price": 24.50, "chosen_by": "vendor_app"}
    with pytest.raises(ValueError):
        db.create_order([line], status="completed")


# ---- drafts -----------------------------------------------------------------

def test_draft_survives_and_never_resurrects(db):
    """The screen-lock answer: the draft is server-side. And a CONFIRMED
    draft is terminal — never silently reopened by a later save."""
    draft_id = db.save_draft({"quantities": {"Heavy Cream": 2}},
                             status="entering")
    got = db.get_open_draft()
    assert got["id"] == draft_id
    assert got["payload"]["quantities"]["Heavy Cream"] == 2

    # A second open draft replaces the first (one open draft, deliberate):
    db.save_draft({"quantities": {"Heavy Cream": 5}}, status="plan_ready")
    got = db.get_open_draft()
    assert got["payload"]["quantities"]["Heavy Cream"] == 5

    # Confirm is terminal:
    db.confirm_draft(got["id"])
    assert db.get_open_draft() is None
    confirmed = db.get_draft(got["id"])
    assert confirmed["status"] == "confirmed"
    assert confirmed["payload"]["quantities"]["Heavy Cream"] == 5


# ---- plan builder -----------------------------------------------------------

def test_plan_builder_snapshots_lines_and_skips_zero(db, priced_world):
    """NAMED MUTATION TARGET. Only lines with quantity enter the plan;
    each line snapshots vendor, unit_price AND the alt baseline."""
    db.upsert_sheet_row(priced_world["hc"], 12, 1)
    db.upsert_sheet_row(priced_world["roma"], 6, 2)

    quantities = {"Heavy Cream": 3, "Roma Tomatoes": 0}   # Roma not needed
    plan = plan_mod.build_plan(db, quantities)

    assert [ln["name"] for ln in plan["lines"]] == ["Heavy Cream"]
    line = plan["lines"][0]
    assert line["vendor"] == "Sysco"
    assert line["unit_price"] == pytest.approx(24.50)
    assert line["alt_vendor"] == "US Foods"
    assert line["alt_price"] == pytest.approx(28.00)
    assert line["chosen_by"] == "engine"
    assert line["quantity"] == 3


def test_plan_builder_unpriced_item_flagged_not_dropped(db, priced_world):
    """An item with no prices at all must be VISIBLE as unorderable,
    never silently missing from the plan."""
    db.add_item("Ghost Pepper", "Produce", "Each")
    plan = plan_mod.build_plan(db, {"Ghost Pepper": 2, "Heavy Cream": 1})
    assert plan["lines"][0]["name"] == "Heavy Cream"
    assert any("Ghost Pepper" in u for u in plan["unpriced"])


def test_pick_cheapest_alternative_still_the_single_definition(priced_world):
    prices = [{"vendor": "Sysco", "vendor_id": 1, "price": 24.50},
              {"vendor": "US Foods", "vendor_id": 2, "price": 28.00}]
    alt = pick_cheapest_alternative(prices, "Sysco")
    assert alt["vendor"] == "US Foods"
    assert pick_cheapest_alternative(prices, "US Foods")["vendor"] == "Sysco"
    assert pick_cheapest_alternative(prices[:1], "Sysco") is None

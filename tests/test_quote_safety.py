"""Purchasing regressions: comparable quantities, fresh quotes, frozen savings."""

from datetime import date, timedelta

import pytest

from core.plan import build_plan
from core.quotes import eligible_quotes, price_factor
from core.settings import set_settings


@pytest.mark.parametrize("source,target,factor", [
    ("LBS", "pound", 1), ("oz", "lb", 16), ("g", "kg", 1000),
    ("ml", "liter", 1000), ("Case", "cs", 1),
    ("Case (6 x 1 lb)", "6 x 16 oz", 1),
    ("Case (6 x 1 lb)", "Case (12 x 1 lb)", None),
    ("Case (6 x 1 lb)", "Case (3 x 2 lb)", None),
    ("Case", "Lb", None), ("Lb", "Case", None),
    ("Case", "Case (6 x 1 lb)", None), ("", "Each", None),
    ("lb", "liter", None),
])
def test_units_and_explicit_pack_contents(source, target, factor):
    result = price_factor(source, target)
    if factor is None:
        assert result is None
    else:
        assert result == pytest.approx(factor)


def test_two_cases_never_become_two_pounds(db):
    db.add_item("Tomatoes", "Produce", "Case")
    db.add_price("Tomatoes", "Sysco", 20, "Case")
    db.add_price("Tomatoes", "US Foods", 2, "Lb")
    plan = build_plan(db, {"Tomatoes": 2})
    line = plan["lines"][0]
    assert (line["vendor"], line["quantity"], line["unit"]) == ("Sysco", 2, "Case")
    assert line["alt_price"] is None
    assert "unit/pack" in plan["warnings"][0]
    result = db.create_order(plan["lines"], status="completed")
    order = db.get_order(result["order_id"])
    assert order["total_amount"] == 40
    assert order["lines_without_alt"] == 1
    assert order["savings_vs_alt"] == 0


def test_normalized_weight_prices_and_savings(db):
    db.add_item("Rice", "Dry Goods", "Lb")
    db.add_price("Rice", "Sysco", 2, "Lb")
    db.add_price("Rice", "US Foods", .20, "oz")
    line = build_plan(db, {"Rice": 2})["lines"][0]
    assert line["vendor"] == "Sysco"
    assert line["alt_price"] == pytest.approx(3.20)
    assert line["unit"] == "Lb"
    order = db.get_order(db.create_order([line])["order_id"])
    assert order["savings_vs_alt"] == pytest.approx(2.40)


def test_stale_quote_excluded_from_plan_override_and_database_baseline(db):
    from app.components.vendor_override import item_options

    db.add_item("Cream", "Dairy", "Case")
    db.add_price("Cream", "Sysco", 10, "Case", date_recorded="2020-01-01")
    db.add_price("Cream", "US Foods", 20, "Case")
    plan = build_plan(db, {"Cream": 1})
    assert plan["lines"][0]["vendor"] == "US Foods"
    assert plan["lines"][0]["alt_price"] is None
    assert "days old" in plan["warnings"][0]
    assert [q["vendor"] for q in item_options(db, "Cream", "US Foods")] == ["US Foods"]
    assert db.get_cheapest_alternative("Cream", "US Foods") is None


def test_quote_age_boundary_invalid_dates_and_config(db):
    today = date.today()
    quotes = [{"vendor": str(days), "price": 10, "unit": "Case",
               "date_recorded": (today - timedelta(days=days)).isoformat()}
              for days in (14, 15, -1)]
    quotes.append({"vendor": "Missing", "price": 10, "unit": "Case"})
    good, bad = eligible_quotes(quotes, "Case", 14, today)
    assert [q["vendor"] for q in good] == ["14"]
    assert len(bad) == 3
    db.add_item("Cream", "Dairy", "Case")
    db.add_price("Cream", "Sysco", 10, "Case", date_recorded=quotes[1]["date_recorded"])
    assert build_plan(db, {"Cream": 1})["unpriced"] == ["Cream"]
    set_settings({"MAX_QUOTE_AGE_DAYS": 16}, db=db)
    assert build_plan(db, {"Cream": 1})["lines"]
    with pytest.raises(ValueError):
        set_settings({"MAX_QUOTE_AGE_DAYS": 0}, db=db)


def test_absent_alternative_stays_absent_after_new_quote(db):
    db.add_item("Cream", "Dairy", "Case")
    db.add_price("Cream", "Sysco", 10, "Case")
    line = build_plan(db, {"Cream": 2})["lines"][0]
    db.add_price("Cream", "US Foods", 30, "Case")
    result = db.create_order([line])
    order = db.get_order(result["order_id"])
    assert order["items"][0]["alt_price"] is None
    assert order["savings_vs_alt"] == 0


def test_autosave_cannot_replace_a_plan_in_review(db):
    db.save_draft({"lines": [], "quantities": {"Cream": 3}}, "plan_ready")
    assert not db.save_entry_quantities({"Cream": 12})
    assert db.get_open_draft()["payload"]["quantities"] == {"Cream": 3}


def test_historical_averages_and_charts_use_ordering_units(db):
    db.add_item("Rice", "Dry Goods", "Lb")
    yesterday = (date.today() - timedelta(days=1)).isoformat()
    db.add_price("Rice", "Sysco", .20, "oz", date_recorded=yesterday)
    db.add_price("Rice", "US Foods", 2, "Lb")
    db.add_price("Rice", "Other", 100, "Case")
    assert db.get_vendor_trend_baseline("Rice", "Sysco") == pytest.approx(3.2)
    assert db.get_item_market_average("Rice") == pytest.approx(2.6)
    rice = next(i for i in db.get_all_items_with_prices() if i["name"] == "Rice")
    assert rice["avg_price"] == pytest.approx(2.6)
    assert [p["price"] for p in db.get_price_history("Rice")] == pytest.approx([3.2, 2])

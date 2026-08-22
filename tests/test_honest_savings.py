"""Phase 2 money-math spec (issue #17): savings measured against the
CHEAPEST alternative vendor — min over others, never max (F-22's basis),
never an average. N-vendor correct from day one; a two-vendor special case
would pass every test here and break the moment vendor #3 lands.

create_order resolves baselines internally at write time and returns
{order_id, lines_excluded, lines_total}. Lines with zero other vendors
quoting are excluded and counted, never folded in at zero. Negative
savings (a dearer vendor chosen anyway) are preserved unclamped.
"""

import pytest

from core.database import Database, pick_cheapest_alternative


class FakeAI:
    pass


def make_line(item_id, vendor_id, unit_price, qty=1, unit="Each"):
    return {"item_id": item_id, "vendor_id": vendor_id,
            "quantity": qty, "unit_price": unit_price, "unit": unit}


class TestCheapestAlternativePure:
    """The single definition of 'the option you forwent'."""

    def test_min_over_others(self):
        prices = [
            {"vendor": "Sysco", "vendor_id": 1, "price": 20.0},
            {"vendor": "US Foods", "vendor_id": 2, "price": 22.0},
            {"vendor": "Gfs", "vendor_id": 3, "price": 25.0},
        ]
        alt = pick_cheapest_alternative(prices, "Sysco")
        assert alt == {"vendor_id": 2, "vendor": "US Foods", "price": 22.0}

    def test_excludes_chosen_vendor(self):
        prices = [{"vendor": "Sysco", "vendor_id": 1, "price": 5.0}]
        assert pick_cheapest_alternative(prices, "Sysco") is None

    def test_tie_breaks_on_lowest_vendor_id(self):
        prices = [
            {"vendor": "Gfs", "vendor_id": 3, "price": 22.0},
            {"vendor": "US Foods", "vendor_id": 2, "price": 22.0},
        ]
        alt = pick_cheapest_alternative(prices, "Sysco")
        assert alt["vendor_id"] == 2   # deterministic: lowest id wins

    def test_empty_input_is_none(self):
        assert pick_cheapest_alternative([], "Sysco") is None


class TestCreateOrderVsAlt:
    """Baseline resolved inside create_order from live latest quotes."""

    def test_three_vendor_baseline_is_cheapest_other(self, three_vendors):
        t = three_vendors
        result = t["db"].create_order(
            [make_line(t["item_id"], t["ids"]["Sysco"], 20.0, qty=2)],
            status="completed",
        )

        assert result["lines_total"] == 1
        assert result["lines_excluded"] == 0

        order = t["db"].get_order(result["order_id"])
        line = order["items"][0]
        # $22 is the counterfactual, not $25
        assert line["alt_vendor_id"] == t["ids"]["US Foods"]
        assert line["alt_price"] == pytest.approx(22.00)
        assert line["savings_vs_alt"] == pytest.approx(4.00)   # 2 * (22-20)
        assert line["savings_basis"] == "vs_alt"

        assert order["savings_vs_alt"] == pytest.approx(4.00)
        assert order["lines_without_alt"] == 0
        assert order["savings_basis"] == "vs_alt"

    def test_dearest_chosen_negative_unclamped(self, three_vendors):
        t = three_vendors
        result = t["db"].create_order(
            [make_line(t["item_id"], t["ids"]["Gfs"], 25.0, qty=1)],
            status="completed",
        )

        order = t["db"].get_order(result["order_id"])
        line = order["items"][0]
        # cheapest other is $20; choosing $25 is a LOSS of $5 per unit
        assert line["alt_vendor_id"] == t["ids"]["Sysco"]
        assert line["alt_price"] == pytest.approx(20.00)
        assert line["savings_vs_alt"] == pytest.approx(-5.00)
        assert order["savings_vs_alt"] == pytest.approx(-5.00)

    def test_zero_other_vendors_line_excluded_and_counted(self, db, three_vendors):
        """No baseline exists when nobody else quotes: excluded + counted,
        never folded in at zero."""
        solo_id = db.add_item("Solo Item", None, None)
        sysco = db.get_or_create_vendor("Sysco")
        db.add_price("Solo Item", "Sysco", 15.0, "Each")

        t = three_vendors
        result = db.create_order([
            make_line(solo_id, sysco, 15.0),
            make_line(t["item_id"], t["ids"]["Sysco"], 20.0, qty=2),
        ], status="completed")

        assert result["lines_total"] == 2
        assert result["lines_excluded"] == 1

        order = db.get_order(result["order_id"])
        assert order["lines_without_alt"] == 1
        assert order["savings_vs_alt"] == pytest.approx(4.00)   # Widget line only

        solo_line = next(l for l in order["items"]
                         if l["item_name"] == "Solo Item")
        assert solo_line["alt_price"] is None
        assert solo_line["alt_vendor_id"] is None
        assert solo_line["savings_vs_alt"] == pytest.approx(0)

    def test_tie_break_lowest_vendor_id_recorded(self, three_vendors):
        """Two others quoting the SAME price: audit identity must be
        reproducible - lowest vendor_id wins, not SQLite's whim."""
        t = three_vendors
        t["db"].add_price("Widget", "US Foods", 24.0, "Each")
        t["db"].add_price("Widget", "Gfs", 24.0, "Each")

        ids = t["db"].create_order(
            [make_line(t["item_id"], t["ids"]["Sysco"], 20.0)],
            status="completed",
        )
        again = t["db"].create_order(
            [make_line(t["item_id"], t["ids"]["Sysco"], 20.0)],
            status="completed",
        )

        first = t["db"].get_order(ids["order_id"])["items"][0]
        second = t["db"].get_order(again["order_id"])["items"][0]
        expected = min(t["ids"]["US Foods"], t["ids"]["Gfs"])
        assert first["alt_vendor_id"] == second["alt_vendor_id"] == expected
        assert first["alt_price"] == 24.0

    def test_frozen_baseline_ignores_later_price_changes(self, three_vendors):
        t = three_vendors
        result = t["db"].create_order(
            [make_line(t["item_id"], t["ids"]["Sysco"], 20.0, qty=2)],
            status="completed",
        )
        before = t["db"].get_order(result["order_id"])

        t["db"].add_price("Widget", "US Foods", 18.0, "Each")   # market moves

        after = t["db"].get_order(result["order_id"])
        assert after["savings_vs_alt"] == before["savings_vs_alt"]
        assert after["items"][0]["alt_price"] == pytest.approx(22.00)

    def test_default_status_still_draft(self, three_vendors):
        t = three_vendors
        result = t["db"].create_order(
            [make_line(t["item_id"], t["ids"]["Sysco"], 20.0)])
        assert t["db"].get_order(result["order_id"])["status"] == "draft"


class TestPreviewSaveParity:
    """Banner math and stored math route through pick_cheapest_alternative;
    this fixture asserts they agree on identical state (issue-9/F-24 shape)."""

    def test_banner_equals_stored_including_exclusions(self, engine, three_vendors):
        t = three_vendors
        db = t["db"]

        solo_id = db.add_item("Solo Item", None, None)
        sysco = db.get_or_create_vendor("Sysco")
        db.add_price("Solo Item", "Sysco", 15.0, "Each")

        widget_prices = db.get_latest_prices("Widget")

        # preview path: resolve alts via the pure function over rec payload
        w_alt = pick_cheapest_alternative(widget_prices, "Sysco")
        s_alt = pick_cheapest_alternative(db.get_latest_prices("Solo Item"), "Sysco")
        preview_lines = [
            {"qty": 2, "unit_price": 20.0, "avg_price": None, "max_price": None,
             "alt_price": w_alt["price"]},
            {"qty": 1, "unit_price": 15.0, "avg_price": None, "max_price": None,
             "alt_price": s_alt["price"] if s_alt else None},
        ]
        preview = engine.calculate_order_savings(preview_lines)

        # save path: create_order resolves from DB
        result = db.create_order([
            make_line(t["item_id"], sysco, 20.0, qty=2),
            make_line(solo_id, sysco, 15.0),
        ], status="completed")

        stored = db.get_order(result["order_id"])
        assert preview["total_savings_vs_alt"] == \
            pytest.approx(stored["savings_vs_alt"]) == pytest.approx(4.00)
        assert preview["lines_excluded"] == stored["lines_without_alt"] == 1


class TestF19SplitAverages:
    """Two names, two meanings - no shared default to get wrong."""

    def test_market_average_cross_vendor_includes_today(self, db):
        from datetime import date, timedelta
        today = date.today()
        yesterday = (today - timedelta(days=1)).isoformat()
        db.add_price("Milk", "Sysco", 10.0, "Gallon", date_recorded=yesterday)
        db.add_price("Milk", "US Foods", 30.0, "Gallon", date_recorded=yesterday)
        db.add_price("Milk", "Sysco", 12.0, "Gallon", date_recorded=today.isoformat())
        db.add_price("Milk", "US Foods", 32.0, "Gallon", date_recorded=today.isoformat())

        avg = db.get_item_market_average("Milk", days=30)
        assert avg == pytest.approx((10 + 30 + 12 + 32) / 4)   # all four rows

    def test_vendor_baseline_single_vendor_excludes_today(self, db):
        from datetime import date, timedelta
        today = date.today()
        two_days_ago = (today - timedelta(days=2)).isoformat()
        db.add_price("Milk", "US Foods", 12.0, "Gallon", date_recorded=two_days_ago)
        db.add_price("Milk", "US Foods", 32.0, "Gallon",
                     date_recorded=today.isoformat())

        base = db.get_vendor_trend_baseline("Milk", "US Foods", days=30)
        assert base == pytest.approx(12.0)                     # today excluded

    def test_vendor_baseline_none_when_only_today_exists(self, db):
        db.add_price("Milk", "Sysco", 3.5, "Gallon")
        assert db.get_vendor_trend_baseline("Milk", "Sysco", days=30) is None

    def test_market_average_ignores_other_items(self, db):
        db.add_price("Milk", "Sysco", 10.0, "Gallon")
        db.add_price("Bread", "Sysco", 90.0, "Loaf")
        assert db.get_item_market_average("Milk", days=30) == pytest.approx(10.0)


class TestRetiredMethods:
    """Old single-name average retired by the split; max-as-baseline helper
    retired with F-22's semantics."""

    def test_get_average_price_is_gone(self, db):
        assert not hasattr(db, "get_average_price")

    def test_get_max_price_for_item_is_gone(self, db):
        assert not hasattr(db, "get_max_price_for_item")

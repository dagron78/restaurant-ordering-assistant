"""Regression tests for the three reproduced findings in docs/CODE_REVIEW.md.

F-01: same-day price sheets must not both surface as "latest"
F-02: saved orders must be readable by the savings queries
F-03: declared foreign keys must be enforced
"""

import sqlite3

import pytest


class TestLatestPricesOneRowPerVendor:
    """F-01: get_latest_prices returns one row per vendor, the newest insert."""

    def test_same_day_duplicate_returns_single_row_per_vendor(self, seeded_db):
        prices = seeded_db.get_latest_prices("Heavy Cream")

        vendors = [p["vendor"] for p in prices]
        assert len(prices) == 2, f"expected 2 rows, got: {prices}"
        assert sorted(vendors) == ["Sysco", "US Foods"]

    def test_superseded_price_is_not_the_one_returned(self, seeded_db):
        prices = seeded_db.get_latest_prices("Heavy Cream")

        by_vendor = {p["vendor"]: p["price"] for p in prices}
        # 24.50 was the superseded morning sheet; 31.00 is current.
        assert by_vendor["Sysco"] == 31.00

    def test_best_vendor_uses_current_price(self, seeded_db):
        """US Foods @ 28.00 is genuinely cheapest; Sysco's stale 24.50
        must not win the recommendation."""
        prices = seeded_db.get_latest_prices("Heavy Cream")
        best = min(prices, key=lambda p: p["price"])

        assert best["vendor"] == "US Foods"

    def test_old_history_still_excluded(self, db):
        """The date axis: a NEWLY INSERTED but genuinely OLD price must not
        win. (Insert order deliberately reversed - newest first.)"""
        db.add_item("Heavy Cream", category="Dairy")
        sysco = db.get_or_create_vendor("Sysco")

        with db.get_connection() as conn:
            conn.execute(
                """INSERT INTO price_history
                   (item_id, vendor_id, price, unit, date_recorded, source)
                   VALUES (?, ?, 20.0, 'Case', '2026-08-01', 'manual')""",
                (db.get_item(name="Heavy Cream")["id"], sysco),
            )
            # Backfilled afterwards, but dated 2020 - must lose
            conn.execute(
                """INSERT INTO price_history
                   (item_id, vendor_id, price, unit, date_recorded, source)
                   VALUES (?, ?, 10.0, 'Case', '2020-01-01', 'manual')""",
                (db.get_item(name="Heavy Cream")["id"], sysco),
            )

        prices = db.get_latest_prices("Heavy Cream")
        assert len(prices) == 1
        assert prices[0]["price"] == 20.0

    def test_backfill_does_not_shadow_current_price(self, db):
        """Re-importing last week's invoice must not overwrite today's
        price as 'latest' - date_recorded is the clock that matters."""
        from datetime import date, timedelta

        db.add_item("Roma Tomatoes", category="Produce", default_unit="Case")
        sysco = db.get_or_create_vendor("Sysco")
        item_id = db.get_item(name="Roma Tomatoes")["id"]

        today = date.today().isoformat()
        last_week = (date.today() - timedelta(days=7)).isoformat()

        with db.get_connection() as conn:
            # Today's sheet arrives first...
            conn.execute(
                """INSERT INTO price_history
                   (item_id, vendor_id, price, unit, date_recorded, source)
                   VALUES (?, ?, 22.00, 'Case', ?, 'manual')""",
                (item_id, sysco, today),
            )
            # ...then someone re-imports the week-old one
            conn.execute(
                """INSERT INTO price_history
                   (item_id, vendor_id, price, unit, date_recorded, source)
                   VALUES (?, ?, 18.00, 'Case', ?, 'manual')""",
                (item_id, sysco, last_week),
            )

        prices = db.get_latest_prices("Roma Tomatoes")
        assert len(prices) == 1
        assert prices[0]["price"] == 22.00
        assert prices[0]["date_recorded"] == today


class TestOrderStatusAndSavings:
    """F-02: savings dashboards can actually see orders."""

    ORDER_ITEMS = [
        {
            "item_id": None, "vendor_id": None,
            "quantity": 2, "unit": "Case",
            "unit_price": 24.50, "avg_price": 30.00, "max_price": 35.00,
        }
    ]

    def test_order_saved_as_completed_is_counted(self, db):
        item = db.add_item("Heavy Cream", category="Dairy")
        vendor = db.get_or_create_vendor("Sysco")
        items = [dict(self.ORDER_ITEMS[0], item_id=item, vendor_id=vendor)]

        order_id = db.create_order(items, status="completed")

        totals = db.get_total_savings()
        assert totals["total_orders"] == 1
        assert totals["total_spent"] == pytest.approx(49.00)
        # vs avg: 2 * (30 - 24.50) = 11; vs max: 2 * (35 - 24.50) = 21
        assert totals["total_savings_vs_avg"] == pytest.approx(11.00)
        assert totals["total_savings_vs_max"] == pytest.approx(21.00)

    def test_draft_orders_are_not_counted(self, db):
        item = db.add_item("Heavy Cream", category="Dairy")
        vendor = db.get_or_create_vendor("Sysco")
        items = [dict(self.ORDER_ITEMS[0], item_id=item, vendor_id=vendor)]

        db.create_order(items, status="draft")

        assert db.get_total_savings()["total_orders"] == 0

    def test_update_order_status_transitions_to_completed(self, db):
        item = db.add_item("Heavy Cream", category="Dairy")
        vendor = db.get_or_create_vendor("Sysco")
        items = [dict(self.ORDER_ITEMS[0], item_id=item, vendor_id=vendor)]

        order_id = db.create_order(items, status="draft")
        assert db.update_order_status(order_id, "completed") is True
        assert db.get_total_savings()["total_orders"] == 1

    def test_update_order_status_rejects_unknown_status(self, db):
        with pytest.raises(ValueError):
            db.update_order_status(1, "shipped")

    def test_default_status_is_draft(self, db):
        item = db.add_item("Heavy Cream", category="Dairy")
        vendor = db.get_or_create_vendor("Sysco")
        items = [dict(self.ORDER_ITEMS[0], item_id=item, vendor_id=vendor)]

        order_id = db.create_order(items)
        assert db.get_order(order_id)["status"] == "draft"


class TestForeignKeyEnforcement:
    """F-03: PRAGMA foreign_keys is enabled on every connection."""

    def test_orphan_price_rejected(self, db):
        with pytest.raises(sqlite3.IntegrityError):
            with db.get_connection() as conn:
                conn.execute(
                    """INSERT INTO price_history
                       (item_id, vendor_id, price, unit)
                       VALUES (99999, 99999, 1.0, 'Each')"""
                )

    def test_orphan_order_item_rejected(self, db):
        with pytest.raises(sqlite3.IntegrityError):
            with db.get_connection() as conn:
                conn.execute(
                    """INSERT INTO order_items
                       (order_id, item_id, vendor_id, quantity)
                       VALUES (99999, 99999, 99999, 1)"""
                )

    def test_cascade_delete_removes_price_history(self, db):
        item_id = db.add_item("Heavy Cream", category="Dairy")
        vendor = db.get_or_create_vendor("Sysco")
        db.add_price("Heavy Cream", "Sysco", 24.50, "Case")

        with db.get_connection() as conn:
            conn.execute("DELETE FROM items WHERE id = ?", (item_id,))
            remaining = conn.execute(
                "SELECT COUNT(*) as n FROM price_history WHERE item_id = ?",
                (item_id,),
            ).fetchone()

        assert remaining["n"] == 0

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


class TestLatestPriceBothEntryPoints:
    """Issue #9: the Order Guide list (get_all_items_with_prices) and the
    detail view (get_latest_prices) are two views of one fact. Both
    adversarial F-01 fixtures must pass through BOTH entry points, so a
    third divergence is structurally impossible."""

    ENTRY_POINTS = ('detail', 'listing')

    def _latest_by_vendor(self, db, item_name, entry_point):
        if entry_point == 'detail':
            rows = db.get_latest_prices(item_name)
            return {r['vendor']: (r['price'], r['date_recorded']) for r in rows}
        items = db.get_all_items_with_prices()
        row = next(i for i in items if i['name'] == item_name)
        return {p['vendor']: (p['price'], p['date_recorded']) for p in row['prices']}

    def _seed_backfill_scenario(self, db):
        """Today's sheets arrive first; a week-old sheet is backfilled LAST."""
        from datetime import date, timedelta

        item_id = db.add_item('Roma Tomatoes', 'Produce', 'Case')
        sysco = db.get_or_create_vendor('Sysco')
        usfoods = db.get_or_create_vendor('US Foods')

        today = date.today().isoformat()
        last_week = (date.today() - timedelta(days=7)).isoformat()

        with db.get_connection() as conn:
            rows = [
                (sysco, 22.00, today),
                (usfoods, 23.00, today),
                (sysco, 18.00, last_week),   # inserted last, dated oldest
            ]
            for vendor_id, price, recorded in rows:
                conn.execute(
                    """INSERT INTO price_history
                       (item_id, vendor_id, price, unit, source, date_recorded)
                       VALUES (?, ?, ?, 'Case', 'manual', ?)""",
                    (item_id, vendor_id, price, recorded),
                )
        return {'Sysco': (22.00, today), 'US Foods': (23.00, today)}

    def _seed_reversed_order_scenario(self, db):
        """Newest first, then progressively older inserts."""
        item_id = db.add_item('Heavy Cream', 'Dairy', 'Case')
        sysco = db.get_or_create_vendor('Sysco')

        with db.get_connection() as conn:
            for offset, price in [(0, 20.00), (-180, 10.00), (-90, 15.00)]:
                from datetime import date, timedelta
                recorded = (date.today() + timedelta(days=offset)).isoformat()
                conn.execute(
                    """INSERT INTO price_history
                       (item_id, vendor_id, price, unit, source, date_recorded)
                       VALUES (?, ?, ?, 'Case', 'manual', ?)""",
                    (item_id, sysco, price, recorded),
                )
        return {'Sysco': (20.00, date.today().isoformat())}

    @pytest.mark.parametrize('entry_point', ENTRY_POINTS)
    @pytest.mark.parametrize('scenario', ['backfill', 'reversed'])
    def test_current_price_wins_everywhere(self, db, scenario, entry_point):
        if scenario == 'backfill':
            expected = self._seed_backfill_scenario(db)
            item_name = 'Roma Tomatoes'
        else:
            expected = self._seed_reversed_order_scenario(db)
            item_name = 'Heavy Cream'

        assert self._latest_by_vendor(db, item_name, entry_point) == expected

    def test_agreement_between_entry_points(self, db):
        """The two views must return identical vendor→(price, date) maps."""
        self._seed_backfill_scenario(db)

        detail = self._latest_by_vendor(db, 'Roma Tomatoes', 'detail')
        listing = self._latest_by_vendor(db, 'Roma Tomatoes', 'listing')

        assert detail == listing


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

        db.create_order(items, status="completed")

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
        db.get_or_create_vendor("Sysco")
        db.add_price("Heavy Cream", "Sysco", 24.50, "Case")

        with db.get_connection() as conn:
            conn.execute("DELETE FROM items WHERE id = ?", (item_id,))
            remaining = conn.execute(
                "SELECT COUNT(*) as n FROM price_history WHERE item_id = ?",
                (item_id,),
            ).fetchone()

        assert remaining["n"] == 0

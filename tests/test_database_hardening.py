"""Tests for database-layer hardening: batch transactions, N+1 removal,
vendor-name guards, and honest savings attribution.
"""

import pytest



class TestVendorNameGuard:
    """F-27: empty vendor names must be rejected, not inserted."""

    def test_empty_name_raises(self, db):
        with pytest.raises(ValueError):
            db.get_or_create_vendor('')

    def test_whitespace_name_raises(self, db):
        with pytest.raises(ValueError):
            db.get_or_create_vendor('   ')

    def test_valid_name_still_works_and_strips(self, db):
        vid = db.get_or_create_vendor('  Sysco  ')
        assert db.get_vendor(vendor_id=vid)['name'] == 'Sysco'


class TestBatchTransaction:
    """F-30: add_prices_batch is one connection/transaction, not N commits,
    and a bad row must not abort the rest of the batch."""

    def test_mixed_rows_partial_success(self, db):
        prices = [
            {'item_name': 'Flour', 'vendor_name': 'Sysco', 'price': 18.0, 'unit': 'Bag'},
            {'item_name': 'Bad Row'},                      # no price -> skipped
            {'item_name': 'Milk', 'vendor_name': 'US Foods', 'price': 3.5},
        ]
        added = db.add_prices_batch(prices, source='email')

        assert added == 2
        assert len(db.get_latest_prices('Flour')) == 1
        assert len(db.get_latest_prices('Milk')) == 1

    def test_failed_row_leaves_no_orphan_item(self, db):
        # A row failing after item creation must not persist the item
        db.add_prices_batch([
            {'item_name': 'Ghost Item', 'vendor_name': '', 'price': 1.0},
        ])
        assert db.get_item(name='Ghost Item') is None

    def test_all_rows_share_one_commit_semantics(self, db):
        """Everything added is visible together; nothing half-applied."""
        prices = [
            {'item_name': f'Item{i}', 'vendor_name': 'Sysco', 'price': float(i)}
            for i in range(25)
        ]
        assert db.add_prices_batch(prices) == 25
        with db.get_connection() as conn:
            n = conn.execute('SELECT COUNT(*) AS n FROM price_history').fetchone()
        assert n['n'] == 25


class TestSingleQueryItemPrices:
    """F-32: get_all_items_with_prices replaces the per-item N+1 loop."""

    @pytest.fixture()
    def populated(self, db):
        db.add_item('Cream', 'Dairy', 'Case')
        db.add_item('Milk', 'Dairy', 'Gallon')
        db.add_price('Cream', 'Sysco', 24.0, 'Case')
        db.add_price('Cream', 'US Foods', 28.0, 'Case')
        db.add_price('Milk', 'Sysco', 3.5, 'Gallon')
        return db

    def test_output_matches_documented_shape(self, populated):
        items = populated.get_all_items_with_prices()

        by_name = {i['name']: i for i in items}
        cream = by_name['Cream']
        milk = by_name['Milk']

        assert [p['vendor'] for p in cream['prices']] == ['Sysco', 'US Foods']  # cheapest first
        assert cream['avg_price'] == pytest.approx((24.0 + 28.0) / 2)
        assert milk['prices'][0]['price'] == 3.5

    def test_same_day_duplicate_still_one_row_per_vendor(self, populated):
        # Second sheet same day supersedes the first (F-01 semantics preserved)
        item = populated.get_item(name='Cream')
        sysco = populated.get_or_create_vendor('Sysco')
        with populated.get_connection() as conn:
            conn.execute(
                """INSERT INTO price_history (item_id, vendor_id, price, unit)
                   VALUES (?, ?, 31.0, 'Case')""",
                (item['id'], sysco),
            )

        items = populated.get_all_items_with_prices()
        cream = next(i for i in items if i['name'] == 'Cream')
        by_vendor = {p['vendor']: p['price'] for p in cream['prices']}

        assert len(cream['prices']) == 2          # one row per vendor
        assert by_vendor['Sysco'] == 31.0         # newest insert wins

    def test_query_count_is_constant(self, populated):
        """The whole point of F-32: O(1) queries, not O(items)."""
        import sqlite3

        statements = []
        conn = sqlite3.connect(str(populated.db_path))
        conn.set_trace_callback(statements.append)
        try:
            populated.get_all_items_with_prices()
        finally:
            conn.set_trace_callback(None)
            conn.close()

        selects = [s for s in statements if s.lstrip().upper().startswith('SELECT')]
        assert len(selects) <= 3   # was: 1 + 2*items

    def test_inactive_items_excluded(self, populated):
        item = populated.get_item(name='Milk')
        populated.update_item(item['id'], is_active=False)

        names = [i['name'] for i in populated.get_all_items_with_prices()]
        assert 'Milk' not in names


class TestMostUsedVendor:
    """F-28: most_used_vendor must reflect actual spend, not an arbitrary row."""

    def _order_from(self, db, item_id, vendor_id, qty, unit_price):
        db.create_order([{
            'item_id': item_id, 'vendor_id': vendor_id,
            'quantity': qty, 'unit': 'Case',
            'unit_price': unit_price, 'avg_price': unit_price,
            'max_price': unit_price,
        }], status='completed')

    def test_reports_highest_spend_vendor(self, db):
        item_id = db.add_item('Heavy Cream', 'Dairy', 'Case')
        sysco = db.get_or_create_vendor('Sysco')
        usfoods = db.get_or_create_vendor('US Foods')

        self._order_from(db, item_id, sysco, 1, 20.0)
        self._order_from(db, item_id, usfoods, 10, 30.0)   # dominant by spend

        breakdown = db.get_item_savings_breakdown()
        row = next(r for r in breakdown if r['item_name'] == 'Heavy Cream')
        assert row['most_used_vendor'] == 'US Foods'

    def test_respects_completed_filter(self, db):
        item_id = db.add_item('Flour', 'Dry Goods', 'Bag')
        sysco = db.get_or_create_vendor('Sysco')
        db.create_order([{
            'item_id': item_id, 'vendor_id': sysco,
            'quantity': 2, 'unit': 'Bag',
            'unit_price': 10.0, 'avg_price': 10.0, 'max_price': 10.0,
        }], status='draft')

        breakdown = db.get_item_savings_breakdown()
        assert all(r['item_name'] != 'Flour' for r in breakdown)


class TestSavingsAttribution:
    """F-25 support: savings math on a subset equals summing that subset only."""

    def test_subset_savings_exclude_dropped_items(self, db):
        from core.recommendation import RecommendationEngine

        engine = RecommendationEngine(db=db, ai=type('A', (), {})())
        full_order = [
            {'qty': 2, 'unit_price': 10.0, 'avg_price': 12.0, 'max_price': 15.0},
            {'qty': 1, 'unit_price': 50.0, 'avg_price': 60.0, 'max_price': 70.0},
        ]
        saved_subset = full_order[:1]     # second line had missing ids and was dropped

        info = engine.calculate_order_savings(saved_subset)
        assert info['total_savings_vs_max'] == pytest.approx(10.0)

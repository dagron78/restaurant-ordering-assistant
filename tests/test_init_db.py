"""Tests for sample data generation (F-29).

Demo data must span real history - everything stamped today makes the
trend chart a single point and every item read "stable" forever.
"""

from datetime import date

from scripts.init_db import add_sample_data


class TestSampleDataSpread:
    def test_creates_items_and_full_history(self, db):
        add_sample_data(db=db)

        items = db.get_all_items()
        assert len(items) == 10

        # 10 items x 2 vendors x 30 days
        with db.get_connection() as conn:
            count = conn.execute('SELECT COUNT(*) AS n FROM price_history').fetchone()['n']
        assert count == 600

    def test_history_spans_multiple_days_not_just_today(self, db):
        add_sample_data(db=db)

        with db.get_connection() as conn:
            dates = [r['date_recorded'] for r in conn.execute(
                'SELECT DISTINCT date_recorded FROM price_history ORDER BY date_recorded')]

        assert len(dates) == 30
        assert min(dates) < date.today().isoformat()          # real history...
        assert max(dates) <= date.today().isoformat()         # ...nothing from the future

    def test_trends_have_signal(self, db):
        """Latest vs 30-day average must differ for at least some series."""
        add_sample_data(db=db)

        movers = 0
        checked = 0
        for item in db.get_all_items():
            avg = db.get_item_market_average(item['name'])
            if not avg:
                continue
            for price_row in db.get_latest_prices(item['name']):
                checked += 1
                latest = price_row['price']
                if abs(latest - avg) / avg > 0.02:
                    movers += 1

        assert checked == 20   # 10 items x 2 vendors
        assert movers >= 8     # drift guarantees visible movement

    def test_deterministic_between_runs(self, tmp_path):
        from core.database import Database

        def snapshot(database):
            with database.get_connection() as conn:
                return conn.execute(
                    'SELECT item_id, vendor_id, price, date_recorded '
                    'FROM price_history ORDER BY id').fetchall()

        db1 = Database(db_path=tmp_path / 'a.db')
        db1.init_database()
        add_sample_data(db=db1)

        db2 = Database(db_path=tmp_path / 'b.db')
        db2.init_database()
        add_sample_data(db=db2)

        assert [tuple(r) for r in snapshot(db1)] == [tuple(r) for r in snapshot(db2)]

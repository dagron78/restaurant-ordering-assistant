"""Behavioural guards for intake status panel and tour (issue #30 C/D).

These tests exercise rendered output, not source text.
"""

import pathlib

import pytest

from core.config import Config
from core.database import Database

from streamlit.testing.v1 import AppTest

APP = pathlib.Path(__file__).parent.parent / "app"


@pytest.fixture()
def seeded_db(tmp_path):
    db = Database(db_path=tmp_path / "intake_status.db")
    db.init_database()
    db.add_item("Heavy Cream 40%", "Dairy", "Case")
    db.add_item("Whole Milk", "Dairy", "Gallon")
    db.get_or_create_vendor("Sysco", email_domain="sysco.com",
                            scrape_url="https://shop.sysco.com")
    db.add_price("Heavy Cream 40%", "Sysco", 21.50, "Case")
    db.add_price("Whole Milk", "Sysco", 3.50, "Gallon")
    db.log_processing(source_type="scrape", source_identifier="Sysco",
                      filename="weekly_scrape", status="success",
                      items_processed=2)
    return db


@pytest.fixture()
def home_app(seeded_db, monkeypatch):
    monkeypatch.setattr(Config, 'DATABASE_PATH', seeded_db.db_path,
                        raising=True)
    monkeypatch.setattr(Config, 'APP_PASSWORD', '', raising=True)
    return AppTest.from_file(str(APP / "Home.py"))


class TestIntakeStatusPanel:
    def test_shows_per_vendor_row_with_date_and_count(self, home_app):
        home_app.run(timeout=30)
        captions = [c.value for c in home_app.caption]
        sysco_rows = [c for c in captions
                      if "Sysco" in c and "prices updated" in c]
        assert len(sysco_rows) >= 1
        row = sysco_rows[0]
        assert "2 prices updated" in row
        assert any(ch.isdigit() for ch in row)

    def test_quarantine_status_always_visible(self, home_app):
        home_app.run(timeout=30)
        captions = [c.value for c in home_app.caption]
        assert any("uarantine" in c or "Quarantine" in c for c in captions)


class TestTourRendersFourSteps:
    """All four steps reachable via session_state stepping."""

    def test_all_four_steps_render_in_sequence(self, tmp_path):
        db = Database(db_path=tmp_path / "tour.db")
        db.init_database()
        db.add_item("Sample Item", "Test", "Each")

        original_db = Config.DATABASE_PATH
        Config.DATABASE_PATH = db.db_path
        try:
            tour_path = str(pathlib.Path(__file__).parent.parent /
                            "app" / "views" / "4_📖_How_This_Works.py")
            at = AppTest.from_file(tour_path)

            expected = [
                "Here is what we know today",
                "Tell it how you buy",
                "Build an order",
                "Take it to the walk-in",
            ]
            for step, want in enumerate(expected, 1):
                at.session_state["tour_step"] = step
                at.run(timeout=15)
                titles = [t.value for t in at.title]
                assert any(want in t for t in titles), \
                    f"step {step}: '{want}' not found in {titles}"
        finally:
            Config.DATABASE_PATH = original_db

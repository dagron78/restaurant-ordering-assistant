"""Behavioural guards for the default environment (issue #44).

These replace source-text assertions that read like behavioural guards.
Each test exercises actual behaviour: construct the engine, generate
recommendations, verify items come back with prices — no key configured.

Revert verification: change RecommendationEngine.__init__ back to
self.ai = ai or GeminiEngine() and confirm every test here fails.
"""

import pathlib

import pytest

from core.config import Config
from core.database import Database
from core.recommendation import RecommendationEngine


@pytest.fixture()
def default_env_db(tmp_path):
    """Database with seeded prices, no AI key required."""
    db = Database(db_path=tmp_path / "default_env.db")
    db.init_database()
    db.add_item("Heavy Cream 40%", "Dairy", "Case")
    db.add_item("Whole Milk", "Dairy", "Gallon")
    db.get_or_create_vendor("Sysco", email_domain="sysco.com",
                            scrape_url="https://shop.sysco.com")
    db.add_price("Heavy Cream 40%", "Sysco", 21.50, "Case")
    db.add_price("Heavy Cream 40%", "US Foods", 24.00, "Case")
    db.add_price("Whole Milk", "Sysco", 3.50, "Gallon")
    return db


class TestEngineConstructsWithoutKey:
    """The engine must construct without raising when GOOGLE_API_KEY is empty."""

    def test_engine_constructs_and_ai_is_none(self, monkeypatch, tmp_path):
        monkeypatch.setattr(Config, 'GOOGLE_API_KEY', '', raising=True)
        db = Database(db_path=tmp_path / "e.db")
        db.init_database()
        engine = RecommendationEngine(db=db)
        assert engine.ai is None

    def test_generate_order_guide_works_without_key(
            self, monkeypatch, default_env_db):
        monkeypatch.setattr(Config, 'GOOGLE_API_KEY', '', raising=True)
        engine = RecommendationEngine(db=default_env_db)
        recs = engine.generate_order_guide()

        assert len(recs) >= 2
        by_name = {r['item']: r for r in recs}
        cream = by_name['Heavy Cream 40%']
        assert cream['price'] is not None
        assert cream['recommended_vendor'] in ('Sysco', 'US Foods')
        assert cream['trend_icon'] in ('🟢', '🔴', '🟡', '⚪', '⚫')


class TestSavingsWithoutKey:
    """Savings arithmetic is pure math — no AI dependency."""

    def test_calculate_order_savings_without_key(self, default_env_db):
        engine = RecommendationEngine(db=default_env_db)
        lines = [
            {"qty": 2, "unit_price": 22.0, "avg_price": None,
             "max_price": None, "alt_price": 20.0},
        ]
        info = engine.calculate_order_savings(lines)
        # Chose at $22, alternative was $20 -> LOSS of $4
        assert info["total_savings_vs_alt"] == pytest.approx(-4.0)


class TestPageDegradesNotStops:
    """Behavioural companion: generate_order_guide produces items without a key.
    Source-text guards removed per issue #44 — diff inspection is not testing."""

    def test_generate_recommendation_single_item_no_key(
            self, monkeypatch, default_env_db):
        monkeypatch.setattr(Config, 'GOOGLE_API_KEY', '', raising=True)
        engine = RecommendationEngine(db=default_env_db)
        item = default_env_db.get_all_items_with_prices()[0]
        rec = engine.generate_recommendation(item)
        assert rec['price'] is not None
        assert rec['recommended_vendor'] != 'N/A'


import pathlib

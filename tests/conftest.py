"""Shared fixtures: a fresh database built from scripts/schema.sql."""

import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from core.database import Database  # noqa: E402
from core.config import Config, _Settings  # noqa: E402

# Pristine descriptor set — reinstated after every test so a shadowing
# write (monkeypatch or direct assignment) can never leak between tests.
_LIVE_DESCRIPTORS = {
    name: attr for name, attr in vars(Config).items()
    if isinstance(attr, _Settings)
}


@pytest.fixture(autouse=True)
def _restore_live_config_descriptors():
    """Any test that shadows a live Config descriptor gets the real one
    back afterwards. This is what stops one test's config from poisoning
    another — the failure class PR #51 fixed for APP_PASSWORD."""
    yield
    for name, desc in _LIVE_DESCRIPTORS.items():
        if vars(Config).get(name) is not desc:
            setattr(Config, name, desc)


@pytest.fixture(autouse=True)
def _clear_streamlit_resource_cache():
    """get_database() is @st.cache_resource — process-global. Without
    this, an AppTest in test N can receive the Database instance built
    for test 1 (pointing at test 1's temp file). Phase B's UI tests
    passed only because their fixtures were identical; Phase C's are
    not. Clear between tests so every AppTest sees its own database."""
    yield
    try:
        import streamlit as st

        st.cache_resource.clear()
    except Exception:
        pass


@pytest.fixture()
def db(tmp_path):
    """Database initialized with the real schema in a temp directory."""
    database = Database(db_path=tmp_path / "test.db")
    database.init_database()
    return database


@pytest.fixture()
def seeded_db(db):
    """Database containing Heavy Cream prices from two vendors.

    Sysco has two same-day sheets (24.50 superseded by 31.00);
    US Foods has one at 28.00.
    """
    item_id = db.add_item("Heavy Cream", category="Dairy", default_unit="Case")
    sysco = db.get_or_create_vendor("Sysco")
    usf = db.get_or_create_vendor("US Foods")

    conn_ctx = db.get_connection
    with conn_ctx() as conn:
        # Same date_recorded for all three; insert order defines recency.
        rows = [
            (item_id, sysco, 24.50),
            (item_id, usf, 28.00),
            (item_id, sysco, 31.00),
        ]
        for item, vendor, price in rows:
            conn.execute(
                """INSERT INTO price_history
                   (item_id, vendor_id, price, unit, source)
                   VALUES (?, ?, ?, 'Case', 'manual')""",
                (item, vendor, price),
            )
    return db


@pytest.fixture()
def three_vendors(db):
    """Widget quoted today by three vendors: Sysco $20, US Foods $22, Gfs $25."""
    item_id = db.add_item("Widget", "Dry Goods", "Each")
    ids = {name: db.get_or_create_vendor(name)
           for name in ("Sysco", "US Foods", "Gfs")}
    for name, price in (("Sysco", 20.0), ("US Foods", 22.0), ("Gfs", 25.0)):
        db.add_price("Widget", name, price, "Each")
    return {"db": db, "item_id": item_id, "ids": ids}

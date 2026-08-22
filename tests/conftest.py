"""Shared fixtures: a fresh database built from scripts/schema.sql."""

import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from core.database import Database  # noqa: E402


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

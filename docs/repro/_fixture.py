"""Shared in-memory SQLite fixture built from the app's real schema."""

import pathlib
import sqlite3

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
SCHEMA = REPO_ROOT / 'scripts' / 'schema.sql'

# The query under review, lifted verbatim from core/database.py::get_latest_prices
CURRENT_QUERY = """
    SELECT vendor, price, date_recorded FROM (
        SELECT v.name as vendor, ph.price, ph.date_recorded,
               ROW_NUMBER() OVER (
                   PARTITION BY ph.vendor_id
                   ORDER BY ph.created_at DESC, ph.id DESC
               ) as rn
        FROM price_history ph
        JOIN items i ON ph.item_id = i.id
        JOIN vendors v ON ph.vendor_id = v.id
        WHERE i.name = ?
    ) WHERE rn = 1 ORDER BY price
"""

FIXED_QUERY = CURRENT_QUERY.replace(
    "ORDER BY ph.created_at DESC, ph.id DESC",
    "ORDER BY ph.date_recorded DESC, ph.created_at DESC, ph.id DESC",
)


def fresh_db(item_name, unit='Case'):
    """In-memory DB with the real schema and one item registered."""
    conn = sqlite3.connect(':memory:')
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA.read_text())
    conn.execute("INSERT INTO items (name, default_unit) VALUES (?, ?)",
                 (item_name, unit))
    return conn


def add_price(conn, vendor, price, date_recorded, unit='Case'):
    """Insert one price_history row, creating the vendor if the schema didn't."""
    conn.execute("INSERT OR IGNORE INTO vendors (name) VALUES (?)", (vendor,))
    vendor_id = conn.execute(
        "SELECT id FROM vendors WHERE name = ?", (vendor,)).fetchone()['id']
    conn.execute(
        """INSERT INTO price_history
           (item_id, vendor_id, price, unit, source, confidence, date_recorded)
           VALUES (1, ?, ?, ?, 'manual', 1.0, ?)""",
        (vendor_id, price, unit, date_recorded))


def run(conn, query, item_name):
    return [dict(r) for r in conn.execute(query, (item_name,)).fetchall()]

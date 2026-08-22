"""Migration gate tests (issue #17).

The top gate item: a database built from the OLD schema and migrated must be
structurally identical to a fresh build from schema.sql. Every other test in
the suite builds from a fresh schema.sql — without this test, a broken
migration passes the entire suite and fails on every real database.

Also covers the legacy-row semantics Charles ruled on issue #17:
- legacy lines with max_price > unit_price recompute exactly (two-vendor era:
  max_price WAS min-of-others), basis stamped 'vs_alt' at migration time
- legacy lines otherwise are 'unknown_legacy': excluded from headline,
  counted — single-quote and dearer-chosen cannot be distinguished, and 0
  was stored where the honest answer is negative
"""

import pathlib
import sqlite3

import pytest

from core.database import Database, SCHEMA_VERSION

PROJECT_ROOT = pathlib.Path(__file__).parent.parent
BASE_SQL = PROJECT_ROOT / "scripts" / "migrations" / "000_base.sql"


# ---- builders ---------------------------------------------------------------

def build_fresh(path):
    db = Database(db_path=path)
    db.init_database()
    return db


def build_old_schema(path):
    """A pre-v1 database: 000_base.sql verbatim, user_version 0."""
    conn = sqlite3.connect(str(path))
    conn.executescript(BASE_SQL.read_text())
    conn.commit()
    conn.close()
    return Database(db_path=path)


def snapshot_structure(path):
    """Semantic structure: everything that changes behaviour.

    Deliberately excludes each table's CREATE sql text — CHECK constraints
    live inline on fresh builds but arrive via ALTER TABLE on migrated ones,
    so the text differs while the semantics match. Enforcement equivalence is
    asserted behaviourally below.
    """
    conn = sqlite3.connect(str(path))
    try:
        tables = [r[0] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' "
            "AND name NOT LIKE 'sqlite_%' ORDER BY name")]

        out = {"tables": tables, "user_version": conn.execute("PRAGMA user_version").fetchone()[0],
               "table_info": {}, "foreign_keys": {}, "indexes": {}, "trigger_sql": {}}

        for t in tables:
            out["table_info"][t] = [
                (r[1], r[2], r[3], r[4], r[5])          # name,type,notnull,dflt,pk
                for r in conn.execute(f"PRAGMA table_info({t})")]
            out["foreign_keys"][t] = sorted(
                tuple(r) for r in conn.execute(f"PRAGMA foreign_key_list({t})"))
            idx = sorted(
                (r[1], r[2], r[3])                       # name, unique, origin
                for r in conn.execute(f"PRAGMA index_list({t})")
                if not r[1].startswith("sqlite_autoindex_"))
            out["indexes"][t] = idx

        for kind in ("trigger", "view"):
            for r in conn.execute(
                    f"SELECT name, sql FROM sqlite_master WHERE type='{kind}' ORDER BY name"):
                out.setdefault(kind + "_sql", {})[r[0]] = r[1]

        return out
    finally:
        conn.close()


# ---- the gate ---------------------------------------------------------------

def test_migrated_old_schema_matches_fresh_build(tmp_path):
    build_fresh(tmp_path / "fresh.db")

    old = build_old_schema(tmp_path / "migrated.db")
    old.migrate()

    assert snapshot_structure(tmp_path / "migrated.db") == \
        snapshot_structure(tmp_path / "fresh.db")


def test_migrated_db_enforces_new_check_like_fresh(tmp_path):
    """Behavioural equivalence for the CHECK that text-comparison can't see."""
    for builder in (build_fresh, build_old_schema):
        db = builder(tmp_path / f"{builder.__name__}.db")
        if builder is build_old_schema:
            db.migrate()
        item_id = db.add_item("X", None, None)
        vendor_id = db.get_or_create_vendor("Sysco")
        result = db.create_order([{
            "item_id": item_id, "vendor_id": vendor_id,
            "quantity": 1, "unit_price": 10.0,
        }], status="completed")

        with pytest.raises(sqlite3.IntegrityError):
            with db.get_connection() as conn:
                conn.execute(
                    "UPDATE orders SET savings_basis = 'bogus' WHERE id = ?",
                    (result["order_id"],),
                )


def test_legacy_rows_recomputed_and_stamped(tmp_path):
    """Charles's ruling: two vendors existed when legacy rows were written, so
    max_price WAS min-of-others wherever max_price > unit_price."""
    db = build_old_schema(tmp_path / "legacy.db")
    item_id = db.add_item("Heavy Cream", "Dairy", "Case")
    sysco = db.get_or_create_vendor("Sysco")

    with db.get_connection() as conn:
        conn.execute(
            "INSERT INTO orders (status) VALUES ('completed')")
        order_id = conn.execute("SELECT MAX(id) FROM orders").fetchone()[0]
        # chosen Sysco@20 vs US Foods@28 -> recomputable (max > unit)
        conn.execute(
            """INSERT INTO order_items
               (order_id, item_id, vendor_id, quantity, unit, unit_price,
                total_price, max_price, savings_vs_max)
               VALUES (?, ?, ?, 2, 'Case', 20.0, 40.0, 28.0, 16.0)""",
            (order_id, item_id, sysco),
        )
        # chosen at the top of the market -> NOT recomputable (max <= unit)
        conn.execute(
            """INSERT INTO order_items
               (order_id, item_id, vendor_id, quantity, unit, unit_price,
                total_price, max_price, savings_vs_max)
               VALUES (?, ?, ?, 1, 'Case', 30.0, 30.0, 30.0, 0.0)""",
            (order_id, item_id, sysco),
        )

    db.migrate()

    with db.get_connection() as conn:
        rows = {r["savings_basis"]: r for r in conn.execute(
            "SELECT alt_price, savings_vs_alt, savings_basis FROM order_items")}
        assert len(rows) == 2

        recomputed = rows["vs_alt"]
        assert recomputed["alt_price"] == pytest.approx(28.00)
        assert recomputed["savings_vs_alt"] == pytest.approx(16.00)

        unknown = rows["unknown_legacy"]
        assert unknown["alt_price"] is None          # no honest baseline exists
        assert unknown["savings_vs_alt"] == pytest.approx(0)

        order = conn.execute(
            "SELECT savings_vs_alt, lines_without_alt, savings_basis "
            "FROM orders").fetchone()
        assert order["savings_vs_alt"] == pytest.approx(16.00)
        assert order["lines_without_alt"] == 1
        assert order["savings_basis"] == "unknown_legacy"


def test_migration_preserves_existing_data(tmp_path):
    db = build_old_schema(tmp_path / "keep.db")
    item = db.add_item("Flour", "Dry Goods", "Bag")
    vendor = db.get_or_create_vendor("Sysco")
    db.add_price("Flour", "Sysco", 18.0, "Bag")

    db.migrate()

    assert db.get_item(name="Flour")["id"] == item
    assert len(db.get_latest_prices("Flour")) == 1
    assert db.get_vendor(vendor_id=vendor)["name"] == "Sysco"


def test_init_database_stamps_current_version(tmp_path):
    db = build_fresh(tmp_path / "fresh.db")
    with db.get_connection() as conn:
        version = conn.execute("PRAGMA user_version").fetchone()[0]
    assert version == SCHEMA_VERSION


def test_second_migrate_is_noop(tmp_path):
    db = build_old_schema(tmp_path / "once.db")
    db.migrate()
    with db.get_connection() as conn:
        before = conn.execute(
            "SELECT COUNT(*) FROM order_items").fetchone()[0]
    db.migrate()
    with db.get_connection() as conn:
        after = conn.execute(
            "SELECT COUNT(*) FROM order_items").fetchone()[0]
    assert before == after

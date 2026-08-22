"""
Phase 0 evidence: F-01 is fixed in get_latest_prices() but not in the `latest`
CTE inside get_all_items_with_prices() -- the query that renders the Order Guide
item list. The two now disagree on the same data.

Self-contained: stdlib sqlite3 against scripts/schema.sql. Both ORDER BY clauses
below are verbatim from core/database.py at master a58a121.
"""

import pathlib
import sqlite3

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
SCHEMA = REPO_ROOT / 'scripts' / 'schema.sql'

# core/database.py:477 -- get_all_items_with_prices(), still on the old clock
CTE_ORDER = "ph.created_at DESC, ph.id DESC"
# core/database.py:389 -- get_latest_prices(), fixed in f6ad58d
FIXED_ORDER = "ph.date_recorded DESC, ph.created_at DESC, ph.id DESC"

QUERY = """
WITH latest AS (
    SELECT ph.item_id, ph.vendor_id, ph.price, ph.date_recorded,
           ROW_NUMBER() OVER (PARTITION BY ph.item_id, ph.vendor_id
                              ORDER BY {order}) as rn
    FROM price_history ph
)
SELECT v.name as vendor, r.price, r.date_recorded
FROM items i
LEFT JOIN latest r ON r.item_id = i.id AND r.rn = 1
LEFT JOIN vendors v ON v.id = r.vendor_id
WHERE i.is_active = 1
ORDER BY r.price
"""


def seeded():
    conn = sqlite3.connect(':memory:')
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA.read_text())
    conn.execute("INSERT INTO items (name, category, default_unit) "
                 "VALUES ('Roma Tomatoes', 'Produce', 'Case')")
    ids = {r['name']: r['id'] for r in conn.execute("SELECT id, name FROM vendors")}
    rows = [
        (ids['Sysco'],    22.00, '2026-08-21'),  # today's real price
        (ids['US Foods'], 23.00, '2026-08-21'),  # today's real price
        (ids['Sysco'],    18.00, '2026-08-14'),  # backfilled last: a WEEK OLD
    ]
    for vendor_id, price, date_recorded in rows:
        conn.execute(
            """INSERT INTO price_history
               (item_id, vendor_id, price, unit, source, confidence, date_recorded)
               VALUES (1, ?, ?, 'Case', 'manual', 1.0, ?)""",
            (vendor_id, price, date_recorded))
    return conn


conn = seeded()
for label, order in (("get_all_items_with_prices  (Order Guide list)", CTE_ORDER),
                     ("get_latest_prices          (already fixed)", FIXED_ORDER)):
    rows = [dict(r) for r in conn.execute(QUERY.format(order=order)).fetchall()]
    best = min(rows, key=lambda r: r['price'])
    print(f"{label}:")
    for row in rows:
        print("   ", row)
    print(f"    -> best = {best['vendor']} @ ${best['price']:.2f} "
          f"(dated {best['date_recorded']})\n")

print("Sysco's real price today is $22.00. The two queries disagree, so the item")
print("list and the detail view report different 'current' prices for one vendor.")

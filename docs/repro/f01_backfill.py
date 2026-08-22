"""
F-01 reopened: get_latest_prices() ranks by created_at, i.e. insertion order.

Backfilling one older invoice after today's sheets makes the stale row win,
which is F-01's original failure mode (recommend a superseded price).
"""

from _fixture import CURRENT_QUERY, FIXED_QUERY, add_price, fresh_db, run

ITEM = 'Roma Tomatoes'

conn = fresh_db(ITEM)
# Today's real sheets land first...
add_price(conn, 'Sysco',    22.00, '2026-08-21')
add_price(conn, 'US Foods', 23.00, '2026-08-21')
# ...then someone re-imports a week-old Sysco invoice. Newer created_at, older date.
add_price(conn, 'Sysco',    18.00, '2026-08-14')

for label, query in (("CURRENT (created_at only)", CURRENT_QUERY),
                     ("FIXED (date_recorded first)", FIXED_QUERY)):
    rows = run(conn, query, ITEM)
    best = rows[0]
    print(f"{label}:")
    for row in rows:
        print("   ", row)
    print(f"    -> recommends {best['vendor']} @ ${best['price']:.2f} "
          f"(dated {best['date_recorded']})\n")

print("Sysco's actual price today is $22.00.")

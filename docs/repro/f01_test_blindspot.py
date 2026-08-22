"""
The F-01 regression test passes for the wrong reason.

tests/test_database.py::test_old_history_still_excluded inserts 2020 then 2026 --
chronological order, so it passes whether ranking is by date or by insertion.
Reverse only those two inserts and a 2020 price becomes "current".
"""

from _fixture import CURRENT_QUERY, FIXED_QUERY, add_price, fresh_db, run

ITEM = 'Heavy Cream'

for label, order in (("as written  (2020, then 2026)", [(10.0, '2020-01-01'),
                                                        (20.0, '2026-08-01')]),
                     ("reversed    (2026, then 2020)", [(20.0, '2026-08-01'),
                                                        (10.0, '2020-01-01')])):
    for query_label, query in (("current", CURRENT_QUERY), ("fixed", FIXED_QUERY)):
        conn = fresh_db(ITEM)
        for price, date_recorded in order:
            add_price(conn, 'Sysco', price, date_recorded)
        rows = run(conn, query, ITEM)
        got = rows[0]['price']
        verdict = 'PASS' if got == 20.0 else f'FAIL (got {got}, a 2020 price)'
        print(f"{label} | {query_label:<7} query | assert price == 20.0 -> {verdict}")

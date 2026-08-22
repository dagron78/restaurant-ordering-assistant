# Review repros

Standalone reproductions for the findings in `../REVIEW_2026-08-21.md`.

Each script uses only the standard library plus `scripts/schema.sql`, so they run
with no virtualenv, no `GOOGLE_API_KEY` and no Playwright browser:

```
python3 docs/repro/f01_backfill.py
python3 docs/repro/f01_test_blindspot.py
python3 docs/repro/f04_tile_matcher.py
python3 docs/repro/f04_proposed_matcher.py
```

`schema.sql` pre-seeds the `vendors` rows, so the DB fixtures use
`INSERT OR IGNORE` and look the ids up rather than inserting blind.

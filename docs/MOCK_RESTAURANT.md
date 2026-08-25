# The Copper Pan — a mock restaurant

A 60-seat neighbourhood bistro that does not exist, built so a person can open
the app and watch each guard do its job.

```bash
python scripts/seed_mock_restaurant.py --reset
streamlit run app/Home.py
```

No `GOOGLE_API_KEY`. No network. About two seconds.

## Why the prices are invented

The first attempt at this stalled trying to research real vendor pricing. That
was the wrong thing to optimise:

> A mock restaurant whose numbers are market-accurate but which exercises three
> code paths is worth less than one whose numbers are invented but which
> exercises all of them.

Where a real anchor was to hand it is used, so nothing looks absurd to a
restaurant person — chicken breast 40 lb around $72–76, ground beef 80/20 around
$4.40–4.50/lb, leg quarters 40 lb around $28. Everything else is chosen to make
a specific behaviour visible. **Do not cite these figures as market data.**

## What each piece is there to demonstrate

The seeder prints the scenario beside every row it creates. The full list:

| Fixture | Demonstrates |
|---|---|
| **3 vendors**, not 2 | With two vendors, "the next cheapest" and "the most expensive" are the same row — a savings bug cannot show itself. Leg Quarters carries three quotes so they separate. |
| **Heavy Duty Foil Wrap, par 0** | Stocked but deliberately never reordered. |
| **Olive Oil 3L, no par** | Nobody has set one yet. Collapsing this to the same thing as par 0 loses a real management instruction — they are different states and the app must show them differently. |
| **Avocados Hass, one quote** | Single-quote lines are excluded from savings *and counted*, so the manager knows the coverage of the number they are reading. |
| **Romaine Hearts, $9.99 dated a week ago, inserted last** | Finding **F-01**. Ranking price history by insertion order instead of `date_recorded` makes this stale figure today's price. It must not appear. |
| **~30 days of drifting history** | Trends has something to draw. Drift is seeded (`random.seed(20260825)`) so the same demo appears every time. |
| **5 rules, incl. two that conflict** | A vendor preference for produce and a hard exclusion sit at different priorities. |
| **A rule naming "Saffron Threads"** | Managers write rules about things they no longer carry. It must be ignored, not fatal. |
| **A confirmed order with a manager override** | The manager took Foil Wrap from the *dearer* vendor. Savings come out **negative** and `chosen_by='manager'` records whose call it was. The app must not quietly re-sort this to look optimal. |
| **A zero-quantity line** | Dropped from outputs, kept in the record. |
| **2 quarantined emails** | Unknown senders are held as metadata and never parsed until a human promotes them. |

## The order sheet is imported, not injected

`tests/fixtures/copper_pan_order_sheet.csv` is a deliberately messy sheet — a
title row above the header, a blank row, a `TOTAL` row, a par of `lots`, and a
row with a quantity but no item name. The seeder pushes it through the real
parser (`core/order_sheet.py`), so the fixture proves the import survives what a
kitchen actually sends:

```
row 13: Saffron Threads — unparseable par 'lots'
row 14: (no name) — no item name in row
1 blank, 1 total-like
```

Every dropped row is either rejected with a reason or counted. Nothing vanishes.

The items are created *before* the import, so the import also exercises
reconciliation: all ten rows match existing items and update in place. A second
import creates nothing and duplicates nothing.

## Running it twice

The script refuses to seed a database that already holds items:

```
error: data/orders.db already holds 10 items.
       Re-run with --reset to rebuild it from scratch.
```

Without that guard a second run doubled the price history and placed a second
order — a fixture that silently drifts from what this document says it is.

## What it deliberately does not cover

- **Vendor portal connection** (Phase E) — needs real credentials.
- **Live mailbox intake** (Phase F) — the quarantine rows are seeded directly;
  no message is ever fetched.
- **AI parsing** — the order sheet is parsed deterministically by design, and
  nothing here calls a model. `tests/fixtures/golden_prefs` covers that path.

Guarded by `tests/test_mock_restaurant.py`, which pins the properties above
rather than the numbers.

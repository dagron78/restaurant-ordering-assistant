# Take it for a test drive

Two ways to try this app. Both use **The Copper Pan**, a mock restaurant that
exists so you can judge the product without setting up a real kitchen.

Neither needs a Google API key. Neither touches the network.

---

## 1 · The two-minute version — let it check itself

```bash
python scripts/test_drive.py
```

It runs a complete ordering round and prints what a person would notice at
each step:

```
6 · The manager overrides a line onto the DEARER vendor
  ✓ overriding to a dearer vendor lowers savings instead of hiding it
      Sysco $20.89 → US Foods $22.51; net $22.71 → $12.99

7 · Confirm BUILDS the order — it does not send it
  ✓ what was approved is what gets recorded — to the penny
      approved $12.99 / recorded $12.99; total $688.35
```

Exits non-zero if anything fails, so it doubles as a smoke test before a demo.
Add `--keep` to keep the database and open it in the app afterwards.

---

## 2 · The real version — drive it yourself

```bash
python scripts/seed_mock_restaurant.py --reset
streamlit run app/Home.py
```

Sign in with the password set during install. Set demo passwords with:

```python
python - <<'EOF'
from core import auth
from core.database import Database
db = Database(); auth.set_password("app", "demo", db=db)
auth.set_password("admin", "demoadmin", db=db)
EOF
```

Two passwords by design: the **app** password runs an ordering round, the
**admin** password also opens configuration.

### What to do, and what you should see

| # | Do this | You should see | If you don't |
|---|---|---|---|
| 1 | Open **Order Sheet** | Ten items already filled in from par — you type nothing to start | Par levels aren't loading; check the sheet imported |
| 2 | Look at **Heavy Duty Foil Wrap** and **Olive Oil 3L** | Foil Wrap shows `0` and says *stocked, not normally reordered*. Olive Oil is blank | These two states got collapsed — a real instruction was lost |
| 3 | Set **Chicken Breast** to 0, **Roma Tomatoes** to 6 | Nothing else changes | — |
| 4 | Hit **Send — build the plan** | A plan appears. Chicken is **absent** — zero means "not this week", not "zero of these" | Zero-quantity lines are leaking into orders |
| 5 | Read the **Why** under each line | Plain sentences: *cheapest remaining: Sysco $27.83*, *rule 4: excluded Gordon Food Service* | A line with no reason is a line the manager can't check |
| 6 | Find **Leg Quarters** | Never Gordon Food Service — the kitchen's rule says so | The written rules aren't binding |
| 7 | Find **Avocados Hass** | *No alternative quote — excluded from savings* | Single-quote lines must be excluded **and counted**, never folded in at zero |
| 8 | Override **Roma Tomatoes** to the other vendor | Savings go **down**, visibly | Overrides are being quietly re-sorted to look optimal |
| 9 | Hit **Confirm** | The order is built. **Nothing is sent.** The totals match what you just approved | Approved ≠ recorded is a trust bug, not a rounding bug |
| 10 | Open **Order History** | Your order, with figures *as confirmed* — not re-priced | History must not silently re-quote yesterday's order |
| 11 | Expand the order → **Read to a rep** | A numbered call sheet with a price on every line | You'd be quoting prices from memory on the phone |

### Then try to break it

- **Set every quantity to 0 and Send.** Nothing should be ordered.
- **Override a line, then discard the plan** and start again. The discarded
  plan must not reappear.
- **Sign in with the app password**, not admin. Configuration should be closed
  to you.
- **Re-run the seeder without `--reset`.** It should refuse rather than
  double the price history.
- **Shrink the window to phone width** and run a round. The nav drawer must
  close when you pick a page, not sit on top of the order sheet.

---

## What isn't built yet

Don't report these — they're known and sequenced:

- **Vendor portal connection** — needs real vendor credentials
- **Live mailbox intake** — the quarantine rows are seeded directly; no
  message is ever fetched
- **AI-parsed order sheets** — deliberately *not* AI. The sheet is a
  spreadsheet parsed deterministically, because a hallucinated quantity is a
  wrong order

## A decision worth a second opinion

A rule written as *"Always buy dairy from US Foods"* carries no stated
tolerance, and the engine treats an unstated tolerance as **zero** — so any
cheaper alternative wins, and a 5¢ difference overrides "always". That is
deliberate (`test_missing_tolerance_defaults_to_zero_strict`: *no premium
paid for a preference unless you say how much*), and it is defensible. But it
does mean **"always" does not currently mean always.** If a manager expects
the stronger reading, that's a one-line change to the default — worth
deciding before a client meets it.

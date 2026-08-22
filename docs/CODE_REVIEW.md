# Code Review — Restaurant Ordering Assistant

**Reviewed:** 20 Aug 2026 · `master @ 35fa5ef`
**Scope:** all 5,100 lines — `core/`, `app/`, `workers/`, `scripts/`, `schema.sql`, Docker
**Findings:** 40 — 6 critical, 10 high, 24 medium
**Verified by execution:** F-01, F-02, F-03 (reproduced against the real schema in SQLite)

---

## Where it stands

The architecture is sound and the layering is genuinely clean. `core/` has no
Streamlit import anywhere, so the boundary the README claims is real. Every
query is parameterised. The schema has CHECK constraints on every enum column
and sensible indexes.

What the project hasn't had is a pass where the numbers were checked against
what the code actually stores. That's where nearly everything below lives —
several features write correct data that nothing can read back, and three paths
put confidently wrong prices in front of the user.

---

## Reproduced, not just read

I built `scripts/schema.sql` in SQLite and ran the app's own queries against it.
These three are confirmed behaviour.

### F-01 · CRITICAL · Two price sheets on the same day make the app quote a superseded price

`core/database.py:257` · `scripts/schema.sql:45`

`price_history.date_recorded` is a `DATE`, not a timestamp. `get_latest_prices()`
finds each vendor's newest price with `date_recorded = (SELECT MAX(date_recorded) …)`,
so when a vendor's price lands twice in one day — a corrected sheet, a re-run
scrape, two invoices — both rows tie for "most recent" and both are returned.
`get_best_vendor()` then takes the minimum across all of them.

```
get_latest_prices('Heavy Cream') — "most recent price from each vendor":
  {'vendor': 'Sysco',    'price': 24.5, 'date_recorded': '2026-08-20'}   ← superseded morning sheet
  {'vendor': 'US Foods', 'price': 28.0, 'date_recorded': '2026-08-20'}
  {'vendor': 'Sysco',    'price': 31.0, 'date_recorded': '2026-08-20'}   ← the real current price

3 rows for 2 vendors. Sysco appears twice.
get_best_vendor() picks min price → Sysco @ $24.50
Recommends Sysco. US Foods @ $28.00 was actually cheapest.
```

**Why it matters:** a kitchen manager follows the recommendation and orders from
the more expensive vendor at a price that no longer exists. The same vendor also
appears twice in the comparison table. This is the finding that costs real money
on every affected order.

**Fix:** store a full timestamp and pick one row per vendor by `id` or
`created_at` — `ROW_NUMBER() OVER (PARTITION BY vendor_id ORDER BY created_at DESC)`
removes the tie entirely.

### F-02 · CRITICAL · The savings dashboard can only ever show zero

`core/database.py:451, 608, 637, 696` · `scripts/schema.sql:78` · Trends tab 1

`create_order()` never sets `status`, so every saved order takes the schema
default of `'draft'`. Every savings query filters `WHERE status = 'completed'`.
Nothing in the codebase transitions an order between the two — there is no
status-update method at all.

```
order row as create_order() writes it:
  {'id': 1, 'status': 'draft', 'total_amount': 100.0, 'savings_vs_avg': 15.0, 'savings_vs_max': 25.0}

what the Savings Dashboard reads back (WHERE status='completed'):
  {'total_orders': 0, 'spent': 0, 'sv_avg': 0, 'sv_max': 0}
```

**Why it matters:** savings tracking is the headline feature and three of the
Trends page's panels depend on it. All of them render "No order history yet"
forever. The data is written correctly — it is just never readable.

**Fix:** add a "mark order placed" action setting `status='completed'`, or drop
the filter. The former is better; the distinction is worth keeping, it just
needs a way to cross it.

### F-03 · HIGH · Foreign keys are declared but never enforced

`core/database.py:31` · `scripts/schema.sql:50, 107`

The schema declares six foreign keys with `ON DELETE CASCADE`. SQLite ignores
all of them unless `PRAGMA foreign_keys = ON` is issued per connection, and
`get_connection()` never does.

```
PRAGMA foreign_keys default: 0
INSERT INTO order_items (order_id, item_id, vendor_id, quantity)
VALUES (99999, 42, 42, 1);   — order 99999 and item 42 do not exist
→ ACCEPTED
```

**Why it matters:** deleting an item leaves its price history and order lines
behind as orphans, and the joins in the savings queries then silently drop rows.
Neither "Clear All Price History" nor "Reset Entire Database" cascades.

**Fix:** `conn.execute("PRAGMA foreign_keys = ON")` in `get_connection()`. Set
`journal_mode=WAL` and a `busy_timeout` in the same place — see F-13.

---

## Also critical

### F-04 · The scraper records the first price on the page, whatever product it belongs to

`workers/web_scraper.py:345–395, 437–487`

`extract_price_from_page()` loads a *search results* page, walks a list of
candidate CSS selectors, and takes `elements[0].inner_text()` from the first
selector that matches anything. It never checks that the product beside that
price is the item searched for.

**Why it matters:** a sponsored result, a promoted bundle or a near-miss product
at the top of the results has its price stored as the searched item's price at
0.8 confidence, then feeds the recommendation. Wrong prices entering silently
are worse than no prices, because nothing about the output looks broken.

**Fix:** scope extraction to a product tile whose title matches the query, and
skip the item when nothing matches rather than falling back to position zero.

### F-05 · Every scraped price is stored as "Each", including case prices

`workers/web_scraper.py:373, 466` · `web_scraper.py:269`

Both scrapers hardcode `'unit': 'Each'` in the dict they return. The caller
reads `price_data.get('unit', item.get('default_unit', 'Each'))` — but the key is
always present, so the item's real `default_unit` is never consulted. That
fallback is dead code.

**Why it matters:** a $42 case of fry oil and a $2 single unit land in the same
column with the same unit label. The vendor comparison, the 30-day average and
the trend arrows are then computed across mixed units, so a "deal" can be
nothing more than a unit mismatch.

**Fix:** parse the unit from the page, or return `None` and let the caller fall
back to `default_unit`. Refuse to compare or average prices whose units differ.

### F-06 · PDF price lists fail, and the email is marked read anyway

`core/ai_engine.py:146` · `workers/email_monitor.py:132, 248` · `Settings.py:58`

Three places advertise PDF support — the uploader's `type=[…'pdf']`, the email
monitor's extension check, and `parse_document`'s own docstring. But
`parse_document` opens the file with `PIL.Image.open()`, which cannot read a PDF.
The exception is caught, logged as `failed`, and then `mailbox.seen(msg, True)`
runs regardless of outcome.

**Why it matters:** vendor price lists arrive as PDFs. Each is marked read and
never retried, so the attachment is gone — the only trace is a processing-log
row. The same path swallows transient Gemini outages: three retries, then the
message is consumed and lost.

**Fix:** two independent changes. Convert PDFs to images (`pdf2image`) or pass
bytes to Gemini with a MIME type; and only mark a message seen once every
attachment on it has succeeded.

### F-07 · The Danger Zone confirmation can never be satisfied

`app/pages/3_⚙️_Settings.py:508–527`

The confirm checkbox is created *inside* the button's `if` block. On the run
where the button is true the checkbox renders fresh and unchecked, so `confirm`
is `False` and nothing happens. Tick it and Streamlit reruns — now the button is
false, the block is skipped, and the checkbox disappears.

**Why it matters:** "Clear All Price History" and "Reset Entire Database" are
both unreachable. Harmless today, but the confirmation is structurally fake
rather than merely broken — so the obvious fix (hoist the checkbox out) turns
both into working one-click destructive buttons if the ordering isn't handled
deliberately.

**Fix:** render the checkbox above the button and gate the button on it —
`st.button(…, disabled=not confirm)`. Consider a typed confirmation for the full
reset, matching what `init_db.py --reset` already asks for on the CLI.

---

## High

| ID | Finding | Where |
|----|---------|-------|
| F-08 | **Gemini 1.5 Flash and Pro are retired models.** Both IDs are hardcoded, so every AI path fails at runtime on a fresh key. | `ai_engine.py:37–38` |
| F-09 | **Vendor sender check is a substring match with no SPF/DKIM.** `'sysco.com' in from_address` matches `anyone@sysco.com.attacker.tld`, and the attachment then goes to the LLM and into the price table. | `email_monitor.py:64–76` |
| F-10 | **No authentication anywhere.** The container binds `0.0.0.0:8501` with no login, exposing vendor sessions, the Danger Zone and all pricing to anyone who can reach the port. | `Dockerfile:61` |
| F-11 | **No `.dockerignore`, so `COPY . .` bakes in secrets.** Any local `.env`, the SQLite database and `data/sessions/` auth cookies get copied into image layers — `.gitignore` does not cover Docker builds. | `Dockerfile:48` |
| F-12 | **Vendor credentials are collected but never used.** `SYSCO_USER/PASS` and `USFOODS_USER/PASS` reach `get_vendor_config()`, which nothing calls. Login is manual-browser-only, so four plaintext credentials sit in `.env` as pure liability. | `config.py:33–38, 106` |
| F-13 | **Two containers write one SQLite file with no WAL and no busy timeout.** App and scheduler share `./data`; the default 5s lock timeout plus the N+1 read patterns make "database is locked" likely during the weekly scrape. | `docker-compose.yml:20, 48` |
| F-14 | **An LLM is asked to rewrite extracted prices.** `validate_extracted_prices()` sends parsed numbers back to Gemini to "fix any obvious errors"; whatever returns is written unchecked. A hallucinated correction is indistinguishable from a real one. | `ai_engine.py:386` |
| F-15 | **Logged-in vendor page HTML is sent to Gemini.** The selector-inference fallback ships 8,000 characters of authenticated page source — which can carry account numbers and contract pricing — to a third party. | `web_scraper.py:381` |
| F-16 | **No tests exist.** The README documents `pytest tests/` and `pytest` is in requirements, but there is no `tests/` directory. Every finding above would have been caught by one. | `README.md` |

---

## Medium

| ID | Finding | Where |
|----|---------|-------|
| F-17 | **Every Order Guide load re-parses preferences with an LLM and wipes the table.** `load_preferences()` calls Gemini then `DELETE FROM preferences` before reinserting — on a 5-minute cache, and again on every Refresh. The saved rows are never read while the file exists. | `recommendation.py:55` |
| F-18 | **Preference rules are last-one-wins and ignore their own conditions.** Only `action` is substring-matched; `condition` is never evaluated. A later exclusion recomputes the winner from scratch, discarding an earlier vendor preference — and "unless US Foods is 15% cheaper" becomes a hardcoded flat 15% for every rule. | `recommendation.py:188–224` |
| F-19 | **The trend baseline averages across vendors.** `get_average_price()` doesn't filter by vendor, so the spike/deal arrow moves when the vendor mix changes even if no vendor changed price. It also includes today's price, damping the signal. | `database.py:277–300` |
| F-20 | **Trends claims a range it doesn't use.** The caption reads "Compared to {time_range}-day average" but the value always uses the fixed 30-day `TREND_DAYS`. Moving the slider changes the label and nothing else. | `2_📈_Trends.py:292` |
| F-21 | **"Potential Savings" sums per-unit dollars across different items and units.** Adding a per-case saving to a per-pound saving produces a meaningless number; the `/unit` suffix acknowledges the problem without fixing it. | `1_📋_Order_Guide.py:82` |
| F-22 | **Savings are measured against the most expensive vendor.** "You're saving $X" compares to a price nobody would have paid, and it is the number written to `total_savings`. Against the previous price paid, or the average, it would mean something. | `recommendation.py:285` |
| F-23 | **US Foods sessions are written and read under different filenames.** The scraper saves `us_foods_auth.json` (from `"US Foods"`); Settings checks `usfoods_auth.json`. Sysco matches; US Foods never will. | `config.py:82` |
| F-24 | **Quantities don't clear after saving an order.** Resetting `order_quantities` leaves each `number_input`'s own keyed state intact, so the inputs still show the previous order. | `1_📋_Order_Guide.py:346` |
| F-25 | **Partial saves report full savings.** Items missing an `item_id`/`vendor_id` are dropped from the insert silently, then the success toast quotes the savings total including the dropped ones. | `1_📋_Order_Guide.py:329–343` |
| F-26 | **The preferences text area fights its own session state.** It passes both `value=` and an existing `key=`, and the four chip buttons mutate that key after instantiation — the pattern Streamlit warns about, so the chips are unreliable. | `3_⚙️_Settings.py:196–233` |
| F-27 | **Manual entry can create a vendor with an empty name.** Choosing "Other" renders the name field only after a rerun, so submitting immediately passes `''` to `get_or_create_vendor()`, which inserts it. | `3_⚙️_Settings.py:169–180` |
| F-28 | **`most_used_vendor` is an arbitrary row.** Selected bare under `GROUP BY i.id`, so SQLite returns whichever vendor it picks — not the most used. | `database.py:671–706` |
| F-29 | **Sample data is all stamped today, so the demo looks broken.** `add_sample_data()` says it simulates history but writes every price at `CURRENT_DATE`. The average equals the current price, so every item reads "⚪ Stable" and the trend chart is a single point on first run. | `scripts/init_db.py:132–171` |
| F-30 | **`add_prices_batch` isn't a batch.** The docstring promises "a single transaction"; it calls `add_price()` per row, each with its own connection and commit. Failures are swallowed to stdout, so the UI reports a count with no sign that rows were skipped. | `database.py:227–252` |
| F-31 | **Retry backoff exponentiates the delay, not the attempt.** `retry_delay ** (attempt + 1)` only looks right because the delay is 2. Set it to 5 and waits become 5s/25s/125s; set it to 1 and there is no backoff. | `ai_engine.py:74` |
| F-32 | **N+1 queries on the pages that load most.** `get_all_items_with_prices()` runs two queries per item; the home page adds another per item for its "Items with Prices" tile. One grouped query replaces all of them. | `database.py:302` |
| F-33 | **Dependencies are unpinned.** Every requirement is `>=` with no ceiling and no lockfile. `use_container_width` — used throughout — is already deprecated in current Streamlit, so a fresh install drifts toward warnings then breakage. | `requirements.txt` |
| F-34 | **Session validity is assumed, not checked.** `has_valid_session()` returns true if the file exists and an optimistic 30-day stamp hasn't passed. An expired cookie scrapes a logged-out page, which then feeds F-04. | `web_scraper.py:57–75` |
| F-35 | **Session refresh can't run in Docker.** It needs `headless=False` and blocks on `input()` — no display and no TTY in the container, so the recommended deployment can't complete the one manual step scraping depends on. | `web_scraper.py:104–112` |
| F-36 | **Compose bind-mounts a file that may not exist.** `./data/preferences.txt` is mounted individually; if absent, Docker creates a *directory* there and reads fail. It is also redundant with the `./data` mount above it. | `docker-compose.yml:22` |
| F-37 | **Dead code and a duplicated helper.** `_parse_price` is copied verbatim into both scrapers instead of the shared base class, and seven public methods are never called: `get_max_price_for_item`, `update_item`, `get_categories`, `get_order`, `get_vendor_config`, `GeminiEngine.generate_recommendation`, `extract_vendor_from_email`. | `web_scraper.py:402, 495` |
| F-38 | **`print()` is the logging strategy.** 56 f-string prints across `core/` and `workers/`, and 29 broad `except Exception` blocks. In Docker the useful detail lands in stdout with no level, timestamp or context — `scheduler.py` already imports `logging` and could be the model. | `core/`, `workers/` |
| F-39 | **Setup docs are stale in three ways.** `.env.example` recommends Gmail "Less secure apps", removed by Google in 2022; `.python-version` pins 3.10.13 while the Dockerfile builds on 3.11; `reportlab` is a dependency for a PDF export that is still a stub. | `.env.example:15` |
| F-40 | **Small hardening odds and ends.** The container runs as root; uploaded filenames become filesystem paths unsanitised and leak on exception; `cron_days[scrape_day]` raises `IndexError` on a bad env var; the scraper has no rate limiting between lookups. | `Dockerfile`, `scheduler.py:81` |

---

## What's already right

- **Clean layering.** `core/` has no Streamlit import anywhere — the boundary the README claims is real and holds.
- **Every query is parameterised.** No string-interpolated user input; the only f-string SQL comes from a closed internal whitelist.
- **Connections are context-managed** with commit-and-rollback in one place, so the F-03 fix lands in a single line.
- **The schema is thought through.** CHECK constraints on every enum column, sensible indexes including a composite one, `updated_at` triggers.
- **Scrapers use an ABC** with vendor-specific parts abstract — adding a third vendor is a small, obvious job.
- **`.gitignore` is right** on what matters: `.env`, `*.db` and `data/sessions/` are all covered.
- **Docstrings throughout,** with args and returns documented — which is what made a review this specific possible.
- **Graceful optional dependencies.** Playwright and imap-tools are import-guarded with actionable messages rather than crashing.

---

## Suggested order

1. **Stop the wrong recommendations** — F-01, F-04, F-05. Until these land, the core output can be confidently wrong, which is worse than being unavailable.
2. **One line, three problems** — F-03 plus WAL and a busy timeout in `get_connection()`. Cheapest fix on the list.
3. **Make the savings feature exist** — F-02, then F-22 while you're in there. An honest baseline is worth more than a big number.
4. **Stop losing vendor emails** — F-06. Fix the seen-marking first; it is independent of the PDF work and prevents further loss immediately.
5. **Close the exposure** — F-07, F-10, F-11, F-12. Deleting four unused credentials from `.env` is the fastest security win here.
6. **Then pin models and dependencies** — F-08, F-33, and add the `tests/` directory the README already promises, starting with a regression test for F-01.

---

*F-01, F-02 and F-03 were reproduced by executing `scripts/schema.sql` and the
app's own queries in SQLite. All other findings were traced by reading; none
were verified against a running instance.*

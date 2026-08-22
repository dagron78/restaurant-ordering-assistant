# Build plan — to a version a kitchen can actually run on

*Written 22 Aug 2026 against `master @ a58a121` · 150 tests green, ruff clean,
CI passing. Supersedes the "Suggested order" list in `CODE_REVIEW.md`, which the
merge of #3/#4/#5 has now largely consumed.*

Everything below is either an open finding from `CODE_REVIEW.md`, a stub the UI
already advertises, or something the review flagged and the merge didn't reach.
No new scope is invented here.

## Two product decisions, now settled

These were blocking and are answered, so the phases below can be specific:

**Savings means: versus the vendor you didn't pick.** For each line, the baseline
is the *other* vendor's current quoted price for that item — the price the
kitchen would actually have paid by choosing differently. Lines where only one
vendor quoted have no baseline and are **excluded and counted**, not folded in at
zero. This replaces "versus the most expensive vendor" (F-22), which compared
against a price nobody would have paid.

**Both stub features get built** — PDF export and email drafting. Buttons wired
to "coming soon" are worse than absent buttons, and `reportlab` is already a
dependency.

---

## Phase 0 · Finish F-01 — it is still live on the busiest screen

**Blocking. Nothing else starts until this lands.**

`f6ad58d` fixed the ranking in `get_latest_prices()`. The second ranking query —
the `latest` CTE inside `get_all_items_with_prices()`, `core/database.py:477` —
is still on the old clock:

```sql
ROW_NUMBER() OVER (PARTITION BY ph.item_id, ph.vendor_id
                   ORDER BY ph.created_at DESC, ph.id DESC)   -- unfixed
```

That CTE is what renders the Order Guide item list, so F-01 is live on the
primary screen. Worse, the two functions now **disagree with each other**: the
list and the detail view will report different "current" prices for the same
vendor. `get_all_items_with_prices()`'s own docstring claims it is "matching
`get_latest_prices` semantics", which is no longer true. Reproduced against
`master @ a58a121` with the real schema:

```
get_all_items_with_prices (Order Guide list):
    -> best = Sysco @ $18.00 (dated 2026-08-14)     <- week-old backfill wins
get_latest_prices        (already fixed):
    -> best = Sysco @ $22.00 (dated 2026-08-21)     <- correct
```

Neither `test_old_history_still_excluded` nor
`test_backfill_does_not_shadow_current_price` calls
`get_all_items_with_prices()`, which is why green tests didn't catch it.

**Work**

1. Apply the same `ORDER BY ph.date_recorded DESC, ph.created_at DESC, ph.id DESC`
   to the CTE, and carry the explanatory comment across.
2. Correct the docstring's "matching `get_latest_prices` semantics" claim, or make
   it true by construction — see the standing rule on shared ranking logic below.
3. **Parametrize both existing F-01 regression tests over both entry points** so
   any future ranking query has to pass the same adversarial fixture.
4. Add an agreement test: seed one fixture, assert `get_latest_prices(item)` and
   the corresponding rows from `get_all_items_with_prices()` return the same
   vendor→price mapping. That test is what makes a third divergence impossible.

**Consider factoring the ranking into one place.** Two copies of a
correctness-critical window function is what produced this; a shared SQL constant
or a single `_latest_price_rows()` helper would have made Phase 0 unnecessary.

**Gate:** the agreement test exists and fails against `a58a121`.

---

## Phase 1 · Run the thing (before any new feature work)

All 150 tests deliberately avoid Streamlit, and `CODE_REVIEW.md` closes by noting
that **nothing has ever been verified against a running instance**. Every phase
after this one builds on the assumption that the app boots, which is currently
unevidenced. This is the cheapest high-information step on the list.

**Work**

1. `python scripts/init_db.py --reset --sample-data`, then
   `streamlit run app/main.py`, with `APP_PASSWORD` set and then unset.
2. Walk all three pages and every control: item add, quantity entry, order save,
   the Trends range slider, Settings upload, the preference chips, the Danger Zone
   confirmations.
3. Write down every runtime defect. Expect at minimum the `use_container_width`
   deprecation (F-33) and possibly the F-26 chip behaviour.
4. Capture a screenshot per page — they double as the README's stale screenshots.

**Gate:** a defect list in `docs/RUNTIME_WALKTHROUGH.md`. Anything critical found
here gets triaged into the phases below before they start; a broken boot outranks
a savings-metric refactor.

*This Mac's Chrome automation has bitten us before: run
`list_connected_browsers` first and confirm the local browser, serve over
`127.0.0.1` rather than `file://`, and note the automated tab is `document.hidden`
so animation frames are frozen.*

---

## Phase 2 · Make the numbers honest — F-19, F-21, F-22

The decision above resolves the semantics. The unit-summing bug (F-21) then falls
out for free: **extended dollars are additive, per-unit deltas are not**. Multiply
by quantity before summing and a per-case saving and a per-pound saving can share
a total legitimately.

**Work**

1. **Baseline at write time.** When an order is saved, record for each line the
   alternative vendor and its price alongside what was paid — `order_items` already
   carries `avg_price`/`max_price`; add `alt_vendor_id` and `alt_price` beside
   them. Baselines must be frozen at order time, not recomputed later from prices
   that have since moved.
2. **Needs a migration.** The schema is created once from `schema.sql` and there is
   no migration path, so existing databases won't gain the columns. Add the
   smallest honest thing: a versioned `ALTER TABLE` step in `init_db.py` guarded by
   `PRAGMA user_version`. This is the first schema change since the app had real
   data in it and the pattern will be needed again.
3. `create_order()` computes `savings = qty × (alt_price − unit_price)` per line,
   only where an alternative quote existed; single-quote lines are excluded and
   the count is returned so the UI can say so.
4. **F-19:** give `get_average_price()` a vendor filter and exclude today, so the
   trend arrow tracks one vendor's movement rather than the vendor mix.
5. Relabel every savings surface to state its baseline. `total_savings` currently
   holds the vs-most-expensive figure — decide explicitly whether to backfill it,
   or leave historical rows and label them by schema version.

**Gate:** tests for single-quote exclusion, mixed units in one order, an order
where the cheaper vendor was *not* chosen (savings must go negative or zero, never
clamp silently), and the excluded-line count reaching the UI.

---

## Phase 3 · Make the recommendation smart — F-17, F-18, F-26

This is the product's headline claim ("Combines price data with your preferences")
and it is the largest remaining functional gap. Today `load_preferences()` calls
Gemini on every Order Guide load and `DELETE`s the preferences table before
reinserting, and rule `condition` text is never evaluated at all — only `action`
is substring-matched, with a flat hardcoded 15% standing in for whatever the rule
actually said.

**Work**

1. **Stop re-parsing.** Hash `preferences.txt`; re-parse only when the hash
   changes. Read the stored rows the rest of the time, and stop deleting the table
   on a read path.
2. **Evaluate conditions deterministically.** The LLM's job is turning prose into
   structured rules; it should not be in the decision path. Parse each rule to a
   small typed predicate (item pattern, comparator, threshold, vendor) and evaluate
   it in Python. A rule's own threshold replaces the hardcoded 15%.
3. **Compose by priority instead of last-one-wins.** Apply rules in priority order
   and let each narrow the candidate set, so an exclusion no longer discards an
   earlier vendor preference by recomputing from scratch.
4. **F-26:** stop passing both `value=` and `key=` to the preferences text area,
   and have the chip buttons write state before the widget instantiates.
5. Surface *why* a vendor won — which rule fired — on the Order Guide row. A
   recommendation the manager can't audit won't be trusted, and it makes this phase
   testable by inspection.

**Gate:** a rule-matrix test — every rule type, conditions both true and false,
two rules in conflict, and a rule referencing an item that no longer exists.

---

## Phase 4 · Trust the inputs — F-34, F-35

Phase 0's and F-04's correctness work only matters if the page being scraped is a
logged-in page. `has_valid_session()` returns true whenever the file exists and an
optimistic 30-day stamp hasn't passed, so an expired cookie scrapes a logged-out
page and feeds whatever it finds into the price table.

**Work**

1. Probe for an actual logged-in marker before scraping; treat "login form
   present" as an expired session and abort the run rather than recording prices.
2. Fail loudly — a scrape that can't authenticate should surface in the UI and the
   processing log, not pass silently with zero rows.
3. **F-35** is a documentation fix, not a code one. Headful Chrome and `input()`
   cannot work in the container; the honest answer is refreshing sessions on the
   host and mounting `data/sessions/` in. Write that down and remove the
   in-container instructions that can't succeed.

**Gate:** a test that a fake logged-out page yields zero stored prices and one
logged error, not a price.

---

## Phase 5 · Finish the advertised features

**PDF export.** A printable order sheet grouped by vendor: item, quantity, unit,
unit price, line total, per-vendor subtotal, order total and date. This is the
artifact that gets carried to the walk-in, so plain and legible beats styled.

**Email draft.** One draft per vendor, pre-filled from the order. Generate a draft
the manager reviews and sends — do **not** silently send on button press. Emitting
a downloadable `.eml`, or displaying copy-ready text, avoids adding an outbound
SMTP surface to an app whose only auth is a shared password.

**Gate:** extract the text back out of the generated PDF and assert the totals
match the order; assert the `.eml` parses and addresses the right vendor. Both
must work with no network.

---

## Phase 6 · Operational maturity

Nothing here changes behaviour, and all of it makes the next change safer.

- **`google-generativeai` → `google-genai`.** Support has ended; the deprecation
  warning fires on every test run. Doing this while the AI paths have fresh test
  coverage is much cheaper than doing it later.
- **F-38 · logging.** Replace 56 `print()` calls with the `logging` module —
  `workers/scheduler.py` already does it right. Narrow the 29 bare
  `except Exception` blocks while passing through; each one is a place a failure
  currently looks like success.
- **F-33 · pin dependencies.** Ceilings plus a lockfile, and fix the
  `use_container_width` deprecation rather than pinning Streamlit back to hide it.
- **F-37 · remove dead code.** The unused public methods named in the finding.
  Check each against the phases above first — Phase 2 may legitimately revive
  `get_max_price_for_item`.

**Gate:** CI runs one job with warnings as errors.

---

## Phase 7 · Verification — F-16 remainder

- Streamlit UI tests via `streamlit.testing.v1.AppTest`, which needs no browser and
  belongs in CI. Cover the auth gate (set and unset), order save, and the Danger
  Zone confirmations.
- Re-run the Phase 1 walkthrough and diff against the defect list.
- Refresh the README screenshots from the Phase 1 captures.

**Gate:** the walkthrough is clean, and every finding in `CODE_REVIEW.md` reads
Fixed, or Won't-fix with a stated reason.

---

## Working agreement

Five rules, each one earned by something that actually happened in this project.

**1. Verify claims against `origin/master`, not the working tree.** Phase 0 exists
because a completion report said the fix landed in "both `get_latest_prices()` and
the CTE" when only one had changed. Before reporting a fix, re-read it from the
pushed ref.

**2. When a fix has more than one call site, prove the count is zero.** Paste the
grep. For Phase 0 that is:

```
git show origin/master:core/database.py | grep -c "ORDER BY ph.created_at DESC"
```

A fix is finished when that returns 0, not when the first hit is patched.

**3. Adversarial test first, for anything touching money.** Both re-opened
findings (F-01, F-04) were green when they shipped, because each test exercised
only the axis where the fix already worked — F-01's inserted chronologically,
F-04's used obviously-unrelated tiles. Write the reversed, near-miss, or malformed
case, watch it fail, then fix. `docs/repro/` has four worked examples; the
technique needs no venv, no API key and no browser.

**4. One phase per branch, one PR per phase, at most two deep.** Four stacked PRs
with nothing merged made review cost compound and put every branch one `master`
change away from four rebases. Merge commits, never squash, when a stack does form.

**5. Update `CODE_REVIEW.md`'s status table in the same PR as the fix.** It is now
the only place the true state of 40 findings lives, and it is only worth trusting
if it is never behind.

---

## Sequencing

Phase 0 blocks everything. Phase 1 gates the rest, because a runtime defect found
there may re-order what follows. Phases 2 and 3 are the substance — honest numbers
and a working preference engine are what make this a tool a kitchen would rely on
rather than a demo. Phase 4 protects their inputs. Phase 5 is the visible payoff,
and it is deliberately after correctness. Phases 6 and 7 are the ones that keep it
alive after this push ends.

Phase 3 is the largest single piece and the one most likely to need a second pass.
Phases 2 and 4 are independent of each other and could run in parallel if there
were two of us on it; nothing else here is safely parallel.

# Handoff

*For whoever picks this up next — a fresh agent session, a new contributor, or the
same people after a gap. Written 22 Aug 2026 at `master @ fd214cb`, with the build feature-complete.*

## What this is

A Streamlit + Gemini tool that tells a restaurant kitchen which vendor to buy each
item from, and what that choice saved. Two vendors today (Sysco, US Foods),
designed for more.

**The product is its two intake paths.** Everything else is arithmetic on what they
bring in:

1. **Email** — a dedicated address receives weekly price sheets from any vendor
   that chooses to send them. Attachments are parsed by Gemini into `price_history`.
2. **Portals** — Playwright scrapes signed-in vendor sites for contract pricing.

Neither has yet run against a real mailbox or a real signed-in session. That is the
single largest gap between this build and a working weekly cycle.

## State in one table

| | |
|---|---|
| Branch | `master @ fd214cb`, 78 commits, 24 merged PRs |
| Tests | 242 passing, 1 skipped (deliberate live-API test), 3 deselected |
| Python | 3.11 everywhere — `.python-version`, `requires-python`, ruff target, CI, Docker |
| Local venv | `./venv` — **must be uv-managed 3.11**, not the Xcode 3.9 that caused #13 |
| CI | lint · tests · docker build · warnings-as-errors |
| Original review | 40 findings in `docs/CODE_REVIEW.md`, all Fixed or Won't-fix bar one partial |
| Phases 0–7 + intake | all merged — the build is feature-complete |

## Establish state in sixty seconds

```bash
cd ~/restaurant-ordering-assistant
git fetch --prune origin
git log --oneline -5 origin/master
./venv/bin/python -V                       # must say 3.11.x
./venv/bin/python -m pytest -q -p no:warnings | tail -1
gh issue list --state open
gh pr list --state open
```

Then read, in this order: `docs/BUILD_PLAN.md` (the eight phases and the working
agreement), the status table at the end of `docs/CODE_REVIEW.md` (the authoritative
per-finding state), and the open issues.

## The working agreement

Five rules. Each was earned by something that actually went wrong here, and the
cost of each is recorded in `docs/CODE_REVIEW.md`'s provenance note.

1. **Verify claims against `origin/master`, not a working tree or a report.** Five
   separate completion reports have described more than the diff contained.
2. **When a fix has more than one call site, prove the remaining count is zero.**
   Paste the grep. Include `*.md`, `*.example`, `*.toml`, `*.yml` — a fix once
   looked complete because the grep only covered `*.py`.
3. **Adversarial test first, for anything touching money or trust.** Write the
   reversed, near-miss or malformed case, watch it fail, then fix.
4. **One phase per branch, one PR per phase, at most two deep.** Merge commits,
   never squash, when a stack forms.
5. **Update the `CODE_REVIEW.md` status row in the same PR as the fix.**

### The rule underneath all of them

> A finding is Fixed only when a test or a runtime observation exercises the
> specific failure axis. Diff inspection establishes intent, not outcome.

Four findings were marked Fixed from the diff and all four were wrong — F-01 (the
fix reached one of two ranking sites), F-04 (a threshold that was a near-no-op on
the real catalogue), F-39 (one part of three), F-24 (desktop widget keys only).

## Verification: mutate, don't grep

The habit that catches what tests miss: **change the code to reintroduce the bug
and confirm a specific test dies.** A passing suite proves the tests run; a killed
mutant proves they *test*.

```bash
# reintroduce the bug, run the suite, restore
python3 - <<'PY'
import pathlib
p = pathlib.Path('core/database.py'); s = p.read_text()
p.write_text(s.replace("min(candidates", "max(candidates", 1))
PY
./venv/bin/python -m pytest -q -p no:warnings | tail -3
git checkout origin/master -- core/database.py
```

Mutants that must stay killed:

| Mutate | Must fail |
|---|---|
| `min` → `max` in `pick_cheapest_alternative` | three-vendor + parity tests |
| drop the `qty *` in a line total | three tests |
| auth gate fall-through `False` → `True` | `test_neither_marker_nor_login_form_fails_closed` |
| `has_valid_session` → always `True` | two session-validity tests |
| vendor lookup always resolves | five intake tests incl. the spoofing matrix |
| `_clean_json_response` → passthrough | `test_parser_matches_golden_outputs` |

Cheap reproductions live in `docs/repro/` — stdlib `sqlite3` against
`scripts/schema.sql`, no venv, no API key, no browser.

## What is open

| | Needs |
|---|---|
| **slow_ui tests** | **three of four `AppTest` UI tests never run.** `pyproject.toml` sets `addopts = "-q -m 'not slow_ui'"` and no job runs `-m slow_ui`, so the auth-gate test — the control Phase 4 made fail-closed — is deselected in every run. `-rs` shows skips, not deselections, so nothing reports it. Add a CI job that runs the marker |
| **dead filterwarnings** | `pyproject.toml` still ignores `google.generativeai` deprecations "pending migration" — that migration completed in Phase 6 |
| **#26** Auth selectors | **credentials.** `AUTH_POSITIVE_SELECTORS` are placeholders; the first real scrape aborts until they are tuned to a live signed-in DOM. Fails closed, so it blocks rather than corrupts |
| **#18** Multi-vendor | largely absorbed by intake; the scraper-per-vendor remainder stands |
| **#28** Intake | merged at `152de62` but the issue is still open — close it |

## What needs a human, not code

- **Vendor portal credentials** — to tune #26's selectors and prove a real scrape.
- **The intake mailbox** — `EMAIL_USER`/`EMAIL_PASS` in `.env`, placed by hand.
- **A Gemini key** *only* if golden fixtures are ever recaptured. Normal test runs
  replay `tests/fixtures/golden_prefs/*.json` and need no key.

**Credential handling:** the user places secrets in `.env` themselves. Nothing
writes a key into a file, a log, a fixture or a test default. `.gitignore` covers
`.env`, `.dockerignore` covers `.env*`, and no credential has ever reached a ref —
verified by scanning every branch for `AQ.` and `AIza` patterns.

## Things that will bite you

- **The venv silently being the wrong Python.** Xcode ships 3.9 at
  `/Applications/Xcode.app/.../python3.9`; a venv built from it satisfies nothing
  and complains about nothing. Print `./venv/bin/python -V` before citing any test
  result.
- **`schema.sql` and the migrations are two sources of truth.** Every test builds
  from a fresh `schema.sql`, so a broken migration passes the whole suite and fails
  on every real database. `tests/test_migration.py` has the structural-identity
  test that catches this — keep it.
- **Skipped tests read as green.** CI runs `pytest -rs` so skips are listed. One
  skip is legitimate and permanent (the live-API capture); a second one appearing
  is a signal.
- **A silent drop is a bug, not a default.** The intake mailbox quarantines unknown
  senders rather than discarding them, precisely because the address exists for
  vendors nobody has added yet.
- **Quarantine is attacker-writable.** Anyone can email the address. Its rows are
  untrusted display data: escaped, capped, basename-only, never parsed until a
  human promotes the sender.

## Where the knowledge lives

- `docs/BUILD_PLAN.md` — the eight phases, the two settled product decisions, the working agreement
- `docs/CODE_REVIEW.md` — the 40 findings, the per-finding status table, the provenance note
- `docs/REVIEW_2026-08-21.md` — the second-pass review that reopened F-01 and F-04
- `docs/RUNTIME_WALKTHROUGH.md` — Phase 1, the first time the app was ever run (on 3.9; superseded by Phase 7's re-run)
- `docs/repro/` — runnable reproductions of the findings that mattered
- GitHub issues — the live work; every phase has one, closed with its verification evidence

## Two settled product decisions — do not re-litigate

1. **Savings is measured against the cheapest alternative vendor** — the price the
   kitchen would actually have paid by choosing differently. Not vs the most
   expensive (that was F-22). Lines where only one vendor quoted are **excluded and
   counted**, never folded in at zero.
2. **Both advertised features are built** — the PDF order sheet and the vendor
   email drafts. Drafts are review-and-send; `core/exports.py` has no outbound SMTP
   surface and `tests/test_no_send_guard.py` keeps it that way.

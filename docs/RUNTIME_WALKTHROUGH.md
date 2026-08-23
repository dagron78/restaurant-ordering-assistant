# Runtime Walkthrough — Phase 1

**Date:** 22 Aug 2026 · branch `phase/1-runtime-walkthrough` · Streamlit 1.50.0 · Python 3.9 (local venv)

> **SUPERSEDED by the Phase 7 re-run below** — Phase 1 ran on Python 3.9
> against a much earlier codebase and never tested the unset-password state.
> The re-run below was performed on Python 3.11.15 against master @ `152de62`
> with all seven phases merged.

## Phase 7 re-run (22 Aug 2026, Python 3.11.15, master @ 152de62)

### D9 · CRITICAL — no APP_PASSWORD hides the entire navigation (issue #37)

The `render_login()` gate emitted the `data-preauth` marker **before**
checking whether a password was required, then returned early on the
no-password branch with the marker still on the page — hiding the sidebar
from users who were never asked for credentials. The app rendered as a
landing page with no navigation.

**Why it survived:** Phase 7's walkthrough "re-run" refreshed screenshots
with `APP_PASSWORD` set but did not test the unset-password state against
the finished UI. The three AppTest tests covering this path were deselected
by `-m 'not slow_ui'` until PR #36 landed, and two are now xfail because
AppTest cannot drive st.form submit buttons. The gate's rendering path has
never been executed by a passing test until now.

**Fixed in this phase.** Marker moved below the early return; regression
test added to the DEFAULT pytest invocation; all three auth states verified
in-browser with Playwright screenshots attached to PR #37.

### Verified auth states (post-fix)

| State | Sidebar | Nav links | Gate | Pages render |
|---|---|---|---|---|
| Unset (open access) | visible | 5 (Home/OG/Trends/Settings/HTW) | warning banner | ✓ |
| Set, pre-auth | absent | 0 | sign-in form only | n/a |
| Set, post-auth | visible | 5 | none | ✓ |


**Method:** real server on `127.0.0.1:8501`, driven headlessly by Playwright's
own bundled Chromium (not any paired Chrome). Server logs captured per pass.
First time anything in this repo has been verified against a running instance.

## Boot matrix

| Config | Result |
|---|---|
| `APP_PASSWORD` set, API key set | ✅ gate → login → all pages render |
| `APP_PASSWORD` set, API key **empty** | ❌→✅ Order Guide & Trends crashed (D1), now guarded |
| `APP_PASSWORD` **unset** | ⚠️ fail-open with loud banner on every page (by design; screenshot 07) |

## Defects found and fixed in this phase

**D1 · CRITICAL — primary pages crashed without an API key.**
With `GOOGLE_API_KEY` unset, Order Guide *and* Trends rendered raw
`ValueError: GOOGLE_API_KEY not configured` + traceback (`get_engine()` /
`RecommendationEngine()` at module scope). `main.py` handled the same state
gracefully; the two busiest pages did not. **Fixed:** try/except guards with
setup guidance + `st.stop()` on both pages (screenshot 06).

**D2 · CRITICAL — Settings ▸ Data tab dead: `KeyError: 'sysco'`.**
The F-12 credential removal (#5) swept config/docs but missed the validation
table at `3_⚙️_Settings.py:417`, which still read `validation['sysco']` /
`validation['usfoods']`. The entire Data Management tab — Danger Zone
included — crashed on open. **Fixed:** stale rows removed; grep for
`validation['sysco']|validation['usfoods']` across `*.py` now returns 0.

**D3 · HIGH — quantities did not clear after saving an order.**
Two layers deep:
1. The F-24 fix in #3 popped only desktop keys (`qty_{item}`); card view uses
   `qty_mobile_{item}` — so the default mobile view never cleared.
2. Even popping both styles was insufficient: these widgets live inside
   `st.form`, and form-buffered values replay client-side regardless of
   server-side `session_state` deletion.
**Fixed:** widget-key namespace rotation (`order_form_version` counter baked
into every quantity input's key) + post-save `st.rerun()` with a flash
message. Verified in-browser: inputs read `[0, 0, 0]` after save, flash shows.

## Defects found, triaged to later phases

| ID | Severity | Finding | Triage |
|----|----------|---------|--------|
| D4 | MEDIUM | Auth is lost on any full page load / refresh / direct URL entry (`st.session_state` is websocket-scoped; only soft sidebar navigation persists) | Phase 7: document + AppTest coverage; cookie persistence optional |
| D5 | LOW | Sidebar nav + "Deploy" visible pre-auth (content blocked, chrome exposed) | Accept behind shared password; revisit if real auth lands |
| D6 | MEDIUM | `use_container_width` deprecation warnings spam server log on Streamlit 1.50 ("will be removed after 2025-12-31") | Phase 6 batch (F-33/F-38) |
| D7 | FLAKE | One ambiguous automation result (`reset_clear_word_relocks`) — timing-suspect, not reproduced as app bug | Phase 7 AppTest deterministic coverage |
| D8 | LOW | Watchdog suggestion in server logs | Optional, Phase 6 |

## Verified working (no action needed)

- Auth gate renders pre-login; wrong password shows "Incorrect"; correct password logs in
- **Danger Zone semantics fully correct:** Clear disabled until its checkbox;
  Reset needs typed `RESET` **and** both confirmations; unchecking relocks;
  clearing the word relocks
- **Savings dashboard reflects saved orders at runtime** ($46.77 spent,
  $13.71 saved, Orders 1 after a save) — F-02 fix confirmed end-to-end
- Trends: item select, slider labels, "Compared to {N}-day average" caption
  honors the selected range (F-20) — `$24.67 @ 90 days`
- Preference chips append reliably on repeat clicks (F-26 not reproducible on
  Streamlit 1.50)
- Sample data produces deals/spikes/alerts and multi-point trend charts (F-29)
- CLI `--reset` WAL concern tested with an open handle: SQLite's salt check
  discards the stale WAL — no resurrection. (Settings' reset already cleans
  sidecars.)

## Ops notes

- A stale Streamlit process held port 8501 through two "restarts" (new
  instances died with "Port 8501 is already in use"), which briefly made the
  no-key guard test measure a server that still had the old key in memory.
  Kill by port (`lsof -t -iTCP:8501`), not by remembered PID file.
- Screenshots for this phase live in `screenshots/walkthrough/`.

## Gate

Phase 1 gate met: defect list recorded (this file), critical items fixed
in-phase, remaining items triaged into Phase 6/7 before Phase 2 starts.

# Product specification

*Written 23 Aug 2026, from Charles's description. This is the first actual
specification this project has had — everything before it was built from a
40-finding code review of pre-existing code, which is why the engine is sound and
the product surface is thin. Where this document contradicts
`docs/BUILD_PLAN.md`, this document wins.*

## The shape of it

A price-intelligence and ordering tool that lives on a computer in the restaurant
and is used from a phone on the same wifi.

```
 vendor price sheets ──email──▶ ┌──────────────────┐
 vendor portals ─────scrape──▶  │  restaurant box  │ ◀──wifi──▶ manager's phone
                                │  (app + SQLite)  │
                                └────────┬─────────┘
                                         └──email──▶ vendor orders
```

## The ordering round — the flow that matters

1. **The order sheet is already there.** The kitchen's standing list of what it
   buys — uploaded once at install, editable after. The manager never builds a
   list from scratch.
2. **The manager walks the sheet on their phone**, entering quantities. This is
   the primary interface, on a phone, over wifi. Not a desktop screen that
   reflows.
3. **They hit Send.**
4. **The app builds a suggested purchasing plan** — for each line, which vendor
   and why, applying current prices and management's rules.
5. **The draft plan appears on the phone.** Every suggestion is overridable: the
   manager can change the vendor or the quantity on any line, easily, without
   leaving the flow.
6. **They confirm, and the app builds the order** — one order per vendor. **It
   does not send it.** The manager chooses how to place each order: they may
   prefer to phone a rep and confirm there are no issues.
7. **Everything is kept**: what was ordered, from whom, at what price, against
   which alternative, under which rule.

The critical difference from what exists today: the app currently shows
recommendations *first* and the manager picks against them. The spec is
**request, then plan** — the manager says what they need, the app proposes how to
buy it, the manager overrides what they disagree with.

## Roles and secrets

**Two passwords.**

| Password | Grants |
|---|---|
| **App password** | the ordering round: order sheet, quantities, plan review, override, confirm, history |
| **Admin password** | everything above, plus all configuration |

One shared secret per role — not per-user accounts. That is proportionate: one
kitchen, one manager ordering, management setting rules.

## Configurability — the current biggest gap

> "These rules should be easily configurable — as should any part of the application."

Today **15 settings live in `.env`** and every change needs shell access and a
restart: the API key, the mailbox, the app password, the scrape schedule, vendor
URLs, thresholds. That is the single largest gap between this codebase and the
spec.

**Everything an operator or admin needs to change must be changeable behind the
admin password, in the app, without a restart.** `.env` retains only what is
needed to boot far enough to read the rest: the database path and the initial
admin password.

Honest note on secrets: config including the API key and mailbox password moves
into the local SQLite file. On a single-tenant box that is roughly equivalent to
`.env` on the same disk — both readable by anyone with filesystem access. The
gain is that the admin UI can write them. This is a **trusted-LAN,
single-tenant** security model, and it should be stated as such rather than
implied.

## Install

Done by us at install time, but **a reasonably technical person should be able to
do it unaided** — possibly with AI help. That sets the bar: a documented,
scripted install and a first-run admin setup page, not a wizard that assumes no
technical knowledge, and not a README instructing someone to hand-edit files.

## Vendor connections

Both intake paths must be connectable **from the app**, not from a terminal:

- **Email** — the app has its own provisioned mailbox, polled on a schedule.
  Unknown senders quarantine for review rather than being dropped.
- **Portals** — connecting a vendor means logging into that vendor's site. A
  headless box cannot show a login form, so this needs a decision (see below).

Today `Settings → System` has "Refresh Sysco Login" buttons that print CLI
instructions. That is not a connect flow.

## What changes from earlier decisions

**Nothing sends itself — confirmed.** An earlier draft of this document said
sending was now required and that `tests/test_no_send_guard.py` should be
replaced. That was wrong: confirming *builds* the order, and the manager places
it however they choose. The no-send guard stands exactly as written, and no
outbound mail surface is added to a LAN-exposed app.

**LAN exposure is now a requirement, not a finding.** F-10 flagged
`0.0.0.0:8501` with no login as a risk. The spec requires phone access over wifi,
so the shared password stops being a mitigation and becomes the security model.
That raises the stakes on it being settable in-app and on the admin/app split
being real.

## Already built and verified — do not rebuild

- Email intake with parsing, quarantine of unknown senders, vendor identity from the `vendors` table
- Best-vendor selection: cheapest alternative, single-quote lines excluded and counted, baseline frozen at order time
- Management rules: natural language → typed predicates, priority-composed, per-rule thresholds
- Per-vendor order PDF and per-vendor email draft generation
- Scheduled email and scrape jobs
- Full history: prices, orders, savings basis, processing log
- 253 tests, eleven behavioural properties each pinned by a mutation-verified guard (`docs/HANDOFF.md`)

## Decisions, settled

**The restaurant computer has a display.** So "Connect Sysco" opens a real
browser on the box for the manual login and captures the session locally — a
genuine connect flow, not a button that prints CLI instructions. This decides the
deployment: **the app runs natively on the box, not in headless Docker.** F-35
(session refresh needs a TTY) is resolved by that choice rather than by
documentation. The Dockerfile stays for development but stops being the
recommended deployment.

**Confirming builds the order; it does not send it.** See above.

**The order sheet is a spreadsheet.** So import is a **deterministic parse**
(`openpyxl` / `csv`), never an AI extraction — it is structured data, and parsing
it locally is free, instant, needs no API key and cannot hallucinate a quantity.
The kitchen's sheet will not use our column names, so import needs a one-time
**column-mapping step**: point *their* headers at item / unit / par.

Note a live defect on this exact path: `Config.VALID_EXTENSIONS` already permits
`.xlsx`, `.xls` and `.csv`, but `parse_document()` sends anything that is not a
PDF to `PIL.Image.open()`. Uploading a CSV today raises
`UnidentifiedImageError`. The app invites a spreadsheet and crashes on it.

**Par levels prefill the sheet.** Each item on the order sheet carries a normal
quantity. The sheet opens pre-filled and the manager adjusts from there rather
than starting at zero.

**The manager chooses how to place each order.** They may want to speak to a rep.
So the outputs have to serve more than email: a per-vendor sheet that is
**readable aloud over the phone** — vendor, item, quantity, unit, and the price
being expected — as well as a PDF to print and a draft to copy or attach.

**Two ordering modes, admin-selectable.**

| Mode | Flow | Suits |
|---|---|---|
| **Plan-after** (default) | walk the sheet → Send → suggested plan → override → confirm | working from par levels; keeps "how much do we need" separate from "where do we buy it" |
| **Plan-during** | prices and best-vendor shown inline while entering quantities | reacting to deals — "avocados are down 12%, take four cases" |

Plan-during is what exists today, so the toggle makes the current Order Guide one
of two modes rather than work to be discarded.

**Vendor override is missing in both modes and is new work either way.** Today
`vendor_id` comes from whatever the engine picked and is written straight to the
order line; the only `radio` on the Order Guide is the Cards/Table view switch.
The manager can change *how much* but never *from whom*. Build the override once
as a shared component and place it inline in plan-during and on the plan screen
in plan-after.

---

## Build order

Each phase leaves the app more usable than it found it. Phase A first because
everything else is easier once configuration is not a file on a server.

**A · Configuration surface.** Two passwords — app and admin. The 15 `.env`
settings move into the database behind the admin password, changeable without a
restart. `.env` keeps only what is needed to boot: database path and the initial
admin password. First-run page to set both passwords and the API key. *This is
the phase that answers "I can't log in and I can't set the API key."*

**B · The order sheet.** Par levels in the schema; deterministic spreadsheet
import with column mapping; fix the `PIL.Image.open()` crash on spreadsheets.

**C · The ordering round.** Phone-shaped sheet view prefilled from par; Send;
the suggested-plan screen; the vendor-override component; the mode toggle;
confirm builds and stores the order.

**D · Outputs.** Per-vendor sheet readable aloud, PDF to print, draft to copy or
attach. Nothing sends itself.

**E · Portal connection.** In-app Connect flow launching a browser on the box;
tune `AUTH_POSITIVE_SELECTORS` against the live signed-in DOM (#26); native
deployment documented.

**F · First real intake.** Provision the mailbox; a real vendor price sheet
landing in `price_history` end to end. The worker equivalent of Phase 1.

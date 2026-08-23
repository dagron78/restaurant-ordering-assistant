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
6. **They confirm, and the orders go to the vendors** — one order per vendor,
   sent from the app.
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

**Sending email is now required.** `core/exports.py` was deliberately built with
no SMTP surface, guarded by `tests/test_no_send_guard.py`. That was the right
default for drafts and is now wrong. Sending must exist — behind an explicit
confirm, with the draft shown first, and with a record of what was sent. The
guard should be replaced by one asserting nothing sends *without* confirmation,
which is the property actually worth protecting.

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

## Open decisions

1. **Portal login on a headless box.** Either the admin runs a helper on a laptop
   and uploads the session file through the admin UI, or the restaurant computer
   has a display and the app launches a local browser for the login. The second
   is a better experience and constrains the deployment (native on the box rather
   than headless Docker). Needs a call.
2. **Does confirming a plan send immediately, or queue for a second look?** The
   spec says the manager confirms and it goes. Worth deciding whether there is
   any hold at all, because unsending an order to a vendor is not possible.
3. **Order sheet format.** What does the kitchen's existing sheet look like — a
   spreadsheet, a vendor's order guide export, paper? That determines whether
   "uploaded at install" is a parse job or a data entry job.

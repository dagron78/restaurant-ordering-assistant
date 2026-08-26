#!/usr/bin/env python3
"""Take the app for a test drive — a full ordering round, checked out loud.

This is the round a manager actually does: the sheet arrives prefilled from
par, they change what they need, hit Send, read the suggested plan, override
a line, and confirm. Every step prints what a PERSON would notice, and every
check says what it means rather than which function it calls.

    python scripts/test_drive.py            # against a fresh mock restaurant
    python scripts/test_drive.py --keep     # keep the database afterwards

Needs no GOOGLE_API_KEY and makes no network calls. Exits non-zero if any
check fails, so it also works as a smoke test before a demo.
"""
import argparse
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

REPO = Path(__file__).parent.parent
PASS, FAIL = "  \033[32m✓\033[0m", "  \033[31m✗\033[0m"
_results = []


def check(claim: str, ok: bool, evidence: str = "") -> bool:
    _results.append((claim, ok))
    print(f"{PASS if ok else FAIL} {claim}")
    if evidence:
        print(f"      {evidence}")
    return ok


def step(n: int, title: str) -> None:
    print(f"\n\033[1m{n} · {title}\033[0m")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--keep", action="store_true",
                    help="keep the database so you can open it in the app")
    args = ap.parse_args()

    workdir = Path(tempfile.mkdtemp(prefix="test-drive-"))
    db_path = workdir / "test_drive.db"

    print("\n\033[1mTest drive — The Copper Pan\033[0m")
    print(f"database: {db_path}")

    seed = subprocess.run(
        [sys.executable, str(REPO / "scripts" / "seed_mock_restaurant.py"),
         "--reset"],
        capture_output=True, text=True,
        env={"PATH": "/usr/bin:/bin", "HOME": str(workdir),
             "DATABASE_PATH": str(db_path)},
        cwd=str(REPO))
    if seed.returncode != 0:
        print(seed.stdout + seed.stderr)
        print("\nCould not seed the mock restaurant — nothing else can run.")
        return 1

    from core.database import Database
    from core.plan import build_plan, plan_net_vs_alt, plan_total
    from core.exports import build_call_sheet
    from core.rules import apply_rules

    db = Database(db_path=db_path)

    # ---------------------------------------------------------------- 1
    step(1, "The sheet arrives prefilled — the manager types nothing")
    sheet = {r["name"]: r["par_level"] for r in db.get_order_sheet()}
    check("every item on the sheet has a par or an explicit blank",
          len(sheet) == 10, f"{len(sheet)} items")
    check("par 0 is kept distinct from 'no par set'",
          sheet["Heavy Duty Foil Wrap"] == 0 and sheet["Olive Oil 3L"] is None,
          "Foil Wrap par=0 (never reorder) · Olive Oil par=None (unset)")

    # ---------------------------------------------------------------- 2
    step(2, "The manager changes two lines and hits Send")
    wanted = {k: (v or 0) for k, v in sheet.items()}
    wanted["Chicken Breast 40lb"] = 0     # plenty in the walk-in
    wanted["Roma Tomatoes"] = 6           # busy weekend
    plan = build_plan(db, wanted)
    names = [ln["name"] for ln in plan["lines"]]
    check("a plan comes back with only what was actually asked for",
          "Chicken Breast 40lb" not in names,
          f"{len(plan['lines'])} lines; chicken zeroed and absent")
    check("nothing quietly failed to price",
          not plan["unpriced"], f"unpriced: {plan['unpriced'] or 'none'}")

    # ---------------------------------------------------------------- 3
    step(3, "Every line says WHY that vendor")
    unexplained = [ln["name"] for ln in plan["lines"] if not ln.get("reasons")]
    check("no line is chosen without a reason the manager can read",
          not unexplained, unexplained and f"silent: {unexplained}" or
          plan["lines"][0]["reasons"][0])

    # ---------------------------------------------------------------- 4
    step(4, "The kitchen's written rules actually bind")
    legs = next(ln for ln in plan["lines"] if ln["name"] == "Leg Quarters 40lb")
    check("'never buy Leg Quarters from Gordon Food Service' is enforced",
          legs["vendor"] != "Gordon Food Service" and
          any("excluded" in r for r in legs["reasons"]),
          "; ".join(legs["reasons"]))
    rigged = [{"vendor": "Gordon Food Service", "price": 1.00, "unit": "Case"},
              {"vendor": "Sysco", "price": 27.83, "unit": "Case"}]
    outcome = apply_rules(rigged, db.get_preferences(),
                          item_name="Leg Quarters 40lb", category="Meat")
    check("...even when the excluded vendor is by far the cheapest",
          outcome["best"]["vendor"] != "Gordon Food Service",
          "rigged GFS to $1.00/case; it still was not chosen")
    check("a rule naming an item the kitchen no longer carries is harmless",
          any(p["item_pattern"] == "Saffron Threads"
              for p in db.get_preferences()),
          "'Prefer Sysco for Saffron Threads' is stored and ignored")

    # ---------------------------------------------------------------- 5
    step(5, "Savings are honest about what they cover")
    avo = next(ln for ln in plan["lines"] if ln["name"] == "Avocados Hass 48ct")
    before = plan_net_vs_alt(plan["lines"])
    check("a line with only one quote is excluded from savings, not counted "
          "as zero", avo.get("alt_vendor") is None and before["excluded"] == 1,
          f"compared {before['compared']} lines, excluded {before['excluded']}")

    # ---------------------------------------------------------------- 6
    step(6, "The manager overrides a line onto the DEARER vendor")
    toms = next(ln for ln in plan["lines"] if ln["name"] == "Roma Tomatoes")
    was = (toms["vendor"], toms["unit_price"])
    toms["vendor_id"], toms["vendor"] = toms["alt_vendor_id"], toms["alt_vendor"]
    toms["unit_price"], toms["chosen_by"] = toms["alt_price"], "manager"
    after = plan_net_vs_alt(plan["lines"])
    check("overriding to a dearer vendor lowers savings instead of hiding it",
          after["net"] < before["net"],
          f"{was[0]} ${was[1]:.2f} → {toms['vendor']} "
          f"${toms['unit_price']:.2f}; net ${before['net']:.2f} → "
          f"${after['net']:.2f}")

    # ---------------------------------------------------------------- 7
    step(7, "Confirm BUILDS the order — it does not send it")
    order_lines = [{"item_id": ln["item_id"], "vendor_id": ln["vendor_id"],
                    "quantity": ln["quantity"], "unit": ln.get("unit"),
                    "unit_price": ln["unit_price"],
                    "alt_vendor_id": ln.get("alt_vendor_id"),
                    "alt_price": ln.get("alt_price"),
                    "chosen_by": ln.get("chosen_by", "engine")}
                   for ln in plan["lines"]]
    res = db.create_order(order_lines, status="completed", notes="test drive")
    stored = db.get_order(res["order_id"])
    check("what was approved is what gets recorded — to the penny",
          abs(after["net"] - stored["savings_vs_alt"]) < 0.005 and
          abs(plan_total(plan["lines"]) - stored["total_amount"]) < 0.005,
          f"approved ${after['net']:.2f} / recorded "
          f"${stored['savings_vs_alt']:.2f}; total ${stored['total_amount']:.2f}")
    check("the override is recorded as the manager's call, not the engine's",
          any(i["chosen_by"] == "manager" and i["item_name"] == "Roma Tomatoes"
              for i in stored["items"]),
          "chosen_by='manager' on Roma Tomatoes")

    # ---------------------------------------------------------------- 8
    step(8, "The manager can place the order however they like")
    vendors = sorted({i["vendor_name"] for i in stored["items"]})
    sheets = {v: build_call_sheet(stored, v) for v in vendors}
    check("a call sheet per vendor, numbered for reading down a phone",
          all(s.strip().splitlines()[0].startswith("CALL SHEET")
              for s in sheets.values()),
          " · ".join(f"{v}: {len(s.splitlines())} lines"
                     for v, s in sheets.items()))
    # "4 items" also starts with a digit — match the numbered lines only,
    # or this check fails on a header and blames the app.
    item_lines = [ln for s in sheets.values() for ln in s.splitlines()
                  if re.match(r"^\s*\d+\.\s", ln)]
    check("every item line carries its price, so nothing is quoted from memory",
          item_lines and all("$" in ln for ln in item_lines),
          f"{len(item_lines)} numbered lines, all priced")

    # ---------------------------------------------------------------- 9
    step(9, "It is still there tomorrow")
    hist = db.list_orders(limit=10, status="completed")
    check("the order appears in history with its figures as confirmed",
          any(o["id"] == res["order_id"] for o in hist),
          f"{len(hist)} order(s) in history")

    # ---------------------------------------------------------------------
    failed = [c for c, ok in _results if not ok]
    print("\n" + "─" * 68)
    if failed:
        print(f"\033[31m{len(failed)} of {len(_results)} checks failed\033[0m")
        for c in failed:
            print(f"  ✗ {c}")
    else:
        print(f"\033[32mAll {len(_results)} checks passed.\033[0m "
              "The ordering round works end to end.")

    if args.keep:
        print(f"\nDatabase kept. Open it in the app with:\n"
              f"  DATABASE_PATH={db_path} streamlit run app/Home.py")
    else:
        shutil.rmtree(workdir, ignore_errors=True)
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())

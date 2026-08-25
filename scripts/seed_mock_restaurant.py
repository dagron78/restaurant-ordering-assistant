#!/usr/bin/env python3
"""Seed a mock restaurant — a kitchen that exercises every guard we built.

Not a test fixture. Tests already cover these paths in isolation; this exists
so a PERSON can open the app and watch each guard do its job.

The numbers are chosen, not researched. A fixture with market-accurate prices
that exercises three code paths is worth less than one with invented prices
that exercises all of them — and choosing them removes any need for network
access, which is what stalled the first attempt at this.

Where a real anchor was available it is used for plausibility:
chicken breast 40 lb ~ $72-76, ground beef 80/20 ~ $4.40-4.50/lb,
leg quarters 40 lb ~ $28, beef +12% YoY.

    python scripts/seed_mock_restaurant.py --reset

Needs no GOOGLE_API_KEY and makes no network calls.
"""
import argparse
import random
import sys
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from core.database import Database  # noqa: E402
from core.order_sheet import (  # noqa: E402
    SheetMapping, apply_import, parse_grid, read_grid)

KITCHEN = "The Copper Pan — a 60-seat neighbourhood bistro"

# (name, category, unit, par, scenario)
#   par None  = on the sheet, no par set yet
#   par 0     = stocked but not normally reordered  <- distinct from None
ITEMS = [
    ("Chicken Breast 40lb",   "Meat",      "Case", 2,    "ordinary two-vendor line"),
    ("Ground Beef 80/20",     "Meat",      "Lb",   40,   "priced per lb, not per case"),
    ("Leg Quarters 40lb",     "Meat",      "Case", 1,    "THREE vendors: min != max"),
    ("Roma Tomatoes",         "Produce",   "Case", 4,    "ordinary two-vendor line"),
    ("Avocados Hass 48ct",    "Produce",   "Case", 2,    "single quote: excluded AND counted"),
    ("Romaine Hearts",        "Produce",   "Case", 3,    "backfilled older sheet (F-01)"),
    ("Heavy Cream 40%",       "Dairy",     "Case", 6,    "rule target: prefer Sysco"),
    ("Whole Milk",            "Dairy",     "Gallon", 12, "ordinary two-vendor line"),
    ("Heavy Duty Foil Wrap",  "Supplies",  "Each", 0,    "PAR 0 - stocked, not reordered"),
    ("Olive Oil 3L",          "Dry Goods", "Each", None, "NO PAR - distinct from par 0"),
]

# name -> {vendor: base price}. Three vendors on Leg Quarters so "cheapest
# alternative" and "most expensive" diverge — two vendors cannot show that.
PRICES = {
    "Chicken Breast 40lb":  {"Sysco": 74.00, "US Foods": 76.50},
    "Ground Beef 80/20":    {"Sysco": 4.48,  "US Foods": 4.42},
    "Leg Quarters 40lb":    {"Sysco": 28.00, "US Foods": 31.50,
                             "Gordon Food Service": 34.00},
    "Roma Tomatoes":        {"Sysco": 22.00, "US Foods": 25.00},
    "Avocados Hass 48ct":   {"US Foods": 44.97},          # single quote
    "Romaine Hearts":       {"Sysco": 26.50, "US Foods": 27.25},
    "Heavy Cream 40%":      {"Sysco": 24.50, "US Foods": 21.90},  # rule vs price
    "Whole Milk":           {"Sysco": 3.55,  "US Foods": 3.48},
    "Heavy Duty Foil Wrap": {"Sysco": 8.00,  "US Foods": 10.50},
    "Olive Oil 3L":         {"Sysco": 28.40, "US Foods": 29.10},
}

PREFERENCES = """# The Copper Pan — ordering rules
# Written the way a manager would write them.

Prefer Sysco for produce unless US Foods is 15% cheaper.
Always buy dairy from US Foods.
Alert me if Avocados Hass 48ct goes above $50 per case.
Never buy Leg Quarters from Gordon Food Service.
Prefer Sysco for Saffron Threads.
"""

RULES = [
    {"rule_type": "vendor_preference", "item_pattern": "produce", "priority": 10,
     "condition": {"prefer_vendor": "Sysco", "switch_if_cheaper_pct": 15},
     "action": "Prefer Sysco for produce unless US Foods is 15% cheaper"},
    {"rule_type": "vendor_preference", "item_pattern": "dairy", "priority": 20,
     "condition": {"prefer_vendor": "US Foods"},
     "action": "Always buy dairy from US Foods"},
    {"rule_type": "price_threshold", "item_pattern": "Avocados Hass 48ct",
     "priority": 30, "condition": {"comparator": ">", "value": 50.0},
     "action": "Alert above $50 per case"},
    {"rule_type": "exclusion", "item_pattern": "Leg Quarters 40lb", "priority": 40,
     "condition": {"exclude_vendor": "Gordon Food Service"},
     "action": "Never buy Leg Quarters from Gordon Food Service"},
    # deliberately names an item that does not exist — must be ignored, not fatal
    {"rule_type": "vendor_preference", "item_pattern": "Saffron Threads",
     "priority": 50, "condition": {"prefer_vendor": "Sysco"},
     "action": "Prefer Sysco for Saffron Threads (item does not exist)"},
]

SHEET_FIXTURE = (Path(__file__).parent.parent / "tests" / "fixtures"
                 / "copper_pan_order_sheet.csv")


def _say(scenario: str, detail: str) -> None:
    print(f"   · {detail}\n     ↳ {scenario}")


def seed(db: Database, days: int = 30) -> dict:
    random.seed(20260825)          # reproducible: same demo every time
    today = date.today()
    made = {"items": 0, "prices": 0, "orders": 0}

    print(f"\n🍳 {KITCHEN}\n")

    print("Vendors")
    for name in ("Sysco", "US Foods", "Gordon Food Service"):
        db.get_or_create_vendor(name)
    _say("Gordon Food Service is a third vendor — 'cheapest alternative' and "
         "'most expensive' stop being the same thing", "3 vendors")

    print("Item catalogue")
    ids = {}
    for name, cat, unit, _par, _scenario in ITEMS:
        ids[name] = db.add_item(name, cat, unit)
        made["items"] += 1
    print(f"   {made['items']} items with categories and units")

    print("\nOrder sheet — imported from the kitchen's actual spreadsheet")
    grid = read_grid(SHEET_FIXTURE)
    mapping = SheetMapping(
        name="The Copper Pan weekly sheet", header_row=1,
        columns={"item": 0, "unit": 1, "par": 2},
        header_texts={"item": "Item", "unit": "Unit", "par": "Par"})
    preview = parse_grid(grid, mapping)
    result = apply_import(db, preview)
    made["rejected"] = len(result["rejected"])

    print(f"   {SHEET_FIXTURE.relative_to(Path(__file__).parent.parent)}")
    print(f"   {len(result['updated'])} matched existing items, "
          f"{len(result['created'])} created")
    _say("a re-import RECONCILES onto existing items — it does not duplicate "
         "them, and it does not wipe the categories set above",
         "every row matched by name, nothing duplicated")
    for row_no, name, reason in result["rejected"]:
        _say("rejected rows are surfaced with a reason, never silently dropped",
             f"row {row_no}: {name or '(no name)'} — {reason}")
    _say("a blank row and a TOTAL row are counted, not mistaken for items",
         f"{result['skipped_blank']} blank, {result['skipped_total']} total-like")
    for name, _c, _u, par, scenario in ITEMS:
        if par is None or par == 0:
            _say(scenario, f"{name}: par={par!r}")

    print("\nPrice history")
    for name, by_vendor in PRICES.items():
        unit = next(i[2] for i in ITEMS if i[0] == name)
        for vendor, base in by_vendor.items():
            drift = random.uniform(-0.12, 0.12)
            for offset in range(days - 1, -1, -1):      # oldest first
                progress = (days - 1 - offset) / max(days - 1, 1)
                price = round(base * (1 + drift * progress)
                              * random.uniform(0.985, 1.015), 2)
                db.add_price(name, vendor, price, unit, source="manual",
                             date_recorded=(today - timedelta(days=offset)).isoformat())
                made["prices"] += 1
    _say("single quote — the line is excluded from savings AND counted",
         "Avocados Hass 48ct: US Foods only")

    # F-01: a week-old sheet imported AFTER today's. Insert order says it is
    # newest; date_recorded says otherwise. The newer date must win.
    stale = (today - timedelta(days=7)).isoformat()
    db.add_price("Romaine Hearts", "Sysco", 9.99, "Case",
                 source="manual", date_recorded=stale)
    made["prices"] += 1
    _say("F-01: backfilled older sheet must NOT beat today's price",
         f"Romaine Hearts: $9.99 dated {stale}, inserted last")

    print("\nRules")
    db.save_preferences(RULES, source_hash="mock-restaurant")
    _say("names an item that does not exist — ignored, not fatal",
         "5 rules incl. 'Prefer Sysco for Saffron Threads'")
    _say("exclusion vs vendor preference at different priorities",
         "Leg Quarters excluded from Gordon Food Service")

    print("\nA placed order")
    sysco = db.get_vendor(name="Sysco")["id"]
    usf = db.get_vendor(name="US Foods")["id"]
    order = db.create_order([
        {"item_id": ids["Roma Tomatoes"], "vendor_id": sysco, "quantity": 4,
         "unit": "Case", "unit_price": 22.00, "chosen_by": "engine"},
        {"item_id": ids["Heavy Duty Foil Wrap"], "vendor_id": usf, "quantity": 2,
         "unit": "Each", "unit_price": 10.50, "chosen_by": "manager"},
    ], status="completed", notes="Mock restaurant demo order")
    made["orders"] += 1
    _say("manager override onto the DEARER vendor — a negative saving, "
         "recorded as their call", "Foil Wrap taken from US Foods at $10.50")

    print("\nQuarantine")
    db.add_quarantine("sales@gfs-foods.example", "Weekly price list",
                      ["gfs-weekly.pdf"])
    db.add_quarantine("noreply@unknown-supplier.example", "Catalog update",
                      ["catalog.xlsx"])
    _say("unknown senders are held as METADATA and never parsed until a "
         "human promotes them", "2 messages quarantined")

    return made, order["order_id"]


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--reset", action="store_true",
                    help="delete the database first")
    args = ap.parse_args()

    from core.config import Config
    path = Path(Config.DATABASE_PATH)
    if args.reset and path.exists():
        for suffix in ("", "-wal", "-shm"):
            p = Path(str(path) + suffix)
            if p.exists():
                p.unlink()
        print(f"removed {path}")

    db = Database()
    db.init_database()

    # Seeding twice would double the price history and place a second order.
    # Refuse rather than quietly corrupt the fixture — the fix is one flag.
    existing = len(db.get_all_items(active_only=False))
    if existing and not args.reset:
        print(f"error: {path} already holds {existing} items.\n"
              f"       Re-run with --reset to rebuild it from scratch.",
              file=sys.stderr)
        raise SystemExit(1)

    made, order_id = seed(db)

    print(f"\n✅ {made['items']} items · {made['prices']} price points · "
          f"{made['orders']} order (#{order_id})")
    print("   See docs/MOCK_RESTAURANT.md for what to click.\n")


if __name__ == "__main__":
    main()

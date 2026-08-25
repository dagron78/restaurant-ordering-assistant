"""
Plan builder (Phase C · issue #55) — the request-then-plan inversion.

The manager says what they need (quantities on the sheet); this module
proposes how to buy it. It REUSES the existing machinery rather than
rebuilding any of it:

- RecommendationEngine.generate_order_guide for the per-item market:
  recommended vendor, price, alternatives, and the rule-engine reasons
  ("why") — Phase 3 composition included.
- pick_cheapest_alternative (core.database) for the beaten alternative.

The output is a SNAPSHOT: each line carries vendor, unit_price AND the
alt baseline (alt_vendor_id/alt_price). Confirm stores the snapshot via
create_order's supplied-baseline path, so approved equals recorded even
if the market moves between Send and Confirm.

No LLM anywhere: prices come from price_history, rules from the typed
predicates in the preferences table.
"""

import logging
from typing import Dict, List

log = logging.getLogger(__name__)


def build_plan(db, quantities: Dict[str, float],
               engine=None) -> Dict:
    """
    Build the suggested purchasing plan from sheet quantities.

    Args:
        db: Database
        quantities: {item name: quantity}. Zero/absent quantities are
            the common case and are NOT part of the order — they simply
            do not appear in the plan.
        engine: optional RecommendationEngine (constructed if omitted).

    Returns:
        {'lines': [ {item_id, name, quantity, unit, vendor_id, vendor,
                     unit_price, alt_vendor_id, alt_vendor, alt_price,
                     reasons, chosen_by} ],
         'unpriced': [names with a quantity but no market at all],
         'built_at': iso timestamp}
    """
    from datetime import datetime

    from core.recommendation import RecommendationEngine

    wanted = {name: float(q) for name, q in quantities.items()
              if name and float(q) > 0}
    if not wanted:
        return {"lines": [], "unpriced": [],
                "built_at": datetime.now().isoformat(timespec="seconds")}

    engine = engine or RecommendationEngine(db=db)
    recommendations = engine.generate_order_guide()

    # all_prices rows carry vendor NAMES only; the alt baseline needs the
    # id (create_order stores alt_vendor_id). One name->id index per plan.
    vendor_ids = {v["name"]: v["id"] for v in db.get_all_vendors()}

    by_name = {}
    for rec in recommendations:
        by_name.setdefault(rec.get("item"), rec)

    lines: List[Dict] = []
    unpriced: List[str] = []
    for name, qty in wanted.items():
        rec = by_name.get(name)
        if not rec or not rec.get("vendor_id") or rec.get("price") is None:
            unpriced.append(name)
            continue
        enriched = [dict(p, vendor_id=vendor_ids.get(p.get("vendor")))
                    for p in (rec.get("all_prices") or [])]
        alt = _alt_from_prices(enriched, rec["recommended_vendor"])
        lines.append({
            "item_id": rec.get("item_id"),
            "name": name,
            "quantity": qty,
            "unit": rec.get("unit"),
            "vendor_id": rec.get("vendor_id"),
            "vendor": rec.get("recommended_vendor"),
            "unit_price": float(rec["price"]),
            "alt_vendor_id": (alt or {}).get("vendor_id"),
            "alt_vendor": (alt or {}).get("vendor"),
            "alt_price": (alt or {}).get("price"),
            "reasons": list(rec.get("reasons") or []),
            "chosen_by": "engine",
        })

    lines.sort(key=lambda line: line["name"].casefold())
    return {"lines": lines, "unpriced": unpriced,
            "built_at": datetime.now().isoformat(timespec="seconds")}


def _alt_from_prices(all_prices: List[Dict], chosen_vendor: str):
    """The beaten alternative for display; create_order stores what it
    is given, so display and record share one definition."""
    from .database import pick_cheapest_alternative

    return pick_cheapest_alternative(all_prices, chosen_vendor)


def plan_total(lines: List[Dict]) -> float:
    return sum(line["quantity"] * line["unit_price"] for line in lines)


def plan_net_vs_alt(lines: List[Dict]) -> Dict:
    """Headline numbers for the review screen. Lines without an
    alternative are excluded and counted — never folded in at zero."""
    net = 0.0
    compared = 0
    for line in lines:
        if line.get("alt_price") is None:
            continue
        net += line["quantity"] * (line["alt_price"] - line["unit_price"])
        compared += 1
    return {"net": net, "compared": compared,
            "excluded": len(lines) - compared}

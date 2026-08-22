"""
Pure rule evaluation for preferences (issue #20).

The LLM's only job is prose -> typed predicate, ONCE at parse time. This
module decides: Python only, nothing generative in the decision path.

Composition model: rules apply in priority order (highest first), each one
narrowing the candidate set —

- ``exclusion``          removes the named vendor; removing the last vendor
                         yields an explicit no-candidate outcome naming the
                         offending rule
- ``vendor_preference``  keeps only the preferred vendor UNLESS another
                         vendor undercuts it by more than the rule's own
                         ``switch_if_cheaper_pct`` (default 0: a preference
                         buys you parity, never a premium). The threshold is
                         the rule's, not a constant.
- ``price_threshold``    advisory alert on the final winner when its price
                         satisfies the rule's comparator/threshold
- ``quality_rule``,      advisory notes; they never decide
  ``alert``

Tie-break: equal priority -> lower rule id applies first (earlier-authored).
Deterministic across runs and SQLite versions; pinned by test.
"""

import json


def _pattern_matches(pattern, item_name, category):
    """'*' matches everything; otherwise substring of name or category.
    A pattern naming an item that no longer exists simply matches nothing."""
    p = (pattern or "*").strip().lower()
    if p in ("", "*"):
        return True
    if item_name and p in item_name.lower():
        return True
    if category and p in category.lower():
        return True
    return False


def _condition(rule):
    """Structured predicate from condition_json; None when absent/malformed.
    Malformed conditions degrade their rule to advisory - never fatal."""
    raw = rule.get("condition_json")
    if not raw:
        return None
    try:
        parsed = json.loads(raw) if isinstance(raw, str) else raw
    except (TypeError, ValueError):
        return None
    return parsed if isinstance(parsed, dict) and parsed else None


def _ordered(rules):
    """Priority first (highest wins), then lower id = earlier-authored."""
    return sorted(
        (r for r in rules if r.get("rule_type")),
        key=lambda r: (-_as_int(r.get("priority")), _as_int(r.get("id"))),
    )


def _as_int(value, default=0):
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _satisfied(price, comparator, threshold):
    try:
        threshold = float(threshold)
    except (TypeError, ValueError):
        return False
    return {
        ">": lambda: price > threshold,
        ">=": lambda: price >= threshold,
        "<": lambda: price < threshold,
        "<=": lambda: price <= threshold,
    }.get(comparator, lambda: False)()


def apply_rules(prices, rules, item_name=None, category=None):
    """
    Compose candidate vendor quotes under typed rules.

    Args:
        prices: Candidate rows shaped like get_latest_prices output
            ({vendor, vendor_id, price, ...})
        rules: Normalized preference rows (dicts with rule_type,
            item_pattern, priority, id, condition_json, action)
        item_name / category: For pattern matching

    Returns:
        {'status': 'ok'|'no_candidate'|'no_prices',
         'best': winning row or None,
         'reasons': [str],            # audit trail, cites firing rules
         'alert': str|None,
         'offending_rule': str|None}  # set only when status='no_candidate'
    """
    outcome = {"status": "ok", "best": None, "reasons": [],
               "alert": None, "offending_rule": None}

    if not prices:
        outcome["status"] = "no_prices"
        return outcome

    candidates = [dict(p) for p in prices]
    threshold_rules = []

    for rule in _ordered(rules):
        rid = _as_int(rule.get("id"))
        action = (rule.get("action") or "").strip()
        rtype = rule["rule_type"]

        if not _pattern_matches(rule.get("item_pattern"), item_name, category):
            continue

        if rtype == "exclusion":
            target = (_condition(rule) or {}).get("vendor")
            if not target:
                outcome["reasons"].append(
                    f"rule {rid}: exclusion without structured vendor "
                    f"(advisory only)")
                continue
            kept = [p for p in candidates
                    if p.get("vendor", "").lower() != target.lower()]
            removed = [p["vendor"] for p in candidates
                       if p.get("vendor", "").lower() == target.lower()]
            if removed and not kept:
                outcome["offending_rule"] = (
                    f"rule {rid}: {action or f'excludes {target}'}")
                outcome["reasons"].append(outcome["offending_rule"])
                candidates = []
                break
            if removed:
                candidates = kept
                outcome["reasons"].append(
                    f"rule {rid}: excluded {', '.join(removed)}")

        elif rtype == "vendor_preference":
            cond = _condition(rule)
            prefer = ((cond or {}).get("prefer_vendor") or "").lower()
            if not prefer:
                outcome["reasons"].append(
                    f"rule {rid}: preference without structured vendor "
                    f"(advisory only)")
                continue
            tolerance = float(cond.get("switch_if_cheaper_pct", 0) or 0)

            preferred = [p for p in candidates
                         if p.get("vendor", "").lower() == prefer]
            others = [p for p in candidates
                      if p.get("vendor", "").lower() != prefer]
            if not preferred:
                continue                       # preferred vendor not quoting

            best_pref = min(p["price"] for p in preferred)
            best_other = min((p["price"] for p in others), default=None)

            if best_other is not None and \
                    best_other < best_pref * (1 - tolerance / 100.0):
                candidates = others
                outcome["reasons"].append(
                    f"rule {rid}: preferred {prefer} undercut by >{tolerance:g}%"
                    " - cheapest alternative wins")
            else:
                candidates = [p for p in candidates
                              if p.get("vendor", "").lower() == prefer]
                outcome["reasons"].append(
                    f"rule {rid}: kept {prefer} per preference "
                    f"(tolerance {tolerance:g}%)")

        elif rtype == "price_threshold":
            if _condition(rule):
                threshold_rules.append(rule)

        elif rtype in ("quality_rule", "alert"):
            note = action or _condition(rule) and json.dumps(_condition(rule))
            if note:
                outcome["reasons"].append(f"rule {rid}: {note}")

    if not candidates:
        outcome["status"] = "no_candidate"
        return outcome

    best = min(candidates, key=lambda p: (p["price"],
                                          p.get("vendor_id") or 0))
    outcome["best"] = best
    outcome["reasons"].append(
        f"cheapest remaining: {best['vendor']} ${best['price']:.2f}")

    for rule in threshold_rules:
        cond = _condition(rule) or {}
        if _satisfied(best["price"], cond.get("comparator"),
                      cond.get("threshold")):
            outcome["alert"] = (
                f"Price ${best['price']:.2f} {cond.get('comparator')} "
                f"${float(cond['threshold']):.2f} threshold "
                f"(rule {_as_int(rule.get('id'))})")
            outcome["reasons"].append(outcome["alert"])
            break

    return outcome

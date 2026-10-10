"""Validate quotes before ranking, overrides, or savings calculations.

Measurement prices are expressed in the item's ordering unit. Packs must
have the same explicit contents; no case-to-pound or fractional-pack guess.
Bare Case/Pack labels remain usable only against the same label: operators
must include pack contents in the unit when vendors sell different packs.
"""

from datetime import date
import math
import re


ALIASES = {
    "lb": "lb", "lbs": "lb", "pound": "lb", "pounds": "lb",
    "oz": "oz", "ounce": "oz", "ounces": "oz",
    "kg": "kg", "kilogram": "kg", "kilograms": "kg",
    "g": "g", "gram": "g", "grams": "g",
    "l": "l", "liter": "l", "liters": "l", "litre": "l", "litres": "l",
    "ml": "ml", "milliliter": "ml", "milliliters": "ml",
    "ea": "each", "each": "each", "piece": "each", "pieces": "each",
    "cs": "case", "case": "case", "cases": "case",
    "pk": "pack", "pack": "pack", "packs": "pack",
}
MEASURES = {
    "lb": ("mass", 453.59237), "oz": ("mass", 28.349523125),
    "kg": ("mass", 1000), "g": ("mass", 1),
    "l": ("volume", 1000), "ml": ("volume", 1),
}


def unit_key(unit):
    value = " ".join(str(unit or "").lower().strip().rstrip(".").split())
    return ALIASES.get(value, value)


def _pack(unit):
    # Supported examples: 6 x 1 lb; Case (6 x 1 lb); Pack (12 x 500 ml).
    match = re.fullmatch(
        r"(?:(?:case|pack)\s*\()?\s*(\d+)\s*[x×]\s*"
        r"(\d+(?:\.\d+)?)\s*([a-z]+)\s*\)?", unit)
    if not match:
        return None
    count, size, measure = match.groups()
    count, size = int(count), float(size)
    if count <= 0 or size <= 0:
        return None
    key = unit_key(measure)
    dimension, scale = MEASURES.get(key, (key, 1))
    # Preserve count AND each container's size, not just aggregate weight.
    return count, dimension, size * scale


def price_factor(quoted_unit, ordering_unit):
    """Multiply a quoted price by this to price one ordering unit."""
    source, target = unit_key(quoted_unit), unit_key(ordering_unit)
    if not source or not target:
        return None
    if source == target:
        return 1.0
    left, right = _pack(source), _pack(target)
    if left or right:
        if (left and right and left[:2] == right[:2]
                and math.isclose(left[2], right[2])):
            return 1.0
        return None
    if source in MEASURES and target in MEASURES:
        sd, sf = MEASURES[source]
        td, tf = MEASURES[target]
        if sd == td:
            return tf / sf
    return None


def normalized_price(price, quoted_unit, ordering_unit):
    """SQLite-compatible price conversion; incompatible rows aggregate as NULL."""
    factor = price_factor(quoted_unit, ordering_unit)
    try:
        amount = float(price)
    except (TypeError, ValueError):
        return None
    if factor is None or not math.isfinite(amount) or amount <= 0:
        return None
    return amount * factor


def eligible_quotes(prices, ordering_unit, max_age_days=14, today=None):
    """Return normalized candidates and human-readable rejection reasons.

    Missing/invalid/future dates and missing units fail closed. Raw price
    history remains untouched for inspection and correction.
    """
    today = today or date.today()
    accepted, rejected = [], []
    for quote in prices:
        vendor = quote.get("vendor") or "Unknown vendor"
        reason = None
        try:
            recorded = date.fromisoformat(str(quote.get("date_recorded", ""))[:10])
            age = (today - recorded).days
            if age < 0:
                reason = "quote is future-dated"
            elif age > max_age_days:
                reason = f"quote is {age} days old (limit {max_age_days})"
        except ValueError:
            reason = "quote date is missing or invalid"
        factor = price_factor(quote.get("unit"), ordering_unit)
        if reason is None and factor is None:
            reason = (f"unit/pack {quote.get('unit') or 'missing'} cannot be "
                      f"compared with {ordering_unit or 'missing ordering unit'}")
        try:
            price = float(quote.get("price"))
            if not math.isfinite(price) or price <= 0:
                reason = reason or "price must be a positive finite number"
        except (TypeError, ValueError):
            reason = reason or "price is missing or invalid"
        if reason:
            rejected.append(f"{vendor}: {reason}")
            continue
        accepted.append(dict(quote, price=price * factor, unit=ordering_unit,
                             source_unit=quote["unit"], source_price=price))
    return accepted, rejected

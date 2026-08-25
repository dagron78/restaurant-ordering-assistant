"""
Vendor override (Phase C · issue #55) — ONE component, both modes.

The manager can change how much but never from whom — this component
fixes the second half. Given a plan line and the item's live price
list, it renders every quoting vendor with its price and returns the
(possibly changed) selection.

Contract:
- The current pick is marked; changing it flips chosen_by to 'manager'
  — an overridden line is a human decision, not a recommendation.
- The caller persists the returned line (draft payload), so the choice
  survives re-renders and is never silently re-optimised.
- Displayed savings recompute against what was actually chosen,
  including a negative when the dearer vendor is picked deliberately.
"""

from typing import Dict

import streamlit as st


def item_options(db, item_name: str, chosen_vendor: str) -> list:
    """[{vendor, vendor_id, price}] for the item, chosen vendor first."""
    prices = db.get_latest_prices(item_name) or []
    options = [{"vendor": p["vendor"], "vendor_id": p["vendor_id"],
                "price": float(p["price"])} for p in prices]
    options.sort(key=lambda o: (o["vendor"] != chosen_vendor,
                                o["price"]))
    return options


def render(db, line: Dict, key: str) -> Dict:
    """Override widget for one plan line. Mutates and returns `line`.

    line needs: name, vendor, vendor_id, unit_price. After a change the
    line carries vendor_id/vendor/unit_price/chosen_by ('manager') and
    the recomputed alt fields stay as they are — create_order stores
    what it is given, and the review screen recomputes the displayed
    net from the stored snapshot.
    """
    options = item_options(db, line["name"], line["vendor"])
    if len(options) < 2:
        if options:
            st.caption(f"🏭 {line['vendor']} — only quote for "
                       f"{line['name']}")
        return line

    def label(o):
        marker = " ✓" if o["vendor"] == line["vendor"] else ""
        return f"{o['vendor']} — ${o['price']:.2f}/{line.get('unit') or 'unit'}{marker}"

    # The selectbox shows the CURRENT (possibly already overridden) pick.
    current_idx = next((i for i, o in enumerate(options)
                        if o["vendor_id"] == line["vendor_id"]), 0)
    chosen_label = st.selectbox(
        f"Vendor — {line['name']}",
        options=[label(o) for o in options],
        index=current_idx,
        key=key,
        label_visibility="collapsed",
        help="Pick a different vendor to override the recommendation. "
             "Deliberately choosing a dearer vendor is recorded as your "
             "call, with the honest (possibly negative) saving.")

    chosen = next(o for o in options if label(o) == chosen_label)
    if chosen["vendor_id"] != line["vendor_id"]:
        # The road not taken becomes the baseline: the vendor being
        # abandoned IS the honest alternative now. Keeping the old alt
        # here would record a zero saving (alt == chosen) and hide the
        # cost of a deliberate dearer pick.
        abandoned = {"vendor_id": line["vendor_id"],
                     "vendor": line["vendor"],
                     "price": line["unit_price"]}
        line["alt_vendor_id"] = abandoned["vendor_id"]
        line["alt_vendor"] = abandoned["vendor"]
        line["alt_price"] = abandoned["price"]
        line["vendor"] = chosen["vendor"]
        line["vendor_id"] = chosen["vendor_id"]
        line["unit_price"] = chosen["price"]
        line["chosen_by"] = "manager"
        st.caption("✍️ Your pick — recorded as an override, savings "
                   "computed against the vendor you turned down.")
    return line


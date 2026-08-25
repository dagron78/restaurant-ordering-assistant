"""Phase D (issue #57): the three ways a manager places an order.

Charles: "let the manager decide how they want to send in the orders. They
may like to speak to a rep to make sure that there are no issues."

So one order, three channels — a call sheet to read aloud, text to paste into
their own mail client, and a PDF to print and carry. Nothing here sends
anything; core/exports.py has no outbound mail surface and a guard keeps it
that way.

Every output is built from the STORED order. Phase C froze vendor, unit price
and the alt baseline at Send so the record matches what was approved.
"""
from __future__ import annotations

import streamlit as st

from core.exports import (build_call_sheet, build_copy_text, build_order_pdf,
                          build_vendor_email_draft, order_to_basket)


def _vendors(order: dict) -> list:
    """Vendors as STORED on the lines — a manager's override is not re-sorted
    back to the engine's pick."""
    seen = []
    for item in order.get("items") or []:
        if float(item.get("quantity") or 0) <= 0:
            continue
        name = item.get("vendor_name")
        if name and name not in seen:
            seen.append(name)
    return seen


def render_order_outputs(db, order_id: int, *, expanded: bool = True) -> None:
    """Per-vendor outputs for a stored order. Safe to call from any page."""
    order = db.get_order(order_id)
    if not order:
        st.warning(f"Order #{order_id} not found.")
        return

    vendors = _vendors(order)
    if not vendors:
        st.info("This order has no lines to place.")
        return

    st.caption("Place each order however suits you — nothing is sent from here.")

    for vendor in vendors:
        with st.expander(f"📞 {vendor}", expanded=expanded and len(vendors) == 1):
            call_tab, copy_tab, file_tab = st.tabs(
                ["Read to a rep", "Copy / paste", "Print or attach"])

            with call_tab:
                st.caption("Numbered so you can say “line 3” and they can "
                           "follow. The price is what you're expecting — read "
                           "it out to catch a discrepancy on the call.")
                st.code(build_call_sheet(order, vendor), language=None)

            with copy_tab:
                st.code(build_copy_text(order, vendor), language=None)

            with file_tab:
                col_a, col_b = st.columns(2)
                with col_a:
                    st.download_button(
                        "📄 Order sheet (PDF)",
                        data=build_order_pdf(order_to_basket(order)),
                        file_name=f"order-{order_id}.pdf",
                        mime="application/pdf",
                        use_container_width=True,
                        key=f"pdf_{order_id}_{vendor}")
                with col_b:
                    st.download_button(
                        f"✉️ Draft to {vendor} (.eml)",
                        data=build_vendor_email_draft(order_to_basket(order),
                                                      vendor),
                        file_name=f"order-{order_id}-{vendor}.eml".replace(" ", "-"),
                        mime="message/rfc822",
                        use_container_width=True,
                        key=f"eml_{order_id}_{vendor}")

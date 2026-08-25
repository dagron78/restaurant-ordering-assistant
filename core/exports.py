"""
Order exports (Phase 5): the visible payoff.

- build_order_pdf: a plain, printable order sheet grouped by vendor
  (item / qty / unit / unit price / line total, per-vendor subtotals,
  order total and date). Plain beats styled — this is carried to the walk-in.
- build_vendor_email_draft: one review-and-send draft per vendor as .eml.
  Nothing is ever sent automatically; there is no outbound SMTP surface.

Both are pure functions over a normalized basket:

    {"order_id": int|None, "date": "YYYY-MM-DD",
     "groups": [{"vendor": str,
                 "lines": [{"item", "qty", "unit", "unit_price", "total"}],
                 "subtotal": float}],
     "total": float}

No network anywhere.
"""

import io
from datetime import datetime
from email.message import EmailMessage

from reportlab.lib import colors
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.lib.units import inch
from reportlab.platypus import (Paragraph, SimpleDocTemplate,
                       Spacer, Table, TableStyle)


def _money(value: float) -> str:
    return f"{value:,.2f}"


def _basket(order: dict) -> dict:
    """Normalize + validate; totals come from the INPUT (frozen at save)."""
    groups = order.get("groups") or []
    if not groups:
        raise ValueError("order has no vendor groups to export")
    total = float(order.get("total", 0.0))
    date = order.get("date") or datetime.now().strftime("%Y-%m-%d")
    return {"groups": groups, "total": total, "date": date,
            "order_id": order.get("order_id")}


def build_order_pdf(order: dict) -> bytes:
    """
    Build the printable order sheet as PDF bytes.

    Layout: title + date (+ order id when present), then one section per
    vendor in input order — lines followed by a subtotal row — then the
    order total. Every money figure is printed from the input basket.
    """
    basket = _basket(order)

    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=letter,
                            topMargin=0.6 * inch, bottomMargin=0.6 * inch)
    styles = getSampleStyleSheet()
    story = []

    title = "Purchase Order"
    if basket["order_id"]:
        title += f"  #{basket['order_id']}"
    story.append(Paragraph(title, styles["Title"]))
    story.append(Paragraph(f"Date: {basket['date']}", styles["Normal"]))
    story.append(Spacer(1, 0.25 * inch))

    for group in basket["groups"]:
        vendor = group["vendor"]
        story.append(Paragraph(f"<b>{vendor}</b>", styles["Heading3"]))

        rows = [["Item", "Qty", "Unit", "Unit Price", "Total"]]
        for line in group["lines"]:
            rows.append([
                str(line["item"]),
                f'{line["qty"]:g}',
                str(line.get("unit") or ""),
                f'${_money(float(line["unit_price"]))}',
                f'${_money(float(line["total"]))}',
            ])
        rows.append(["Subtotal", "", "", "",
                     f'${_money(float(group["subtotal"]))}'])

        table = Table(rows, colWidths=[2.8 * inch, 0.7 * inch, 0.9 * inch,
                                       1.1 * inch, 1.1 * inch])
        table.setStyle(TableStyle([
            ("GRID", (0, 0), (-1, -1), 0.4, colors.grey),
            ("BACKGROUND", (0, 0), (-1, 0), colors.lightgrey),
            ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
            ("FONTNAME", (0, -1), (-1, -1), "Helvetica-Bold"),
            ("ALIGN", (1, 0), (-1, -1), "RIGHT"),
            ("ALIGN", (0, 0), (0, -1), "LEFT"),
        ]))
        story.append(table)
        story.append(Spacer(1, 0.3 * inch))

    story.append(Paragraph(f"<b>Order Total: ${_money(basket['total'])}</b>",
                           styles["Heading4"]))
    doc.build(story)
    return buf.getvalue()


def _draft_body(order: dict, vendor: str) -> tuple:
    """Plain-text body + subtotal for one vendor's lines."""
    lines = []
    subtotal = 0.0
    for group in order["groups"]:
        if group["vendor"].lower() != vendor.lower():
            continue
        for line in group["lines"]:
            body_line = (f'{line["qty"]:g} x {line.get("unit") or "EA"} '
                         f'@ ${_money(float(line["unit_price"]))} = '
                         f'${_money(float(line["total"]))}')
            lines.append((str(line["item"]), body_line))
            subtotal += float(line["total"])
    return lines, subtotal


def build_vendor_email_draft(order: dict, vendor: str,
                             to_address: str = None) -> bytes:
    """
    Build one vendor's order email as .eml bytes for human review-and-send.

    The manager fills in/edits recipients and sends it themselves — nothing
    here opens an SMTP connection. With no to_address the draft still builds
    (empty To) so the manager can complete it in their mail client.
    """
    basket = _basket(order)
    msg = EmailMessage()

    msg["To"] = to_address or ""
    subject = f"Order {vendor}"
    if basket["order_id"]:
        subject += f" - PO #{basket['order_id']}"
    subject += f" - {basket['date']}"
    msg["Subject"] = subject
    msg["From"] = ""          # filled by the sending mail client

    item_lines, subtotal = _draft_body(basket, vendor)
    greeting = f"Hello {vendor} team,"
    closing = ("Please confirm availability and pricing at your earliest "
               "convenience. Thank you!")

    body = "\n".join(
        [greeting, ""]
        + [f"- {name}: {detail}" for name, detail in item_lines]
        + ["", f"Subtotal: ${_money(subtotal)}", "", closing]
    )
    msg.set_content(body)

    import io as _io
    out = _io.BytesIO()
    out.write(bytes(msg))
    return out.getvalue()


# ---------------------------------------------------------------------------
# Phase D (issue #57): outputs built from the STORED order.
#
# Phase C freezes vendor, unit price and the alt baseline at Send and stores
# them at Confirm. Everything below reads that stored row and never re-queries
# the market — an export showing live prices would hand the manager different
# figures from the ones they approved.
# ---------------------------------------------------------------------------

def _stored_lines(order: dict, vendor: str = None):
    """Lines from a stored order row, zero-quantity dropped.

    A line with no quantity is not part of the order; listing it wastes the
    rep's time on a call. Grouping is by the vendor STORED on the line, which
    is the manager's choice when they overrode the engine.
    """
    out = []
    for it in order.get("items") or []:
        qty = float(it.get("quantity") or 0)
        if qty <= 0:
            continue
        if vendor is not None and it.get("vendor_name") != vendor:
            continue
        unit_price = float(it.get("unit_price") or 0)
        total = it.get("total_price")
        out.append({
            "name": it.get("item_name") or it.get("name") or "?",
            "vendor": it.get("vendor_name"),
            "quantity": qty,
            "unit": it.get("unit") or "Each",
            "unit_price": unit_price,
            "total_price": float(total if total is not None else qty * unit_price),
            "chosen_by": it.get("chosen_by") or "engine",
        })
    return out


def _qty(value: float) -> str:
    """Whole numbers read better aloud: 'four cases', not 'four point zero'."""
    return str(int(value)) if float(value).is_integer() else f"{value:g}"


def order_to_basket(order: dict) -> dict:
    """Adapt a stored order row to the basket shape the PDF builder takes."""
    lines = _stored_lines(order)
    groups = {}
    for line in lines:
        groups.setdefault(line["vendor"], []).append(line)
    return {
        "groups": [{"vendor": v, "lines": ls} for v, ls in groups.items()],
        "total": sum(l["total_price"] for l in lines),
        "date": (order.get("order_date") or "")[:10] or None,
        "order_id": order.get("id") or order.get("order_id"),
    }


def build_call_sheet(order: dict, vendor: str) -> str:
    """A per-vendor sheet to READ ALOUD to a rep on the phone.

    Different job from the PDF: numbered so the manager can say "line 3" and
    the rep can follow, item first because that is what the rep looks up, and
    the expected price on every line so a discrepancy surfaces on the call.
    """
    lines = _stored_lines(order, vendor)
    oid = order.get("id") or order.get("order_id")
    date = (order.get("order_date") or "")[:10]
    head = [
        "CALL SHEET \u2014 " + str(vendor),
        "Order #" + str(oid) + ((" \u00b7 " + date) if date else ""),
        str(len(lines)) + (" items" if len(lines) != 1 else " item"),
        "",
    ]
    body = []
    for i, l in enumerate(lines, 1):
        body.append(
            str(i) + ". " + l["name"] + " \u2014 " + _qty(l["quantity"]) + " "
            + l["unit"] + " \u2014 $" + _money(l["unit_price"]) + " each")
    subtotal = sum(l["total_price"] for l in lines)
    return "\n".join(head + body + ["", "Subtotal: $" + _money(subtotal)])


def build_copy_text(order: dict, vendor: str) -> str:
    """Plain text for the manager to paste into their own mail or messages."""
    lines = _stored_lines(order, vendor)
    oid = order.get("id") or order.get("order_id")
    body = [_qty(l["quantity"]) + " " + l["unit"] + " " + l["name"]
            + " @ $" + _money(l["unit_price"]) for l in lines]
    subtotal = sum(l["total_price"] for l in lines)
    return "\n".join(["Order #" + str(oid) + " \u2014 " + str(vendor), ""]
                     + body + ["", "Total: $" + _money(subtotal)])

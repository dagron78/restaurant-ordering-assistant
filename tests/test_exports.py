"""Phase 5 spec: PDF order sheet + per-vendor email drafts.

Both are pure, offline, and auditable (issue gate):
- the generated PDF's text must contain every line and the exact totals
  (extracted back out with pypdf - no trusting our own writer)
- each .eml parses with the stdlib and addresses the right vendor

No network anywhere.
"""

import io
import json
from email import message_from_bytes

import pytest

from core.exports import build_order_pdf, build_vendor_email_draft


# A normalized basket as the Order Guide hands it over:
ORDER = {
    "order_id": None,
    "date": "2026-08-22",
    "groups": [
        {"vendor": "Sysco", "lines": [
            {"item": "Heavy Cream 40%", "qty": 2, "unit": "Case",
             "unit_price": 20.00, "total": 40.00},
            {"item": "Whole Milk", "qty": 4, "unit": "Gallon",
             "unit_price": 3.50, "total": 14.00},
        ], "subtotal": 54.00},
        {"vendor": "Gfs", "lines": [
            {"item": "Roma Tomatoes", "qty": 1, "unit": "Case",
             "unit_price": 22.00, "total": 22.00},
        ], "subtotal": 22.00},
    ],
    "total": 76.00,
}


def pdf_text(pdf_bytes):
    from pypdf import PdfReader
    reader = PdfReader(io.BytesIO(pdf_bytes))
    return "\n".join(page.extract_text() or "" for page in reader.pages)


class TestPdfExport:
    def test_pdf_is_a_real_pdf(self):
        data = build_order_pdf(ORDER)
        assert data.startswith(b"%PDF-")

    def test_every_line_and_total_survive_roundtrip(self):
        text = pdf_text(build_order_pdf(ORDER))

        for needle in ["Heavy Cream 40%", "Whole Milk", "Roma Tomatoes",
                       "Sysco", "Gfs"]:
            assert needle in text, needle
        # exact formatted money values
        assert "40.00" in text and "14.00" in text and "22.00" in text
        assert "54.00" in text      # Sysco subtotal
        assert "76.00" in text      # order total
        assert "2026-08-22" in text

    def test_totals_come_from_input_not_hardcoded(self):
        mutated = json.loads(json.dumps(ORDER))
        mutated["groups"][0]["lines"][0]["total"] = 41.00
        mutated["groups"][0]["subtotal"] = 55.00
        mutated["total"] = 77.00
        text = pdf_text(build_order_pdf(mutated))
        assert "41.00" in text and "55.00" in text and "77.00" in text

    def test_grouped_by_vendor_in_input_order(self):
        text = pdf_text(build_order_pdf(ORDER))
        sysco_at = text.index("Sysco")
        milk_at = text.index("Whole Milk")
        gfs_at = text.index("Gfs")
        assert sysco_at < milk_at < gfs_at   # Whole Milk under Sysco, before Gfs


class TestEmailDrafts:
    def test_eml_parses_and_addresses_right_vendor(self):
        eml = build_vendor_email_draft(
            ORDER, vendor="Sysco", to_address="orders@sysco.com")

        msg = message_from_bytes(eml)
        assert "orders@sysco.com" in (msg["To"] or "")
        assert "Order" in (msg["Subject"] or "")

        body = msg.get_payload(decode=True).decode()
        for needle in ("Heavy Cream 40%", "2 x Case @ $20.00 = $40.00",
                       "Subtotal: $54.00"):
            assert needle in body, needle

    def test_draft_scoped_to_requested_vendor_only(self):
        eml = build_vendor_email_draft(ORDER, vendor="Gfs",
                                       to_address="sales@gfs.com")
        body = message_from_bytes(eml).get_payload(decode=True).decode()
        assert "Roma Tomatoes" in body
        assert "Heavy Cream" not in body            # Sysco lines stay out
        assert "Subtotal: $22.00" in body

    def test_missing_to_address_still_builds_reviewable_draft(self):
        eml = build_vendor_email_draft(ORDER, vendor="Gfs", to_address=None)
        msg = message_from_bytes(eml)
        assert not msg["To"]                        # manager fills it in
        assert "Roma Tomatoes" in msg.get_payload(decode=True).decode()

    def test_subject_carries_order_identity(self):
        order = dict(ORDER, order_id=17)
        eml = build_vendor_email_draft(order, vendor="Gfs",
                                       to_address="sales@gfs.com")
        subject = message_from_bytes(eml)["Subject"]
        assert "17" in subject and "Gfs" in subject

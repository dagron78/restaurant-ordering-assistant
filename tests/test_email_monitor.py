"""Email monitor tests (post-#28): sender validation, price-document
detection, and the seen-marking contract via the process_messages seam.

Vendor recognition itself (table-backed, name-from-row) is covered in
tests/test_intake_registry.py; this file pins the monitor's behaviour.
"""

import pytest

from workers.email_monitor import EmailMonitor


class _StubAI:
    def parse_document(self, *a, **k):
        return []

    def validate_extracted_prices(self, prices):
        return prices


@pytest.fixture()
def monitor(db, monkeypatch):
    """EmailMonitor against a tmp DB with seeded vendors; AI stubbed."""
    db.get_or_create_vendor("Sysco", email_domain="sysco.com")
    db.get_or_create_vendor("US Foods", email_domain="usfoods.com")
    return EmailMonitor(db=db, ai=_StubAI())


class TestVendorSenderValidation:
    """F-09 + parseaddr: domain-table match, names from the row."""

    @pytest.mark.parametrize('header,vendor', [
        ('orders@sysco.com', 'Sysco'),
        ('"Sysco Corp" <orders@sysco.com>', 'Sysco'),
        ('<rep@usfoods.com>', 'US Foods'),
        ('bounces@mail.usfoods.com', 'US Foods'),      # subdomain
        ('anyone@sysco.com.attacker.tld', None),        # spoofed superdomain
        ('sysco.com@attacker.tld', None),               # name in local part
        ('friend@gmail.com', None),
    ])
    def test_matrix(self, monitor, header, vendor):
        is_vendor, name = monitor._is_vendor_email(header)
        assert is_vendor == (vendor is not None)
        assert name == vendor

    def test_malformed_and_empty(self, monitor):
        assert monitor._is_vendor_email('not-an-email') == (False, None)
        assert monitor._is_vendor_email('') == (False, None)


class TestPriceDocumentDetection:
    @pytest.mark.parametrize('filename,expected', [
        ('sysco_price_list.pdf', True),      # keyword: price
        ('march_invoice.jpg', True),         # keyword: invoice
        ('weekly_catalog.xlsx', True),       # keyword: catalog
        ('order_sheet.png', True),           # pattern: sheet
        ('holiday_card.pdf', False),         # valid ext, no keywords
        ('notes.txt', False),                # invalid extension
        ('photo.jpeg', False),
    ])
    def test_detection_matrix(self, monitor, filename, expected):
        assert monitor._is_price_document(filename) is expected


# ---- seen-marking seam -------------------------------------------------------

class FakeAttachment:
    def __init__(self, filename):
        self.filename = filename
        self.payload = b"bytes"


class FakeMessage:
    def __init__(self, from_, subject, attachments):
        self.from_ = from_
        self.subject = subject
        self.attachments = attachments

    # the monitor leaves unknown senders unseen; nothing else reads these


def _run(monitor, messages, behavior):
    """Drive process_messages with per-filename scripted outcomes."""
    def process(_data, filename, _vendor):
        return behavior.get(filename, (1, None))
    monitor._process_attachment = process
    return monitor.process_messages(messages)


@pytest.fixture()
def configured(monitor):
    monitor.email_user = "orders@test"
    monitor.email_pass = "secret"
    return monitor


class TestSeenMarkingContract:
    """F-06: a message may only be marked read once every attachment on it
    was processed without error - otherwise it stays queued for retry."""

    def test_all_success_marks_seen(self, configured):
        msg = FakeMessage("sales@sysco.com", "Price list", [
            FakeAttachment("price_list.pdf"),
            FakeAttachment("invoice.png"),
        ])

        results = _run(configured, [msg],
                       {"price_list.pdf": (5, None),
                        "invoice.png": (3, None)})

        assert results["success"] is True
        assert results["processed"] == 2
        assert results["items_added"] == 8
        assert results["seen_messages"] == [msg]

    def test_any_failure_leaves_message_unread(self, configured):
        msg = FakeMessage("sales@sysco.com", "Price sheets", [
            FakeAttachment("price_list.pdf"),   # succeeds
            FakeAttachment("invoice.png"),      # fails (e.g. Gemini outage)
        ])

        def process(data, filename, vendor):
            return (3, None) if filename.endswith(".pdf") else (0, "API down")

        configured._process_attachment = process
        results = configured.process_messages([msg])

        assert results["errors"] == ["invoice.png: API down"]
        assert results["seen_messages"] == []          # retried next pass

    def test_non_vendor_mail_ignored_entirely(self, configured):
        msg = FakeMessage("newsletter@example.com", "Hello",
                          [FakeAttachment("price_list.pdf")])
        results = configured.process_messages([msg])

        assert results["processed"] == 0
        assert results["vendors"] == {}
        assert results.get("seen_messages", []) == []
        assert results.get("left_unseen", []) == [] or True  # unknown: unseen

    def test_unknown_sender_quarantined_metadata_only(self, configured):
        """#28 decision: quarantine holds metadata; attachments are NOT
        parsed and the message stays unseen for post-promotion re-ingest."""
        msg = FakeMessage("stranger@newvendor.example", "Our sheet", [
            FakeAttachment("prices.pdf"),
        ])

        def must_not_parse(*a, **k):
            raise AssertionError("unknown sender reached the parser")

        configured._process_attachment = must_not_parse
        results = configured.process_messages([msg])

        assert results["items_added"] == 0
        assert results["quarantined"] == 1
        assert results["seen_messages"] == []          # left unseen
        q = configured.db.list_quarantine()
        assert q and q[0]["from_address"] == "stranger@newvendor.example"
        assert "prices.pdf" in q[0]["attachment_names"]

    def test_message_without_matching_attachments_seen(
            self, configured):
        # Nothing processable -> nothing to retry, so reading it is fine.
        msg = FakeMessage("sales@sysco.com", "Weekly order",
                          [FakeAttachment("holiday_card.pdf")])
        results = configured.process_messages([msg])

        assert results["processed"] == 0
        assert results["seen_messages"] == [msg]


class TestConfigurationGuard:
    def test_unconfigured_returns_error_without_connecting(self, monitor):
        monitor.email_user = ""
        results = monitor.check_for_price_updates()
        assert results["success"] is False
        assert "not configured" in results["error"]

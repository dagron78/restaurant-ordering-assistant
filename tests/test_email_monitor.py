"""Tests for the email monitor: vendor sender validation, price-document
detection, and the seen-marking contract (failed attachments must not
consume the message).
"""

import sys
import types

import pytest

import workers.email_monitor as email_monitor_module
from workers.email_monitor import EmailMonitor


class _StubAI:
    pass


@pytest.fixture()
def monitor(monkeypatch):
    """EmailMonitor with AI/DB construction stubbed out."""
    monkeypatch.setattr(email_monitor_module, 'GeminiEngine', _StubAI)
    return EmailMonitor()


class TestVendorSenderValidation:
    """F-09: the vendor check must match domains, not substrings."""

    def test_exact_domain_accepted(self, monitor):
        assert monitor._is_vendor_email('orders@sysco.com') == (True, 'Sysco')

    def test_subdomain_of_vendor_accepted(self, monitor):
        assert monitor._is_vendor_email('rep@mail.usfoods.com') == (True, 'US Foods')

    def test_spoofed_superdomain_rejected(self, monitor):
        # Substring matching accepted this attacker domain
        assert monitor._is_vendor_email('anyone@sysco.com.attacker.tld')[0] is False

    def test_vendor_name_in_local_part_elsewhere_rejected(self, monitor):
        assert monitor._is_vendor_email('sysco.com@attacker.tld')[0] is False

    def test_case_insensitive(self, monitor):
        assert monitor._is_vendor_email('SalesRep@SYSCO.Com') == (True, 'Sysco')

    def test_unrelated_sender_rejected(self, monitor):
        assert monitor._is_vendor_email('friend@gmail.com') == (False, None)

    def test_malformed_address_rejected(self, monitor):
        assert monitor._is_vendor_email('not-an-email')[0] is False
        assert monitor._is_vendor_email('')[0] is False
        assert monitor._is_vendor_email(None)[0] is False


class TestPriceDocumentDetection:
    @pytest.mark.parametrize('filename,expected', [
        ('sysco_price_list.pdf', True),      # keyword: price
        ('march_invoice.jpg', True),         # keyword: invoice
        ('weekly_catalog.xlsx', True),       # keyword: catalog
        ('order_sheet.png', True),           # pattern: sheet
        ('holiday_card.pdf', False),         # valid ext, no keywords
        ('notes.txt', False),                # invalid extension
        ('photo.jpeg', False),               # invalid extension
    ])
    def test_detection_matrix(self, monitor, filename, expected):
        assert monitor._is_price_document(filename) is expected


# ---- helpers for the mailbox flow test -------------------------------------

class FakeAttachment:
    def __init__(self, filename):
        self.filename = filename
        self.payload = b'bytes'


class FakeMessage:
    def __init__(self, from_, attachments):
        self.from_ = from_
        self.attachments = attachments


class FakeMailBox:
    def __init__(self, messages):
        self.messages = messages
        self.seen_calls = []

    def login(self, user, password):
        return self

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def fetch(self, criteria):
        return iter(self.messages)

    def seen(self, msg, value):
        self.seen_calls.append((msg, value))


def install_fake_imap(monkeypatch, messages):
    mailbox = FakeMailBox(messages)
    fake_module = types.ModuleType('imap_tools')
    fake_module.MailBox = lambda server: mailbox
    fake_module.AND = lambda **kw: kw
    monkeypatch.setitem(sys.modules, 'imap_tools', fake_module)
    return mailbox


@pytest.fixture()
def configured(monitor):
    monitor.email_user = 'orders@test'
    monitor.email_pass = 'secret'
    return monitor


class TestSeenMarkingContract:
    """F-06: a message may only be marked read once every attachment on it
    was processed without error - otherwise it must stay queued for retry."""

    def test_all_attachments_success_marks_seen(self, configured, monkeypatch):
        msg = FakeMessage('sales@sysco.com', [
            FakeAttachment('price_list.pdf'),
            FakeAttachment('invoice.png'),
        ])
        mailbox = install_fake_imap(monkeypatch, [msg])
        configured._process_attachment = lambda data, fn, vendor: (5, None)

        results = configured.check_for_price_updates()

        assert results['success'] is True
        assert results['processed'] == 2
        assert results['items_added'] == 10
        assert results['errors'] == []
        assert mailbox.seen_calls == [(msg, True)]

    def test_any_failure_leaves_message_unread(self, configured, monkeypatch):
        msg = FakeMessage('sales@sysco.com', [
            FakeAttachment('price_list.pdf'),   # succeeds
            FakeAttachment('invoice.png'),      # fails (e.g. Gemini outage)
        ])
        mailbox = install_fake_imap(monkeypatch, [msg])

        def process(data, filename, vendor):
            return (3, None) if filename.endswith('.pdf') else (0, 'API down')

        configured._process_attachment = process

        results = configured.check_for_price_updates()

        assert results['processed'] == 2
        assert results['errors'] == ['invoice.png: API down']
        assert mailbox.seen_calls == []  # message kept for retry

    def test_non_vendor_mail_ignored_entirely(self, configured, monkeypatch):
        msg = FakeMessage('newsletter@example.com', [FakeAttachment('price_list.pdf')])
        mailbox = install_fake_imap(monkeypatch, [msg])

        results = configured.check_for_price_updates()

        assert results['processed'] == 0
        assert results['vendors'] == {}
        assert mailbox.seen_calls == []

    def test_message_without_matching_attachments_marks_seen(
            self, configured, monkeypatch):
        # Nothing processable -> nothing to retry, so reading it is fine
        msg = FakeMessage('sales@sysco.com', [FakeAttachment('holiday_card.pdf')])
        mailbox = install_fake_imap(monkeypatch, [msg])

        results = configured.check_for_price_updates()

        assert results['processed'] == 0
        assert mailbox.seen_calls == [(msg, True)]


class TestConfigurationGuard:
    def test_unconfigured_returns_error_without_connecting(self, monitor):
        monitor.email_user = ''
        results = monitor.check_for_price_updates()
        assert results['success'] is False
        assert 'not configured' in results['error']

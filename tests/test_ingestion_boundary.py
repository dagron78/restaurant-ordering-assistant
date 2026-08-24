"""Tests for external review findings C, D and E on the ingestion/security
boundary: per-row extraction resilience, schema price bounds, auth-gate
config sourcing, and stdlib From-header parsing.
"""

import json
import pathlib
import sqlite3

import pytest

from core.config import Config
from core.ai_engine import GeminiEngine


# ---- helpers ----------------------------------------------------------------

class _StubAI:
    pass


@pytest.fixture()
def engine(monkeypatch):
    monkeypatch.setattr(Config, 'GOOGLE_API_KEY', 'test-key', raising=True)
    return GeminiEngine()


def _png(tmp_path):
    from PIL import Image
    path = tmp_path / 'doc.png'
    Image.new('RGB', (10, 10)).save(path)
    return path


@pytest.fixture()
def monitor(tmp_path):
    """EmailMonitor against a properly initialised tmp DB."""
    from core.database import Database
    import workers.email_monitor as em
    db = Database(db_path=tmp_path / "intake.db")
    db.init_database()
    db.get_or_create_vendor("Sysco", email_domain="sysco.com")
    db.get_or_create_vendor("US Foods", email_domain="usfoods.com")
    return em.EmailMonitor(db=db, ai=_StubAI())


class TestParseDocumentRowResilience:
    """C: one malformed row must cost its row, not the whole document."""

    def test_string_price_row_skipped_others_survive(self, engine, monkeypatch, tmp_path):
        raw = json.dumps([
            {'item_name': 'Good Item', 'price': 24.50},
            {'item_name': 'Not Applicable', 'price': 'N/A'},
            {'item_name': 'Currency Sign', 'price': '$24.50'},
            {'item_name': 'Also Good', 'price': 3.5},
        ])
        monkeypatch.setattr(engine, '_send_to_model',
                            lambda model_name, contents: raw)

        items = engine.parse_document(_png(tmp_path))

        names = [i['item_name'] for i in items]
        assert names == ['Good Item', 'Also Good']

    def test_non_dict_rows_ignored(self, engine, monkeypatch, tmp_path):
        raw = json.dumps([{'item_name': 'Fine', 'price': 1.0}, 'garbage', 42])
        monkeypatch.setattr(engine, '_send_to_model',
                            lambda model_name, contents: raw)

        items = engine.parse_document(_png(tmp_path))
        assert [i['item_name'] for i in items] == ['Fine']

    def test_non_array_response_discarded(self, engine, monkeypatch, tmp_path):
        monkeypatch.setattr(engine, '_send_to_model',
                            lambda model_name, contents: '{"a": 1}')
        assert engine.parse_document(_png(tmp_path)) == []


class TestSchemaPriceBounds:
    """C: the database itself refuses non-positive prices."""

    def test_negative_price_rejected(self, db):
        item_id = db.add_item('X', None, None)
        vendor_id = db.get_or_create_vendor('Sysco')
        with pytest.raises(sqlite3.IntegrityError):
            with db.get_connection() as conn:
                conn.execute(
                    """INSERT INTO price_history (item_id, vendor_id, price, unit)
                       VALUES (?, ?, -1.0, 'Each')""",
                    (item_id, vendor_id),
                )

    def test_zero_price_rejected(self, db):
        item_id = db.add_item('X', None, None)
        vendor_id = db.get_or_create_vendor('Sysco')
        with pytest.raises(sqlite3.IntegrityError):
            with db.get_connection() as conn:
                conn.execute(
                    """INSERT INTO price_history (item_id, vendor_id, price, unit)
                       VALUES (?, ?, 0.0, 'Each')""",
                    (item_id, vendor_id),
                )


class TestAuthGateConfigSourcing:
    """Phase A (issue #50): the gate must read credentials through the
    settings store via core.auth — never a Config.APP_PASSWORD constant
    (removed) and never os.getenv directly (fails open if core.config was
    not imported first)."""

    def test_gate_authenticates_through_the_store(self):
        gate_path = pathlib.Path(__file__).parent.parent / 'app' / 'components' / 'auth_gate.py'
        source = gate_path.read_text()
        assert 'auth.authenticate(' in source
        assert 'Config.APP_PASSWORD' not in source
        assert "os.getenv" not in source

    def test_config_no_longer_has_a_password_constant(self):
        # The eager plaintext password attribute is gone by design; the
        # only credential storage is the hashed settings table.
        assert not hasattr(Config, 'APP_PASSWORD')


class TestFromHeaderParsing:
    """E: parse the From header with email.utils.parseaddr."""

    @pytest.mark.parametrize('header,vendor', [
        ('orders@sysco.com', 'Sysco'),
        ('"Sysco Corporation" <orders@sysco.com>', 'Sysco'),
        ('<rep@usfoods.com>', 'US Foods'),
        ('Sysco Alerts <bounces@mail.sysco.com>', 'Sysco'),   # subdomain
        ('anyone@sysco.com.attacker.tld', None),               # spoof
        ('not-an-email', None),
        (None, None),
    ])
    def test_header_matrix(self, monitor, header, vendor):
        is_vendor, detected = monitor._is_vendor_email(header)
        assert is_vendor == (vendor is not None)
        assert detected == vendor

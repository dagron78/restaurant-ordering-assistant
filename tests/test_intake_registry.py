"""Phase: vendor intake (#28) — recognition from the vendors table,
quarantine for unknown senders, scraper registry.

Product decisions encoded here (issue #28 comment):
- Vendor names come from the vendors ROW, never synthesised from a domain
  stem (gfs.com must ingest beside Gordon Food Service, not beside a new
  'Gfs').
- Unknown senders are QUARANTINED - metadata only (from/subject/names).
  Nothing from them reaches the AI parser or price_history until a human
  promotes the sender; the mailbox message stays unseen so promoting the
  vendor re-ingests it naturally.
- Quarantine is attacker-writable display data: capped and truncated.
- A vendor with no scraper is valid: email-only intake.
"""


import pytest



@pytest.fixture()
def db_with_vendors(db):
    db.get_or_create_vendor("Gordon Food Service", email_domain="gfs.com")
    db.get_or_create_vendor("Sysco", email_domain="sysco.com",
                            scrape_url="https://shop.sysco.com")
    return db


class TestVendorRecognitionFromTable:
    def test_exact_domain_resolves_to_row_name(self, db_with_vendors):
        is_v, vendor = db_with_vendors.get_vendor_by_domain("orders@gfs.com")
        assert is_v is True
        assert vendor["name"] == "Gordon Food Service"   # NOT "Gfs"

    def test_subdomain_resolves(self, db_with_vendors):
        is_v, vendor = db_with_vendors.get_vendor_by_domain(
            "bounces@mail.sysco.com")
        assert is_v is True
        assert vendor["name"] == "Sysco"

    def test_unknown_domain_returns_none(self, db_with_vendors):
        assert db_with_vendors.get_vendor_by_domain("x@attacker.tld") == \
            (False, None)

    def test_spoofed_superdomain_rejected(self, db_with_vendors):
        assert db_with_vendors.get_vendor_by_domain(
            "a@sysco.com.attacker.tld") == (False, None)


class TestNameComesFromRow:
    def test_gfs_ingests_to_one_row_not_two(self, db_with_vendors, monkeypatch):
        """THE bug: domain stem 'gfs' synthesising a second 'Gfs' vendor."""
        monitor = _monitor(db_with_vendors)
        is_v, name = monitor._is_vendor_email("rep@gfs.com")
        assert is_v and name == "Gordon Food Service"

        # simulate the ingest write path using that name
        db_with_vendors.get_or_create_vendor(name)
        names = [v["name"] for v in db_with_vendors.get_all_vendors()]
        assert names.count("Gordon Food Service") == 1
        assert "Gfs" not in names

    def test_create_vendor_stores_domain_and_url(self, db_with_vendors):
        vid = db_with_vendors.get_or_create_vendor(
            "New Co", email_domain="newco.example",
            scrape_url="https://portal.newco.example")
        row = db_with_vendors.get_vendor(vendor_id=vid)
        assert row["email_domain"] == "newco.example"
        assert row["scrape_url"].endswith("newco.example")


class TestQuarantine:
    def test_unknown_sender_recorded_metadata_only(self, db_with_vendors, monkeypatch):
        m = _monitor(db_with_vendors)
        parsed_calls = []
        monkeypatch.setattr(m.ai, "parse_document",
                            lambda *a, **k: parsed_calls.append(a) or [])
        m._process_attachment = lambda *a, **k: (_ for _ in ()).throw(
            AssertionError("unknown sender must not be parsed"))

        msg = _msg(from_="stranger@newvendor.example",
                   subject="Our price list",
                   attachments=[_att("prices.pdf"), _att("notes.xlsx")])
        results = m.process_messages(messages=[msg])

        q = db_with_vendors.list_quarantine()
        assert len(q) == 1
        row = q[0]
        assert row["from_address"] == "stranger@newvendor.example"
        assert "price list" in row["subject"]
        assert "prices.pdf" in row["attachment_names"]
        assert "notes.xlsx" in row["attachment_names"]

        # metadata only: parser never invoked, nothing stored as prices
        assert parsed_calls == []
        assert results["items_added"] == 0

        # mailbox message stays UNSEEN so promotion re-ingests it
        assert results["left_unseen"] >= 1

        # surfaced in processing_log
        logs = db_with_vendors.get_recent_processing_logs(limit=5)
        assert any(lg["source_type"] == "email"
                   and "quarantine" in (lg["error_message"] or "").lower()
                   and "stranger@newvendor.example" in lg["source_identifier"]
                   for lg in logs)

    def test_duplicate_unknown_message_records_once(self, db_with_vendors, monkeypatch):
        m = _monitor(db_with_vendors)
        msg = _msg(from_="sales@brand.new", subject="Sheet v1",
                   attachments=[_att("sheet.pdf")])
        m.process_messages(messages=[msg])
        m.process_messages(messages=[msg])   # same sender+subject

        assert len(db_with_vendors.list_quarantine()) == 1

    def test_quarantine_fields_are_capped(self, db_with_vendors):
        long_from = "a" * 500 + "@evil.example"
        long_subject = "S" * 900
        weird_names = ["../../etc/passwd.pdf", "<script>alert(1)</script>.pdf"]
        db_with_vendors.add_quarantine(long_from, long_subject,
                                       weird_names)
        row = db_with_vendors.list_quarantine()[0]

        assert len(row["from_address"]) <= 254
        assert len(row["subject"]) <= 200
        assert ".." not in row["attachment_names"]      # no traversal
        assert "/" not in row["attachment_names"]       # basename only
        assert "<script>" not in row["attachment_names"]  # escaped for display

    def test_quarantine_capped_at_max_rows(self, db_with_vendors):
        for i in range(230):
            db_with_vendors.add_quarantine(
            f"s{i}@x.example", f"S{i}", [])
        assert len(db_with_vendors.list_quarantine(limit=1000)) <= 200

    def test_resolve_removes_from_queue(self, db_with_vendors):
        db_with_vendors.add_quarantine("v@ok.example", "Hi", ["a.pdf"])
        qid = db_with_vendors.list_quarantine()[0]["id"]
        db_with_vendors.resolve_quarantine(qid)
        assert db_with_vendors.list_quarantine() == []


class TestScraperRegistry:
    def test_known_vendor_gets_scraper_with_row_base_url(self, db_with_vendors):
        from workers.web_scraper import get_scraper_for
        row = db_with_vendors.get_vendor(name="Sysco")
        s = get_scraper_for(row, db=db_with_vendors)
        assert s is not None and s.vendor_name == "Sysco"
        assert s.base_url == "https://shop.sysco.com"

    def test_email_only_vendor_is_valid_without_scraper(self, db_with_vendors):
        from workers.web_scraper import get_scraper_for
        row = db_with_vendors.get_vendor(name="Gordon Food Service")
        assert get_scraper_for(row, db=db_with_vendors) is None

# ---- helpers -----------------------------------------------------------------

class _att:
    def __init__(self, filename):
        self.filename = filename
        self.payload = b"x"


class _msg:
    def __init__(self, from_, subject, attachments):
        self.from_ = from_
        self.subject = subject
        self.attachments = attachments


def _monitor(db):
    import workers.email_monitor as em
    inst = em.EmailMonitor.__new__(em.EmailMonitor)
    inst.db = db
    inst.ai = type("A", (), {"parse_document": staticmethod(
        lambda *a, **k: []), "validate_extracted_prices": staticmethod(lambda p: p)})()
    inst.email_user = "u"
    inst.email_pass = "p"
    inst.imap_server = "localhost"
    inst.vendor_domains = None          # dead path after #28; ensure unused
    inst.price_keywords = em.Config.PRICE_LIST_KEYWORDS
    inst.valid_extensions = em.Config.VALID_EXTENSIONS
    return inst

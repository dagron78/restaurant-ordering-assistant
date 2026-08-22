"""Phase 4 spec (issue #24): session probes must detect logged-IN
positively and fail closed. A missing login form is NOT authentication —
redirects, error pages and interstitials all lack login forms too.

Gate items encoded:
- fake logged-out page → zero stored prices, error logged, run 'failed'
- fake logged-in page (positive marker) → prices stored normally
- neither-marker page (error/redirect/empty) → treated as unauthenticated
- stamp-valid but probe-failing → aborted (probe beats the 30-day stamp)
- mid-scrape expiry → defined partial outcome: earlier rows kept, run
  recorded as partial with an explanatory processing_log row
"""

import pytest

from workers.web_scraper import SyscoScraper


class FakeElement:
    def __init__(self, price_text, tile_text):
        self._price_text = price_text
        self._tile_text = tile_text

    def inner_text(self):
        return self._price_text

    def evaluate(self, js):
        return self._tile_text


class FakePage:
    """Fake Playwright page: single-selector hits drive the auth probe,
    query_selector_all drives price extraction."""

    def __init__(self, single_hits=None, by_selector=None):
        self._single = single_hits or {}
        self._by_selector = by_selector or {}

    def wait_for_selector(self, selector, timeout=None):
        pass

    def query_selector(self, selector):
        return self._single.get(selector)

    def query_selector_all(self, selector):
        return self._by_selector.get(selector, [])

    def content(self):
        return '<html></html>'

    # navigation surface used by scrape_all_items
    def goto(self, url):
        self.last_url = url

    def wait_for_load_state(self, state=None):
        pass

    def set_default_timeout(self, t):
        pass


def logged_in_page():
    """Positive marker present; no login form."""
    hits = {'.account-menu': object()}
    prices = {'.product-price': [FakeElement('$24.50', 'Heavy Cream 40% Case')]}
    return FakePage(single_hits=hits, by_selector=prices)


def logged_out_page():
    """Login form present."""
    return FakePage(single_hits={'#login-form': object()})


def neither_page():
    """Redirect/error/interstitial: no login form AND no signed-in marker."""
    return FakePage()


@pytest.fixture()
def scraper(db):
    s = SyscoScraper(db=db, ai=type('A', (), {})())
    s.session_file = db.db_path.parent / 'sysco_auth.json'
    s.session_file.touch()
    # two items so mid-scrape expiry has something to interrupt
    db.add_item('Heavy Cream 40%', 'Dairy', 'Case')
    db.add_item('Whole Milk', 'Dairy', 'Gallon')
    return s


def _fake_playwright(monkeypatch, current_page):
    """Patch playwright.sync_api.sync_playwright (function-local import in
    scrape_all_items) to serve one fake page for the whole run."""
    class FakeBrowser:
        def new_context(self, storage_state=None): return self
        def new_page(self): return current_page
        def close(self): pass
    class FakePW:
        @property
        def chromium(self): return self
        def launch(self, headless=True): return FakeBrowser()
    class _Ctx:
        def __enter__(self): return FakePW()
        def __exit__(self, *a): return False
    monkeypatch.setattr('playwright.sync_api.sync_playwright',
                        lambda: _Ctx())


def _processing_rows(db):
    with db.get_connection() as conn:
        return [dict(r) for r in conn.execute(
            "SELECT status, error_message FROM processing_log "
            "ORDER BY id DESC LIMIT 1")]


class TestAuthProbeGate:
    def test_logged_out_aborts_with_zero_prices_and_failed_log(self, scraper, monkeypatch):
        page = logged_out_page()
        _fake_playwright(monkeypatch, page)

        results = scraper.scrape_all_items()

        assert results['success'] is False
        assert results['prices'] == []                       # zero stored
        assert results['items_scraped'] == 0
        assert 'auth' in results.get('error', '').lower() or \
               'authenticated' in results.get('error', '').lower()
        row = _processing_rows(scraper.db)[0]
        assert row['status'] == 'failed'
        assert 'authenticated' in (row['error_message'] or '').lower()
        # right reason: positive marker absent / login form seen
        combined = (results.get('error', '') + ' ' +
                    (results.get('auth_reason') or '')).lower()
        assert 'login form' in combined

    def test_neither_marker_nor_login_form_fails_closed(self, scraper, monkeypatch):
        page = neither_page()
        _fake_playwright(monkeypatch, page)

        results = scraper.scrape_all_items()

        assert results['success'] is False
        assert results['prices'] == []
        row = _processing_rows(scraper.db)[0]
        assert row['status'] == 'failed'
        combined = (results.get('error', '') + ' ' +
                    (results.get('auth_reason') or '')).lower()
        assert 'marker not found' in combined

    def test_logged_in_stores_prices_normally(self, scraper, monkeypatch):
        page = logged_in_page()
        _fake_playwright(monkeypatch, page)

        results = scraper.scrape_all_items()

        assert results['success'] is True
        assert results['items_scraped'] >= 1
        assert len(results['prices']) >= 1
        row = _processing_rows(scraper.db)[0]
        assert row['status'] == 'success'

    def test_probe_beats_valid_stamp(self, scraper, monkeypatch):
        """Session file exists and the 30-day DB stamp says valid - the live
        probe still aborts the run when the marker is absent."""
        vendor = scraper.db.get_or_create_vendor('Sysco')
        from datetime import datetime, timedelta
        scraper.db.update_vendor_session(vendor, datetime.now() + timedelta(days=30))
        assert scraper.has_valid_session() is True          # stamp says fine

        page = logged_out_page()
        _fake_playwright(monkeypatch, page)
        results = scraper.scrape_all_items()

        assert results['success'] is False                  # probe overruled it
        assert results['prices'] == []


class TestMidScrapeExpiry:
    def test_partial_outcome_is_defined(self, scraper, monkeypatch):
        """Session lapses after the first item: earlier rows stay (they were
        fetched under a verified session), run recorded PARTIAL with an
        error saying so - never silently identical to a clean scrape."""
        state = {"probes": 0}

        def flaky(self, page):
            state["probes"] += 1
            if state["probes"] >= 2:     # start-probe ok; next probe lapses
                return False, "signed-in marker not found"
            return True, "ok"

        monkeypatch.setattr(SyscoScraper, "_verify_logged_in", flaky)
        scraper.REPROBE_EVERY = 1

        good = logged_in_page()
        _fake_playwright(monkeypatch, good)

        results = scraper.scrape_all_items()

        monkeypatch.setattr(SyscoScraper, "_verify_logged_in",
                            SyscoScraper._verify_logged_in)

        assert results["success"] is False              # not a clean run
        assert results["session_expired_after_items"] == 1
        assert len(results["prices"]) == 1              # earlier row kept
        row = _processing_rows(scraper.db)[0]
        assert row["status"] == "partial"
        assert "expired" in (row["error_message"] or "").lower()

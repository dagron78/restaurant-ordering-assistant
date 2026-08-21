"""Tests for scraper pure logic: price parsing, product-tile matching,
extraction filtering, unit resolution, and session validity.

No browser is launched - Playwright pages are replaced with fakes.
"""

from datetime import datetime, timedelta

import pytest

from core.config import Config
from workers.web_scraper import SyscoScraper, USFoodsScraper, VendorScraper


class _StubAI:
    def analyze_html_for_selectors(self, html, item_name):
        return {}


@pytest.fixture()
def sysco(db):
    scraper = SyscoScraper(db=db, ai=_StubAI())
    scraper.session_file = db.db_path.parent / 'sysco_auth.json'
    return scraper


# ---- fake playwright objects -----------------------------------------------

class FakeElement:
    def __init__(self, price_text, tile_text):
        self._price_text = price_text
        self._tile_text = tile_text

    def inner_text(self):
        return self._price_text

    def evaluate(self, js):
        return self._tile_text


class FakePage:
    def __init__(self, by_selector):
        self._by_selector = by_selector
        self.wait_calls = []

    def wait_for_selector(self, selector, timeout=None):
        self.wait_calls.append(selector)

    def query_selector_all(self, selector):
        return self._by_selector.get(selector, [])

    def content(self):
        return '<html></html>'


# ---- pure helpers -----------------------------------------------------------

class TestParsePrice:
    @pytest.mark.parametrize('text,expected', [
        ('$24.50', 24.50),
        ('1,234.56', 1234.56),
        ('$42', 42.0),
        ('24,50', 24.50),      # decimal comma
        ('1,234', 1234.0),     # thousands separator
        ('  $9.99 each ', 9.99),
        ('no price here', None),
        ('', None),
    ])
    def test_formats(self, sysco, text, expected):
        assert sysco._parse_price(text) == expected


class TestTileMatching:
    """F-04 guard: only accept tiles that plausibly belong to the item."""

    def test_matching_tile_accepted(self):
        assert VendorScraper._tile_matches_item(
            'Heavy Cream 40% - Case of 12 - $29.99', 'Heavy Cream 40%')

    def test_partial_overlap_still_accepted(self):
        # At least half the item tokens present
        assert VendorScraper._tile_matches_item(
            'Heavy Cream Whipped Topping', 'Heavy Cream')

    def test_unrelated_tile_rejected(self):
        assert not VendorScraper._tile_matches_item(
            'Paper Towels 12 Pack', 'Heavy Cream')

    def test_sponsored_promo_tile_rejected(self):
        assert not VendorScraper._tile_matches_item(
            'Weekly Deals - Fryer Baskets on sale', 'Roma Tomatoes')

    def test_case_insensitive(self):
        assert VendorScraper._tile_matches_item('HEAVY CREAM case', 'heavy cream')


class TestExtractionFiltering:
    def test_skips_wrong_product_and_takes_matching_price(self, sysco):
        page = FakePage({
            '.product-price': [
                FakeElement('$19.99', 'Sponsored: Canola Oil 35lb'),   # wrong product
                FakeElement('$24.50', 'Heavy Cream 40% Case'),         # our item
            ],
        })

        result = sysco.extract_price_from_page(page, 'Heavy Cream 40%')

        assert result is not None
        assert result['price'] == 24.50
        assert result['confidence'] == 0.8

    def test_unit_is_none_not_hardcoded_each(self, sysco):
        """F-05: scrapers must not claim a unit they didn't read."""
        page = FakePage({'.product-price': [FakeElement('$24.50', 'Heavy Cream')]})

        result = sysco.extract_price_from_page(page, 'Heavy Cream')

        assert result['unit'] is None

    def test_returns_none_when_nothing_matches(self, sysco):
        page = FakePage({
            '.product-price': [FakeElement('$19.99', 'Unrelated Product')],
            '.price': [FakeElement('$5.00', 'Another Unrelated Thing')],
        })

        assert sysco.extract_price_from_page(page, 'Heavy Cream') is None

    def test_falls_through_to_later_selectors(self, sysco):
        page = FakePage({
            '.product-price': [FakeElement('$19.99', 'Wrong Item')],
            '.item-price': [FakeElement('$31.00', 'Heavy Cream 40%')],
        })

        result = sysco.extract_price_from_page(page, 'Heavy Cream 40%')
        assert result['price'] == 31.00

    def test_usfoods_scraper_uses_same_contract(self, db):
        scraper = USFoodsScraper(db=db, ai=_StubAI())
        page = FakePage({'.price-value': [FakeElement('$28.00', 'US Foods Heavy Cream')]})

        result = scraper.extract_price_from_page(page, 'Heavy Cream')

        assert result['price'] == 28.00
        assert result['vendor'] == 'US Foods'
        assert result['unit'] is None


class TestUnitResolution:
    """F-05 caller contract: fall back to the item's default unit."""

    def test_scraped_unit_wins_when_present(self):
        assert VendorScraper._resolve_unit({'unit': 'Lb'}, {'default_unit': 'Case'}) == 'Lb'

    def test_falls_back_to_item_default(self):
        assert VendorScraper._resolve_unit({'unit': None}, {'default_unit': 'Case'}) == 'Case'

    def test_final_fallback_is_each(self):
        assert VendorScraper._resolve_unit({}, {}) == 'Each'


class TestSessionValidity:
    def test_no_session_file_means_invalid(self, sysco):
        assert sysco.has_valid_session() is False

    def test_existing_file_without_expiry_is_valid(self, sysco):
        sysco.session_file.touch()
        assert sysco.has_valid_session() is True

    def test_expired_db_session_invalidates_file(self, sysco):
        sysco.session_file.touch()
        vendor_id = sysco.db.get_or_create_vendor(sysco.vendor_name)
        expired = datetime.now() - timedelta(days=1)
        sysco.db.update_vendor_session(vendor_id, expired)

        assert sysco.has_valid_session() is False

    def test_future_expiry_keeps_session_valid(self, sysco):
        sysco.session_file.touch()
        vendor_id = sysco.db.get_or_create_vendor(sysco.vendor_name)
        future = datetime.now() + timedelta(days=30)
        sysco.db.update_vendor_session(vendor_id, future)

        assert sysco.has_valid_session() is True

    def test_corrupt_expiry_does_not_crash(self, sysco):
        sysco.session_file.touch()
        vendor_id = sysco.db.get_or_create_vendor(sysco.vendor_name)
        with sysco.db.get_connection() as conn:
            conn.execute("UPDATE vendors SET session_expires = 'not-a-date' WHERE id = ?",
                         (vendor_id,))

        assert sysco.has_valid_session() is True

    def test_session_files_match_settings_page_expectations(self, db):
        """F-23 regression: scraper and Settings must agree on filenames."""
        assert Config.get_session_file('Sysco').name == 'sysco_auth.json'
        assert Config.get_session_file('US Foods').name == 'us_foods_auth.json'

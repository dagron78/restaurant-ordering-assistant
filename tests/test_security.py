"""Security-focused tests: password gate, credential removal, HTML scrubbing."""


from core.config import Config
from core.security import password_matches
from workers.web_scraper import VendorScraper


class TestPasswordGate:
    """F-10: shared-password gate helpers."""

    def test_correct_password_accepted(self, monkeypatch):
        assert password_matches('hunter2', 'hunter2') is True

    def test_wrong_password_rejected(self, monkeypatch):
        assert password_matches('wrong', 'hunter2') is False

    def test_empty_candidate_rejected(self, monkeypatch):
        assert password_matches('', 'hunter2') is False

    def test_no_expected_password_never_matches(self):
        # An unset expected value must not let every candidate through;
        # require_login() treats unset APP_PASSWORD as "auth disabled".
        assert password_matches('anything', '') is False
        assert password_matches(None, '') is False


class TestVendorCredentialRemoval:
    """F-12: vendor usernames/passwords must not exist anywhere in config -
    they were collected but never used, pure plaintext liability."""

    def test_config_has_no_credential_attributes(self):
        for attr in ('SYSCO_USER', 'SYSCO_PASS', 'USFOODS_USER', 'USFOODS_PASS'):
            assert not hasattr(Config, attr), f"Config.{attr} should be gone"

    def test_site_urls_are_kept(self):
        assert Config.SYSCO_URL.startswith('https://')
        assert Config.USFOODS_URL.startswith('https://')

    def test_validate_reports_only_real_dependencies(self):
        results = Config.validate()
        assert set(results) == {'gemini_api', 'email', 'database_dir', 'all_valid'}

    def test_dead_vendor_config_lookup_is_gone(self):
        assert not hasattr(Config, 'get_vendor_config')


class TestHtmlScrubbing:
    """F-15: authenticated page source must be sanitized before it goes to Gemini."""

    PAGE = """
    <html>
      <head><style>body { color: red; }</style></head>
      <body>
        <script>var accountNumber = 'ACCT-12345';</script>
        <!-- internal comment -->
        <div class="price">$24.50</div>
      </body>
    </html>
    """

    def test_scripts_removed(self):
        scrubbed = VendorScraper._scrub_html(self.PAGE)
        assert 'accountNumber' not in scrubbed
        assert '<script' not in scrubbed.lower()

    def test_styles_and_comments_removed(self):
        scrubbed = VendorScraper._scrub_html(self.PAGE)
        assert 'color: red' not in scrubbed
        assert 'internal comment' not in scrubbed

    def test_useful_markup_survives(self):
        scrubbed = VendorScraper._scrub_html(self.PAGE)
        assert '$24.50' in scrubbed

    def test_output_length_capped(self):
        huge = '<div>' + ('x' * 500_000) + '</div>'
        assert len(VendorScraper._scrub_html(huge)) <= VendorScraper.MAX_HTML_CHARS

    def test_empty_input_safe(self):
        assert VendorScraper._scrub_html('') == ''

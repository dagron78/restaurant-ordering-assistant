"""Tests for configuration invariants."""


from core.config import Config


class TestSessionFileNaming:
    """F-23: every writer and reader must derive the same filename."""

    def test_us_foods_session_name(self):
        assert Config.get_session_file('US Foods').name == 'us_foods_auth.json'

    def test_sysco_session_name(self):
        assert Config.get_session_file('Sysco').name == 'sysco_auth.json'

    def test_names_are_stable_and_lowercase(self):
        path = Config.get_session_file('Restaurant Depot')
        assert path.name == 'restaurant_depot_auth.json'


class TestGeminiModelDefaults:
    """F-08 guard: retired model IDs must never come back as defaults."""

    def test_defaults_are_not_retired_models(self):
        assert 'gemini-1.5' not in Config.GEMINI_MODEL_FLASH
        assert 'gemini-1.5' not in Config.GEMINI_MODEL_PRO

    def test_current_generation_defaults(self):
        assert Config.GEMINI_MODEL_FLASH == 'gemini-2.5-flash'
        assert Config.GEMINI_MODEL_PRO == 'gemini-2.5-pro'


class TestValidate:
    def test_all_configured(self, monkeypatch):
        monkeypatch.setattr(Config, 'GOOGLE_API_KEY', 'key', raising=True)
        monkeypatch.setattr(Config, 'EMAIL_USER', 'u', raising=True)
        monkeypatch.setattr(Config, 'EMAIL_PASS', 'p', raising=True)

        results = Config.validate()
        assert results['all_valid'] is True

    def test_missing_gemini_key_fails_validation(self, monkeypatch):
        monkeypatch.setattr(Config, 'GOOGLE_API_KEY', '', raising=True)
        monkeypatch.setattr(Config, 'EMAIL_USER', 'u', raising=True)
        monkeypatch.setattr(Config, 'EMAIL_PASS', 'p', raising=True)

        results = Config.validate()
        assert results['gemini_api'] is False
        assert results['all_valid'] is False

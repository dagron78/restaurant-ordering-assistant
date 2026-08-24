"""
Configuration management for Restaurant Ordering Assistant.

Phase A (issue #50): configuration is DATA, not import-time constants.

Bootstrap keys — the ones needed to boot far enough to read everything
else — still come from the environment:

    DATABASE_PATH             where the SQLite file lives
    INITIAL_ADMIN_PASSWORD    consumed once, at first-run seeding

Everything else is a row in the `settings` table behind the admin
password, resolved live on every read (see core/settings.py). That live
resolution is what makes a changed setting take effect on the next page
run without a restart: there is no snapshot anywhere to go stale.

Attribute mechanics: each managed key sits in the class body as a
_Settings descriptor whose __get__ consults the store. Assigning over one
(e.g. tests monkeypatching) shadows the descriptor with a plain value;
tests/conftest.py reinstates every descriptor after each test, so an
override can never leak from one test into another.
"""

import os
from pathlib import Path
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()


class _Settings:
    """Descriptor resolving a managed settings key live on every read."""

    def __init__(self, key: str):
        self.key = key

    def __get__(self, obj, objtype=None):
        from .settings import get_setting

        return get_setting(self.key)

    def __repr__(self):
        return f"_Settings({self.key!r})"


class Config:
    """Centralized configuration management."""

    # Base paths
    BASE_DIR = Path(__file__).parent.parent

    # Bootstrap-only environment reads. Everything below the separator
    # lives in the settings table — see core/settings.py for the typed
    # registry these descriptors resolve through.
    DATABASE_PATH: Path = BASE_DIR / os.getenv('DATABASE_PATH', 'data/restaurant_data.db')

    @staticmethod
    def initial_admin_password() -> str:
        """One-time admin password placed by the installer in .env.

        Consumed by first-run seeding; once an admin password hash exists
        in the settings table this value is ignored.
        """
        return os.getenv('INITIAL_ADMIN_PASSWORD', '')

    # ---------------------------------------------------------------
    # Live settings — rows in the `settings` table, admin-editable.
    # ---------------------------------------------------------------
    GOOGLE_API_KEY = _Settings("GOOGLE_API_KEY")
    GEMINI_MODEL_FLASH = _Settings("GEMINI_MODEL_FLASH")
    GEMINI_MODEL_PRO = _Settings("GEMINI_MODEL_PRO")

    EMAIL_USER = _Settings("EMAIL_USER")
    EMAIL_PASS = _Settings("EMAIL_PASS")
    EMAIL_IMAP_SERVER = _Settings("EMAIL_IMAP_SERVER")
    EMAIL_CHECK_INTERVAL = _Settings("EMAIL_CHECK_INTERVAL")

    PREFERENCES_PATH = _Settings("PREFERENCES_PATH")
    SESSIONS_PATH = _Settings("SESSIONS_PATH")
    TEMP_PATH = _Settings("TEMP_PATH")

    SCRAPE_DAY = _Settings("SCRAPE_DAY")
    SCRAPE_HOUR = _Settings("SCRAPE_HOUR")
    SCRAPE_DELAY_SECS = _Settings("SCRAPE_DELAY_SECS")

    TREND_DAYS = _Settings("TREND_DAYS")
    SPIKE_THRESHOLD = _Settings("SPIKE_THRESHOLD")
    DEAL_THRESHOLD = _Settings("DEAL_THRESHOLD")

    # ---------------------------------------------------------------
    # Static application constants (not operator settings)
    # ---------------------------------------------------------------
    SCHEMA_PATH: Path = BASE_DIR / 'scripts' / 'schema.sql'

    # Price list keywords for email filtering
    PRICE_LIST_KEYWORDS: list = ['price', 'catalog', 'list', 'quote', 'invoice', 'pricing']

    # Valid attachment extensions
    VALID_EXTENSIONS: list = ['.pdf', '.jpg', '.jpeg', '.png', '.xlsx', '.xls', '.csv']

    @classmethod
    def ensure_directories(cls) -> None:
        """Create necessary directories if they don't exist."""
        directories = [
            cls.DATABASE_PATH.parent,
            cls.SESSIONS_PATH,
            cls.TEMP_PATH,
        ]
        for directory in directories:
            directory.mkdir(parents=True, exist_ok=True)

    @classmethod
    def get_session_file(cls, vendor_name: str) -> Path:
        """Get the session file path for a specific vendor."""
        safe_name = vendor_name.lower().replace(' ', '_')
        return cls.SESSIONS_PATH / f"{safe_name}_auth.json"

    @classmethod
    def validate(cls) -> dict:
        """
        Validate configuration and return status.

        Returns:
            dict with validation results for each config section
        """
        results = {
            'gemini_api': bool(cls.GOOGLE_API_KEY),
            'email': bool(cls.EMAIL_USER and cls.EMAIL_PASS),
            'database_dir': cls.DATABASE_PATH.parent.exists(),
        }
        results['all_valid'] = all([
            results['gemini_api'],
            results['email'],
            results['database_dir']
        ])
        return results


# Ensure directories exist on module load
Config.ensure_directories()

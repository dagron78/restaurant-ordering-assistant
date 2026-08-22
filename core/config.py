"""
Configuration management for Restaurant Ordering Assistant.

Loads settings from environment variables and provides
centralized access to all configuration values.
"""

import os
from pathlib import Path
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()


class Config:
    """Centralized configuration management."""
    
    # Base paths
    BASE_DIR = Path(__file__).parent.parent
    
    # Google Gemini API
    GOOGLE_API_KEY: str = os.getenv('GOOGLE_API_KEY', '')
    
    # Gemini models (gemini-1.5-* are retired)
    GEMINI_MODEL_FLASH: str = os.getenv('GEMINI_MODEL_FLASH', 'gemini-2.5-flash')
    GEMINI_MODEL_PRO: str = os.getenv('GEMINI_MODEL_PRO', 'gemini-2.5-pro')
    
    # Email configuration
    EMAIL_USER: str = os.getenv('EMAIL_USER', '')
    EMAIL_PASS: str = os.getenv('EMAIL_PASS', '')
    EMAIL_IMAP_SERVER: str = os.getenv('EMAIL_IMAP_SERVER', 'imap.gmail.com')
    EMAIL_CHECK_INTERVAL: int = int(os.getenv('EMAIL_CHECK_INTERVAL', '8'))
    
    # File paths
    DATABASE_PATH: Path = BASE_DIR / os.getenv('DATABASE_PATH', 'data/restaurant_data.db')
    PREFERENCES_PATH: Path = BASE_DIR / os.getenv('PREFERENCES_PATH', 'data/preferences.txt')
    SESSIONS_PATH: Path = BASE_DIR / os.getenv('SESSIONS_PATH', 'data/sessions')
    TEMP_PATH: Path = BASE_DIR / os.getenv('TEMP_PATH', 'data/temp')
    SCHEMA_PATH: Path = BASE_DIR / 'scripts' / 'schema.sql'
    
    # Scheduling
    SCRAPE_DAY: int = int(os.getenv('SCRAPE_DAY', '0'))  # 0=Monday
    SCRAPE_HOUR: int = int(os.getenv('SCRAPE_HOUR', '4'))
    
    # Pause between per-item page loads during a scrape (seconds)
    SCRAPE_DELAY_SECS: float = float(os.getenv('SCRAPE_DELAY_SECS', '2'))
    
    # Optional app password. When set, every UI page requires it.
    APP_PASSWORD: str = os.getenv('APP_PASSWORD', '')
    
    # Price list keywords for email filtering
    PRICE_LIST_KEYWORDS: list = ['price', 'catalog', 'list', 'quote', 'invoice', 'pricing']
    
    # Valid attachment extensions
    VALID_EXTENSIONS: list = ['.pdf', '.jpg', '.jpeg', '.png', '.xlsx', '.xls', '.csv']
    
    # Trend analysis settings
    TREND_DAYS: int = 30  # Days to consider for rolling average
    SPIKE_THRESHOLD: float = 0.10  # 10% increase = spike
    DEAL_THRESHOLD: float = -0.10  # 10% decrease = deal
    
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

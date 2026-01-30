"""
Background workers for Restaurant Ordering Assistant.

This package contains automated workers:
- email_monitor: Monitors email for price list attachments
- web_scraper: Scrapes vendor websites for prices
- scheduler: Coordinates background tasks
"""

from .email_monitor import EmailMonitor, run_email_check
from .web_scraper import VendorScraper, SyscoScraper, USFoodsScraper

__all__ = [
    'EmailMonitor', 
    'run_email_check',
    'VendorScraper',
    'SyscoScraper',
    'USFoodsScraper'
]

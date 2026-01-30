#!/usr/bin/env python3
"""
Vendor Login Session Refresh Script

Utility script to manually refresh vendor login sessions.
Opens a browser window for the user to log in, then saves
the session for automated scraping.

Usage:
    python scripts/refresh_login.py sysco
    python scripts/refresh_login.py usfoods
    python scripts/refresh_login.py --all
"""

import sys
import argparse
from pathlib import Path

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from workers.web_scraper import SyscoScraper, USFoodsScraper


def refresh_sysco():
    """Refresh Sysco login session."""
    print("\n" + "="*50)
    print("🏪 Refreshing Sysco Session")
    print("="*50)
    
    scraper = SyscoScraper()
    success = scraper.refresh_session()
    
    return success


def refresh_usfoods():
    """Refresh US Foods login session."""
    print("\n" + "="*50)
    print("🏪 Refreshing US Foods Session")
    print("="*50)
    
    scraper = USFoodsScraper()
    success = scraper.refresh_session()
    
    return success


def main():
    parser = argparse.ArgumentParser(
        description='Refresh vendor login sessions for web scraping'
    )
    parser.add_argument(
        'vendor',
        nargs='?',
        choices=['sysco', 'usfoods'],
        help='Vendor to refresh session for'
    )
    parser.add_argument(
        '--all',
        action='store_true',
        help='Refresh all vendor sessions'
    )
    
    args = parser.parse_args()
    
    if args.all:
        print("\n🔄 Refreshing all vendor sessions...")
        refresh_sysco()
        refresh_usfoods()
        print("\n✅ All sessions refreshed!")
        
    elif args.vendor == 'sysco':
        refresh_sysco()
        
    elif args.vendor == 'usfoods':
        refresh_usfoods()
        
    else:
        parser.print_help()
        print("\nExamples:")
        print("  python scripts/refresh_login.py sysco")
        print("  python scripts/refresh_login.py usfoods")
        print("  python scripts/refresh_login.py --all")


if __name__ == '__main__':
    main()

"""
Web Scraper Worker for Restaurant Ordering Assistant.

Automates price scraping from vendor websites using Playwright.
Uses session persistence to maintain login state between runs.
"""

import sys
import math
import re
from pathlib import Path
from datetime import datetime, timedelta
from typing import List, Dict, Optional, Any
from abc import ABC, abstractmethod

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from core.config import Config
from core.database import Database
from core.ai_engine import GeminiEngine


class VendorScraper(ABC):
    """
    Base class for vendor-specific scrapers.
    
    Uses Playwright with session persistence to maintain login state.
    Subclasses implement vendor-specific scraping logic.
    """
    
    def __init__(self, vendor_name: str, base_url: str,
                 db: Database = None, ai: GeminiEngine = None):
        """
        Initialize the scraper.
        
        Args:
            vendor_name: Name of the vendor
            base_url: Base URL for the vendor site
            db: Database instance (creates new if not provided)
            ai: GeminiEngine instance (creates new if not provided)
        """
        self.vendor_name = vendor_name
        self.base_url = base_url
        self.session_file = Config.get_session_file(vendor_name)
        
        self.db = db or Database()
        self.ai = ai or GeminiEngine()
        
        # Scraping configuration
        self.headless = True
        self.timeout = 30000  # 30 seconds
    
    def _check_playwright(self) -> bool:
        """Check if Playwright is available."""
        try:
            # The import itself is the availability probe
            from playwright.sync_api import sync_playwright  # noqa: F401
            return True
        except ImportError:
            return False
    
    def has_valid_session(self) -> bool:
        """
        Check if a valid session file exists.
        
        Returns:
            True if session file exists and is not expired
        """
        if not self.session_file.exists():
            return False
        
        # Check vendor session expiration in database
        vendor = self.db.get_vendor(name=self.vendor_name)
        if vendor and vendor.get('session_expires'):
            try:
                expires = datetime.fromisoformat(vendor['session_expires'])
                if datetime.now() > expires:
                    return False
            except (ValueError, TypeError):
                pass
        
        return True
    
    def refresh_session(self, login_url: str = None) -> bool:
        """
        Manually refresh the login session.
        
        Opens a browser window for the user to log in manually.
        Saves the session state for future automated runs.
        
        Args:
            login_url: Optional specific login URL
            
        Returns:
            True if session was saved successfully
        """
        if not self._check_playwright():
            print("Error: Playwright not installed. Run: pip install playwright && playwright install")
            return False
        
        from playwright.sync_api import sync_playwright
        
        url = login_url or self.base_url
        
        print(f"\n{'='*50}")
        print(f"🔐 Session Refresh for {self.vendor_name}")
        print(f"{'='*50}")
        print(f"\nOpening browser to: {url}")
        print("\n⚠️  IMPORTANT:")
        print(f"   1. Log in to your {self.vendor_name} account")
        print("   2. Navigate to the main product/ordering page")
        print("   3. Return here and press Enter when done")
        
        try:
            with sync_playwright() as p:
                browser = p.chromium.launch(headless=False)
                context = browser.new_context()
                page = context.new_page()
                
                page.goto(url)
                
                input("\n✋ Press Enter after logging in successfully...")
                
                # Save session state
                self.session_file.parent.mkdir(parents=True, exist_ok=True)
                context.storage_state(path=str(self.session_file))
                
                browser.close()
            
            # Update vendor session expiration (30 days from now)
            vendor = self.db.get_vendor(name=self.vendor_name)
            if vendor:
                expires = datetime.now() + timedelta(days=30)
                self.db.update_vendor_session(vendor['id'], expires)
            
            print(f"\n✓ Session saved to: {self.session_file}")
            print("  Session valid for 30 days")
            
            return True
            
        except Exception as e:
            print(f"\n✗ Error refreshing session: {e}")
            return False
    
    def _get_browser_context(self, playwright: Any):
        """
        Get a browser context with saved session.
        
        Args:
            playwright: Playwright instance
            
        Returns:
            Browser context with session loaded
        """
        browser = playwright.chromium.launch(headless=self.headless)
        
        if self.session_file.exists():
            context = browser.new_context(storage_state=str(self.session_file))
        else:
            context = browser.new_context()
        
        return browser, context
    
    @abstractmethod
    def get_search_url(self, item_name: str) -> str:
        """
        Get the search URL for an item.
        
        Args:
            item_name: Name of item to search for
            
        Returns:
            Full URL for searching
        """
        pass
    
    @abstractmethod
    def extract_price_from_page(self, page: Any, item_name: str) -> Optional[Dict]:
        """
        Extract price information from a search results page.
        
        Args:
            page: Playwright page object
            item_name: Name of item being searched
            
        Returns:
            Dict with price info or None if not found
        """
        pass
    
    # Shared extraction helpers ===================================
    
    @staticmethod
    def _parse_price(price_text: str) -> Optional[float]:
        """Parse a price from text like '$1,234.56' or '24,50'."""
        cleaned = re.sub(r'[^\d.,]', '', price_text)
        
        if ',' in cleaned and '.' in cleaned:
            # Format: 1,234.56
            cleaned = cleaned.replace(',', '')
        elif ',' in cleaned:
            # Could be 1,234 (thousands) or 1,23 (decimal comma)
            parts = cleaned.split(',')
            if len(parts[-1]) == 2:
                cleaned = cleaned.replace(',', '.')
            else:
                cleaned = cleaned.replace(',', '')
        
        try:
            return float(cleaned)
        except ValueError:
            return None
    
    @staticmethod
    def _tile_matches_item(tile_text: str, item_name: str) -> bool:
        """
        Check whether a product tile's text plausibly belongs to the item.
        
        Guards against storing the price of a near-miss neighbour (Ground
        Turkey 93/7 for Ground Beef 80/20, foil wrap for Heavy Cream 40%).
        
        Rules:
        - tokens shorter than 3 chars are dropped UNLESS numeric: '40',
          '80', '20' are the grade markers that separate SKUs
        - every numeric token in the item name must appear in the tile:
          80/20 is not 73/27
        - short names (<=3 words): ALL words must match; longer names use
          a ceiling-half threshold
        
        Note this deliberately still accepts e.g. 'Heavy Cream Whipped
        Topping' for 'Heavy Cream' - distinguishing product variants
        needs product-identity matching, out of scope here.
        
        Args:
            tile_text: Text of the candidate product tile
            item_name: The item being searched
            
        Returns:
            True if the tile looks like the searched product
        """
        def tokenize(text: str) -> List[str]:
            return [t for t in re.findall(r'[a-z0-9]+', text.lower())
                    if len(t) > 2 or t.isdigit()]
        
        item_tokens = tokenize(item_name)
        if not item_tokens:
            return bool(tile_text and tile_text.strip())
        
        tile_tokens = set(tokenize(tile_text))
        
        # Every grade/size number must be present in the tile
        numerics = [t for t in item_tokens if any(ch.isdigit() for ch in t)]
        if any(t not in tile_tokens for t in numerics):
            return False
        
        words = [t for t in item_tokens if t not in numerics]
        hits = sum(1 for t in words if t in tile_tokens)
        if len(words) <= 3:
            return hits == len(words)
        return hits >= math.ceil(len(words) / 2)
    
    def _extract_price_via_selectors(self, page: Any, item_name: str,
                                     price_selectors: List[str],
                                     confidence: float = 0.8) -> Optional[Dict]:
        """
        Find the searched item's price using a list of CSS selectors.
        
        Only accepts a price whose surrounding product tile matches the
        item name - the first price on the page may belong to a promoted
        or unrelated product. Returns None rather than guessing.
        
        Args:
            page: Playwright page object
            item_name: Name of item being searched
            price_selectors: Candidate CSS selectors for price elements
            confidence: Confidence score to attach on success
            
        Returns:
            Dict with price info (unit None = not determined from page),
            or None if no matching product/price pair was found
        """
        tile_js = (
            "el => { const t = el.closest("
            "'.product-card, .product-tile, [data-testid=\"product\"], "
            "[data-product], article, li');"
            " const box = t || el.parentElement; return box ? box.innerText : ''; }"
        )
        
        for selector in price_selectors:
            try:
                elements = page.query_selector_all(selector)
            except Exception:
                continue
            
            for element in elements:
                try:
                    tile_text = element.evaluate(tile_js)
                except Exception:
                    tile_text = ''
                
                if not self._tile_matches_item(tile_text or '', item_name):
                    continue
                
                price = self._parse_price(element.inner_text())
                if price is not None:
                    return {
                        'item_name': item_name,
                        'price': price,
                        'vendor': self.vendor_name,
                        'unit': None,
                        'confidence': confidence
                    }
        
        return None
    
    @staticmethod
    def _resolve_unit(price_data: Dict, item: Dict) -> str:
        """
        Resolve the unit for a scraped price.
        
        Scrapers return unit=None when the page doesn't state one; fall
        back to the item's default unit instead of assuming 'Each'.
        """
        return price_data.get('unit') or item.get('default_unit', 'Each')
    
    def scrape_item(self, item_name: str) -> Optional[Dict]:
        """
        Scrape price for a single item.
        
        Args:
            item_name: Name of the item to scrape
            
        Returns:
            Dict with item, price, vendor, unit or None
        """
        if not self._check_playwright():
            return None
        
        if not self.has_valid_session():
            print(f"⚠️  No valid session for {self.vendor_name}. Run refresh_session() first.")
            return None
        
        from playwright.sync_api import sync_playwright
        
        try:
            with sync_playwright() as p:
                browser, context = self._get_browser_context(p)
                page = context.new_page()
                page.set_default_timeout(self.timeout)
                
                # Navigate to search
                search_url = self.get_search_url(item_name)
                page.goto(search_url)
                page.wait_for_load_state('networkidle')
                
                # Extract price
                result = self.extract_price_from_page(page, item_name)
                
                browser.close()
                
                return result
                
        except Exception as e:
            print(f"Error scraping {item_name} from {self.vendor_name}: {e}")
            return None
    
    def scrape_all_items(self) -> Dict:
        """
        Scrape prices for all active items in the database.
        
        Returns:
            Dict with scraping results
        """
        if not self._check_playwright():
            return {
                'success': False,
                'error': 'Playwright not installed',
                'items_scraped': 0
            }
        
        if not self.has_valid_session():
            return {
                'success': False,
                'error': f'No valid session for {self.vendor_name}',
                'items_scraped': 0
            }
        
        from playwright.sync_api import sync_playwright
        
        # Get all active items
        items = self.db.get_all_items(active_only=True)
        
        results = {
            'success': True,
            'vendor': self.vendor_name,
            'items_scraped': 0,
            'items_failed': 0,
            'prices': [],
            'errors': []
        }
        
        try:
            with sync_playwright() as p:
                browser, context = self._get_browser_context(p)
                page = context.new_page()
                page.set_default_timeout(self.timeout)
                
                for item in items:
                    item_name = item['name']
                    
                    try:
                        # Navigate to search
                        search_url = self.get_search_url(item_name)
                        page.goto(search_url)
                        page.wait_for_load_state('networkidle')
                        
                        # Extract price
                        price_data = self.extract_price_from_page(page, item_name)
                        
                        if price_data:
                            # Save to database
                            self.db.add_price(
                                item_name=item_name,
                                vendor_name=self.vendor_name,
                                price=price_data['price'],
                                unit=self._resolve_unit(price_data, item),
                                source='scrape',
                                confidence=price_data.get('confidence', 0.8)
                            )
                            
                            results['items_scraped'] += 1
                            results['prices'].append(price_data)
                            print(f"  ✓ {item_name}: ${price_data['price']}")
                        else:
                            results['items_failed'] += 1
                            results['errors'].append(f"{item_name}: Price not found")
                            print(f"  ✗ {item_name}: Not found")
                        
                    except Exception as e:
                        results['items_failed'] += 1
                        results['errors'].append(f"{item_name}: {str(e)}")
                        print(f"  ✗ {item_name}: Error - {e}")
                
                browser.close()
            
            # Log processing
            self.db.log_processing(
                source_type='scrape',
                source_identifier=self.vendor_name,
                filename='weekly_scrape',
                status='success' if results['items_scraped'] > 0 else 'partial',
                items_processed=results['items_scraped']
            )
            
            return results
            
        except Exception as e:
            results['success'] = False
            results['error'] = str(e)
            
            self.db.log_processing(
                source_type='scrape',
                source_identifier=self.vendor_name,
                filename='weekly_scrape',
                status='failed',
                error_message=str(e)
            )
            
            return results


class SyscoScraper(VendorScraper):
    """Sysco-specific scraper implementation."""
    
    def __init__(self, **kwargs):
        super().__init__(
            vendor_name='Sysco',
            base_url=Config.SYSCO_URL,
            **kwargs
        )
    
    def get_search_url(self, item_name: str) -> str:
        """Get Sysco search URL."""
        from urllib.parse import quote
        return f"{self.base_url}/shop/search?q={quote(item_name)}"
    
    def extract_price_from_page(self, page: Any, item_name: str) -> Optional[Dict]:
        """
        Extract price from Sysco search results page.
        
        Note: This is a template implementation. The actual selectors
        may need to be updated based on Sysco's current website structure.
        """
        try:
            # Wait for search results
            page.wait_for_selector('.product-card, .search-results, [data-testid="product"]', timeout=10000)
            
            # Try common price selectors; only tiles matching the item are accepted
            result = self._extract_price_via_selectors(page, item_name, [
                '.product-price',
                '.price',
                '[data-testid="price"]',
                '.item-price',
                '.product-card .price'
            ])
            if result:
                return result
            
            # If no price found with standard selectors, use AI
            html = page.content()
            selectors = self.ai.analyze_html_for_selectors(html, item_name)
            
            if selectors.get('price_selector'):
                return self._extract_price_via_selectors(
                    page, item_name, [selectors['price_selector']], confidence=0.6
                )
            
            return None
            
        except Exception as e:
            print(f"Error extracting price for {item_name}: {e}")
            return None


class USFoodsScraper(VendorScraper):
    """US Foods-specific scraper implementation."""
    
    def __init__(self, **kwargs):
        super().__init__(
            vendor_name='US Foods',
            base_url=Config.USFOODS_URL,
            **kwargs
        )
    
    def get_search_url(self, item_name: str) -> str:
        """Get US Foods search URL."""
        from urllib.parse import quote
        return f"{self.base_url}/shop/search?query={quote(item_name)}"
    
    def extract_price_from_page(self, page: Any, item_name: str) -> Optional[Dict]:
        """
        Extract price from US Foods search results page.
        
        Note: This is a template implementation. The actual selectors
        may need to be updated based on US Foods' current website structure.
        """
        try:
            # Wait for search results
            page.wait_for_selector('.product-tile, .product-list, [data-product]', timeout=10000)
            
            # Try common price selectors; only tiles matching the item are accepted
            result = self._extract_price_via_selectors(page, item_name, [
                '.product-price',
                '.price-value',
                '[data-price]',
                '.item-price',
                '.product-tile .price'
            ])
            if result:
                return result
            
            # If no price found, use AI analysis
            html = page.content()
            selectors = self.ai.analyze_html_for_selectors(html, item_name)
            
            if selectors.get('price_selector'):
                return self._extract_price_via_selectors(
                    page, item_name, [selectors['price_selector']], confidence=0.6
                )
            
            return None
            
        except Exception as e:
            print(f"Error extracting price for {item_name}: {e}")
            return None


def run_weekly_scrape() -> Dict:
    """
    Entry point for scheduled weekly scraping.
    
    Returns:
        Combined results from all scrapers
    """
    print(f"\n{'='*50}")
    print(f"🌐 Weekly Vendor Scrape - {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"{'='*50}")
    
    combined_results = {
        'success': True,
        'vendors': {},
        'total_items': 0,
        'total_errors': 0
    }
    
    scrapers = [SyscoScraper(), USFoodsScraper()]
    
    for scraper in scrapers:
        print(f"\n📦 Scraping {scraper.vendor_name}...")
        
        if not scraper.has_valid_session():
            print("  ⚠️ No valid session. Skipping.")
            combined_results['vendors'][scraper.vendor_name] = {
                'success': False,
                'error': 'No valid session'
            }
            continue
        
        results = scraper.scrape_all_items()
        
        combined_results['vendors'][scraper.vendor_name] = results
        combined_results['total_items'] += results.get('items_scraped', 0)
        combined_results['total_errors'] += results.get('items_failed', 0)
        
        if not results.get('success'):
            combined_results['success'] = False
    
    print(f"\n{'='*50}")
    print("Scraping complete!")
    print(f"  Total items updated: {combined_results['total_items']}")
    print(f"  Total errors: {combined_results['total_errors']}")
    print(f"{'='*50}")
    
    return combined_results


if __name__ == '__main__':
    import argparse
    
    parser = argparse.ArgumentParser(description='Vendor web scraper')
    parser.add_argument('--refresh', choices=['sysco', 'usfoods'], 
                       help='Refresh session for a vendor')
    parser.add_argument('--scrape', action='store_true',
                       help='Run weekly scrape')
    
    args = parser.parse_args()
    
    if args.refresh:
        if args.refresh == 'sysco':
            scraper = SyscoScraper()
        else:
            scraper = USFoodsScraper()
        
        scraper.refresh_session()
    
    elif args.scrape:
        run_weekly_scrape()
    
    else:
        parser.print_help()

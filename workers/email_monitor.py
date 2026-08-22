"""
Email Monitor Worker for Restaurant Ordering Assistant.

Monitors a dedicated email account for price list attachments
from vendor sales reps. Uses Gemini to parse documents and
update the database with new prices.
"""

import sys
from email.utils import parseaddr
from pathlib import Path
from datetime import datetime
from typing import Optional, Tuple

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from core.config import Config
from core.database import Database
from core.ai_engine import GeminiEngine
import logging

log = logging.getLogger(__name__)


class EmailMonitor:
    """
    Monitors email for price list attachments and processes them.
    
    Connects via IMAP, downloads attachments from vendor emails,
    parses them with Gemini, and updates the price database.
    """
    
    def __init__(self):
        """Initialize the email monitor."""
        self.email_user = Config.EMAIL_USER
        self.email_pass = Config.EMAIL_PASS
        self.imap_server = Config.EMAIL_IMAP_SERVER
        
        self.ai = GeminiEngine()
        self.db = Database()
        
        # Vendor domains to watch
        self.vendor_domains = Config.VENDOR_EMAIL_DOMAINS
        
        # Keywords for price list detection
        self.price_keywords = Config.PRICE_LIST_KEYWORDS
        
        # Valid file extensions
        self.valid_extensions = Config.VALID_EXTENSIONS
    
    def _is_configured(self) -> bool:
        """Check if email credentials are configured."""
        return bool(self.email_user and self.email_pass)
    
    def _is_vendor_email(self, from_address: str) -> Tuple[bool, Optional[str]]:
        """
        Check if email is from a known vendor.
        
        Args:
            from_address: Email sender address (may be a full From header,
                e.g. '"Sysco Corp" <orders@sysco.com>')
            
        Returns:
            Tuple of (is_vendor, vendor_name)
        """
        # Parse with the stdlib: display names, angle brackets and other
        # header edge cases are more than an rsplit/rstrip can cover.
        address = (parseaddr(from_address or '')[1] or '').lower()
        if '@' not in address:
            return False, None
        
        # Compare the actual domain, not a substring: 'sysco.com' in
        # 'anyone@sysco.com.attacker.tld' is true but the mail is not ours.
        domain = address.rsplit('@', 1)[1].rstrip('>.')
        
        for vendor_domain in self.vendor_domains:
            if domain == vendor_domain or domain.endswith('.' + vendor_domain):
                # Determine vendor name
                if 'sysco' in vendor_domain:
                    return True, 'Sysco'
                elif 'usfoods' in vendor_domain:
                    return True, 'US Foods'
                else:
                    return True, vendor_domain.split('.')[0].title()
        
        return False, None
    
    def _is_price_document(self, filename: str) -> bool:
        """
        Check if attachment is likely a price list.
        
        Args:
            filename: Attachment filename
            
        Returns:
            True if file appears to be a price document
        """
        filename_lower = filename.lower()
        
        # Check extension
        ext_valid = any(filename_lower.endswith(ext) for ext in self.valid_extensions)
        
        if not ext_valid:
            return False
        
        # Check for price-related keywords
        has_keyword = any(kw in filename_lower for kw in self.price_keywords)
        
        # Also accept common attachment patterns
        common_patterns = ['attachment', 'document', 'list', 'sheet']
        has_pattern = any(pattern in filename_lower for pattern in common_patterns)
        
        return has_keyword or has_pattern
    
    def _process_attachment(self, attachment_data: bytes, filename: str, 
                           vendor_name: str) -> Tuple[int, Optional[str]]:
        """
        Process a single attachment.
        
        Args:
            attachment_data: Raw attachment bytes
            filename: Original filename
            vendor_name: Name of the vendor
            
        Returns:
            Tuple of (items_processed, error_message)
        """
        temp_path = None
        
        try:
            # Determine file extension
            ext = Path(filename).suffix.lower()
            
            # Save to temp file
            Config.TEMP_PATH.mkdir(parents=True, exist_ok=True)
            temp_path = Config.TEMP_PATH / f"attachment_{datetime.now().strftime('%Y%m%d_%H%M%S')}{ext}"
            
            with open(temp_path, 'wb') as f:
                f.write(attachment_data)
            
            # Parse with Gemini
            if ext in ['.jpg', '.jpeg', '.png', '.pdf']:
                parsed_data = self.ai.parse_document(temp_path, vendor_hint=vendor_name)
            else:
                # For Excel/CSV, we'd need different handling
                # For now, skip non-image formats
                return 0, f"Unsupported format: {ext}"
            
            if not parsed_data:
                return 0, "No items extracted from document"
            
            # Validate prices
            validated_data = self.ai.validate_extracted_prices(parsed_data)
            
            # Save to database
            count = self.db.add_prices_batch(validated_data, source='email')
            
            # Log processing
            self.db.log_processing(
                source_type='email',
                source_identifier=vendor_name,
                filename=filename,
                status='success' if count > 0 else 'partial',
                items_processed=count
            )
            
            return count, None
            
        except Exception as e:
            error_msg = str(e)
            
            # Log failure
            self.db.log_processing(
                source_type='email',
                source_identifier=vendor_name,
                filename=filename,
                status='failed',
                error_message=error_msg
            )
            
            return 0, error_msg
            
        finally:
            # Cleanup temp file
            if temp_path and temp_path.exists():
                try:
                    temp_path.unlink()
                except Exception:
                    pass
    
    def check_for_price_updates(self) -> dict:
        """
        Check email for new price list attachments.
        
        Returns:
            Dict with processing results
        """
        if not self._is_configured():
            return {
                'success': False,
                'error': 'Email credentials not configured',
                'processed': 0,
                'items_added': 0
            }
        
        try:
            from imap_tools import MailBox, AND
        except ImportError:
            return {
                'success': False,
                'error': 'imap-tools not installed. Run: pip install imap-tools',
                'processed': 0,
                'items_added': 0
            }
        
        results = {
            'success': True,
            'processed': 0,
            'items_added': 0,
            'errors': [],
            'vendors': {}
        }
        
        try:
            with MailBox(self.imap_server).login(self.email_user, self.email_pass) as mailbox:
                # Fetch unread emails
                for msg in mailbox.fetch(AND(seen=False)):
                    # Check if from vendor
                    is_vendor, vendor_name = self._is_vendor_email(msg.from_)
                    
                    if not is_vendor:
                        continue
                    
                    # Track failures so the message is left unread and
                    # retried on the next pass instead of being consumed.
                    had_failure = False
                    
                    # Process attachments
                    for att in msg.attachments:
                        if self._is_price_document(att.filename):
                            log.info(f"Processing: {att.filename} from {vendor_name}")
                            
                            count, error = self._process_attachment(
                                att.payload,
                                att.filename,
                                vendor_name
                            )
                            
                            results['processed'] += 1
                            results['items_added'] += count
                            
                            if vendor_name not in results['vendors']:
                                results['vendors'][vendor_name] = {'files': 0, 'items': 0}
                            
                            results['vendors'][vendor_name]['files'] += 1
                            results['vendors'][vendor_name]['items'] += count
                            
                            if error:
                                had_failure = True
                                results['errors'].append(f"{att.filename}: {error}")
                    
                    # Mark as read only when nothing failed; attachments that
                    # errored (transient Gemini outage, bad parse) stay queued.
                    if not had_failure:
                        mailbox.seen(msg, True)
            
            return results
            
        except Exception as e:
            return {
                'success': False,
                'error': str(e),
                'processed': results['processed'],
                'items_added': results['items_added']
            }
    
    def get_status(self) -> dict:
        """Get email monitor status and recent activity."""
        recent_logs = self.db.get_recent_processing_logs(limit=10)
        email_logs = [log for log in recent_logs if log.get('source_type') == 'email']
        
        return {
            'configured': self._is_configured(),
            'email_user': self.email_user[:3] + '***' if self.email_user else None,
            'imap_server': self.imap_server,
            'watched_domains': self.vendor_domains,
            'recent_processing': email_logs[:5]
        }


def run_email_check() -> dict:
    """
    Entry point for scheduled email checks.
    
    Returns:
        Processing results dict
    """
    log.info(f"\n{'='*50}")
    log.info(f"📧 Email Monitor - {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    log.info(f"{'='*50}")
    
    monitor = EmailMonitor()
    results = monitor.check_for_price_updates()
    
    if results['success']:
        log.info("\n✓ Check complete!")
        log.info(f"  Documents processed: {results['processed']}")
        log.info(f"  Items added: {results['items_added']}")
        
        if results.get('vendors'):
            log.info("\n  By vendor:")
            for vendor, stats in results['vendors'].items():
                log.info(f"    - {vendor}: {stats['files']} files, {stats['items']} items")
        
        if results.get('errors'):
            log.warning("\n  ⚠️ Errors:")
            for error in results['errors']:
                log.warning(f"    - {error}")
    else:
        log.warning(f"\n✗ Check failed: {results.get('error')}")
    
    return results


import logging
logging.basicConfig(level=logging.INFO,
                    format='%(asctime)s %(name)s %(levelname)s %(message)s')

if __name__ == '__main__':
    # Run a single email check
    run_email_check()

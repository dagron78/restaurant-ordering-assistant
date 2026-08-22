"""
Email Monitor Worker for Restaurant Ordering Assistant.

Vendor intake path (#28): vendor recognition reads the `vendors` TABLE
(name, email_domain) - never a hardcoded domain list, never a name guessed
from a domain stem (#18). Unknown senders are QUARANTINED as metadata
(from / subject / attachment names); their attachments are never parsed,
and the mailbox message stays unread so promoting the vendor re-ingests it
through the normal path.
"""

import logging
import re
import sys
from datetime import datetime
from email.utils import parseaddr
from pathlib import Path
from typing import Optional, Tuple

sys.path.insert(0, str(Path(__file__).parent.parent))

from core.config import Config
from core.database import Database

log = logging.getLogger(__name__)

QUARANTINE_CAP = 200


class EmailMonitor:
    """Monitors the intake mailbox and routes messages safely."""

    def __init__(self, db: Database = None, ai=None):
        self.email_user = Config.EMAIL_USER
        self.email_pass = Config.EMAIL_PASS
        self.imap_server = Config.EMAIL_IMAP_SERVER

        self.db = db or Database()
        self.ai = ai

        self.price_keywords = Config.PRICE_LIST_KEYWORDS
        self.valid_extensions = Config.VALID_EXTENSIONS

    # ---- vendor recognition ------------------------------------------------

    def _vendor_for_address(self, from_address: str):
        """(is_vendor, vendors_row) using the vendors TABLE."""
        _, domain = parseaddr(from_address or "")
        return self.db.get_vendor_by_domain(domain)

    def _is_vendor_email(self, from_address: str) -> Tuple[bool, Optional[str]]:
        """Compat view returning (is_vendor, vendor_NAME from the row)."""
        is_vendor, row = self._vendor_for_address(from_address)
        return (is_vendor, row["name"]) if is_vendor else (False, None)

    def _is_price_document(self, filename: str) -> bool:
        filename_lower = (filename or "").lower()
        if not any(filename_lower.endswith(ext)
                   for ext in self.valid_extensions):
            return False
        has_keyword = any(kw in filename_lower for kw in self.price_keywords)
        common_patterns = ["attachment", "document", "list", "sheet"]
        return has_keyword or any(p in filename_lower
                                  for p in common_patterns)

    def _is_configured(self) -> bool:
        return bool(self.email_user and self.email_pass)

    # ---- attachment processing ---------------------------------------------

    def _process_attachment(self, attachment_data: bytes, filename: str,
                            vendor_name: str):
        """Persist, parse with Gemini, validate, store -> (count, error)."""
        temp_path = None
        try:
            ext = Path(filename).suffix.lower()

            Config.TEMP_PATH.mkdir(parents=True, exist_ok=True)
            safe_ext = re.sub(r"[^a-z0-9.]",
                              "", filename.rsplit(".", 1)[-1].lower())[:8]
            temp_path = Config.TEMP_PATH / (
                f"attachment_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
                f".{safe_ext or 'bin'}")
            with open(temp_path, "wb") as f:
                f.write(attachment_data)

            if ext in ['.jpg', '.jpeg', '.png', '.pdf']:
                parsed = self.ai.parse_document(temp_path,
                                                vendor_hint=vendor_name)
            else:
                return 0, f"Unsupported format: {ext}"

            if not parsed:
                return 0, "No items extracted from document"

            validated = self.ai.validate_extracted_prices(parsed)
            count = self.db.add_prices_batch(validated, source='email')

            self.db.log_processing(
                source_type='email', source_identifier=vendor_name,
                filename=filename,
                status='success' if count > 0 else 'partial',
                items_processed=count)
            return count, None

        except Exception as e:
            self.db.log_processing(
                source_type='email', source_identifier=vendor_name,
                filename=filename, status='failed',
                items_processed=0, error_message=str(e))
            return 0, str(e)
        finally:
            if temp_path and Path(temp_path).exists():
                try:
                    temp_path.unlink()
                except Exception:
                    pass

    # ---- message processing -------------------------------------------------

    def process_messages(self, messages) -> dict:
        """
        Process fetched messages. Test seam: check_for_price_updates feeds
        this from IMAP.

        Vendor recognition reads the vendors table; unknown senders are
        quarantined as METADATA (from / subject / attachment names) - their
        attachments are never parsed - and the message is left unread so a
        human-promoted vendor re-ingests it on the next pass.
        """
        results = {
            "success": True,
            "processed": 0,
            "items_added": 0,
            "quarantined": 0,
            "left_unseen": 0,
            "errors": [],
            "vendors": {},
            "seen_messages": [],
        }

        for msg in messages:
            is_vendor, vendor_row = self._vendor_for_address(msg.from_)
            vendor_name = vendor_row["name"] if is_vendor else None

            if not is_vendor:
                names = [a.filename for a in getattr(msg, "attachments", [])]
                recorded = self.db.add_quarantine(
                    msg.from_, getattr(msg, "subject", "") or "", names)
                if recorded:
                    self.db.log_processing(
                        source_type="email",
                        source_identifier=msg.from_,
                        filename=(getattr(msg, "subject", "") or "")[:120],
                        status="partial",
                        items_processed=0,
                        error_message=(
                            "QUARANTINE: unknown sender awaiting review "
                            f"({len(names)} attachment(s))"))
                    results["quarantined"] += 1
                else:
                    results["quarantine_duplicate"] = \
                        results.get("quarantine_duplicate", 0) + 1
                results["left_unseen"] += 1      # stays queued for promotion
                continue

            had_failure = False

            for att in msg.attachments:
                if not self._is_price_document(att.filename):
                    continue
                log.info("Processing: %s from %s", att.filename, vendor_name)

                count, error = self._process_attachment(
                    att.payload, att.filename, vendor_name)

                results["processed"] += 1
                results["items_added"] += count

                vstats = results["vendors"].setdefault(
                    vendor_name, {"files": 0, "items": 0})
                vstats["files"] += 1
                vstats["items"] += count

                if error:
                    had_failure = True
                    results["errors"].append(f"{att.filename}: {error}")

            # Mark as read only when nothing failed; failed attachments stay
            # queued and are retried on the next pass instead of being lost.
            if not had_failure:
                results["seen_messages"].append(msg)

        return results

    def check_for_price_updates(self) -> dict:
        if not self._is_configured():
            return {"success": False,
                    "error": "Email credentials not configured",
                    "processed": 0, "items_added": 0}
        try:
            from imap_tools import MailBox, AND
        except ImportError:
            return {"success": False,
                    "error": "imap-tools not installed. Run: pip install imap-tools",
                    "processed": 0, "items_added": 0}

        try:
            with MailBox(self.imap_server).login(
                    self.email_user, self.email_pass) as mailbox:
                msgs = list(mailbox.fetch(AND(seen=False)))
                partial = self.process_messages(msgs)

                results = {k: v for k, v in partial.items()
                           if k != "seen_messages"}

                seen_ids = {id(m) for m in partial.get("seen_messages", [])}
                for msg in msgs:
                    if id(msg) in seen_ids:
                        mailbox.seen(msg, True)
                return results
        except Exception as e:
            log.error("Email check failed: %s", e)
            return {"success": False, "error": str(e),
                    "processed": 0, "items_added": 0}

    def get_status(self) -> dict:
        recent_logs = self.db.get_recent_processing_logs(limit=10)
        email_logs = [lg for lg in recent_logs
                      if lg.get("source_type") == "email"]
        quarantine = self.db.list_quarantine(limit=5)
        return {
            "configured": self._is_configured(),
            "email_user":
                self.email_user[:3] + "***" if self.email_user else None,
            "imap_server": self.imap_server,
            "recent_processing": email_logs[:5],
            "quarantine_pending": len(quarantine),
        }


def run_email_check() -> dict:
    """Entry point for scheduled email checks (scheduler + CLI)."""
    log.info("=" * 50)
    log.info("Email Monitor run starting")
    monitor = EmailMonitor()
    results = monitor.check_for_price_updates()

    if results.get("success"):
        log.info(
            "Check complete: processed=%(processed)s items=%(items_added)s "
            "quarantined=%(quarantined)s errors=%(errors)s", results)
        if results.get("quarantine_duplicate"):
            log.info("Quarantine duplicates suppressed: %s",
                     results["quarantine_duplicate"])
    else:
        log.error("Check failed: %s", results.get("error"))
    return results


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(name)s %(levelname)s %(message)s")
    run_email_check()

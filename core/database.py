"""
Database operations for Restaurant Ordering Assistant.

Provides a clean interface for all SQLite database operations
including CRUD for items, prices, vendors, and orders.
"""

import json
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path
from typing import List, Dict, Optional
from contextlib import contextmanager

from .config import Config
import logging

log = logging.getLogger(__name__)

# The one definition of "most recent price". date_recorded decides which
# sheet is newest; created_at/id only break same-day ties (a backfilled
# old sheet gets a fresh created_at and must not win).
# Issue #9 happened because this ordering existed as two copies; keep it
# as one. Referenced via f-string in both ranking queries below.
LATEST_PRICE_RANK_ORDER = "ph.date_recorded DESC, ph.created_at DESC, ph.id DESC"

# Highest schema version implemented by scripts/migrations/. Bump it together
# with a new NNN_*.sql file there; PRAGMA user_version on real databases
# records how far each one has come.
SCHEMA_VERSION = 5
MIGRATIONS_DIR = Config.BASE_DIR / "scripts" / "migrations"


def pick_cheapest_alternative(prices: List[Dict], chosen_vendor: str) -> Optional[Dict]:
    """
    The single definition of "the option you forwent": the cheapest latest
    quote among vendors OTHER than the one picked. Never the max (F-22's
    basis) and never an average - beating a bad quote is not a saving.

    Ties on price break to the lowest vendor_id so the recorded
    alt_vendor_id is reproducible across runs and SQLite versions.

    Args:
        prices: Rows shaped like get_latest_prices output
            ({vendor, vendor_id, price, ...})
        chosen_vendor: Name of the vendor whose line this baseline serves

    Returns:
        {'vendor_id', 'vendor', 'price'} of the cheapest alternative,
        or None when no other vendor quotes the item.
    """
    candidates = [p for p in prices
                  if p.get("vendor") != chosen_vendor
                  and p.get("price") is not None]
    if not candidates:
        return None
    best = min(candidates, key=lambda p: (p["price"], p.get("vendor_id") or 0))
    return {"vendor_id": best.get("vendor_id"),
            "vendor": best["vendor"],
            "price": float(best["price"])}


class Database:
    """SQLite database manager with connection pooling and helper methods."""
    
    def __init__(self, db_path: Optional[Path] = None):
        """
        Initialize database connection.
        
        Args:
            db_path: Path to SQLite database file. Defaults to Config.DATABASE_PATH
        """
        self.db_path = db_path or Config.DATABASE_PATH
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        # Trusted-LAN single-tenant model: the settings store now holds the
        # API key and mailbox password. Tighten the file so only the owning
        # user reads it — parity with a 0600 .env, stated in docs rather
        # than implied encryption.
        self._harden_permissions()

    def _harden_permissions(self) -> None:
        """Best-effort owner-only permissions on the database and its WAL
        sidecars. Never fatal on filesystems that do not support it."""
        try:
            import os

            for suffix in ("", "-wal", "-shm"):
                target = Path(str(self.db_path) + suffix)
                if target.exists():
                    os.chmod(target, 0o600)
        except OSError:
            pass
    
    @contextmanager
    def get_connection(self):
        """
        Context manager for database connections.
        
        Yields:
            sqlite3.Connection with row_factory set to sqlite3.Row
        """
        conn = sqlite3.connect(str(self.db_path))
        conn.row_factory = sqlite3.Row
        # Enforce declared foreign keys (off by default in SQLite),
        # tolerate concurrent access from workers, and allow writers to wait.
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("PRAGMA journal_mode = WAL")
        conn.execute("PRAGMA busy_timeout = 5000")
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()
    
    def init_database(self) -> None:
        """Initialize database with schema from SQL file."""
        schema_path = Config.SCHEMA_PATH
        
        if not schema_path.exists():
            raise FileNotFoundError(f"Schema file not found: {schema_path}")
        
        with open(schema_path, 'r') as f:
            schema_sql = f.read()
        
        with self.get_connection() as conn:
            current_version = conn.execute(
                "PRAGMA user_version").fetchone()[0]

            if current_version >= SCHEMA_VERSION:
                return                                    # already current

            has_tables = conn.execute(
                "SELECT COUNT(*) AS n FROM sqlite_master"
                " WHERE type='table' AND name NOT LIKE 'sqlite_%'"
            ).fetchone()["n"]

            if has_tables == 0:
                # Truly fresh: full DDL is safe and sufficient
                conn.executescript(schema_sql)
                conn.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")
                return

        # Existing database below SCHEMA_VERSION: apply pending migrations.
        # NEVER run full DDL here — CREATE IF NOT EXISTS won't add columns
        # to existing tables, and ALTER TABLE from migrations handles that.
        self.migrate()

    def migrate(self) -> list:
        """
        Apply pending schema migrations, oldest first.
        
        Each migration is scripts/migrations/NNN_name.sql and bumps
        PRAGMA user_version to its number when applied, so this is a no-op
        on an up-to-date database. New databases never enter the loop:
        init_database() builds them at SCHEMA_VERSION directly.
        
        Returns:
            List of migration step numbers applied (empty when current)
        """
        applied = []
        with self.get_connection() as conn:
            version = conn.execute("PRAGMA user_version").fetchone()[0]
            while version < SCHEMA_VERSION:
                step = version + 1
                path = self._migration_path(step)
                conn.executescript(path.read_text())
                conn.execute(f"PRAGMA user_version = {step}")
                version = step
                applied.append(step)
        return applied

    @staticmethod
    def _migration_path(step: int) -> Path:
        matches = sorted(MIGRATIONS_DIR.glob(f"{step:03d}_*.sql"))
        if not matches:
            raise FileNotFoundError(
                f"No migration file for schema step {step} in {MIGRATIONS_DIR}")
        return matches[0]
    
    # ==========================================
    # ITEMS OPERATIONS
    # ==========================================
    
    def add_item(self, name: str, category: str = None, 
                 default_unit: str = None) -> int:
        """
        Add a new item to the master list.
        
        Args:
            name: Item name (must be unique)
            category: Item category (Produce, Meat, etc.)
            default_unit: Default unit of measure
            
        Returns:
            ID of the inserted item
        """
        with self.get_connection() as conn:
            cursor = conn.execute(
                """INSERT OR IGNORE INTO items (name, category, default_unit) 
                   VALUES (?, ?, ?)""",
                (name, category, default_unit)
            )
            
            if cursor.lastrowid == 0:
                # Item already exists, get its ID
                cursor = conn.execute(
                    "SELECT id FROM items WHERE name = ?", (name,)
                )
                return cursor.fetchone()['id']
            
            return cursor.lastrowid
    
    def update_item_unit(self, item_id: int, default_unit: str) -> None:
        """Set an item's default unit (order-sheet import fills blanks;
        it never overwrites a unit already known)."""
        with self.get_connection() as conn:
            conn.execute("UPDATE items SET default_unit = ? WHERE id = ?",
                         (default_unit, item_id))

    def get_item(self, item_id: int = None, name: str = None) -> Optional[Dict]:
        """Get item by ID or name."""
        with self.get_connection() as conn:
            if item_id:
                cursor = conn.execute(
                    "SELECT * FROM items WHERE id = ?", (item_id,)
                )
            elif name:
                cursor = conn.execute(
                    "SELECT * FROM items WHERE name = ?", (name,)
                )
            else:
                return None
            
            row = cursor.fetchone()
            return dict(row) if row else None
    
    def get_all_items(self, active_only: bool = True) -> List[Dict]:
        """Get all items, optionally filtering by active status."""
        with self.get_connection() as conn:
            if active_only:
                cursor = conn.execute(
                    "SELECT * FROM items WHERE is_active = 1 ORDER BY category, name"
                )
            else:
                cursor = conn.execute(
                    "SELECT * FROM items ORDER BY category, name"
                )
            return [dict(row) for row in cursor.fetchall()]

    # ==========================================
    # ORDER SHEET (Phase B · issue #53)
    # The kitchen's standing list as a first-class entity. Membership is
    # the manager's fact, granted by import or explicit edit — never a
    # side effect of items existing.
    # ==========================================

    def get_order_sheet(self) -> List[Dict]:
        """Sheet rows joined with their items, in the kitchen's own order.

        Position NULLs sort last (imports always assign positions, so
        NULLs only exist for hand-added rows)."""
        with self.get_connection() as conn:
            cursor = conn.execute(
                """SELECT os.item_id, os.par_level, os.sheet_position,
                          os.updated_at, i.name, i.default_unit, i.category
                   FROM order_sheet os
                   JOIN items i ON i.id = os.item_id
                   ORDER BY (os.sheet_position IS NULL),
                            os.sheet_position, i.name"""
            )
            return [dict(row) for row in cursor.fetchall()]

    def get_sheet_entry(self, item_id: int) -> Optional[Dict]:
        """One sheet row, or None when the item is not on the sheet."""
        with self.get_connection() as conn:
            row = conn.execute(
                "SELECT * FROM order_sheet WHERE item_id = ?", (item_id,)
            ).fetchone()
            return dict(row) if row else None

    def upsert_sheet_row(self, item_id: int, par_level: Optional[float],
                         sheet_position: Optional[int] = None) -> None:
        """Put an item on the sheet or update its row.

        par_level is the FULL value: a float, 0 (meaningful), or None
        (no par set). Callers must pass the intended value — there is no
        "leave unchanged" sentinel here, so a falsy check upstream can
        never collapse 0 into absent.
        """
        with self.get_connection() as conn:
            conn.execute(
                """INSERT INTO order_sheet (item_id, par_level, sheet_position)
                   VALUES (?, ?, ?)
                   ON CONFLICT(item_id) DO UPDATE SET
                       par_level = excluded.par_level,
                       sheet_position = COALESCE(excluded.sheet_position,
                                                 order_sheet.sheet_position),
                       updated_at = CURRENT_TIMESTAMP""",
                (item_id, par_level, sheet_position),
            )

    def update_sheet_par(self, item_id: int, par_level: Optional[float]) -> None:
        """Edit one par. Same contract as upsert_sheet_row: pass the FULL
        intended value — 0 survives, None means absent."""
        self.upsert_sheet_row(item_id, par_level, None)

    def remove_from_order_sheet(self, item_id: int) -> None:
        """Take an item off the sheet. Explicit manager action — a
        re-import never removes rows the file did not mention."""
        with self.get_connection() as conn:
            conn.execute("DELETE FROM order_sheet WHERE item_id = ?",
                         (item_id,))

    # ==========================================
    # SHEET MAPPINGS (Phase B · issue #53)
    # Named, admin-visible, deletable column mappings. An invisible
    # mapping that is subtly wrong becomes undebuggable; these are
    # configuration, not magic.
    # ==========================================

    def save_sheet_mapping(self, name: str, header_row: int,
                           columns: Dict[str, int],
                           header_texts: Dict[str, str]) -> None:
        """Upsert a mapping by name. columns are 0-based grid indices."""
        import json

        with self.get_connection() as conn:
            conn.execute(
                """INSERT INTO sheet_mappings
                       (name, header_row, columns_json, header_texts_json)
                   VALUES (?, ?, ?, ?)
                   ON CONFLICT(name) DO UPDATE SET
                       header_row = excluded.header_row,
                       columns_json = excluded.columns_json,
                       header_texts_json = excluded.header_texts_json""",
                (name, header_row, json.dumps(columns),
                 json.dumps(header_texts)),
            )

    def get_sheet_mapping(self, name: str) -> Optional[Dict]:
        import json

        with self.get_connection() as conn:
            row = conn.execute(
                "SELECT * FROM sheet_mappings WHERE name = ?", (name,)
            ).fetchone()
        if not row:
            return None
        return {"name": row["name"], "header_row": row["header_row"],
                "columns": json.loads(row["columns_json"]),
                "header_texts": json.loads(row["header_texts_json"])}

    def list_sheet_mappings(self) -> List[Dict]:
        import json

        with self.get_connection() as conn:
            rows = conn.execute(
                "SELECT name, header_row, columns_json, header_texts_json,"
                " created_at FROM sheet_mappings ORDER BY name"
            ).fetchall()
        return [{"name": r["name"], "header_row": r["header_row"],
                 "columns": json.loads(r["columns_json"]),
                 "header_texts": json.loads(r["header_texts_json"]),
                 "created_at": r["created_at"]} for r in rows]

    def delete_sheet_mapping(self, name: str) -> None:
        with self.get_connection() as conn:
            conn.execute("DELETE FROM sheet_mappings WHERE name = ?",
                         (name,))
    
    def get_vendor(self, vendor_id: int = None, name: str = None) -> Optional[Dict]:
        """Get vendor by ID or name."""
        with self.get_connection() as conn:
            if vendor_id:
                cursor = conn.execute(
                    "SELECT * FROM vendors WHERE id = ?", (vendor_id,)
                )
            elif name:
                cursor = conn.execute(
                    "SELECT * FROM vendors WHERE name = ?", (name,)
                )
            else:
                return None
            
            row = cursor.fetchone()
            return dict(row) if row else None
    
    def get_or_create_vendor(self, name: str, email_domain: str = None,
                             scrape_url: str = None) -> int:
        """Get vendor ID, creating if necessary.
        
        Raises:
            ValueError: If name is empty or whitespace
        """
        if not name or not name.strip():
            raise ValueError("Vendor name cannot be empty")
        
        with self.get_connection() as conn:
            return self._get_or_create_vendor(conn, name, email_domain, scrape_url)
    
    def _get_or_create_vendor(self, conn: sqlite3.Connection, name: str,
                              email_domain: str = None,
                              scrape_url: str = None) -> int:
        """Get-or-create a vendor using an existing connection.
        
        Raises:
            ValueError: If name is empty or whitespace
        """
        if not name or not name.strip():
            raise ValueError("Vendor name cannot be empty")
        
        cursor = conn.execute("SELECT id FROM vendors WHERE name = ?", (name.strip(),))
        row = cursor.fetchone()
        
        if row:
            return row['id']
        
        cursor = conn.execute(
            "INSERT INTO vendors (name, email_domain, scrape_url) VALUES (?, ?, ?)",
            (name.strip(), email_domain, scrape_url))
        return cursor.lastrowid
    
    def get_all_vendors(self) -> List[Dict]:
        """Get all vendors."""
        with self.get_connection() as conn:
            cursor = conn.execute("SELECT * FROM vendors ORDER BY name")
            return [dict(row) for row in cursor.fetchall()]
    
    def update_vendor_session(self, vendor_id: int, expires: datetime) -> None:
        """Update vendor session expiration."""
        with self.get_connection() as conn:
            conn.execute(
                "UPDATE vendors SET session_expires = ? WHERE id = ?",
                (expires.isoformat(), vendor_id)
            )

    def update_vendor_details(self, vendor_id: int, email_domain: str = None,
                              scrape_url: str = None,
                              scrape_enabled: bool = None) -> None:
        """
        Update operator-editable vendor fields (Phase A · issue #50).

        Only provided fields are written; None leaves a field untouched.
        """
        assignments, params = [], []
        if email_domain is not None:
            assignments.append("email_domain = ?")
            params.append(email_domain.strip() or None)
        if scrape_url is not None:
            assignments.append("scrape_url = ?")
            params.append(scrape_url.strip() or None)
        if scrape_enabled is not None:
            assignments.append("scrape_enabled = ?")
            params.append(1 if scrape_enabled else 0)
        if not assignments:
            return
        params.append(vendor_id)
        with self.get_connection() as conn:
            conn.execute(
                f"UPDATE vendors SET {', '.join(assignments)} WHERE id = ?",
                params)
    
    # ==========================================
    # PRICE HISTORY OPERATIONS
    # ==========================================
    
    def add_price(self, item_name: str, vendor_name: str, price: float,
                  unit: str, source: str = 'manual', 
                  confidence: float = 1.0, raw_text: str = None,
                  date_recorded: str = None) -> int:
        """
        Record a price point in history.
        
        Args:
            item_name: Name of the item
            vendor_name: Name of the vendor
            price: Price value
            unit: Unit of measure
            source: 'email', 'scrape', or 'manual'
            confidence: Confidence score (0-1)
            raw_text: Original text from document
            date_recorded: Optional date (YYYY-MM-DD) for backfilled
                history; defaults to today
            
        Returns:
            ID of the inserted price record
        """
        # Get or create item
        item = self.get_item(name=item_name)
        if item:
            item_id = item['id']
        else:
            item_id = self.add_item(item_name, default_unit=unit)
        
        # Get or create vendor
        vendor_id = self.get_or_create_vendor(vendor_name)
        
        with self.get_connection() as conn:
            return self._insert_price(
                conn, item_id, vendor_id, price, unit, source,
                confidence, raw_text, date_recorded
            )
    
    def _resolve_item_id(self, conn: sqlite3.Connection, item_name: str,
                         unit: str = None, create_missing: bool = True) -> int:
        """Resolve an item to its id using an existing connection.
        
        Raises:
            ValueError: If the item is unknown and create_missing is False
        """
        cursor = conn.execute("SELECT id FROM items WHERE name = ?", (item_name,))
        row = cursor.fetchone()
        if row:
            return row['id']
        
        if not create_missing:
            raise ValueError(f"unknown item {item_name!r}")
        
        cursor = conn.execute(
            "INSERT INTO items (name, default_unit) VALUES (?, ?)",
            (item_name, unit)
        )
        return cursor.lastrowid
    
    def _insert_price(self, conn: sqlite3.Connection, item_id: int,
                      vendor_id: int, price: float, unit: str,
                      source: str, confidence: float,
                      raw_text: str = None,
                      date_recorded: str = None) -> int:
        """Insert one price row using an existing connection."""
        cursor = conn.execute(
            """INSERT INTO price_history 
               (item_id, vendor_id, price, unit, source, confidence,
                raw_text, date_recorded)
               VALUES (?, ?, ?, ?, ?, ?, ?, COALESCE(?, CURRENT_DATE))""",
            (item_id, vendor_id, price, unit, source, confidence,
             raw_text, date_recorded)
        )
        return cursor.lastrowid
    
    def add_prices_batch(self, prices: List[Dict], source: str = 'manual',
                         create_missing_items: bool = False) -> int:
        """
        Add multiple prices in a single transaction.
        
        Uses ONE connection and commit for the whole batch. A row that
        fails validation is skipped without aborting the others; failures
        are logged rather than silently swallowed.
        
        By default rows naming an item that doesn't exist are SKIPPED -
        this is the AI-ingestion boundary, and auto-creating items from
        model output let a garbled PDF expand the catalog with
        hallucinated product names. Pass create_missing_items=True only
        for trusted sources (e.g. demo data).
        
        Args:
            prices: List of dicts with keys: item_name, vendor_name, price
                (optional: unit, confidence, date_recorded)
            source: Source type for all prices
            create_missing_items: Whether to create items that don't exist
            
        Returns:
            Number of prices added
        """
        added = 0
        
        with self.get_connection() as conn:
            for price_data in prices:
                item_name = price_data.get('item_name')
                
                try:
                    if not item_name or not str(item_name).strip():
                        raise ValueError("missing item_name")
                    
                    price = float(price_data['price'])
                    vendor_name = price_data.get('vendor_name',
                                                 price_data.get('vendor', 'Unknown'))
                    unit = price_data.get('unit') or 'Each'
                    confidence = float(price_data.get('confidence', 0.9))
                    date_recorded = price_data.get('date_recorded')
                    
                    conn.execute("SAVEPOINT row_sp")
                    try:
                        item_id = self._resolve_item_id(
                            conn, str(item_name).strip(), unit,
                            create_missing=create_missing_items
                        )
                        vendor_id = self._get_or_create_vendor(conn, vendor_name)
                        self._insert_price(
                            conn, item_id, vendor_id, price, unit, source,
                            confidence, date_recorded=date_recorded
                        )
                    except Exception:
                        conn.execute("ROLLBACK TO row_sp")
                        raise
                    finally:
                        conn.execute("RELEASE row_sp")
                    
                    added += 1
                    
                except Exception as e:
                    log.warning(f"Skipping price for {item_name!r}: {e}")
                    continue
        
        return added
    
    def get_latest_prices(self, item_name: str) -> List[Dict]:
        """
        Get most recent price from each vendor for an item.
        
        Args:
            item_name: Name of the item
            
        Returns:
            List of price records with vendor info (one per vendor)
        """
        with self.get_connection() as conn:
            # date_recorded has day precision, so several sheets can share the
            # newest date. Rank date_recorded FIRST - created_at/id only break
            # same-day ties, because a backfilled old sheet gets a fresh
            # created_at and must not win.
            cursor = conn.execute(f"""
                SELECT vendor, vendor_id, price, unit, date_recorded, source
                FROM (
                    SELECT v.name as vendor, v.id as vendor_id, ph.price, ph.unit,
                           ph.date_recorded, ph.source,
                           ROW_NUMBER() OVER (
                               PARTITION BY ph.vendor_id
                               ORDER BY {LATEST_PRICE_RANK_ORDER}
                           ) as rn
                    FROM price_history ph
                    JOIN items i ON ph.item_id = i.id
                    JOIN vendors v ON ph.vendor_id = v.id
                    WHERE i.name = ?
                )
                WHERE rn = 1
                ORDER BY price
            """, (item_name,))
            
            return [dict(row) for row in cursor.fetchall()]
    
    def get_item_market_average(self, item_name: str, days: int = None) -> Optional[float]:
        """
        Cross-vendor average for an item over the trailing window, including
        today. A market rate: right for "how does this price compare to the
        market", wrong for trend arrows (a vendor mix shift moves it).
        """
        return self._average(item_name=item_name, days=days)

    def get_vendor_trend_baseline(self, item_name: str, vendor_name: str,
                                  days: int = None) -> Optional[float]:
        """
        Single-vendor average over the trailing window, excluding today.
        The honest basis for a trend arrow on that vendor's current quote:
        tracks one vendor's movement, immune to vendor-mix shifts, and not
        damped by averaging today's price against itself.
        """
        if not vendor_name:
            return None
        return self._average(item_name=item_name, days=days,
                             vendor_name=vendor_name, exclude_today=True)

    def _average(self, item_name: str, days: int = None,
                 vendor_name: str = None, exclude_today: bool = False) -> Optional[float]:
        """Shared averaging machinery behind the two named entry points."""
        days = days or Config.TREND_DAYS
        cutoff_date = (datetime.now() - timedelta(days=days)).strftime('%Y-%m-%d')
        
        query = """
            SELECT AVG(ph.price) as avg_price
            FROM price_history ph
            JOIN items i ON ph.item_id = i.id
            WHERE i.name = ?
            AND ph.date_recorded >= ?
        """
        params: List = [item_name, cutoff_date]
        
        if vendor_name:
            query += " AND EXISTS (SELECT 1 FROM vendors v WHERE v.id = ph.vendor_id AND v.name = ?)"
            params.append(vendor_name)
        
        if exclude_today:
            query += " AND ph.date_recorded < ?"
            params.append(datetime.now().strftime('%Y-%m-%d'))
        
        with self.get_connection() as conn:
            row = conn.execute(query , params).fetchone()
            if row and row['avg_price'] is not None:
                return float(row['avg_price'])
            return None
    
    def get_price_history(self, item_name: str, days: int = 180) -> List[Dict]:
        """
        Get price history for trend charting.
        
        Args:
            item_name: Name of the item
            days: Number of days of history
            
        Returns:
            List of price records ordered by date
        """
        cutoff_date = (datetime.now() - timedelta(days=days)).strftime('%Y-%m-%d')
        
        with self.get_connection() as conn:
            cursor = conn.execute("""
                SELECT v.name as vendor, ph.price, ph.date_recorded, ph.source
                FROM price_history ph
                JOIN items i ON ph.item_id = i.id
                JOIN vendors v ON ph.vendor_id = v.id
                WHERE i.name = ?
                AND ph.date_recorded >= ?
                ORDER BY ph.date_recorded
            """, (item_name, cutoff_date))
            
            return [dict(row) for row in cursor.fetchall()]
    
    def get_all_items_with_prices(self) -> List[Dict]:
        """
        Get all active items with their latest prices and averages.
        
        Single query: latest-per-vendor via window function (matching
        get_latest_prices semantics), 30-day average per item, joined to
        the item list. Replaces the previous two-queries-per-item loop.
        
        Returns:
            List of items with prices and trend data
        """
        cutoff_date = (datetime.now() - timedelta(days=Config.TREND_DAYS)).strftime('%Y-%m-%d')
        
        with self.get_connection() as conn:
            cursor = conn.execute(f"""
                WITH latest AS (
                    SELECT ph.item_id, ph.vendor_id, ph.price, ph.unit,
                           ph.date_recorded, ph.source,
                           ROW_NUMBER() OVER (
                               PARTITION BY ph.item_id, ph.vendor_id
                               ORDER BY {LATEST_PRICE_RANK_ORDER}
                           ) as rn
                    FROM price_history ph
                ),
                avgs AS (
                    SELECT item_id, AVG(price) as avg_price
                    FROM price_history
                    WHERE date_recorded >= ?
                    GROUP BY item_id
                )
                SELECT i.id, i.name, i.category, i.default_unit,
                       v.name as vendor, r.price, r.unit,
                       r.date_recorded, r.source, a.avg_price
                FROM items i
                LEFT JOIN latest r ON r.item_id = i.id AND r.rn = 1
                LEFT JOIN vendors v ON v.id = r.vendor_id
                LEFT JOIN avgs a ON a.item_id = i.id
                WHERE i.is_active = 1
                ORDER BY i.category, i.name
            """, (cutoff_date,))
            
            rows = [dict(row) for row in cursor.fetchall()]
        
        items = {}
        for row in rows:
            item = items.setdefault(row['id'], {
                'id': row['id'],
                'name': row['name'],
                'category': row['category'],
                'default_unit': row['default_unit'],
                'prices': [],
                'avg_price': None,
            })
            if row['vendor'] is not None:
                item['prices'].append({
                    'vendor': row['vendor'],
                    'price': row['price'],
                    'unit': row['unit'],
                    'date_recorded': row['date_recorded'],
                    'source': row['source'],
                })
            if row['avg_price'] is not None:
                item['avg_price'] = row['avg_price']
        
        # Keep the documented shape: prices sorted cheapest-first
        for item in items.values():
            item['prices'].sort(key=lambda p: p['price'])
        
        return list(items.values())
    
    # ==========================================
    # PREFERENCES OPERATIONS
    # ==========================================
    
    def save_preferences(self, preferences: List[Dict],
                         source_hash: str = None) -> int:
        """
        Replace all stored preferences (WRITE path only - reads never call
        this). Each rule may carry 'condition' as a dict (structured
        predicate -> condition_json) or a string (legacy prose ->
        condition_text). source_hash is stamped on every row and in
        prefs_meta so load_preferences can skip Gemini until the file
        changes.
        """
        import json as _json
        count = 0
        with self.get_connection() as conn:
            conn.execute("DELETE FROM preferences")
            for pref in preferences:
                cond = pref.get('condition')
                if isinstance(cond, dict):
                    cond_text = _json.dumps(cond)
                    cond_json = _json.dumps(cond)
                elif cond is None and pref.get('condition_json'):
                    cond_json = (pref['condition_json']
                                 if isinstance(pref['condition_json'], str)
                                 else _json.dumps(pref['condition_json']))
                    cond_text = cond_json
                else:
                    cond_text = str(cond or '')
                    cond_json = None
                conn.execute("""
                    INSERT INTO preferences
                    (rule_type, item_pattern, condition_text, action_text,
                     priority, is_active, raw_note, condition_json, source_hash)
                    VALUES (?, ?, ?, ?, COALESCE(?, 0), 1, ?, ?, ?)
                """, (
                    pref.get('rule_type', 'vendor_preference'),
                    pref.get('item_pattern', '*'),
                    cond_text,
                    pref.get('action', pref.get('action_text', '')),
                    pref.get('priority'),
                    pref.get('raw_note', ''),
                    cond_json,
                    source_hash,
                ))
                count += 1
            if source_hash is not None:
                conn.execute(
                    "INSERT INTO prefs_meta (key, value) VALUES ('source_hash', ?)"
                    " ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                    (source_hash,))
        return count

    def get_vendor_by_domain(self, sender_domain: str):
        """Resolve an email sender's DOMAIN to a vendors row.
        Matches exact or subdomain. Returns (True, row) / (False, None)."""
        d = (sender_domain or "").strip().lower()
        if "@" in d:
            d = d.rsplit("@", 1)[1]
        if not d:
            return False, None
        with self.get_connection() as conn:
            row = conn.execute(
                "SELECT * FROM vendors "
                "WHERE lower(email_domain) = ? "
                "   OR ? LIKE '%.' || lower(email_domain) LIMIT 1",
                (d, d)).fetchone()
        return (True, dict(row)) if row else (False, None)

    def add_quarantine(self, from_address: str, subject: str,
                       attachment_names: List[str]) -> bool:
        """Record an unknown-sender email as METADATA only.
        Attacker-writable display data: truncated + stripped of path/markup.
        Deduped on (from_address, subject); capped at 200 pending rows."""
        def clean(value, limit):
            text = str(value or "").replace("\\", "/")
            text = text.rsplit("/", 1)[-1]
            text = text.replace("..", ".").replace("<", "&lt;").replace(">", "&gt;")
            return text[:limit]

        with self.get_connection() as conn:
            exists = conn.execute(
                "SELECT 1 FROM quarantine WHERE from_address = ? AND subject = ?",
                (clean(from_address, 254), clean(subject, 200))).fetchone()
            if exists:
                return False
            cap = conn.execute(
                "SELECT COUNT(*) AS n FROM quarantine").fetchone()["n"]
            if cap >= 200:
                return False
            names = json.dumps(
                [clean(n, 80) for n in (attachment_names or [])][:20])
            conn.execute(
                "INSERT INTO quarantine"
                " (from_address, subject, attachment_names) VALUES (?, ?, ?)",
                (clean(from_address, 254), clean(subject, 200), names))
        return True

    def list_quarantine(self, limit: int = 50) -> List[Dict]:
        with self.get_connection() as conn:
            rows = conn.execute(
                "SELECT * FROM quarantine ORDER BY id DESC LIMIT ?",
                (limit,)).fetchall()
        out = []
        for r in rows:
            d = dict(r)
            try:
                d["attachment_names"] = ", ".join(
                    json.loads(d.get("attachment_names") or "[]"))
            except ValueError:
                d["attachment_names"] = ""
            out.append(d)
        return out

    def resolve_quarantine(self, quarantine_id: int) -> bool:
        with self.get_connection() as conn:
            cur = conn.execute("DELETE FROM quarantine WHERE id = ?",
                               (quarantine_id,))
        return cur.rowcount > 0

    def get_pref_meta(self, key: str) -> Optional[str]:
        with self.get_connection() as conn:
            row = conn.execute(
                "SELECT value FROM prefs_meta WHERE key = ?", (key,)).fetchone()
            return row["value"] if row else None

    def set_pref_meta(self, key: str, value: str) -> None:
        with self.get_connection() as conn:
            conn.execute(
                "INSERT INTO prefs_meta (key, value) VALUES (?, ?)"
                " ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                (key, str(value)))


    def get_preferences(self, active_only: bool = True) -> List[Dict]:
        """Get all preferences."""
        with self.get_connection() as conn:
            if active_only:
                cursor = conn.execute(
                    "SELECT * FROM preferences WHERE is_active = 1 ORDER BY priority DESC"
                )
            else:
                cursor = conn.execute(
                    "SELECT * FROM preferences ORDER BY priority DESC"
                )
            return [dict(row) for row in cursor.fetchall()]
    
    # ==========================================
    # ORDERS OPERATIONS
    # ==========================================
    
    def _get_cheapest_alternative(self, conn, item_id: int,
                                  exclude_vendor_id: int) -> Optional[Dict]:
        """Resolve the baseline for one line using an existing connection.

        Cheapest latest quote among all OTHER vendors; ties break to the
        lowest vendor_id (mirrors pick_cheapest_alternative exactly).
        Returns None when no other vendor quotes the item.
        """
        cursor = conn.execute(f"""
            SELECT v.id AS vendor_id, v.name AS vendor, ranked.price AS price
            FROM (
                SELECT ph.vendor_id, ph.price,
                       ROW_NUMBER() OVER (
                           PARTITION BY ph.vendor_id
                           ORDER BY {LATEST_PRICE_RANK_ORDER}
                       ) as rn
                FROM price_history ph
                WHERE ph.item_id = ?
            ) ranked
            JOIN vendors v ON v.id = ranked.vendor_id
            WHERE ranked.rn = 1 AND ranked.vendor_id != ?
            ORDER BY ranked.price ASC, v.id ASC
            LIMIT 1
        """, (item_id, exclude_vendor_id))
        row = cursor.fetchone()
        if row is None:
            return None
        return {"vendor_id": row["vendor_id"],
                "vendor": row["vendor"],
                "price": float(row["price"])}

    def get_cheapest_alternative(self, item_name: str,
                                 exclude_vendor) -> Optional[Dict]:
        """
        Public form of the baseline lookup: the cheapest latest quote among
        vendors other than `exclude_vendor` (name or id). Thin wrapper over
        the conn-taking private used inside create_order, so previews and
        saves share one definition.

        Returns:
            {'vendor_id', 'vendor', 'price'} or None
        """
        if isinstance(exclude_vendor, int):
            vendor = self.get_vendor(vendor_id=exclude_vendor)
        else:
            vendor = self.get_vendor(name=exclude_vendor)
        item = self.get_item(name=item_name)
        if not vendor or not item:
            return None
        with self.get_connection() as conn:
            return self._get_cheapest_alternative(conn, item["id"], vendor["id"])

    def create_order(self, items: List[Dict], notes: str = None,
                     status: str = 'draft') -> Dict:
        """
        Create a new order with items and honest savings tracking.

        Each line's baseline is resolved INTERNALLY at save time: the
        cheapest latest quote among all OTHER vendors for that item, frozen
        thereafter. Lines where no other vendor quotes are excluded from
        savings and counted - never folded in at zero. Negative savings (a
        dearer vendor chosen anyway) are preserved unclamped.

        Args:
            items: Lines shaped {item_id, vendor_id, quantity, unit_price[, unit]}
                (avg_price/max_price still accepted and stored as context)
            notes: Order notes
            status: Initial status ('draft', 'submitted', 'completed',
                'cancelled'). Savings dashboards only read 'completed'.

        Returns:
            {'order_id': int, 'lines_excluded': int, 'lines_total': int}
        """
        with self.get_connection() as conn:
            total = 0
            sv_avg = 0
            sv_max = 0
            sv_alt = 0
            excluded = 0
            prepared = []
            
            for item in items:
                qty = item.get('quantity', 0)
                unit_price = item.get('unit_price', 0)
                avg_price = item.get('avg_price')
                max_price = item.get('max_price')
                
                total += qty * unit_price
                
                # Legacy context columns (labelled pre-v1 semantics upstream)
                if avg_price and avg_price > unit_price:
                    sv_avg += qty * (avg_price - unit_price)
                if max_price and max_price > unit_price:
                    sv_max += qty * (max_price - unit_price)
                
                # The headline baseline: cheapest alternative, frozen now.
                alt = None
                if item.get('item_id') and item.get('vendor_id'):
                    alt = self._get_cheapest_alternative(
                        conn, item['item_id'], item['vendor_id'])
                
                if alt is None:
                    excluded += 1
                    line_basis = 'no_alternative'
                    line_vs_alt = 0
                    alt_vendor_id = None
                    alt_price = None
                else:
                    line_basis = 'vs_alt'
                    line_vs_alt = qty * (alt['price'] - unit_price)
                    sv_alt += line_vs_alt
                    alt_vendor_id = alt['vendor_id']
                    alt_price = alt['price']
                
                prepared.append((item, alt_vendor_id, alt_price,
                                 line_vs_alt, line_basis))
            
            # Any real baseline makes the aggregate a vs-alt number; an order
            # whose every line lacked one is honestly labelled otherwise.
            order_basis = ('unknown_legacy' if prepared
                           and all(p[4] != 'vs_alt' for p in prepared) else 'vs_alt')
            
            cursor = conn.execute(
                """INSERT INTO orders
                   (status, total_amount, total_savings, savings_vs_avg,
                    savings_vs_max, savings_vs_alt, lines_without_alt,
                    savings_basis, notes)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (status, total, sv_max, sv_avg, sv_max,
                 sv_alt, excluded, order_basis, notes)
            )
            order_id = cursor.lastrowid
            
            for item, alt_vendor_id, alt_price, line_vs_alt, line_basis in prepared:
                qty = item.get('quantity', 0)
                unit_price = item.get('unit_price', 0)
                avg_price = item.get('avg_price')
                max_price = item.get('max_price')
                total_price = qty * unit_price
                line_sv_avg = qty * (avg_price - unit_price) \
                    if avg_price and avg_price > unit_price else 0
                line_sv_max = qty * (max_price - unit_price) \
                    if max_price and max_price > unit_price else 0
                
                conn.execute("""
                    INSERT INTO order_items
                    (order_id, item_id, vendor_id, quantity, unit, unit_price,
                     total_price, avg_price, max_price, savings_vs_avg,
                     savings_vs_max, savings_vs_alt, alt_vendor_id, alt_price,
                     savings_basis)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    order_id, item['item_id'], item['vendor_id'], qty,
                    item.get('unit', 'Each'), unit_price, total_price,
                    avg_price, max_price, line_sv_avg, line_sv_max,
                    line_vs_alt, alt_vendor_id, alt_price, line_basis,
                ))
            
            return {
                'order_id': order_id,
                'lines_excluded': excluded,
                'lines_total': len(items),
            }
    
    def update_order_status(self, order_id: int, status: str) -> bool:
        """
        Transition an order to a new status.
        
        Args:
            order_id: Order ID
            status: 'draft', 'submitted', 'completed', or 'cancelled'.
                Savings dashboards only read 'completed' orders.
            
        Returns:
            True if an order was updated, False if the ID was not found
            
        Raises:
            ValueError: If status is not one of the allowed values
        """
        allowed = ('draft', 'submitted', 'completed', 'cancelled')
        if status not in allowed:
            raise ValueError(f"Invalid status {status!r}; must be one of {allowed}")
        
        with self.get_connection() as conn:
            cursor = conn.execute(
                "UPDATE orders SET status = ? WHERE id = ?", (status, order_id)
            )
            return cursor.rowcount > 0
    
    def get_order(self, order_id: int) -> Optional[Dict]:
        """Get order with items and savings details."""
        with self.get_connection() as conn:
            cursor = conn.execute(
                "SELECT * FROM orders WHERE id = ?", (order_id,)
            )
            order = cursor.fetchone()
            
            if not order:
                return None
            
            order_dict = dict(order)
            
            cursor = conn.execute("""
                SELECT oi.*, i.name as item_name, v.name as vendor_name
                FROM order_items oi
                JOIN items i ON oi.item_id = i.id
                JOIN vendors v ON oi.vendor_id = v.id
                WHERE oi.order_id = ?
            """, (order_id,))
            
            order_dict['items'] = [dict(row) for row in cursor.fetchall()]
            
            return order_dict
    
    # get_max_price_for_item was retired with F-22's semantics: the max is
    # no longer a savings basis anywhere, and the cheapest-alternative
    # resolution lives in _get_cheapest_alternative.

    def get_savings_summary(self, period_type: str = 'weekly',
                           limit: int = 12) -> List[Dict]:
        """
        Get aggregated savings over time periods.
        
        Args:
            period_type: 'daily', 'weekly', or 'monthly'
            limit: Number of periods to return
            
        Returns:
            List of savings summaries by period
        """
        with self.get_connection() as conn:
            if period_type == 'daily':
                group_by = "date(order_date)"
            elif period_type == 'monthly':
                group_by = "strftime('%Y-%m', order_date)"
            else:  # weekly
                group_by = "strftime('%Y-%W', order_date)"
            
            cursor = conn.execute(f"""
                SELECT
                    {group_by} as period,
                    COUNT(*) as total_orders,
                    SUM(total_amount) as total_spent,
                    SUM(savings_vs_avg) as total_savings_vs_avg,
                    SUM(savings_vs_max) as total_savings_vs_max,
                    COALESCE(SUM(savings_vs_alt), 0) as total_savings_vs_alt,
                    COALESCE(SUM(lines_without_alt), 0) as lines_without_alt,
                    MIN(date(order_date)) as period_start,
                    MAX(date(order_date)) as period_end
                FROM orders
                WHERE status = 'completed'
                GROUP BY {group_by}
                ORDER BY period DESC
                LIMIT ?
            """, (limit,))
            
            return [dict(row) for row in cursor.fetchall()]
    
    def get_total_savings(self, start_date: str = None,
                         end_date: str = None) -> Dict:
        """
        Get total savings across all orders in a date range.
        
        Args:
            start_date: Start date (YYYY-MM-DD format)
            end_date: End date (YYYY-MM-DD format)
            
        Returns:
            Dict with total savings metrics
        """
        with self.get_connection() as conn:
            query = """
                SELECT
                    COUNT(*) as total_orders,
                    COALESCE(SUM(total_amount), 0) as total_spent,
                    COALESCE(SUM(savings_vs_avg), 0) as total_savings_vs_avg,
                    COALESCE(SUM(savings_vs_max), 0) as total_savings_vs_max,
                    COALESCE(SUM(savings_vs_alt), 0) as total_savings_vs_alt,
                    COALESCE(SUM(lines_without_alt), 0) as lines_without_alt,
                    COALESCE(AVG(savings_vs_alt), 0) as avg_savings_per_order
                FROM orders
                WHERE status = 'completed'
            """
            params = []
            
            if start_date:
                query += " AND date(order_date) >= ?"
                params.append(start_date)
            
            if end_date:
                query += " AND date(order_date) <= ?"
                params.append(end_date)
            
            cursor = conn.execute(query, params)
            row = cursor.fetchone()
            
            if row:
                result = dict(row)
                # Headline percentage on the honest basis (#17): versus the
                # cheapest alternative actually available at order time.
                if result['total_spent'] > 0:
                    potential = result['total_spent'] + result['total_savings_vs_alt']
                    result['savings_percentage'] = (
                        (result['total_savings_vs_alt'] / potential) * 100
                        if potential > 0 else 0)
                else:
                    result['savings_percentage'] = 0
                return result
            
            return {
                'total_orders': 0,
                'total_spent': 0,
                'total_savings_vs_avg': 0,
                'total_savings_vs_max': 0,
                'total_savings_vs_alt': 0,
                'lines_without_alt': 0,
                'avg_savings_per_order': 0,
                'savings_percentage': 0
            }
    
    def get_item_savings_breakdown(self, order_id: int = None) -> List[Dict]:
        """
        Get savings breakdown by item for an order or all orders.
        
        Args:
            order_id: Specific order ID (optional, None for all)
            
        Returns:
            List of items with savings details
        """
        with self.get_connection() as conn:
            query = """
                SELECT
                    i.name as item_name,
                    i.category,
                    SUM(oi.quantity) as total_quantity,
                    SUM(oi.total_price) as total_spent,
                    SUM(oi.savings_vs_avg) as savings_vs_avg,
                    SUM(oi.savings_vs_max) as savings_vs_max,
                    AVG(oi.unit_price) as avg_unit_price,
                    (
                        SELECT v2.name
                        FROM order_items oi2
                        JOIN vendors v2 ON v2.id = oi2.vendor_id
                        JOIN orders o2 ON o2.id = oi2.order_id
                        WHERE oi2.item_id = i.id AND o2.status = 'completed'
            """
            params = []
            
            if order_id:
                query += " AND oi2.order_id = ?"
                params.append(order_id)
            
            query += """
                        GROUP BY v2.id
                        ORDER BY SUM(oi2.total_price) DESC
                        LIMIT 1
                    ) as most_used_vendor
                FROM order_items oi
                JOIN items i ON oi.item_id = i.id
                JOIN orders o ON oi.order_id = o.id
                WHERE o.status = 'completed'
            """
            
            if order_id:
                query += " AND oi.order_id = ?"
                params.append(order_id)
            
            query += """
                GROUP BY i.id
                ORDER BY savings_vs_max DESC
            """
            
            cursor = conn.execute(query, params)
            return [dict(row) for row in cursor.fetchall()]
    
    # ==========================================
    # PROCESSING LOG OPERATIONS
    # ==========================================
    
    def log_processing(self, source_type: str, source_identifier: str,
                       filename: str, status: str, items_processed: int = 0,
                       error_message: str = None) -> int:
        """Log document processing result."""
        with self.get_connection() as conn:
            cursor = conn.execute("""
                INSERT INTO processing_log 
                (source_type, source_identifier, filename, status, items_processed, error_message)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (source_type, source_identifier, filename, status, 
                  items_processed, error_message))
            return cursor.lastrowid
    
    def get_recent_processing_logs(self, limit: int = 50) -> List[Dict]:
        """Get recent processing logs."""
        with self.get_connection() as conn:
            cursor = conn.execute("""
                SELECT * FROM processing_log 
                ORDER BY processed_at DESC 
                LIMIT ?
            """, (limit,))
            return [dict(row) for row in cursor.fetchall()]

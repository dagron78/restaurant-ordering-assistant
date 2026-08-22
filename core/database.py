"""
Database operations for Restaurant Ordering Assistant.

Provides a clean interface for all SQLite database operations
including CRUD for items, prices, vendors, and orders.
"""

import sqlite3
from datetime import datetime, timedelta
from pathlib import Path
from typing import List, Dict, Optional
from contextlib import contextmanager

from .config import Config


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
            conn.executescript(schema_sql)
    
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
    
    def update_item(self, item_id: int, **kwargs) -> bool:
        """Update item fields."""
        allowed_fields = {'name', 'category', 'default_unit', 'is_active'}
        updates = {k: v for k, v in kwargs.items() if k in allowed_fields}
        
        if not updates:
            return False
        
        set_clause = ', '.join(f"{k} = ?" for k in updates.keys())
        values = list(updates.values()) + [item_id]
        
        with self.get_connection() as conn:
            conn.execute(
                f"UPDATE items SET {set_clause} WHERE id = ?",
                values
            )
            return True
    
    def get_categories(self) -> List[str]:
        """Get list of unique categories."""
        with self.get_connection() as conn:
            cursor = conn.execute(
                "SELECT DISTINCT category FROM items WHERE category IS NOT NULL ORDER BY category"
            )
            return [row['category'] for row in cursor.fetchall()]
    
    # ==========================================
    # VENDORS OPERATIONS
    # ==========================================
    
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
    
    def get_or_create_vendor(self, name: str) -> int:
        """Get vendor ID, creating if necessary."""
        with self.get_connection() as conn:
            cursor = conn.execute(
                "SELECT id FROM vendors WHERE name = ?", (name,)
            )
            row = cursor.fetchone()
            
            if row:
                return row['id']
            
            cursor = conn.execute(
                "INSERT INTO vendors (name) VALUES (?)", (name,)
            )
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
            cursor = conn.execute(
                """INSERT INTO price_history 
                   (item_id, vendor_id, price, unit, source, confidence,
                    raw_text, date_recorded)
                   VALUES (?, ?, ?, ?, ?, ?, ?, COALESCE(?, CURRENT_DATE))""",
                (item_id, vendor_id, price, unit, source, confidence,
                 raw_text, date_recorded)
            )
            return cursor.lastrowid
    
    def add_prices_batch(self, prices: List[Dict], source: str = 'manual') -> int:
        """
        Add multiple prices in a single transaction.
        
        Args:
            prices: List of dicts with keys: item_name, vendor_name, price, unit
            source: Source type for all prices
            
        Returns:
            Number of prices added
        """
        count = 0
        for price_data in prices:
            try:
                self.add_price(
                    item_name=price_data['item_name'],
                    vendor_name=price_data.get('vendor_name', price_data.get('vendor', 'Unknown')),
                    price=float(price_data['price']),
                    unit=price_data.get('unit', 'Each'),
                    source=source,
                    confidence=price_data.get('confidence', 0.9)
                )
                count += 1
            except Exception as e:
                print(f"Error adding price for {price_data.get('item_name')}: {e}")
        
        return count
    
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
            cursor = conn.execute("""
                SELECT vendor, price, unit, date_recorded, source
                FROM (
                    SELECT v.name as vendor, ph.price, ph.unit,
                           ph.date_recorded, ph.source,
                           ROW_NUMBER() OVER (
                               PARTITION BY ph.vendor_id
                               ORDER BY ph.date_recorded DESC, ph.created_at DESC,
                                        ph.id DESC
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
    
    def get_average_price(self, item_name: str, days: int = None) -> Optional[float]:
        """
        Calculate rolling average price for an item.
        
        Args:
            item_name: Name of the item
            days: Number of days to include (default: Config.TREND_DAYS)
            
        Returns:
            Average price or None if no data
        """
        days = days or Config.TREND_DAYS
        cutoff_date = (datetime.now() - timedelta(days=days)).strftime('%Y-%m-%d')
        
        with self.get_connection() as conn:
            cursor = conn.execute("""
                SELECT AVG(ph.price) as avg_price
                FROM price_history ph
                JOIN items i ON ph.item_id = i.id
                WHERE i.name = ?
                AND ph.date_recorded >= ?
            """, (item_name, cutoff_date))
            
            row = cursor.fetchone()
            return row['avg_price'] if row and row['avg_price'] else None
    
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
        
        Returns:
            List of items with prices and trend data
        """
        items = self.get_all_items(active_only=True)
        
        for item in items:
            item['prices'] = self.get_latest_prices(item['name'])
            item['avg_price'] = self.get_average_price(item['name'])
        
        return items
    
    # ==========================================
    # PREFERENCES OPERATIONS
    # ==========================================
    
    def save_preferences(self, preferences: List[Dict]) -> int:
        """
        Save parsed preferences to database.
        
        Args:
            preferences: List of preference dicts from AI parser
            
        Returns:
            Number of preferences saved
        """
        with self.get_connection() as conn:
            # Clear existing preferences
            conn.execute("DELETE FROM preferences")
            
            count = 0
            for pref in preferences:
                conn.execute("""
                    INSERT INTO preferences 
                    (rule_type, item_pattern, condition_text, action_text, raw_note)
                    VALUES (?, ?, ?, ?, ?)
                """, (
                    pref.get('rule_type', 'vendor_preference'),
                    pref.get('item_pattern', '*'),
                    pref.get('condition', pref.get('condition_text', '')),
                    pref.get('action', pref.get('action_text', '')),
                    pref.get('raw_note', '')
                ))
                count += 1
            
            return count
    
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
    
    def create_order(self, items: List[Dict], notes: str = None,
                     status: str = 'draft') -> int:
        """
        Create a new order with items and savings tracking.
        
        Args:
            items: List of order items with savings info:
                - item_id, vendor_id, quantity, unit_price
                - avg_price, max_price (for savings calculation)
            notes: Order notes
            status: Initial status ('draft', 'submitted', 'completed',
                'cancelled'). Savings dashboards only read 'completed'.
            
        Returns:
            Order ID
        """
        with self.get_connection() as conn:
            # Calculate totals and savings
            total = 0
            total_savings_vs_avg = 0
            total_savings_vs_max = 0
            
            for item in items:
                qty = item.get('quantity', 0)
                unit_price = item.get('unit_price', 0)
                avg_price = item.get('avg_price', unit_price)
                max_price = item.get('max_price', unit_price)
                
                item_total = qty * unit_price
                total += item_total
                
                # Calculate savings vs average price
                if avg_price and avg_price > unit_price:
                    total_savings_vs_avg += qty * (avg_price - unit_price)
                
                # Calculate savings vs max vendor price
                if max_price and max_price > unit_price:
                    total_savings_vs_max += qty * (max_price - unit_price)
            
            cursor = conn.execute(
                """INSERT INTO orders
                   (status, total_amount, total_savings, savings_vs_avg, savings_vs_max, notes)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (status, total, total_savings_vs_max,
                 total_savings_vs_avg, total_savings_vs_max, notes)
            )
            order_id = cursor.lastrowid
            
            # Add order items with savings details
            for item in items:
                qty = item.get('quantity', 0)
                unit_price = item.get('unit_price', 0)
                avg_price = item.get('avg_price', unit_price)
                max_price = item.get('max_price', unit_price)
                
                total_price = qty * unit_price
                savings_vs_avg = qty * (avg_price - unit_price) if avg_price and avg_price > unit_price else 0
                savings_vs_max = qty * (max_price - unit_price) if max_price and max_price > unit_price else 0
                
                conn.execute("""
                    INSERT INTO order_items
                    (order_id, item_id, vendor_id, quantity, unit, unit_price, total_price,
                     avg_price, max_price, savings_vs_avg, savings_vs_max)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    order_id,
                    item['item_id'],
                    item['vendor_id'],
                    qty,
                    item.get('unit', 'Each'),
                    unit_price,
                    total_price,
                    avg_price,
                    max_price,
                    savings_vs_avg,
                    savings_vs_max
                ))
            
            return order_id
    
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
    
    def get_max_price_for_item(self, item_name: str) -> Optional[float]:
        """
        Get the maximum price from any vendor for an item (current prices).
        
        Args:
            item_name: Name of the item
            
        Returns:
            Maximum price or None if no data
        """
        prices = self.get_latest_prices(item_name)
        if not prices:
            return None
        return max(p.get('price', 0) for p in prices)
    
    def get_orders_with_savings(self,
                                 start_date: str = None,
                                 end_date: str = None,
                                 status: str = 'completed') -> List[Dict]:
        """
        Get orders with savings information for a date range.
        
        Args:
            start_date: Start date (YYYY-MM-DD format)
            end_date: End date (YYYY-MM-DD format)
            status: Order status filter
            
        Returns:
            List of orders with savings data
        """
        with self.get_connection() as conn:
            query = """
                SELECT id, order_date, status, total_amount,
                       total_savings, savings_vs_avg, savings_vs_max,
                       notes, created_at
                FROM orders
                WHERE 1=1
            """
            params = []
            
            if status:
                query += " AND status = ?"
                params.append(status)
            
            if start_date:
                query += " AND date(order_date) >= ?"
                params.append(start_date)
            
            if end_date:
                query += " AND date(order_date) <= ?"
                params.append(end_date)
            
            query += " ORDER BY order_date DESC"
            
            cursor = conn.execute(query, params)
            return [dict(row) for row in cursor.fetchall()]
    
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
                    COALESCE(AVG(savings_vs_max), 0) as avg_savings_per_order
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
                # Calculate savings percentage
                if result['total_spent'] > 0:
                    potential_spend = result['total_spent'] + result['total_savings_vs_max']
                    result['savings_percentage'] = (result['total_savings_vs_max'] / potential_spend) * 100
                else:
                    result['savings_percentage'] = 0
                return result
            
            return {
                'total_orders': 0,
                'total_spent': 0,
                'total_savings_vs_avg': 0,
                'total_savings_vs_max': 0,
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
                    v.name as most_used_vendor
                FROM order_items oi
                JOIN items i ON oi.item_id = i.id
                JOIN vendors v ON oi.vendor_id = v.id
                JOIN orders o ON oi.order_id = o.id
                WHERE o.status = 'completed'
            """
            params = []
            
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

-- Restaurant Ordering Assistant Database Schema
-- SQLite Database Initialization Script

-- ===========================================
-- ITEMS TABLE
-- Master list of all products tracked
-- ===========================================
CREATE TABLE IF NOT EXISTS items (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT UNIQUE NOT NULL,
    category TEXT,
    default_unit TEXT,
    is_active BOOLEAN DEFAULT 1,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
);

-- ===========================================
-- VENDORS TABLE
-- Supplier information
-- ===========================================
CREATE TABLE IF NOT EXISTS vendors (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT UNIQUE NOT NULL,
    email_domain TEXT,
    scrape_url TEXT,
    scrape_enabled BOOLEAN DEFAULT 0,
    session_expires DATETIME,
    contact_email TEXT,
    contact_phone TEXT,
    notes TEXT,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
);

-- ===========================================
-- PRICE HISTORY TABLE
-- Historical price tracking for trend analysis
-- ===========================================
CREATE TABLE IF NOT EXISTS price_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    item_id INTEGER NOT NULL,
    vendor_id INTEGER NOT NULL,
    price REAL NOT NULL CHECK(price > 0),
    unit TEXT,
    date_recorded DATE DEFAULT CURRENT_DATE,
    source TEXT CHECK(source IN ('email', 'scrape', 'manual')) DEFAULT 'manual',
    confidence REAL DEFAULT 1.0,
    raw_text TEXT,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (item_id) REFERENCES items(id) ON DELETE CASCADE,
    FOREIGN KEY (vendor_id) REFERENCES vendors(id) ON DELETE CASCADE
);

-- ===========================================
-- PREFERENCES TABLE
-- Parsed ordering rules and preferences
-- ===========================================
CREATE TABLE IF NOT EXISTS preferences (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    rule_type TEXT CHECK(rule_type IN ('vendor_preference', 'price_threshold', 'quality_rule', 'alert', 'exclusion')),
    item_pattern TEXT DEFAULT '*',
    condition_text TEXT NOT NULL,
    action_text TEXT,
    priority INTEGER DEFAULT 0,
    is_active BOOLEAN DEFAULT 1,
    raw_note TEXT,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
);

-- ===========================================
-- ORDERS TABLE
-- Order history and drafts with savings tracking
-- ===========================================
CREATE TABLE IF NOT EXISTS orders (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    order_date DATETIME DEFAULT CURRENT_TIMESTAMP,
    status TEXT CHECK(status IN ('draft', 'submitted', 'completed', 'cancelled')) DEFAULT 'draft',
    total_amount REAL,
    total_savings REAL DEFAULT 0,
    savings_vs_avg REAL DEFAULT 0,
    savings_vs_max REAL DEFAULT 0,
    notes TEXT,
    created_by TEXT,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    -- Phase 2 (issue #17): headline basis = cheapest alternative vendor.
    -- lines_without_alt counts lines excluded for lack of a baseline;
    -- savings_basis='unknown_legacy' marks orders whose every line lacks one
    -- (stamped during migration; see migrations/001).
    savings_vs_alt REAL NOT NULL DEFAULT 0,
    lines_without_alt INTEGER NOT NULL DEFAULT 0,
    savings_basis TEXT NOT NULL DEFAULT 'vs_alt'
        CHECK(savings_basis IN ('vs_alt', 'unknown_legacy'))
);

-- ===========================================
-- ORDER ITEMS TABLE
-- Individual items in an order with savings details
-- ===========================================
CREATE TABLE IF NOT EXISTS order_items (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    order_id INTEGER NOT NULL,
    item_id INTEGER NOT NULL,
    vendor_id INTEGER NOT NULL,
    quantity REAL NOT NULL,
    unit TEXT,
    unit_price REAL,
    total_price REAL,
    avg_price REAL,
    max_price REAL,
    savings_vs_avg REAL DEFAULT 0,
    savings_vs_max REAL DEFAULT 0,
    notes TEXT,
    -- Phase 2 (issue #17): baseline = cheapest alternative vendor's latest
    -- quote at save time. NULL on legacy rows stamped during migration.
    alt_vendor_id INTEGER REFERENCES vendors(id),
    alt_price REAL,
    savings_basis TEXT NOT NULL DEFAULT 'vs_alt'
        CHECK(savings_basis IN ('vs_alt', 'unknown_legacy', 'no_alternative')),
    savings_vs_alt REAL NOT NULL DEFAULT 0,
    FOREIGN KEY (order_id) REFERENCES orders(id) ON DELETE CASCADE,
    FOREIGN KEY (item_id) REFERENCES items(id),
    FOREIGN KEY (vendor_id) REFERENCES vendors(id)
);

-- ===========================================
-- SAVINGS SUMMARY TABLE
-- Aggregated savings tracking over time
-- ===========================================
CREATE TABLE IF NOT EXISTS savings_summary (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    period_start DATE NOT NULL,
    period_end DATE NOT NULL,
    period_type TEXT CHECK(period_type IN ('daily', 'weekly', 'monthly')) DEFAULT 'weekly',
    total_orders INTEGER DEFAULT 0,
    total_spent REAL DEFAULT 0,
    total_savings_vs_avg REAL DEFAULT 0,
    total_savings_vs_max REAL DEFAULT 0,
    items_ordered INTEGER DEFAULT 0,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(period_start, period_end, period_type)
);

-- ===========================================
-- PROCESSING LOG TABLE
-- Track document processing history
-- ===========================================
CREATE TABLE IF NOT EXISTS processing_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source_type TEXT CHECK(source_type IN ('email', 'scrape', 'upload')),
    source_identifier TEXT,
    filename TEXT,
    status TEXT CHECK(status IN ('success', 'partial', 'failed')),
    items_processed INTEGER DEFAULT 0,
    error_message TEXT,
    processed_at DATETIME DEFAULT CURRENT_TIMESTAMP
);

-- ===========================================
-- INDEXES FOR PERFORMANCE
-- ===========================================
CREATE INDEX IF NOT EXISTS idx_price_history_item ON price_history(item_id);
CREATE INDEX IF NOT EXISTS idx_price_history_vendor ON price_history(vendor_id);
CREATE INDEX IF NOT EXISTS idx_price_history_date ON price_history(date_recorded);
CREATE INDEX IF NOT EXISTS idx_price_history_item_date ON price_history(item_id, date_recorded);
CREATE INDEX IF NOT EXISTS idx_items_category ON items(category);
CREATE INDEX IF NOT EXISTS idx_items_active ON items(is_active);
CREATE INDEX IF NOT EXISTS idx_orders_status ON orders(status);
CREATE INDEX IF NOT EXISTS idx_orders_date ON orders(order_date);
CREATE INDEX IF NOT EXISTS idx_savings_summary_period ON savings_summary(period_start, period_end);
CREATE INDEX IF NOT EXISTS idx_savings_summary_type ON savings_summary(period_type);

-- ===========================================
-- INITIAL DATA - DEFAULT VENDORS
-- ===========================================
INSERT OR IGNORE INTO vendors (name, email_domain, scrape_url, scrape_enabled) VALUES 
    ('Sysco', 'sysco.com', 'https://shop.sysco.com', 1),
    ('US Foods', 'usfoods.com', 'https://www.usfoods.com', 1);

-- ===========================================
-- INITIAL DATA - DEFAULT CATEGORIES
-- ===========================================
-- Categories will be populated as items are added
-- Common categories: Produce, Meat, Dairy, Dry Goods, Frozen, Beverages, Seafood, Bakery

-- ===========================================
-- TRIGGERS FOR UPDATED_AT
-- ===========================================
CREATE TRIGGER IF NOT EXISTS update_items_timestamp 
AFTER UPDATE ON items
BEGIN
    UPDATE items SET updated_at = CURRENT_TIMESTAMP WHERE id = NEW.id;
END;

CREATE TRIGGER IF NOT EXISTS update_preferences_timestamp 
AFTER UPDATE ON preferences
BEGIN
    UPDATE preferences SET updated_at = CURRENT_TIMESTAMP WHERE id = NEW.id;
END;

CREATE TRIGGER IF NOT EXISTS update_orders_timestamp 
AFTER UPDATE ON orders
BEGIN
    UPDATE orders SET updated_at = CURRENT_TIMESTAMP WHERE id = NEW.id;
END;

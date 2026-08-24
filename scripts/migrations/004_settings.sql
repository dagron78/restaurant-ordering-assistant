-- Migration 004 · settings table (Phase A, issue #50)
--
-- Operator-changeable configuration moves out of .env into the database
-- behind the admin password: API key, mailbox, scrape schedule, thresholds,
-- both password hashes. Fresh builds get this table from schema.sql;
-- existing databases get it here. PRAGMA user_version bumps to 4.

CREATE TABLE IF NOT EXISTS settings (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
);

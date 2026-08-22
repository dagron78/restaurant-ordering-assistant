-- Migration 003 · vendor intake registry + quarantine (issue #28)

-- Quarantine holds METADATA ONLY for messages from senders not present in
-- vendors. Nothing here is ever parsed or promoted into price_history
-- without a human adding the vendor; the mailbox message stays unseen so
-- promotion re-ingests it through the normal path.
CREATE TABLE IF NOT EXISTS quarantine (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    received_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    from_address TEXT NOT NULL,
    subject TEXT,
    attachment_names TEXT,
    UNIQUE(from_address, subject)
);

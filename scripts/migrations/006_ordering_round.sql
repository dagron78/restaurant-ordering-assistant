-- Migration 006 · ordering round (Phase C, issue #55)
--
-- order_items.chosen_by: records WHO picked the vendor on each line.
-- 'engine' = the recommendation, 'manager' = a human override. An
-- overridden line is not a recommendation; its savings are computed
-- against what was actually chosen (create_order already does this from
-- the chosen vendor_id, preserving deliberate negatives). Plain column,
-- not an audit table: one kitchen, one manager.
--
-- plan_drafts: the ordering round's server-side draft. The sheet's
-- quantities and the SENT plan snapshot (vendor, unit_price AND the
-- alt baseline per line) live here, so a phone locking its screen
-- cannot lose twenty minutes of entry, and confirm stores exactly what
-- was on screen. One open draft at a time (single kitchen, one
-- manager); a confirmed draft is never silently resurrected.

ALTER TABLE order_items ADD COLUMN chosen_by TEXT NOT NULL DEFAULT 'engine'
    CHECK(chosen_by IN ('engine', 'manager'));

CREATE TABLE IF NOT EXISTS plan_drafts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    status TEXT NOT NULL DEFAULT 'entering'
        CHECK(status IN ('entering', 'plan_ready', 'confirmed')),
    payload TEXT NOT NULL,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
);

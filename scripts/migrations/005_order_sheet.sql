-- Migration 005 · order sheet + sheet mappings (Phase B, issue #53)
--
-- order_sheet: the kitchen's standing list as a FIRST-CLASS entity, one
-- row per item on the sheet. Deliberately NOT columns on items: items is
-- the catalogue of things we know prices for, and email intake keeps
-- growing it — sheet membership is a different fact that only the
-- manager's import grants. par_level NULL means "no par set"; 0 means
-- "we stock this but do not normally reorder" — the distinction is
-- load-bearing, do not collapse them.
--
-- sheet_mappings: the stored column mapping (Phase B decision: named,
-- admin-visible, deletable — an invisible mapping that is subtly wrong
-- becomes undebuggable). header_texts_json records the header cells the
-- mapping was built from, so a re-import can tell whether the mapping
-- still applies.

CREATE TABLE IF NOT EXISTS order_sheet (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    item_id INTEGER NOT NULL UNIQUE REFERENCES items(id) ON DELETE CASCADE,
    par_level REAL,
    sheet_position INTEGER,
    added_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS sheet_mappings (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT UNIQUE NOT NULL,
    header_row INTEGER NOT NULL,
    columns_json TEXT NOT NULL,
    header_texts_json TEXT NOT NULL,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_order_sheet_position ON order_sheet(sheet_position);

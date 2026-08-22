-- Migration 002 · typed rule conditions + parser cache bookkeeping
-- (issue #20, Phase 3)
--
-- condition_json holds the structured predicate the parser extracted from
-- prose ({"prefer_vendor": ..., "switch_if_cheaper_pct": ...} for
-- vendor_preference; {"vendor": ...} for exclusion;
-- {"comparator": ..., "threshold": ...} for price_threshold). The
-- evaluator in core/rules.py reads ONLY this column — the LLM never sits
-- in the decision path.
--
-- source_hash records which content hash of preferences.txt produced the
-- row, and prefs_meta stores the latest one, so unchanged files skip
-- Gemini entirely on read paths (F-17).

ALTER TABLE preferences ADD COLUMN condition_json TEXT;
ALTER TABLE preferences ADD COLUMN source_hash TEXT;

CREATE TABLE IF NOT EXISTS prefs_meta (
    key TEXT PRIMARY KEY,
    value TEXT
);

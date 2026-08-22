-- Migration 001 · honest savings semantics (issue #17, Phase 2)
--
-- Adds the cheapest-alternative baseline columns and stamps legacy rows.
--
-- Legacy stamping rationale: these rows were written while exactly two
-- vendors existed, so wherever the stored max_price exceeded the unit price,
-- max_price IS min-of-others — the alternative quote at order time. That
-- equivalence is recorded ONCE here (savings_basis='vs_alt') rather than
-- left to be re-derived later by someone unaware a third vendor has since
-- been added. Rows where max_price <= unit_price collapse two situations
-- the data cannot distinguish (single-vendor quote vs dearer vendor chosen
-- anyway, stored 0 where honest answer is negative): they become
-- 'unknown_legacy' and are excluded from headline aggregates by count.
--
-- New rows written after this migration get basis 'vs_alt' or
-- 'no_alternative' from create_order(); this migration never emits
-- 'no_alternative'.

ALTER TABLE order_items ADD COLUMN alt_vendor_id INTEGER REFERENCES vendors(id);
ALTER TABLE order_items ADD COLUMN alt_price REAL;
ALTER TABLE order_items ADD COLUMN savings_basis TEXT NOT NULL DEFAULT 'vs_alt'
    CHECK(savings_basis IN ('vs_alt', 'unknown_legacy', 'no_alternative'));
ALTER TABLE order_items ADD COLUMN savings_vs_alt REAL NOT NULL DEFAULT 0;

ALTER TABLE orders ADD COLUMN savings_vs_alt REAL NOT NULL DEFAULT 0;
ALTER TABLE orders ADD COLUMN lines_without_alt INTEGER NOT NULL DEFAULT 0;
ALTER TABLE orders ADD COLUMN savings_basis TEXT NOT NULL DEFAULT 'vs_alt'
    CHECK(savings_basis IN ('vs_alt', 'unknown_legacy'));

-- Recomputable legacy lines: the two-vendor equivalence holds exactly.
UPDATE order_items SET
    alt_price       = max_price,
    savings_vs_alt  = savings_vs_max,
    savings_basis   = 'vs_alt'
 WHERE max_price > unit_price;

-- Unrecoverable legacy lines: excluded from headline, counted on the order.
UPDATE order_items SET
    alt_price      = NULL,
    savings_vs_alt = 0,
    savings_basis  = 'unknown_legacy'
 WHERE NOT (max_price > unit_price);

-- Order-level rollups over the stamped lines.
UPDATE orders SET
    savings_vs_alt    = COALESCE((SELECT SUM(oi.savings_vs_alt)
                                   FROM order_items oi
                                  WHERE oi.order_id = orders.id
                                    AND oi.savings_basis = 'vs_alt'), 0),
    lines_without_alt = COALESCE((SELECT COUNT(*)
                                   FROM order_items oi
                                  WHERE oi.order_id = orders.id
                                    AND oi.savings_basis <> 'vs_alt'), 0);

-- An order whose every line lacks a baseline is labelled unknown_legacy;
-- mixed orders keep 'vs_alt' (their aggregate is real) with the count shown.
UPDATE orders SET savings_basis = 'unknown_legacy'
 WHERE lines_without_alt > 0
   AND savings_vs_alt = 0;

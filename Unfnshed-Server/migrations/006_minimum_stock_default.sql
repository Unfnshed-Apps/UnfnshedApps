-- Migration 006: Update minimum_stock default from 5 to 2
-- Component minimums are now BOM-derived (product minimum × bom quantity),
-- so the per-product floor can be lower.

UPDATE replenishment_config SET minimum_stock = 2 WHERE id = 1 AND minimum_stock = 5;

ALTER TABLE replenishment_config ALTER COLUMN minimum_stock SET DEFAULT 2;

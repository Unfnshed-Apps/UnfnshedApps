-- Intent-aware assembly: tag sheet parts with the product they were nested for
-- so assembly only consumes components intended for each specific product.

ALTER TABLE sheet_parts
    ADD COLUMN IF NOT EXISTS product_sku VARCHAR(100),
    ADD COLUMN IF NOT EXISTS assembled_qty INTEGER NOT NULL DEFAULT 0;

ALTER TABLE sheet_part_placements
    ADD COLUMN IF NOT EXISTS product_sku VARCHAR(100);

CREATE INDEX IF NOT EXISTS idx_sheet_parts_assembly
    ON sheet_parts(product_sku, component_id)
    WHERE product_sku IS NOT NULL;

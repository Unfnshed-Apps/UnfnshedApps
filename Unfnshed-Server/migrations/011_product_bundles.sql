-- Product bundles: a bundle product references other products as "units"
-- e.g., SKU "2-ST18" is a bundle containing 2 units of "1-ST18"

CREATE TABLE IF NOT EXISTS product_units (
    id SERIAL PRIMARY KEY,
    bundle_sku TEXT NOT NULL REFERENCES products(sku) ON DELETE CASCADE,
    source_product_sku TEXT NOT NULL REFERENCES products(sku) ON DELETE RESTRICT,
    unit_index INTEGER NOT NULL DEFAULT 0,
    UNIQUE(bundle_sku, unit_index)
);
CREATE INDEX IF NOT EXISTS idx_product_units_bundle ON product_units(bundle_sku);

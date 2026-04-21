-- Manual Nests: hand-built sheet layouts that can override the auto-nester.
-- A manual nest is N sheets, each carrying M parts placed by hand. When
-- override_enabled is true and a job's demand matches the nest's contents
-- (product SKU + quantity), the nester uses the pre-built layout verbatim
-- instead of computing its own. Leftover demand still flows to auto-nest.

CREATE TABLE IF NOT EXISTS manual_nests (
    id SERIAL PRIMARY KEY,
    name TEXT NOT NULL,
    override_enabled BOOLEAN NOT NULL DEFAULT FALSE,
    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_manual_nests_override
    ON manual_nests(override_enabled);

CREATE TABLE IF NOT EXISTS manual_nest_sheets (
    id SERIAL PRIMARY KEY,
    nest_id INTEGER NOT NULL REFERENCES manual_nests(id) ON DELETE CASCADE,
    sheet_index INTEGER NOT NULL,
    width DOUBLE PRECISION NOT NULL,
    height DOUBLE PRECISION NOT NULL,
    part_spacing DOUBLE PRECISION NOT NULL DEFAULT 0.75,
    edge_margin DOUBLE PRECISION NOT NULL DEFAULT 0.75,
    material TEXT,
    thickness DOUBLE PRECISION,
    UNIQUE(nest_id, sheet_index)
);
CREATE INDEX IF NOT EXISTS idx_manual_nest_sheets_nest
    ON manual_nest_sheets(nest_id);

CREATE TABLE IF NOT EXISTS manual_nest_parts (
    id SERIAL PRIMARY KEY,
    sheet_id INTEGER NOT NULL REFERENCES manual_nest_sheets(id) ON DELETE CASCADE,
    component_id INTEGER NOT NULL REFERENCES component_definitions(id) ON DELETE RESTRICT,
    product_sku TEXT REFERENCES products(sku) ON DELETE SET NULL,
    product_unit INTEGER,
    instance_index INTEGER NOT NULL DEFAULT 0,
    x DOUBLE PRECISION NOT NULL,
    y DOUBLE PRECISION NOT NULL,
    rotation_deg DOUBLE PRECISION NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_manual_nest_parts_sheet
    ON manual_nest_parts(sheet_id);
CREATE INDEX IF NOT EXISTS idx_manual_nest_parts_product
    ON manual_nest_parts(product_sku);

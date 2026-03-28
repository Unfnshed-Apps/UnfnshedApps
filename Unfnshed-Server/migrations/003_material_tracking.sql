-- Migration 003: Material tracking (pallets, mating pairs)
-- Run against unfnshed_db after previous migrations

BEGIN;

-- ==================== New Tables ====================

-- Pallet tracking with measured thickness
CREATE TABLE IF NOT EXISTS pallets (
    id SERIAL PRIMARY KEY,
    material_type_id INTEGER REFERENCES material_types(id),
    measurement_1 DOUBLE PRECISION NOT NULL,
    measurement_2 DOUBLE PRECISION NOT NULL,
    measurement_3 DOUBLE PRECISION NOT NULL,
    avg_thickness_inches DOUBLE PRECISION NOT NULL,
    sheets_remaining INTEGER NOT NULL DEFAULT 0,
    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
    depleted_at TIMESTAMPTZ
);

-- Which pallet is currently loaded on each CNC machine
CREATE TABLE IF NOT EXISTS machine_active_pallets (
    machine_letter VARCHAR(10) PRIMARY KEY,
    pallet_id INTEGER REFERENCES pallets(id),
    assigned_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
);

-- Defines which components mate: pocket_component receives mating_component's tab
CREATE TABLE IF NOT EXISTS component_mating_pairs (
    id SERIAL PRIMARY KEY,
    pocket_component_id INTEGER NOT NULL REFERENCES component_definitions(id),
    mating_component_id INTEGER NOT NULL REFERENCES component_definitions(id),
    pocket_index INTEGER NOT NULL DEFAULT 0,
    clearance_inches DOUBLE PRECISION NOT NULL DEFAULT 0.0079,
    UNIQUE(pocket_component_id, mating_component_id, pocket_index)
);

-- ==================== Alter Existing Tables ====================

-- Add material tracking fields to nesting sheets
ALTER TABLE nesting_sheets
    ADD COLUMN IF NOT EXISTS has_variable_pockets BOOLEAN DEFAULT FALSE,
    ADD COLUMN IF NOT EXISTS pallet_id INTEGER REFERENCES pallets(id),
    ADD COLUMN IF NOT EXISTS actual_thickness_inches DOUBLE PRECISION;

-- ==================== Indexes ====================

CREATE INDEX IF NOT EXISTS idx_pallets_material_type ON pallets(material_type_id);
CREATE INDEX IF NOT EXISTS idx_pallets_active ON pallets(depleted_at) WHERE depleted_at IS NULL;
CREATE INDEX IF NOT EXISTS idx_component_mating_pairs_pocket ON component_mating_pairs(pocket_component_id);
CREATE INDEX IF NOT EXISTS idx_component_mating_pairs_mating ON component_mating_pairs(mating_component_id);
-- ==================== Permissions ====================

GRANT ALL PRIVILEGES ON ALL TABLES IN SCHEMA public TO nesting_user;
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO nesting_user;
GRANT ALL PRIVILEGES ON ALL TABLES IN SCHEMA public TO unfnshed_user;
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO unfnshed_user;

COMMIT;

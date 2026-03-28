-- Migration 004: Inventory replenishment system
-- Adds forecasting, replenishment queue, and sheet bundle tables

-- ==================== Replenishment Config ====================

-- Single-row config table for tunable replenishment parameters
CREATE TABLE IF NOT EXISTS replenishment_config (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    target_days_a INTEGER NOT NULL DEFAULT 4,
    target_days_b INTEGER NOT NULL DEFAULT 2,
    reorder_days_a INTEGER NOT NULL DEFAULT 2,
    reorder_days_b INTEGER NOT NULL DEFAULT 1,
    minimum_stock INTEGER NOT NULL DEFAULT 2,
    tolerance_ceiling DOUBLE PRECISION NOT NULL DEFAULT 1.25,
    ses_alpha DOUBLE PRECISION NOT NULL DEFAULT 0.3,
    trend_clamp_low DOUBLE PRECISION NOT NULL DEFAULT 0.85,
    trend_clamp_high DOUBLE PRECISION NOT NULL DEFAULT 1.15,
    fill_weight_urgency DOUBLE PRECISION NOT NULL DEFAULT 0.40,
    fill_weight_velocity DOUBLE PRECISION NOT NULL DEFAULT 0.25,
    fill_weight_geometric DOUBLE PRECISION NOT NULL DEFAULT 0.20,
    fill_weight_value DOUBLE PRECISION NOT NULL DEFAULT 0.15,
    max_fill_types_per_sheet INTEGER NOT NULL DEFAULT 5,
    updated_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
);

-- Insert default config row
INSERT INTO replenishment_config (id) VALUES (1)
ON CONFLICT (id) DO NOTHING;

-- ==================== Demand Tracking ====================

-- Materialized daily demand per component (from orders × BOM)
CREATE TABLE IF NOT EXISTS component_daily_demand (
    id SERIAL PRIMARY KEY,
    component_id INTEGER NOT NULL REFERENCES component_definitions(id) ON DELETE CASCADE,
    demand_date DATE NOT NULL,
    quantity INTEGER NOT NULL DEFAULT 0,
    UNIQUE(component_id, demand_date)
);

CREATE INDEX IF NOT EXISTS idx_daily_demand_component ON component_daily_demand(component_id);
CREATE INDEX IF NOT EXISTS idx_daily_demand_date ON component_daily_demand(demand_date DESC);

-- ==================== Forecasting ====================

-- SES forecast state per component
CREATE TABLE IF NOT EXISTS component_forecast (
    id SERIAL PRIMARY KEY,
    component_id INTEGER NOT NULL REFERENCES component_definitions(id) ON DELETE CASCADE UNIQUE,
    velocity DOUBLE PRECISION NOT NULL DEFAULT 0,          -- units per day (smoothed)
    forecast DOUBLE PRECISION NOT NULL DEFAULT 0,          -- SES forecast value
    std_dev DOUBLE PRECISION NOT NULL DEFAULT 0,           -- forecast error std dev
    abc_class VARCHAR(1) NOT NULL DEFAULT 'C',             -- A, B, or C
    trend_ratio DOUBLE PRECISION NOT NULL DEFAULT 1.0,     -- 7d_avg / 30d_avg clamped
    trailing_7d DOUBLE PRECISION NOT NULL DEFAULT 0,       -- trailing 7-day average
    trailing_30d DOUBLE PRECISION NOT NULL DEFAULT 0,      -- trailing 30-day average
    data_points INTEGER NOT NULL DEFAULT 0,                -- days of history available
    updated_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_forecast_abc ON component_forecast(abc_class);

-- ==================== Replenishment Snapshots ====================

-- Point-in-time calculation audit trail
CREATE TABLE IF NOT EXISTS replenishment_snapshots (
    id SERIAL PRIMARY KEY,
    calculated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    config_snapshot JSONB,                                 -- config values used
    total_mandatory INTEGER NOT NULL DEFAULT 0,
    total_fill INTEGER NOT NULL DEFAULT 0
);

-- Per-component needs within a snapshot
CREATE TABLE IF NOT EXISTS replenishment_needs (
    id SERIAL PRIMARY KEY,
    snapshot_id INTEGER NOT NULL REFERENCES replenishment_snapshots(id) ON DELETE CASCADE,
    component_id INTEGER NOT NULL REFERENCES component_definitions(id) ON DELETE CASCADE,
    abc_class VARCHAR(1) NOT NULL DEFAULT 'C',
    velocity DOUBLE PRECISION NOT NULL DEFAULT 0,
    trend_ratio DOUBLE PRECISION NOT NULL DEFAULT 1.0,
    current_stock INTEGER NOT NULL DEFAULT 0,
    reserved INTEGER NOT NULL DEFAULT 0,
    pipeline INTEGER NOT NULL DEFAULT 0,                   -- in cutting queue
    effective_stock INTEGER NOT NULL DEFAULT 0,
    target_stock INTEGER NOT NULL DEFAULT 0,
    reorder_point INTEGER NOT NULL DEFAULT 0,
    tolerance_ceiling INTEGER NOT NULL DEFAULT 0,
    deficit INTEGER NOT NULL DEFAULT 0,                    -- how many to cut
    is_mandatory BOOLEAN NOT NULL DEFAULT FALSE,
    fill_score DOUBLE PRECISION,                           -- NULL if mandatory
    fill_score_urgency DOUBLE PRECISION,
    fill_score_velocity DOUBLE PRECISION,
    fill_score_geometric DOUBLE PRECISION,
    fill_score_value DOUBLE PRECISION
);

CREATE INDEX IF NOT EXISTS idx_replenishment_needs_snapshot ON replenishment_needs(snapshot_id);
CREATE INDEX IF NOT EXISTS idx_replenishment_needs_mandatory ON replenishment_needs(is_mandatory);

-- ==================== Sheet Bundles ====================

-- Groups 2-4 sheets with pallet/machine affinity
CREATE TABLE IF NOT EXISTS sheet_bundles (
    id SERIAL PRIMARY KEY,
    status VARCHAR(20) NOT NULL DEFAULT 'pending',         -- pending, cutting, completed
    sheet_count INTEGER NOT NULL DEFAULT 0,
    claimed_by VARCHAR(10),                                -- machine letter, NULL until first claim
    pallet_id INTEGER REFERENCES pallets(id),              -- NULL until assigned at CNC claim time
    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
    completed_at TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS idx_bundles_status ON sheet_bundles(status);
CREATE INDEX IF NOT EXISTS idx_bundles_claimed ON sheet_bundles(claimed_by);

-- Add bundle_id to nesting_sheets (nullable FK)
DO $$ BEGIN
    ALTER TABLE nesting_sheets ADD COLUMN bundle_id INTEGER;
EXCEPTION WHEN duplicate_column THEN NULL;
END $$;

DO $$ BEGIN
    ALTER TABLE nesting_sheets ADD CONSTRAINT fk_nesting_sheets_bundle
        FOREIGN KEY (bundle_id) REFERENCES sheet_bundles(id) ON DELETE SET NULL;
EXCEPTION WHEN duplicate_object THEN NULL;
END $$;

CREATE INDEX IF NOT EXISTS idx_nesting_sheets_bundle ON nesting_sheets(bundle_id);

-- ==================== Permissions ====================

GRANT ALL PRIVILEGES ON ALL TABLES IN SCHEMA public TO nesting_user;
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO nesting_user;
GRANT ALL PRIVILEGES ON ALL TABLES IN SCHEMA public TO unfnshed_user;
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO unfnshed_user;

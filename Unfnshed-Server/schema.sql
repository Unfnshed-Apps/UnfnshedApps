-- PostgreSQL schema for Nesting App
-- Converted from SQLite schema in src/database.py

-- Component definitions (master list of component types)
CREATE TABLE IF NOT EXISTS component_definitions (
    id SERIAL PRIMARY KEY,
    name TEXT NOT NULL UNIQUE,
    dxf_filename TEXT NOT NULL,
    variable_pockets BOOLEAN NOT NULL DEFAULT FALSE,
    mating_role VARCHAR(10) NOT NULL DEFAULT 'neutral'
);

-- CNC machine registry
CREATE TABLE IF NOT EXISTS machines (
    id SERIAL PRIMARY KEY,
    name TEXT NOT NULL UNIQUE,
    active BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

-- Products table
CREATE TABLE IF NOT EXISTS products (
    sku TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    description TEXT,
    outsourced BOOLEAN DEFAULT FALSE
);

-- Product-component relationship (which components make up a product)
CREATE TABLE IF NOT EXISTS product_components (
    id SERIAL PRIMARY KEY,
    product_sku TEXT NOT NULL REFERENCES products(sku) ON DELETE CASCADE,
    component_id INTEGER NOT NULL REFERENCES component_definitions(id),
    quantity INTEGER NOT NULL DEFAULT 1
);

-- Product bundles: a bundle product references other products as "units"
CREATE TABLE IF NOT EXISTS product_units (
    id SERIAL PRIMARY KEY,
    bundle_sku TEXT NOT NULL REFERENCES products(sku) ON DELETE CASCADE,
    source_product_sku TEXT NOT NULL REFERENCES products(sku) ON DELETE RESTRICT,
    unit_index INTEGER NOT NULL DEFAULT 0,
    UNIQUE(bundle_sku, unit_index)
);
CREATE INDEX IF NOT EXISTS idx_product_units_bundle ON product_units(bundle_sku);

-- Shopify settings (single row table for API credentials)
CREATE TABLE IF NOT EXISTS shopify_settings (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    store_url TEXT,
    client_id TEXT,
    client_secret TEXT,
    api_version TEXT DEFAULT '2026-01',
    auto_sync BOOLEAN DEFAULT FALSE,
    sync_interval_minutes INTEGER DEFAULT 60,
    last_sync TIMESTAMP WITH TIME ZONE
);

-- Shopify orders (comprehensive data)
CREATE TABLE IF NOT EXISTS shopify_orders (
    id SERIAL PRIMARY KEY,
    shopify_order_id TEXT UNIQUE NOT NULL,
    order_number TEXT,
    name TEXT,                                    -- Display name like "#1001"
    created_at TIMESTAMP WITH TIME ZONE,
    processed_at TIMESTAMP WITH TIME ZONE,
    closed_at TIMESTAMP WITH TIME ZONE,
    cancelled_at TIMESTAMP WITH TIME ZONE,
    cancel_reason TEXT,
    -- Customer info
    customer_name TEXT,
    email TEXT,
    phone TEXT,
    -- Addresses
    shipping_address JSONB,
    billing_address JSONB,
    -- Pricing
    total_price TEXT,
    subtotal_price TEXT,
    total_tax TEXT,
    total_discounts TEXT,
    total_shipping TEXT,
    currency TEXT,
    -- Status
    financial_status TEXT,
    fulfillment_status TEXT,
    -- Metadata
    note TEXT,                                    -- Customer notes/instructions
    tags TEXT,                                    -- Comma-separated tags
    source_name TEXT,                             -- web, pos, api, etc.
    landing_site TEXT,
    referring_site TEXT,
    discount_codes JSONB,                         -- Array of discount codes used
    shipping_lines JSONB,                         -- Shipping methods chosen
    payment_gateway_names JSONB,                  -- Payment methods used
    -- Internal / Production tracking
    synced_at TIMESTAMP WITH TIME ZONE,
    production_status TEXT DEFAULT 'pending',
    nested_at TIMESTAMP WITH TIME ZONE,
    cut_at TIMESTAMP WITH TIME ZONE,
    packed_at TIMESTAMP WITH TIME ZONE
);

-- Shopify order line items (comprehensive data)
CREATE TABLE IF NOT EXISTS shopify_order_items (
    id SERIAL PRIMARY KEY,
    order_id INTEGER NOT NULL REFERENCES shopify_orders(id) ON DELETE CASCADE,
    shopify_line_item_id BIGINT,
    shopify_product_id BIGINT,                    -- Link to Shopify product
    shopify_variant_id BIGINT,                    -- Link to Shopify variant
    sku TEXT,
    title TEXT,
    variant_title TEXT,                           -- e.g., "Large / Walnut"
    vendor TEXT,
    quantity INTEGER,
    price TEXT,
    total_discount TEXT,
    fulfillable_quantity INTEGER,
    fulfillment_status TEXT,
    requires_shipping BOOLEAN DEFAULT TRUE,
    taxable BOOLEAN DEFAULT TRUE,
    gift_card BOOLEAN DEFAULT FALSE,
    properties JSONB,                             -- Custom line item properties
    tax_lines JSONB,
    discount_allocations JSONB,
    grams INTEGER,                                -- Weight in grams
    local_product_sku TEXT REFERENCES products(sku) ON DELETE SET NULL
);

-- Shopify fulfillments (tracking info)
CREATE TABLE IF NOT EXISTS shopify_fulfillments (
    id SERIAL PRIMARY KEY,
    order_id INTEGER NOT NULL REFERENCES shopify_orders(id) ON DELETE CASCADE,
    shopify_fulfillment_id BIGINT UNIQUE,
    status TEXT,                                  -- pending, open, success, cancelled, error, failure
    created_at TIMESTAMP WITH TIME ZONE,
    updated_at TIMESTAMP WITH TIME ZONE,
    tracking_company TEXT,                        -- UPS, FedEx, USPS, etc.
    tracking_number TEXT,
    tracking_numbers JSONB,                       -- Array if multiple
    tracking_url TEXT,
    tracking_urls JSONB,                          -- Array if multiple
    shipment_status TEXT,                         -- delivered, in_transit, etc.
    service TEXT,                                 -- Shipping service name
    location_id BIGINT,
    line_items JSONB                              -- Which line items are in this fulfillment
);

-- Indexes for common queries
CREATE INDEX IF NOT EXISTS idx_product_components_sku ON product_components(product_sku);
CREATE INDEX IF NOT EXISTS idx_product_components_component ON product_components(component_id);
CREATE INDEX IF NOT EXISTS idx_shopify_orders_status ON shopify_orders(production_status);
CREATE INDEX IF NOT EXISTS idx_shopify_orders_created ON shopify_orders(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_shopify_orders_financial ON shopify_orders(financial_status);
CREATE INDEX IF NOT EXISTS idx_shopify_orders_fulfillment ON shopify_orders(fulfillment_status);
CREATE INDEX IF NOT EXISTS idx_shopify_order_items_order ON shopify_order_items(order_id);
CREATE INDEX IF NOT EXISTS idx_shopify_order_items_sku ON shopify_order_items(sku);
CREATE INDEX IF NOT EXISTS idx_shopify_order_items_product ON shopify_order_items(shopify_product_id);
CREATE INDEX IF NOT EXISTS idx_shopify_fulfillments_order ON shopify_fulfillments(order_id);
CREATE INDEX IF NOT EXISTS idx_shopify_fulfillments_status ON shopify_fulfillments(status);

-- ==================== Inventory Management Tables ====================

-- Component inventory (cut parts on hand)
CREATE TABLE IF NOT EXISTS component_inventory (
    id SERIAL PRIMARY KEY,
    component_id INTEGER NOT NULL REFERENCES component_definitions(id) ON DELETE CASCADE UNIQUE,
    quantity_on_hand INTEGER NOT NULL DEFAULT 0,
    quantity_reserved INTEGER NOT NULL DEFAULT 0,
    last_updated TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

-- Audit trail for all inventory changes
CREATE TABLE IF NOT EXISTS inventory_transactions (
    id SERIAL PRIMARY KEY,
    component_id INTEGER NOT NULL REFERENCES component_definitions(id) ON DELETE CASCADE,
    transaction_type VARCHAR(50) NOT NULL,  -- cut, assembled, adjustment, damaged
    quantity INTEGER NOT NULL,              -- positive=add, negative=remove
    reference_type VARCHAR(50),             -- nesting_sheet, assembly_batch, manual
    reference_id INTEGER,
    notes TEXT,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    created_by VARCHAR(100)
);

-- Nesting jobs (batches of sheets from Unfnest)
CREATE TABLE IF NOT EXISTS nesting_jobs (
    id SERIAL PRIMARY KEY,
    name VARCHAR(255),
    status VARCHAR(50) DEFAULT 'pending',   -- pending, cutting, completed
    total_sheets INTEGER DEFAULT 0,
    completed_sheets INTEGER DEFAULT 0,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    created_by VARCHAR(100),
    prototype BOOLEAN DEFAULT FALSE
);

-- Individual sheets within a job
CREATE TABLE IF NOT EXISTS nesting_sheets (
    id SERIAL PRIMARY KEY,
    job_id INTEGER NOT NULL REFERENCES nesting_jobs(id) ON DELETE CASCADE,
    sheet_number INTEGER NOT NULL,
    dxf_filename VARCHAR(255),
    gcode_filename VARCHAR(255),
    status VARCHAR(50) DEFAULT 'pending',   -- pending, cutting, cut, failed
    cut_at TIMESTAMP WITH TIME ZONE,
    claimed_by VARCHAR(100),                -- machine name
    claimed_at TIMESTAMP WITH TIME ZONE,
    has_variable_pockets BOOLEAN DEFAULT FALSE,
    pallet_id INTEGER,                            -- FK added after pallets table creation
    actual_thickness_inches DOUBLE PRECISION,
    bundle_id INTEGER                             -- FK added after sheet_bundles table creation
);

-- Parts on each sheet (for inventory tracking)
CREATE TABLE IF NOT EXISTS sheet_parts (
    id SERIAL PRIMARY KEY,
    sheet_id INTEGER NOT NULL REFERENCES nesting_sheets(id) ON DELETE CASCADE,
    component_id INTEGER NOT NULL REFERENCES component_definitions(id) ON DELETE CASCADE,
    quantity INTEGER DEFAULT 1
);

-- Per-instance placement positions (for exact part identification in UnfnCNC)
CREATE TABLE IF NOT EXISTS sheet_part_placements (
    id SERIAL PRIMARY KEY,
    sheet_id INTEGER NOT NULL REFERENCES nesting_sheets(id) ON DELETE CASCADE,
    component_id INTEGER NOT NULL REFERENCES component_definitions(id) ON DELETE CASCADE,
    order_id INTEGER REFERENCES shopify_orders(id) ON DELETE SET NULL,
    instance_index INTEGER NOT NULL DEFAULT 0,
    x DOUBLE PRECISION NOT NULL,
    y DOUBLE PRECISION NOT NULL,
    rotation DOUBLE PRECISION NOT NULL DEFAULT 0,
    source_dxf VARCHAR(255)
);
CREATE INDEX IF NOT EXISTS idx_spp_sheet ON sheet_part_placements(sheet_id);

-- Finished product inventory
CREATE TABLE IF NOT EXISTS product_inventory (
    id SERIAL PRIMARY KEY,
    product_sku VARCHAR(100) NOT NULL REFERENCES products(sku) ON DELETE CASCADE UNIQUE,
    quantity_on_hand INTEGER NOT NULL DEFAULT 0,
    quantity_reserved INTEGER NOT NULL DEFAULT 0,
    last_updated TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

-- Raw materials (plywood, boxes, hardware)
CREATE TABLE IF NOT EXISTS material_types (
    id SERIAL PRIMARY KEY,
    name VARCHAR(255) NOT NULL UNIQUE,
    category VARCHAR(50),                   -- sheet_goods, packaging, hardware
    unit VARCHAR(50) NOT NULL,              -- sheet, box, piece
    reorder_point INTEGER DEFAULT 0
);

-- Raw material inventory
CREATE TABLE IF NOT EXISTS material_inventory (
    id SERIAL PRIMARY KEY,
    material_type_id INTEGER NOT NULL REFERENCES material_types(id) UNIQUE,
    quantity_on_hand INTEGER NOT NULL DEFAULT 0,
    last_updated TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

-- ==================== Material Tracking Tables ====================

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
    machine_letter VARCHAR(100) PRIMARY KEY,
    pallet_id INTEGER REFERENCES pallets(id),
    assigned_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
);

-- Defines which components mate: pocket_component receives mating_component's tab
CREATE TABLE IF NOT EXISTS component_mating_pairs (
    id SERIAL PRIMARY KEY,
    product_sku TEXT NOT NULL REFERENCES products(sku) ON DELETE CASCADE,
    pocket_component_id INTEGER NOT NULL REFERENCES component_definitions(id) ON DELETE CASCADE,
    mating_component_id INTEGER NOT NULL REFERENCES component_definitions(id) ON DELETE CASCADE,
    pocket_index INTEGER NOT NULL DEFAULT 0,
    clearance_inches DOUBLE PRECISION NOT NULL DEFAULT 0.0079,
    UNIQUE(product_sku, pocket_component_id, mating_component_id, pocket_index)
);

CREATE INDEX IF NOT EXISTS idx_pallets_material_type ON pallets(material_type_id);
CREATE INDEX IF NOT EXISTS idx_pallets_active ON pallets(depleted_at) WHERE depleted_at IS NULL;
CREATE INDEX IF NOT EXISTS idx_component_mating_pairs_pocket ON component_mating_pairs(pocket_component_id);
CREATE INDEX IF NOT EXISTS idx_component_mating_pairs_mating ON component_mating_pairs(mating_component_id);
-- Add deferred FK from nesting_sheets to pallets (pallets defined after nesting_sheets)
DO $$ BEGIN
    ALTER TABLE nesting_sheets ADD CONSTRAINT fk_nesting_sheets_pallet
        FOREIGN KEY (pallet_id) REFERENCES pallets(id);
EXCEPTION WHEN duplicate_object THEN NULL;
END $$;

-- Indexes for inventory tables
CREATE INDEX IF NOT EXISTS idx_inventory_transactions_component ON inventory_transactions(component_id);
CREATE INDEX IF NOT EXISTS idx_inventory_transactions_type ON inventory_transactions(transaction_type);
CREATE INDEX IF NOT EXISTS idx_inventory_transactions_created ON inventory_transactions(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_nesting_jobs_status ON nesting_jobs(status);
CREATE INDEX IF NOT EXISTS idx_nesting_sheets_job ON nesting_sheets(job_id);
CREATE INDEX IF NOT EXISTS idx_nesting_sheets_status ON nesting_sheets(status);
CREATE INDEX IF NOT EXISTS idx_nesting_sheets_variable_pockets ON nesting_sheets(has_variable_pockets);
CREATE INDEX IF NOT EXISTS idx_sheet_parts_sheet ON sheet_parts(sheet_id);
CREATE INDEX IF NOT EXISTS idx_sheet_parts_component ON sheet_parts(component_id);

-- Damaged parts reported during cutting
CREATE TABLE IF NOT EXISTS damaged_parts (
    id SERIAL PRIMARY KEY,
    sheet_id INTEGER NOT NULL REFERENCES nesting_sheets(id) ON DELETE CASCADE,
    component_id INTEGER NOT NULL REFERENCES component_definitions(id) ON DELETE CASCADE,
    quantity INTEGER NOT NULL DEFAULT 1,
    reported_by VARCHAR(10),
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    renested_job_id INTEGER REFERENCES nesting_jobs(id),
    renested_at TIMESTAMP WITH TIME ZONE
);
CREATE INDEX IF NOT EXISTS idx_damaged_parts_sheet ON damaged_parts(sheet_id);
CREATE INDEX IF NOT EXISTS idx_damaged_parts_component ON damaged_parts(component_id);

-- Junction table linking nesting sheets to shopify orders
CREATE TABLE IF NOT EXISTS nesting_sheet_orders (
    id SERIAL PRIMARY KEY,
    sheet_id INTEGER NOT NULL REFERENCES nesting_sheets(id) ON DELETE CASCADE,
    order_id INTEGER NOT NULL REFERENCES shopify_orders(id) ON DELETE CASCADE,
    UNIQUE(sheet_id, order_id)
);
CREATE INDEX IF NOT EXISTS idx_nesting_sheet_orders_sheet ON nesting_sheet_orders(sheet_id);
CREATE INDEX IF NOT EXISTS idx_nesting_sheet_orders_order ON nesting_sheet_orders(order_id);

-- ==================== Replenishment System Tables ====================

-- Single-row config for tunable replenishment parameters
CREATE TABLE IF NOT EXISTS replenishment_config (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    target_days_a INTEGER NOT NULL DEFAULT 4,
    target_days_b INTEGER NOT NULL DEFAULT 2,
    reorder_days_a INTEGER NOT NULL DEFAULT 2,
    reorder_days_b INTEGER NOT NULL DEFAULT 1,
    minimum_stock INTEGER NOT NULL DEFAULT 5,
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

-- Materialized daily demand per component (from orders x BOM)
CREATE TABLE IF NOT EXISTS component_daily_demand (
    id SERIAL PRIMARY KEY,
    component_id INTEGER NOT NULL REFERENCES component_definitions(id) ON DELETE CASCADE,
    demand_date DATE NOT NULL,
    quantity INTEGER NOT NULL DEFAULT 0,
    UNIQUE(component_id, demand_date)
);
CREATE INDEX IF NOT EXISTS idx_daily_demand_component ON component_daily_demand(component_id);
CREATE INDEX IF NOT EXISTS idx_daily_demand_date ON component_daily_demand(demand_date DESC);

-- SES forecast state per component
CREATE TABLE IF NOT EXISTS component_forecast (
    id SERIAL PRIMARY KEY,
    component_id INTEGER NOT NULL REFERENCES component_definitions(id) ON DELETE CASCADE UNIQUE,
    velocity DOUBLE PRECISION NOT NULL DEFAULT 0,
    forecast DOUBLE PRECISION NOT NULL DEFAULT 0,
    std_dev DOUBLE PRECISION NOT NULL DEFAULT 0,
    abc_class VARCHAR(1) NOT NULL DEFAULT 'C',
    trend_ratio DOUBLE PRECISION NOT NULL DEFAULT 1.0,
    trailing_7d DOUBLE PRECISION NOT NULL DEFAULT 0,
    trailing_30d DOUBLE PRECISION NOT NULL DEFAULT 0,
    data_points INTEGER NOT NULL DEFAULT 0,
    updated_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_forecast_abc ON component_forecast(abc_class);

-- Point-in-time replenishment calculation audit trail
CREATE TABLE IF NOT EXISTS replenishment_snapshots (
    id SERIAL PRIMARY KEY,
    calculated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    config_snapshot JSONB,
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
    pipeline INTEGER NOT NULL DEFAULT 0,
    effective_stock INTEGER NOT NULL DEFAULT 0,
    target_stock INTEGER NOT NULL DEFAULT 0,
    reorder_point INTEGER NOT NULL DEFAULT 0,
    tolerance_ceiling INTEGER NOT NULL DEFAULT 0,
    deficit INTEGER NOT NULL DEFAULT 0,
    is_mandatory BOOLEAN NOT NULL DEFAULT FALSE,
    fill_score DOUBLE PRECISION,
    fill_score_urgency DOUBLE PRECISION,
    fill_score_velocity DOUBLE PRECISION,
    fill_score_geometric DOUBLE PRECISION,
    fill_score_value DOUBLE PRECISION
);
CREATE INDEX IF NOT EXISTS idx_replenishment_needs_snapshot ON replenishment_needs(snapshot_id);
CREATE INDEX IF NOT EXISTS idx_replenishment_needs_mandatory ON replenishment_needs(is_mandatory);

-- Sheet bundles: groups 2-4 sheets with pallet/machine affinity
CREATE TABLE IF NOT EXISTS sheet_bundles (
    id SERIAL PRIMARY KEY,
    status VARCHAR(20) NOT NULL DEFAULT 'pending',
    sheet_count INTEGER NOT NULL DEFAULT 0,
    claimed_by VARCHAR(100),
    pallet_id INTEGER REFERENCES pallets(id),
    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
    completed_at TIMESTAMPTZ
);
CREATE INDEX IF NOT EXISTS idx_bundles_status ON sheet_bundles(status);
CREATE INDEX IF NOT EXISTS idx_bundles_claimed ON sheet_bundles(claimed_by);

-- Add deferred FK from nesting_sheets.bundle_id to sheet_bundles
DO $$ BEGIN
    ALTER TABLE nesting_sheets ADD CONSTRAINT fk_nesting_sheets_bundle
        FOREIGN KEY (bundle_id) REFERENCES sheet_bundles(id);
EXCEPTION WHEN duplicate_object THEN NULL;
END $$;
CREATE INDEX IF NOT EXISTS idx_nesting_sheets_bundle ON nesting_sheets(bundle_id);

-- ==================== Product-Level Forecasting Tables ====================

-- Materialized daily demand per product (from Shopify orders)
CREATE TABLE IF NOT EXISTS product_daily_demand (
    id SERIAL PRIMARY KEY,
    product_sku TEXT NOT NULL REFERENCES products(sku) ON DELETE CASCADE,
    demand_date DATE NOT NULL,
    quantity INTEGER NOT NULL DEFAULT 0,
    UNIQUE(product_sku, demand_date)
);
CREATE INDEX IF NOT EXISTS idx_product_daily_demand_sku ON product_daily_demand(product_sku);
CREATE INDEX IF NOT EXISTS idx_product_daily_demand_date ON product_daily_demand(demand_date DESC);

-- SES forecast state per product
CREATE TABLE IF NOT EXISTS product_forecast (
    id SERIAL PRIMARY KEY,
    product_sku TEXT NOT NULL REFERENCES products(sku) ON DELETE CASCADE UNIQUE,
    velocity DOUBLE PRECISION NOT NULL DEFAULT 0,
    forecast DOUBLE PRECISION NOT NULL DEFAULT 0,
    std_dev DOUBLE PRECISION NOT NULL DEFAULT 0,
    abc_class VARCHAR(1) NOT NULL DEFAULT 'C',
    trailing_7d DOUBLE PRECISION NOT NULL DEFAULT 0,
    trailing_30d DOUBLE PRECISION NOT NULL DEFAULT 0,
    trend_ratio DOUBLE PRECISION NOT NULL DEFAULT 1.0,
    data_points INTEGER NOT NULL DEFAULT 0,
    target_units INTEGER NOT NULL DEFAULT 0,
    updated_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_product_forecast_abc ON product_forecast(abc_class);

-- Add precomputed product-driven target columns to component_forecast
DO $$ BEGIN
    ALTER TABLE component_forecast ADD COLUMN target_stock INTEGER NOT NULL DEFAULT 0;
EXCEPTION WHEN duplicate_column THEN NULL;
END $$;

DO $$ BEGIN
    ALTER TABLE component_forecast ADD COLUMN reorder_point INTEGER NOT NULL DEFAULT 0;
EXCEPTION WHEN duplicate_column THEN NULL;
END $$;

-- Grant permissions to database users
GRANT ALL PRIVILEGES ON ALL TABLES IN SCHEMA public TO nesting_user;
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO nesting_user;
GRANT ALL PRIVILEGES ON ALL TABLES IN SCHEMA public TO unfnshed_user;
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO unfnshed_user;

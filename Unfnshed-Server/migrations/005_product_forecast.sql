-- Migration 005: Product-level forecasting with bundle rounding
-- Adds product demand tracking, product forecasts, and precomputed component targets

-- ==================== Product Daily Demand ====================

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

-- ==================== Product Forecast ====================

-- SES forecast state per product (mirrors component_forecast structure)
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

-- ==================== Precomputed Component Targets ====================

-- Add product-driven target columns to component_forecast
DO $$ BEGIN
    ALTER TABLE component_forecast ADD COLUMN target_stock INTEGER NOT NULL DEFAULT 0;
EXCEPTION WHEN duplicate_column THEN NULL;
END $$;

DO $$ BEGIN
    ALTER TABLE component_forecast ADD COLUMN reorder_point INTEGER NOT NULL DEFAULT 0;
EXCEPTION WHEN duplicate_column THEN NULL;
END $$;

-- ==================== Permissions ====================

GRANT ALL PRIVILEGES ON ALL TABLES IN SCHEMA public TO nesting_user;
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO nesting_user;
GRANT ALL PRIVILEGES ON ALL TABLES IN SCHEMA public TO unfnshed_user;
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO unfnshed_user;

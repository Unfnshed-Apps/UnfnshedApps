-- Add Order-Up-To (R,S) policy parameters to replenishment config.
-- review_period_days: how often we nest (R), default 7 = weekly
-- lead_time_days: nesting → cut → assembled (L), default 4
-- service_z: Z-score for safety stock, default 1.65 = 95% service level
-- trend_clamp_low/high: bounds for trend reactivity

DO $$ BEGIN
    ALTER TABLE replenishment_config ADD COLUMN review_period_days INTEGER NOT NULL DEFAULT 7;
EXCEPTION WHEN duplicate_column THEN NULL;
END $$;

DO $$ BEGIN
    ALTER TABLE replenishment_config ADD COLUMN lead_time_days INTEGER NOT NULL DEFAULT 4;
EXCEPTION WHEN duplicate_column THEN NULL;
END $$;

DO $$ BEGIN
    ALTER TABLE replenishment_config ADD COLUMN service_z DOUBLE PRECISION NOT NULL DEFAULT 1.65;
EXCEPTION WHEN duplicate_column THEN NULL;
END $$;

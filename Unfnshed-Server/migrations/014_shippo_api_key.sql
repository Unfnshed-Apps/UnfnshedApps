-- Add Shippo API key to the settings table (shared single-row config)
DO $$ BEGIN
    ALTER TABLE shopify_settings ADD COLUMN shippo_api_key TEXT DEFAULT '';
EXCEPTION WHEN duplicate_column THEN NULL;
END $$;

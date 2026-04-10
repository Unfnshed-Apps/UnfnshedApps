-- Add ship-from address columns to shopify_settings (used by Shippo rate shopping)

DO $$ BEGIN
    ALTER TABLE shopify_settings ADD COLUMN ship_from_name TEXT DEFAULT '';
EXCEPTION WHEN duplicate_column THEN NULL;
END $$;

DO $$ BEGIN
    ALTER TABLE shopify_settings ADD COLUMN ship_from_street1 TEXT DEFAULT '';
EXCEPTION WHEN duplicate_column THEN NULL;
END $$;

DO $$ BEGIN
    ALTER TABLE shopify_settings ADD COLUMN ship_from_street2 TEXT DEFAULT '';
EXCEPTION WHEN duplicate_column THEN NULL;
END $$;

DO $$ BEGIN
    ALTER TABLE shopify_settings ADD COLUMN ship_from_city TEXT DEFAULT '';
EXCEPTION WHEN duplicate_column THEN NULL;
END $$;

DO $$ BEGIN
    ALTER TABLE shopify_settings ADD COLUMN ship_from_state TEXT DEFAULT '';
EXCEPTION WHEN duplicate_column THEN NULL;
END $$;

DO $$ BEGIN
    ALTER TABLE shopify_settings ADD COLUMN ship_from_zip TEXT DEFAULT '';
EXCEPTION WHEN duplicate_column THEN NULL;
END $$;

DO $$ BEGIN
    ALTER TABLE shopify_settings ADD COLUMN ship_from_country TEXT DEFAULT 'US';
EXCEPTION WHEN duplicate_column THEN NULL;
END $$;

DO $$ BEGIN
    ALTER TABLE shopify_settings ADD COLUMN ship_from_phone TEXT DEFAULT '';
EXCEPTION WHEN duplicate_column THEN NULL;
END $$;

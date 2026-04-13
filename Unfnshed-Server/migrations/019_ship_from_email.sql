-- Shippo requires an email on the sender address for label purchase.
DO $$ BEGIN
    ALTER TABLE shopify_settings ADD COLUMN ship_from_email TEXT DEFAULT '';
EXCEPTION WHEN duplicate_column THEN NULL;
END $$;

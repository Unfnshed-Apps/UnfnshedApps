-- Split the single shippo_api_key column into separate test/live key fields
-- with an explicit toggle for which one is active. The old shippo_api_key
-- column is intentionally NOT dropped so a rollback to pre-017 code still
-- finds the column it expects; new code reads only the new columns.

DO $$ BEGIN
    ALTER TABLE shopify_settings ADD COLUMN shippo_test_key TEXT DEFAULT '';
EXCEPTION WHEN duplicate_column THEN NULL;
END $$;

DO $$ BEGIN
    ALTER TABLE shopify_settings ADD COLUMN shippo_live_key TEXT DEFAULT '';
EXCEPTION WHEN duplicate_column THEN NULL;
END $$;

DO $$ BEGIN
    ALTER TABLE shopify_settings ADD COLUMN shippo_use_live BOOLEAN DEFAULT FALSE;
EXCEPTION WHEN duplicate_column THEN NULL;
END $$;

-- Backfill from existing shippo_api_key based on key prefix.
-- Test keys start with shippo_test_; live keys start with shippo_live_.
UPDATE shopify_settings
SET shippo_test_key = shippo_api_key
WHERE shippo_api_key IS NOT NULL
  AND shippo_api_key <> ''
  AND shippo_api_key LIKE 'shippo\_test\_%' ESCAPE '\'
  AND (shippo_test_key IS NULL OR shippo_test_key = '');

UPDATE shopify_settings
SET shippo_live_key = shippo_api_key
WHERE shippo_api_key IS NOT NULL
  AND shippo_api_key <> ''
  AND shippo_api_key LIKE 'shippo\_live\_%' ESCAPE '\'
  AND (shippo_live_key IS NULL OR shippo_live_key = '');

-- Catch-all: if a value exists that matches neither prefix, store it in the
-- test field with use_live=false. This is the safe default — anything we
-- don't recognize gets treated as test mode rather than potentially
-- charging real money.
UPDATE shopify_settings
SET shippo_test_key = shippo_api_key
WHERE shippo_api_key IS NOT NULL
  AND shippo_api_key <> ''
  AND shippo_api_key NOT LIKE 'shippo\_test\_%' ESCAPE '\'
  AND shippo_api_key NOT LIKE 'shippo\_live\_%' ESCAPE '\'
  AND (shippo_test_key IS NULL OR shippo_test_key = '')
  AND (shippo_live_key IS NULL OR shippo_live_key = '');

-- Track purchased shipping labels (Shippo transactions).
-- Each row is the receipt for a label purchase and ties back to an order.

CREATE TABLE IF NOT EXISTS shipping_labels (
    id SERIAL PRIMARY KEY,
    order_id INTEGER NOT NULL REFERENCES shopify_orders(id) ON DELETE CASCADE,
    rate_id TEXT NOT NULL,
    transaction_id TEXT,
    tracking_number TEXT,
    carrier TEXT,
    service TEXT,
    label_url TEXT,
    amount NUMERIC(10,2),
    test_mode BOOLEAN NOT NULL DEFAULT TRUE,
    status TEXT NOT NULL DEFAULT 'purchased',
    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_shipping_labels_order
    ON shipping_labels(order_id);

-- Safety toggle: when FALSE (default), the fulfill endpoint skips the
-- Shopify API call so test runs don't push tracking to real customers.
DO $$ BEGIN
    ALTER TABLE shopify_settings
        ADD COLUMN push_fulfillments_to_shopify BOOLEAN DEFAULT FALSE;
EXCEPTION WHEN duplicate_column THEN NULL;
END $$;

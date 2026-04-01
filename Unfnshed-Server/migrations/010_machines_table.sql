-- Centralized machine registry for CNC machines.
-- Machines are managed in Unfnest and selected in UnfnCNC.

CREATE TABLE IF NOT EXISTS machines (
    id SERIAL PRIMARY KEY,
    name TEXT NOT NULL UNIQUE,
    active BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

-- Widen claimed_by columns so machine names aren't truncated
ALTER TABLE nesting_sheets ALTER COLUMN claimed_by TYPE VARCHAR(100);
ALTER TABLE sheet_bundles ALTER COLUMN claimed_by TYPE VARCHAR(100);
ALTER TABLE machine_active_pallets ALTER COLUMN machine_letter TYPE VARCHAR(100);

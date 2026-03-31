-- Scope mating pairs to products so the same components can have
-- different mating configurations in different products.

-- Add product_sku column (nullable first for the ALTER, then enforce NOT NULL)
ALTER TABLE component_mating_pairs
    ADD COLUMN product_sku TEXT;

-- Set any existing rows to empty string (table is currently empty, but safe)
UPDATE component_mating_pairs SET product_sku = '' WHERE product_sku IS NULL;

-- Now make it NOT NULL and add FK
ALTER TABLE component_mating_pairs
    ALTER COLUMN product_sku SET NOT NULL,
    ADD CONSTRAINT component_mating_pairs_product_sku_fkey
        FOREIGN KEY (product_sku) REFERENCES products(sku) ON DELETE CASCADE;

-- Replace the old unique constraint with a product-scoped one
ALTER TABLE component_mating_pairs
    DROP CONSTRAINT component_mating_pairs_pocket_component_id_mating_componen_key,
    ADD CONSTRAINT component_mating_pairs_product_pair_unique
        UNIQUE(product_sku, pocket_component_id, mating_component_id, pocket_index);

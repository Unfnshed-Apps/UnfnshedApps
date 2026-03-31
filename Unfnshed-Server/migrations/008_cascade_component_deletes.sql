-- Add ON DELETE CASCADE to all component_definitions FK references
-- except product_components (which should block deletion).
--
-- This allows deleting a component to cleanly remove all dependent
-- records: inventory, transactions, sheet parts, mating pairs, etc.
-- Product usage is the only thing that blocks component deletion.

-- component_inventory
ALTER TABLE component_inventory
    DROP CONSTRAINT component_inventory_component_id_fkey,
    ADD CONSTRAINT component_inventory_component_id_fkey
        FOREIGN KEY (component_id) REFERENCES component_definitions(id) ON DELETE CASCADE;

-- inventory_transactions
ALTER TABLE inventory_transactions
    DROP CONSTRAINT inventory_transactions_component_id_fkey,
    ADD CONSTRAINT inventory_transactions_component_id_fkey
        FOREIGN KEY (component_id) REFERENCES component_definitions(id) ON DELETE CASCADE;

-- sheet_parts
ALTER TABLE sheet_parts
    DROP CONSTRAINT sheet_parts_component_id_fkey,
    ADD CONSTRAINT sheet_parts_component_id_fkey
        FOREIGN KEY (component_id) REFERENCES component_definitions(id) ON DELETE CASCADE;

-- sheet_part_placements
ALTER TABLE sheet_part_placements
    DROP CONSTRAINT sheet_part_placements_component_id_fkey,
    ADD CONSTRAINT sheet_part_placements_component_id_fkey
        FOREIGN KEY (component_id) REFERENCES component_definitions(id) ON DELETE CASCADE;

-- damaged_parts
ALTER TABLE damaged_parts
    DROP CONSTRAINT damaged_parts_component_id_fkey,
    ADD CONSTRAINT damaged_parts_component_id_fkey
        FOREIGN KEY (component_id) REFERENCES component_definitions(id) ON DELETE CASCADE;

-- component_mating_pairs (both FK columns)
ALTER TABLE component_mating_pairs
    DROP CONSTRAINT component_mating_pairs_pocket_component_id_fkey,
    ADD CONSTRAINT component_mating_pairs_pocket_component_id_fkey
        FOREIGN KEY (pocket_component_id) REFERENCES component_definitions(id) ON DELETE CASCADE;

ALTER TABLE component_mating_pairs
    DROP CONSTRAINT component_mating_pairs_mating_component_id_fkey,
    ADD CONSTRAINT component_mating_pairs_mating_component_id_fkey
        FOREIGN KEY (mating_component_id) REFERENCES component_definitions(id) ON DELETE CASCADE;

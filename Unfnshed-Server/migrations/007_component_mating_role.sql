-- Add mating_role to component_definitions so each component can be tagged
-- as tab, receiver, or neutral directly (replaces mating_pairs-based inference).
ALTER TABLE component_definitions
    ADD COLUMN IF NOT EXISTS mating_role VARCHAR(10) NOT NULL DEFAULT 'neutral';

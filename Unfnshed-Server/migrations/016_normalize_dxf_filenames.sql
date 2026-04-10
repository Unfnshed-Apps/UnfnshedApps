-- Normalize component_definitions.dxf_filename to the underscore convention
-- used by server disk storage. Before this migration, 47 of 51 rows had
-- space-named values that only "worked" because file_storage._sanitize_filename
-- rewrote them on every lookup. After this migration the DB matches disk and
-- no implicit normalization is needed for normal traffic.

UPDATE component_definitions
SET dxf_filename = REPLACE(REPLACE(dxf_filename, ' ', '_'), '+', '_')
WHERE dxf_filename LIKE '% %' OR dxf_filename LIKE '%+%';

-- Collapse any resulting consecutive underscores (e.g. "Stools_+_Side" -> "Stools_Side").
UPDATE component_definitions
SET dxf_filename = REGEXP_REPLACE(dxf_filename, '_+', '_', 'g')
WHERE dxf_filename LIKE '%\_\_%' ESCAPE '\';

-- Initialises the Postgres database on first boot.
-- pgvector ships extensions in the image; we just enable it.
CREATE EXTENSION IF NOT EXISTS vector;

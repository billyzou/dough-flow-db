-- Marks this database as the demo one. Only postgres-demo runs this file (from
-- docker-entrypoint-initdb.d, after sql/schema.sql). demo/generate.py won't write to a database
-- without it, and the demo dashboard won't show one.
CREATE TABLE ops.demo_marker (created_at TIMESTAMPTZ NOT NULL DEFAULT NOW());
INSERT INTO ops.demo_marker DEFAULT VALUES;

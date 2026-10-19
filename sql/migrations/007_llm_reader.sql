-- Read-only login for the dashboard's Ask tab: the local model's SQL runs as this role, so it can
-- read gold and nothing else, and can't change anything even if it tries. Run as the dbt user
-- (DB_USER), which owns gold: the default privileges below cover the views dbt rebuilds every run.
-- The password is LLM_DB_PASSWORD from .env, passed in so it never sits in this file:
-- docker compose exec -T postgres sh -c 'psql -v ON_ERROR_STOP=1 -v pw="$1" -U $POSTGRES_USER -d $POSTGRES_DB' _ "$(sed -n 's/^LLM_DB_PASSWORD=//p' .env)" < sql/migrations/007_llm_reader.sql

BEGIN;

CREATE ROLE llm_reader LOGIN PASSWORD :'pw' CONNECTION LIMIT 3;
-- set again by the dashboard on every connection; here too, so the role is safe on its own
ALTER ROLE llm_reader SET default_transaction_read_only = on;
ALTER ROLE llm_reader SET statement_timeout = '10s';

GRANT USAGE ON SCHEMA gold TO llm_reader;
GRANT SELECT ON ALL TABLES IN SCHEMA gold TO llm_reader;
ALTER DEFAULT PRIVILEGES IN SCHEMA gold GRANT SELECT ON TABLES TO llm_reader;

COMMIT;

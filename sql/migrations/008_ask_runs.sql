-- One row per Ask Dough Bot question, so the dashboard can say how long answers usually take.
-- Timing only: the question and answer are not stored.
-- docker compose exec -T postgres sh -c 'psql -v ON_ERROR_STOP=1 -U $POSTGRES_USER -d $POSTGRES_DB' < sql/migrations/008_ask_runs.sql

CREATE TABLE IF NOT EXISTS ops.ask_runs (
    run_id   SERIAL PRIMARY KEY,
    asked_at TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    seconds  NUMERIC(7, 1) NOT NULL,
    steps    INT          NOT NULL,
    success  BOOLEAN      NOT NULL
);

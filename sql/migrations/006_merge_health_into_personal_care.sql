-- Health & Wellness (29) is folded into Personal Care (9) (2026-10-17). The seeds carry the
-- mapping change; this moves the hand-picked overrides to match. Run before the next dbt seed.
-- docker compose exec -T postgres sh -c 'psql -v ON_ERROR_STOP=1 -U $POSTGRES_USER -d $POSTGRES_DB' < sql/migrations/006_merge_health_into_personal_care.sql

UPDATE bronze.category_overrides SET category_id = 9 WHERE category_id = 29;

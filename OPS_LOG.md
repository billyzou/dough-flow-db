# Ops log

Manual fixes, backfills and one-off scripts run against the live database, newest first.
Anything not done by the daily DAGs goes here: what broke, what was run, how it was checked.

---

## 2026-11-23: Filled the Nov 17–22 outage gap in net worth

**Why:** The Mac was down Nov 17–22 (power outage, then a full disk stopped OrbStack). Plaid can't
return past balances, so `gold.daily_balances` drew a straight line from the Nov 16 snapshot to
the Nov 23 one, an identical drop every day, which looked like a cliff. The drop itself was real
(SPY −8.9% over the gap).

**Ran:**
- Price backfill, since prices had last been loaded Oct 16 (the script isn't in a DAG):
  `docker exec dough-flow-db-airflow-scheduler-1 python /opt/airflow/scripts/backfill_prices.py`
- Changed `models/gold/daily_balances.sql`: during outages only, linked investment accounts
  follow SPY's close instead of a straight line, still landing exactly on each real snapshot. An
  outage is a gap with no successful run in `ops.pipeline_runs` on any day inside it (gaps before
  the log starts on 2026-05-10 never count). Every other gap stays a straight line. Added
  `ops.pipeline_runs` as a dbt source for this.
- `dbt run --select daily_balances+` in the Airflow scheduler container.

**Checked:** Compared every day against a plain straight-line fill. The only differences are
linked investment accounts in the four outages: Jul 14–18, Aug 11–16, Aug 21–Sep 10, Nov 16–23
(the first three were also reshaped by this change). Real snapshot days are unchanged;
`dbt test` 58/58 pass.

**Follow-up:** Prices only load when the backfill script is run by hand. A future gap falls back to a
straight line unless it's run first, or until it's added to a daily DAG.

---

## 2026-11-22: Rebuilt gold views after the outage

**Why:** On restart after the Nov 17 outage, two catch-up `dbt_run` DAG runs collided on dbt's
`__dbt_backup` renames and dropped the gold views.

**Ran:** A manual `dbt run`, then set `max_active_runs=1` on the `dbt_run` DAG (commit 091c8fc).

---

## 2026-10-11: Database backup before the medallion restructure

**Why:** Safety copy before moving the warehouse to bronze/silver/gold (commit 9abc912).

**Ran:** A `pg_dump` to `backups/dough_flow_db_pre_medallion_20261011.dump`.

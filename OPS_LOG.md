# Ops log

Manual fixes, backfills and one-off scripts run against the live database, newest first.
Anything not done by the daily DAGs goes here: what broke, what was run, how it was checked.

---

## 2026-11-26: Plaid afternoon-freshness test (read-only)

**Why:** To see whether a second, post-market-close Plaid pull would give fresher investment
balances and prices than the 10:00 UTC ingest, before adding one to the DAGs.

**Ran:** `scripts/plaid_freshness_test.py` in the Airflow scheduler container. It calls Plaid
`/accounts/get` and `/investments/holdings/get` and compares them with the latest bronze snapshot.
It writes nothing to the database. Dry run on 2026-11-26 (market holiday). The real test is
scheduled for 2026-11-30 21:30 UTC by a one-shot LaunchAgent (`com.billyzou.plaid-freshness-test`,
outside the repo) that pushes the summary via ntfy and then removes itself.

**Checked:** Dry run: 1/10 investment balances changed and 3/22 holdings had a newer price date
than the morning pull, all at Fidelity. Plaid does refresh at least one institution after 10:00 UTC.

---

## 2026-11-26: Recategorized Amex Platinum statement credits

**Why:** The card's statement credits (digital entertainment, Walmart+, Uber One, Resy, hotel, CLEAR,
Lululemon, Saks, Pay with Points) were spread across Housing & Bills, Shopping, Transport,
Entertainment and Transfers depending on how Plaid or the CSV backfill labelled them, so they didn't
offset the charges they pay for, and the CLEAR credit was left out of spending entirely.

**Ran:**
- Changed `models/silver/fct_transactions.sql`: a description rule files each credit under the
  category of what it pays for (Entertainment, Shopping, Transport, Food & Groceries, Travel).
  Manual overrides still win; the rule wins over Plaid's labels. Plaid's Walmart+ credits arrive
  named just "Walmart" and already land in Shopping, so they're untouched.
- `dbt run --select fct_transactions+` in the Airflow scheduler container.

**Checked:** Every credit description now sits in a single category; per-category before/after
totals differ only by the moved credits (the moves net to zero apart from the CLEAR credit leaving
Transfers); no uncategorized rows; `dbt test` 58/58 pass.

**Not changed:** `ANNUAL HOTEL CREDIT` (Housing & Bills) and `PAYYOURSELFBACK CREDIT` (Shopping) are
from other cards; the subscription charges themselves are also inconsistent in the CSV backfill era
(e.g. Disney+ and YouTube Premium under Shopping or Housing & Bills).

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

**Ran:** A manual `dbt seed` + `dbt run` (the same command as the DAG) in the Airflow scheduler
container, then set `max_active_runs=1` on the `dbt_run` DAG (commit 091c8fc). Also marked the
stuck `scheduled__2026-11-16T10:00:00+00:00` run (left "running" at `wait_for_ingest` by the outage)
as failed.

**Checked:** dbt PASS=34 ERROR=0; all gold views present again; Streamlit loads (HTTP 200); no
leftover `__dbt_backup`/`__dbt_tmp` relations; Airflow scheduler reports `max_active_runs = 1`.
The DAG's own runs for Nov 17 and Nov 21 stay recorded as failed; the next scheduled run confirms the fix.

---

## 2026-10-11: Database backup before the medallion restructure

**Why:** Safety copy before moving the warehouse to bronze/silver/gold (commit 9abc912).

**Ran:** A `pg_dump` to `backups/dough_flow_db_pre_medallion_20261011.dump`.

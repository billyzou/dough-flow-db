#!/usr/bin/env bash
# Rebuilds the demo database at start and then every morning at 6:30am Pacific (13:30 UTC), so its
# data runs through yesterday: the gold views compare against current_date. Runs in the
# demo-pipeline container, which only knows the demo database's credentials.
set -u
DBT_ARGS="--project-dir /demo-dbt --profiles-dir /demo-dbt --target-path /tmp/dbt_target"

while true; do
    if python /demo/generate.py && dbt --log-path /tmp/dbt_logs seed $DBT_ARGS && dbt --log-path /tmp/dbt_logs run $DBT_ARGS; then
        echo "demo refresh done $(date -u)"
    else
        echo "demo refresh failed $(date -u); keeping the previous data"
    fi
    wait=$(( (48600 - $(date -u +%s) % 86400 + 86400) % 86400 ))
    sleep $(( wait > 0 ? wait : 86400 ))
done

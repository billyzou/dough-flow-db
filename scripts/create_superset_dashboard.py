#!/usr/bin/env python3
"""
Creates the Personal Finance Superset dashboard via the Superset REST API.

Run from repo root:
  .venv/bin/python3 scripts/create_superset_dashboard.py

Re-running creates duplicate charts/dashboard — delete old ones via the UI first.
"""

import json
import os
import uuid

import requests

BASE_URL = os.getenv("SUPERSET_URL", "http://192.168.2.117:8088")
ADMIN_USER = os.getenv("SUPERSET_USER", "admin")
ADMIN_PASS = os.getenv("SUPERSET_PASS", "admin")


def uid():
    return uuid.uuid4().hex[:12]


def login(session):
    r = session.post(f"{BASE_URL}/api/v1/security/login", json={
        "username": ADMIN_USER,
        "password": ADMIN_PASS,
        "provider": "db",
        "refresh": True,
    })
    r.raise_for_status()
    session.headers["Authorization"] = f"Bearer {r.json()['access_token']}"


def refresh_csrf(session):
    r = session.get(f"{BASE_URL}/api/v1/security/csrf_token/")
    r.raise_for_status()
    session.headers.update({"X-CSRFToken": r.json()["result"], "Referer": BASE_URL})


def get_dataset_id(session, name):
    q = json.dumps({"filters": [{"col": "table_name", "opr": "eq", "value": name}]})
    r = session.get(f"{BASE_URL}/api/v1/dataset/", params={"q": q})
    r.raise_for_status()
    results = r.json()["result"]
    if not results:
        raise ValueError(f"Dataset '{name}' not found — register it in Superset first")
    return results[0]["id"]


def sql_metric(sql, label):
    return {"expressionType": "SQL", "sqlExpression": sql, "label": label, "optionName": uid()}


def sql_filter(expr):
    return {"expressionType": "SQL", "sqlExpression": expr, "clause": "WHERE", "filterOptionName": uid()}


def simple_filter(col, val):
    return {
        "expressionType": "SIMPLE",
        "subject": col,
        "operator": "==",
        "comparator": val,
        "clause": "WHERE",
        "filterOptionName": uid(),
    }


def create_chart(session, name, viz_type, ds_id, params):
    params["viz_type"] = viz_type
    params["datasource"] = f"{ds_id}__table"
    r = session.post(f"{BASE_URL}/api/v1/chart/", json={
        "slice_name": name,
        "viz_type": viz_type,
        "datasource_id": ds_id,
        "datasource_type": "table",
        "params": json.dumps(params),
    })
    if not r.ok:
        raise RuntimeError(f"Failed to create '{name}': {r.status_code} {r.text[:300]}")
    chart_id = r.json()["id"]
    print(f"  ✓ {name} (id={chart_id})")
    return chart_id


def build_layout(chart_ids):
    """
    Row 1: MTD Spend (w=6)       | MTD Income (w=6)
    Row 2: Spend by Category (w=5) | Top Merchants (w=7)
    Row 3: Monthly Spend by Category (w=12)
    Row 4: Net Cash Flow (w=12)

    chart_ids order: spend, income, by_category, monthly_trend, top_merchants, net_cash_flow
    """
    pos = {
        "DASHBOARD_VERSION_KEY": "v2",
        "ROOT_ID": {"type": "ROOT", "id": "ROOT_ID", "children": ["GRID_ID"]},
        "GRID_ID": {
            "type": "GRID", "id": "GRID_ID",
            "children": ["ROW-1", "ROW-2", "ROW-3", "ROW-4"],
            "parents": ["ROOT_ID"],
        },
    }

    def add_chart(cid, width, height):
        key = f"CHART-{cid}"
        pos[key] = {
            "type": "CHART", "id": key, "children": [],
            "meta": {"chartId": cid, "width": width, "height": height},
        }
        return key

    def add_row(row_id, child_keys):
        pos[row_id] = {
            "type": "ROW", "id": row_id, "children": child_keys,
            "meta": {"background": "BACKGROUND_TRANSPARENT"},
            "parents": ["ROOT_ID", "GRID_ID"],
        }

    add_row("ROW-1", [add_chart(chart_ids[0], 6, 36), add_chart(chart_ids[1], 6, 36)])
    add_row("ROW-2", [add_chart(chart_ids[2], 5, 70), add_chart(chart_ids[4], 7, 70)])
    add_row("ROW-3", [add_chart(chart_ids[3], 12, 80)])
    add_row("ROW-4", [add_chart(chart_ids[5], 12, 70)])
    return pos


def main():
    s = requests.Session()
    s.headers["Content-Type"] = "application/json"

    print("Authenticating...")
    login(s)
    refresh_csrf(s)

    print("Fetching dataset IDs...")
    ds = {n: get_dataset_id(s, n) for n in [
        "monthly_cash_flow", "monthly_spending", "category_trends", "top_merchants",
    ]}
    for name, did in ds.items():
        print(f"  {name}: {did}")

    current_month = sql_filter("month = date_trunc('month', current_date)::date")

    print("\nCreating charts...")
    chart_ids = []

    # 0: MTD Spend
    chart_ids.append(create_chart(s, "MTD Spend", "big_number_total", ds["monthly_cash_flow"], {
        "metric": sql_metric("ABS(SUM(total))", "MTD Spend"),
        "adhoc_filters": [current_month, simple_filter("category_type", "expense")],
        "y_axis_format": "$,.0f",
        "subheader": "this month",
    }))

    # 1: MTD Income
    chart_ids.append(create_chart(s, "MTD Income", "big_number_total", ds["monthly_cash_flow"], {
        "metric": sql_metric("SUM(total)", "MTD Income"),
        "adhoc_filters": [current_month, simple_filter("category_type", "income")],
        "y_axis_format": "$,.0f",
        "subheader": "this month",
    }))

    # 2: Spend by Category (pie, current month)
    chart_ids.append(create_chart(s, "Spend by Category", "pie", ds["monthly_spending"], {
        "metric": sql_metric("ABS(SUM(total))", "Total Spent"),
        "groupby": ["category_name"],
        "adhoc_filters": [current_month],
        "label_type": "key_percent",
        "show_legend": True,
        "donut": False,
    }))

    # 3: Monthly Spend by Category (stacked bar, last 12 months)
    chart_ids.append(create_chart(s, "Monthly Spend by Category", "echarts_timeseries_bar", ds["category_trends"], {
        "metrics": [sql_metric("ABS(SUM(total))", "Total Spent")],
        "groupby": ["category_name"],
        "x_axis": "month",
        "adhoc_filters": [],
        "stack": True,
        "y_axis_format": "$,.0f",
        "rich_tooltip": True,
    }))

    # 4: Top Merchants (table)
    chart_ids.append(create_chart(s, "Top Merchants", "table", ds["top_merchants"], {
        "all_columns": ["merchant", "total_spent", "transaction_count"],
        "metrics": [],
        "groupby": [],
        "adhoc_filters": [],
        "row_limit": 20,
        "page_length": 20,
    }))

    # 5: Net Cash Flow (grouped bar by month)
    chart_ids.append(create_chart(s, "Net Cash Flow", "echarts_timeseries_bar", ds["monthly_cash_flow"], {
        "metrics": [sql_metric("SUM(total)", "Total")],
        "groupby": ["category_type"],
        "x_axis": "month",
        "adhoc_filters": [],
        "stack": False,
        "y_axis_format": "$,.0f",
        "rich_tooltip": True,
    }))

    print("\nCreating dashboard...")
    position = build_layout(chart_ids)
    r = s.post(f"{BASE_URL}/api/v1/dashboard/", json={
        "dashboard_title": "Personal Finance",
        "published": True,
        "position_json": json.dumps(position),
    })
    if not r.ok:
        raise RuntimeError(f"Failed to create dashboard: {r.status_code} {r.text[:300]}")
    dash_id = r.json()["id"]
    print(f"  ✓ Personal Finance (id={dash_id})")
    print(f"\nDone: {BASE_URL}/superset/dashboard/{dash_id}/")


if __name__ == "__main__":
    main()

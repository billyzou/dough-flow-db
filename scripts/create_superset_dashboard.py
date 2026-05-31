#!/usr/bin/env python3
"""
Creates the Personal Finance Superset dashboard via the Superset REST API.

Run from repo root:
  .venv/bin/python3 scripts/create_superset_dashboard.py

Re-running creates duplicate charts/dashboard — delete old ones via the UI first,
or use the --delete flag to delete existing dashboard+charts by title before recreating:
  .venv/bin/python3 scripts/create_superset_dashboard.py --delete
"""

import argparse
import json
import os
import uuid

import requests

BASE_URL = os.getenv("SUPERSET_URL", "http://192.168.2.117:8088")
ADMIN_USER = os.getenv("SUPERSET_USER", "admin")
ADMIN_PASS = os.getenv("SUPERSET_PASS", "admin")
DASHBOARD_TITLE = "Personal Finance"


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


def delete_existing(session):
    # Delete dashboards matching the title
    q = json.dumps({"filters": [{"col": "dashboard_title", "opr": "ChartSearch", "value": DASHBOARD_TITLE}]})
    r = session.get(f"{BASE_URL}/api/v1/dashboard/", params={"q": q})
    r.raise_for_status()
    for d in r.json().get("result", []):
        if d["dashboard_title"] == DASHBOARD_TITLE:
            session.delete(f"{BASE_URL}/api/v1/dashboard/{d['id']}")
            print(f"  Deleted dashboard id={d['id']}")

    # Delete all charts (fetch up to 100)
    r = session.get(f"{BASE_URL}/api/v1/chart/", params={"q": json.dumps({"page_size": 100})})
    r.raise_for_status()
    for c in r.json().get("result", []):
        session.delete(f"{BASE_URL}/api/v1/chart/{c['id']}")
        print(f"  Deleted chart id={c['id']} '{c['slice_name']}'")
    refresh_csrf(session)


def build_layout(chart_ids):
    """
    Row 1: YTD Cumulative (w=6)          | MTD Cumulative (w=6)
    Row 2: YTD by Category (w=6)         | MTD by Category (w=6)
    Row 3: (empty w=6)                   | MTD % of Total (w=6)
    Row 4: Monthly Spend by Category (w=12)
    Row 5: Net Cash Flow (w=8)           | Top Merchants (w=4)

    chart_ids order:
      0: YTD Cumulative
      1: MTD Cumulative
      2: MTD by Category
      3: Top Merchants
      4: Monthly Spend by Category
      5: Net Cash Flow
      6: YTD by Category
      7: MTD % of Total
    """
    glossary_md = """## Category Glossary

| Category | What's included |
|---|---|
| **Bills & Utilities** | Recurring fixed bills — phone, internet, cable, insurance, utilities, bank fees, government services |
| **Entertainment** | Streaming services, concerts, events, gifts, donations |
| **Food & Groceries** | All food spend — groceries (Whole Foods, Trader Joe's, Nijiya), restaurants, bars, cafés, food delivery |
| **Health & Wellness** | Gym memberships, fitness classes, wellness services |
| **Housing** | Rent, home improvement, maintenance, repairs |
| **Loan Payments** | Mortgage payments, credit card payments, any debt service |
| **Personal Care** | Medical, pharmacy, haircuts, personal hygiene services |
| **Shopping** | General retail — clothing, electronics, household goods, department stores, online purchases |
| **Transport** | Rideshare (Uber, Lyft), public transit, gas, parking, car-related expenses |
| **Travel** | Flights, hotels, travel agencies — trips away from home |
| **Transfers** | Internal transfers between your own accounts — excluded from all spend charts |
| **Income** | All inflows — paychecks, reimbursements, interest, any money coming in |

---

**Notes**
- Transfers are excluded from all spend and income totals to avoid double-counting.
- Loan Payments includes both mortgage and credit card payments. Credit card purchases are captured in their respective categories at transaction time.
- 12-mo Avg on the MTD chart is a rolling average of the last 12 fully completed calendar months.
- Prior Year columns compare the same time period one year ago.
"""
    pos = {
        "DASHBOARD_VERSION_KEY": "v2",
        "ROOT_ID": {"type": "ROOT", "id": "ROOT_ID", "children": ["GRID_ID"]},
        "GRID_ID": {
            "type": "GRID", "id": "GRID_ID",
            "children": ["ROW-1", "ROW-GLOSSARY", "ROW-2", "ROW-3", "ROW-4", "ROW-5"],
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

    add_row("ROW-1", [add_chart(chart_ids[0], 6, 50), add_chart(chart_ids[1], 6, 50)])

    # Native markdown glossary — sits between cumulative charts and category tables
    pos["MARKDOWN-GLOSSARY"] = {
        "type": "MARKDOWN", "id": "MARKDOWN-GLOSSARY", "children": [],
        "parents": ["ROOT_ID", "GRID_ID", "ROW-GLOSSARY"],
        "meta": {"width": 12, "height": 100, "code": glossary_md},
    }
    add_row("ROW-GLOSSARY", ["MARKDOWN-GLOSSARY"])

    add_row("ROW-2", [add_chart(chart_ids[6], 6, 62), add_chart(chart_ids[2], 6, 62)])
    add_row("ROW-3", [add_chart(chart_ids[4], 12, 80)])
    add_row("ROW-4", [add_chart(chart_ids[7], 12, 80)])
    add_row("ROW-5", [add_chart(chart_ids[5], 8, 70), add_chart(chart_ids[3], 4, 70)])
    return pos


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--delete", action="store_true", help="Delete existing dashboard and charts before recreating")
    args = parser.parse_args()

    s = requests.Session()
    s.headers["Content-Type"] = "application/json"

    print("Authenticating...")
    login(s)
    refresh_csrf(s)

    if args.delete:
        print("\nDeleting existing charts and dashboard...")
        delete_existing(s)

    print("Fetching dataset IDs...")
    ds = {n: get_dataset_id(s, n) for n in [
        "monthly_cash_flow", "monthly_spending", "category_trends", "top_merchants",
        "daily_cumulative_ytd", "daily_cumulative_mtd", "mtd_avg_reference",
        "category_comparison",
    ]}
    for name, did in ds.items():
        print(f"  {name}: {did}")

    current_month = sql_filter("month = date_trunc('month', current_date)::date")
    mtd_date = sql_filter("date >= date_trunc('month', current_date)::date")

    print("\nCreating charts...")
    chart_ids = []

    expense_only = simple_filter("category_type", "expense")

    # 0: YTD cumulative spend — this year vs prior year
    chart_ids.append(create_chart(s, "YTD Cumulative Spend", "echarts_timeseries_line", ds["daily_cumulative_ytd"], {
        "metrics": [sql_metric("SUM(cumulative_total)", "Spend")],
        "groupby": ["year"],
        "x_axis": "date",
        "adhoc_filters": [expense_only],
        "y_axis_format": "$,.0f",
        "rich_tooltip": True,
        "tooltipTimeFormat": "%b %d",
        "x_axis_time_format": "%b %d",
        "smooth": False,
    }))

    # 1: MTD cumulative spend — this month vs prior year month + 12-mo avg flat line
    chart_ids.append(create_chart(s, "MTD Cumulative Spend", "echarts_timeseries_line", ds["daily_cumulative_mtd"], {
        "metrics": [
            sql_metric("MAX(this_month)", "This Month"),
            sql_metric("MAX(prior_year_month)", "Prior Year"),
            sql_metric("MAX(avg_monthly_spend)", "12-mo Avg"),
        ],
        "groupby": [],
        "x_axis": "date",
        "adhoc_filters": [],
        "y_axis_format": "$,.0f",
        "rich_tooltip": True,
        "tooltipTimeFormat": "%b %d",
        "x_axis_time_format": "%b %d",
        "smooth": False,
    }))

    # 2: MTD Spend by Category (table)
    chart_ids.append(create_chart(s, "MTD Spend by Category", "table", ds["category_comparison"], {
        "all_columns": ["category_name", "this_month", "last_year_month", "monthly_avg_12mo"],
        "metrics": [],
        "groupby": [],
        "adhoc_filters": [],
        "row_limit": 50,
        "page_length": 50,
        "column_config": {
            "this_month":        {"d3NumberFormat": "$,.0f", "columnWidth": 120, "showCellBars": False},
            "last_year_month":   {"d3NumberFormat": "$,.0f", "columnWidth": 120, "showCellBars": False},
            "monthly_avg_12mo":  {"d3NumberFormat": "$,.0f", "columnWidth": 120, "showCellBars": False},
        },
        "order_by_cols": [json.dumps(["this_month", False])],
    }))

    # 3: Top Merchants (table)
    chart_ids.append(create_chart(s, "Top Merchants", "table", ds["top_merchants"], {
        "all_columns": ["merchant", "total_spent", "transaction_count"],
        "metrics": [],
        "groupby": [],
        "adhoc_filters": [],
        "row_limit": 20,
        "page_length": 20,
        "column_config": {
            "total_spent": {"d3NumberFormat": "$,.2f", "columnWidth": 120, "showCellBars": False},
            "transaction_count": {"showCellBars": False},
        },
        "order_by_cols": [json.dumps(["total_spent", False])],
    }))

    # 4: Monthly Spend by Category (stacked bar, last 12 months)
    chart_ids.append(create_chart(s, "Monthly Spend by Category", "echarts_timeseries_bar", ds["category_trends"], {
        "metrics": [sql_metric("ABS(SUM(total))", "Total Spent")],
        "groupby": ["category_name"],
        "x_axis": "month",
        "adhoc_filters": [],
        "stack": True,
        "y_axis_format": "$,.0f",
        "rich_tooltip": True,
        "tooltipTimeFormat": "%b %Y",
        "x_axis_time_format": "%b %Y",
        "legendOrientation": "right",
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
        "tooltipTimeFormat": "%b %Y",
        "x_axis_time_format": "%b %Y",
    }))

    # 6: YTD Spend by Category (table)
    chart_ids.append(create_chart(s, "YTD Spend by Category", "table", ds["category_comparison"], {
        "all_columns": ["category_name", "this_year", "last_year"],
        "metrics": [],
        "groupby": [],
        "adhoc_filters": [],
        "row_limit": 50,
        "page_length": 50,
        "column_config": {
            "this_year":  {"d3NumberFormat": "$,.0f", "columnWidth": 120, "showCellBars": False},
            "last_year":  {"d3NumberFormat": "$,.0f", "columnWidth": 120, "showCellBars": False},
        },
        "order_by_cols": [json.dumps(["this_year", False])],
    }))

    # 7: Monthly Spend % of Total by Category (100% stacked bar)
    chart_ids.append(create_chart(s, "Monthly Spend % by Category", "echarts_timeseries_bar", ds["category_trends"], {
        "metrics": [sql_metric("ABS(SUM(total))", "Total Spent")],
        "groupby": ["category_name"],
        "x_axis": "month",
        "adhoc_filters": [],
        "stack": "Expand",
        "y_axis_format": ".0%",
        "rich_tooltip": True,
        "tooltipTimeFormat": "%b %Y",
        "x_axis_time_format": "%b %Y",
        "legendOrientation": "right",
    }))

    # glossary text — added as a native MARKDOWN layout element, not a chart

    print("\nCreating dashboard...")
    position = build_layout(chart_ids)

    # Native filters: date range on transaction_date (targets monthly mart columns via month)
    native_filters = [
        {
            "id": f"NATIVE_FILTER_{uid()}",
            "name": "Date Range",
            "filterType": "filter_time",
            "targets": [{}],
            "defaultDataMask": {"filterState": {"value": "No filter"}},
            "controlValues": {"enableEmptyFilter": False},
            "cascadeParentIds": [],
            "scope": {
                "rootPath": ["ROOT_ID"],
                "excluded": [],
            },
            "type": "NATIVE_FILTER",
        }
    ]

    r = s.post(f"{BASE_URL}/api/v1/dashboard/", json={
        "dashboard_title": DASHBOARD_TITLE,
        "published": True,
        "position_json": json.dumps(position),
        "json_metadata": json.dumps({"native_filter_configuration": native_filters}),
    })
    if not r.ok:
        raise RuntimeError(f"Failed to create dashboard: {r.status_code} {r.text[:300]}")
    dash_id = r.json()["id"]
    print(f"  ✓ {DASHBOARD_TITLE} (id={dash_id})")
    print(f"\nDone: {BASE_URL}/superset/dashboard/{dash_id}/")


if __name__ == "__main__":
    main()

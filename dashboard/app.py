"""
Dough Flow dashboard.

Reads the dbt marts live from Postgres. Runs as the `streamlit` service in
docker-compose: http://<host>:8501
"""

import os

import altair as alt
import pandas as pd
import psycopg2
import streamlit as st

st.set_page_config(page_title='Dough Flow', layout='wide')

# Categorical palette in fixed order; categories past the 7th fold into "Other"
PALETTE = ['#2a78d6', '#eb6834', '#1baf7a', '#eda100', '#e87ba4', '#008300', '#6250d6']
OTHER = '#898781'
MAX_CATEGORIES = len(PALETTE)


@st.cache_data(ttl=600)
def query(sql):
    with psycopg2.connect(
        host=os.environ['DB_HOST'],
        port=os.environ['DB_PORT'],
        dbname=os.environ['DB_NAME'],
        user=os.environ['DB_USER'],
        password=os.environ['DB_PASSWORD'],
    ) as conn:
        return pd.read_sql(sql, conn)


def line_chart(df, x, y, color, x_format, colors):
    return alt.Chart(df).mark_line(strokeWidth=2).encode(
        x=alt.X(f'{x}:T', title=None, axis=alt.Axis(format=x_format)),
        y=alt.Y(f'{y}:Q', title=None, axis=alt.Axis(format='$,.0f')),
        color=alt.Color(f'{color}:N', title=None, scale=alt.Scale(domain=list(colors), range=list(colors.values())),
                        legend=alt.Legend(orient='bottom')),
        tooltip=[alt.Tooltip(f'{x}:T', format=x_format), alt.Tooltip(f'{color}:N'), alt.Tooltip(f'{y}:Q', format='$,.0f')],
    )


def money_table(df, columns, sort_by):
    df = df[list(columns)].sort_values(sort_by, ascending=False)
    total = df.drop(columns=df.columns[0]).sum().to_frame().T
    total.insert(0, df.columns[0], 'Total')
    df = pd.concat([df, total], ignore_index=True).rename(columns=columns)
    st.dataframe(
        df.style.format('${:,.0f}', subset=df.columns[1:]),
        hide_index=True,
        height=table_height(df),
    )


def table_height(df):
    # Tall enough to show every row (35px rows + header) so the table never scrolls
    return (len(df) + 1) * 35 + 3


def month_axis(df):
    # Label months as text so each bar sits under its own month name
    df['label'] = df['month'].map(lambda m: m.strftime('%b %Y'))
    return alt.X('label:O', title=None, sort=sorted(df['label'].unique(), key=lambda l: pd.to_datetime(l)),
                 axis=alt.Axis(labelAngle=0))


st.title('Dough Flow')

# ---------- Row 1: cumulative spend ----------
left, right = st.columns(2)

with left:
    st.subheader('YTD Cumulative Spend')
    ytd = query("""
        select date, year, cumulative_total
        from daily_cumulative_ytd
        where category_type = 'expense'
    """)
    years = sorted(ytd['year'].unique(), reverse=True)
    st.altair_chart(
        line_chart(ytd, 'date', 'cumulative_total', 'year', '%b %d',
                   dict(zip(years, [PALETTE[0], OTHER] + PALETTE[1:]))),
        use_container_width=True,
    )

with right:
    st.subheader('MTD Cumulative Spend')
    mtd = query('select date, this_month, prior_year_month, avg_monthly_spend from daily_cumulative_mtd')
    mtd = mtd.rename(columns={
        'this_month': 'This Month', 'prior_year_month': 'Prior Year', 'avg_monthly_spend': '12-mo Avg',
    }).melt('date', var_name='series', value_name='spend')
    st.altair_chart(
        line_chart(mtd, 'date', 'spend', 'series', '%b %d',
                   {'This Month': PALETTE[0], 'Prior Year': OTHER, '12-mo Avg': PALETTE[1]}),
        use_container_width=True,
    )

# ---------- Row 2: category tables ----------
categories = query('select * from category_comparison')
left, right = st.columns(2)

with left:
    st.subheader('YTD Spend by Category')
    money_table(categories, {'category_name': 'Category', 'this_year': 'This Year', 'last_year': 'Prior Year'},
                'this_year')

with right:
    st.subheader('MTD Spend by Category')
    money_table(categories, {
        'category_name': 'Category', 'this_month': 'This Month',
        'last_year_month': 'Prior Year', 'monthly_avg_12mo': '12-mo Avg',
    }, 'this_month')

# ---------- Rows 3-4: monthly spend by category ----------
trends = query('select month, category_name, abs(total) as total from category_trends')
ranked = trends.groupby('category_name')['total'].sum().sort_values(ascending=False).index.tolist()
top = ranked[:MAX_CATEGORIES]
trends['category'] = trends['category_name'].where(trends['category_name'].isin(top), 'Other')
trends = trends.groupby(['month', 'category'], as_index=False)['total'].sum()
trends['share'] = trends['total'] / trends.groupby('month')['total'].transform('sum')

domain = top + (['Other'] if len(ranked) > MAX_CATEGORIES else [])
category_color = alt.Color('category:N', title=None, sort=domain,
                           scale=alt.Scale(domain=domain, range=PALETTE[:len(top)] + [OTHER]),
                           legend=alt.Legend(orient='bottom', columns=4))
trends['rank'] = trends['category'].map({c: i for i, c in enumerate(domain)})
trends_x = month_axis(trends)


def stacked_bar(y, y_format, stack):
    return alt.Chart(trends).mark_bar(stroke='white', strokeWidth=1).encode(
        x=trends_x,
        y=alt.Y(f'{y}:Q', title=None, stack=stack, axis=alt.Axis(format=y_format)),
        color=category_color,
        order=alt.Order('rank:Q'),
        tooltip=[alt.Tooltip('label:N', title='Month'), 'category:N',
                 alt.Tooltip('total:Q', format='$,.0f'), alt.Tooltip('share:Q', format='.0%')],
    ).properties(height=400)


st.subheader('Monthly Spend by Category')
st.altair_chart(stacked_bar('total', '$,.0f', 'zero'), use_container_width=True)

st.subheader('Monthly Spend % by Category')
st.altair_chart(stacked_bar('total', '.0%', 'normalize'), use_container_width=True)

# ---------- Glossary ----------
with st.expander('Category Glossary', expanded=True):
    st.markdown("""
| Category | What's included |
|---|---|
| **Bills & Utilities** | Recurring fixed bills — phone, internet, cable, insurance, utilities, bank fees, government services |
| **Entertainment** | Streaming services, concerts, events, gifts, donations |
| **Food & Groceries** | All food spend — groceries (Whole Foods, Trader Joe's, Nijiya), restaurants, bars, cafes, food delivery |
| **Health & Wellness** | Gym memberships, fitness classes, wellness services |
| **Housing** | Rent, home improvement, maintenance, repairs |
| **Loan Payments** | Mortgage payments, credit card payments, any debt service |
| **Personal Care** | Medical, pharmacy, haircuts, personal hygiene services |
| **Shopping** | General retail — clothing, electronics, household goods, department stores, online purchases |
| **Transport** | Rideshare (Uber, Lyft), public transit, gas, parking, car-related expenses |
| **Travel** | Flights, hotels, travel agencies — trips away from home |
| **Transfers** | Internal transfers between your own accounts — excluded from all spend charts |
| **Income** | All inflows — paychecks, reimbursements, interest, any money coming in |

**Notes**
- Transfers are excluded from all spend and income totals to avoid double-counting.
- Loan Payments includes both mortgage and credit card payments. Credit card purchases are captured in their respective categories at transaction time.
- 12-mo Avg on the MTD chart is a rolling average of the last 12 fully completed calendar months.
- Prior Year columns compare the same time period one year ago.
- The two monthly category charts show the 7 largest categories; the rest are grouped as "Other" (the tables list every category).
""")

# ---------- Row 5: cash flow + merchants ----------
left, right = st.columns([2, 1])

with left:
    st.subheader('Net Cash Flow')
    cash = query("select month, initcap(category_type) as type, total from monthly_cash_flow")
    st.altair_chart(
        alt.Chart(cash).mark_bar(cornerRadius=4).encode(
            x=month_axis(cash),
            xOffset='type:N',
            y=alt.Y('total:Q', title=None, axis=alt.Axis(format='$,.0f')),
            color=alt.Color('type:N', title=None, scale=alt.Scale(domain=['Income', 'Expense'], range=PALETTE[:2]),
                            legend=alt.Legend(orient='bottom')),
            tooltip=[alt.Tooltip('label:N', title='Month'), 'type:N', alt.Tooltip('total:Q', format='$,.0f')],
        ).properties(height=400),
        use_container_width=True,
    )

with right:
    st.subheader('Top Merchants')
    st.caption('Last 28 days')
    merchants = query('select merchant, total_spent, transaction_count from top_merchants order by total_spent desc limit 20')
    merchants = merchants.rename(columns={'merchant': 'Merchant', 'total_spent': 'Total', 'transaction_count': 'Txns'})
    st.dataframe(
        merchants.style.format({'Total': '${:,.2f}'}),
        hide_index=True,
        height=table_height(merchants),
    )

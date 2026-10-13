"""
Dough Flow dashboard.

Reads the dbt gold models live from Postgres. Runs as the `streamlit` service in
docker-compose: http://<host>:8501
"""

import os
from html import escape
from pathlib import Path

import altair as alt
import pandas as pd
import psycopg2
import streamlit as st

ICON = str(Path(__file__).parent / 'assets' / 'icon.png')
DANCING_ICON = str(Path(__file__).parent / 'assets' / 'icon-dancing.gif')

st.set_page_config(page_title='Dough Flow', page_icon=ICON, layout='wide')

# Icon and title sit in the top bar like a site nav: the header goes transparent, the page
# moves up into it (default top padding is 6rem), and the title shrinks to wordmark size
st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=Fredoka:wght@600&display=swap');
[data-testid="stHeader"] { background: transparent; }
[data-testid="stMainBlockContainer"] { padding-top: 0; }
/* this style block's own (empty) element would otherwise add a row gap above the title */
[data-testid="stElementContainer"]:has(style) { display: none; }
/* wordmark: dark green from the icon's tile; line-height 1 so it centers on the icon */
[data-testid="stMainBlockContainer"] h1 {
    font-family: 'Fredoka', sans-serif; font-weight: 600; font-size: 2rem; color: #2F6B4F;
    padding: 0; line-height: 1;
}
/* title row and tab bar stay pinned while the page scrolls. Sticky goes on their wrappers,
   which are exactly their height (sticky needs a taller parent). They sit below the Deploy
   menu (stHeader) */
[data-testid="stLayoutWrapper"]:has(> .st-key-masthead),
[data-testid="stTabs"] div:has(> [data-baseweb="tab-list"]) {
    position: sticky; z-index: 999;
}
/* content slides under the pinned bars, so they need the app's background. Only stApp paints
   it, so every element from stApp down to the bars inherits it, matching light or dark theme */
[data-testid="stApp"] :has(.st-key-masthead),
[data-testid="stApp"] :has([data-baseweb="tab-list"]) { background-color: inherit; }
/* the bottom padding covers the 1rem row gap below it (the negative margin keeps the layout
   unchanged), so nothing shows between the bars */
[data-testid="stLayoutWrapper"]:has(> .st-key-masthead) {
    top: 0; padding: 0.5rem 0 1rem; margin-bottom: -1rem;
}
/* pinned exactly where the tabs sit at rest (0.5rem padding + 60px icon + 1rem row gap), so they don't shift */
[data-testid="stTabs"] div:has(> [data-baseweb="tab-list"]) {
    top: calc(1.5rem + 60px); box-shadow: 0 1px 0 rgba(49, 51, 63, 0.2);
}
/* the tab underline is a separate element that would scroll away; the box-shadow above replaces it */
[data-testid="stTabs"] [data-baseweb="tab-border"] { display: none; }
/* breathing room between each tab's last chart/table and the dancing bread */
[class*="st-key-dancer-"] { margin-top: 3rem; }
/* html_table(): looks like st.dataframe, plus hover tooltips. Grays mix with the text color so
   they work in light and dark themes */
.dough-table { width: 100%; border-collapse: separate; border-spacing: 0; font-size: 14px;
    border: 1px solid color-mix(in srgb, currentColor 15%, transparent); border-radius: 0.5rem; }
.dough-table th, .dough-table td { height: 35px; padding: 0 8px; text-align: left; white-space: nowrap;
    border-bottom: 1px solid color-mix(in srgb, currentColor 10%, transparent); }
.dough-table th + th, .dough-table td + td { border-left: 1px solid color-mix(in srgb, currentColor 10%, transparent); }
.dough-table th { font-weight: 400; color: color-mix(in srgb, currentColor 65%, transparent);
    background: color-mix(in srgb, currentColor 3%, transparent); }
.dough-table tbody tr:last-child td { border-bottom: none; }
/* number columns hug their contents so text columns (merchant, category) get the spare width */
.dough-table .num { text-align: right; width: 1%; padding: 0 16px; }
.has-tip { position: relative; cursor: help; }
.has-tip.category { text-decoration: underline dotted; text-underline-offset: 3px; }
.has-tip.help { display: inline-flex; align-items: center; justify-content: center; width: 14px; height: 14px;
    margin-left: 6px; border: 1px solid currentColor; border-radius: 50%; font-size: 10px; vertical-align: 1px; }
.tip { visibility: hidden; opacity: 0; transition: opacity 0.1s; position: absolute; top: calc(100% + 6px); left: 0;
    z-index: 1000; width: max-content; max-width: 280px; padding: 6px 10px; border-radius: 6px;
    background: #31333f; color: #fff; font-size: 13px; line-height: 1.4; white-space: normal; text-align: left; }
.tip.right { left: auto; right: 0; }
.has-tip:hover > .tip { visibility: visible; opacity: 1; }
</style>
""", unsafe_allow_html=True)

# Categorical palette in fixed order; categories past the 7th fold into "Other"
PALETTE = ['#2a78d6', '#eb6834', '#1baf7a', '#eda100', '#e87ba4', '#008300', '#6250d6']
OTHER = '#898781'
MAX_CATEGORIES = len(PALETTE)
# What each category includes; shown on hover wherever a category name appears
CATEGORY_HELP = {
    'Bills & Utilities': 'Recurring fixed bills: phone, internet, cable, insurance, utilities, bank fees, government services',
    'Entertainment': 'Streaming services, concerts, events, gifts, donations',
    'Food & Groceries': "All food spend: groceries (Whole Foods, Trader Joe's, Nijiya), restaurants, bars, cafes, food delivery",
    'Health & Wellness': 'Doctors, dentists, eye care, pharmacy, gyms and fitness classes',
    'Housing': 'Rent, home improvement, maintenance, repairs',
    'Loan Payments': 'Mortgage payments, credit card payments, any debt service',
    'Personal Care': 'Haircuts, beauty, other personal care services',
    'Shopping': 'General retail: clothing, electronics, household goods, department stores, online purchases',
    'Transport': 'Rideshare (Uber, Lyft), public transit, gas, parking, car-related expenses',
    'Travel': 'Flights, hotels, travel agencies: trips away from home',
    'Transfers': 'Internal transfers between your own accounts; excluded from all spend charts',
    'Income': 'All inflows: paychecks, reimbursements, interest, any money coming in',
    'Other': 'Smaller categories grouped together',
}
# First day of the daily Plaid ingest (dags/ingest_plaid.py)
PLAID_SYNC_START = pd.Timestamp('2026-05-04')


# No spinner: on a cache miss it adds an element above the tabs, which resets them to the first tab
@st.cache_data(ttl=600, show_spinner=False)
def query(sql):
    with psycopg2.connect(
        host=os.environ['DB_HOST'],
        port=os.environ['DB_PORT'],
        dbname=os.environ['DB_NAME'],
        user=os.environ['DB_USER'],
        password=os.environ['DB_PASSWORD'],
    ) as conn:
        return pd.read_sql(sql, conn)


def crosshair(df, x, series, y, y_format, order, monthly=False):
    # Hover anywhere on the plot: a hairline snaps to the nearest date and one tooltip
    # lists every series there, so the pointer never has to land on a line
    wide = df.pivot_table(index=x, columns=series, values=y, aggfunc='sum').reset_index()
    wide.columns = [str(c) for c in wide.columns]
    hover = alt.selection_point(fields=[x], nearest=True, on='pointerover', clear='pointerout', empty=False)
    rule = alt.Chart(wide).mark_rule(color=OTHER).encode(
        x=f'{x}:T',
        opacity=alt.condition(hover, alt.value(0.8), alt.value(0)),
        tooltip=[alt.Tooltip(f'{x}:T', title='Month' if monthly else 'Date', format='%b %Y' if monthly else '%b %d, %Y')]
                + [alt.Tooltip(field=str(s), type='quantitative', format=y_format) for s in order],
    ).add_params(hover)
    return hover, rule


def end_labels(ends, x_enc, y, series, color_scale, y_format, gap, top=None, show_value=False, fmt=None,
               tooltip=None):
    # Name each series just past the chart's right edge instead of using a legend. Labels
    # that would overlap are nudged apart (and kept under `top`), each with a dot in its
    # series color beside it.
    ends = ends.sort_values(y).copy()
    label_y, prev = [], None
    for v in ends[y]:
        prev = v if prev is None else max(v, prev + gap)
        label_y.append(prev)
    if top is not None and label_y[-1] > top:
        label_y[-1] = top
        for i in range(len(label_y) - 2, -1, -1):
            label_y[i] = min(label_y[i], label_y[i + 1] - gap)
    ends['label_y'] = label_y
    fmt = fmt or money
    ends['label_text'] = ends[series].astype(str) + (ends[y].map(lambda v: f' · {fmt(v)}') if show_value else '')
    chart = alt.Chart(ends).encode(x=x_enc, color=alt.Color(f'{series}:N', scale=color_scale, legend=None))
    if tooltip:
        chart = chart.encode(tooltip=tooltip)
    dot = chart.mark_point(filled=True, size=50, opacity=1, xOffset=6).encode(
        y=alt.Y('label_y:Q', title=None, axis=alt.Axis(format=y_format)))
    # label text stays neutral; the dot beside it carries the series color
    text = chart.mark_text(align='left', dx=14, fontSize=12).encode(
        y=alt.Y('label_y:Q', title=None, axis=alt.Axis(format=y_format)), text='label_text:N', color=alt.value(OTHER))
    # no extra padding needed: fitting to the container width already makes room for the text
    return [dot, text]


def line_chart(df, x, y, color, x_format, colors, zero=True, y_format='$,.0f', fmt=None, category_help=False,
               monthly=False):
    # category_help: series are categories; hovering a line or its label shows what it includes
    color_scale = alt.Scale(domain=list(colors), range=list(colors.values()))
    tooltip = None
    if category_help:
        df = df.assign(includes=df[color].map(CATEGORY_HELP).fillna(''))
        tooltip = [alt.Tooltip(f'{color}:N', title='Category'), alt.Tooltip('includes:N', title='Includes')]
    base = alt.Chart(df).encode(
        # monthly: one tick per data month (auto ticks drift off the points and can repeat a month)
        x=alt.X(f'{x}:T', title=None, axis=alt.Axis(format=x_format, values=[
            alt.DateTime(year=d.year, month=d.month, date=1) for d in sorted(df[x].unique())] if monthly else alt.Undefined)),
        y=alt.Y(f'{y}:Q', title=None, scale=alt.Scale(zero=zero), axis=alt.Axis(format=y_format)),
        color=alt.Color(f'{color}:N', title=None, scale=color_scale, legend=None),
    )
    hover, rule = crosshair(df, x, color, y, y_format, colors, monthly)
    points = base.mark_point(filled=True, size=60, opacity=1).encode(
        opacity=alt.condition(hover, alt.value(1), alt.value(0)))
    line = base.mark_line(strokeWidth=2)
    if tooltip:
        line = line.encode(tooltip=tooltip)
    span = df[y].max() - (df[y].min() if not zero else min(df[y].min(), 0))
    labels = end_labels(df[df[x] == df[x].max()], base.encoding.x, y, color, color_scale, y_format,
                        gap=span * 0.06, show_value=True, fmt=fmt, tooltip=tooltip)
    return alt.layer(line, points, rule, *labels)


def stack_midpoints(df, series, value, rank):
    # Middle of each series' band in a stacked chart (lowest rank at the bottom)
    df = df.sort_values(rank).copy()
    df['mid'] = df[value].cumsum() - df[value] / 2
    return df


def money_table(df, columns, sort_by):
    df = df[list(columns)].sort_values(sort_by, ascending=False)
    total = df.drop(columns=df.columns[0]).sum().to_frame().T
    total.insert(0, df.columns[0], 'Total')
    df = pd.concat([df, total], ignore_index=True).rename(columns=columns)
    html_table(df, {c: '${:,.0f}' for c in df.columns[1:]})


def html_table(df, formats=None, help=None):
    # A static table like st.dataframe, which can't show tooltips: a ? on headers listed in
    # `help`, and each category name in a Category column shows what it includes
    formats, help = formats or {}, help or {}
    numeric = {c for c in df.columns if pd.api.types.is_numeric_dtype(df[c])}

    def tip(text, right=False):
        return f'<span class="tip{" right" if right else ""}">{escape(text)}</span>'

    head = ''.join(
        f'<th class="{"num" if c in numeric else ""}">{escape(c)}'
        + (f'<span class="has-tip help">?{tip(help[c], right=c in numeric)}</span>' if c in help else '')
        + '</th>'
        for c in df.columns)
    rows = ''
    for row in df.to_dict('records'):
        cells = ''
        for c in df.columns:
            text = escape(formats[c].format(row[c]) if c in formats else str(row[c]))
            if c == 'Category' and row[c] in CATEGORY_HELP:
                text = f'<span class="has-tip category">{text}{tip(CATEGORY_HELP[row[c]])}</span>'
            cells += f'<td class="{"num" if c in numeric else ""}">{text}</td>'
        rows += f'<tr>{cells}</tr>'
    st.html(f'<table class="dough-table"><thead><tr>{head}</tr></thead><tbody>{rows}</tbody></table>')


def money(x, sign=False):
    prefix = '-' if x < 0 else '+' if sign else ''
    return f'{prefix}${abs(x):,.0f}'


def escape_dollars(text):
    # Streamlit markdown reads text between two dollar signs as math
    return text.replace('$', r'\$')


def table_height(df):
    # Tall enough to show every row (35px rows + header) so the table never scrolls
    return (len(df) + 1) * 35 + 3


def month_axis(df):
    # Label months as text so each bar sits under its own month name
    df['label'] = df['month'].map(lambda m: m.strftime('%b %Y'))
    return alt.X('label:O', title=None, sort=sorted(df['label'].unique(), key=lambda l: pd.to_datetime(l)),
                 axis=alt.Axis(labelAngle=0))


with st.container(horizontal=True, vertical_alignment='center', key='masthead'):
    st.image(ICON, width=60)
    st.title('Dough Flow')

categories = query('select * from gold.category_comparison')
net_worth_tab, this_month_tab, transactions_tab, trends_tab, glossary_tab = st.tabs(
    ['Net Worth', 'This Month', 'Transactions', 'Trends', 'Glossary'])

# ---------- This Month: am I on track? ----------
with this_month_tab:
    mtd = query('select date, this_month, prior_year_month, avg_monthly_spend from gold.daily_cumulative_mtd')
    today = mtd.iloc[-1]
    # 12-mo avg month spread evenly over the days, so "usual pace" by today's date
    pace = today['avg_monthly_spend'] * today['date'].day / pd.Timestamp(today['date']).days_in_month
    net_worth = query('select sum(net_worth_contribution) as total, min(snapshot_date) as oldest from gold.net_worth').iloc[0]
    syncs = query("""
        select distinct on (enrollment) enrollment, started_at, success, error_message
        from ops.pipeline_runs
        order by enrollment, started_at desc
    """)

    spent, typical, worth, synced = st.columns(4)
    spent.metric('Spent this month', money(today['this_month']),
                 delta=f'{money(today["this_month"] - pace, sign=True)} vs usual pace', delta_color='inverse',
                 help=f'Usual pace by today is {money(pace)}: the 12-mo avg spread evenly across the month', border=True, height='stretch')
    typical.metric('Typical month', money(today['avg_monthly_spend']),
                   help='Average spend over the last 12 full months', border=True, height='stretch')
    worth.metric('Net worth', money(net_worth['total']), help='Latest balance of every active account, minus credit cards',
                 border=True, height='stretch')
    last_sync = pd.Timestamp(syncs['started_at'].max()).tz_convert('America/Los_Angeles')
    synced.metric('Last bank sync', f'{last_sync:%b %d, %-I:%M %p}', border=True, height='stretch')
    # Below the row rather than under the tile, so the tiles stay the same height
    if (pd.Timestamp(today['date']) - pd.Timestamp(net_worth['oldest'])).days > 30:
        st.caption(f'Net worth includes balances last updated {net_worth["oldest"]:%b %d, %Y} (see Net Worth → Accounts)')

    failed = syncs[~syncs['success']]
    for _, run in failed.iterrows():
        st.warning(f'Latest {run["enrollment"]} sync failed on {run["started_at"]:%b %d}: {run["error_message"]}')

    left, right = st.columns(2)

    with left:
        st.subheader('MTD Cumulative Spend')
        mtd = mtd.rename(columns={
            'this_month': 'This Month', 'prior_year_month': 'Prior Year', 'avg_monthly_spend': '12-mo Avg',
        }).melt('date', var_name='series', value_name='spend')
        st.altair_chart(
            line_chart(mtd, 'date', 'spend', 'series', '%b %d',
                       {'This Month': PALETTE[0], 'Prior Year': OTHER, '12-mo Avg': PALETTE[1]}),
            use_container_width=True,
        )

    with right:
        st.subheader('MTD Spend by Category')
        money_table(categories, {
            'category_name': 'Category', 'this_month': 'This Month',
            'last_year_month': 'Prior Year', 'monthly_avg_12mo': '12-mo Avg',
        }, 'this_month')

    st.subheader('Top Merchants')
    st.caption('Last 28 days')
    merchants = query('select merchant, total_spent, transaction_count, share_of_spend from gold.top_merchants order by total_spent desc')
    merchants.insert(0, 'rank', range(1, len(merchants) + 1))
    merchants = merchants.rename(columns={'rank': 'Rank', 'merchant': 'Merchant', 'total_spent': 'Total', 'transaction_count': 'Txns', 'share_of_spend': '% of spend'})
    # 10 at a time; the arrows on either side page through the rest
    last_page = max(0, (len(merchants) - 1) // 10)
    page = min(st.session_state.get('merchant_page', 0), last_page)
    prev_col, table_col, next_col = st.columns([1, 30, 1], vertical_alignment='center')
    prev_col.button(':material/chevron_left:', key='merchants_prev', disabled=page == 0,
                    on_click=lambda: st.session_state.update(merchant_page=page - 1))
    next_col.button(':material/chevron_right:', key='merchants_next', disabled=page == last_page,
                    on_click=lambda: st.session_state.update(merchant_page=page + 1))
    shown = merchants.iloc[page * 10:(page + 1) * 10]
    with table_col:
        html_table(shown, {'Total': '${:,.2f}', '% of spend': '{:.1%}'},
                   help={'% of spend': 'Share of all spending in the last 28 days, including charges with no merchant'})
    table_col.caption(f'{page * 10 + 1}–{page * 10 + len(shown)} of {len(merchants)}')

# ---------- Transactions: what's behind the numbers? ----------
with transactions_tab:
    txns = query("""
        select
            transaction_date,
            coalesce(merchant, '')                     as merchant,
            coalesce(description, '')                  as description,
            coalesce(category_name, 'Uncategorized')   as category,
            institution || ' · ' || account_name       as account,
            owner,
            amount,
            spend
        from gold.transactions
        order by transaction_date desc, transaction_id desc
    """)

    dates_col, search_col, category_col, account_col = st.columns([1.2, 1.5, 1.5, 1.5])
    month_start = pd.Timestamp(today['date']).replace(day=1).date()
    dates = dates_col.date_input('Dates', value=(month_start, today['date']), format='MM/DD/YYYY')
    # While a range is half-picked the widget returns one date; treat it as a single day
    start, end = (tuple(dates) * 2)[:2]
    search = search_col.text_input('Search', placeholder='Merchant or description')
    category_list = '\n'.join(f'- **{c}**: {h}' for c, h in CATEGORY_HELP.items() if c != 'Other')
    chosen_categories = category_col.multiselect('Category', sorted(txns['category'].unique()), placeholder='All',
                                                 help=escape_dollars(category_list))
    chosen_accounts = account_col.multiselect('Account', sorted(txns['account'].unique()), placeholder='All')

    shown = txns[txns['transaction_date'].between(start, end)]
    if search:
        shown = shown[shown['merchant'].str.contains(search, case=False, regex=False)
                      | shown['description'].str.contains(search, case=False, regex=False)]
    if chosen_categories:
        shown = shown[shown['category'].isin(chosen_categories)]
    if chosen_accounts:
        shown = shown[shown['account'].isin(chosen_accounts)]

    income = shown.loc[shown['category'] == 'Income', 'amount'].sum()
    st.caption(escape_dollars(f'{len(shown):,} transactions · {money(shown["spend"].sum())} spent (net of refunds) · '
                              f'{money(income)} income'))
    st.dataframe(
        shown,
        hide_index=True,
        height=600,
        column_config={
            'transaction_date': st.column_config.DateColumn('Date', format='MMM D, YYYY'),
            'merchant': 'Merchant',
            'description': 'Description',
            'category': st.column_config.TextColumn(
                'Category', help='\n'.join(f'{c}: {h}' for c, h in CATEGORY_HELP.items() if c != 'Other')),
            'account': 'Account',
            'owner': 'Owner',
            'amount': st.column_config.NumberColumn('Amount', format='dollar'),
            'spend': None,
        },
    )

# ---------- Trends: where is the money going over time? ----------
with trends_tab:
    left, right = st.columns(2)

    with left:
        st.subheader('YTD Cumulative Spend')
        ytd = query("""
            select date, year, cumulative_total
            from gold.daily_cumulative_ytd
            where category_type = 'expense'
        """)
        years = sorted(ytd['year'].unique(), reverse=True)
        st.altair_chart(
            line_chart(ytd, 'date', 'cumulative_total', 'year', '%b %d',
                       dict(zip(years, [PALETTE[0], OTHER] + PALETTE[1:]))),
            use_container_width=True,
        )

    with right:
        st.subheader('YTD Spend by Category')
        money_table(categories, {'category_name': 'Category', 'this_year': 'This Year', 'last_year': 'Prior Year'},
                    'this_year')

    trends = query('select month, category_name, total from gold.category_trends')
    ranked = trends.groupby('category_name')['total'].sum().sort_values(ascending=False).index.tolist()
    top = ranked[:MAX_CATEGORIES]
    trends['category'] = trends['category_name'].where(trends['category_name'].isin(top), 'Other')
    trends = trends.groupby(['month', 'category'], as_index=False)['total'].sum()
    trends['share'] = trends['total'] / trends.groupby('month')['total'].transform('sum')

    domain = top + (['Other'] if len(ranked) > MAX_CATEGORIES else [])
    category_colors = dict(zip(domain, PALETTE[:len(top)] + [OTHER]))
    # a month with no spend in a category is 0, not a gap in its line
    trends = (trends.set_index(['month', 'category'])
              .reindex(pd.MultiIndex.from_product([trends['month'].unique(), domain], names=['month', 'category']),
                       fill_value=0)
              .reset_index())
    trends['month'] = pd.to_datetime(trends['month'])

    st.subheader('Monthly Spend by Category')
    st.altair_chart(line_chart(trends, 'month', 'total', 'category', '%b %Y', category_colors,
                               category_help=True, monthly=True).properties(height=400), use_container_width=True)

    st.subheader('Monthly Spend % by Category')
    st.altair_chart(line_chart(trends, 'month', 'share', 'category', '%b %Y', category_colors, y_format='.0%',
                               fmt='{:.0%}'.format, category_help=True, monthly=True).properties(height=400),
                    use_container_width=True)

    st.subheader('Net Cash Flow')
    cash = query("select month, initcap(category_type) as type, total from gold.monthly_cash_flow")
    st.altair_chart(
        alt.Chart(cash).mark_bar(cornerRadius=4).encode(
            x=month_axis(cash),
            xOffset='type:N',
            y=alt.Y('total:Q', title=None, axis=alt.Axis(format='$,.0f')),
            color=alt.Color('type:N', title=None, scale=alt.Scale(domain=['Income', 'Expense'], range=PALETTE[:2]),
                            legend=alt.Legend(orient='right')),
            tooltip=[alt.Tooltip('label:N', title='Month'), 'type:N', alt.Tooltip('total:Q', format='$,.0f')],
        ).properties(height=400),
        use_container_width=True,
    )

# ---------- Net Worth: how are my assets growing? ----------
with net_worth_tab:
    balances = query("""
        select date, account_id, institution || ' · ' || account_name as account, account_group,
               is_linked, net_worth_contribution as value, snapshot_date
        from gold.daily_balances
    """)
    balances['date'] = pd.to_datetime(balances['date'])
    # Start once every account linked in the initial setup (first 30 days) has history, so that
    # setup doesn't look like growth. Accounts added later appear as a step on their first day;
    # they're left out of growth until they exist (below). Setup is counted from when the daily
    # Plaid sync began, not the oldest balance: two Chase accounts have 2025 balances from the
    # CSV backfill, which would otherwise start the chart before most accounts existed.
    first_seen = balances[balances['is_linked']].groupby('account_id')['date'].min()
    start = first_seen[first_seen <= PLAID_SYNC_START + pd.Timedelta(days=30)].max()
    balances = balances[balances['date'] >= start]

    daily = balances.groupby('date', as_index=False)['value'].sum()
    latest_date = daily['date'].max()
    month_ago_date = max(latest_date - pd.Timedelta(days=30), start)
    worth_now = daily.loc[daily['date'] == latest_date, 'value'].iloc[0]

    def growth(since):
        # Only accounts that existed on `since`, so adding an account isn't counted as growth
        then = balances[balances['date'] == since]
        now = balances[(balances['date'] == latest_date) & balances['account_id'].isin(then['account_id'])]
        change = now['value'].sum() - then['value'].sum()
        return money(change, sign=True), f'{change / then["value"].sum():+.1%}'

    now_col, month_col, start_col = st.columns(3)
    now_col.metric('Net worth', money(worth_now), border=True, height='stretch')
    month_change, month_pct = growth(month_ago_date)
    month_col.metric('Last 30 days', month_change, delta=month_pct, border=True, height='stretch')
    quarter_change, quarter_pct = growth(max(latest_date - pd.Timedelta(days=90), start))
    start_col.metric('Last 90 days', quarter_change, delta=quarter_pct, border=True, height='stretch')

    st.subheader('Net Worth')
    st.altair_chart(
        line_chart(daily.assign(series='Net worth'), 'date', 'value', 'series', '%b %d', {'Net worth': PALETTE[0]},
                   zero=False).properties(height=350),
        use_container_width=True,
    )

    groups = ['Cash', 'Investments', 'Retirement']
    by_group = balances[balances['account_group'].isin(groups)].groupby(['date', 'account_group'], as_index=False)['value'].sum()
    by_group['rank'] = by_group['account_group'].map({g: i for i, g in enumerate(groups)})
    by_group['share'] = by_group['value'] / by_group.groupby('date')['value'].transform('sum')
    group_scale = alt.Scale(domain=groups, range=PALETTE[:len(groups)])
    left, right = st.columns(2)

    with left:
        st.subheader('Assets by Type')
        st.caption('Credit card balances are subtracted from net worth but not shown here')
        st.altair_chart(
            line_chart(by_group, 'date', 'value', 'account_group', '%b %d', dict(zip(groups, PALETTE))),
            use_container_width=True,
        )

    with right:
        st.subheader('Asset Mix')
        st.caption('Share of total assets by type')
        mix = alt.Chart(by_group).mark_area(stroke='white', strokeWidth=1).encode(
            x=alt.X('date:T', title=None, axis=alt.Axis(format='%b %d')),
            y=alt.Y('value:Q', title=None, stack='normalize', axis=alt.Axis(format='.0%')),
            color=alt.Color('account_group:N', title=None, sort=groups, scale=group_scale, legend=None),
            order=alt.Order('rank:Q'),
        )
        _, mix_rule = crosshair(by_group, 'date', 'account_group', 'share', '.0%', groups)
        mix_ends = stack_midpoints(by_group[by_group['date'] == latest_date], 'account_group', 'share', 'rank')
        mix_labels = end_labels(mix_ends, mix.encoding.x, 'mid', 'account_group', group_scale, '.0%', gap=0.06, top=1)
        st.altair_chart(alt.layer(mix, mix_rule, *mix_labels), use_container_width=True)

    st.subheader('Accounts')
    accounts = balances[balances['date'] == latest_date].merge(
        balances.loc[balances['date'] == month_ago_date, ['account_id', 'value']].rename(columns={'value': 'value_month_ago'}),
        on='account_id', how='left',
    )
    accounts['change'] = accounts['value'] - accounts['value_month_ago']
    accounts['group_rank'] = accounts['account_group'].map({g: i for i, g in enumerate(groups + ['Credit Cards'])})
    accounts['size'] = accounts['value'].abs()
    accounts = accounts.sort_values(['group_rank', 'size'], ascending=[True, False])
    updated = pd.to_datetime(accounts['snapshot_date'])
    accounts['stale'] = updated < latest_date - pd.Timedelta(days=30)
    accounts['last_updated'] = updated.dt.strftime('%b %d, %Y') + accounts['stale'].map({True: ' (STALE)', False: ''})

    def cents(x):
        return f"{'-' if x < 0 else ''}${abs(x):,.2f}"

    def signed_cents(x):
        # text, so a new account shows blank rather than "None"
        return '' if pd.isna(x) else f"{'+' if x > 0 else ''}{cents(x)}"

    def change_color(v):
        color = '#30a46c' if v.startswith('+') else '#e5484d' if v.startswith('-') else None
        return f'color: {color}; text-align: right' if color else 'text-align: right'

    table = accounts[['account', 'account_group', 'value', 'change', 'last_updated']].assign(
        change=accounts['change'].map(signed_cents))
    st.dataframe(
        table.style
        .format({'value': cents})
        .map(change_color, subset=['change'])
        .map(lambda v: 'color: #e5484d' if v.endswith('(STALE)') else '', subset=['last_updated']),
        hide_index=True,
        height=table_height(table),
        column_config={
            'account': 'Account',
            'account_group': 'Type',
            'value': 'Value',
            'change': '30-day Change',
            'last_updated': 'Last Updated',
        },
    )
    stale = accounts[accounts['stale']]
    if len(stale):
        st.caption(escape_dollars(
            f'{len(stale)} accounts have no balance in over 30 days and are carried forward at their last value: '
            f'{money(stale["value"].sum())} in total. Update them with scripts/update_balance.py.'))

# ---------- Glossary ----------
with glossary_tab:
    st.markdown("""
Hover over a category name anywhere in the dashboard to see what it includes.

**Notes**
- Transfers are excluded from all spend and income totals to avoid double-counting.
- Loan Payments includes both mortgage and credit card payments. Credit card purchases are captured in their respective categories at transaction time.
- 12-mo Avg on the MTD chart is a rolling average of the last 12 fully completed calendar months.
- Prior Year columns compare the same time period one year ago.
- The two monthly category charts show the 7 largest categories; the rest are grouped as "Other" (the tables list every category).
""")

for i, tab in enumerate((net_worth_tab, this_month_tab, transactions_tab, trends_tab, glossary_tab)):
    with tab, st.container(horizontal_alignment='center', key=f'dancer-{i}'):
        st.image(DANCING_ICON)

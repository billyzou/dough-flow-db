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
# Browser tab icon: just the toast, no tile, so it reads at 16px
FAVICON = str(Path(__file__).parent / 'assets' / 'favicon.png')

st.set_page_config(page_title='Dough Flow', page_icon=FAVICON, layout='wide')

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
/* line charts with month_bars: clicking off the lines picks a month (see line_chart) */
.month_targets_voronoi path { cursor: pointer; }
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
LINE_CLICK_HELP = ('Click a line or its label to show only that line. Option-click to hide it (you can hide several). '
                   'Double-click to bring them all back.')
# What each category includes; shown on hover wherever a category name appears
CATEGORY_HELP = {
    'Bills & Utilities': 'Recurring fixed bills: phone, internet, cable, insurance, utilities, bank fees, government services',
    'Entertainment': 'Streaming services, concerts, events, gifts, donations',
    'Food & Groceries': "All food spend: groceries (Whole Foods, Trader Joe's, Nijiya), restaurants, bars, cafes, food delivery",
    'Health & Wellness': 'Doctors, dentists, eye care, pharmacy, gyms and fitness classes',
    'Housing': 'Rent, home improvement, maintenance, repairs',
    'Loan Payments': ('Mortgage payments, credit card payments, any debt service. A card payment lands here twice '
                      '(out of checking, into the card) and cancels out; the purchases count in their own categories'),
    'Personal Care': 'Haircuts, beauty, other personal care services',
    'Shopping': 'General retail: clothing, electronics, household goods, department stores, online purchases',
    'Transport': 'Rideshare (Uber, Lyft), public transit, gas, parking, car-related expenses',
    'Travel': 'Flights, hotels, travel agencies: trips away from home',
    'Transfers': 'Internal transfers between your own accounts; left out of spend and income totals so nothing is counted twice',
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


def spread_labels(values, gap, floor=None, top=None):
    # Positions as close to `values` (ascending) as possible while at least `gap` apart: labels that
    # would overlap form a group centered on the mean of its values, kept within [floor, top]
    def start(total, n):
        s = total / n - (n - 1) * gap / 2
        if top is not None:
            s = min(s, top - (n - 1) * gap)
        return s if floor is None else max(s, floor)

    groups = []  # [sum of values, count]
    for v in values:
        groups.append([v, 1])
        while len(groups) > 1 and start(*groups[-2]) + groups[-2][1] * gap > start(*groups[-1]):
            total, n = groups.pop()
            groups[-1][0] += total
            groups[-1][1] += n
    return [start(*g) + i * gap for g in groups for i in range(g[1])]


def end_labels(ends, x_enc, y, series, color_scale, y_format, gap, top=None, floor=None, show_value=False,
               tooltip=None, cursor=alt.Undefined, label_y=None):
    # Name each series just past the chart's right edge instead of using a legend, each with a dot
    # in its series color beside it. Labels that would overlap are spread apart around their lines,
    # and a thin connector joins each line's end to its label. label_y: a column of positions already
    # worked out, used instead.
    ends = ends.sort_values(y).copy()
    ends['label_y'] = ends[label_y] if label_y else spread_labels(ends[y].tolist(), gap, floor, top)
    ends['label_text'] = ends[series].astype(str) + (ends[y].map(lambda v: f' · {money(v)}') if show_value else '')
    chart = alt.Chart(ends).encode(x=x_enc, color=alt.Color(f'{series}:N', scale=color_scale, legend=None))
    if tooltip:
        chart = chart.encode(tooltip=tooltip)
    connector = chart.mark_rule(strokeWidth=1, opacity=0.6, x2Offset=14).encode(
        y=alt.Y(f'{y}:Q', title=None, axis=alt.Axis(format=y_format)), y2='label_y:Q',
        x2=alt.X2(x_enc.to_dict()['field']))
    dot = chart.mark_point(filled=True, size=50, opacity=1, xOffset=14, cursor=cursor).encode(
        y=alt.Y('label_y:Q', title=None, axis=alt.Axis(format=y_format)))
    # label text stays neutral; the dot beside it carries the series color
    text = chart.mark_text(align='left', dx=22, fontSize=13, cursor=cursor).encode(
        y=alt.Y('label_y:Q', title=None, axis=alt.Axis(format=y_format)), text='label_text:N', color=alt.value(OTHER))
    return [connector, dot, text]


def hit_points(df, x, y, color, per_segment):
    # Invisible circles along each line, its click and hover area. Lines with few points get extra
    # circles between them so the gaps are covered; each carries its nearest data point's fields
    # (hover_x included), placed at the interpolated position.
    rows = []
    for _, g in df.sort_values(x).groupby(color):
        g = g.reset_index(drop=True)
        for i in range(len(g)):
            rows.append(g.iloc[i].to_dict())
            for k in range(1, per_segment if i + 1 < len(g) else 1):
                t = k / per_segment
                rows.append(g.iloc[i if t < 0.5 else i + 1].to_dict() | {
                    x: g[x][i] + (g[x][i + 1] - g[x][i]) * t, y: g[y][i] + (g[y][i + 1] - g[y][i]) * t})
    return pd.DataFrame(rows)


def line_chart(df, x, y, color, x_format, colors, zero=True, category_help=False, monthly=False, prior=None,
               month_bars=None):
    # category_help: series are categories; hovering a line or its label shows what it includes.
    # prior: column of each point's value a year earlier, drawn dashed for an isolated line.
    # month_bars: rows of (month, name, total, prior, color) for every category. Clicking off the lines
    # then swaps the lines for that month's bars, in this same chart (Streamlit can't pass a layered
    # chart's clicks back to Python); double-click goes back.
    y_format = '$,.0f'
    color_scale = alt.Scale(domain=list(colors), range=list(colors.values()))
    label_tooltip = alt.value(None)  # otherwise Streamlit shows every field of the label row
    if category_help:
        df = df.assign(includes=df[color].map(CATEGORY_HELP).fillna(''))
        label_tooltip = [alt.Tooltip(f'{color}:N', title='Category'), alt.Tooltip('includes:N', title='Includes')]
    # each point also carries every series' value at its x, so one tooltip can list them all
    wide = df.pivot_table(index=x, columns=color, values=y, aggfunc='sum')
    wide.columns = [f'v_{c}' for c in wide.columns]
    # hover_x: the data point a hover or month click is about (hit_points sit between data points).
    # Text, not a date: Vega-Lite parses a date field only in the layers that encode it as one, so a
    # date key wouldn't match between layers
    df = df.merge(wide.reset_index(), on=x).assign(
        hover_x=lambda d: pd.to_datetime(d[x]).dt.strftime('%Y-%m-%d'),
        hover_label=lambda d: pd.to_datetime(d[x]).dt.strftime('%b %Y' if monthly else '%b %d, %Y'))
    if prior:
        df['prior_plot'] = df[prior].clip(lower=0)
    hover_tooltip = ([alt.Tooltip('hover_label:N', title='Month' if monthly else 'Date')]
                     + (label_tooltip if category_help else [])
                     + ([alt.Tooltip(f'{prior}:Q', title='Same month last year', format=y_format)] if prior else [])
                     + [alt.Tooltip(field=f'v_{s}', type='quantitative', format=y_format, title=str(s)) for s in colors])
    base = alt.Chart(df).encode(
        # monthly: one tick per data month (auto ticks drift off the points and can repeat a month)
        x=alt.X(f'{x}:T', title=None, axis=alt.Axis(format=x_format, values=[
            alt.DateTime(year=d.year, month=d.month, date=1) for d in sorted(df[x].unique())] if monthly else alt.Undefined,
            # the month bars put category names there instead
            labelExpr=f"length(data('month_store')) ? '' : timeFormat(datum.value, '{x_format}')"
            if month_bars is not None else alt.Undefined)),
        y=alt.Y(f'{y}:Q', title=None, scale=alt.Scale(zero=zero), axis=alt.Axis(format=y_format)),
        color=alt.Color(f'{color}:N', title=None, scale=color_scale, legend=None),
    )
    # Hovering anywhere shows a hairline, a dot on each line and one tooltip. Clicking a line or its
    # label shows only that line, Option-click hides it (several can be hidden), double-click brings
    # them all back; hidden lines leave the y scale, so the rest rescale.
    # Vega-Lite doesn't limit a selection's events to its own layers, so each click filter checks what
    # was clicked: line hit points and labels carry the series, the hover area's items don't.
    on_series = f'event.item && event.item.datum && event.item.datum.{color} != null'
    hover = alt.selection_point(name='hover', fields=['hover_x'], nearest=True, on='pointerover',
                                clear='pointerout', empty=False)
    # a nearest selection only listens to its own hover area, which the line hit points cover, so
    # they set the hover through a second selection
    hover_hit = alt.selection_point(name='hover_hit', fields=['hover_x'], clear='pointerout', empty=False,
                                    on='pointerover[event.item && event.item.datum && event.item.datum.hover_x != null]')
    hovered = ("(length(data('hover_store')) && vlSelectionTest('hover_store', datum)) || "
               "(length(data('hover_hit_store')) && vlSelectionTest('hover_hit_store', datum))")
    pick = alt.selection_point(name='pick', fields=[color], on=f'click[!event.altKey && {on_series}]', clear='dblclick')
    drop = alt.selection_point(name='drop', fields=[color], on=f'click[event.altKey && {on_series}]', toggle='true',
                               clear='dblclick', empty=False)
    # written out because pick & ~drop loses drop's empty=False, which hides every line
    not_dropped = {'not': {'param': 'drop', 'empty': False}}
    month_mode = "length(data('month_store'))" if month_bars is not None else 'false'
    shown = {'and': [{'param': 'pick'}, not_dropped, f'!{month_mode}']}
    isolated = "length(data('pick_store'))"
    rule = alt.Chart(df).mark_rule(color=OTHER).encode(
        x=base.encoding.x, opacity=alt.condition(hovered, alt.value(0.8), alt.value(0))).transform_filter(shown)
    line = base.mark_line(strokeWidth=3).transform_filter(shown)
    points = base.mark_point(filled=True, size=60, opacity=1).encode(
        opacity=alt.condition(hovered, alt.value(1), alt.value(0))).transform_filter(shown)
    ends = df[df[x] == df[x].max()].copy()
    ends['iso_y'] = ends[y]
    if prior:
        # isolated, a line's label and its "Last year" label can collide: space the pair apart on the
        # axis the isolated chart rescales to (0 up to that category's own max)
        own_max = df.groupby(color)[[y, 'prior_plot']].max().max(axis=1)
        ends['iso_prior_y'] = ends['prior_plot']
        for i, row in ends[ends['prior_plot'].notna()].iterrows():
            pair = sorted([(row[y], 'iso_y'), (row['prior_plot'], 'iso_prior_y')])
            spread = spread_labels([v for v, _ in pair], own_max[row[color]] * 0.06, floor=0)
            for (_, column), v in zip(pair, spread):
                ends.loc[i, column] = v
    floor = df[y].min() if not zero else min(df[y].min(), 0)
    span = df[y].max() - floor
    labels = [layer.transform_filter(shown).transform_filter(f'!{isolated}').add_params(pick, drop) for layer in end_labels(
        ends, base.encoding.x, y, color, color_scale, y_format, gap=span * 0.05, floor=floor, show_value=True,
        tooltip=label_tooltip, cursor='pointer')]
    # an isolated line is labeled at its own value (the nudging above spaced labels for every line),
    # or moved just enough to clear its "Last year" label
    picked_labels = [layer.transform_filter(shown).transform_filter(isolated) for layer in end_labels(
        ends, base.encoding.x, y, color, color_scale, y_format, gap=0, show_value=True, tooltip=label_tooltip,
        label_y='iso_y')]
    prior_layers = []
    if prior:
        # the isolated line's same months a year earlier, dashed, with its own end label. A month of net
        # refunds is drawn at 0 (the tooltip keeps the real value): even hidden, a negative value
        # would stretch the axis below 0
        prior_shown = {'and': [{'param': 'pick', 'empty': False}, not_dropped, f'!{month_mode}']}
        has_prior = f'isValid(datum["{prior}"])'
        prior_ends = ends[ends[prior].notna()].assign(prior_text=lambda d: d[prior].map(lambda v: f'Last year · {money(v)}'))
        prior_end = alt.Chart(prior_ends).encode(x=base.encoding.x, y=alt.Y('iso_prior_y:Q'))
        prior_layers = [
            base.mark_line(strokeWidth=2, strokeDash=[6, 4], opacity=0.7).encode(y=alt.Y('prior_plot:Q'))
            .transform_filter(has_prior).transform_filter(prior_shown),
            prior_end.mark_rule(strokeWidth=1, opacity=0.6, x2Offset=14).encode(
                y='prior_plot:Q', y2='iso_prior_y:Q', x2=alt.X2(base.encoding.x.to_dict()['field']),
                color=alt.Color(f'{color}:N', scale=color_scale, legend=None)).transform_filter(prior_shown),
            prior_end.mark_point(filled=True, size=50, opacity=0.7, xOffset=14).encode(
                color=alt.Color(f'{color}:N', scale=color_scale, legend=None)).transform_filter(prior_shown),
            prior_end.mark_text(align='left', dx=22, fontSize=13, color=OTHER).encode(text='prior_text:N')
            .transform_filter(prior_shown),
        ]
    # the hover area: invisible points with a nearest-point area over the whole plot
    targets = base.mark_point(opacity=0).encode(tooltip=hover_tooltip).transform_filter(shown).add_params(hover)
    bar_layers = []
    if month_bars is not None:
        month = alt.selection_point(name='month', fields=['hover_x'], nearest=True, clear='dblclick',
                                    on=f'click[!event.altKey && !({on_series}) && !{month_mode}]')
        targets = targets.add_params(month).properties(name='month_targets')  # named for the pointer cursor CSS
        bar_layers = month_bar_layers(month_bars, df[x].min(), df[x].max(), y_format)
    # each line's click area, on top (at opacity 0 a mark isn't drawn, so it can't be clicked)
    hits = alt.Chart(hit_points(df, x, y, color, max(1, 240 // df[x].nunique()))).mark_circle(
        size=220, opacity=0.001, cursor='pointer').encode(
        x=base.encoding.x, y=base.encoding.y, tooltip=hover_tooltip).transform_filter(shown).add_params(pick, drop, hover_hit)
    # labels sit past the plot's right edge, outside the hover area, so they still get their own clicks.
    # extra right padding: fitting to the container leaves the end of the longest label clipped
    return alt.layer(rule, line, *prior_layers, points, *labels, *picked_labels, *bar_layers, targets, hits).properties(
        padding={'left': 5, 'top': 24 if month_bars is not None else 5, 'bottom': 5, 'right': 16})


def month_bar_layers(bars, start, end, y_format):
    # One month's categories as bars across the line chart's own axes: each bar gets a slot of the
    # date range (x is still the month scale) and its height in the same $ scale. Shown only while
    # 'month' is selected.
    bars = bars.sort_values(['month', 'total'], ascending=[True, False]).copy()
    bars['i'] = bars.groupby('month').cumcount()
    slot = (end - start) / bars.groupby('month')['name'].transform('count')
    bars['x0'] = start + slot * (bars['i'] + 0.15)
    bars['x1'] = start + slot * (bars['i'] + 0.85)
    bars['xc'] = start + slot * (bars['i'] + 0.5)
    bars['hover_x'] = bars['month'].dt.strftime('%Y-%m-%d')  # matches line_chart's hover_x
    bars['value'] = bars['total'].map(money)
    bars['total_plot'] = bars['total'].clip(lower=0)
    bars['prior_plot'] = bars['prior'].clip(lower=0)
    bars['includes'] = bars['name'].map(CATEGORY_HELP).fillna('')
    selected = {'param': 'month', 'empty': False}
    tooltip = [alt.Tooltip('name:N', title='Category'), alt.Tooltip('includes:N', title='Includes'),
               alt.Tooltip('total:Q', title='Spend', format=y_format),
               alt.Tooltip('prior:Q', title='Same month last year', format=y_format)]
    chart = alt.Chart(bars).transform_filter(selected)
    titles = alt.Chart(bars.drop_duplicates('month').assign(
        title=lambda d: d['month'].dt.strftime('%B %Y') + ' · double-click to go back')).transform_filter(selected)
    return [
        chart.mark_bar(cornerRadius=3).encode(x='x0:T', x2='x1:T', y='total_plot:Q', y2=alt.datum(0),
                                              color=alt.Color('color:N', scale=None), tooltip=tooltip),
        # last year's spend in the same month, a grey line across the bar
        chart.mark_rule(strokeWidth=3, color=OTHER).encode(x='x0:T', x2='x1:T', y='prior_plot:Q', tooltip=tooltip)
        .transform_filter('isValid(datum.prior)'),
        chart.mark_text(dy=-8, fontSize=13, color=OTHER).encode(x='xc:T', y='total_plot:Q', text='value:N'),
        chart.mark_text(dy=14, fontSize=12, color=OTHER).encode(x='xc:T', y=alt.datum(0), text='name:N'),
        titles.mark_text(align='left', fontSize=14, fontWeight='bold').encode(
            x=alt.value(0), y=alt.value(-14), text='title:N'),
    ]


def stack_midpoints(df, series, value, rank):
    # Middle of each series' band in a stacked chart (lowest rank at the bottom)
    df = df.sort_values(rank).copy()
    df['mid'] = df[value].cumsum() - df[value] / 2
    return df


def money_table(df, columns, sort_by, help=None, total=True):
    df = df[list(columns)].sort_values(sort_by, ascending=False)
    if total:
        totals = df.drop(columns=df.columns[0]).sum().to_frame().T
        totals.insert(0, df.columns[0], 'Total')
        df = pd.concat([df, totals], ignore_index=True)
    df = df.rename(columns=columns)
    html_table(df, {c: '${:,.0f}' for c in df.columns[1:]}, help=help)


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
net_worth_tab, this_month_tab, this_year_tab, transactions_tab = st.tabs(
    ['Net Worth', 'This Month', 'This Year', 'Transactions'])

# ---------- This Month: am I on track? ----------
with this_month_tab:
    mtd = query('select date, this_month, prior_year_month, avg_monthly_spend from gold.daily_cumulative_mtd')
    # Usual pace: the 12-mo avg month spread evenly over its days. The chart's line and the
    # "vs usual pace" delta both use it, so they agree
    days_in_month = pd.Timestamp(mtd['date'].iloc[-1]).days_in_month
    mtd['usual_pace'] = mtd['avg_monthly_spend'] * pd.to_datetime(mtd['date']).dt.day / days_in_month
    today = mtd.iloc[-1]
    pace = today['usual_pace']
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
        st.subheader('MTD Cumulative Spend', help='Usual Pace is the average month (last 12 fully completed months) '
                     'spread evenly across its days, so it ends at the typical monthly total.\n\n' + LINE_CLICK_HELP)
        mtd = mtd.drop(columns='avg_monthly_spend').rename(columns={
            'this_month': 'This Month', 'prior_year_month': 'Prior Year', 'usual_pace': 'Usual Pace',
        }).melt('date', var_name='series', value_name='spend')
        st.altair_chart(
            line_chart(mtd, 'date', 'spend', 'series', '%b %d',
                       {'This Month': PALETTE[0], 'Prior Year': OTHER, 'Usual Pace': PALETTE[1]}),
            use_container_width=True,
        )

    with right:
        st.subheader('MTD Spend by Category')
        money_table(categories, {
            'category_name': 'Category', 'this_month': 'This Month',
            'last_year_month': 'Prior Year', 'monthly_avg_12mo': '12-mo Avg',
        }, 'this_month', help={'Prior Year': 'The whole of this month, one year ago',
                               '12-mo Avg': 'Average month over the last 12 fully completed months'})

    st.subheader('Top Merchants')
    st.caption('Last 28 days')
    merchants = query('select merchant, total_spent, transaction_count, share_of_spend from gold.top_merchants order by total_spent desc')
    merchants.insert(0, 'rank', range(1, len(merchants) + 1))
    merchants = merchants.rename(columns={'rank': 'Rank', 'merchant': 'Merchant', 'total_spent': 'Total', 'transaction_count': 'Transactions', 'share_of_spend': '% of Spend'})
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
        html_table(shown, {'Total': '${:,.2f}', '% of Spend': '{:.1%}'},
                   help={'% of Spend': 'Share of all spending in the last 28 days, including charges with no merchant'})
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

# ---------- This Year: where is the money going over time? ----------
with this_year_tab:
    left, right = st.columns(2)

    with left:
        st.subheader('YTD Cumulative Spend', help=LINE_CLICK_HELP)
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
                    'this_year', help={'Prior Year': 'Last year, Jan 1 through the same date'}, total=False)

    trends = query('select month, category_name, total from gold.category_trends')
    ranked = trends.groupby('category_name')['total'].sum().sort_values(ascending=False).index.tolist()
    top = ranked[:MAX_CATEGORIES]
    trends['category'] = trends['category_name'].where(trends['category_name'].isin(top), 'Other')
    trends = trends.groupby(['month', 'category'], as_index=False)['total'].sum()

    domain = top + (['Other'] if len(ranked) > MAX_CATEGORIES else [])
    category_colors = dict(zip(domain, PALETTE[:len(top)] + [OTHER]))
    # a month with no spend in a category is 0, not a gap in its line
    trends = (trends.set_index(['month', 'category'])
              .reindex(pd.MultiIndex.from_product([trends['month'].unique(), domain], names=['month', 'category']),
                       fill_value=0)
              .reset_index())
    trends['month'] = pd.to_datetime(trends['month'])
    months = sorted(trends['month'].unique())
    a_year_before = [m - pd.DateOffset(years=1) for m in months]

    # every month's spend by category, for prior-year values (category_trends only covers the last 12 months)
    history = query('select month, category_name, total from gold.monthly_spending')
    history['month'] = pd.to_datetime(history['month'])

    total_col, cash_col = st.columns(2)
    with total_col:
        st.subheader('Monthly Total Spend', help='Every category combined, transfers excluded. Prior Year is the '
                     'same month a year earlier (the current month compares a partial month with a full one).')
        spend_by_month = history.groupby('month')['total'].sum()
        monthly_total = pd.concat([
            pd.DataFrame({'month': months, 'series': 'Total Spend',
                          'total': spend_by_month.reindex(months).fillna(0).values}),
            # history starts Jan 2025, so earlier months have no prior year and are left off
            pd.DataFrame({'month': months, 'series': 'Prior Year',
                          'total': spend_by_month.reindex(a_year_before).values}).dropna(),
        ])
        st.altair_chart(line_chart(monthly_total, 'month', 'total', 'series', '%b %Y',
                                   {'Total Spend': PALETTE[0], 'Prior Year': OTHER},
                                   monthly=True).properties(height=400), use_container_width=True)

    with cash_col:
        st.subheader('Net Cash Flow', help="Income (up) and spending (down) each month. Transfers between your own "
                     "accounts are left out of both, so they aren't counted twice. Grey ticks are the same month a "
                     "year earlier.")
        cash = query("select month, initcap(category_type) as type, total from gold.monthly_cash_flow")
        cash['month'] = pd.to_datetime(cash['month'])
        by_type = cash.pivot_table(index='month', columns='type', values='total', aggfunc='sum')
        by_type = by_type.reindex(columns=['Income', 'Expense']).fillna(0)
        this_year = by_type.reindex(months).fillna(0)
        last_year = by_type.reindex(a_year_before)  # NaN before history starts
        flow = pd.DataFrame({'month': months})
        for name, frame in (('', this_year), ('prior_', last_year)):
            flow[f'{name}income'] = frame['Income'].values
            flow[f'{name}expense'] = frame['Expense'].values
            flow[f'{name}net'] = flow[f'{name}income'] + flow[f'{name}expense']
        # income up and expense down at the same month, so each month is one column
        cash = pd.concat([flow.assign(type='Income', total=flow['income'], prior=flow['prior_income']),
                          flow.assign(type='Expense', total=flow['expense'], prior=flow['prior_expense'])])
        cash_x = month_axis(cash)
        cash_colors = alt.Scale(domain=['Income', 'Expense', 'Prior Year'], range=PALETTE[:2] + [OTHER])
        cash_tooltip = [alt.Tooltip('label:N', title='Month')] + [
            alt.Tooltip(f'{field}:Q', title=title, format='$,.0f') for field, title in (
                ('income', 'Income'), ('expense', 'Expense'), ('net', 'Net'),
                ('prior_income', 'Income last year'), ('prior_expense', 'Expense last year'), ('prior_net', 'Net last year'))]
        bars = alt.Chart(cash).mark_bar(cornerRadius=3).encode(
            x=cash_x, y=alt.Y('total:Q', title=None, axis=alt.Axis(format='$,.0f')),
            color=alt.Color('type:N', title=None, scale=cash_colors, legend=alt.Legend(orient='top')),
            tooltip=cash_tooltip)
        ticks = alt.Chart(cash).mark_tick(thickness=3).encode(
            x=cash_x, y='prior:Q', color=alt.datum('Prior Year'), tooltip=cash_tooltip).transform_filter('isValid(datum.prior)')
        st.altair_chart(alt.layer(bars, ticks).properties(height=400), use_container_width=True)

    st.subheader('Monthly Spend by Category', help=(
        f'Shows the {MAX_CATEGORIES} largest categories; the rest are grouped as Other (the tables list every '
        'category).\n\nClick a line or its label to show only that category, with the same months last year '
        'dashed. Click anywhere else to see every category for that month as bars. Option-click hides a line '
        '(you can hide several); double-click brings them all back.'))
    grouped = history.assign(category=history['category_name'].where(history['category_name'].isin(top), 'Other'))
    grouped = grouped.groupby(['month', 'category'])['total'].sum()
    trends['prior'] = [grouped.get((m - pd.DateOffset(years=1), c)) for m, c in zip(trends['month'], trends['category'])]
    # every category (not grouped into Other) of each month, for the bars a month click shows
    month_bars = history[history['month'].isin(months)].rename(columns={'category_name': 'name'})
    last_year_spend = history.set_index(['month', 'category_name'])['total']
    month_bars['prior'] = [last_year_spend.get((m - pd.DateOffset(years=1), c)) for m, c in zip(month_bars['month'], month_bars['name'])]
    month_bars['color'] = month_bars['name'].map(category_colors).fillna(OTHER)
    st.altair_chart(line_chart(trends, 'month', 'total', 'category', '%b %Y', category_colors, category_help=True,
                               monthly=True, prior='prior', month_bars=month_bars).properties(height=400),
                    use_container_width=True)

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
        st.subheader('Assets by Type', help=LINE_CLICK_HELP)
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
        mix_labels = end_labels(mix_ends, mix.encoding.x, 'mid', 'account_group', group_scale, '.0%', gap=0.05, top=1, floor=0)
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

for i, tab in enumerate((net_worth_tab, this_month_tab, this_year_tab, transactions_tab)):
    with tab, st.container(horizontal_alignment='center', key=f'dancer-{i}'):
        st.image(DANCING_ICON)

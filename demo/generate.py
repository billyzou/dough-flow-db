#!/usr/bin/env python3
"""
generate.py

Fills the demo database's bronze tables with a made-up household, shaped like the Plaid payloads
scripts/ingest_plaid.py stores, so the real dbt models build silver and gold from it unchanged.
Nothing here comes from the real data: a two-income couple in Seattle with a mortgage, at banks
and brokerages the real setup doesn't use.

Every run rebuilds everything from 2025-01-01 through yesterday. The randomness is seeded and
drawn day by day in order, so earlier days come out the same each run and only new days are
added. Prices are real Yahoo Finance closes.

Only writes to the demo database: it stops unless the database is named dough_flow_demo and has
the ops.demo_marker table, which only postgres-demo creates (demo/demo_marker.sql).

Run by demo/refresh.sh in the demo-pipeline container; see docker-compose.yml.
"""
import bisect
import hashlib
import json
import math
import os
import random
import string
import sys
from datetime import date, datetime, time, timedelta, timezone

import psycopg2
import requests
from psycopg2.extras import Json, execute_values

DEMO_DATABASE = 'dough_flow_demo'
SEED = 'dough-flow-demo-v1'
START = date(2025, 1, 1)
# initial positions were bought over these years, so holdings history is rebuilt back to here
FIRST_LOT = date(2019, 1, 7)
CHART_URL = 'https://query1.finance.yahoo.com/v8/finance/chart/{ticker}'

# Linked accounts get Plaid payloads; the wife's 401k is entered by hand once a month, like the
# real setup's hand-entered accounts
ACCOUNTS = [
    dict(key='checking', id=1, name='Joint Checking - 4821', institution='Bank of America', enrollment='BANK_OF_AMERICA',
         type='depository', subtype='checking', plaid_name='Adv Plus Banking', owner=None),
    dict(key='savings', id=2, name='Joint Savings - 0937', institution='Ally Bank', enrollment='ALLY',
         type='depository', subtype='savings', plaid_name='Online Savings Account', owner=None),
    dict(key='venture', id=3, name='Venture X - 6203', institution='Capital One', enrollment='CAPITAL_ONE',
         type='credit', subtype='credit card', plaid_name='Venture X', owner='husband'),
    dict(key='discover', id=4, name='Discover it - 1158', institution='Discover', enrollment='DISCOVER',
         type='credit', subtype='credit card', plaid_name='Discover it Card', owner='wife'),
    dict(key='brokerage', id=5, name='Brokerage - 5519', institution='Vanguard', enrollment='VANGUARD',
         type='investment', subtype='brokerage', plaid_name='Individual Brokerage Account', owner='husband'),
    dict(key='roth', id=6, name='Roth IRA - 3390', institution='Vanguard', enrollment='VANGUARD',
         type='investment', subtype='roth', plaid_name='Roth IRA Brokerage Account', owner='wife'),
    dict(key='401k', id=7, name='401k - 7702', institution='Empower', enrollment='EMPOWER',
         type='investment', subtype='401k', plaid_name='Brightline Software 401(k) Plan', owner='husband'),
    dict(key='wife_401k', id=8, name='401k - 2264', institution='Principal', type='investment', owner='wife',
         manual=True),
]
LINKED = [a for a in ACCOUNTS if not a.get('manual')]

SECURITIES = {
    'VTI': ('Vanguard Total Stock Market ETF', 'etf'),
    'VXUS': ('Vanguard Total International Stock ETF', 'etf'),
    'BND': ('Vanguard Total Bond Market ETF', 'etf'),
    'VOO': ('Vanguard S&P 500 ETF', 'etf'),
    'AAPL': ('Apple Inc.', 'equity'),
    'MSFT': ('Microsoft Corporation', 'equity'),
    'VFIFX': ('Vanguard Target Retirement 2050 Fund', 'mutual fund'),
}
# value of each position on START, built up from lots bought since FIRST_LOT
INITIAL_POSITIONS = {
    'brokerage': {'VTI': 58_000, 'VXUS': 21_000, 'BND': 14_000, 'AAPL': 16_000, 'MSFT': 11_000},
    'roth': {'VOO': 34_000, 'VXUS': 12_000},
}
INITIAL_CASH = {'brokerage': 640.18, 'roth': 85.42}
# where new contributions go
TARGETS = {'brokerage': {'VTI': .60, 'VXUS': .25, 'BND': .15}, 'roth': {'VOO': .70, 'VXUS': .30}}

# Daily spending habits. per_month is how often on average, mean the typical amount, sd how much
# it varies (lognormal). Each shop is (merchant name, how the bank describes it); {r} becomes a
# random reference. Local habits mostly stop while the household is away on a trip.
WEEKDAYS = {  # Monday first
    'even': [1] * 7,
    'weekend': [.7, .7, .8, .9, 1.3, 1.6, 1.0],
    'weekday': [1.2, 1.25, 1.25, 1.2, 1.1, .55, .45],
    'errands': [.8, .8, .9, .9, 1.0, 1.5, 1.1],
}
GROCERIES = ('FOOD_AND_DRINK', 'FOOD_AND_DRINK_GROCERIES')
RESTAURANT = ('FOOD_AND_DRINK', 'FOOD_AND_DRINK_RESTAURANT')
HABITS = [
    dict(cat=GROCERIES, per_month=4.0, mean=76, sd=.35, card='discover', days='errands',
         shops=[("Trader Joe's", 'TRADER JOE S #131')]),
    dict(cat=GROCERIES, per_month=3.0, mean=58, sd=.5, card='discover', days='errands',
         shops=[('QFC', 'QFC #5853'), ('Safeway', 'SAFEWAY #1885')]),
    dict(cat=GROCERIES, per_month=1.5, mean=41, sd=.45, card='discover', days='errands',
         shops=[('PCC Community Markets', 'PCC COMMUNITY MARKETS')]),
    # Costco takes only Visa, so it goes on the Venture X
    dict(cat=GROCERIES, per_month=1.3, mean=248, sd=.3, card='venture', days='errands',
         shops=[('Costco', 'COSTCO WHSE #0001')]),
    dict(cat=RESTAURANT, per_month=9.0, mean=72, sd=.55, card='venture', days='weekend', months={12: 1.3},
         shops=[('Din Tai Fung', 'DIN TAI FUNG BELLEVUE'), ("Ivar's", 'IVARS ACRES OF CLAMS'),
                ('Pagliacci Pizza', 'PAGLIACCI PIZZA #11'), ('Tamarind Tree', 'TST* TAMARIND TREE'),
                ('Paseo', 'SQ *PASEO'), ('The Pink Door', 'TST* THE PINK DOOR'), ('Ba Bar', 'TST* BA BAR'),
                ('Taylor Shellfish', 'TAYLOR SHELLFISH OYSTER'), ('Tacos Chukis', 'SQ *TACOS CHUKIS'),
                ('Marination', 'MARINATION MA KAI'), ('Kedai Makan', 'TST* KEDAI MAKAN'), ("Rocco's", 'ROCCOS')]),
    dict(cat=('FOOD_AND_DRINK', 'FOOD_AND_DRINK_FAST_FOOD'), per_month=3.0, mean=24, sd=.4, card='venture',
         days='even', shops=[('Chipotle', 'CHIPOTLE 1834'), ("Dick's Drive-In", "DICK'S DRIVE IN #7"),
                             ('Taco Time', 'TACO TIME NW #38'), ('Chick-fil-A', 'CHICK-FIL-A #04162')]),
    dict(cat=('FOOD_AND_DRINK', 'FOOD_AND_DRINK_COFFEE'), per_month=11.0, mean=7.2, sd=.3, card='discover',
         days='weekday', shops=[('Starbucks', 'STARBUCKS STORE 10475'), ('Caffe Vita', 'SQ *CAFFE VITA'),
                                ('Espresso Vivace', 'ESPRESSO VIVACE'), ('Victrola Coffee', 'SQ *VICTROLA COFFEE')]),
    dict(cat=RESTAURANT, per_month=2.5, mean=48, sd=.3, card='venture', days='weekend', channel='online',
         shops=[('DoorDash', 'DOORDASH*{r}'), ('Uber Eats', 'UBER *EATS {r}')]),
    dict(cat=('FOOD_AND_DRINK', 'FOOD_AND_DRINK_BEER_WINE_AND_LIQUOR'), per_month=1.6, mean=58, sd=.5,
         card='venture', days='weekend', shops=[('Fremont Brewing', 'FREMONT BREWING CO'),
                                                 ('Stoup Brewing', 'SQ *STOUP BREWING'), ('Canon', 'TST* CANON')]),
    dict(cat=('GENERAL_MERCHANDISE', 'GENERAL_MERCHANDISE_ONLINE_MARKETPLACES'), per_month=9.0, mean=41, sd=.8,
         card='venture', days='even', channel='online', local=False, months={11: 1.4, 12: 2.2, 1: .8},
         shops=[('Amazon', 'AMAZON MKTPL*{r}'), ('Amazon', 'Amazon.com*{r}')]),
    dict(cat=('GENERAL_MERCHANDISE', 'GENERAL_MERCHANDISE_SUPERSTORES'), per_month=1.8, mean=64, sd=.6,
         card='discover', days='errands', months={11: 1.3, 12: 2.0}, shops=[('Target', 'TARGET 00012385')]),
    dict(cat=('HOME_IMPROVEMENT', 'HOME_IMPROVEMENT_HARDWARE'), per_month=.6, mean=92, sd=.7, card='venture',
         days='errands', months={4: 1.6, 5: 1.6}, shops=[('The Home Depot', 'THE HOME DEPOT #4702')]),
    dict(cat=('GENERAL_MERCHANDISE', 'GENERAL_MERCHANDISE_SPORTING_GOODS'), per_month=.35, mean=118, sd=.6,
         card='venture', days='errands', shops=[('REI', 'REI #11 SEATTLE')]),
    dict(cat=('GENERAL_MERCHANDISE', 'GENERAL_MERCHANDISE_CLOTHING_AND_ACCESSORIES'), per_month=.65, mean=96,
         sd=.6, card='discover', days='errands', months={11: 1.5, 12: 2.0},
         shops=[('Uniqlo', 'UNIQLO U-VILLAGE'), ('Nordstrom', 'NORDSTROM #0001')]),
    dict(cat=('GENERAL_MERCHANDISE', 'GENERAL_MERCHANDISE_ELECTRONICS'), per_month=.15, mean=240, sd=.6,
         card='venture', days='errands', months={11: 2.0, 12: 2.0}, shops=[('Best Buy', 'BEST BUY 00001156')]),
    dict(cat=('HOME_IMPROVEMENT', 'HOME_IMPROVEMENT_FURNITURE'), per_month=.12, mean=285, sd=.5, card='venture',
         days='errands', shops=[('IKEA', 'IKEA RENTON')]),
    dict(cat=('GENERAL_MERCHANDISE', 'GENERAL_MERCHANDISE_BOOKSTORES_AND_NEWSSTANDS'), per_month=.35, mean=31,
         sd=.4, card='discover', days='weekend', months={12: 2.0},
         shops=[('Elliott Bay Book Company', 'ELLIOTT BAY BOOK CO')]),
    dict(cat=('GENERAL_MERCHANDISE', 'GENERAL_MERCHANDISE_GIFTS_AND_NOVELTIES'), per_month=.3, mean=42, sd=.5,
         card='discover', days='even', channel='online', local=False, months={12: 2.5},
         shops=[('Etsy', 'ETSY.COM*{r}')]),
    dict(cat=('TRANSPORTATION', 'TRANSPORTATION_GAS'), per_month=3.2, mean=56, sd=.2, card='discover',
         days='even', shops=[('Shell', 'SHELL OIL 57444'), ('Chevron', 'CHEVRON 0207561')]),
    dict(cat=('TRANSPORTATION', 'TRANSPORTATION_TAXIS_AND_RIDE_SHARES'), per_month=2.5, mean=23, sd=.5,
         card='venture', days='weekend', channel='online', shops=[('Uber', 'UBER *TRIP {r}'), ('Lyft', 'LYFT *RIDE {r}')]),
    dict(cat=('TRANSPORTATION', 'TRANSPORTATION_PARKING'), per_month=2.0, mean=11, sd=.5, card='venture',
         days='weekend', channel='online', shops=[('PayByPhone', 'PAYBYPHONE SEATTLE')]),
    dict(cat=('TRANSPORTATION', 'TRANSPORTATION_PUBLIC_TRANSIT'), per_month=.5, mean=50, sd=.2, card='discover',
         days='weekday', channel='online', shops=[('ORCA', 'ORCA CARD')]),
    dict(cat=('ENTERTAINMENT', 'ENTERTAINMENT_TV_AND_MOVIES'), per_month=.5, mean=36, sd=.3, card='venture',
         days='weekend', shops=[('AMC Theatres', 'AMC 1137 ONLINE'), ('SIFF', 'SIFF CINEMA EGYPTIAN')]),
    dict(cat=('ENTERTAINMENT', 'ENTERTAINMENT_SPORTING_EVENTS_AMUSEMENT_PARKS_AND_MUSEUMS'), per_month=.2,
         mean=190, sd=.5, card='venture', days='even', channel='online', local=False,
         shops=[('Ticketmaster', 'TICKETMASTER {r}')]),
    dict(cat=('ENTERTAINMENT', 'ENTERTAINMENT_VIDEO_GAMES'), per_month=.35, mean=26, sd=.5, card='venture',
         days='weekend', channel='online', local=False, shops=[('Steam', 'STEAMGAMES.COM {r}')]),
    dict(cat=('MEDICAL', 'MEDICAL_PHARMACIES_AND_SUPPLEMENTS'), per_month=1.1, mean=23, sd=.6, card='discover',
         days='errands', shops=[('Walgreens', 'WALGREENS #7718')]),
    dict(cat=('MEDICAL', 'MEDICAL_PRIMARY_CARE'), per_month=.25, mean=40, sd=.2, card='discover', days='weekday',
         shops=[('Swedish Medical Center', 'SWEDISH MEDICAL CENTER')]),
]
# same day every month: (day, account, Plaid category, merchant, description, amount by year)
SUBSCRIPTIONS = [
    (3, 'venture', ('ENTERTAINMENT', 'ENTERTAINMENT_TV_AND_MOVIES'), 'The New York Times', 'NYTIMES*NYTIMES.COM', {2025: 25.00}),
    (8, 'venture', ('ENTERTAINMENT', 'ENTERTAINMENT_TV_AND_MOVIES'), 'Netflix', 'NETFLIX.COM', {2025: 17.99, 2026: 19.99}),
    (12, 'venture', ('ENTERTAINMENT', 'ENTERTAINMENT_MUSIC_AND_AUDIO'), 'Spotify', 'SPOTIFY USA', {2025: 19.99, 2026: 21.99}),
    (21, 'venture', ('ENTERTAINMENT', 'ENTERTAINMENT_TV_AND_MOVIES'), 'Disney+', 'DISNEY PLUS', {2025: 15.99, 2026: 18.99}),
    (17, 'discover', ('GENERAL_SERVICES', 'GENERAL_SERVICES_OTHER_GENERAL_SERVICES'), 'Apple', 'APPLE.COM/BILL', {2025: 9.99}),
    (1, 'venture', ('PERSONAL_CARE', 'PERSONAL_CARE_GYMS_AND_FITNESS_CENTERS'), 'Seattle Bouldering Project',
     'SEATTLE BOULDERING PROJ', {2025: 196.00, 2026: 210.00}),
    (5, 'venture', ('GENERAL_SERVICES', 'GENERAL_SERVICES_INSURANCE'), 'GEICO', 'GEICO *AUTO', {2025: 171.40, 2026: 188.62}),
    (14, 'venture', ('RENT_AND_UTILITIES', 'RENT_AND_UTILITIES_INTERNET_AND_CABLE'), 'Comcast', 'COMCAST XFINITY',
     {2025: 89.99, 2026: 94.99}),
    (26, 'discover', ('RENT_AND_UTILITIES', 'RENT_AND_UTILITIES_TELEPHONE'), 'T-Mobile', 'T-MOBILE*AUTO PAY', {2025: 142.17}),
]
# once a year: (month, day, account, Plaid category, merchant, description, amount by year)
ANNUAL = [
    (3, 9, 'venture', ('GENERAL_MERCHANDISE', 'GENERAL_MERCHANDISE_ONLINE_MARKETPLACES'), 'Amazon',
     'AMAZON PRIME*{r}', {2025: 139.00}),
    (6, 11, 'venture', ('GENERAL_MERCHANDISE', 'GENERAL_MERCHANDISE_SUPERSTORES'), 'Costco', 'COSTCO *ANNUAL RENEWAL',
     {2025: 130.00}),
    (8, 14, 'checking', ('GOVERNMENT_AND_NON_PROFIT', 'GOVERNMENT_AND_NON_PROFIT_GOVERNMENT_DEPARTMENTS_AND_AGENCIES'),
     None, 'WA DOL VEHICLE LICENSING', {2025: 186.75, 2026: 192.25}),
    (3, 18, 'discover', ('MEDICAL', 'MEDICAL_DENTAL_CARE'), 'Pacific Dental', 'PACIFIC DENTAL SEATTLE', {2025: 85.00}),
    (9, 23, 'discover', ('MEDICAL', 'MEDICAL_DENTAL_CARE'), 'Pacific Dental', 'PACIFIC DENTAL SEATTLE', {2025: 85.00}),
]
# every so many days: (days apart, account, Plaid category, merchant, description, typical amount)
EVERY = [
    (35, 'venture', ('PERSONAL_CARE', 'PERSONAL_CARE_HAIR_AND_BEAUTY'), "Rudy's Barbershop", "RUDY'S BARBERSHOP", 45),
    (58, 'discover', ('PERSONAL_CARE', 'PERSONAL_CARE_HAIR_AND_BEAUTY'), 'Gene Juarez', 'GENE JUAREZ SALON', 165),
    (120, 'venture', ('GENERAL_SERVICES', 'GENERAL_SERVICES_AUTOMOTIVE'), 'Jiffy Lube', 'JIFFY LUBE #1923', 105),
]
# One of each kind of trip a year, to a randomly picked place: (airline or None for driving, hotel
# or None for staying with family or in an Airbnb, flight cost per ticket, hotel cost per night,
# rental car, restaurants there)
DESTINATIONS = {
    'spring': [('Alaska Airlines', 'Hilton Palm Springs', 240, 260, True, ["Cheeky's", 'Workshop Kitchen', 'Tac/Quila']),
               ('Alaska Airlines', 'Hotel del Coronado', 260, 340, True, ["Hodad's", 'Puesto', 'Lolita\'s'])],
    'summer': [('Alaska Airlines', 'Westin Maui', 690, 410, True, ["Mama's Fish House", "Leoda's", 'Monkeypod Kitchen']),
               ('Delta Air Lines', 'The Standard High Line', 560, 390, False, ["Katz's Delicatessen", "Joe's Pizza", 'Via Carota'])],
    'holiday': [('Alaska Airlines', None, 470, None, False, ["Lou Malnati's", "Portillo's"]),
                ('Delta Air Lines', None, 520, None, False, ['Franklin Barbecue', 'Veracruz All Natural'])],
    'fall': [(None, None, 0, None, False, ['Pelican Brewing', 'Kiwanda Pub']),
             (None, None, 0, None, False, ['Duck Soup Inn', 'Coho Restaurant'])],
}


class Household:
    """Running balances, holdings and the bronze rows they produce, built one day at a time."""

    def __init__(self, today, prices):
        self.today = today
        self.prices = prices
        self.rng = random.Random(f'{SEED}-days')
        ids = random.Random(f'{SEED}-ids')
        self.plaid_id = {a['key']: ''.join(ids.choices(string.ascii_letters + string.digits, k=37)) for a in LINKED}
        self.security_id = {t: ''.join(ids.choices(string.ascii_letters + string.digits, k=37))
                            for t in [*SECURITIES, 'CASH']}
        self.balance = {'checking': 9_412.37, 'savings': 38_250.00, 'venture': 2_184.66, 'discover': 611.09}
        self.statement = dict(self.balance)  # card balances owed at the last month end
        self.lots = {k: {t: lots for t, lots in initial_lots(k, prices).items()} for k in INITIAL_POSITIONS}
        self.cash = dict(INITIAL_CASH)
        # 401k fund shares: Empower's are Plaid holdings; Principal's only become a monthly hand-entered value
        self.units = {'401k': 158_000 / price_before(prices, 'VFIFX', START),
                      'wife_401k': 88_000 / price_before(prices, 'VFIFX', START)}
        self.trips = plan_trips(today)
        self.away = {d for t in self.trips for d in daterange(t['depart'], t['depart'] + timedelta(days=t['nights']))}
        self.next_due = {i: START + timedelta(days=random.Random(f'{SEED}-every-{i}').randrange(e[0]))
                         for i, e in enumerate(EVERY)}
        self.transactions, self.account_rows, self.holding_rows, self.manual_rows = [], [], [], []

    # ---------- posting ----------
    def charge(self, d, account, amount, description, merchant, cat, ttype='place', channel=None):
        """One transaction, in Plaid's convention: a positive amount is money out of the account."""
        amount = round(amount, 2)
        self.balance[account] += amount if account in ('venture', 'discover') else -amount
        # card purchases post a day or two after they're made
        posted = d + timedelta(days=self.rng.choice([0, 1, 1, 2]) if ttype == 'place' and account in ('venture', 'discover') else 0)
        description = description.replace('{r}', ''.join(self.rng.choices(string.ascii_uppercase + string.digits, k=6)))
        payload = {
            'transaction_id': ''.join(self.rng.choices(string.ascii_letters + string.digits, k=37)),
            'account_id': self.plaid_id[account],
            'amount': amount,
            'iso_currency_code': 'USD',
            'date': posted.isoformat(),
            'authorized_date': d.isoformat(),
            'name': description,
            'merchant_name': merchant,
            'payment_channel': channel or ('online' if ttype == 'online' else 'in store' if ttype == 'place' else 'other'),
            'personal_finance_category': {'primary': cat[0], 'detailed': cat[1], 'confidence_level': 'VERY_HIGH'},
            'transaction_type': ttype,
            'pending': False,
        }
        loaded = min(posted + timedelta(days=1), self.today)
        self.transactions.append((payload, self.enrollment(account), at_6am(loaded)))

    def transfer(self, d, source, target, amount, out_text, in_text, detailed_out, detailed_in):
        """Both sides of a move between two of the household's accounts."""
        self.charge(d, source, amount, out_text, None, ('TRANSFER_OUT', detailed_out), 'special')
        self.charge(d, target, -amount, in_text, None, ('TRANSFER_IN', detailed_in), 'special')

    def income(self, d, account, amount, description, detailed='INCOME_WAGES'):
        self.charge(d, account, -amount, description, None, ('INCOME', detailed), 'special')

    @staticmethod
    def enrollment(account):
        return next(a['enrollment'] for a in LINKED if a['key'] == account)

    # ---------- investing ----------
    def invest(self, d, account, amount):
        """Add cash to a brokerage account and buy whole shares of its targets; the rest stays as cash."""
        self.cash[account] += amount
        budget = self.cash[account]
        for ticker, share in TARGETS[account].items():
            price = price_on(self.prices, ticker, d)
            qty = math.floor(budget * share / price)
            if qty:
                self.lots[account].setdefault(ticker, []).append((d, qty, round(qty * price, 2)))
                self.cash[account] -= qty * price
        self.cash[account] = round(self.cash[account], 2)

    # ---------- one day ----------
    def snapshot(self, d):
        """What Plaid would return at 6am on d: balances and holdings as of the end of the day before."""
        loaded = at_6am(d)
        for a in LINKED:
            key = a['key']
            holdings = self.holdings(key, d) if a['type'] == 'investment' else []
            if holdings:
                current = sum(h['institution_value'] for h in holdings)
                available = None
            else:
                current = round(self.balance[key], 2)
                available = current if a['type'] == 'depository' else round(max(0, 25_000 - current), 2)
            self.account_rows.append((a['enrollment'], a['institution'], self.plaid_id[key], Json({
                'account_id': self.plaid_id[key], 'name': a['plaid_name'], 'official_name': a['plaid_name'],
                'mask': a['name'][-4:], 'type': a['type'], 'subtype': a['subtype'],
                'balances': {'current': round(current, 2), 'available': available, 'iso_currency_code': 'USD'},
            }), loaded))
            for h in holdings:
                self.holding_rows.append((a['enrollment'], self.plaid_id[key], h['security_id'], Json(h), loaded))

    def holdings(self, account, d):
        rows = []
        if account == '401k':
            price = price_before(self.prices, 'VFIFX', d)
            rows.append(self.holding(account, 'VFIFX', self.units['401k'], price, None, []))
        else:
            for ticker, lots in self.lots[account].items():
                held = [lot for lot in lots if lot[0] < d]
                if held:
                    rows.append(self.holding(account, ticker, sum(q for _, q, _ in held), price_before(self.prices, ticker, d),
                                             round(sum(c for _, _, c in held), 2), held))
            rows.append(self.holding(account, 'CASH', self.cash[account], 1.0, None, []))
        return rows

    def holding(self, account, ticker, qty, price, cost_basis, lots):
        return {
            'account_id': self.plaid_id[account], 'security_id': self.security_id[ticker],
            'quantity': round(qty, 4), 'institution_price': round(price, 4),
            'institution_value': round(qty * price, 2), 'cost_basis': cost_basis, 'iso_currency_code': 'USD',
            'tax_lots': [{'quantity': q, 'cost_basis': c, 'original_purchase_datetime': f'{p.isoformat()}T00:00:00Z'}
                         for p, q, c in lots],
        }

    def day(self, d):
        rng = self.rng
        year = d.year
        month_end = (d + timedelta(days=1)).day == 1

        # paychecks: his every other Friday, hers on the 15th and the last business day
        if d.weekday() == 4 and (d - date(2025, 1, 10)).days % 14 == 0:
            self.income(d, 'checking', (4_120 if d < date(2026, 3, 1) else 4_305) + rng.uniform(-6, 6),
                        'BRIGHTLINE SOFTWARE DES:PAYROLL')
            # 401k: $900 of his pay plus a $250 match, under the yearly limit
            self.units['401k'] += 1_150 / price_on(self.prices, 'VFIFX', d)
            if d.month == 3 and d.day <= 14:
                self.income(d, 'checking', 9_640 if year == 2025 else 10_980, 'BRIGHTLINE SOFTWARE DES:PAYROLL BONUS')
        if d == business_day(d.replace(day=15)) or d == business_day(last_day(d)):
            self.income(d, 'checking', 3_310 if year == 2025 else 3_420, 'RIVERSIDE MEDICAL GRP DES:DIR DEP')
            self.units['wife_401k'] += 820 / price_on(self.prices, 'VFIFX', d)

        # fixed costs
        if d == business_day(d.replace(day=1)):
            self.charge(d, 'checking', 3_912.44, 'ROCKET MORTGAGE DES:MTG PYMT', 'Rocket Mortgage',
                        ('LOAN_PAYMENTS', 'LOAN_PAYMENTS_MORTGAGE_PAYMENT'), 'special')
        if d.day == 22:
            # gas heat: highest in January, lowest in July
            winter = (math.cos(2 * math.pi * (d.month - 1) / 12) + 1) / 2
            self.charge(d, 'checking', (92 + 178 * winter) * rng.uniform(.9, 1.1), 'PUGET SOUND ENERGY DES:BILLPAY',
                        'Puget Sound Energy', ('RENT_AND_UTILITIES', 'RENT_AND_UTILITIES_GAS_AND_ELECTRICITY'), 'special')
        if d.day == 9 and d.month % 2:
            # water, sewer and garbage, billed every two months; lawn watering in summer
            self.charge(d, 'checking', (238 + (70 if d.month in (7, 9) else 0)) * rng.uniform(.95, 1.05),
                        'SEATTLE PUBLIC UTIL DES:WEB PAY', 'Seattle Public Utilities',
                        ('RENT_AND_UTILITIES', 'RENT_AND_UTILITIES_WATER'), 'special')
        if (d.month, d.day) in ((4, 28), (10, 28)):
            self.charge(d, 'checking', 4_612.18 if year == 2025 else 4_795.55, 'KING COUNTY TREASURY DES:PROP TAX',
                        'King County', ('GOVERNMENT_AND_NON_PROFIT', 'GOVERNMENT_AND_NON_PROFIT_TAX_PAYMENT'), 'special')
        for day, account, cat, merchant, description, amounts in SUBSCRIPTIONS:
            if d.day == day:
                self.charge(d, account, by_year(amounts, year), description, merchant, cat, 'online')
        for month, day, account, cat, merchant, description, amounts in ANNUAL:
            if (d.month, d.day) == (month, day):
                self.charge(d, account, by_year(amounts, year), description, merchant, cat, 'online')
        for i, (gap, account, cat, merchant, description, mean) in enumerate(EVERY):
            if d >= self.next_due[i] and d not in self.away:
                self.charge(d, account, mean * rng.uniform(.9, 1.15), description, merchant, cat)
                self.next_due[i] = d + timedelta(days=round(gap * rng.uniform(.85, 1.2)))

        # saving and investing
        if d == business_day(d.replace(day=2)):
            self.transfer(d, 'checking', 'savings', 1_500, 'Online Banking transfer to ALLY BANK', 'ONLINE TRANSFER FROM BANK OF AMERICA',
                          'TRANSFER_OUT_SAVINGS', 'TRANSFER_IN_SAVINGS')
        if d == business_day(d.replace(day=3)):
            self.charge(d, 'checking', 3_500, 'VANGUARD DES:BUY INVESTMENT', 'Vanguard',
                        ('TRANSFER_OUT', 'TRANSFER_OUT_INVESTMENT_AND_RETIREMENT_FUNDS'), 'special')
            self.invest(d, 'brokerage', 3_500)
        if d == business_day(date(year, 1, 2)):
            self.charge(d, 'savings', 7_000, 'VANGUARD ROTH IRA CONTRIBUTION', 'Vanguard',
                        ('TRANSFER_OUT', 'TRANSFER_OUT_INVESTMENT_AND_RETIREMENT_FUNDS'), 'special')
            self.invest(d, 'roth', 7_000)

        # card payments: last month's statement balance, in full
        for card, day, out_text, in_text in (('venture', 20, 'CAPITAL ONE DES:MOBILE PMT', 'CAPITAL ONE MOBILE PYMT'),
                                             ('discover', 24, 'DISCOVER DES:E-PAYMENT', 'INTERNET PAYMENT - THANK YOU')):
            if d.day == day and self.statement[card] > 0:
                amount = round(self.statement[card], 2)
                self.charge(d, 'checking', amount, out_text, None, ('LOAN_PAYMENTS', 'LOAN_PAYMENTS_CREDIT_CARD_PAYMENT'), 'special')
                self.charge(d, card, -amount, in_text, None, ('LOAN_PAYMENTS', 'LOAN_PAYMENTS_CREDIT_CARD_PAYMENT'), 'special')

        self.travel(d)
        self.spend(d)

        if month_end:
            # savings interest, falling as rates came down
            rate = .042 - .006 * min(1, (d - START).days / 600)
            self.income(d, 'savings', self.balance['savings'] * rate / 12, 'Interest Paid', 'INCOME_INTEREST_EARNED')
        # keep checking between a cushion and a ceiling, moving the difference to or from savings
        if self.balance['checking'] < 2_500:
            amount = math.ceil((5_000 - self.balance['checking']) / 1_000) * 1_000
            self.transfer(d, 'savings', 'checking', amount, 'TRANSFER TO BANK OF AMERICA', 'Online Banking transfer from ALLY BANK',
                          'TRANSFER_OUT_ACCOUNT_TRANSFER', 'TRANSFER_IN_ACCOUNT_TRANSFER')
        elif month_end and self.balance['checking'] > 22_000:
            amount = math.floor((self.balance['checking'] - 12_000) / 500) * 500
            self.transfer(d, 'checking', 'savings', amount, 'Online Banking transfer to ALLY BANK', 'ONLINE TRANSFER FROM BANK OF AMERICA',
                          'TRANSFER_OUT_SAVINGS', 'TRANSFER_IN_SAVINGS')
        if month_end:
            self.statement = {k: self.balance[k] for k in ('venture', 'discover')}
        # Principal's balance gets entered by hand mid-month
        if d.day == 15 or d == START:
            self.manual_rows.append((8, d, round(self.units['wife_401k'] * price_before(self.prices, 'VFIFX', d), 2)))

    def spend(self, d):
        rng = self.rng
        away = d in self.away
        for h in HABITS:
            p = h['per_month'] * 12 / 365 * WEEKDAYS[h['days']][d.weekday()] * h.get('months', {}).get(d.month, 1)
            if away and h.get('local', True):
                p *= .1
            if rng.random() < p:
                merchant, description = rng.choice(h['shops'])
                ttype = 'online' if h.get('channel') == 'online' else 'place'
                self.charge(d, h['card'], lognormal(rng, h['mean'], h['sd']), description, merchant, h['cat'], ttype)
        # returns: about one Amazon refund a month
        if rng.random() < .7 * 12 / 365:
            self.charge(d, 'venture', -lognormal(rng, 36, .6), 'AMAZON MKTPL*{r} REFUND', 'Amazon',
                        ('GENERAL_MERCHANDISE', 'GENERAL_MERCHANDISE_ONLINE_MARKETPLACES'), 'online')

    def travel(self, d):
        rng = self.rng
        for t in self.trips:
            airline, hotel, ticket, nightly, car, restaurants = t['place']
            back = t['depart'] + timedelta(days=t['nights'])
            if d == t['booked'] and airline:
                for _ in range(2):
                    self.charge(d, 'venture', ticket * t['price'] * rng.uniform(.97, 1.03),
                                f"{airline.upper()} {rng.randrange(10**9, 10**10)}", airline, ('TRAVEL', 'TRAVEL_FLIGHTS'), 'online')
            if t['depart'] <= d < back:
                for _ in range(rng.choice([1, 2, 2, 3])):
                    name = rng.choice(restaurants)
                    self.charge(d, 'venture', lognormal(rng, 64, .5), f'TST* {name.upper()}', name, RESTAURANT)
                if rng.random() < .4:
                    self.charge(d, 'venture', lognormal(rng, 28, .4), 'UBER *TRIP {r}', 'Uber',
                                ('TRANSPORTATION', 'TRANSPORTATION_TAXIS_AND_RIDE_SHARES'), 'online')
            if d == back and hotel:
                self.charge(d, 'venture', nightly * t['price'] * t['nights'] * 1.16, hotel.upper(), hotel,
                            ('TRAVEL', 'TRAVEL_LODGING'))
            if d == back and car:
                self.charge(d, 'venture', 68 * t['nights'] * rng.uniform(.9, 1.2), 'HERTZ CAR RENTAL', 'Hertz',
                            ('TRAVEL', 'TRAVEL_RENTAL_CARS'))
            if d == t['depart'] and t['kind'] == 'fall':
                # a weekend road trip: the Airbnb was paid when booked; gas on the way
                self.charge(d, 'discover', lognormal(rng, 61, .15), 'CHEVRON 0098772', 'Chevron',
                            ('TRANSPORTATION', 'TRANSPORTATION_GAS'))
            if d == t['booked'] and t['kind'] == 'fall':
                self.charge(d, 'venture', 560 * t['price'], 'AIRBNB * HM{r}', 'Airbnb', ('TRAVEL', 'TRAVEL_LODGING'), 'online')


def plan_trips(today):
    """Each year: a spring getaway, a summer vacation, a fall road trip and the holidays with family.
    Planned with a generator per year, so adding a year doesn't change earlier ones."""
    trips = []
    for year in range(START.year, today.year + 2):
        rng = random.Random(f'{SEED}-trips-{year}')
        plans = [
            ('spring', date(year, rng.choice([3, 4, 5]), rng.randint(1, 24)), rng.choice([3, 4])),
            ('summer', date(year, rng.choice([7, 8]), rng.randint(1, 20)), rng.choice([7, 8, 9])),
            ('fall', date(year, rng.choice([9, 10]), rng.randint(1, 25)), 2),
            ('holiday', date(year, 12, rng.randint(19, 22)), rng.choice([5, 6])),
        ]
        for kind, depart, nights in plans:
            # flights are booked one to three months ahead; the fall road trip's Airbnb a month ahead
            trips.append(dict(kind=kind, depart=depart, nights=nights, place=rng.choice(DESTINATIONS[kind]),
                              price=rng.uniform(.85, 1.2),
                              booked=depart - timedelta(days=30 if kind == 'fall' else rng.randint(30, 80))))
    return trips


def initial_lots(account, prices):
    """Whole-share purchases since FIRST_LOT, scaled so each position is worth its target on START."""
    rng = random.Random(f'{SEED}-lots-{account}')
    out = {}
    for ticker, target in INITIAL_POSITIONS[account].items():
        if account == 'roth':
            # Roth contributions: once a year, early January
            dates = [business_day(date(y, 1, rng.randint(2, 10))) for y in range(FIRST_LOT.year, START.year)]
        else:
            n = rng.randint(3, 5) if SECURITIES[ticker][1] == 'equity' else rng.randint(9, 14)
            span = (date(2024, 12, 15) - FIRST_LOT).days
            dates = sorted(business_day(FIRST_LOT + timedelta(days=rng.randrange(span))) for _ in range(n))
        weights = [rng.uniform(.5, 1.5) for _ in dates]
        # shares each lot would buy per dollar of weight, then scale to the target value
        raw = [w / price_on(prices, ticker, d) for w, d in zip(weights, dates)]
        scale = target / (sum(raw) * price_before(prices, ticker, START))
        lots = []
        for d, r in zip(dates, raw):
            qty = max(1, round(r * scale))
            lots.append((d, qty, round(qty * price_on(prices, ticker, d), 2)))
        out[ticker] = lots
    return out


# ---------- helpers ----------
def daterange(start, end):
    return [start + timedelta(days=i) for i in range((end - start).days)]


def last_day(d):
    return (d.replace(day=28) + timedelta(days=4)).replace(day=1) - timedelta(days=1)


def business_day(d):
    """d, moved off a weekend: to the next Monday early in the month (bills), else the Friday before (paydays)."""
    step = timedelta(days=1 if d.day < 15 else -1)
    while d.weekday() >= 5:
        d += step
    return d


def by_year(amounts, year):
    # amounts are keyed by the year a price took effect
    return amounts[max(y for y in amounts if y <= year)]


def lognormal(rng, mean, sd):
    return mean * math.exp(rng.gauss(0, sd) - sd * sd / 2)


def at_6am(d):
    # the real ingest runs at 6am Pacific
    return datetime.combine(d, time(13, 0), timezone.utc)


def price_on(prices, ticker, d):
    """Close on d, or the last trading day before it."""
    days, closes = prices[ticker]
    return closes[bisect.bisect_right(days, d) - 1]


def price_before(prices, ticker, d):
    """The previous close, as a morning snapshot sees it."""
    days, closes = prices[ticker]
    return closes[bisect.bisect_left(days, d) - 1]


def fetch_closes(ticker, start, end):
    """[(date, close)] for trading days from start to end, split-adjusted (as scripts/backfill_prices.py)."""
    resp = requests.get(
        CHART_URL.format(ticker=ticker),
        params={'period1': int(datetime.combine(start, time(), timezone.utc).timestamp()),
                'period2': int(datetime.combine(end + timedelta(days=1), time(), timezone.utc).timestamp()),
                'interval': '1d'},
        headers={'User-Agent': 'Mozilla/5.0'},
        timeout=30,
    )
    resp.raise_for_status()
    result = resp.json()['chart']['result'][0]
    days = [datetime.fromtimestamp(t, timezone.utc).date() for t in result.get('timestamp', [])]
    return [(d, c) for d, c in zip(days, result['indicators']['quote'][0]['close']) if c is not None]


def connect_to_demo_database():
    conn = psycopg2.connect(host=os.environ['DB_HOST'], port=os.environ['DB_PORT'], dbname=os.environ['DB_NAME'],
                            user=os.environ['DB_USER'], password=os.environ['DB_PASSWORD'])
    with conn.cursor() as cur:
        cur.execute("select current_database(), to_regclass('ops.demo_marker') is not null")
        name, marked = cur.fetchone()
    if name != DEMO_DATABASE or not marked:
        conn.close()
        sys.exit(f'Refusing to write: database {name!r} is not the demo database')
    return conn


def main():
    conn = connect_to_demo_database()
    with conn.cursor() as cur:
        cur.execute('select current_date')
        today = cur.fetchone()[0]

    # prices first: if Yahoo is down, nothing is touched and yesterday's demo data stays
    prices = {}
    for ticker in [*SECURITIES, 'SPY']:
        closes = fetch_closes(ticker, FIRST_LOT - timedelta(days=30), today - timedelta(days=1))
        prices[ticker] = ([d for d, _ in closes], [c for _, c in closes])

    house = Household(today, prices)
    for d in daterange(START, today + timedelta(days=1)):
        house.snapshot(d)
        if d < today:
            house.day(d)

    with conn, conn.cursor() as cur:
        cur.execute("""
            truncate bronze.accounts, bronze.plaid_transactions, bronze.plaid_accounts, bronze.plaid_holdings,
                     bronze.plaid_securities, bronze.plaid_investment_transactions, bronze.security_prices,
                     bronze.manual_balances, bronze.category_overrides, bronze.legacy_transactions,
                     bronze.legacy_account_balances, ops.pipeline_runs
            restart identity cascade
        """)
        execute_values(cur, 'insert into bronze.accounts (account_id, external_account_id, name, type, institution, owner) values %s', [
            (a['id'], house.plaid_id.get(a['key']), a['name'],
             a['type'] if a.get('manual') else None, a['institution'] if a.get('manual') else None, a['owner'])
            for a in ACCOUNTS])
        cur.execute("select setval('bronze.accounts_account_id_seq', %s)", (len(ACCOUNTS),))
        execute_values(cur, 'insert into bronze.plaid_transactions (plaid_transaction_id, payload_hash, enrollment, payload, loaded_at) values %s', [
            (p['transaction_id'], hashlib.md5(json.dumps(p, sort_keys=True).encode()).hexdigest(), e, Json(p), loaded)
            for p, e, loaded in house.transactions], page_size=1000)
        execute_values(cur, 'insert into bronze.plaid_accounts (enrollment, institution_name, plaid_account_id, payload, loaded_at) values %s',
                       house.account_rows, page_size=1000)
        execute_values(cur, 'insert into bronze.plaid_holdings (enrollment, plaid_account_id, security_id, payload, loaded_at) values %s',
                       house.holding_rows, page_size=1000)
        securities = [(t, *SECURITIES[t]) for t in SECURITIES] + [('CASH', 'U S Dollar', 'cash')]
        execute_values(cur, 'insert into bronze.plaid_securities (enrollment, security_id, payload, loaded_at) values %s', [
            ('VANGUARD' if t != 'VFIFX' else 'EMPOWER', house.security_id[t], Json({
                'security_id': house.security_id[t], 'ticker_symbol': 'CUR:USD' if t == 'CASH' else t, 'name': name,
                'type': kind, 'is_cash_equivalent': kind == 'cash',
                'close_price': 1.0 if t == 'CASH' else round(price_before(prices, t, today), 4)}), at_6am(today))
            for t, name, kind in securities])
        execute_values(cur, 'insert into bronze.security_prices (ticker, price_date, close) values %s', [
            (t, d, round(c, 6)) for t, (days, closes) in prices.items() for d, c in zip(days, closes)], page_size=5000)
        execute_values(cur, 'insert into bronze.manual_balances (account_id, snapshot_date, balance, entered_at) values %s',
                       [(a, d, b, at_6am(d)) for a, d, b in house.manual_rows])
        enrollments = sorted({a['enrollment'] for a in LINKED})
        execute_values(cur, 'insert into ops.pipeline_runs (enrollment, started_at, finished_at, success, rows_seen, rows_inserted, rows_skipped) values %s', [
            (e, at_6am(d) + timedelta(minutes=2), at_6am(d) + timedelta(minutes=3), True, 0, 0, 0)
            for d in daterange(today - timedelta(days=7), today + timedelta(days=1)) for e in enrollments
            # the database's date is UTC, so today's 6am run can still be ahead
            if at_6am(d) < datetime.now(timezone.utc)])

    print(f'demo data through {today - timedelta(days=1)}: {len(house.transactions):,} transactions, '
          f'{len(house.account_rows):,} balance snapshots, {len(house.holding_rows):,} holding snapshots')


if __name__ == '__main__':
    main()

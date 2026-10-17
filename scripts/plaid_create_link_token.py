#!/usr/bin/env python3
"""
plaid_create_link_token.py

Mints a Plaid link_token for use with plaid_link.html.
Run once each time you want to open Plaid Link — link_tokens expire after 30 minutes.

Usage:
    python3 scripts/plaid_create_link_token.py
    # copy the printed link_token into plaid_link.html when prompted

    python3 scripts/plaid_create_link_token.py BROKERAGE
    # update mode: re-links PLAID_TOKEN_BROKERAGE and asks for investments consent.
    # The access_token stays the same, so skip plaid_exchange_public_token.py afterwards.

    python3 scripts/plaid_create_link_token.py NEW_BROKERAGE
    # a label with no PLAID_TOKEN_<LABEL> yet: a new investments link (plus transactions
    # where the bank supports them). Exchange the public_token as usual.
"""
import os
import sys

from dotenv import load_dotenv
import plaid
from plaid.api import plaid_api
from plaid.model.link_token_create_request import LinkTokenCreateRequest
from plaid.model.link_token_create_request_user import LinkTokenCreateRequestUser
from plaid.model.country_code import CountryCode
from plaid.model.products import Products

load_dotenv(dotenv_path=os.path.join(os.path.dirname(__file__), '..', '.env'))

PLAID_ENV_MAP = {
    'sandbox':    plaid.Environment.Sandbox,
    'production': plaid.Environment.Production,
}

env_name = os.environ.get('PLAID_ENV', 'production').lower()
config = plaid.Configuration(
    host=PLAID_ENV_MAP.get(env_name, plaid.Environment.Production),
    api_key={
        'clientId': os.environ['PLAID_CLIENT_ID'],
        'secret':   os.environ['PLAID_SECRET'],
    },
)
client = plaid_api.PlaidApi(plaid.ApiClient(config))

label = sys.argv[1].upper() if len(sys.argv) > 1 else None
if label and f'PLAID_TOKEN_{label}' in os.environ:
    # Update mode: an existing Item takes access_token instead of products
    mode = {
        'access_token': os.environ[f'PLAID_TOKEN_{label}'],
        'additional_consented_products': [Products('investments')],
    }
elif label:
    mode = {
        'products': [Products('investments')],
        'required_if_supported_products': [Products('transactions')],
    }
else:
    mode = {'products': [Products('transactions')]}

response = client.link_token_create(
    LinkTokenCreateRequest(
        user=LinkTokenCreateRequestUser(client_user_id=os.environ.get('DB_USER', 'user')),
        client_name='dough-flow-db',
        country_codes=[CountryCode('US')],
        language='en',
        **mode,
    )
)

print()
print(f'Environment : {env_name}')
print(f'link_token  : {response["link_token"]}')
print()
print('Paste the link_token into plaid_link.html and open it in a browser.')
print('link_tokens expire after 30 minutes.')

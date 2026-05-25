#!/usr/bin/env python3
"""
plaid_create_link_token.py

Mints a Plaid link_token for use with plaid_link.html.
Run once each time you want to open Plaid Link — link_tokens expire after 30 minutes.

Usage:
    python3 scripts/plaid_create_link_token.py
    # copy the printed link_token into plaid_link.html when prompted
"""
import os

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

response = client.link_token_create(
    LinkTokenCreateRequest(
        user=LinkTokenCreateRequestUser(client_user_id=os.environ.get('DB_USER', 'user')),
        client_name='dough-flow-db',
        products=[Products('transactions')],
        country_codes=[CountryCode('US')],
        language='en',
    )
)

print()
print(f'Environment : {env_name}')
print(f'link_token  : {response["link_token"]}')
print()
print('Paste the link_token into plaid_link.html and open it in a browser.')
print('link_tokens expire after 30 minutes.')

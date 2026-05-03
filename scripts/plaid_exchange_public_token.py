#!/usr/bin/env python3
"""
plaid_exchange_public_token.py

Exchanges a public_token (from Plaid Link onSuccess) for a permanent access_token.

Usage:
    python3 scripts/plaid_exchange_public_token.py <public_token>
    # add the printed PLAID_TOKEN_<BANK>=... line to .env
"""
import os
import sys

from dotenv import load_dotenv
import plaid
from plaid.api import plaid_api
from plaid.model.item_public_token_exchange_request import ItemPublicTokenExchangeRequest

load_dotenv(dotenv_path=os.path.join(os.path.dirname(__file__), '..', '.env'))

if len(sys.argv) != 2:
    raise SystemExit('Usage: python3 scripts/plaid_exchange_public_token.py <public_token>')

public_token = sys.argv[1]

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

response = client.item_public_token_exchange(
    ItemPublicTokenExchangeRequest(public_token=public_token)
)

access_token = response['access_token']
item_id = response['item_id']

print()
print(f'item_id      : {item_id}')
print(f'access_token : {access_token}')
print()
print('Add to .env as (replace BANK with a label like CHASE, AMEX, etc.):')
print(f'PLAID_TOKEN_BANK={access_token}')

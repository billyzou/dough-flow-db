#!/usr/bin/env python3
"""
plaid_sandbox_token.py

One-shot helper: mints a sandbox public_token for Plaid's fake bank
("First Platypus Bank", ins_109508), exchanges it for an access_token,
and prints the result. Copy the access_token line into .env as
PLAID_TOKEN_SANDBOX=access-sandbox-...
"""
import os

from dotenv import load_dotenv
import plaid
from plaid.api import plaid_api
from plaid.model.products import Products
from plaid.model.sandbox_public_token_create_request import SandboxPublicTokenCreateRequest
from plaid.model.item_public_token_exchange_request import ItemPublicTokenExchangeRequest

load_dotenv(dotenv_path=os.path.join(os.path.dirname(__file__), '..', '.env'))

config = plaid.Configuration(
    host=plaid.Environment.Sandbox,
    api_key={
        'clientId': os.environ['PLAID_CLIENT_ID'],
        'secret':   os.environ['PLAID_SECRET'],
    },
)
client = plaid_api.PlaidApi(plaid.ApiClient(config))

pt = client.sandbox_public_token_create(
    SandboxPublicTokenCreateRequest(
        institution_id='ins_109508',
        initial_products=[Products('transactions')],
    )
)['public_token']

access_token = client.item_public_token_exchange(
    ItemPublicTokenExchangeRequest(public_token=pt)
)['access_token']

print()
print('Add this line to .env (replace any existing PLAID_TOKEN_SANDBOX):')
print(f'PLAID_TOKEN_SANDBOX={access_token}')

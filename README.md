# getpaid-bitpay

[![PyPI](https://img.shields.io/pypi/v/python-getpaid-bitpay.svg)](https://pypi.org/project/python-getpaid-bitpay/)
[![Python Version](https://img.shields.io/pypi/pyversions/python-getpaid-bitpay)](https://pypi.org/project/python-getpaid-bitpay/)
[![License](https://img.shields.io/pypi/l/python-getpaid-bitpay)](https://github.com/django-getpaid/python-getpaid-bitpay/blob/main/LICENSE)

BitPay payment gateway plugin for the
[python-getpaid](https://github.com/django-getpaid) ecosystem. Provides a
fully async HTTP client (`BitPayClient`) and a payment processor
(`BitPayProcessor`) implementing the
[getpaid-core](https://github.com/django-getpaid/python-getpaid-core)
`BaseProcessor` interface. Communicates with BitPay via their REST API v2
using POS and merchant facade authentication.

> **Status:** Alpha — under active development.

## Architecture

getpaid-bitpay is composed of three layers:

- **Signing** — EC key (secp256k1) generation, compressed public key
  derivation, and ECDSA-SHA256 message signing used by the merchant facade.
- **BitPayClient** — a low-level async HTTP client (built on `httpx`) that
  wraps the BitPay REST API v2 endpoints. Supports POS facade (token-only)
  and merchant facade (EC key signed requests). Can be used as an async
  context manager for connection reuse.
- **BitPayProcessor** — a high-level processor that implements `BaseProcessor`
  from getpaid-core. Translates between the core payment protocol and
  BitPay's API, handles IPN webhooks, PULL status polling, and FSM
  transitions.

### Why not the official SDK?

This plugin uses its own native async HTTP client instead of wrapping the
[official BitPay Python SDK](https://pypi.org/project/bitpay/). The reasons:

1. **Sync-only** — the official SDK uses `requests`, requiring thread
   offloading for every call in an async context.
2. **Pydantic version pinning** — the SDK pins `pydantic==2.11.9` exactly,
   causing dependency conflicts in projects using different Pydantic versions.
3. **Testing opacity** — mocking `requests` inside third-party code is
   fragile; with `httpx` we use `respx` for clean, reliable test doubles.
4. **Minimal surface** — we only need invoices and refunds (6 endpoints), not
   the SDK's 40+ methods.
5. **Small footprint** — the custom client is ~275 lines, a net reduction in
   complexity compared to wrapping the full SDK.

## Key Features

- Invoice creation via POS facade (token-only authentication)
- Invoice retrieval, cancellation via merchant facade (EC key signing)
- Refund creation, retrieval, cancellation via merchant facade
- Callback authenticity verification via `X-Signature` HMAC
- IPN webhook handling for both invoice and refund status changes
- PULL status polling via `fetch_payment_status`
- Two-step payment confirmation (confirm_payment + mark_as_paid)
- Automatic refund completion (confirm_refund + mark_as_refunded)
- Sandbox and production environment support

## Quick Usage

`BitPayClient` can be used standalone as an async context manager:

```python
from getpaid_bitpay.client import BitPayClient

async with BitPayClient(
    base_url="https://test.bitpay.com",
    pos_token="your-pos-token",
) as client:
    invoice = await client.create_invoice(
        price=29.99,
        currency="USD",
        order_id="order-123",
        notification_url="https://example.com/webhooks/bitpay",
    )
    checkout_url = invoice["url"]
```

For merchant facade operations (invoice retrieval, refunds), provide an EC
private key and merchant token:

```python
from getpaid_bitpay.client import BitPayClient
from getpaid_bitpay.signing import generate_pem

# Generate a key pair (do this once, store the PEM securely)
private_key_pem = generate_pem()

async with BitPayClient(
    base_url="https://test.bitpay.com",
    pos_token="your-pos-token",
    merchant_token="your-merchant-token",
    private_key_pem=private_key_pem,
) as client:
    invoice = await client.get_invoice("invoice-id-123")
    refund = await client.create_refund(
        invoice_id="invoice-id-123",
        amount=10.0,
    )
```

## Key Generation

BitPay merchant facade requires an EC key pair (secp256k1). The signing
module provides a helper:

```python
from getpaid_bitpay.signing import generate_pem, get_compressed_public_key

# Generate a new private key in PEM format
pem = generate_pem()

# Derive the compressed public key (hex) — needed for BitPay dashboard pairing
public_key_hex = get_compressed_public_key(pem)
print(public_key_hex)  # e.g. "02a1b2c3d4..."
```

Store the PEM string securely (e.g. in environment variables or a secrets
manager). The compressed public key hex is used when pairing with the BitPay
merchant dashboard to obtain your merchant token.

## Configuration

When used via a framework adapter (e.g. django-getpaid, litestar-getpaid),
configuration is provided as a dictionary:

| Key | Type | Required | Description |
|-----|------|----------|-------------|
| `pos_token` | `str` | Yes | POS facade API token from BitPay dashboard |
| `merchant_token` | `str` | No | Merchant facade API token (needed for refunds, invoice retrieval) |
| `private_key_pem` | `str` | No | EC private key in PEM format (needed for merchant facade signing) |
| `sandbox` | `bool` | No | Use sandbox (`test.bitpay.com`) or production (`bitpay.com`). Default: `True` |
| `notification_url` | `str` | No | IPN webhook URL template, e.g. `https://example.com/payments/{payment_id}/notify` |
| `redirect_url` | `str` | No | Redirect URL template after payment, e.g. `https://example.com/payments/{payment_id}/done` |

Example configuration dict:

```python
GETPAID_BACKENDS = {
    "bitpay": {
        "pos_token": "your-pos-token",
        "merchant_token": "your-merchant-token",
        "private_key_pem": "-----BEGIN EC PRIVATE KEY-----\n...",
        "sandbox": True,
        "notification_url": "https://example.com/payments/{payment_id}/notify",
        "redirect_url": "https://example.com/payments/{payment_id}/done",
    }
}
```

> **Note:** `merchant_token` and `private_key_pem` are only required if you
> need merchant facade operations (invoice retrieval, cancellation, refunds).
> Basic invoice creation works with just `pos_token`.

## Status Mapping

### Invoice Statuses

| BitPay Status | FSM Trigger | Description |
|---------------|-------------|-------------|
| `new` | `confirm_prepared` | Invoice created, awaiting payment |
| `paid` | `confirm_payment` | Payment detected, awaiting confirmation |
| `confirmed` | `mark_as_paid` | Payment confirmed on blockchain |
| `complete` | *(none)* | Invoice complete, no further action |
| `expired` | `fail` | Invoice expired without payment |
| `invalid` | `fail` | Payment invalid |
| `declined` | `fail` | Payment declined |

### Refund Statuses

| BitPay Status | FSM Trigger | Description |
|---------------|-------------|-------------|
| `pending` | *(none)* | Refund pending processing |
| `created` | *(none)* | Refund created |
| `preview` | *(none)* | Refund in preview |
| `success` | `confirm_refund` | Refund completed successfully |
| `failure` | `cancel_refund` | Refund failed |
| `cancelled` | `cancel_refund` | Refund cancelled |

## Supported Currencies

BTC, BCH, DOGE, ETH, LTC, MATIC, SHIB, USDC, USDP, BUSD, PAX, XRP, APE,
EUR, GBP, USD, CAD, AUD

## Requirements

- Python 3.12+
- `python-getpaid-core >= 0.1.0`
- `httpx >= 0.27.0`
- `ecdsa >= 0.19.0`
- `anyio >= 4.0`

## Related Projects

- [getpaid-core](https://github.com/django-getpaid/python-getpaid-core) —
  framework-agnostic payment processing library
- [django-getpaid](https://github.com/django-getpaid/django-getpaid) —
  Django framework adapter
- [litestar-getpaid](https://github.com/django-getpaid/litestar-getpaid) —
  Litestar framework adapter

## License

MIT

## Disclaimer

This project has nothing in common with the
[getpaid](http://code.google.com/p/getpaid/) plone project.

## Credits

Created by [Dominik Kozaczko](https://github.com/dekoza).

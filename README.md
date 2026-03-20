# python-getpaid-bitpay

[![PyPI version](https://img.shields.io/pypi/v/python-getpaid-bitpay.svg)](https://pypi.org/project/python-getpaid-bitpay/)
[![Python versions](https://img.shields.io/pypi/pyversions/python-getpaid-bitpay.svg)](https://pypi.org/project/python-getpaid-bitpay/)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](https://opensource.org/licenses/MIT)
[![Documentation Status](https://readthedocs.org/projects/getpaid-bitpay/badge/?version=latest)](https://getpaid-bitpay.readthedocs.io/en/latest/?badge=latest)

**BitPay cryptocurrency payment processor for python-getpaid.**

This is a backend for [python-getpaid](https://github.com/django-getpaid/python-getpaid-core) that integrates [BitPay](https://bitpay.com/) payment gateway. It allows your application to accept both traditional fiat and various cryptocurrencies, with payments optionally converted to fiat or kept in crypto.

## Features

- **Full Async Support**: Built on top of `httpx` and `anyio` for high-performance asynchronous operations.
- **Cryptocurrency Support**: Accept BTC, BCH, ETH, XRP, DOGE, LTC, and stablecoins like USDC, USDT, DAI, WBTC, SHIB.
- **Fiat Support**: Supports over 200 fiat currencies (USD, EUR, GBP, PLN, JPY, CAD, etc.).
- **Dual Facade Support**:
    - **POS Facade**: Lightweight invoice creation using only a POS Token.
    - **Merchant Facade**: Full control including invoice retrieval, cancellation, and refunds (requires private key and merchant token).
- **Secure Webhooks**: Automatic verification of BitPay IPN (Instant Payment Notification) using HMAC-SHA256 signatures.
- **Refunds**: Support for partial and full refunds via the BitPay API.
- **Framework Agnostic**: Works with Django, Litestar, or any other Python web framework via `python-getpaid-core`.

## Why not the official SDK?

This plugin uses its own native async HTTP client instead of wrapping the [official BitPay Python SDK](https://pypi.org/project/bitpay/). The custom implementation provides:
1. **Async-first architecture**: No thread offloading for sync calls.
2. **Minimal dependencies**: Avoids version pinning conflicts (e.g., Pydantic).
3. **Clean testing**: Built-in support for `respx` for reliable test doubles.

## Installation

Install the package using pip:

```bash
pip install python-getpaid-bitpay
```

## Configuration

Add `bitpay` to your `GETPAID_BACKENDS` setting and provide the necessary credentials.

### Basic Configuration (POS Facade)

Only invoice creation is supported with this setup.

```python
GETPAID_BACKENDS = (
    'getpaid_bitpay',
)

GETPAID_BACKEND_SETTINGS = {
    'bitpay': {
        'pos_token': 'your-bitpay-pos-token',
        'notification_url': 'https://your-domain.com/payments/{payment_id}/callback/',
        'redirect_url': 'https://your-domain.com/payments/{payment_id}/success/',
    }
}
```

### Full Configuration (Merchant Facade)

Required for status polling and refunds. Requires an EC private key (secp256k1).

```python
GETPAID_BACKEND_SETTINGS = {
    'bitpay': {
        'pos_token': 'your-bitpay-pos-token',
        'merchant_token': 'your-bitpay-merchant-token',
        'private_key_pem': '-----BEGIN EC PRIVATE KEY-----\n...',
        'sandbox': True,  # Use test.bitpay.com
        'notification_url': 'https://your-domain.com/payments/{payment_id}/callback/',
        'redirect_url': 'https://your-domain.com/payments/{payment_id}/success/',
    }
}
```

## Supported Currencies

### Cryptocurrencies
- **Bitcoin**: BTC, BCH, WBTC
- **Ethereum**: ETH
- **Others**: XRP, DOGE, LTC, SHIB
- **Stablecoins**: USDC, USDT, DAI

### Fiat Currencies
Supports over 200 global currencies including USD, EUR, GBP, PLN, JPY, CAD, AUD, and many more.

## Status Mapping

| BitPay Status | Semantic Event | Description |
|---------------|----------------|-------------|
| `new` | `prepared` | Invoice created, awaiting payment |
| `paid` | `payment_captured` | Payment detected, awaiting confirmation |
| `confirmed` | `payment_captured` | Payment confirmed on blockchain |
| `expired` / `invalid` / `declined` | `failed` | Payment failed or expired |

## Links

- **Core Library**: [python-getpaid-core](https://github.com/django-getpaid/python-getpaid-core)
- **Documentation**: [getpaid-bitpay.readthedocs.io](https://getpaid-bitpay.readthedocs.io/)
- **Source Code**: [github.com/django-getpaid/python-getpaid-bitpay](https://github.com/django-getpaid/python-getpaid-bitpay)
- **BitPay API Documentation**: [bitpay.com/api](https://bitpay.com/api/)

## License

This project is licensed under the MIT License.

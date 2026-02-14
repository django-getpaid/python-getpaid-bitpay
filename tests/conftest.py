"""Shared test fixtures for getpaid-bitpay."""

import pytest

from getpaid_bitpay.signing import generate_pem


@pytest.fixture
def pem_key():
    """A fresh secp256k1 private key in PEM format."""
    return generate_pem()


@pytest.fixture
def pos_token():
    return "test-pos-token-abc123"


@pytest.fixture
def merchant_token():
    return "test-merchant-token-xyz789"

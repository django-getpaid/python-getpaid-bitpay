"""Tests for the public package API."""

import getpaid_bitpay


def test_version() -> None:
    assert getpaid_bitpay.__version__ == "3.0.0a3"

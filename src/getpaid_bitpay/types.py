"""BitPay type definitions, enums, and status mappings."""

from enum import StrEnum
from typing import TypedDict


class InvoiceStatus(StrEnum):
    """BitPay invoice statuses."""

    NEW = "new"
    PAID = "paid"
    CONFIRMED = "confirmed"
    COMPLETE = "complete"
    EXPIRED = "expired"
    INVALID = "invalid"
    DECLINED = "declined"


class RefundStatus(StrEnum):
    """BitPay refund statuses."""

    PENDING = "pending"
    CREATED = "created"
    PREVIEW = "preview"
    SUCCESS = "success"
    FAILURE = "failure"
    CANCELLED = "cancelled"


# Maps BitPay invoice status → getpaid FSM trigger name (or None).
INVOICE_STATUS_MAP: dict[InvoiceStatus, str | None] = {
    InvoiceStatus.NEW: "confirm_prepared",
    InvoiceStatus.PAID: "confirm_payment",
    InvoiceStatus.CONFIRMED: "mark_as_paid",
    InvoiceStatus.COMPLETE: None,
    InvoiceStatus.EXPIRED: "fail",
    InvoiceStatus.INVALID: "fail",
    InvoiceStatus.DECLINED: "fail",
}

# Maps BitPay refund status → getpaid FSM trigger name (or None).
REFUND_STATUS_MAP: dict[RefundStatus, str | None] = {
    RefundStatus.PENDING: None,
    RefundStatus.CREATED: None,
    RefundStatus.PREVIEW: None,
    RefundStatus.SUCCESS: "confirm_refund",
    RefundStatus.FAILURE: "cancel_refund",
    RefundStatus.CANCELLED: "cancel_refund",
}


class InvoiceData(TypedDict, total=False):
    """Data returned from BitPay invoice API."""

    id: str
    url: str
    status: str
    price: float
    currency: str
    order_id: str
    invoice_time: int
    expiration_time: int
    current_time: int
    exception_status: str | bool
    amount_paid: float
    transaction_currency: str
    token: str


class RefundData(TypedDict, total=False):
    """Data returned from BitPay refund API."""

    id: str
    invoice: str
    status: str
    amount: float
    currency: str
    request_date: str
    reference: str


class WebhookPayload(TypedDict, total=False):
    """BitPay IPN webhook payload (invoice events)."""

    id: str
    url: str
    status: str
    price: float
    currency: str
    order_id: str
    amount_paid: float
    exception_status: str | bool
    buyer_fields: dict


# Accepted fiat currencies for BitPay invoices.
# Source: BitPay API documentation + old django-getpaid-bitpay processor.
ACCEPTED_CURRENCIES: list[str] = [
    "AED",
    "AFN",
    "ALL",
    "AMD",
    "ANG",
    "AOA",
    "ARS",
    "AUD",
    "AWG",
    "AZN",
    "BAM",
    "BBD",
    "BDT",
    "BGN",
    "BHD",
    "BIF",
    "BMD",
    "BND",
    "BOB",
    "BRL",
    "BSD",
    "BTN",
    "BWP",
    "BYN",
    "BZD",
    "CAD",
    "CDF",
    "CHF",
    "CLP",
    "CNY",
    "COP",
    "CRC",
    "CUP",
    "CVE",
    "CZK",
    "DJF",
    "DKK",
    "DOP",
    "DZD",
    "EGP",
    "ERN",
    "ETB",
    "EUR",
    "FJD",
    "FKP",
    "GBP",
    "GEL",
    "GHS",
    "GIP",
    "GMD",
    "GNF",
    "GTQ",
    "GYD",
    "HKD",
    "HNL",
    "HRK",
    "HTG",
    "HUF",
    "IDR",
    "ILS",
    "INR",
    "IQD",
    "IRR",
    "ISK",
    "JMD",
    "JOD",
    "JPY",
    "KES",
    "KGS",
    "KHR",
    "KMF",
    "KPW",
    "KRW",
    "KWD",
    "KYD",
    "KZT",
    "LAK",
    "LBP",
    "LKR",
    "LRD",
    "LSL",
    "LYD",
    "MAD",
    "MDL",
    "MGA",
    "MKD",
    "MMK",
    "MNT",
    "MOP",
    "MRU",
    "MUR",
    "MVR",
    "MWK",
    "MXN",
    "MYR",
    "MZN",
    "NAD",
    "NGN",
    "NIO",
    "NOK",
    "NPR",
    "NZD",
    "OMR",
    "PAB",
    "PEN",
    "PGK",
    "PHP",
    "PKR",
    "PLN",
    "PYG",
    "QAR",
    "RON",
    "RSD",
    "RUB",
    "RWF",
    "SAR",
    "SBD",
    "SCR",
    "SDG",
    "SEK",
    "SGD",
    "SHP",
    "SLE",
    "SOS",
    "SRD",
    "STN",
    "SVC",
    "SYP",
    "SZL",
    "THB",
    "TJS",
    "TMT",
    "TND",
    "TOP",
    "TRY",
    "TTD",
    "TWD",
    "TZS",
    "UAH",
    "UGX",
    "USD",
    "UYU",
    "UZS",
    "VES",
    "VND",
    "VUV",
    "WST",
    "XAF",
    "XCD",
    "XOF",
    "XPF",
    "YER",
    "ZAR",
    "ZMW",
    "ZWL",
    # Crypto currencies
    "BTC",
    "BCH",
    "ETH",
    "XRP",
    "DOGE",
    "LTC",
    "USDC",
    "USDT",
    "DAI",
    "WBTC",
    "SHIB",
]

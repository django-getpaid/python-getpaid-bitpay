"""BitPay type definitions, enums, and status mappings."""

from enum import StrEnum
from typing import TypedDict

from getpaid_core.enums import PaymentEvent


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


# Maps BitPay invoice status to semantic payment events.
INVOICE_STATUS_MAP: dict[InvoiceStatus, PaymentEvent | None] = {
    InvoiceStatus.NEW: PaymentEvent.PREPARED,
    InvoiceStatus.PAID: PaymentEvent.PAYMENT_CAPTURED,
    InvoiceStatus.CONFIRMED: PaymentEvent.PAYMENT_CAPTURED,
    InvoiceStatus.COMPLETE: None,
    InvoiceStatus.EXPIRED: PaymentEvent.FAILED,
    InvoiceStatus.INVALID: PaymentEvent.FAILED,
    InvoiceStatus.DECLINED: PaymentEvent.FAILED,
}

# Maps BitPay refund status to semantic payment events.
REFUND_STATUS_MAP: dict[RefundStatus, PaymentEvent | None] = {
    RefundStatus.PENDING: None,
    RefundStatus.CREATED: None,
    RefundStatus.PREVIEW: None,
    RefundStatus.SUCCESS: PaymentEvent.REFUND_CONFIRMED,
    RefundStatus.FAILURE: PaymentEvent.REFUND_CANCELLED,
    RefundStatus.CANCELLED: PaymentEvent.REFUND_CANCELLED,
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

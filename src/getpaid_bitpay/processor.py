"""BitPay payment processor."""

import hashlib
import hmac
import logging
from decimal import Decimal
from typing import ClassVar

from getpaid_core.enums import PaymentEvent
from getpaid_core.exceptions import InvalidCallbackError
from getpaid_core.processor import BaseProcessor
from getpaid_core.types import PaymentUpdate
from getpaid_core.types import RefundResult
from getpaid_core.types import TransactionResult

from .client import BitPayClient
from .types import ACCEPTED_CURRENCIES
from .types import INVOICE_STATUS_MAP
from .types import REFUND_STATUS_MAP
from .types import InvoiceStatus
from .types import RefundStatus


logger = logging.getLogger(__name__)


class BitPayProcessor(BaseProcessor):
    """BitPay payment gateway processor.

    Wraps the BitPay REST API v2 using a native async HTTP client.
    Supports POS facade (invoice creation) and optionally merchant
    facade (invoice retrieval, cancellation, refunds) when a
    private key and merchant token are configured.
    """

    slug: ClassVar[str] = "bitpay"
    display_name: ClassVar[str] = "BitPay"
    accepted_currencies: ClassVar[list[str]] = ACCEPTED_CURRENCIES
    sandbox_url: ClassVar[str] = "https://test.bitpay.com"
    production_url: ClassVar[str] = "https://bitpay.com"

    def _get_client(self) -> BitPayClient:
        """Create a BitPayClient from processor config."""
        return BitPayClient(
            base_url=self.get_paywall_baseurl(),
            pos_token=self.get_setting("pos_token", ""),
            merchant_token=self.get_setting("merchant_token"),
            private_key_pem=self.get_setting("private_key_pem"),
        )

    def _resolve_url(self, url_template: str) -> str:
        """Replace {payment_id} placeholder in URL templates."""
        return url_template.format(payment_id=self.payment.id)

    async def prepare_transaction(self, **kwargs) -> TransactionResult:
        """Create a BitPay invoice and return redirect URL.

        Uses POS facade — only ``pos_token`` is required.
        """
        client = self._get_client()

        notify_url = self.get_setting("notification_url")
        redirect_url = self.get_setting("redirect_url")

        buyer_info = self.payment.order.get_buyer_info()

        invoice = await client.create_invoice(
            price=float(self.payment.amount_required),
            currency=self.payment.currency,
            order_id=self.payment.id,
            notification_url=(
                self._resolve_url(notify_url) if notify_url else None
            ),
            redirect_url=(
                self._resolve_url(redirect_url) if redirect_url else None
            ),
            buyer_email=buyer_info.get("email"),
            buyer_name=(
                f"{buyer_info.get('first_name', '')} "
                f"{buyer_info.get('last_name', '')}"
            ).strip()
            or None,
            item_desc=self.payment.description,
        )

        return TransactionResult(
            redirect_url=invoice.get("url"),
            form_data=None,
            method="GET",
            headers={},
            external_id=invoice.get("id") or None,
            provider_data={"invoice_status": invoice.get("status", "")},
        )

    async def verify_callback(
        self, data: dict, headers: dict, **kwargs
    ) -> None:
        """Verify BitPay callback authenticity."""
        raw_body = kwargs.get("raw_body")
        if raw_body is None:
            raise InvalidCallbackError("Missing raw_body in callback kwargs.")
        if isinstance(raw_body, str):
            raw_body = raw_body.encode("utf-8")
        if not isinstance(raw_body, bytes | bytearray):
            raise InvalidCallbackError("raw_body must be bytes or str.")

        signature = ""
        for key, value in headers.items():
            if key.lower() == "x-signature":
                signature = value
                break
        if not signature:
            raise InvalidCallbackError("NO SIGNATURE")

        secret = self.get_setting("pos_token", "")
        expected = hmac.new(
            secret.encode("utf-8"),
            bytes(raw_body),
            hashlib.sha256,
        ).hexdigest()
        if not hmac.compare_digest(expected, signature.lower()):
            raise InvalidCallbackError("BAD SIGNATURE")

    async def handle_callback(
        self, data: dict, headers: dict, **kwargs
    ) -> PaymentUpdate:
        """Handle BitPay IPN webhook (invoice or refund event).

        Dispatches based on ``event_type`` kwarg or infers from
        the webhook payload structure.
        """
        event_type = kwargs.get("event_type", "invoice")
        status_str = data.get("status", "")

        if event_type == "refund":
            return self._handle_refund_callback(status_str, data)
        return self._handle_invoice_callback(status_str, data)

    def _handle_invoice_callback(
        self, status_str: str, data: dict
    ) -> PaymentUpdate:
        """Process invoice status change from webhook."""
        invoice_id = data.get("id") or self.payment.external_id
        provider_event_id = (
            f"invoice:{invoice_id}:{status_str}" if invoice_id else None
        )
        provider_data = {"invoice_status": status_str}
        try:
            status = InvoiceStatus(status_str)
        except ValueError:
            logger.warning("Unknown BitPay invoice status: %s", status_str)
            return PaymentUpdate(
                payment_event=PaymentEvent.FAILED,
                external_id=invoice_id,
                provider_event_id=provider_event_id,
                provider_data=provider_data,
            )

        payment_event = INVOICE_STATUS_MAP.get(status)
        paid_amount = None
        if payment_event is PaymentEvent.PAYMENT_CAPTURED:
            paid_amount = _extract_decimal_amount(
                data,
                "amount_paid",
                "amountPaid",
                "price",
            )
            if paid_amount is None:
                paid_amount = self.payment.amount_required

        return PaymentUpdate(
            payment_event=payment_event,
            paid_amount=paid_amount,
            external_id=invoice_id,
            provider_event_id=provider_event_id,
            provider_data=provider_data,
        )

    def _handle_refund_callback(
        self, status_str: str, data: dict
    ) -> PaymentUpdate:
        """Process refund status change from webhook."""
        refund_id = data.get("id")
        provider_event_id = (
            f"refund:{refund_id}:{status_str}" if refund_id else None
        )
        provider_data = {"refund_status": status_str}
        if refund_id:
            provider_data["refund_id"] = refund_id

        try:
            status = RefundStatus(status_str)
        except ValueError:
            logger.warning("Unknown BitPay refund status: %s", status_str)
            return PaymentUpdate(
                provider_event_id=provider_event_id,
                provider_data=provider_data,
            )

        payment_event = REFUND_STATUS_MAP.get(status)
        refunded_amount = None
        if payment_event is PaymentEvent.REFUND_CONFIRMED:
            refunded_amount = _extract_decimal_amount(data, "amount")

        return PaymentUpdate(
            payment_event=payment_event,
            refunded_amount=refunded_amount,
            provider_event_id=provider_event_id,
            provider_data=provider_data,
        )

    async def fetch_payment_status(self, **kwargs) -> PaymentUpdate:
        """PULL flow: fetch invoice status from BitPay API.

        Requires merchant facade configuration.
        """
        client = self._get_client()
        invoice = await client.get_invoice(self.payment.external_id)

        status_str = invoice.get("status", "")
        invoice_id = invoice.get("id") or self.payment.external_id
        provider_data = {"invoice_status": status_str}
        try:
            status = InvoiceStatus(status_str)
            payment_event = INVOICE_STATUS_MAP.get(status)
        except ValueError:
            payment_event = PaymentEvent.FAILED

        paid_amount = None
        if payment_event is PaymentEvent.PAYMENT_CAPTURED:
            paid_amount = _extract_decimal_amount(
                invoice,
                "amount_paid",
                "amountPaid",
                "price",
            )
            if paid_amount is None:
                paid_amount = self.payment.amount_required

        return PaymentUpdate(
            payment_event=payment_event,
            paid_amount=paid_amount,
            external_id=invoice_id,
            provider_event_id=(
                f"poll:{invoice_id}:{status_str}" if invoice_id else None
            ),
            provider_data=provider_data,
        )

    async def start_refund(
        self, amount: Decimal | None = None, **kwargs
    ) -> RefundResult:
        """Start a refund via BitPay API.

        Requires merchant facade configuration.
        """
        client = self._get_client()
        refund_amount = amount or self.payment.amount_paid

        refund = await client.create_refund(
            invoice_id=self.payment.external_id,
            amount=float(refund_amount),
        )

        provider_data = {"refund_status": refund.get("status", "")}
        refund_id = refund.get("id")
        if refund_id:
            provider_data["refund_id"] = refund_id
        return RefundResult(amount=refund_amount, provider_data=provider_data)

    async def charge(self, amount: Decimal | None = None, **kwargs):
        """BitPay does not support delayed capture."""
        raise NotImplementedError(
            "BitPay does not support pre-authorization/charge flow"
        )

    async def release_lock(self, **kwargs) -> Decimal:
        """BitPay does not support releasing a payment lock."""
        raise NotImplementedError(
            "BitPay does not support pre-authorization/release flow"
        )

    async def cancel_refund(self, **kwargs) -> bool:
        """Cancel an in-progress refund using the merchant API."""
        client = self._get_client()
        refund_id = self.payment.provider_data.get("refund_id")
        if not refund_id:
            raise InvalidCallbackError("Missing refund identifier")
        await client.cancel_refund(refund_id)
        return True


def _extract_decimal_amount(data: dict, *keys: str) -> Decimal | None:
    for key in keys:
        value = data.get(key)
        if value in (None, ""):
            continue
        return Decimal(str(value))
    return None

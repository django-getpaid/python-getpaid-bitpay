"""BitPay payment processor."""

import contextlib
import logging
from decimal import Decimal
from typing import ClassVar

from getpaid_core.processor import BaseProcessor
from getpaid_core.types import PaymentStatusResponse
from getpaid_core.types import TransactionResult
from transitions.core import MachineError

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

        self.payment.external_id = invoice.get("id", "")

        return TransactionResult(
            redirect_url=invoice.get("url"),
            form_data=None,
            method="GET",
            headers={},
        )

    async def handle_callback(
        self, data: dict, headers: dict, **kwargs
    ) -> None:
        """Handle BitPay IPN webhook (invoice or refund event).

        Dispatches based on ``event_type`` kwarg or infers from
        the webhook payload structure.
        """
        event_type = kwargs.get("event_type", "invoice")
        status_str = data.get("status", "")

        if event_type == "refund":
            self._handle_refund_callback(status_str, data)
        else:
            self._handle_invoice_callback(status_str, data)

    def _handle_invoice_callback(self, status_str: str, data: dict) -> None:
        """Process invoice status change from webhook."""
        try:
            status = InvoiceStatus(status_str)
        except ValueError:
            logger.warning("Unknown BitPay invoice status: %s", status_str)
            return

        trigger = INVOICE_STATUS_MAP.get(status)
        if trigger is None:
            logger.debug("No FSM trigger for BitPay status %s", status_str)
            return

        if not self.payment.may_trigger(trigger):
            logger.debug(
                "Cannot trigger %s for payment %s (status=%s)",
                trigger,
                self.payment.id,
                self.payment.status,
            )
            return

        getattr(self.payment, trigger)()

        # After confirm_payment, try to mark_as_paid
        if trigger == "confirm_payment":
            with contextlib.suppress(MachineError):
                if self.payment.may_trigger("mark_as_paid"):
                    self.payment.mark_as_paid()

    def _handle_refund_callback(self, status_str: str, data: dict) -> None:
        """Process refund status change from webhook."""
        try:
            status = RefundStatus(status_str)
        except ValueError:
            logger.warning("Unknown BitPay refund status: %s", status_str)
            return

        trigger = REFUND_STATUS_MAP.get(status)
        if trigger is None:
            logger.debug("No FSM trigger for refund status %s", status_str)
            return

        if not self.payment.may_trigger(trigger):
            return

        if trigger == "confirm_refund":
            amount = Decimal(str(data.get("amount", 0)))
            self.payment.confirm_refund(amount=amount)
            with contextlib.suppress(MachineError):
                if self.payment.may_trigger("mark_as_refunded"):
                    self.payment.mark_as_refunded()
        else:
            getattr(self.payment, trigger)()

    async def fetch_payment_status(self, **kwargs) -> PaymentStatusResponse:
        """PULL flow: fetch invoice status from BitPay API.

        Requires merchant facade configuration.
        """
        client = self._get_client()
        invoice = await client.get_invoice(self.payment.external_id)

        status_str = invoice.get("status", "")
        try:
            status = InvoiceStatus(status_str)
            trigger = INVOICE_STATUS_MAP.get(status)
        except ValueError:
            trigger = None

        return PaymentStatusResponse(
            status=trigger,
            external_id=invoice.get("id"),
        )

    async def start_refund(
        self, amount: Decimal | None = None, **kwargs
    ) -> Decimal:
        """Start a refund via BitPay API.

        Requires merchant facade configuration.
        """
        client = self._get_client()
        refund_amount = amount or self.payment.amount_paid

        await client.create_refund(
            invoice_id=self.payment.external_id,
            amount=float(refund_amount),
        )

        return refund_amount

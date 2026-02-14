"""Tests for BitPay payment processor."""

import json
from decimal import Decimal
from unittest.mock import MagicMock

import httpx
import respx

from getpaid_bitpay.processor import BitPayProcessor
from getpaid_bitpay.signing import generate_pem
from getpaid_bitpay.types import ACCEPTED_CURRENCIES


BITPAY_TEST_URL = "https://test.bitpay.com"


def make_payment(**overrides):
    """Create a mock Payment protocol object."""
    payment = MagicMock()
    payment.id = overrides.get("id", "pay-001")
    payment.external_id = overrides.get("external_id", "")
    payment.amount_required = overrides.get("amount_required", Decimal("10.00"))
    payment.amount_paid = overrides.get("amount_paid", Decimal("0"))
    payment.amount_locked = overrides.get("amount_locked", Decimal("0"))
    payment.amount_refunded = overrides.get("amount_refunded", Decimal("0"))
    payment.currency = overrides.get("currency", "USD")
    payment.status = overrides.get("status", "new")
    payment.backend = "bitpay"
    payment.description = overrides.get("description", "Test payment")
    payment.fraud_status = "unknown"
    payment.fraud_message = ""

    order = MagicMock()
    order.get_total_amount.return_value = payment.amount_required
    order.get_currency.return_value = payment.currency
    order.get_description.return_value = payment.description
    order.get_buyer_info.return_value = {
        "email": "buyer@example.com",
        "first_name": "John",
        "last_name": "Doe",
    }
    order.get_items.return_value = [
        {"name": "Widget", "quantity": 1, "unit_price": payment.amount_required}
    ]
    order.get_return_url.return_value = "https://example.com/return"
    payment.order = order

    # FSM trigger methods
    payment.may_trigger = MagicMock(return_value=True)
    payment.confirm_prepared = MagicMock()
    payment.confirm_payment = MagicMock()
    payment.mark_as_paid = MagicMock()
    payment.fail = MagicMock()
    payment.start_refund = MagicMock()
    payment.confirm_refund = MagicMock()
    payment.mark_as_refunded = MagicMock()
    payment.cancel_refund = MagicMock()
    return payment


def make_config(**overrides):
    """Create processor config dict."""
    config = {
        "sandbox": True,
        "pos_token": "test-pos-token",
        "notification_url": "https://example.com/webhook/{payment_id}",
        "redirect_url": "https://example.com/return/{payment_id}",
    }
    config.update(overrides)
    return config


class TestProcessorClassVars:
    def test_slug(self):
        assert BitPayProcessor.slug == "bitpay"

    def test_display_name(self):
        assert BitPayProcessor.display_name == "BitPay"

    def test_accepted_currencies(self):
        assert BitPayProcessor.accepted_currencies == ACCEPTED_CURRENCIES

    def test_sandbox_url(self):
        assert BitPayProcessor.sandbox_url == "https://test.bitpay.com"

    def test_production_url(self):
        assert BitPayProcessor.production_url == "https://bitpay.com"


class TestPrepareTransaction:
    @respx.mock
    async def test_creates_invoice_and_returns_redirect(self):
        payment = make_payment()
        config = make_config()
        processor = BitPayProcessor(payment, config)

        respx.post(f"{BITPAY_TEST_URL}/invoices").mock(
            return_value=httpx.Response(
                200,
                json={
                    "data": {
                        "id": "inv-abc",
                        "url": "https://test.bitpay.com/invoice?id=inv-abc",
                        "status": "new",
                        "token": "invoice-token",
                    }
                },
            )
        )

        result = await processor.prepare_transaction()

        assert result["method"] == "GET"
        assert (
            result["redirect_url"]
            == "https://test.bitpay.com/invoice?id=inv-abc"
        )
        assert result["form_data"] is None
        assert payment.external_id == "inv-abc"

    @respx.mock
    async def test_passes_notification_url(self):
        payment = make_payment()
        config = make_config()
        processor = BitPayProcessor(payment, config)

        respx.post(f"{BITPAY_TEST_URL}/invoices").mock(
            return_value=httpx.Response(
                200, json={"data": {"id": "inv1", "url": "u"}}
            )
        )

        await processor.prepare_transaction()

        body = json.loads(respx.calls[0].request.content)
        assert body["notificationURL"] == "https://example.com/webhook/pay-001"

    @respx.mock
    async def test_passes_redirect_url(self):
        payment = make_payment()
        config = make_config()
        processor = BitPayProcessor(payment, config)

        respx.post(f"{BITPAY_TEST_URL}/invoices").mock(
            return_value=httpx.Response(
                200, json={"data": {"id": "inv1", "url": "u"}}
            )
        )

        await processor.prepare_transaction()

        body = json.loads(respx.calls[0].request.content)
        assert body["redirectURL"] == "https://example.com/return/pay-001"


class TestHandleCallback:
    async def _make_processor_and_handle(self, payment, webhook_data, **kwargs):
        config = make_config()
        processor = BitPayProcessor(payment, config)
        await processor.handle_callback(webhook_data, {}, **kwargs)

    async def test_paid_status_triggers_confirm_payment(self):
        payment = make_payment()
        await self._make_processor_and_handle(
            payment, {"id": "inv1", "status": "paid"}
        )
        payment.confirm_payment.assert_called_once()

    async def test_confirmed_status_triggers_mark_as_paid(self):
        payment = make_payment()
        await self._make_processor_and_handle(
            payment, {"id": "inv1", "status": "confirmed"}
        )
        payment.mark_as_paid.assert_called_once()

    async def test_complete_status_no_transition(self):
        payment = make_payment()
        await self._make_processor_and_handle(
            payment, {"id": "inv1", "status": "complete"}
        )
        payment.confirm_payment.assert_not_called()
        payment.mark_as_paid.assert_not_called()
        payment.fail.assert_not_called()

    async def test_expired_status_triggers_fail(self):
        payment = make_payment()
        await self._make_processor_and_handle(
            payment, {"id": "inv1", "status": "expired"}
        )
        payment.fail.assert_called_once()

    async def test_invalid_status_triggers_fail(self):
        payment = make_payment()
        await self._make_processor_and_handle(
            payment, {"id": "inv1", "status": "invalid"}
        )
        payment.fail.assert_called_once()

    async def test_skips_transition_if_may_trigger_false(self):
        payment = make_payment()
        payment.may_trigger.return_value = False
        await self._make_processor_and_handle(
            payment, {"id": "inv1", "status": "paid"}
        )
        payment.confirm_payment.assert_not_called()


class TestHandleCallbackRefund:
    async def test_refund_success_triggers_confirm_refund(self):
        payment = make_payment()
        config = make_config()
        processor = BitPayProcessor(payment, config)

        await processor.handle_callback(
            {"id": "ref1", "status": "success", "amount": 5.0},
            {},
            event_type="refund",
        )
        payment.confirm_refund.assert_called_once()

    async def test_refund_cancelled_triggers_cancel_refund(self):
        payment = make_payment()
        config = make_config()
        processor = BitPayProcessor(payment, config)

        await processor.handle_callback(
            {"id": "ref1", "status": "cancelled"},
            {},
            event_type="refund",
        )
        payment.cancel_refund.assert_called_once()


class TestFetchPaymentStatus:
    @respx.mock
    async def test_fetches_and_maps_status(self):
        payment = make_payment(external_id="inv-abc")
        config = make_config(
            merchant_token="merch-token",
            private_key_pem=generate_pem(),
        )
        processor = BitPayProcessor(payment, config)

        respx.get(url__startswith=f"{BITPAY_TEST_URL}/invoices/inv-abc").mock(
            return_value=httpx.Response(
                200,
                json={
                    "data": {
                        "id": "inv-abc",
                        "status": "confirmed",
                        "price": 10.0,
                        "amountPaid": 10.0,
                    }
                },
            )
        )

        result = await processor.fetch_payment_status()
        assert result["status"] == "mark_as_paid"
        assert result["external_id"] == "inv-abc"


class TestStartRefund:
    @respx.mock
    async def test_starts_refund(self):
        payment = make_payment(
            external_id="inv-abc",
            amount_paid=Decimal("10.00"),
        )
        config = make_config(
            merchant_token="merch-token",
            private_key_pem=generate_pem(),
        )
        processor = BitPayProcessor(payment, config)

        respx.post(f"{BITPAY_TEST_URL}/refunds").mock(
            return_value=httpx.Response(
                200,
                json={
                    "data": {
                        "id": "ref-001",
                        "status": "created",
                        "amount": 5.0,
                    }
                },
            )
        )

        result = await processor.start_refund(amount=Decimal("5.00"))
        assert result == Decimal("5.00")

    @respx.mock
    async def test_full_refund_uses_amount_paid(self):
        payment = make_payment(
            external_id="inv-abc",
            amount_paid=Decimal("10.00"),
        )
        config = make_config(
            merchant_token="merch-token",
            private_key_pem=generate_pem(),
        )
        processor = BitPayProcessor(payment, config)

        respx.post(f"{BITPAY_TEST_URL}/refunds").mock(
            return_value=httpx.Response(
                200,
                json={
                    "data": {
                        "id": "ref-001",
                        "status": "created",
                        "amount": 10.0,
                    }
                },
            )
        )

        result = await processor.start_refund()
        assert result == Decimal("10.00")

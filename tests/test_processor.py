"""Tests for BitPay payment processor."""

import hashlib
import hmac
import json
from decimal import Decimal
from unittest.mock import MagicMock

import httpx
import pytest
import respx
from getpaid_core.enums import BackendMethod
from getpaid_core.enums import PaymentEvent
from getpaid_core.exceptions import InvalidCallbackError

from getpaid_bitpay.processor import BitPayProcessor
from getpaid_bitpay.signing import generate_pem
from getpaid_bitpay.types import ACCEPTED_CURRENCIES


BITPAY_TEST_URL = "https://test.bitpay.com"


def make_payment(**overrides):
    """Create a mock Payment protocol object."""
    payment = MagicMock()
    payment.id = overrides.get("id", "pay-001")
    payment.external_id = overrides.get("external_id")
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
    payment.provider_data = dict(overrides.get("provider_data", {}))

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


def make_processor(payment=None, **config_overrides):
    if payment is None:
        payment = make_payment()
    return BitPayProcessor(
        payment=payment, config=make_config(**config_overrides)
    )


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
        processor = make_processor()

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

        assert result.method is BackendMethod.GET
        assert (
            result.redirect_url == "https://test.bitpay.com/invoice?id=inv-abc"
        )
        assert result.form_data is None
        assert result.external_id == "inv-abc"
        assert result.provider_data == {"invoice_status": "new"}

    @respx.mock
    async def test_passes_notification_url(self):
        processor = make_processor()

        route = respx.post(f"{BITPAY_TEST_URL}/invoices").mock(
            return_value=httpx.Response(
                200,
                json={"data": {"id": "inv1", "url": "u", "status": "new"}},
            )
        )

        await processor.prepare_transaction()

        body = json.loads(route.calls[0].request.content)
        assert body["notificationURL"] == "https://example.com/webhook/pay-001"

    @respx.mock
    async def test_passes_redirect_url(self):
        processor = make_processor()

        route = respx.post(f"{BITPAY_TEST_URL}/invoices").mock(
            return_value=httpx.Response(
                200,
                json={"data": {"id": "inv1", "url": "u", "status": "new"}},
            )
        )

        await processor.prepare_transaction()

        body = json.loads(route.calls[0].request.content)
        assert body["redirectURL"] == "https://example.com/return/pay-001"


class TestHandleCallback:
    async def test_paid_status_returns_capture_update(self):
        processor = make_processor()

        result = await processor.handle_callback(
            {"id": "inv1", "status": "paid", "price": 10.0},
            {},
        )

        assert result is not None
        assert result.payment_event is PaymentEvent.PAYMENT_CAPTURED
        assert result.external_id == "inv1"
        assert result.paid_amount == Decimal("10.0")
        assert result.provider_event_id == "invoice:inv1:paid"
        assert result.provider_data == {"invoice_status": "paid"}

    async def test_confirmed_status_returns_capture_update(self):
        processor = make_processor()

        result = await processor.handle_callback(
            {"id": "inv1", "status": "confirmed", "price": 10.0},
            {},
        )

        assert result is not None
        assert result.payment_event is PaymentEvent.PAYMENT_CAPTURED
        assert result.paid_amount == Decimal("10.0")

    async def test_complete_status_returns_metadata_only_update(self):
        processor = make_processor()

        result = await processor.handle_callback(
            {"id": "inv1", "status": "complete"},
            {},
        )

        assert result is not None
        assert result.payment_event is None
        assert result.external_id == "inv1"
        assert result.provider_event_id == "invoice:inv1:complete"
        assert result.provider_data == {"invoice_status": "complete"}

    async def test_expired_status_returns_failed_update(self):
        processor = make_processor()

        result = await processor.handle_callback(
            {"id": "inv1", "status": "expired"},
            {},
        )

        assert result is not None
        assert result.payment_event is PaymentEvent.FAILED

    async def test_invalid_status_returns_failed_update(self):
        processor = make_processor()

        result = await processor.handle_callback(
            {"id": "inv1", "status": "mystery_status"},
            {},
        )

        assert result is not None
        assert result.payment_event is PaymentEvent.FAILED
        assert result.provider_data == {"invoice_status": "mystery_status"}


class TestHandleCallbackRefund:
    async def test_refund_success_returns_refund_confirmation_update(self):
        processor = make_processor()

        result = await processor.handle_callback(
            {"id": "ref1", "status": "success", "amount": 5.0},
            {},
            event_type="refund",
        )

        assert result is not None
        assert result.payment_event is PaymentEvent.REFUND_CONFIRMED
        assert result.refunded_amount == Decimal("5.0")
        assert result.provider_event_id == "refund:ref1:success"
        assert result.provider_data == {
            "refund_id": "ref1",
            "refund_status": "success",
        }

    async def test_refund_cancelled_returns_refund_cancelled_update(self):
        processor = make_processor()

        result = await processor.handle_callback(
            {"id": "ref1", "status": "cancelled"},
            {},
            event_type="refund",
        )

        assert result is not None
        assert result.payment_event is PaymentEvent.REFUND_CANCELLED


class TestVerifyCallback:
    async def test_valid_signature(self):
        processor = make_processor()
        raw_body = json.dumps({"id": "inv1", "status": "paid"})
        signature = hmac.new(
            b"test-pos-token",
            raw_body.encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()

        await processor.verify_callback(
            data={},
            headers={"X-Signature": signature},
            raw_body=raw_body,
        )

    async def test_missing_signature_raises(self):
        processor = make_processor()

        with pytest.raises(InvalidCallbackError, match="NO SIGNATURE"):
            await processor.verify_callback(
                data={},
                headers={},
                raw_body=b'{"id":"inv1"}',
            )

    async def test_missing_raw_body_raises(self):
        processor = make_processor()

        with pytest.raises(InvalidCallbackError, match="raw_body"):
            await processor.verify_callback(
                data={},
                headers={"x-signature": "abc"},
            )

    async def test_bad_signature_raises(self):
        processor = make_processor()

        with pytest.raises(InvalidCallbackError, match="BAD SIGNATURE"):
            await processor.verify_callback(
                data={},
                headers={"x-signature": "bad"},
                raw_body=b'{"id":"inv1"}',
            )


class TestFetchPaymentStatus:
    @respx.mock
    async def test_fetches_and_maps_status(self):
        payment = make_payment(external_id="inv-abc")
        processor = make_processor(
            payment=payment,
            merchant_token="merch-token",
            private_key_pem=generate_pem(),
        )

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

        assert result is not None
        assert result.payment_event is PaymentEvent.PAYMENT_CAPTURED
        assert result.external_id == "inv-abc"
        assert result.paid_amount == Decimal("10.0")
        assert result.provider_data == {"invoice_status": "confirmed"}


class TestRefunds:
    @respx.mock
    async def test_starts_refund(self):
        payment = make_payment(
            external_id="inv-abc",
            amount_paid=Decimal("10.00"),
        )
        processor = make_processor(
            payment=payment,
            merchant_token="merch-token",
            private_key_pem=generate_pem(),
        )

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

        assert result.amount == Decimal("5.00")
        assert result.provider_data == {
            "refund_id": "ref-001",
            "refund_status": "created",
        }

    @respx.mock
    async def test_full_refund_uses_amount_paid(self):
        payment = make_payment(
            external_id="inv-abc",
            amount_paid=Decimal("10.00"),
        )
        processor = make_processor(
            payment=payment,
            merchant_token="merch-token",
            private_key_pem=generate_pem(),
        )

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

        assert result.amount == Decimal("10.00")

    @respx.mock
    async def test_cancel_refund_uses_refund_id_from_provider_data(self):
        payment = make_payment(
            provider_data={"refund_id": "ref-001"},
        )
        processor = make_processor(
            payment=payment,
            merchant_token="merch-token",
            private_key_pem=generate_pem(),
        )

        route = respx.delete(
            url__startswith=f"{BITPAY_TEST_URL}/refunds/ref-001"
        ).mock(
            return_value=httpx.Response(200, json={"data": {"id": "ref-001"}})
        )

        result = await processor.cancel_refund()

        assert result is True
        assert route.called


class TestUnsupportedOperations:
    async def test_charge_not_supported(self):
        processor = make_processor()

        with pytest.raises(NotImplementedError):
            await processor.charge()

    async def test_release_lock_not_supported(self):
        processor = make_processor()

        with pytest.raises(NotImplementedError):
            await processor.release_lock()

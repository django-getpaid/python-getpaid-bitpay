"""Tests for BitPay status mappings."""

from getpaid_core.enums import PaymentEvent

from getpaid_bitpay.types import INVOICE_STATUS_MAP
from getpaid_bitpay.types import REFUND_STATUS_MAP
from getpaid_bitpay.types import InvoiceStatus
from getpaid_bitpay.types import RefundStatus


class TestInvoiceStatus:
    def test_all_values_present(self):
        expected = {
            "new",
            "paid",
            "confirmed",
            "complete",
            "expired",
            "invalid",
            "declined",
        }
        assert {status.value for status in InvoiceStatus} == expected

    def test_status_map_covers_all(self):
        for status in InvoiceStatus:
            assert status in INVOICE_STATUS_MAP


class TestRefundStatus:
    def test_all_values_present(self):
        expected = {
            "pending",
            "created",
            "preview",
            "success",
            "failure",
            "cancelled",
        }
        assert {status.value for status in RefundStatus} == expected

    def test_status_map_covers_all(self):
        for status in RefundStatus:
            assert status in REFUND_STATUS_MAP


class TestInvoiceStatusMapping:
    def test_new_maps_to_prepared(self):
        assert INVOICE_STATUS_MAP[InvoiceStatus.NEW] is PaymentEvent.PREPARED

    def test_paid_maps_to_payment_captured(self):
        assert (
            INVOICE_STATUS_MAP[InvoiceStatus.PAID]
            is PaymentEvent.PAYMENT_CAPTURED
        )

    def test_confirmed_maps_to_payment_captured(self):
        assert (
            INVOICE_STATUS_MAP[InvoiceStatus.CONFIRMED]
            is PaymentEvent.PAYMENT_CAPTURED
        )

    def test_complete_maps_to_none(self):
        assert INVOICE_STATUS_MAP[InvoiceStatus.COMPLETE] is None

    def test_expired_maps_to_failed(self):
        assert INVOICE_STATUS_MAP[InvoiceStatus.EXPIRED] is PaymentEvent.FAILED

    def test_invalid_maps_to_failed(self):
        assert INVOICE_STATUS_MAP[InvoiceStatus.INVALID] is PaymentEvent.FAILED

    def test_declined_maps_to_failed(self):
        assert INVOICE_STATUS_MAP[InvoiceStatus.DECLINED] is PaymentEvent.FAILED


class TestRefundStatusMapping:
    def test_pending_maps_to_none(self):
        assert REFUND_STATUS_MAP[RefundStatus.PENDING] is None

    def test_created_maps_to_none(self):
        assert REFUND_STATUS_MAP[RefundStatus.CREATED] is None

    def test_preview_maps_to_none(self):
        assert REFUND_STATUS_MAP[RefundStatus.PREVIEW] is None

    def test_success_maps_to_refund_confirmed(self):
        assert (
            REFUND_STATUS_MAP[RefundStatus.SUCCESS]
            is PaymentEvent.REFUND_CONFIRMED
        )

    def test_failure_maps_to_refund_cancelled(self):
        assert (
            REFUND_STATUS_MAP[RefundStatus.FAILURE]
            is PaymentEvent.REFUND_CANCELLED
        )

    def test_cancelled_maps_to_refund_cancelled(self):
        assert (
            REFUND_STATUS_MAP[RefundStatus.CANCELLED]
            is PaymentEvent.REFUND_CANCELLED
        )

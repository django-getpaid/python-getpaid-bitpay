"""Tests for BitPay type definitions and status mappings."""

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
        assert {s.value for s in InvoiceStatus} == expected

    def test_status_map_covers_all(self):
        """Every InvoiceStatus has a mapping entry."""
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
        assert {s.value for s in RefundStatus} == expected

    def test_status_map_covers_all(self):
        """Every RefundStatus has a mapping entry."""
        for status in RefundStatus:
            assert status in REFUND_STATUS_MAP


class TestInvoiceStatusMapping:
    def test_new_maps_to_confirm_prepared(self):
        assert INVOICE_STATUS_MAP[InvoiceStatus.NEW] == "confirm_prepared"

    def test_paid_maps_to_confirm_payment(self):
        assert INVOICE_STATUS_MAP[InvoiceStatus.PAID] == "confirm_payment"

    def test_confirmed_maps_to_mark_as_paid(self):
        assert INVOICE_STATUS_MAP[InvoiceStatus.CONFIRMED] == "mark_as_paid"

    def test_complete_maps_to_none(self):
        assert INVOICE_STATUS_MAP[InvoiceStatus.COMPLETE] is None

    def test_expired_maps_to_fail(self):
        assert INVOICE_STATUS_MAP[InvoiceStatus.EXPIRED] == "fail"

    def test_invalid_maps_to_fail(self):
        assert INVOICE_STATUS_MAP[InvoiceStatus.INVALID] == "fail"

    def test_declined_maps_to_fail(self):
        assert INVOICE_STATUS_MAP[InvoiceStatus.DECLINED] == "fail"


class TestRefundStatusMapping:
    def test_pending_maps_to_none(self):
        assert REFUND_STATUS_MAP[RefundStatus.PENDING] is None

    def test_created_maps_to_none(self):
        assert REFUND_STATUS_MAP[RefundStatus.CREATED] is None

    def test_preview_maps_to_none(self):
        assert REFUND_STATUS_MAP[RefundStatus.PREVIEW] is None

    def test_success_maps_to_confirm_refund(self):
        assert REFUND_STATUS_MAP[RefundStatus.SUCCESS] == "confirm_refund"

    def test_failure_maps_to_cancel_refund(self):
        assert REFUND_STATUS_MAP[RefundStatus.FAILURE] == "cancel_refund"

    def test_cancelled_maps_to_cancel_refund(self):
        assert REFUND_STATUS_MAP[RefundStatus.CANCELLED] == "cancel_refund"

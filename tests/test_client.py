"""Behavioral equivalence tests: our BitPayClient vs official bitpay SDK.

These tests verify that our async client produces identical HTTP requests
to the official BitPay Python SDK (v7.0.8). If both implementations pass
these tests, they are functionally equivalent at the HTTP protocol level.

Reference SDK source files:
- bitpay/clients/bitpay_client.py   — HTTP transport (signs, sends)
- bitpay/clients/invoice_client.py  — invoice operations
- bitpay/clients/refund_client.py   — refund operations
- bitpay/clients/response_parser.py — response envelope parsing
- bitpay/utils/key_utils.py         — EC key signing (SHA-256 + secp256k1)
"""

import hashlib
import json
from urllib.parse import parse_qs
from urllib.parse import urlparse

import httpx
import pytest
import respx
from ecdsa import SECP256k1
from ecdsa import SigningKey
from ecdsa.util import sigdecode_der
from getpaid_core.exceptions import CommunicationError
from getpaid_core.exceptions import CredentialsError
from getpaid_core.exceptions import LockFailure
from getpaid_core.exceptions import RefundFailure

from getpaid_bitpay.client import BitPayClient
from getpaid_bitpay.signing import generate_pem
from getpaid_bitpay.signing import get_compressed_public_key
from getpaid_bitpay.signing import sign


BITPAY_TEST_URL = "https://test.bitpay.com"


# ---------------------------------------------------------------------------
# Fixtures (pem_key, pos_token, merchant_token are in conftest.py)
# ---------------------------------------------------------------------------


@pytest.fixture
def pos_client(pos_token):
    """POS-facade-only client (no signing)."""
    return BitPayClient(
        base_url=BITPAY_TEST_URL,
        pos_token=pos_token,
    )


@pytest.fixture
def merchant_client(pos_token, merchant_token, pem_key):
    """Merchant-facade client with signing enabled."""
    return BitPayClient(
        base_url=BITPAY_TEST_URL,
        pos_token=pos_token,
        merchant_token=merchant_token,
        private_key_pem=pem_key,
    )


def _ok(data: dict) -> httpx.Response:
    """Helper: build a 200 response with BitPay envelope."""
    return httpx.Response(200, json={"data": data})


# ===================================================================
# 1. Signing — behavioral equivalence with bitpay.utils.key_utils
# ===================================================================


class TestSigningEquivalence:
    """Verify our signing module produces output identical to the SDK.

    SDK reference: bitpay/utils/key_utils.py
    - sign(message, pem):  ECDSA-SHA256 + DER + hex
    - get_compressed_public_key_from_pem(pem): 02/03 + x-coordinate hex
    """

    def test_compressed_public_key_matches_sdk(self, pem_key):
        """Our get_compressed_public_key must match the SDK's output.

        SDK: binascii.hexlify(vk.to_string()) -> compress_key(bts)
        where compress_key checks int(full_hex, 16) % 2 for prefix.
        """
        sdk_keys = pytest.importorskip("bitpay.utils.key_utils")
        sdk_get_pubkey = sdk_keys.get_compressed_public_key_from_pem

        ours = get_compressed_public_key(pem_key)
        theirs = sdk_get_pubkey(pem_key)
        assert ours == theirs

    def test_signature_matches_sdk(self, pem_key):
        """Our sign() and SDK sign() must both verify under SHA-256.

        ECDSA uses a random nonce, so the hex values won't be equal.
        Instead we verify both signatures are valid SHA-256 signatures
        for the same message and key.
        """
        sdk_keys = pytest.importorskip("bitpay.utils.key_utils")
        sdk_sign = sdk_keys.sign

        message = 'https://test.bitpay.com/invoices{"token":"abc"}'
        ours = sign(message, pem_key)
        theirs = sdk_sign(message, pem_key)

        sk = SigningKey.from_pem(pem_key)
        vk = sk.get_verifying_key()
        # Both must verify under SHA-256
        vk.verify(
            bytes.fromhex(ours),
            message.encode("utf-8"),
            hashfunc=hashlib.sha256,
            sigdecode=sigdecode_der,
        )
        vk.verify(
            bytes.fromhex(theirs),
            message.encode("utf-8"),
            hashfunc=hashlib.sha256,
            sigdecode=sigdecode_der,
        )

    def test_signature_verifies_with_sha256(self, pem_key):
        """Signatures must be verifiable using SHA-256.

        SDK uses SHA-256 for all signing operations.
        """
        message = 'https://test.bitpay.com/refunds{"token":"xyz"}'
        sig_hex = sign(message, pem_key)
        sig_bytes = bytes.fromhex(sig_hex)

        sk = SigningKey.from_pem(pem_key)
        vk = sk.get_verifying_key()
        # This will raise BadSignatureError if sig was computed with SHA-1
        vk.verify(
            sig_bytes,
            message.encode("utf-8"),
            hashfunc=hashlib.sha256,
            sigdecode=sigdecode_der,
        )

    def test_generate_pem_produces_secp256k1_key(self):
        """SDK uses SECP256k1 curve; our generate_pem must too."""
        pem = generate_pem()
        sk = SigningKey.from_pem(pem)
        assert sk.curve == SECP256k1

    def test_compressed_key_is_66_hex_chars(self, pem_key):
        """SDK compressed key format: 02/03 prefix + 64 hex chars."""
        pubkey = get_compressed_public_key(pem_key)
        assert len(pubkey) == 66
        assert pubkey[:2] in ("02", "03")

    def test_compressed_key_deterministic(self, pem_key):
        """Same PEM always yields same compressed key."""
        assert get_compressed_public_key(pem_key) == get_compressed_public_key(
            pem_key
        )


# ===================================================================
# 2. Common request properties (headers, version)
# ===================================================================


class TestCommonRequestBehavior:
    """Verify headers and API version match the SDK's BitPayClient.init().

    SDK sends: x-accept-version: 2.0.0, content-type: application/json
    (plus telemetry headers we intentionally omit).
    """

    @respx.mock
    async def test_content_type_is_json(self, pos_client):
        """SDK: content-type: application/json on all requests."""
        respx.post(f"{BITPAY_TEST_URL}/invoices").mock(
            return_value=_ok({"id": "x"})
        )
        await pos_client.create_invoice(price=1.0, currency="USD")
        assert (
            respx.calls[0].request.headers["content-type"] == "application/json"
        )

    @respx.mock
    async def test_accept_version_is_2_0_0(self, pos_client):
        """SDK: x-accept-version: 2.0.0 (from Config.BITPAY_API_VERSION)."""
        respx.post(f"{BITPAY_TEST_URL}/invoices").mock(
            return_value=_ok({"id": "x"})
        )
        await pos_client.create_invoice(price=1.0, currency="USD")
        assert respx.calls[0].request.headers["x-accept-version"] == "2.0.0"


# ===================================================================
# 3. Create Invoice — POST /invoices (POS facade)
# ===================================================================


class TestCreateInvoiceBehavior:
    """Behavioral equivalence with InvoiceClient.create().

    SDK: POST to ``{base_url}invoices`` with token in JSON body.
    POS facade: sign_request=False -> no signing headers.
    """

    @respx.mock
    async def test_posts_to_invoices_endpoint(self, pos_client):
        """SDK: post("invoices", ...) -> POST {base}/invoices."""
        route = respx.post(f"{BITPAY_TEST_URL}/invoices").mock(
            return_value=_ok({"id": "inv1"})
        )
        await pos_client.create_invoice(price=10.0, currency="USD")
        assert route.called

    @respx.mock
    async def test_token_in_body(self, pos_client, pos_token):
        """SDK: invoice.token = token_container.get_access_token(facade)
        Token must be in the JSON request body, not in headers or query."""
        respx.post(f"{BITPAY_TEST_URL}/invoices").mock(
            return_value=_ok({"id": "inv1"})
        )
        await pos_client.create_invoice(price=10.0, currency="USD")
        body = json.loads(respx.calls[0].request.content)
        assert body["token"] == pos_token

    @respx.mock
    async def test_price_and_currency_in_body(self, pos_client):
        """SDK: invoice model has price and currency fields in body."""
        respx.post(f"{BITPAY_TEST_URL}/invoices").mock(
            return_value=_ok({"id": "inv1"})
        )
        await pos_client.create_invoice(price=42.5, currency="BTC")
        body = json.loads(respx.calls[0].request.content)
        assert body["price"] == 42.5
        assert body["currency"] == "BTC"

    @respx.mock
    async def test_order_id_field_name(self, pos_client):
        """SDK: Invoice model uses alias ``orderId`` (camelCase)."""
        respx.post(f"{BITPAY_TEST_URL}/invoices").mock(
            return_value=_ok({"id": "inv1"})
        )
        await pos_client.create_invoice(
            price=10.0, currency="USD", order_id="order-42"
        )
        body = json.loads(respx.calls[0].request.content)
        assert body["orderId"] == "order-42"

    @respx.mock
    async def test_notification_url_field_name(self, pos_client):
        """SDK: Invoice model uses explicit alias ``notificationURL``
        (not camelCase ``notificationUrl``)."""
        respx.post(f"{BITPAY_TEST_URL}/invoices").mock(
            return_value=_ok({"id": "inv1"})
        )
        await pos_client.create_invoice(
            price=10.0,
            currency="USD",
            notification_url="https://example.com/ipn",
        )
        body = json.loads(respx.calls[0].request.content)
        assert "notificationURL" in body
        assert body["notificationURL"] == "https://example.com/ipn"

    @respx.mock
    async def test_redirect_url_field_name(self, pos_client):
        """SDK: Invoice model uses explicit alias ``redirectURL``
        (not camelCase ``redirectUrl``)."""
        respx.post(f"{BITPAY_TEST_URL}/invoices").mock(
            return_value=_ok({"id": "inv1"})
        )
        await pos_client.create_invoice(
            price=10.0,
            currency="USD",
            redirect_url="https://example.com/thanks",
        )
        body = json.loads(respx.calls[0].request.content)
        assert "redirectURL" in body
        assert body["redirectURL"] == "https://example.com/thanks"

    @respx.mock
    async def test_item_desc_field_name(self, pos_client):
        """SDK: Invoice model uses alias ``itemDesc``."""
        respx.post(f"{BITPAY_TEST_URL}/invoices").mock(
            return_value=_ok({"id": "inv1"})
        )
        await pos_client.create_invoice(
            price=10.0,
            currency="USD",
            item_desc="Premium widget",
        )
        body = json.loads(respx.calls[0].request.content)
        assert body["itemDesc"] == "Premium widget"

    @respx.mock
    async def test_buyer_nested_object(self, pos_client):
        """SDK: Invoice model has a nested ``buyer`` object with email/name."""
        respx.post(f"{BITPAY_TEST_URL}/invoices").mock(
            return_value=_ok({"id": "inv1"})
        )
        await pos_client.create_invoice(
            price=10.0,
            currency="USD",
            buyer_email="buyer@example.com",
            buyer_name="Jane Doe",
        )
        body = json.loads(respx.calls[0].request.content)
        assert body["buyer"]["email"] == "buyer@example.com"
        assert body["buyer"]["name"] == "Jane Doe"

    @respx.mock
    async def test_omits_optional_fields_when_not_set(self, pos_client):
        """SDK: model_dump(exclude_unset=True) — only set fields are sent.
        Our client should not send None values for optional params."""
        respx.post(f"{BITPAY_TEST_URL}/invoices").mock(
            return_value=_ok({"id": "inv1"})
        )
        await pos_client.create_invoice(price=10.0, currency="USD")
        body = json.loads(respx.calls[0].request.content)
        assert "notificationURL" not in body
        assert "redirectURL" not in body
        assert "orderId" not in body
        assert "itemDesc" not in body
        assert "buyer" not in body

    @respx.mock
    async def test_pos_facade_no_signing_headers(self, pos_client):
        """SDK: POS facade passes sign_request=False.
        No x-identity or x-signature headers should be present."""
        respx.post(f"{BITPAY_TEST_URL}/invoices").mock(
            return_value=_ok({"id": "inv1"})
        )
        await pos_client.create_invoice(price=10.0, currency="USD")
        headers = respx.calls[0].request.headers
        assert "x-identity" not in headers
        assert "x-signature" not in headers

    @respx.mock
    async def test_response_extracts_data_envelope(self, pos_client):
        """SDK: ResponseParser extracts the ``data`` field from envelope."""
        respx.post(f"{BITPAY_TEST_URL}/invoices").mock(
            return_value=httpx.Response(
                200,
                json={
                    "data": {
                        "id": "inv123",
                        "url": "https://test.bitpay.com/invoice?id=inv123",
                        "status": "new",
                    }
                },
            )
        )
        result = await pos_client.create_invoice(price=10.0, currency="USD")
        assert result["id"] == "inv123"
        assert result["url"] == "https://test.bitpay.com/invoice?id=inv123"
        assert result["status"] == "new"

    @respx.mock
    async def test_error_response_raises_exception(self, pos_client):
        """SDK: ``{"error": "msg"}`` -> BitPayApiException.
        Our client should raise LockFailure (wrapping CommunicationError)."""
        respx.post(f"{BITPAY_TEST_URL}/invoices").mock(
            return_value=httpx.Response(
                400, json={"error": "Invalid currency", "code": "000000"}
            )
        )
        with pytest.raises(LockFailure):
            await pos_client.create_invoice(price=10.0, currency="INVALID")


# ===================================================================
# 4. Get Invoice — GET /invoices/{id} (merchant facade)
# ===================================================================


class TestGetInvoiceBehavior:
    """Behavioral equivalence with InvoiceClient.get().

    SDK: GET ``{base_url}invoices/{id}?token={merchant_token}``
    Signs the full URL including query string. No request body.
    """

    @respx.mock
    async def test_uses_get_method(self, merchant_client):
        """SDK: self.__bitpay_client.get(...)"""
        route = respx.get(
            url__startswith=f"{BITPAY_TEST_URL}/invoices/inv123"
        ).mock(return_value=_ok({"id": "inv123", "status": "paid"}))
        await merchant_client.get_invoice("inv123")
        assert route.calls[0].request.method == "GET"

    @respx.mock
    async def test_token_in_query_params(self, merchant_client, merchant_token):
        """SDK: params = {"token": token} -> URL-encoded query string.
        Token must be in the URL as ?token=..., not in the body."""
        respx.get(url__startswith=f"{BITPAY_TEST_URL}/invoices/inv123").mock(
            return_value=_ok({"id": "inv123"})
        )
        await merchant_client.get_invoice("inv123")
        url = str(respx.calls[0].request.url)
        parsed = urlparse(url)
        params = parse_qs(parsed.query)
        assert "token" in params
        assert params["token"] == [merchant_token]

    @respx.mock
    async def test_no_request_body(self, merchant_client):
        """SDK: GET requests have no body."""
        respx.get(url__startswith=f"{BITPAY_TEST_URL}/invoices/inv123").mock(
            return_value=_ok({"id": "inv123"})
        )
        await merchant_client.get_invoice("inv123")
        content = respx.calls[0].request.content
        assert content == b"" or content is None

    @respx.mock
    async def test_signing_headers_present(self, merchant_client):
        """SDK: signature_required=True -> identity+signature."""
        respx.get(url__startswith=f"{BITPAY_TEST_URL}/invoices/inv123").mock(
            return_value=_ok({"id": "inv123"})
        )
        await merchant_client.get_invoice("inv123")
        headers = respx.calls[0].request.headers
        assert "x-identity" in headers
        assert "x-signature" in headers

    @respx.mock
    async def test_identity_is_compressed_pubkey(
        self, merchant_client, pem_key
    ):
        """SDK: x-identity = get_compressed_public_key_from_pem(ec_key).
        Must be 66-char hex, matching our compressed key for the same PEM."""
        respx.get(url__startswith=f"{BITPAY_TEST_URL}/invoices/inv123").mock(
            return_value=_ok({"id": "inv123"})
        )
        await merchant_client.get_invoice("inv123")
        identity = respx.calls[0].request.headers["x-identity"]
        expected = get_compressed_public_key(pem_key)
        assert identity == expected

    @respx.mock
    async def test_signature_verifiable_with_sha256(
        self, merchant_client, pem_key
    ):
        """SDK signs URL with SHA-256. Our signature must verify under SHA-256.

        SDK signing input for GET: the full URL including query params.
        """
        respx.get(url__startswith=f"{BITPAY_TEST_URL}/invoices/inv123").mock(
            return_value=_ok({"id": "inv123"})
        )
        await merchant_client.get_invoice("inv123")
        request = respx.calls[0].request
        sig_hex = request.headers["x-signature"]
        sig_bytes = bytes.fromhex(sig_hex)
        # SDK signs the full URL (with query params)
        signed_content = str(request.url)

        sk = SigningKey.from_pem(pem_key)
        vk = sk.get_verifying_key()
        vk.verify(
            sig_bytes,
            signed_content.encode("utf-8"),
            hashfunc=hashlib.sha256,
            sigdecode=sigdecode_der,
        )

    async def test_requires_merchant_credentials(self, pos_client):
        """SDK: merchant facade requires ec_key + merchant token.
        Missing credentials should raise before any HTTP call."""
        with pytest.raises(CredentialsError):
            await pos_client.get_invoice("inv123")


# ===================================================================
# 5. Cancel Invoice — DELETE /invoices/{id} (merchant facade)
# ===================================================================


class TestCancelInvoiceBehavior:
    """Behavioral equivalence with InvoiceClient.cancel().

    SDK: DELETE ``{base_url}invoices/{id}?token={token}&forceCancel={bool}``
    Parameters go in query string. No request body. Always signed.
    """

    @respx.mock
    async def test_uses_delete_method(self, merchant_client):
        """SDK: self.__bitpay_client.delete(...)"""
        route = respx.delete(
            url__startswith=f"{BITPAY_TEST_URL}/invoices/inv123"
        ).mock(return_value=_ok({"id": "inv123", "status": "expired"}))
        await merchant_client.cancel_invoice("inv123")
        assert route.calls[0].request.method == "DELETE"

    @respx.mock
    async def test_token_in_query_params(self, merchant_client, merchant_token):
        """SDK: params = {"token": token, "forceCancel": False}
        These go into URL query string via urllib.parse.urlencode."""
        respx.delete(url__startswith=f"{BITPAY_TEST_URL}/invoices/inv123").mock(
            return_value=_ok({"id": "inv123"})
        )
        await merchant_client.cancel_invoice("inv123")
        url = str(respx.calls[0].request.url)
        parsed = urlparse(url)
        params = parse_qs(parsed.query)
        assert "token" in params
        assert params["token"] == [merchant_token]

    @respx.mock
    async def test_no_request_body(self, merchant_client):
        """SDK: BitPayClient.delete() sends no request body.
        Query parameters are the only way data is passed."""
        respx.delete(url__startswith=f"{BITPAY_TEST_URL}/invoices/inv123").mock(
            return_value=_ok({"id": "inv123"})
        )
        await merchant_client.cancel_invoice("inv123")
        content = respx.calls[0].request.content
        assert content == b"" or content is None

    @respx.mock
    async def test_force_cancel_default_false_in_query(
        self, merchant_client, merchant_token
    ):
        """SDK: forceCancel is always sent, defaults to False.
        ``params = {"token": ..., "forceCancel": False}``"""
        respx.delete(url__startswith=f"{BITPAY_TEST_URL}/invoices/inv123").mock(
            return_value=_ok({"id": "inv123"})
        )
        await merchant_client.cancel_invoice("inv123")
        url = str(respx.calls[0].request.url)
        parsed = urlparse(url)
        params = parse_qs(parsed.query)
        assert "forceCancel" in params
        assert params["forceCancel"] == ["False"]

    @respx.mock
    async def test_force_cancel_true_in_query(
        self, merchant_client, merchant_token
    ):
        """SDK: forceCancel=True passed as query parameter."""
        respx.delete(url__startswith=f"{BITPAY_TEST_URL}/invoices/inv123").mock(
            return_value=_ok({"id": "inv123"})
        )
        await merchant_client.cancel_invoice("inv123", force=True)
        url = str(respx.calls[0].request.url)
        parsed = urlparse(url)
        params = parse_qs(parsed.query)
        assert "forceCancel" in params
        assert params["forceCancel"] == ["True"]

    @respx.mock
    async def test_signing_headers_present(self, merchant_client):
        """SDK: delete() always signs — x-identity and x-signature required."""
        respx.delete(url__startswith=f"{BITPAY_TEST_URL}/invoices/inv123").mock(
            return_value=_ok({"id": "inv123"})
        )
        await merchant_client.cancel_invoice("inv123")
        headers = respx.calls[0].request.headers
        assert "x-identity" in headers
        assert "x-signature" in headers

    @respx.mock
    async def test_response_extracts_data(self, merchant_client):
        """SDK: ResponseParser extracts ``data`` from envelope."""
        respx.delete(url__startswith=f"{BITPAY_TEST_URL}/invoices/inv123").mock(
            return_value=_ok({"id": "inv123", "status": "expired"})
        )
        result = await merchant_client.cancel_invoice("inv123")
        assert result["id"] == "inv123"
        assert result["status"] == "expired"


# ===================================================================
# 6. Create Refund — POST /refunds (merchant facade)
# ===================================================================


class TestCreateRefundBehavior:
    """Behavioral equivalence with RefundClient.create().

    SDK: POST ``{base_url}refunds`` with signed body containing token,
    invoiceId, amount, guid, preview, immediate, buyerPaysRefundFee.
    """

    @respx.mock
    async def test_posts_to_refunds_endpoint(self, merchant_client):
        """SDK: self.__bitpay_client.post("refunds", ..., True)"""
        route = respx.post(f"{BITPAY_TEST_URL}/refunds").mock(
            return_value=_ok({"id": "ref1"})
        )
        await merchant_client.create_refund(invoice_id="inv1", amount=5.0)
        assert route.called

    @respx.mock
    async def test_token_in_body(self, merchant_client, merchant_token):
        """SDK: params["token"] = token_container.get_access_token(MERCHANT)"""
        respx.post(f"{BITPAY_TEST_URL}/refunds").mock(
            return_value=_ok({"id": "ref1"})
        )
        await merchant_client.create_refund(invoice_id="inv1", amount=5.0)
        body = json.loads(respx.calls[0].request.content)
        assert body["token"] == merchant_token

    @respx.mock
    async def test_invoice_id_field_name(self, merchant_client):
        """SDK: params["invoiceId"] = invoice_id (camelCase)."""
        respx.post(f"{BITPAY_TEST_URL}/refunds").mock(
            return_value=_ok({"id": "ref1"})
        )
        await merchant_client.create_refund(invoice_id="inv-abc", amount=10.0)
        body = json.loads(respx.calls[0].request.content)
        assert body["invoiceId"] == "inv-abc"

    @respx.mock
    async def test_amount_field(self, merchant_client):
        """SDK: params["amount"] = amount."""
        respx.post(f"{BITPAY_TEST_URL}/refunds").mock(
            return_value=_ok({"id": "ref1"})
        )
        await merchant_client.create_refund(invoice_id="inv1", amount=42.99)
        body = json.loads(respx.calls[0].request.content)
        assert body["amount"] == 42.99

    @respx.mock
    async def test_preview_default_false(self, merchant_client):
        """SDK: params["preview"] = preview, default False."""
        respx.post(f"{BITPAY_TEST_URL}/refunds").mock(
            return_value=_ok({"id": "ref1"})
        )
        await merchant_client.create_refund(invoice_id="inv1", amount=5.0)
        body = json.loads(respx.calls[0].request.content)
        assert body["preview"] is False

    @respx.mock
    async def test_immediate_default_false(self, merchant_client):
        """SDK: params["immediate"] = immediate, default False."""
        respx.post(f"{BITPAY_TEST_URL}/refunds").mock(
            return_value=_ok({"id": "ref1"})
        )
        await merchant_client.create_refund(invoice_id="inv1", amount=5.0)
        body = json.loads(respx.calls[0].request.content)
        assert body["immediate"] is False

    @respx.mock
    async def test_preview_true(self, merchant_client):
        """SDK: preview=True goes into body."""
        respx.post(f"{BITPAY_TEST_URL}/refunds").mock(
            return_value=_ok({"id": "ref1"})
        )
        await merchant_client.create_refund(
            invoice_id="inv1", amount=5.0, preview=True
        )
        body = json.loads(respx.calls[0].request.content)
        assert body["preview"] is True

    @respx.mock
    async def test_immediate_true(self, merchant_client):
        """SDK: immediate=True goes into body."""
        respx.post(f"{BITPAY_TEST_URL}/refunds").mock(
            return_value=_ok({"id": "ref1"})
        )
        await merchant_client.create_refund(
            invoice_id="inv1", amount=5.0, immediate=True
        )
        body = json.loads(respx.calls[0].request.content)
        assert body["immediate"] is True

    @respx.mock
    async def test_reference_optional(self, merchant_client):
        """SDK: reference is only added if not None."""
        respx.post(f"{BITPAY_TEST_URL}/refunds").mock(
            return_value=_ok({"id": "ref1"})
        )
        await merchant_client.create_refund(
            invoice_id="inv1", amount=5.0, reference="my-ref-001"
        )
        body = json.loads(respx.calls[0].request.content)
        assert body["reference"] == "my-ref-001"

    @respx.mock
    async def test_reference_omitted_by_default(self, merchant_client):
        """SDK: reference not in params when not provided."""
        respx.post(f"{BITPAY_TEST_URL}/refunds").mock(
            return_value=_ok({"id": "ref1"})
        )
        await merchant_client.create_refund(invoice_id="inv1", amount=5.0)
        body = json.loads(respx.calls[0].request.content)
        assert "reference" not in body

    @respx.mock
    async def test_signing_headers_present(self, merchant_client):
        """SDK: sign_request=True for refunds — always signed."""
        respx.post(f"{BITPAY_TEST_URL}/refunds").mock(
            return_value=_ok({"id": "ref1"})
        )
        await merchant_client.create_refund(invoice_id="inv1", amount=5.0)
        headers = respx.calls[0].request.headers
        assert "x-identity" in headers
        assert "x-signature" in headers

    @respx.mock
    async def test_signature_verifiable_with_sha256(
        self, merchant_client, pem_key
    ):
        """SDK signs URL+body with SHA-256 for POST requests."""
        respx.post(f"{BITPAY_TEST_URL}/refunds").mock(
            return_value=_ok({"id": "ref1"})
        )
        await merchant_client.create_refund(invoice_id="inv1", amount=5.0)
        request = respx.calls[0].request
        sig_hex = request.headers["x-signature"]
        sig_bytes = bytes.fromhex(sig_hex)
        # SDK signing input for POST: full_url + json_body
        signed_content = str(request.url) + request.content.decode("utf-8")

        sk = SigningKey.from_pem(pem_key)
        vk = sk.get_verifying_key()
        vk.verify(
            sig_bytes,
            signed_content.encode("utf-8"),
            hashfunc=hashlib.sha256,
            sigdecode=sigdecode_der,
        )

    @respx.mock
    async def test_error_raises_refund_failure(self, merchant_client):
        """SDK: API error on refund create -> exception.
        Our client wraps CommunicationError into RefundFailure."""
        respx.post(f"{BITPAY_TEST_URL}/refunds").mock(
            return_value=httpx.Response(
                400, json={"error": "Invoice not eligible for refund"}
            )
        )
        with pytest.raises(RefundFailure):
            await merchant_client.create_refund(invoice_id="inv1", amount=5.0)

    async def test_requires_merchant_credentials(self, pos_client):
        """SDK: merchant facade requires credentials."""
        with pytest.raises(CredentialsError):
            await pos_client.create_refund(invoice_id="inv1", amount=5.0)


# ===================================================================
# 7. Get Refund — GET /refunds/{id} (merchant facade)
# ===================================================================


class TestGetRefundBehavior:
    """Behavioral equivalence with RefundClient.get().

    SDK: GET ``{base_url}refunds/{id}?token={merchant_token}``
    Signed. No request body.
    """

    @respx.mock
    async def test_uses_get_method(self, merchant_client):
        """SDK: self.__bitpay_client.get(...)"""
        route = respx.get(
            url__startswith=f"{BITPAY_TEST_URL}/refunds/ref123"
        ).mock(return_value=_ok({"id": "ref123", "status": "success"}))
        await merchant_client.get_refund("ref123")
        assert route.calls[0].request.method == "GET"

    @respx.mock
    async def test_token_in_query_params(self, merchant_client, merchant_token):
        """SDK: params = {"token": merchant_token} -> query string."""
        respx.get(url__startswith=f"{BITPAY_TEST_URL}/refunds/ref123").mock(
            return_value=_ok({"id": "ref123"})
        )
        await merchant_client.get_refund("ref123")
        url = str(respx.calls[0].request.url)
        parsed = urlparse(url)
        params = parse_qs(parsed.query)
        assert "token" in params
        assert params["token"] == [merchant_token]

    @respx.mock
    async def test_no_request_body(self, merchant_client):
        """SDK: GET requests have no body."""
        respx.get(url__startswith=f"{BITPAY_TEST_URL}/refunds/ref123").mock(
            return_value=_ok({"id": "ref123"})
        )
        await merchant_client.get_refund("ref123")
        content = respx.calls[0].request.content
        assert content == b"" or content is None

    @respx.mock
    async def test_signing_headers_present(self, merchant_client):
        """SDK: get() defaults signature_required=True."""
        respx.get(url__startswith=f"{BITPAY_TEST_URL}/refunds/ref123").mock(
            return_value=_ok({"id": "ref123"})
        )
        await merchant_client.get_refund("ref123")
        headers = respx.calls[0].request.headers
        assert "x-identity" in headers
        assert "x-signature" in headers

    @respx.mock
    async def test_response_extracts_data(self, merchant_client):
        """SDK: ResponseParser extracts ``data``."""
        respx.get(url__startswith=f"{BITPAY_TEST_URL}/refunds/ref123").mock(
            return_value=_ok(
                {"id": "ref123", "status": "success", "amount": 5.0}
            )
        )
        result = await merchant_client.get_refund("ref123")
        assert result["id"] == "ref123"
        assert result["status"] == "success"
        assert result["amount"] == 5.0

    async def test_requires_merchant_credentials(self, pos_client):
        """SDK: merchant facade requires credentials."""
        with pytest.raises(CredentialsError):
            await pos_client.get_refund("ref123")


# ===================================================================
# 8. Cancel Refund — DELETE /refunds/{id} (merchant facade)
# ===================================================================


class TestCancelRefundBehavior:
    """Behavioral equivalence with RefundClient.cancel().

    SDK: DELETE ``{base_url}refunds/{id}?token={merchant_token}``
    Parameters as query string. No body. Always signed.
    """

    @respx.mock
    async def test_uses_delete_method(self, merchant_client):
        """SDK: self.__bitpay_client.delete(...)"""
        route = respx.delete(
            url__startswith=f"{BITPAY_TEST_URL}/refunds/ref123"
        ).mock(return_value=_ok({"id": "ref123", "status": "cancelled"}))
        await merchant_client.cancel_refund("ref123")
        assert route.calls[0].request.method == "DELETE"

    @respx.mock
    async def test_token_in_query_params(self, merchant_client, merchant_token):
        """SDK: params = {"token": merchant_token} -> query string."""
        respx.delete(url__startswith=f"{BITPAY_TEST_URL}/refunds/ref123").mock(
            return_value=_ok({"id": "ref123", "status": "cancelled"})
        )
        await merchant_client.cancel_refund("ref123")
        url = str(respx.calls[0].request.url)
        parsed = urlparse(url)
        params = parse_qs(parsed.query)
        assert "token" in params
        assert params["token"] == [merchant_token]

    @respx.mock
    async def test_no_request_body(self, merchant_client):
        """SDK: delete() sends no request body."""
        respx.delete(url__startswith=f"{BITPAY_TEST_URL}/refunds/ref123").mock(
            return_value=_ok({"id": "ref123", "status": "cancelled"})
        )
        await merchant_client.cancel_refund("ref123")
        content = respx.calls[0].request.content
        assert content == b"" or content is None

    @respx.mock
    async def test_signing_headers_present(self, merchant_client):
        """SDK: delete() always signs."""
        respx.delete(url__startswith=f"{BITPAY_TEST_URL}/refunds/ref123").mock(
            return_value=_ok({"id": "ref123", "status": "cancelled"})
        )
        await merchant_client.cancel_refund("ref123")
        headers = respx.calls[0].request.headers
        assert "x-identity" in headers
        assert "x-signature" in headers

    @respx.mock
    async def test_response_extracts_data(self, merchant_client):
        """SDK: ResponseParser extracts ``data``."""
        respx.delete(url__startswith=f"{BITPAY_TEST_URL}/refunds/ref123").mock(
            return_value=_ok({"id": "ref123", "status": "cancelled"})
        )
        result = await merchant_client.cancel_refund("ref123")
        assert result["id"] == "ref123"
        assert result["status"] == "cancelled"


# ===================================================================
# 9. Response parsing — behavioral equivalence with ResponseParser
# ===================================================================


class TestResponseParsingBehavior:
    """Behavioral equivalence with ResponseParser.response_to_json_string().

    SDK response handling priority:
    1. {"status": "error", "error": msg, "code": code} -> exception
    2. {"error": msg} -> exception
    3. {"errors": [...]} -> exception with concatenated messages
    4. {"success": val} -> return val
    5. {"data": val} -> return val
    6. fallback -> return entire object
    """

    @respx.mock
    async def test_error_key_raises(self, pos_client):
        """SDK: top-level ``error`` key -> BitPayApiException."""
        respx.post(f"{BITPAY_TEST_URL}/invoices").mock(
            return_value=httpx.Response(400, json={"error": "Unauthorized"})
        )
        with pytest.raises(LockFailure):
            await pos_client.create_invoice(price=1.0, currency="USD")

    @respx.mock
    async def test_status_error_raises(self, pos_client):
        """SDK: {"status": "error", "error": msg, "code": code}
        raises BitPayApiException. Our client should also raise."""
        respx.post(f"{BITPAY_TEST_URL}/invoices").mock(
            return_value=httpx.Response(
                200,
                json={
                    "status": "error",
                    "error": "Rate limit exceeded",
                    "code": "000001",
                },
            )
        )
        # The response has "error" key so our client catches it too
        with pytest.raises(LockFailure):
            await pos_client.create_invoice(price=1.0, currency="USD")

    @respx.mock
    async def test_errors_array_raises(self, pos_client):
        """SDK: {"errors": [{"error": "msg1", "param": "field1"}, ...]}
        raises BitPayApiException with concatenated message."""
        respx.post(f"{BITPAY_TEST_URL}/invoices").mock(
            return_value=httpx.Response(
                422,
                json={
                    "errors": [
                        {"error": "Invalid value", "param": "currency"},
                        {"error": "Required field", "param": "price"},
                    ]
                },
            )
        )
        with pytest.raises(LockFailure):
            await pos_client.create_invoice(price=0, currency="")

    @respx.mock
    async def test_data_envelope_extracted(self, pos_client):
        """SDK: {"data": {...}} -> returns the inner dict."""
        respx.post(f"{BITPAY_TEST_URL}/invoices").mock(
            return_value=httpx.Response(
                200, json={"data": {"id": "inv1", "status": "new"}}
            )
        )
        result = await pos_client.create_invoice(price=1.0, currency="USD")
        assert result == {"id": "inv1", "status": "new"}

    @respx.mock
    async def test_non_json_response_raises(self, pos_client):
        """SDK: response.json() failure -> exception propagation.
        Our client should raise CommunicationError for invalid JSON."""
        respx.post(f"{BITPAY_TEST_URL}/invoices").mock(
            return_value=httpx.Response(500, text="Internal Server Error")
        )
        with pytest.raises((LockFailure, CommunicationError)):
            await pos_client.create_invoice(price=1.0, currency="USD")

    @respx.mock
    async def test_http_error_without_error_body(self, pos_client):
        """If the response is non-2xx but has valid JSON without ``error``
        key, our client should still raise (via is_success check)."""
        respx.post(f"{BITPAY_TEST_URL}/invoices").mock(
            return_value=httpx.Response(
                403, json={"data": {"message": "forbidden"}}
            )
        )
        with pytest.raises((LockFailure, CommunicationError)):
            await pos_client.create_invoice(price=1.0, currency="USD")


# ===================================================================
# 10. Context manager behavior
# ===================================================================


class TestContextManagerBehavior:
    """Verify async context manager works for connection reuse."""

    @respx.mock
    async def test_multiple_calls_reuse_connection(self, pos_token):
        """Using context manager should allow multiple calls."""
        respx.post(f"{BITPAY_TEST_URL}/invoices").mock(
            return_value=_ok({"id": "inv1"})
        )

        async with BitPayClient(
            base_url=BITPAY_TEST_URL,
            pos_token=pos_token,
        ) as client:
            await client.create_invoice(price=1.0, currency="USD")
            await client.create_invoice(price=2.0, currency="EUR")

        assert respx.calls.call_count == 2

"""Async HTTP client for BitPay REST API v2.

Supports both POS facade (token-only) and merchant facade
(EC key signed requests) authentication modes.
"""

import json
import logging

import httpx
from getpaid_core.exceptions import CommunicationError
from getpaid_core.exceptions import CredentialsError
from getpaid_core.exceptions import LockFailure
from getpaid_core.exceptions import RefundFailure

from .signing import get_compressed_public_key
from .signing import sign


logger = logging.getLogger(__name__)

_API_VERSION = "2.0.0"


class BitPayClient:
    """Async client for BitPay REST API.

    Uses ``httpx.AsyncClient`` for all HTTP communication.

    Can be used as an async context manager for connection reuse::

        async with BitPayClient(...) as client:
            await client.create_invoice(...)
    """

    def __init__(
        self,
        base_url: str,
        pos_token: str,
        merchant_token: str | None = None,
        private_key_pem: str | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.pos_token = pos_token
        self.merchant_token = merchant_token
        self.private_key_pem = private_key_pem
        self._client: httpx.AsyncClient | None = None
        self._owns_client: bool = False

    async def __aenter__(self) -> "BitPayClient":
        self._client = httpx.AsyncClient()
        self._owns_client = True
        return self

    async def __aexit__(self, *exc) -> None:
        if self._owns_client and self._client is not None:
            await self._client.aclose()
            self._client = None
            self._owns_client = False

    def _require_merchant(self) -> None:
        """Raise if merchant facade is not configured."""
        if not self.merchant_token or not self.private_key_pem:
            raise CredentialsError(
                "Merchant facade requires merchant_token and "
                "private_key_pem to be configured."
            )

    def _common_headers(self) -> dict[str, str]:
        """Headers included in every request."""
        return {
            "content-type": "application/json",
            "x-accept-version": _API_VERSION,
        }

    def _sign_headers(self, url: str, body: str) -> dict[str, str]:
        """Add signing headers for merchant facade requests."""
        assert self.private_key_pem is not None
        return {
            "x-identity": get_compressed_public_key(self.private_key_pem),
            "x-signature": sign(url + body, self.private_key_pem),
        }

    async def _request(
        self,
        method: str,
        url: str,
        *,
        body: str | None = None,
        signed: bool = False,
    ) -> dict:
        """Execute HTTP request and unwrap BitPay response envelope.

        Returns the ``data`` field from the response JSON.
        """
        headers = self._common_headers()
        if signed:
            self._require_merchant()
            headers.update(self._sign_headers(url, body or ""))

        if self._client is not None:
            response = await self._client.request(
                method,
                url,
                headers=headers,
                content=body,
            )
        else:
            async with httpx.AsyncClient() as client:
                response = await client.request(
                    method,
                    url,
                    headers=headers,
                    content=body,
                )

        return self._parse_response(response)

    def _parse_response(self, response: httpx.Response) -> dict:
        """Parse BitPay response, raising on errors."""
        try:
            payload = response.json()
        except Exception as exc:
            raise CommunicationError(
                "Invalid JSON response from BitPay",
                context={"status_code": response.status_code},
            ) from exc

        if "error" in payload:
            error_msg = payload["error"]
            code = payload.get("code", "")
            raise CommunicationError(
                f"BitPay API error: {error_msg} (code={code})",
                context={"raw_response": payload},
            )

        if "errors" in payload:
            errors = payload["errors"]
            messages = ", ".join(
                e.get("error", str(e)) if isinstance(e, dict) else str(e)
                for e in errors
            )
            raise CommunicationError(
                f"BitPay API errors: {messages}",
                context={"raw_response": payload},
            )

        if not response.is_success:
            raise CommunicationError(
                f"BitPay HTTP {response.status_code}",
                context={"raw_response": payload},
            )

        return payload.get("data", payload)

    # --- Invoice methods ---

    async def create_invoice(
        self,
        price: float,
        currency: str = "USD",
        order_id: str | None = None,
        notification_url: str | None = None,
        redirect_url: str | None = None,
        buyer_email: str | None = None,
        buyer_name: str | None = None,
        item_desc: str | None = None,
        **kwargs,
    ) -> dict:
        """Create a BitPay invoice.

        Uses POS facade (token in body, no signing).
        """
        url = f"{self.base_url}/invoices"
        data: dict = {
            "token": self.pos_token,
            "price": price,
            "currency": currency,
        }
        if order_id is not None:
            data["orderId"] = order_id
        if notification_url is not None:
            data["notificationURL"] = notification_url
        if redirect_url is not None:
            data["redirectURL"] = redirect_url
        if item_desc is not None:
            data["itemDesc"] = item_desc

        buyer: dict = {}
        if buyer_email is not None:
            buyer["email"] = buyer_email
        if buyer_name is not None:
            buyer["name"] = buyer_name
        if buyer:
            data["buyer"] = buyer

        data.update(kwargs)
        body = json.dumps(data)

        try:
            return await self._request("POST", url, body=body)
        except CommunicationError as exc:
            raise LockFailure(
                "Failed to create BitPay invoice",
                context=exc.context,
            ) from exc

    async def get_invoice(self, invoice_id: str) -> dict:
        """Retrieve an invoice by ID. Requires merchant facade."""
        self._require_merchant()
        url = (
            f"{self.base_url}/invoices/{invoice_id}?token={self.merchant_token}"
        )
        return await self._request("GET", url, signed=True)

    async def cancel_invoice(
        self,
        invoice_id: str,
        force: bool = False,
    ) -> dict:
        """Cancel an invoice. Requires merchant facade."""
        self._require_merchant()
        url = (
            f"{self.base_url}/invoices/{invoice_id}"
            f"?token={self.merchant_token}"
            f"&forceCancel={force}"
        )
        return await self._request("DELETE", url, signed=True)

    # --- Refund methods ---

    async def create_refund(
        self,
        invoice_id: str,
        amount: float,
        preview: bool = False,
        immediate: bool = False,
        reference: str | None = None,
        **kwargs,
    ) -> dict:
        """Create a refund. Requires merchant facade."""
        self._require_merchant()
        url = f"{self.base_url}/refunds"
        data: dict = {
            "token": self.merchant_token,
            "invoiceId": invoice_id,
            "amount": amount,
            "preview": preview,
            "immediate": immediate,
        }
        if reference is not None:
            data["reference"] = reference
        data.update(kwargs)
        body = json.dumps(data)

        try:
            return await self._request("POST", url, body=body, signed=True)
        except CommunicationError as exc:
            raise RefundFailure(
                "Failed to create BitPay refund",
                context=exc.context,
            ) from exc

    async def get_refund(self, refund_id: str) -> dict:
        """Retrieve a refund by ID. Requires merchant facade."""
        self._require_merchant()
        url = f"{self.base_url}/refunds/{refund_id}?token={self.merchant_token}"
        return await self._request("GET", url, signed=True)

    async def cancel_refund(self, refund_id: str) -> dict:
        """Cancel a refund. Requires merchant facade."""
        self._require_merchant()
        url = f"{self.base_url}/refunds/{refund_id}?token={self.merchant_token}"
        return await self._request("DELETE", url, signed=True)

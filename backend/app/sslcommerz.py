"""Server-side SSLCOMMERZ payment client for DisasterNet.

Credentials are read only from environment variables.  The frontend never sees
``SSLCOMMERZ_STORE_PASSWORD``.  This module supports both Sandbox and Live
endpoints and keeps all provider communication on the FastAPI server.
"""

from __future__ import annotations

import json
import os
from typing import Any, Dict

import requests


class SSLCommerzConfigurationError(RuntimeError):
    """Raised when required SSLCOMMERZ credentials are missing."""


class SSLCommerzAPIError(RuntimeError):
    """Raised when SSLCOMMERZ returns an error or cannot be reached."""


class SSLCommerzClient:
    def __init__(self) -> None:
        self.store_id = os.getenv("SSLCOMMERZ_STORE_ID", "").strip()
        self.store_password = os.getenv("SSLCOMMERZ_STORE_PASSWORD", "").strip()
        self.sandbox = os.getenv("SSLCOMMERZ_SANDBOX", "true").strip().lower() in {
            "1",
            "true",
            "yes",
            "on",
        }

        configured_base = os.getenv("SSLCOMMERZ_BASE_URL", "").strip().rstrip("/")
        if configured_base:
            self.base_url = configured_base
        else:
            self.base_url = (
                "https://sandbox.sslcommerz.com"
                if self.sandbox
                else "https://securepay.sslcommerz.com"
            )
        self.session = requests.Session()

    @property
    def configured(self) -> bool:
        return bool(self.store_id and self.store_password)

    def configuration_status(self) -> Dict[str, Any]:
        """Return only non-secret configuration state for the frontend."""
        return {
            "configured": self.configured,
            "sandbox": self.sandbox,
            "store_id_configured": bool(self.store_id),
            "store_password_configured": bool(self.store_password),
            "base_url": self.base_url,
        }

    def _require_configured(self) -> None:
        if not self.configured:
            raise SSLCommerzConfigurationError(
                "SSLCOMMERZ Sandbox credentials are not configured. Set "
                "SSLCOMMERZ_STORE_ID and SSLCOMMERZ_STORE_PASSWORD in backend/.env."
            )

    @staticmethod
    def _json_response(response: requests.Response) -> Dict[str, Any]:
        try:
            data = response.json()
        except ValueError as exc:
            raise SSLCommerzAPIError("SSLCOMMERZ returned an invalid response") from exc
        if response.status_code >= 400:
            message = (
                data.get("failedreason")
                or data.get("errorReason")
                or data.get("message")
                or f"SSLCOMMERZ HTTP {response.status_code}"
            )
            raise SSLCommerzAPIError(str(message))
        return data

    def create_payment(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """Create a Hosted Checkout session and return SSLCOMMERZ response."""
        self._require_configured()
        request_payload = {
            **payload,
            "store_id": self.store_id,
            "store_passwd": self.store_password,
        }
        try:
            response = self.session.post(
                f"{self.base_url}/gwprocess/v4/api.php",
                data=request_payload,
                timeout=30,
            )
        except requests.RequestException as exc:
            raise SSLCommerzAPIError("Could not connect to SSLCOMMERZ") from exc

        data = self._json_response(response)
        if data.get("status") != "SUCCESS" or not data.get("GatewayPageURL"):
            raise SSLCommerzAPIError(
                str(data.get("failedreason") or "SSLCOMMERZ payment session creation failed")
            )
        return data

    def validate_payment(self, val_id: str) -> Dict[str, Any]:
        """Validate a successful payment using SSLCOMMERZ Order Validation API."""
        self._require_configured()
        try:
            response = self.session.get(
                f"{self.base_url}/validator/api/validationserverAPI.php",
                params={
                    "val_id": val_id,
                    "store_id": self.store_id,
                    "store_passwd": self.store_password,
                    "format": "json",
                },
                timeout=30,
            )
        except requests.RequestException as exc:
            raise SSLCommerzAPIError("Could not validate the SSLCOMMERZ payment") from exc
        return self._json_response(response)

    def query_by_transaction_id(self, tran_id: str) -> Dict[str, Any]:
        """Query payment status by the merchant transaction ID."""
        self._require_configured()
        try:
            response = self.session.get(
                f"{self.base_url}/validator/api/merchantTransIDvalidationAPI.php",
                params={
                    "tran_id": tran_id,
                    "store_id": self.store_id,
                    "store_passwd": self.store_password,
                    "format": "json",
                },
                timeout=30,
            )
        except requests.RequestException as exc:
            raise SSLCommerzAPIError("Could not query the SSLCOMMERZ payment") from exc
        return self._json_response(response)

    def initiate_refund(
        self,
        *,
        bank_tran_id: str,
        refund_trans_id: str,
        amount: float,
        remarks: str,
        reference_id: str,
    ) -> Dict[str, Any]:
        """Initiate a full or partial refund using the V4 refund API."""
        self._require_configured()
        try:
            response = self.session.get(
                f"{self.base_url}/validator/api/merchantTransIDvalidationAPI.php",
                params={
                    "bank_tran_id": bank_tran_id,
                    "refund_trans_id": refund_trans_id,
                    "store_id": self.store_id,
                    "store_passwd": self.store_password,
                    "refund_amount": f"{amount:.2f}",
                    "refund_remarks": remarks,
                    "refe_id": reference_id,
                    "format": "json",
                },
                timeout=30,
            )
        except requests.RequestException as exc:
            raise SSLCommerzAPIError("Could not submit the SSLCOMMERZ refund") from exc
        return self._json_response(response)

    def query_refund(self, refund_ref_id: str) -> Dict[str, Any]:
        self._require_configured()
        try:
            response = self.session.get(
                f"{self.base_url}/validator/api/merchantTransIDvalidationAPI.php",
                params={
                    "refund_ref_id": refund_ref_id,
                    "store_id": self.store_id,
                    "store_passwd": self.store_password,
                    "format": "json",
                },
                timeout=30,
            )
        except requests.RequestException as exc:
            raise SSLCommerzAPIError("Could not query the SSLCOMMERZ refund") from exc
        return self._json_response(response)


def sanitize_sslcommerz_response(data: Dict[str, Any] | None) -> str | None:
    """Serialize provider responses without storing merchant credentials."""
    if data is None:
        return None
    scrubbed = {
        key: value
        for key, value in data.items()
        if key.lower() not in {"store_passwd", "store_password", "password"}
    }
    return json.dumps(scrubbed, ensure_ascii=False, default=str)


sslcommerz_client = SSLCommerzClient()

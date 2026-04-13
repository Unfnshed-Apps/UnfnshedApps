"""
API client for the Unfnship shipping application.
"""

from __future__ import annotations

from typing import Optional

from shared.api_client_base import APIClientBase
from .config import load_config, get_suggested_device_name


class APIClient(APIClientBase):
    """API client for shipping and order fulfillment."""

    ENV_PREFIX = "UNFNSHIP"

    def __init__(self, api_url=None, api_key=None, device_name=None, timeout=10.0):
        config = load_config()
        super().__init__(
            api_url=api_url, api_key=api_key, device_name=device_name,
            timeout=timeout,
            config_api_url=config.api_url,
            config_api_key=config.api_key,
            config_device_name=config.device_name,
            config_lan_server_ip=config.lan_server_ip,
            suggested_device_name=get_suggested_device_name(),
        )

    # ==================== Shipping Queue ====================

    def get_shipping_queue(self) -> list[dict]:
        """Get unfulfilled orders with stock availability."""
        return self._get("/shipping/queue")

    # ==================== Status ====================

    def get_shipping_status(self) -> dict:
        """Get current Shippo mode + key configuration state.

        Returns ``{test_mode, active_key_present, test_key_stored,
        live_key_stored}``. The client uses this to drive the TEST MODE
        banner and to enable/disable mutation buttons (Print Label,
        Mark Fulfilled).
        """
        return self._get("/shipping/status")

    # ==================== Rates ====================

    def get_rates(self, order_id: int, weight_lbs: float,
                  length_in: float, width_in: float, height_in: float) -> dict:
        """Fetch shipping rates from Shippo via the server.

        Returns ``{rates: [...], test_mode: bool}``. The ``test_mode`` field
        is the server's authoritative answer for the active mode at the
        moment the rates were fetched; the client uses it to detect drift
        from its local banner state.
        """
        return self._post("/shipping/rates", {
            "order_id": order_id,
            "weight_lbs": weight_lbs,
            "length_in": length_in,
            "width_in": width_in,
            "height_in": height_in,
        })

    def purchase_label(self, rate_id: str, order_id: int) -> dict:
        """Purchase a shipping label for a quoted rate."""
        return self._post("/shipping/purchase-label", {
            "rate_id": rate_id,
            "order_id": order_id,
        })

    # ==================== Fulfillment ====================

    def fulfill_order(self, order_id: int, tracking_number: str = "",
                      carrier: str = "") -> dict:
        """Mark an order as fulfilled and deduct inventory."""
        return self._post("/shipping/fulfill", {
            "order_id": order_id,
            "tracking_number": tracking_number,
            "carrier": carrier,
        })

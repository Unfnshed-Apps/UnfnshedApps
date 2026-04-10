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

    # ==================== Rates ====================

    def get_rates(self, order_id: int, weight_lbs: float,
                  length_in: float, width_in: float, height_in: float) -> list[dict]:
        """Fetch shipping rates from Shippo via the server."""
        return self._post("/shipping/rates", {
            "order_id": order_id,
            "weight_lbs": weight_lbs,
            "length_in": length_in,
            "width_in": width_in,
            "height_in": height_in,
        })

    def purchase_label(self, rate_id: str) -> Optional[dict]:
        """Purchase a shipping label. Stub — returns mock data."""
        # TODO: Replace with Shippo API call
        return {
            "label_url": "https://example.com/mock-label.pdf",
            "tracking_number": "MOCK1234567890",
            "carrier": "USPS",
        }

    # ==================== Fulfillment ====================

    def fulfill_order(self, order_id: int, tracking_number: str = "",
                      carrier: str = "") -> Optional[dict]:
        """Mark an order as fulfilled and deduct inventory. Stub."""
        # TODO: Implement server endpoint
        return {"status": "fulfilled"}

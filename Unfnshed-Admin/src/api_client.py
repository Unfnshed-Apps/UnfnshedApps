"""
API client for the Unfnshed Admin application.
"""

from __future__ import annotations

from shared.api_client_base import APIClientBase
from .config import load_config, get_suggested_device_name


class APIClient(APIClientBase):
    """API client for admin operations — Shopify settings, sync, orders."""

    ENV_PREFIX = "UNFNSHED_ADMIN"

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

    # ==================== Shopify Settings ====================

    def get_shopify_settings(self) -> dict:
        """Fetch current Shopify settings from the server."""
        return self._get("/admin/shopify-settings")

    def save_shopify_settings(self, store_url: str, client_id: str,
                              client_secret: str, api_version: str,
                              shippo_test_key: str = None,
                              shippo_live_key: str = None,
                              shippo_use_live: bool = None,
                              ship_from: dict = None,
                              only_ship_from: bool = False) -> dict:
        """Save API credentials on the server.

        Secret fields (``client_secret``, ``shippo_test_key``,
        ``shippo_live_key``) are only included in the PUT body when
        non-empty — an empty string means "don't touch the existing stored
        value". This prevents the masked display value from being
        round-tripped back into storage. ``shippo_use_live`` is included
        whenever it is provided (it's a non-secret boolean).

        If only_ship_from is True, omits the Shopify fields entirely so they
        are not overwritten — useful for saving just the ship-from address.
        """
        data = {"api_version": api_version}
        if not only_ship_from:
            data["store_url"] = store_url
            data["client_id"] = client_id
            if client_secret:
                data["client_secret"] = client_secret
        if shippo_test_key:
            data["shippo_test_key"] = shippo_test_key
        if shippo_live_key:
            data["shippo_live_key"] = shippo_live_key
        if shippo_use_live is not None:
            data["shippo_use_live"] = shippo_use_live
        if ship_from is not None:
            for field in ("name", "street1", "street2", "city",
                          "state", "zip", "country", "phone", "email"):
                data[f"ship_from_{field}"] = ship_from.get(field, "")
        return self._put("/admin/shopify-settings", data)

    def clear_shopify_settings(self) -> None:
        """Clear all Shopify credentials on the server."""
        self._delete("/admin/shopify-settings")

    def test_shopify_connection(self, store_url: str, client_id: str,
                                client_secret: str, api_version: str) -> dict:
        """Test Shopify connection with given credentials (server-side)."""
        return self._post("/admin/shopify-settings/test", {
            "store_url": store_url,
            "client_id": client_id,
            "client_secret": client_secret,
            "api_version": api_version,
        })

    # ==================== Sync ====================

    def trigger_sync(self) -> dict:
        """Trigger an immediate Shopify order sync on the server."""
        return self._post("/admin/sync/trigger", {})

    def get_sync_settings(self) -> dict:
        """Get current sync settings (auto_sync, interval, last_sync)."""
        return self._get("/admin/sync/settings")

    def save_sync_settings(self, auto_sync: bool, sync_interval_minutes: int) -> dict:
        """Save sync settings on the server."""
        return self._put("/admin/sync/settings", {
            "auto_sync": auto_sync,
            "sync_interval_minutes": sync_interval_minutes,
        })

    # ==================== Orders ====================

    def get_orders(self, filter: str = "all", offset: int = 0, limit: int = 200) -> dict:
        """Fetch paginated orders from the server."""
        return self._get("/admin/orders", params={
            "filter": filter,
            "offset": offset,
            "limit": limit,
        })

    def get_order_count(self, filter: str = "all") -> int:
        """Get total order count for the given filter."""
        result = self._get("/admin/orders/count", params={"filter": filter})
        return result.get("count", 0)

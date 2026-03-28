"""
API client for the Unfnventory application.
"""

from __future__ import annotations

import requests
from pathlib import Path
from typing import Optional
from datetime import datetime
from dataclasses import dataclass

from shared.api_client_base import APIClientBase
from .config import load_config, get_suggested_device_name


@dataclass
class ComponentInventory:
    """Component with current stock level."""
    id: int
    component_name: str
    dxf_filename: str
    stock: int = 0
    last_updated: Optional[datetime] = None


class APIClient(APIClientBase):
    """API client for component inventory management."""

    ENV_PREFIX = "UNFNVENTORY"

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

    # ==================== Component Inventory ====================

    def get_component_inventory(self) -> list[ComponentInventory]:
        """Fetch component inventory from server."""
        components = self._get("/components")
        comp_map = {c["id"]: c for c in components}

        inv_map = {}
        try:
            inventory = self._get("/inventory/components")
            for inv in inventory:
                inv_map[inv["component_id"]] = inv
        except Exception:
            pass

        result = []
        for comp_id, comp in comp_map.items():
            inv = inv_map.get(comp_id, {})

            last_updated = None
            if inv.get("last_updated"):
                try:
                    last_updated = datetime.fromisoformat(
                        inv["last_updated"].replace("Z", "+00:00")
                    )
                except (ValueError, TypeError):
                    pass

            result.append(ComponentInventory(
                id=comp_id,
                component_name=comp["name"],
                dxf_filename=comp["dxf_filename"],
                stock=inv.get("quantity_on_hand", 0),
                last_updated=last_updated,
            ))

        return result

    def adjust_component_inventory(self, component_id, quantity, reason, notes=None):
        """Adjust component inventory on the server."""
        data = {"quantity": quantity, "reason": reason}
        if notes:
            data["notes"] = notes
        return self._post(f"/inventory/components/{component_id}/adjust", data)

    # ==================== Product Inventory ====================

    def get_product_inventory(self) -> list[dict]:
        """Fetch finished product inventory from server."""
        return self._get("/inventory/products")

    def adjust_product_inventory(self, sku, quantity, reason, notes=None):
        """Adjust finished product inventory on the server."""
        data = {"quantity": quantity, "reason": reason}
        if notes:
            data["notes"] = notes
        return self._post(f"/inventory/products/{sku}/adjust", data)

    def get_product_replenishment_status(self) -> list[dict]:
        """Get product-level replenishment status."""
        return self._get("/replenishment/product-status")

    # ==================== Replenishment ====================

    def get_replenishment_status(self) -> list[dict]:
        """Get live stock positions for all components."""
        return self._get("/replenishment/status")

    def recalculate_replenishment(self) -> dict:
        """Trigger full replenishment recalculation on the server."""
        return self._post("/replenishment/recalculate", {})

    def get_replenishment_config(self) -> dict:
        """Get the current replenishment configuration."""
        return self._get("/replenishment/config")

    def update_replenishment_config(self, updates: dict) -> dict:
        """Update replenishment configuration (partial update)."""
        return self._put("/replenishment/config", updates)

    # ==================== DXF File Download ====================

    def download_component_dxf(self, filename: str, dest_path: Path) -> bool:
        """Download a component DXF file from the server."""
        try:
            response = requests.get(
                f"{self.base_url}/files/component-dxf/{filename}",
                headers=self._upload_headers,
                timeout=30,
                stream=True,
            )
            response.raise_for_status()

            dest_path.parent.mkdir(parents=True, exist_ok=True)

            with open(dest_path, "wb") as f:
                for chunk in response.iter_content(chunk_size=8192):
                    f.write(chunk)

            return True
        except requests.RequestException:
            return False

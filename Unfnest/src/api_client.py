"""
API client for the Nesting API server.

Drop-in replacement for the Database class - same method signatures,
but calls the API instead of local SQLite.

Configuration is read from:
1. Config file (~/.config/Unfnest/config.ini or equivalent)
2. Environment variables (override config file)
3. Constructor arguments (override everything)
"""

from __future__ import annotations

import os
import requests
from pathlib import Path
from typing import Optional

from .database import (
    ComponentDefinition, ComponentMatingPair, ProductComponent, Product,
)
from .config import load_config, get_suggested_device_name
from shared.api_client_base import APIClientBase


class APIClient(APIClientBase):
    """API client that mirrors the Database class interface."""

    ENV_PREFIX = "UNFNEST"

    def __init__(
        self,
        api_url: str = None,
        api_key: str = None,
        device_name: str = None,
        timeout: float = 5.0
    ):
        config = load_config()
        suggested = get_suggested_device_name()
        super().__init__(
            api_url=api_url,
            api_key=api_key,
            device_name=device_name,
            timeout=timeout,
            config_api_url=config.api_url,
            config_api_key=config.api_key,
            config_device_name=config.device_name,
            config_lan_server_ip=config.lan_server_ip,
            suggested_device_name=suggested,
        )

    # ==================== Component Definition Methods ====================

    def get_all_component_definitions(self) -> list[ComponentDefinition]:
        """Get all component definitions."""
        data = self._get("/components")
        return [
            ComponentDefinition(
                id=c["id"], name=c["name"], dxf_filename=c["dxf_filename"],
                variable_pockets=c.get("variable_pockets", False),
                mating_role=c.get("mating_role", "neutral"),
            )
            for c in data
        ]

    def get_component_definition(self, component_id: int) -> Optional[ComponentDefinition]:
        """Get a component definition by ID."""
        try:
            c = self._get(f"/components/{component_id}")
            return ComponentDefinition(
                id=c["id"], name=c["name"], dxf_filename=c["dxf_filename"],
                variable_pockets=c.get("variable_pockets", False),
                mating_role=c.get("mating_role", "neutral"),
            )
        except requests.HTTPError as e:
            if e.response.status_code == 404:
                return None
            raise

    def get_component_definition_by_name(self, name: str) -> Optional[ComponentDefinition]:
        """Get a component definition by name."""
        components = self.get_all_component_definitions()
        for c in components:
            if c.name == name:
                return c
        return None

    def get_all_mating_pairs(self) -> list[ComponentMatingPair]:
        """Get all component mating pairs from the server."""
        try:
            data = self._get("/mating-pairs")
            return [
                ComponentMatingPair(
                    pocket_component_id=mp["pocket_component_id"],
                    mating_component_id=mp["mating_component_id"],
                    pocket_index=mp.get("pocket_index", 0),
                    clearance_inches=mp.get("clearance_inches", 0.0079),
                )
                for mp in data
            ]
        except Exception:
            return []

    def add_component_definition(self, name: str, dxf_filename: str, variable_pockets: bool = False) -> int:
        """Add a new component definition. Returns the component ID."""
        data = self._post("/components", {
            "name": name, "dxf_filename": dxf_filename,
            "variable_pockets": variable_pockets,
        })
        return data["id"]

    def update_component_definition(self, component_id: int, name: str, dxf_filename: str, variable_pockets: bool = False, mating_role: str = "neutral") -> None:
        """Update a component definition."""
        self._put(f"/components/{component_id}", {
            "name": name, "dxf_filename": dxf_filename,
            "variable_pockets": variable_pockets,
            "mating_role": mating_role,
        })

    def delete_component_definition(self, component_id: int) -> bool:
        """Delete a component definition. Returns False if component is used in products."""
        try:
            self._delete(f"/components/{component_id}")
            return True
        except requests.HTTPError as e:
            if e.response.status_code == 400:
                return False  # Component in use
            raise

    # ==================== Product Methods ====================

    def get_all_products(self) -> list[Product]:
        """Get all products with their components."""
        data = self._get("/products")
        return [self._parse_product(p) for p in data]

    def get_product(self, sku: str) -> Optional[Product]:
        """Get a product by SKU with all its components."""
        try:
            p = self._get(f"/products/{sku}")
            return self._parse_product(p)
        except requests.HTTPError as e:
            if e.response.status_code == 404:
                return None
            raise

    def _parse_product(self, p: dict) -> Product:
        """Parse a product dict into a Product object."""
        components = [
            ProductComponent(
                id=c["id"],
                product_sku=c["product_sku"],
                component_id=c["component_id"],
                component_name=c["component_name"],
                dxf_filename=c["dxf_filename"],
                quantity=c["quantity"]
            )
            for c in p.get("components", [])
        ]
        return Product(
            sku=p["sku"],
            name=p["name"],
            description=p.get("description", ""),
            components=components,
            outsourced=p.get("outsourced", False)
        )

    def add_product(self, sku: str, name: str, description: str = "", outsourced: bool = False) -> None:
        """Add or update a product."""
        # Check if product exists first
        existing = self.get_product(sku)
        if existing:
            # Update existing product
            self._put(f"/products/{sku}", {
                "name": name,
                "description": description,
                "outsourced": outsourced
            })
        else:
            # Create new product
            self._post("/products", {
                "sku": sku,
                "name": name,
                "description": description,
                "outsourced": outsourced,
                "components": []
            })

    def add_product_component(self, product_sku: str, component_id: int, quantity: int = 1) -> int:
        """Add a component to a product."""
        # Get current product, add component, update
        product = self.get_product(product_sku)
        if not product:
            raise ValueError(f"Product {product_sku} not found")

        components = [
            {"component_id": c.component_id, "quantity": c.quantity}
            for c in product.components
        ]
        components.append({"component_id": component_id, "quantity": quantity})

        self._put(f"/products/{product_sku}", {"components": components})
        return 0  # API doesn't return the relationship ID

    def clear_product_components(self, sku: str) -> None:
        """Remove all components from a product."""
        self._put(f"/products/{sku}", {"components": []})

    def delete_product(self, sku: str) -> None:
        """Delete a product and its component relationships."""
        self._delete(f"/products/{sku}")

    # ==================== File Methods ====================

    def upload_component_dxf(self, file_path: Path) -> dict:
        """
        Upload a DXF file to the server.

        Args:
            file_path: Path to the local DXF file

        Returns:
            dict with filename, size, checksum, message

        Raises:
            requests.HTTPError: If upload fails
            FileNotFoundError: If local file doesn't exist
        """
        if not file_path.exists():
            raise FileNotFoundError(f"File not found: {file_path}")

        with open(file_path, "rb") as f:
            files = {"file": (file_path.name, f, "application/dxf")}
            response = requests.post(
                f"{self.base_url}/files/component-dxf",
                headers=self._upload_headers,
                files=files,
                timeout=30,
            )

        response.raise_for_status()
        return response.json()

    def download_component_dxf(self, filename: str, dest_path: Path) -> bool:
        """
        Download a DXF file from the server.

        Args:
            filename: Name of the file on the server
            dest_path: Local path to save the file

        Returns:
            True if download succeeded, False otherwise
        """
        try:
            response = requests.get(
                f"{self.base_url}/files/component-dxf/{filename}",
                headers=self._upload_headers,
                timeout=30,
                stream=True
            )
            response.raise_for_status()

            # Ensure destination directory exists
            dest_path.parent.mkdir(parents=True, exist_ok=True)

            with open(dest_path, "wb") as f:
                for chunk in response.iter_content(chunk_size=8192):
                    f.write(chunk)

            return True
        except requests.RequestException:
            return False

    def list_server_dxf_files(self) -> list[dict]:
        """
        List all DXF files available on the server.

        Returns:
            List of dicts with filename, size, checksum for each file
        """
        try:
            return self._get("/files/component-dxf")
        except requests.RequestException:
            return []

    def upload_nesting_dxf(self, file_path: Path) -> dict:
        """Upload a nesting layout DXF file to the server."""
        if not file_path.exists():
            raise FileNotFoundError(f"File not found: {file_path}")

        with open(file_path, "rb") as f:
            files = {"file": (file_path.name, f, "application/dxf")}
            response = requests.post(
                f"{self.base_url}/files/nesting-dxf",
                headers=self._upload_headers,
                files=files,
                timeout=30
            )

        response.raise_for_status()
        return response.json()

    def upload_gcode(self, file_path: Path) -> dict:
        """Upload a G-code file to the server."""
        if not file_path.exists():
            raise FileNotFoundError(f"File not found: {file_path}")

        with open(file_path, "rb") as f:
            files = {"file": (file_path.name, f, "text/plain")}
            response = requests.post(
                f"{self.base_url}/files/gcode",
                headers=self._upload_headers,
                files=files,
                timeout=30
            )

        response.raise_for_status()
        return response.json()

    def get_inventory_map(self) -> dict[int, int]:
        """Return {component_id: quantity_on_hand} for all components."""
        try:
            data = self._get("/inventory/components")
            return {item["component_id"]: item["quantity_on_hand"] for item in data}
        except Exception:
            return {}

    # ==================== Nesting Jobs Methods ====================

    def create_nesting_job(self, name: str, sheets: list[dict], prototype: bool = False) -> dict:
        """
        Create a nesting job with sheets and parts for inventory tracking.

        Args:
            name: Job name (e.g., "Nest 2026-02-03 14:30")
            sheets: List of sheet dicts with keys:
                - sheet_number: int
                - gcode_filename: str (optional)
                - dxf_filename: str (optional)
                - parts: list of dicts with component_id and quantity
            prototype: If True, job goes to prototype queue (no inventory tracking)

        Returns:
            The created job data

        Example:
            sheets = [
                {
                    "sheet_number": 1,
                    "gcode_filename": "sheet_001.nc",
                    "parts": [
                        {"component_id": 1, "quantity": 4},
                        {"component_id": 2, "quantity": 2}
                    ]
                }
            ]
            job = api.create_nesting_job("Nest 2026-02-03", sheets)
        """
        payload = {
            "name": name,
            "sheets": sheets,
            "prototype": prototype
        }
        return self._post("/nesting-jobs", payload)

    def get_nesting_jobs(self, status: str = None, limit: int = 50) -> list[dict]:
        """Get nesting jobs, optionally filtered by status."""
        endpoint = "/nesting-jobs"
        params = []
        if status:
            params.append(f"status={status}")
        if limit != 50:
            params.append(f"limit={limit}")
        if params:
            endpoint += "?" + "&".join(params)
        return self._get(endpoint)

    def get_nesting_job(self, job_id: int) -> Optional[dict]:
        """Get a nesting job by ID."""
        try:
            return self._get(f"/nesting-jobs/{job_id}")
        except requests.HTTPError as e:
            if e.response.status_code == 404:
                return None
            raise

    def mark_sheet_cut(self, job_id: int, sheet_id: int) -> dict:
        """
        Mark a sheet as cut and update component inventory.

        This increments inventory for all parts on the sheet.
        """
        return self._post(f"/nesting-jobs/{job_id}/sheets/{sheet_id}/mark-cut", {})

    def mark_sheet_failed(self, job_id: int, sheet_id: int) -> dict:
        """Mark a sheet as failed (no inventory update)."""
        return self._post(f"/nesting-jobs/{job_id}/sheets/{sheet_id}/mark-failed", {})

    # ==================== Replenishment Methods ====================

    def get_replenishment_config(self) -> dict:
        """Get replenishment configuration."""
        return self._get("/replenishment/config")

    def update_replenishment_config(self, updates: dict) -> dict:
        """Update replenishment configuration."""
        return self._put("/replenishment/config", updates)

    def get_replenishment_status(self) -> list[dict]:
        """Get live stock positions for all components."""
        return self._get("/replenishment/status")

    def get_product_replenishment_status(self) -> list[dict]:
        """Get live stock positions for all non-outsourced products."""
        return self._get("/replenishment/product-status")

    def get_replenishment_queue(self) -> dict:
        """Get latest replenishment snapshot with mandatory and fill candidates."""
        return self._get("/replenishment/queue")

    def recalculate_replenishment(self) -> dict:
        """Run full forecast update + replenishment calculation."""
        response = requests.post(
            f"{self.base_url}/replenishment/recalculate",
            headers=self.headers,
            json={},
            timeout=30,
        )
        response.raise_for_status()
        return response.json()

    # ==================== Bundle Methods ====================

    def create_bundle(self, sheet_ids: list[int]) -> dict:
        """Create a sheet bundle from 2-4 sheet IDs."""
        return self._post("/bundles", {"sheet_ids": sheet_ids})

    def get_bundles(self) -> list[dict]:
        """List all bundles."""
        return self._get("/bundles")

    def get_bundle(self, bundle_id: int) -> Optional[dict]:
        """Get a bundle by ID."""
        try:
            return self._get(f"/bundles/{bundle_id}")
        except requests.HTTPError as e:
            if e.response.status_code == 404:
                return None
            raise

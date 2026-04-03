"""
API client for the UnfnCNC application.

Handles claiming sheets, marking cuts, and downloading files
from the Unfnshed Server.
"""

from __future__ import annotations

import requests
from pathlib import Path
from typing import Optional

from shared.api_client_base import APIClientBase
from .config import load_config, get_suggested_device_name


class APIClient(APIClientBase):
    """API client for CNC machine operations."""

    ENV_PREFIX = "UNFNCNC"

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

    # ==================== CNC Operations ====================

    def claim_next_sheet(self, machine_id: str, prototype: bool = False) -> Optional[dict]:
        """
        Claim the next pending sheet for this machine.

        Args:
            machine_id: CNC machine identifier
            prototype: If True, claim from prototype queue instead of production

        Returns the full NestingJob dict with sheets/parts/order_ids,
        or None if no pending sheets (404).
        """
        try:
            return self._post("/nesting-jobs/claim-next-sheet", {
                "machine_id": machine_id,
                "prototype": prototype,
            })
        except requests.HTTPError as e:
            if e.response.status_code == 404:
                return None
            raise

    def mark_sheet_cut(self, job_id: int, sheet_id: int, damaged_parts: list[dict] = None) -> dict:
        """
        Mark a sheet as cut, optionally reporting damaged parts.

        damaged_parts: list of {"component_id": int, "quantity": int}
        """
        data = {"damaged_parts": damaged_parts or []}
        return self._post(
            f"/nesting-jobs/{job_id}/sheets/{sheet_id}/mark-cut-with-damages",
            data
        )

    def release_sheet(self, job_id: int, sheet_id: int) -> dict:
        """Release a claimed sheet back to pending."""
        return self._post(f"/nesting-jobs/{job_id}/sheets/{sheet_id}/release")

    def get_queue(self) -> dict:
        """Get queue summary (pending/cutting/completed counts)."""
        return self._get("/nesting-jobs/queue")

    def get_claimed_sheets(self, machine_id: str) -> list[dict]:
        """Get sheets currently claimed by this machine (for crash recovery).

        Returns list of {"job_id": int, "sheet_id": int, "sheet_number": int, "job_name": str}
        """
        try:
            return self._get(f"/nesting-jobs/claimed-sheets?machine_id={machine_id}")
        except Exception:
            return []

    # ==================== File Downloads ====================

    def upload_gcode(self, file_path: Path) -> dict:
        """Upload G-code to server for archival. POST /files/gcode (multipart)."""
        with open(file_path, "rb") as f:
            response = requests.post(
                f"{self.base_url}/files/gcode",
                headers=self._upload_headers,
                files={"file": (file_path.name, f)},
                timeout=30,
            )
        response.raise_for_status()
        return response.json()

    def delete_gcode(self, filename: str) -> bool:
        """Delete G-code from server. DELETE /files/gcode/{filename}."""
        try:
            response = requests.delete(
                f"{self.base_url}/files/gcode/{filename}",
                headers=self._upload_headers,
                timeout=self.timeout,
            )
            response.raise_for_status()
            return True
        except requests.RequestException:
            return False

    def update_sheet_gcode_filename(self, job_id: int, sheet_id: int, gcode_filename: str) -> dict:
        """Set gcode_filename on sheet after local generation."""
        response = requests.patch(
            f"{self.base_url}/nesting-jobs/{job_id}/sheets/{sheet_id}/gcode-filename",
            headers=self.headers,
            json={"gcode_filename": gcode_filename},
            timeout=self.timeout,
        )
        response.raise_for_status()
        return response.json()

    # ==================== Sheet Thickness ====================

    def set_sheet_thickness(self, sheet_id: int, thickness: float) -> dict:
        """Set the actual thickness on a nesting sheet."""
        return self._post(f"/sheets/{sheet_id}/set-thickness", {
            "actual_thickness_inches": thickness,
        })

    def get_pocket_targets(self, sheet_id: int) -> list:
        """Get pocket target thicknesses for a sheet's variable pockets."""
        try:
            return self._get(f"/sheets/{sheet_id}/pocket-targets")
        except requests.HTTPError as e:
            if e.response.status_code == 404:
                return []
            raise

    # ==================== Bundle Operations ====================

    def get_bundle(self, bundle_id: int) -> Optional[dict]:
        """Get a bundle with sheet details."""
        try:
            return self._get(f"/bundles/{bundle_id}")
        except requests.HTTPError as e:
            if e.response.status_code == 404:
                return None
            raise

    # ==================== File Downloads ====================

    def download_nesting_dxf(self, filename: str, dest_path: Path) -> bool:
        """Download a nesting DXF file from the server."""
        try:
            response = requests.get(
                f"{self.base_url}/files/nesting-dxf/{filename}",
                headers=self._upload_headers,
                timeout=30,
                stream=True
            )
            response.raise_for_status()

            dest_path.parent.mkdir(parents=True, exist_ok=True)

            with open(dest_path, "wb") as f:
                for chunk in response.iter_content(chunk_size=8192):
                    f.write(chunk)

            return True
        except requests.RequestException:
            return False

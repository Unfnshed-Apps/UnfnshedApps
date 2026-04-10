"""
Base API client for Unfnshed applications.

Provides connection auto-detection (configured -> local -> LAN -> remote),
HTTP method helpers, and common headers. Each app subclasses this and adds
its own domain-specific endpoints.
"""

from __future__ import annotations

import os
import requests
from typing import Optional


class APIClientBase:
    """Base API client with connection auto-detection and HTTP helpers."""

    REMOTE_URL = "https://api.gradschoolalternative.com"
    LOCAL_URL = "http://127.0.0.1:8000"

    # Subclasses set these to their app-specific env var prefix
    ENV_PREFIX = "UNFNSHED"  # -> UNFNSHED_API_URL, UNFNSHED_API_KEY, etc.

    def __init__(
        self,
        api_url: str = None,
        api_key: str = None,
        device_name: str = None,
        timeout: float = 10.0,
        *,
        config_api_url: str = "",
        config_api_key: str = "",
        config_device_name: str = "",
        config_lan_server_ip: str = "",
        suggested_device_name: str = "",
    ):
        prefix = self.ENV_PREFIX

        self.api_url = (
            api_url or
            os.environ.get(f"{prefix}_API_URL") or
            config_api_url or
            ""
        )
        self.api_key = (
            api_key or
            os.environ.get(f"{prefix}_API_KEY") or
            config_api_key or
            "dev"
        )
        self.device_name = (
            device_name or
            os.environ.get(f"{prefix}_DEVICE_NAME") or
            config_device_name or
            suggested_device_name
        )
        self.lan_server_ip = config_lan_server_ip or ""
        self.timeout = timeout
        self._base_url = None
        self._connection_type = None

    @property
    def base_url(self) -> str:
        """Get the active base URL, auto-detecting if needed."""
        if self._base_url:
            return self._base_url

        if self.api_url:
            try:
                response = requests.get(f"{self.api_url}/health", timeout=2)
                if response.status_code == 200:
                    self._base_url = self.api_url
                    self._connection_type = "configured"
                    return self._base_url
            except requests.RequestException:
                pass

        try:
            response = requests.get(f"{self.LOCAL_URL}/health", timeout=2)
            if response.status_code == 200:
                self._base_url = self.LOCAL_URL
                self._connection_type = "local"
                return self._base_url
        except requests.RequestException:
            pass

        if self.lan_server_ip:
            lan_url = f"http://{self.lan_server_ip}:8000"
            try:
                response = requests.get(f"{lan_url}/health", timeout=2)
                if response.status_code == 200:
                    self._base_url = lan_url
                    self._connection_type = "lan"
                    return self._base_url
            except requests.RequestException:
                pass

        self._base_url = self.REMOTE_URL
        self._connection_type = "remote"
        return self._base_url

    def set_server(self, url: str, connection_type: str) -> None:
        """Update the active server URL and connection type."""
        self._base_url = url
        self._connection_type = connection_type

    @property
    def connection_info(self) -> dict:
        """Get info about the current connection."""
        return {
            "url": self.base_url,
            "type": self._connection_type,
            "device": self.device_name,
        }

    @property
    def headers(self) -> dict:
        """Request headers including API key and device identifier."""
        h = {
            "Content-Type": "application/json",
            "X-Device-Name": self.device_name,
        }
        if self.api_key:
            h["X-API-Key"] = self.api_key
        return h

    @property
    def _upload_headers(self) -> dict:
        """Headers for file uploads (no Content-Type -- let requests set it)."""
        h = {"X-Device-Name": self.device_name}
        if self.api_key:
            h["X-API-Key"] = self.api_key
        return h

    def _get(self, endpoint: str, params: dict = None) -> dict | list | None:
        """Make a GET request."""
        response = requests.get(
            f"{self.base_url}{endpoint}",
            headers=self.headers,
            params=params,
            timeout=self.timeout,
        )
        response.raise_for_status()
        return response.json()

    def _post(self, endpoint: str, data: dict = None) -> dict | None:
        """Make a POST request."""
        response = requests.post(
            f"{self.base_url}{endpoint}",
            headers=self.headers,
            json=data or {},
            timeout=self.timeout,
        )
        response.raise_for_status()
        return response.json()

    def _put(self, endpoint: str, data: dict) -> dict:
        """Make a PUT request."""
        response = requests.put(
            f"{self.base_url}{endpoint}",
            headers=self.headers,
            json=data,
            timeout=self.timeout,
        )
        response.raise_for_status()
        return response.json()

    def _patch(self, endpoint: str, data: dict) -> dict:
        """Make a PATCH request."""
        response = requests.patch(
            f"{self.base_url}{endpoint}",
            headers=self.headers,
            json=data,
            timeout=self.timeout,
        )
        response.raise_for_status()
        return response.json()

    def _delete(self, endpoint: str) -> None:
        """Make a DELETE request."""
        response = requests.delete(
            f"{self.base_url}{endpoint}",
            headers=self.headers,
            timeout=self.timeout,
        )
        response.raise_for_status()

    def close(self):
        """Close connection (no-op for API client)."""
        pass

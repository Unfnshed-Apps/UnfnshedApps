"""Tests for shared.api_client_base module."""

import pytest

from shared.api_client_base import APIClientBase


# ---------------------------------------------------------------------------
# Helper subclass with a custom prefix
# ---------------------------------------------------------------------------

class CNCClient(APIClientBase):
    ENV_PREFIX = "UNFNCNC"


# ---------------------------------------------------------------------------
# Default construction
# ---------------------------------------------------------------------------

class TestDefaults:
    def test_default_env_prefix(self):
        client = APIClientBase()
        assert client.ENV_PREFIX == "UNFNSHED"

    def test_default_timeout(self):
        client = APIClientBase()
        assert client.timeout == 10.0

    def test_default_api_key_is_dev(self):
        client = APIClientBase()
        assert client.api_key == "dev"

    def test_default_api_url_is_empty(self):
        client = APIClientBase()
        assert client.api_url == ""


# ---------------------------------------------------------------------------
# Constructor priority: explicit > env var > config
# ---------------------------------------------------------------------------

class TestConstructorPriority:
    def test_explicit_beats_env(self, monkeypatch):
        monkeypatch.setenv("UNFNSHED_API_URL", "http://from-env")
        client = APIClientBase(api_url="http://explicit")
        assert client.api_url == "http://explicit"

    def test_env_beats_config(self, monkeypatch):
        monkeypatch.setenv("UNFNSHED_API_URL", "http://from-env")
        client = APIClientBase(config_api_url="http://from-config")
        assert client.api_url == "http://from-env"

    def test_config_used_when_no_explicit_or_env(self, monkeypatch):
        monkeypatch.delenv("UNFNSHED_API_URL", raising=False)
        client = APIClientBase(config_api_url="http://from-config")
        assert client.api_url == "http://from-config"

    def test_api_key_priority(self, monkeypatch):
        monkeypatch.setenv("UNFNSHED_API_KEY", "env-key")
        client = APIClientBase(api_key="explicit-key")
        assert client.api_key == "explicit-key"

    def test_api_key_env_beats_config(self, monkeypatch):
        monkeypatch.setenv("UNFNSHED_API_KEY", "env-key")
        client = APIClientBase(config_api_key="config-key")
        assert client.api_key == "env-key"

    def test_device_name_priority(self, monkeypatch):
        monkeypatch.setenv("UNFNSHED_DEVICE_NAME", "env-device")
        client = APIClientBase(
            device_name="explicit-device",
            config_device_name="config-device",
        )
        assert client.device_name == "explicit-device"

    def test_device_name_falls_back_to_suggested(self, monkeypatch):
        monkeypatch.delenv("UNFNSHED_DEVICE_NAME", raising=False)
        client = APIClientBase(suggested_device_name="suggested")
        assert client.device_name == "suggested"


# ---------------------------------------------------------------------------
# headers property
# ---------------------------------------------------------------------------

class TestHeaders:
    def test_contains_content_type(self):
        client = APIClientBase(device_name="dev1")
        assert client.headers["Content-Type"] == "application/json"

    def test_contains_device_name(self):
        client = APIClientBase(device_name="dev1")
        assert client.headers["X-Device-Name"] == "dev1"

    def test_contains_api_key(self):
        client = APIClientBase(api_key="mykey", device_name="dev1")
        assert client.headers["X-API-Key"] == "mykey"

    def test_api_key_fallback_to_dev_when_empty(self):
        # Empty string is falsy, so the or-chain falls through to "dev"
        client = APIClientBase(api_key="", device_name="dev1")
        assert client.headers["X-API-Key"] == "dev"


# ---------------------------------------------------------------------------
# _upload_headers property
# ---------------------------------------------------------------------------

class TestUploadHeaders:
    def test_has_device_name(self):
        client = APIClientBase(device_name="dev1")
        assert client._upload_headers["X-Device-Name"] == "dev1"

    def test_no_content_type(self):
        client = APIClientBase(device_name="dev1")
        assert "Content-Type" not in client._upload_headers

    def test_has_api_key(self):
        client = APIClientBase(api_key="mykey", device_name="dev1")
        assert client._upload_headers["X-API-Key"] == "mykey"


# ---------------------------------------------------------------------------
# set_server
# ---------------------------------------------------------------------------

class TestSetServer:
    def test_updates_base_url(self):
        client = APIClientBase()
        client.set_server("http://custom:9000", "manual")
        assert client._base_url == "http://custom:9000"

    def test_updates_connection_type(self):
        client = APIClientBase()
        client.set_server("http://custom:9000", "manual")
        assert client._connection_type == "manual"


# ---------------------------------------------------------------------------
# connection_info
# ---------------------------------------------------------------------------

class TestConnectionInfo:
    def test_returns_dict_with_expected_keys(self):
        client = APIClientBase(device_name="dev1")
        client.set_server("http://test:8000", "local")
        info = client.connection_info
        assert info["url"] == "http://test:8000"
        assert info["type"] == "local"
        assert info["device"] == "dev1"


# ---------------------------------------------------------------------------
# Subclass with custom ENV_PREFIX
# ---------------------------------------------------------------------------

class TestCustomPrefix:
    def test_env_prefix_used(self):
        client = CNCClient()
        assert client.ENV_PREFIX == "UNFNCNC"

    def test_reads_prefixed_env_vars(self, monkeypatch):
        monkeypatch.setenv("UNFNCNC_API_URL", "http://cnc-env")
        monkeypatch.delenv("UNFNSHED_API_URL", raising=False)
        client = CNCClient()
        assert client.api_url == "http://cnc-env"

    def test_ignores_base_prefix_env_vars(self, monkeypatch):
        monkeypatch.setenv("UNFNSHED_API_URL", "http://base-env")
        monkeypatch.delenv("UNFNCNC_API_URL", raising=False)
        client = CNCClient()
        # Should NOT pick up the UNFNSHED_ prefixed var
        assert client.api_url == ""

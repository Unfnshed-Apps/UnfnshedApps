"""Tests for shared.config_base module."""

import dataclasses
from dataclasses import dataclass, fields
from pathlib import Path
from typing import ClassVar, Optional

import pytest

from shared.config_base import (
    AppConfigBase,
    get_config_dir,
    get_config_path,
    get_suggested_device_name,
    load_config,
    save_config,
)


# ---------------------------------------------------------------------------
# Test subclass used by several tests
# ---------------------------------------------------------------------------

@dataclass
class MyAppConfig(AppConfigBase):
    machine_type: str = ""
    serial_number: str = ""

    CONFIG_SECTIONS: ClassVar[Optional[dict]] = {
        "machine": [
            ("machine_type", "type"),
            ("serial_number", "serial"),
        ],
    }


# ---------------------------------------------------------------------------
# get_config_dir
# ---------------------------------------------------------------------------

class TestGetConfigDir:
    def test_returns_path_object(self, tmp_path, monkeypatch):
        # Redirect the home-based path to tmp_path
        monkeypatch.setattr(Path, "home", lambda: tmp_path)
        result = get_config_dir("TestApp")
        assert isinstance(result, Path)

    def test_creates_directory(self, tmp_path, monkeypatch):
        monkeypatch.setattr(Path, "home", lambda: tmp_path)
        result = get_config_dir("TestApp")
        assert result.is_dir()

    def test_contains_app_name(self, tmp_path, monkeypatch):
        monkeypatch.setattr(Path, "home", lambda: tmp_path)
        result = get_config_dir("TestApp")
        assert result.name == "TestApp"


# ---------------------------------------------------------------------------
# get_config_path
# ---------------------------------------------------------------------------

class TestGetConfigPath:
    def test_returns_config_ini(self, tmp_path, monkeypatch):
        monkeypatch.setattr(Path, "home", lambda: tmp_path)
        result = get_config_path("TestApp")
        assert result.name == "config.ini"
        assert result.parent.name == "TestApp"


# ---------------------------------------------------------------------------
# get_suggested_device_name
# ---------------------------------------------------------------------------

class TestGetSuggestedDeviceName:
    def test_returns_non_empty_string(self):
        name = get_suggested_device_name()
        assert isinstance(name, str)
        assert len(name) > 0

    def test_no_dots(self):
        # Should return hostname up to the first dot
        name = get_suggested_device_name()
        assert "." not in name


# ---------------------------------------------------------------------------
# AppConfigBase defaults and is_configured
# ---------------------------------------------------------------------------

class TestAppConfigBase:
    def test_default_values_are_empty_strings(self):
        cfg = AppConfigBase()
        assert cfg.api_url == ""
        assert cfg.api_key == ""
        assert cfg.device_name == ""
        assert cfg.lan_server_ip == ""

    def test_is_configured_false_when_device_name_empty(self):
        cfg = AppConfigBase()
        assert cfg.is_configured is False

    def test_is_configured_true_when_device_name_set(self):
        cfg = AppConfigBase(device_name="my-machine")
        assert cfg.is_configured is True


# ---------------------------------------------------------------------------
# Subclassing with CONFIG_SECTIONS
# ---------------------------------------------------------------------------

class TestSubclassing:
    def test_config_sections_is_classvar(self):
        # CONFIG_SECTIONS should NOT appear in dataclass fields
        field_names = {f.name for f in fields(MyAppConfig)}
        assert "CONFIG_SECTIONS" not in field_names

    def test_config_sections_not_a_constructor_arg(self):
        # Regression: if CONFIG_SECTIONS leaks into the dataclass fields,
        # constructing with unexpected kwargs or round-tripping breaks.
        # This must work without passing CONFIG_SECTIONS:
        cfg = MyAppConfig(device_name="test", machine_type="cnc")
        assert cfg.device_name == "test"
        # And CONFIG_SECTIONS must be accessible as a class attribute:
        assert MyAppConfig.CONFIG_SECTIONS is not None
        assert "machine" in MyAppConfig.CONFIG_SECTIONS

    def test_extra_fields_present(self):
        cfg = MyAppConfig()
        assert hasattr(cfg, "machine_type")
        assert hasattr(cfg, "serial_number")
        assert cfg.machine_type == ""
        assert cfg.serial_number == ""

    def test_inherits_base_fields(self):
        cfg = MyAppConfig(device_name="dev1", machine_type="router")
        assert cfg.device_name == "dev1"
        assert cfg.machine_type == "router"
        assert cfg.is_configured is True


# ---------------------------------------------------------------------------
# load_config / save_config round-trip
# ---------------------------------------------------------------------------

class TestRoundTrip:
    @pytest.fixture(autouse=True)
    def _patch_config_dir(self, tmp_path, monkeypatch):
        """Redirect config directory to a temp folder."""
        monkeypatch.setattr(Path, "home", lambda: tmp_path)

    def test_save_and_load_base(self):
        original = AppConfigBase(
            api_url="http://localhost:8000",
            api_key="secret123",
            device_name="workstation",
            lan_server_ip="192.168.1.50",
        )
        save_config("TestApp", original)
        loaded = load_config("TestApp", AppConfigBase)

        assert loaded.api_url == original.api_url
        assert loaded.api_key == original.api_key
        assert loaded.device_name == original.device_name
        assert loaded.lan_server_ip == original.lan_server_ip

    def test_save_and_load_subclass(self):
        original = MyAppConfig(
            api_url="http://remote:8000",
            api_key="key456",
            device_name="cnc-1",
            lan_server_ip="10.0.0.5",
            machine_type="laser",
            serial_number="SN-9999",
        )
        save_config("TestApp", original)
        loaded = load_config("TestApp", MyAppConfig)

        assert loaded.api_url == original.api_url
        assert loaded.api_key == original.api_key
        assert loaded.device_name == original.device_name
        assert loaded.lan_server_ip == original.lan_server_ip
        assert loaded.machine_type == original.machine_type
        assert loaded.serial_number == original.serial_number

    def test_load_missing_file_returns_defaults(self):
        loaded = load_config("NoSuchApp", AppConfigBase)
        assert loaded.api_url == ""
        assert loaded.api_key == ""
        assert loaded.device_name == ""
        assert loaded.lan_server_ip == ""

    def test_load_missing_file_subclass_returns_defaults(self):
        loaded = load_config("NoSuchApp", MyAppConfig)
        assert loaded.machine_type == ""
        assert loaded.serial_number == ""

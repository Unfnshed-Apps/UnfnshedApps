"""
Configuration management for the Unfnship Application.
"""

from dataclasses import dataclass
from pathlib import Path

from shared.config_base import (
    AppConfigBase,
    get_config_path as _get_config_path_base,
    get_suggested_device_name,
    load_config as _load_config,
    save_config as _save_config,
)

APP_NAME = "Unfnship"


@dataclass
class AppConfig(AppConfigBase):
    """Unfnship application configuration."""
    pass


def load_config() -> AppConfig:
    return _load_config(APP_NAME, AppConfig)


def save_config(app_config: AppConfig) -> None:
    _save_config(APP_NAME, app_config)


def get_config_path() -> Path:
    return _get_config_path_base(APP_NAME)

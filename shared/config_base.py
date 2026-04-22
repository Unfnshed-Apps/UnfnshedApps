"""
Base configuration management for Unfnshed applications.

Each app subclasses AppConfigBase and calls the module-level functions
with its own APP_NAME to get per-app config directories.
"""

import os
import configparser
from pathlib import Path
from dataclasses import dataclass, fields
from typing import ClassVar, Optional
import socket


# One-time migrations for stored config URLs. Each entry is {old: new};
# when load_config sees the old value on disk, it substitutes the new
# value and writes the updated config back. Add entries here when a
# tunnel/domain moves so existing installs migrate without a Setup-dialog
# visit on every client machine.
_API_URL_MIGRATIONS = {
    "https://api.gradschoolalternative.com": "https://unfnshedapi.gradschoolalternative.com",
}


def get_config_dir(app_name: str) -> Path:
    """Get the configuration directory for the given app."""
    if os.name == 'nt':  # Windows
        base = Path(os.environ.get('APPDATA', Path.home()))
    else:  # macOS / Linux
        base = Path.home() / "Library" / "Application Support"

    config_dir = base / app_name
    config_dir.mkdir(parents=True, exist_ok=True)
    return config_dir


def get_config_path(app_name: str) -> Path:
    """Get the path to the config file for the given app."""
    return get_config_dir(app_name) / "config.ini"


def get_suggested_device_name() -> str:
    """Get a suggested device name based on the hostname."""
    try:
        return socket.gethostname().split('.')[0]
    except Exception:
        return ""


@dataclass
class AppConfigBase:
    """Base application configuration with common fields.

    Subclass this to add app-specific fields. Override CONFIG_SECTIONS
    to define how extra fields map to config.ini sections.

    CONFIG_SECTIONS is a dict mapping section names to lists of
    (field_name, ini_key) tuples.
    """
    api_url: str = ""
    api_key: str = ""
    device_name: str = ""
    lan_server_ip: str = ""

    # Subclasses override this to define extra config.ini mappings.
    # ClassVar so it's not treated as a dataclass field.
    CONFIG_SECTIONS: ClassVar[Optional[dict]] = None

    @property
    def is_configured(self) -> bool:
        """Check if the essential settings are configured."""
        return bool(self.device_name)


def load_config(app_name: str, config_cls: type[AppConfigBase]) -> AppConfigBase:
    """Load configuration from file into the given config class."""
    config_path = get_config_path(app_name)
    config = configparser.ConfigParser()

    if config_path.exists():
        config.read(config_path)

    # Start with base fields
    kwargs = {
        'api_url': config.get('api', 'url', fallback=''),
        'api_key': config.get('api', 'key', fallback=''),
        'device_name': config.get('device', 'name', fallback=''),
        'lan_server_ip': config.get('network', 'lan_server_ip', fallback=''),
    }

    # Load extra fields from CONFIG_SECTIONS
    if config_cls.CONFIG_SECTIONS:
        for section, field_mappings in config_cls.CONFIG_SECTIONS.items():
            for field_name, ini_key in field_mappings:
                kwargs[field_name] = config.get(section, ini_key, fallback='')

    # Apply URL migrations: rewrite deprecated hosts to the current default
    # and persist the change so subsequent loads see the new value.
    migrated_url = _API_URL_MIGRATIONS.get(kwargs.get("api_url", ""))
    needs_resave = migrated_url is not None
    if needs_resave:
        kwargs["api_url"] = migrated_url

    # Only pass kwargs that are actual fields on the dataclass
    valid_fields = {f.name for f in fields(config_cls)}
    kwargs = {k: v for k, v in kwargs.items() if k in valid_fields}

    cfg = config_cls(**kwargs)
    if needs_resave:
        try:
            save_config(app_name, cfg)
        except Exception:
            # A failed save shouldn't break app startup — we'll just try again
            # next launch and the in-memory value is still correct.
            pass
    return cfg


def save_config(app_name: str, app_config: AppConfigBase) -> None:
    """Save configuration to file."""
    config_path = get_config_path(app_name)
    config = configparser.ConfigParser()

    # Base sections
    config['api'] = {
        'url': app_config.api_url,
        'key': app_config.api_key,
    }
    config['device'] = {
        'name': app_config.device_name,
    }
    config['network'] = {
        'lan_server_ip': app_config.lan_server_ip,
    }

    # Extra sections from CONFIG_SECTIONS
    if app_config.CONFIG_SECTIONS:
        for section, field_mappings in app_config.CONFIG_SECTIONS.items():
            if section not in config:
                config[section] = {}
            for field_name, ini_key in field_mappings:
                config[section][ini_key] = str(getattr(app_config, field_name, ''))

    with open(config_path, 'w') as f:
        config.write(f)

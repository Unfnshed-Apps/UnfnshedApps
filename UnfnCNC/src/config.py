"""
Configuration management for the UnfnCNC Application.
"""

import json
import configparser
from dataclasses import dataclass
from pathlib import Path

from shared.config_base import (
    AppConfigBase,
    get_config_path as _get_config_path_base,
    get_suggested_device_name,
    load_config as _load_config,
    save_config as _save_config,
)

APP_NAME = "UnfnCNC"


@dataclass
class AppConfig(AppConfigBase):
    """UnfnCNC application configuration."""
    machine_letter: str = ""
    hot_folder_path: str = ""

    CONFIG_SECTIONS = {
        'machine': [
            ('machine_letter', 'letter'),
            ('hot_folder_path', 'hot_folder'),
        ],
    }

    @property
    def is_configured(self) -> bool:
        return bool(self.device_name and self.machine_letter and self.hot_folder_path)


def load_config() -> AppConfig:
    return _load_config(APP_NAME, AppConfig)


def save_config(app_config: AppConfig) -> None:
    _save_config(APP_NAME, app_config)


def get_config_path() -> Path:
    """Get the path to the config file (for display purposes)."""
    return _get_config_path_base(APP_NAME)


# ==================== G-code Settings ====================

# Zero reference constants
ZERO_FROM_SPOILBOARD = "spoilboard"
ZERO_FROM_TOP = "top"

# Pocket depth offset: 4mm in inches
POCKET_DEPTH_OFFSET = 0.1575

GCODE_DEFAULTS = {
    'spindle_rpm': 18000,
    'feed_xy_rough': 650,
    'feed_xy_finish': 350,
    'feed_z': 60,
    'cut_depth_adjustment': 0.0,
    'roughing_pct': 80,
    'zero_from': ZERO_FROM_SPOILBOARD,
    'pocket_clearance': 0.0079,
    'safe_z': 0.2004,
    'retract_z': 0.1969,
    'end_position_offset': 3.0,
    'end_z_height': 2.0,
    'ramp_angle': 5.0,
    'outline_tool': 5,
    'pocket_tool': 5,
}

DEFAULT_TOOL_LIBRARY = [
    {'number': 5, 'name': '3/8" Down Cut', 'diameter': 0.375, 'type': 'Down Cut'},
]


def _read_config():
    """Read and parse the config file once."""
    config_path = _get_config_path_base(APP_NAME)
    config = configparser.ConfigParser()
    if config_path.exists():
        config.read(config_path)
    return config


def _extract_gcode_settings(config):
    """Extract G-code settings from a parsed config."""
    d = GCODE_DEFAULTS
    return {
        'spindle_rpm': config.getint('gcode', 'spindle_rpm', fallback=d['spindle_rpm']),
        'feed_xy_rough': config.getint('gcode', 'feed_xy_rough', fallback=d['feed_xy_rough']),
        'feed_xy_finish': config.getint('gcode', 'feed_xy_finish', fallback=d['feed_xy_finish']),
        'feed_z': config.getint('gcode', 'feed_z', fallback=d['feed_z']),
        'cut_depth_adjustment': config.getfloat('gcode', 'cut_depth_adjustment', fallback=d['cut_depth_adjustment']),
        'roughing_pct': config.getint('gcode', 'roughing_pct', fallback=d['roughing_pct']),
        'zero_from': config.get('gcode', 'zero_from', fallback=d['zero_from']),
        'pocket_clearance': config.getfloat('gcode', 'pocket_clearance', fallback=d['pocket_clearance']),
        'safe_z': config.getfloat('gcode', 'safe_z', fallback=d['safe_z']),
        'retract_z': config.getfloat('gcode', 'retract_z', fallback=d['retract_z']),
        'end_position_offset': config.getfloat('gcode', 'end_position_offset', fallback=d['end_position_offset']),
        'end_z_height': config.getfloat('gcode', 'end_z_height', fallback=d['end_z_height']),
        'ramp_angle': config.getfloat('gcode', 'ramp_angle', fallback=d['ramp_angle']),
        'outline_tool': config.getint('gcode', 'outline_tool', fallback=d['outline_tool']),
        'pocket_tool': config.getint('gcode', 'pocket_tool', fallback=d['pocket_tool']),
    }


def _extract_tool_library(config):
    """Extract tool library from a parsed config."""
    tool_json = config.get('tools', 'library', fallback='[]')
    try:
        tools = json.loads(tool_json)
    except (json.JSONDecodeError, ValueError):
        tools = []
    if not tools:
        tools = list(DEFAULT_TOOL_LIBRARY)
    return tools


def load_gcode_settings():
    """Load G-code settings from config file."""
    return _extract_gcode_settings(_read_config())


def save_gcode_settings(settings: dict) -> None:
    """Save G-code settings to config file.

    Preserves existing sections (api, device, machine).
    """
    config_path = _get_config_path_base(APP_NAME)
    config = configparser.ConfigParser()

    if config_path.exists():
        config.read(config_path)

    if 'gcode' not in config:
        config['gcode'] = {}

    for key, value in settings.items():
        config['gcode'][key] = str(value)

    with open(config_path, 'w') as f:
        config.write(f)


def load_tool_library() -> list[dict]:
    """Load tool library from config file."""
    return _extract_tool_library(_read_config())


def load_gcode_and_tools():
    """Load both G-code settings and tool library with a single file read."""
    config = _read_config()
    return _extract_gcode_settings(config), _extract_tool_library(config)


def save_tool_library(tools: list[dict]) -> None:
    """Save tool library to config file."""
    config_path = _get_config_path_base(APP_NAME)
    config = configparser.ConfigParser()

    if config_path.exists():
        config.read(config_path)

    if 'tools' not in config:
        config['tools'] = {}

    config['tools']['library'] = json.dumps(tools)

    with open(config_path, 'w') as f:
        config.write(f)

"""
Resource path handling for PyInstaller compatibility.

When running as a bundled executable, resources are in a different location
than when running from source.
"""

import sys
from pathlib import Path


def get_base_path() -> Path:
    """
    Get the base path for the application.

    When running from source: returns the project directory.
    When running as PyInstaller bundle: returns the bundle's temp directory.
    """
    if getattr(sys, 'frozen', False) and hasattr(sys, '_MEIPASS'):
        # Running as PyInstaller bundle
        return Path(sys._MEIPASS)
    else:
        # Running from source
        return Path(__file__).parent.parent


def _get_app_data_dir() -> Path:
    """Get the platform-specific app data directory for frozen builds."""
    if sys.platform == 'darwin':
        return Path.home() / 'Library' / 'Application Support' / 'NestingApp'
    elif sys.platform == 'win32':
        return Path.home() / 'AppData' / 'Local' / 'NestingApp'
    else:
        return Path.home() / '.nesting_app'


def get_dxf_directory() -> Path:
    """
    Get the path to the dxf_files directory.

    When bundled, use a writable location in user's data directory
    so users can import new DXF files.
    """
    if getattr(sys, 'frozen', False):
        dxf_dir = _get_app_data_dir() / 'dxf_files'
        dxf_dir.mkdir(parents=True, exist_ok=True)
        return dxf_dir
    else:
        # Running from source, use project directory
        return get_base_path() / 'dxf_files'


def get_database_path() -> Path:
    """
    Get the path to the database file.

    For the database, we always want it in a writable location,
    so we use the user's data directory when bundled.
    """
    if getattr(sys, 'frozen', False):
        data_dir = _get_app_data_dir()
        data_dir.mkdir(parents=True, exist_ok=True)
        return data_dir / 'nesting.db'
    else:
        # Running from source, use project directory
        return get_base_path() / 'nesting.db'


def get_output_directory() -> Path:
    """Get the default output directory for exported files."""
    if getattr(sys, 'frozen', False):
        # When bundled, use user's Documents folder
        output_dir = Path.home() / 'Documents' / 'NestingApp_Output'
    else:
        # Running from source
        output_dir = get_base_path() / 'output'

    output_dir.mkdir(parents=True, exist_ok=True)
    return output_dir

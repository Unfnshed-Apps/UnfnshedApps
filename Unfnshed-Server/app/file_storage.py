"""File storage utilities for DXF and other files."""

import hashlib
import os
import re
from pathlib import Path
from typing import BinaryIO

from .config import get_settings


class FileStorage:
    """Handles file storage operations for the server."""

    # Subdirectories for different file types
    COMPONENT_DXF_DIR = "component_dxf"
    NESTED_OUTPUT_DIR = "nested_output"
    GCODE_EXPORTS_DIR = "gcode_exports"

    # Security limits
    MAX_FILE_SIZE = 10 * 1024 * 1024  # 10MB
    ALLOWED_DXF_EXTENSIONS = {".dxf"}
    ALLOWED_GCODE_EXTENSIONS = {".tap", ".nc", ".gcode"}

    def __init__(self, base_path: str = None):
        if base_path is None:
            settings = get_settings()
            base_path = settings.file_storage_path
        self.base_path = Path(base_path)
        self._ensure_directories()

    def _ensure_directories(self):
        """Create storage directories if they don't exist."""
        for subdir in [self.COMPONENT_DXF_DIR, self.NESTED_OUTPUT_DIR, self.GCODE_EXPORTS_DIR]:
            (self.base_path / subdir).mkdir(parents=True, exist_ok=True)

    def _sanitize_filename(self, filename: str) -> str:
        """
        Sanitize a filename to prevent path traversal and other attacks.

        Removes special characters, replaces spaces with underscores,
        and ensures the filename is safe for filesystem operations.
        """
        # Remove path components (prevent directory traversal)
        filename = os.path.basename(filename)

        # Remove or replace dangerous characters
        # Keep alphanumeric, underscore, hyphen, and period
        filename = re.sub(r'[^\w\-.]', '_', filename)

        # Remove multiple consecutive underscores/periods
        filename = re.sub(r'_{2,}', '_', filename)
        filename = re.sub(r'\.{2,}', '.', filename)

        # Remove leading/trailing underscores and periods
        filename = filename.strip('_.')

        # Ensure we have a filename
        if not filename:
            filename = "unnamed"

        return filename

    def _validate_file(self, filename: str, allowed_extensions: set, file_size: int = None) -> None:
        """Validate a file for upload. Raises ValueError if validation fails."""
        ext = Path(filename).suffix.lower()
        if ext not in allowed_extensions:
            allowed = ", ".join(sorted(allowed_extensions))
            raise ValueError(f"Invalid file extension: {ext}. Allowed: {allowed}")

        if file_size is not None and file_size > self.MAX_FILE_SIZE:
            raise ValueError(
                f"File too large: {file_size / 1024 / 1024:.1f}MB. "
                f"Maximum size is {self.MAX_FILE_SIZE / 1024 / 1024:.0f}MB."
            )

    def calculate_checksum(self, file_path: Path) -> str:
        """Calculate MD5 checksum of a file."""
        hash_md5 = hashlib.md5()
        with open(file_path, "rb") as f:
            for chunk in iter(lambda: f.read(8192), b""):
                hash_md5.update(chunk)
        return hash_md5.hexdigest()

    def _save_file(self, file: BinaryIO, filename: str, subdir: str,
                   allowed_extensions: set, default_ext: str = None) -> dict:
        """Save a file to the given subdirectory. Returns {filename, size, checksum}."""
        safe_filename = self._sanitize_filename(filename)
        self._validate_file(safe_filename, allowed_extensions)

        if default_ext and not any(safe_filename.lower().endswith(e) for e in allowed_extensions):
            safe_filename += default_ext

        dest_path = self.base_path / subdir / safe_filename

        content = file.read()
        self._validate_file(safe_filename, allowed_extensions, len(content))

        with open(dest_path, "wb") as f:
            f.write(content)

        return {
            "filename": safe_filename,
            "size": len(content),
            "checksum": self.calculate_checksum(dest_path)
        }

    def _get_file_path(self, filename: str, subdir: str) -> Path:
        """Get full path to a file, raising FileNotFoundError if missing."""
        safe_filename = self._sanitize_filename(filename)
        file_path = self.base_path / subdir / safe_filename
        if not file_path.exists():
            raise FileNotFoundError(f"File not found: {safe_filename}")
        return file_path

    def _delete_file(self, filename: str, subdir: str) -> bool:
        """Delete a file. Returns True if deleted, False if not found."""
        safe_filename = self._sanitize_filename(filename)
        file_path = self.base_path / subdir / safe_filename
        if file_path.exists():
            file_path.unlink()
            return True
        return False

    def _list_files(self, subdir: str, pattern: str) -> list[dict]:
        """List files matching pattern in subdirectory."""
        directory = self.base_path / subdir
        files = []
        for file_path in sorted(directory.glob(pattern)):
            files.append({
                "filename": file_path.name,
                "size": file_path.stat().st_size,
                "checksum": self.calculate_checksum(file_path)
            })
        return files

    def _file_exists(self, filename: str, subdir: str) -> bool:
        safe_filename = self._sanitize_filename(filename)
        return (self.base_path / subdir / safe_filename).exists()

    # ==================== Component DXF ====================

    def save_component_dxf(self, file: BinaryIO, filename: str) -> dict:
        return self._save_file(file, filename, self.COMPONENT_DXF_DIR,
                               self.ALLOWED_DXF_EXTENSIONS, ".dxf")

    def get_component_dxf_path(self, filename: str) -> Path:
        return self._get_file_path(filename, self.COMPONENT_DXF_DIR)

    def delete_component_dxf(self, filename: str) -> bool:
        return self._delete_file(filename, self.COMPONENT_DXF_DIR)

    def list_component_dxf(self) -> list[dict]:
        return self._list_files(self.COMPONENT_DXF_DIR, "*.dxf")

    def component_dxf_exists(self, filename: str) -> bool:
        return self._file_exists(filename, self.COMPONENT_DXF_DIR)

    # ==================== Nesting DXF ====================

    def save_nesting_dxf(self, file: BinaryIO, filename: str) -> dict:
        return self._save_file(file, filename, self.NESTED_OUTPUT_DIR,
                               self.ALLOWED_DXF_EXTENSIONS, ".dxf")

    def get_nesting_dxf_path(self, filename: str) -> Path:
        return self._get_file_path(filename, self.NESTED_OUTPUT_DIR)

    def delete_nesting_dxf(self, filename: str) -> bool:
        return self._delete_file(filename, self.NESTED_OUTPUT_DIR)

    def list_nesting_dxf(self) -> list[dict]:
        return self._list_files(self.NESTED_OUTPUT_DIR, "*.dxf")

    # ==================== G-code ====================

    def save_gcode(self, file: BinaryIO, filename: str) -> dict:
        return self._save_file(file, filename, self.GCODE_EXPORTS_DIR,
                               self.ALLOWED_GCODE_EXTENSIONS, ".tap")

    def get_gcode_path(self, filename: str) -> Path:
        return self._get_file_path(filename, self.GCODE_EXPORTS_DIR)

    def delete_gcode(self, filename: str) -> bool:
        return self._delete_file(filename, self.GCODE_EXPORTS_DIR)

    def list_gcode(self) -> list[dict]:
        files = []
        for ext in self.ALLOWED_GCODE_EXTENSIONS:
            files.extend(self._list_files(self.GCODE_EXPORTS_DIR, f"*{ext}"))
        return sorted(files, key=lambda f: f["filename"])


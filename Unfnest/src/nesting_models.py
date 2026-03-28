"""
Data models for the nesting system.

These are pure data containers used across the nesting pipeline,
DXF output, and UI layers.
"""

from dataclasses import dataclass, field
from typing import Optional

from .dxf_loader import EntityPath
from .enrichment import _polygon_area


# Default sheet dimensions: 4' x 8' in inches
SHEET_WIDTH = 48.0
SHEET_HEIGHT = 96.0

# Default part spacing: 3/4" bit diameter
PART_SPACING = 0.75


@dataclass
class PlacedPart:
    """A part that has been placed on a sheet."""
    part_id: str
    source_filename: str
    x: float
    y: float
    rotation: float
    polygon: list[tuple[float, float]]
    # Layer-separated geometry for G-code generation (polygon approximations)
    outline_polygons: list[list[tuple[float, float]]] = field(default_factory=list)
    pocket_polygons: list[list[tuple[float, float]]] = field(default_factory=list)
    internal_polygons: list[list[tuple[float, float]]] = field(default_factory=list)
    # Raw entity data for smooth G-code output (preserves arcs/circles)
    outline_entities: list[EntityPath] = field(default_factory=list)
    pocket_entities: list[EntityPath] = field(default_factory=list)
    internal_entities: list[EntityPath] = field(default_factory=list)


@dataclass
class NestedSheet:
    """A single sheet with placed parts."""
    sheet_number: int
    width: float
    height: float
    parts: list[PlacedPart]

    @property
    def utilization(self) -> float:
        """Calculate material utilization percentage."""
        if not self.parts:
            return 0.0
        total_part_area = sum(
            _polygon_area(p.polygon) for p in self.parts
        )
        sheet_area = self.width * self.height
        return (total_part_area / sheet_area) * 100


@dataclass
class SheetMetadata:
    """Per-sheet metadata for constrained nesting."""
    has_variable_pockets: bool
    bundle_group: Optional[int] = None


@dataclass
class NestingResult:
    """Result of a nesting operation."""
    sheets: list[NestedSheet]
    total_parts: int
    parts_placed: int
    parts_failed: int
    sheet_metadata: Optional[list[SheetMetadata]] = None

    @property
    def sheets_used(self) -> int:
        return len(self.sheets)

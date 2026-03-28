"""
Simplified DXF loader for preview rendering.

Extracts polygon geometry from DXF files for icon display.
No raw entity preservation (not needed for previews).
"""

import ezdxf
import math
from pathlib import Path
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class BoundingBox:
    """Axis-aligned bounding box."""
    min_x: float
    min_y: float
    max_x: float
    max_y: float

    @property
    def width(self) -> float:
        return self.max_x - self.min_x

    @property
    def height(self) -> float:
        return self.max_y - self.min_y


@dataclass
class PartGeometry:
    """Polygon geometry of a part extracted from a DXF file."""
    filename: str
    polygons: list[list[tuple[float, float]]]
    bounding_box: BoundingBox
    outline_polygons: list[list[tuple[float, float]]] = field(default_factory=list)
    pocket_polygons: list[list[tuple[float, float]]] = field(default_factory=list)

    @property
    def width(self) -> float:
        return self.bounding_box.width

    @property
    def height(self) -> float:
        return self.bounding_box.height


class DXFLoader:
    """
    Loads DXF files and extracts polygon geometry for preview rendering.

    Recognizes layers:
    - "Outline": Through-cut geometry (case-insensitive)
    - "Pocket": Partial-depth pocket geometry (case-insensitive)
    - Other layers treated as outline.

    Can fetch files from server if not found locally.
    """

    OUTLINE_LAYER = "outline"
    POCKET_LAYER = "pocket"

    def __init__(self, dxf_directory: str, api_client=None):
        self.dxf_directory = Path(dxf_directory)
        self.dxf_directory.mkdir(parents=True, exist_ok=True)
        self.api_client = api_client

    def _fetch_from_server(self, filename: str) -> bool:
        """Download a DXF file from the server if available."""
        if self.api_client is None:
            return False
        dest_path = self.dxf_directory / filename
        try:
            if self.api_client.download_component_dxf(filename, dest_path):
                return True
        except Exception as e:
            print(f"Failed to download DXF: {e}")
        return False

    def _is_pocket_layer(self, layer_name: str) -> bool:
        return layer_name.lower() == self.POCKET_LAYER

    def _extract_points(self, entity, entity_type: str) -> Optional[list[tuple[float, float]]]:
        """Extract polygon points from a DXF entity."""
        if entity_type == "LWPOLYLINE":
            if entity.closed:
                return [(p[0], p[1]) for p in entity.get_points()]

        elif entity_type == "POLYLINE":
            if entity.is_closed:
                return [(v.dxf.location.x, v.dxf.location.y) for v in entity.vertices]

        elif entity_type == "CIRCLE":
            center = entity.dxf.center
            radius = entity.dxf.radius
            return [
                (center.x + radius * math.cos(2 * math.pi * i / 32),
                 center.y + radius * math.sin(2 * math.pi * i / 32))
                for i in range(32)
            ]

        elif entity_type == "SPLINE":
            try:
                pts = [(p[0], p[1]) for p in entity.flattening(0.1)]
                if len(pts) >= 3:
                    dist = math.hypot(pts[0][0] - pts[-1][0], pts[0][1] - pts[-1][1])
                    if dist < 0.01:
                        pts = pts[:-1]
                    return pts
            except Exception:
                pass

        return None

    def load_part(self, filename: str) -> Optional[PartGeometry]:
        """Load a DXF file and extract polygon geometry."""
        filepath = self.dxf_directory / filename
        if not filepath.exists():
            if not self._fetch_from_server(filename):
                return None

        try:
            doc = ezdxf.readfile(str(filepath))
        except Exception as e:
            print(f"Error reading DXF {filepath}: {e}")
            return None

        msp = doc.modelspace()
        outline_polygons = []
        pocket_polygons = []

        for etype in ["LWPOLYLINE", "POLYLINE", "CIRCLE", "SPLINE"]:
            for entity in msp.query(etype):
                layer = entity.dxf.layer if hasattr(entity.dxf, 'layer') else "0"
                points = self._extract_points(entity, etype)
                if points and len(points) >= 3:
                    if self._is_pocket_layer(layer):
                        pocket_polygons.append(points)
                    else:
                        outline_polygons.append(points)

        all_polygons = outline_polygons + pocket_polygons
        if not all_polygons:
            return None

        bbox_polygons = outline_polygons if outline_polygons else all_polygons
        all_points = [p for poly in bbox_polygons for p in poly]
        min_x = min(p[0] for p in all_points)
        min_y = min(p[1] for p in all_points)
        max_x = max(p[0] for p in all_points)
        max_y = max(p[1] for p in all_points)

        def normalize(polygons):
            return [[(p[0] - min_x, p[1] - min_y) for p in poly] for poly in polygons]

        return PartGeometry(
            filename=filename,
            polygons=normalize(outline_polygons) + normalize(pocket_polygons),
            bounding_box=BoundingBox(0, 0, max_x - min_x, max_y - min_y),
            outline_polygons=normalize(outline_polygons),
            pocket_polygons=normalize(pocket_polygons),
        )

"""
DXF loader for preview rendering and G-code entity extraction.

Extracts polygon geometry from DXF files for icon display.
Fetches nesting DXF files from the server for sheet preview.
Extracts raw entity data (arcs, circles, polylines with bulges)
from nesting DXFs for G-code generation.
"""

from __future__ import annotations

import ezdxf
import math
from pathlib import Path
from dataclasses import dataclass, field
from typing import Optional, Union


# ==================== Geometry Conversion Helpers ====================

def _arc_to_points_from_params(
    cx: float, cy: float, radius: float,
    start_angle: float, end_angle: float,
    segments: int = 36, clockwise: bool = False,
) -> list[tuple[float, float]]:
    """Convert arc parameters to a list of (x, y) points.

    Angles are in radians. Returns *segments+1* points covering the arc span.
    """
    if not clockwise:
        if end_angle <= start_angle:
            end_angle += 2 * math.pi
    else:
        if start_angle <= end_angle:
            start_angle += 2 * math.pi

    arc_span = abs(end_angle - start_angle)
    actual_segments = max(8, int(segments * arc_span / (2 * math.pi)))

    points: list[tuple[float, float]] = []
    for i in range(actual_segments + 1):
        t = i / actual_segments
        if clockwise:
            angle = start_angle - t * (start_angle - end_angle)
        else:
            angle = start_angle + t * (end_angle - start_angle)
        points.append((cx + radius * math.cos(angle), cy + radius * math.sin(angle)))
    return points


def _circle_to_points(
    cx: float, cy: float, radius: float, segments: int = 72,
) -> list[tuple[float, float]]:
    """Convert a circle to a list of polygon points."""
    return [
        (cx + radius * math.cos(2 * math.pi * i / segments),
         cy + radius * math.sin(2 * math.pi * i / segments))
        for i in range(segments)
    ]


def _spline_to_points(
    entity, tolerance: float = 0.01,
) -> Optional[list[tuple[float, float]]]:
    """Flatten a spline entity to polygon points.

    Returns the point list, or None if the spline cannot be flattened.
    """
    try:
        pts = [(p[0], p[1]) for p in entity.flattening(tolerance)]
        if len(pts) >= 3:
            dist = math.hypot(pts[0][0] - pts[-1][0], pts[0][1] - pts[-1][1])
            if dist < 0.01:
                pts = pts[:-1]
            return pts
    except Exception:
        pass
    return None


# ==================== Entity Types for G-code Generation ====================

@dataclass
class LineEntity:
    """A straight line segment."""
    start: tuple[float, float]
    end: tuple[float, float]

    def get_start_point(self) -> tuple[float, float]:
        return self.start

    def get_end_point(self) -> tuple[float, float]:
        return self.end


@dataclass
class ArcEntity:
    """A circular arc segment.

    Angles are in degrees, counter-clockwise from positive X axis.
    """
    center: tuple[float, float]
    radius: float
    start_angle: float  # degrees
    end_angle: float    # degrees
    clockwise: bool = False  # Direction for G-code (G2=CW, G3=CCW)

    def get_start_point(self) -> tuple[float, float]:
        angle_rad = math.radians(self.start_angle)
        return (
            self.center[0] + self.radius * math.cos(angle_rad),
            self.center[1] + self.radius * math.sin(angle_rad),
        )

    def get_end_point(self) -> tuple[float, float]:
        angle_rad = math.radians(self.end_angle)
        return (
            self.center[0] + self.radius * math.cos(angle_rad),
            self.center[1] + self.radius * math.sin(angle_rad),
        )


@dataclass
class CircleEntity:
    """A full circle.

    For G-code, circles are typically output as two 180-degree arcs.
    """
    center: tuple[float, float]
    radius: float

    def get_start_point(self) -> tuple[float, float]:
        return (self.center[0] + self.radius, self.center[1])

    def get_end_point(self) -> tuple[float, float]:
        return self.get_start_point()


@dataclass
class PolylineEntity:
    """A polyline (connected line segments, possibly with bulges for arcs).

    Each point can have a bulge value that defines an arc to the next point.
    Bulge = tan(arc_angle / 4), where positive = CCW, negative = CW
    """
    points: list[tuple[float, float]]
    bulges: list[float]  # Bulge value for each point (0 = straight line)
    closed: bool = True

    def get_start_point(self) -> tuple[float, float]:
        return self.points[0] if self.points else (0, 0)

    def get_end_point(self) -> tuple[float, float]:
        if self.closed:
            return self.points[0] if self.points else (0, 0)
        return self.points[-1] if self.points else (0, 0)


# Type alias for any entity
DXFEntity = Union[LineEntity, ArcEntity, CircleEntity, PolylineEntity]


@dataclass
class EntityPath:
    """A closed path made up of connected entities.

    Represents a single closed contour (outline or pocket boundary).
    """
    entities: list[DXFEntity] = field(default_factory=list)

    def to_polygon_points(self, segments_per_arc: int = 180) -> list[tuple[float, float]]:
        """Convert to polygon points for bounding box calculations."""
        points = []

        for entity in self.entities:
            if isinstance(entity, LineEntity):
                if not points or points[-1] != entity.start:
                    points.append(entity.start)
                points.append(entity.end)

            elif isinstance(entity, ArcEntity):
                arc_points = _arc_to_points(entity, segments_per_arc)
                for pt in arc_points:
                    if not points or points[-1] != pt:
                        points.append(pt)

            elif isinstance(entity, CircleEntity):
                points.extend(_circle_to_points(
                    entity.center[0], entity.center[1], entity.radius, segments=segments_per_arc
                ))

            elif isinstance(entity, PolylineEntity):
                poly_points = _polyline_to_points(entity, segments_per_arc)
                for pt in poly_points:
                    if not points or points[-1] != pt:
                        points.append(pt)

        return points


def _arc_to_points(arc: ArcEntity, num_segments: int) -> list[tuple[float, float]]:
    """Convert an ArcEntity to line segment points."""
    return _arc_to_points_from_params(
        arc.center[0], arc.center[1], arc.radius,
        math.radians(arc.start_angle), math.radians(arc.end_angle),
        segments=num_segments, clockwise=arc.clockwise,
    )


def _polyline_to_points(poly: PolylineEntity, segments_per_arc: int) -> list[tuple[float, float]]:
    """Convert polyline with bulges to points."""
    points = []
    n = len(poly.points)

    for i in range(n):
        pt = poly.points[i]
        if not points or points[-1] != pt:
            points.append(pt)

        bulge = poly.bulges[i] if i < len(poly.bulges) else 0

        if bulge != 0 and (poly.closed or i < n - 1):
            next_i = (i + 1) % n if poly.closed else i + 1
            if next_i < n:
                next_pt = poly.points[next_i]
                arc_points = _bulge_to_arc_points(pt, next_pt, bulge, segments_per_arc)
                for apt in arc_points[1:]:
                    points.append(apt)

    return points


def _bulge_to_arc_points(
    start: tuple[float, float],
    end: tuple[float, float],
    bulge: float,
    num_segments: int
) -> list[tuple[float, float]]:
    """Convert a bulge arc to points."""
    dx = end[0] - start[0]
    dy = end[1] - start[1]
    chord_len = math.sqrt(dx * dx + dy * dy)

    if chord_len < 1e-10:
        return [start, end]

    theta = 4 * math.atan(abs(bulge))
    radius = chord_len / (2 * math.sin(theta / 2))

    mid_x = (start[0] + end[0]) / 2
    mid_y = (start[1] + end[1]) / 2

    perp_x = -dy / chord_len
    perp_y = dx / chord_len

    h = radius * math.cos(theta / 2)

    if bulge > 0:
        center_x = mid_x + h * perp_x
        center_y = mid_y + h * perp_y
    else:
        center_x = mid_x - h * perp_x
        center_y = mid_y - h * perp_y

    start_angle = math.atan2(start[1] - center_y, start[0] - center_x)
    end_angle = math.atan2(end[1] - center_y, end[0] - center_x)

    arc_segments = max(4, int(num_segments * theta / (2 * math.pi)))

    points = []
    for i in range(arc_segments + 1):
        t = i / arc_segments
        if bulge > 0:  # CCW
            if end_angle < start_angle:
                end_angle += 2 * math.pi
            angle = start_angle + t * (end_angle - start_angle)
        else:  # CW
            if start_angle < end_angle:
                start_angle += 2 * math.pi
            angle = start_angle - t * (start_angle - end_angle)

        x = center_x + radius * math.cos(angle)
        y = center_y + radius * math.sin(angle)
        points.append((x, y))

    return points


# ==================== Nesting DXF Entity Extraction ====================

@dataclass
class NestingDXFEntities:
    """Extracted entity data from a nesting DXF for G-code generation.

    Entities are in final sheet coordinates (no transforms needed).
    """
    outline_contours: list[EntityPath]   # Closed paths on Outline layer
    pocket_contours: list[EntityPath]    # Closed paths on Pocket layer
    internal_contours: list[EntityPath] = field(default_factory=list)  # Internal layer (through-cut holes)
    variable_pocket_contours: list[EntityPath] = field(default_factory=list)  # Pocket_Variable layer
    sheet_width: float = 0.0
    sheet_height: float = 0.0


# ==================== Preview Data Classes ====================

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
class SheetEntity:
    """A single entity from a nested sheet DXF, used for clickable damage reporting."""
    polygon: list[tuple[float, float]]
    layer: str
    bounding_box: BoundingBox
    centroid: tuple[float, float]


@dataclass
class PartGeometry:
    """Polygon geometry of a part extracted from a DXF file."""
    filename: str
    polygons: list[list[tuple[float, float]]]
    bounding_box: BoundingBox
    outline_polygons: list[list[tuple[float, float]]] = field(default_factory=list)
    pocket_polygons: list[list[tuple[float, float]]] = field(default_factory=list)
    internal_polygons: list[list[tuple[float, float]]] = field(default_factory=list)
    variable_pocket_polygons: list[list[tuple[float, float]]] = field(default_factory=list)
    sheet_entities: list[SheetEntity] = field(default_factory=list)
    sheet_boundary: Optional[list[tuple[float, float]]] = None


class DXFLoader:
    """
    Loads DXF files and extracts polygon geometry for preview rendering.

    Recognizes layers:
    - "Outline": Through-cut geometry (case-insensitive)
    - "Pocket": Partial-depth pocket geometry (case-insensitive)
    - Other layers treated as outline.

    Can fetch nesting DXF files from server.
    """

    OUTLINE_LAYER = "outline"
    POCKET_LAYER = "pocket"
    INTERNAL_LAYER = "internal"
    VARIABLE_POCKET_LAYER = "pocket_variable"
    SHEET_BOUNDARY_LAYER = "sheet_boundary"

    def __init__(self, dxf_directory: str, api_client=None):
        self.dxf_directory = Path(dxf_directory)
        self.dxf_directory.mkdir(parents=True, exist_ok=True)
        self.api_client = api_client

    def _fetch_from_server(self, filename: str) -> bool:
        """Download a nesting DXF file from the server if available."""
        if self.api_client is None:
            return False
        dest_path = self.dxf_directory / filename
        try:
            if self.api_client.download_nesting_dxf(filename, dest_path):
                return True
        except Exception as e:
            print(f"Failed to download DXF: {e}")
        return False

    def _is_pocket_layer(self, layer_name: str) -> bool:
        return layer_name.lower() == self.POCKET_LAYER

    def _is_internal_layer(self, layer_name: str) -> bool:
        return layer_name.lower() == self.INTERNAL_LAYER

    def _is_variable_pocket_layer(self, layer_name: str) -> bool:
        return layer_name.lower() == self.VARIABLE_POCKET_LAYER

    def _is_sheet_boundary_layer(self, layer_name: str) -> bool:
        return layer_name.lower() == self.SHEET_BOUNDARY_LAYER

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
            return _circle_to_points(center.x, center.y, entity.dxf.radius, segments=32)

        elif entity_type == "ARC":
            center = entity.dxf.center
            return _arc_to_points_from_params(
                center.x, center.y, entity.dxf.radius,
                math.radians(entity.dxf.start_angle),
                math.radians(entity.dxf.end_angle),
                segments=32, clockwise=False,
            )

        elif entity_type == "SPLINE":
            return _spline_to_points(entity, tolerance=0.1)

        return None

    @staticmethod
    def _lines_to_closed_paths(
        segments: list[tuple[tuple[float, float], tuple[float, float]]],
    ) -> list[list[tuple[float, float]]]:
        """Build closed polygons from individual LINE segments."""
        TOL = 0.001
        remaining = list(segments)
        closed_paths = []

        while remaining:
            seg = remaining.pop(0)
            path = [seg[0], seg[1]]

            changed = True
            while changed:
                changed = False
                for i, s in enumerate(remaining):
                    # Check if s connects to end of path
                    if math.hypot(s[0][0] - path[-1][0], s[0][1] - path[-1][1]) < TOL:
                        path.append(s[1])
                        remaining.pop(i)
                        changed = True
                        break
                    if math.hypot(s[1][0] - path[-1][0], s[1][1] - path[-1][1]) < TOL:
                        path.append(s[0])
                        remaining.pop(i)
                        changed = True
                        break
                    # Check if s connects to start of path
                    if math.hypot(s[1][0] - path[0][0], s[1][1] - path[0][1]) < TOL:
                        path.insert(0, s[0])
                        remaining.pop(i)
                        changed = True
                        break
                    if math.hypot(s[0][0] - path[0][0], s[0][1] - path[0][1]) < TOL:
                        path.insert(0, s[1])
                        remaining.pop(i)
                        changed = True
                        break

            # Check if path is closed
            if len(path) >= 3 and math.hypot(path[0][0] - path[-1][0], path[0][1] - path[-1][1]) < TOL:
                path = path[:-1]  # Remove duplicate closing point
                closed_paths.append(path)

        return closed_paths

    def load_nesting_dxf_entities(self, filename: str) -> Optional[NestingDXFEntities]:
        """Extract raw entity data from a nesting DXF for G-code generation.

        Nesting DXFs contain all parts already positioned and transformed.
        This method extracts entities by layer without any normalization.

        Args:
            filename: Nesting DXF filename (already cached locally by load_part).

        Returns:
            NestingDXFEntities with outline/pocket contours and sheet dimensions,
            or None if the file can't be loaded.
        """
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
        outline_contours: list[EntityPath] = []
        pocket_contours: list[EntityPath] = []
        internal_contours: list[EntityPath] = []
        variable_pocket_contours: list[EntityPath] = []
        sheet_width = 0.0
        sheet_height = 0.0

        for etype in ["LWPOLYLINE", "POLYLINE", "CIRCLE", "SPLINE", "ARC"]:
            for entity in msp.query(etype):
                layer = entity.dxf.layer if hasattr(entity.dxf, 'layer') else "0"

                if self._is_sheet_boundary_layer(layer):
                    # Extract sheet dimensions from boundary
                    points = self._extract_points(entity, etype)
                    if points and len(points) >= 3:
                        xs = [p[0] for p in points]
                        ys = [p[1] for p in points]
                        sheet_width = max(xs) - min(xs)
                        sheet_height = max(ys) - min(ys)
                    continue

                # Extract raw entity data
                raw_entity = self._extract_raw_entity(entity, etype)
                if raw_entity is None:
                    continue

                entity_path = EntityPath(entities=[raw_entity])

                if self._is_variable_pocket_layer(layer):
                    variable_pocket_contours.append(entity_path)
                elif self._is_pocket_layer(layer):
                    pocket_contours.append(entity_path)
                elif self._is_internal_layer(layer):
                    internal_contours.append(entity_path)
                else:
                    outline_contours.append(entity_path)

        if not outline_contours and not pocket_contours and not internal_contours and not variable_pocket_contours:
            return None

        return NestingDXFEntities(
            outline_contours=outline_contours,
            pocket_contours=pocket_contours,
            internal_contours=internal_contours,
            variable_pocket_contours=variable_pocket_contours,
            sheet_width=sheet_width,
            sheet_height=sheet_height,
        )

    def _extract_raw_entity(self, entity, entity_type: str) -> Optional[DXFEntity]:
        """Extract a raw DXFEntity from an ezdxf entity.

        Returns the entity data structure for G-code generation, or None.
        """
        if entity_type == "LWPOLYLINE":
            if entity.closed:
                raw_points = []
                raw_bulges = []
                for x, y, start_width, end_width, bulge in entity.get_points(format='xyseb'):
                    raw_points.append((x, y))
                    raw_bulges.append(bulge)
                return PolylineEntity(points=raw_points, bulges=raw_bulges, closed=True)

        elif entity_type == "POLYLINE":
            if entity.is_closed:
                raw_points = [(v.dxf.location.x, v.dxf.location.y) for v in entity.vertices]
                raw_bulges = [getattr(v.dxf, 'bulge', 0) for v in entity.vertices]
                return PolylineEntity(points=raw_points, bulges=raw_bulges, closed=True)

        elif entity_type == "CIRCLE":
            center = entity.dxf.center
            radius = entity.dxf.radius
            return CircleEntity(center=(center.x, center.y), radius=radius)

        elif entity_type == "ARC":
            center = entity.dxf.center
            return ArcEntity(
                center=(center.x, center.y),
                radius=entity.dxf.radius,
                start_angle=entity.dxf.start_angle,
                end_angle=entity.dxf.end_angle,
                clockwise=False,
            )

        elif entity_type == "SPLINE":
            flattened = _spline_to_points(entity, tolerance=0.0001)
            if flattened is not None:
                return PolylineEntity(
                    points=flattened,
                    bulges=[0] * len(flattened),
                    closed=True,
                )

        return None

    def load_part(self, filename: str, normalize: bool = True) -> Optional[PartGeometry]:
        """Load a DXF file and extract polygon geometry.

        Args:
            filename: DXF filename to load.
            normalize: If True (default), translate coordinates so bbox starts at (0,0).
                       If False, keep absolute coordinates (for placement matching).
        """
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
        internal_polygons = []
        variable_pocket_polygons = []
        sheet_entities_list: list[SheetEntity] = []
        sheet_boundary = None

        for etype in ["LWPOLYLINE", "POLYLINE", "CIRCLE", "SPLINE", "ARC"]:
            for entity in msp.query(etype):
                layer = entity.dxf.layer if hasattr(entity.dxf, 'layer') else "0"

                if self._is_sheet_boundary_layer(layer):
                    points = self._extract_points(entity, etype)
                    if points and len(points) >= 3:
                        sheet_boundary = points
                    continue

                points = self._extract_points(entity, etype)
                if points and len(points) >= 3:
                    if self._is_variable_pocket_layer(layer):
                        variable_pocket_polygons.append(points)
                    elif self._is_pocket_layer(layer):
                        pocket_polygons.append(points)
                    elif self._is_internal_layer(layer):
                        internal_polygons.append(points)
                    else:
                        outline_polygons.append(points)
                        xs = [p[0] for p in points]
                        ys = [p[1] for p in points]
                        sheet_entities_list.append(SheetEntity(
                            polygon=points,
                            layer=layer,
                            bounding_box=BoundingBox(min(xs), min(ys), max(xs), max(ys)),
                            centroid=(sum(xs) / len(xs), sum(ys) / len(ys)),
                        ))

        # Build closed polygons from individual LINE entities
        lines = list(msp.query("LINE"))
        if lines:
            line_groups = {}  # layer → list of (start, end)
            for line in lines:
                layer = line.dxf.layer if hasattr(line.dxf, 'layer') else "0"
                start = (line.dxf.start.x, line.dxf.start.y)
                end = (line.dxf.end.x, line.dxf.end.y)
                line_groups.setdefault(layer, []).append((start, end))

            for layer, segs in line_groups.items():
                if self._is_sheet_boundary_layer(layer):
                    closed = self._lines_to_closed_paths(segs)
                    if closed:
                        sheet_boundary = closed[0]
                    continue

                closed_paths = self._lines_to_closed_paths(segs)
                for points in closed_paths:
                    if len(points) < 3:
                        continue
                    if self._is_variable_pocket_layer(layer):
                        variable_pocket_polygons.append(points)
                    elif self._is_pocket_layer(layer):
                        pocket_polygons.append(points)
                    elif self._is_internal_layer(layer):
                        internal_polygons.append(points)
                    else:
                        outline_polygons.append(points)
                        xs = [p[0] for p in points]
                        ys = [p[1] for p in points]
                        sheet_entities_list.append(SheetEntity(
                            polygon=points,
                            layer=layer,
                            bounding_box=BoundingBox(min(xs), min(ys), max(xs), max(ys)),
                            centroid=(sum(xs) / len(xs), sum(ys) / len(ys)),
                        ))

        all_polygons = outline_polygons + pocket_polygons + internal_polygons + variable_pocket_polygons
        if not all_polygons:
            return None

        bbox_polygons = outline_polygons if outline_polygons else all_polygons
        all_points = [p for poly in bbox_polygons for p in poly]
        min_x = min(p[0] for p in all_points)
        min_y = min(p[1] for p in all_points)
        max_x = max(p[0] for p in all_points)
        max_y = max(p[1] for p in all_points)

        if normalize:
            def _translate(polygons):
                return [[(p[0] - min_x, p[1] - min_y) for p in poly] for poly in polygons]

            result_entities = []
            for se in sheet_entities_list:
                np_ = [(p[0] - min_x, p[1] - min_y) for p in se.polygon]
                nxs = [p[0] for p in np_]
                nys = [p[1] for p in np_]
                result_entities.append(SheetEntity(
                    polygon=np_, layer=se.layer,
                    bounding_box=BoundingBox(min(nxs), min(nys), max(nxs), max(nys)),
                    centroid=(sum(nxs) / len(nxs), sum(nys) / len(nys)),
                ))

            result_boundary = None
            if sheet_boundary:
                result_boundary = [(p[0] - min_x, p[1] - min_y) for p in sheet_boundary]

            return PartGeometry(
                filename=filename,
                polygons=_translate(outline_polygons) + _translate(pocket_polygons) + _translate(internal_polygons) + _translate(variable_pocket_polygons),
                bounding_box=BoundingBox(0, 0, max_x - min_x, max_y - min_y),
                outline_polygons=_translate(outline_polygons),
                pocket_polygons=_translate(pocket_polygons),
                internal_polygons=_translate(internal_polygons),
                variable_pocket_polygons=_translate(variable_pocket_polygons),
                sheet_entities=result_entities,
                sheet_boundary=result_boundary,
            )
        else:
            # Keep absolute coordinates for placement matching
            return PartGeometry(
                filename=filename,
                polygons=outline_polygons + pocket_polygons + internal_polygons + variable_pocket_polygons,
                bounding_box=BoundingBox(min_x, min_y, max_x, max_y),
                outline_polygons=outline_polygons,
                pocket_polygons=pocket_polygons,
                internal_polygons=internal_polygons,
                variable_pocket_polygons=variable_pocket_polygons,
                sheet_entities=sheet_entities_list,
                sheet_boundary=sheet_boundary,
            )

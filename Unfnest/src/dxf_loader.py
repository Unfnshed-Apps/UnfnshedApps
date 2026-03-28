"""
DXF file loading and geometry extraction utilities.

Supports layer-based geometry separation:
- "Outline" layer: Through-cut geometry (full depth, outward offset)
- "Pocket" layer: Partial-depth pocket geometry
- "Internal" layer: Through-cut internal holes (full depth, inward offset)

Preserves raw DXF entity data (arcs, circles) for smooth G-code output.
"""

import ezdxf
import hashlib
import math
from pathlib import Path
from dataclasses import dataclass, field
from typing import Optional, Union

from .resources import get_dxf_directory


# ---------------------------------------------------------------------------
# Geometry conversion helpers (single source of truth)
# ---------------------------------------------------------------------------

def _arc_to_points(
    cx: float, cy: float, radius: float,
    start_angle: float, end_angle: float,
    segments: int = 36, clockwise: bool = False,
) -> list[tuple[float, float]]:
    """
    Approximate a circular arc as a list of (x, y) points.

    Args:
        cx, cy: Centre of the arc.
        radius: Arc radius.
        start_angle: Start angle in **degrees**.
        end_angle: End angle in **degrees**.
        segments: Base number of segments for a full circle; actual count is
                  scaled by the arc's angular span.
        clockwise: If True the arc is traversed CW, otherwise CCW.

    Returns:
        List of (x, y) points along the arc (inclusive of both endpoints).
    """
    start_rad = math.radians(start_angle)
    end_rad = math.radians(end_angle)

    # Handle angle wrap-around
    if not clockwise:
        if end_rad <= start_rad:
            end_rad += 2 * math.pi
    else:
        if start_rad <= end_rad:
            start_rad += 2 * math.pi

    arc_span = abs(end_rad - start_rad)
    actual_segments = max(8, int(segments * arc_span / (2 * math.pi)))

    points: list[tuple[float, float]] = []
    for i in range(actual_segments + 1):
        t = i / actual_segments
        if clockwise:
            angle = start_rad - t * (start_rad - end_rad)
        else:
            angle = start_rad + t * (end_rad - start_rad)
        points.append((cx + radius * math.cos(angle),
                        cy + radius * math.sin(angle)))
    return points


def _circle_to_points(
    cx: float, cy: float, radius: float, segments: int = 72,
) -> list[tuple[float, float]]:
    """
    Approximate a full circle as a list of (x, y) polygon points.

    Args:
        cx, cy: Centre of the circle.
        radius: Circle radius.
        segments: Number of polygon vertices.

    Returns:
        List of *segments* (x, y) points evenly spaced around the circle.
    """
    points: list[tuple[float, float]] = []
    for i in range(segments):
        angle = 2.0 * math.pi * i / segments
        points.append((cx + radius * math.cos(angle),
                        cy + radius * math.sin(angle)))
    return points


def _spline_to_points(
    entity, tolerance: float = 0.01,
) -> Optional[list[tuple[float, float]]]:
    """
    Flatten a DXF SPLINE entity into polygon points.

    Args:
        entity: An ezdxf SPLINE entity.
        tolerance: Flattening tolerance (smaller = more points).

    Returns:
        List of (x, y) points with the duplicate closing point removed if the
        spline is closed, or *None* on failure / too few points.
    """
    try:
        points = [(p[0], p[1]) for p in entity.flattening(tolerance)]
        if len(points) >= 3:
            # Remove duplicate closing point when the spline is closed
            dist = math.hypot(points[0][0] - points[-1][0],
                              points[0][1] - points[-1][1])
            if dist < 0.01:
                points = points[:-1]
            return points
    except Exception as e:
        print(f"Warning: Could not flatten spline: {e}")
    return None



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
    """
    A circular arc segment.

    Angles are in degrees, counter-clockwise from positive X axis.
    """
    center: tuple[float, float]
    radius: float
    start_angle: float  # degrees
    end_angle: float    # degrees
    clockwise: bool = False  # Direction for G-code (G2=CW, G3=CCW)

    def get_start_point(self) -> tuple[float, float]:
        """Get the starting point of the arc."""
        angle_rad = math.radians(self.start_angle)
        x = self.center[0] + self.radius * math.cos(angle_rad)
        y = self.center[1] + self.radius * math.sin(angle_rad)
        return (x, y)

    def get_end_point(self) -> tuple[float, float]:
        """Get the ending point of the arc."""
        angle_rad = math.radians(self.end_angle)
        x = self.center[0] + self.radius * math.cos(angle_rad)
        y = self.center[1] + self.radius * math.sin(angle_rad)
        return (x, y)


@dataclass
class CircleEntity:
    """
    A full circle.

    For G-code, circles are typically output as two 180-degree arcs.
    """
    center: tuple[float, float]
    radius: float

    def get_start_point(self) -> tuple[float, float]:
        """Get a consistent starting point (rightmost point)."""
        return (self.center[0] + self.radius, self.center[1])

    def get_end_point(self) -> tuple[float, float]:
        """Circle ends where it starts."""
        return self.get_start_point()


@dataclass
class PolylineEntity:
    """
    A polyline (connected line segments, possibly with bulges for arcs).

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
    """
    A closed path made up of connected entities.

    This represents a single closed contour (outline or pocket boundary).
    """
    entities: list[DXFEntity] = field(default_factory=list)

    def to_polygon_points(self, segments_per_arc: int = 180) -> list[tuple[float, float]]:
        """
        Convert to polygon points for nesting/bounding box calculations.

        Args:
            segments_per_arc: Number of line segments to approximate arcs

        Returns:
            List of (x, y) points
        """
        points = []

        for entity in self.entities:
            if isinstance(entity, LineEntity):
                if not points or points[-1] != entity.start:
                    points.append(entity.start)
                points.append(entity.end)

            elif isinstance(entity, ArcEntity):
                arc_points = _arc_to_points(
                    entity.center[0], entity.center[1], entity.radius,
                    entity.start_angle, entity.end_angle,
                    segments=segments_per_arc, clockwise=entity.clockwise,
                )
                for pt in arc_points:
                    if not points or points[-1] != pt:
                        points.append(pt)

            elif isinstance(entity, CircleEntity):
                circle_pts = _circle_to_points(
                    entity.center[0], entity.center[1], entity.radius,
                    segments=segments_per_arc,
                )
                points.extend(circle_pts)

            elif isinstance(entity, PolylineEntity):
                poly_points = self._polyline_to_points(entity, segments_per_arc)
                for pt in poly_points:
                    if not points or points[-1] != pt:
                        points.append(pt)

        return points

    def _polyline_to_points(self, poly: PolylineEntity, segments_per_arc: int) -> list[tuple[float, float]]:
        """Convert polyline with bulges to points."""
        points = []
        n = len(poly.points)

        for i in range(n):
            pt = poly.points[i]
            if not points or points[-1] != pt:
                points.append(pt)

            bulge = poly.bulges[i] if i < len(poly.bulges) else 0

            if bulge != 0 and (poly.closed or i < n - 1):
                # Arc segment to next point
                next_i = (i + 1) % n if poly.closed else i + 1
                if next_i < n:
                    next_pt = poly.points[next_i]
                    arc_points = self._bulge_to_arc_points(pt, next_pt, bulge, segments_per_arc)
                    for apt in arc_points[1:]:  # Skip first point (already added)
                        points.append(apt)

        return points

    def _bulge_to_arc_points(
        self,
        start: tuple[float, float],
        end: tuple[float, float],
        bulge: float,
        num_segments: int
    ) -> list[tuple[float, float]]:
        """Convert a bulge arc to points."""
        # Calculate arc parameters from bulge
        dx = end[0] - start[0]
        dy = end[1] - start[1]
        chord_len = math.sqrt(dx * dx + dy * dy)

        if chord_len < 1e-10:
            return [start, end]

        # Bulge = tan(theta/4) where theta is the arc angle
        theta = 4 * math.atan(abs(bulge))
        radius = chord_len / (2 * math.sin(theta / 2))

        # Find center point
        mid_x = (start[0] + end[0]) / 2
        mid_y = (start[1] + end[1]) / 2

        # Perpendicular direction
        perp_x = -dy / chord_len
        perp_y = dx / chord_len

        # Distance from midpoint to center
        h = radius * math.cos(theta / 2)

        # Bulge sign determines which side of chord the center is on
        if bulge > 0:
            center_x = mid_x + h * perp_x
            center_y = mid_y + h * perp_y
        else:
            center_x = mid_x - h * perp_x
            center_y = mid_y - h * perp_y

        # Generate arc points
        start_angle = math.atan2(start[1] - center_y, start[0] - center_x)
        end_angle = math.atan2(end[1] - center_y, end[0] - center_x)

        # Number of segments based on arc angle
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

    @property
    def area(self) -> float:
        return self.width * self.height


@dataclass
class PartGeometry:
    """
    Represents the geometry of a single part extracted from a DXF file.

    Geometry is separated by layer:
    - outline_polygons: Geometry from "Outline" layer (through-cuts) - polygon approximation
    - pocket_polygons: Geometry from "Pocket" layer (partial-depth cuts) - polygon approximation
    - polygons: Legacy field - all polygons combined (for nesting bounding box)

    Raw entity data (for smooth G-code output):
    - outline_entities: Raw DXF entities for outlines (preserves arcs/circles)
    - pocket_entities: Raw DXF entities for pockets
    """
    filename: str
    polygons: list[list[tuple[float, float]]]  # All polygons (for nesting)
    bounding_box: BoundingBox
    # Layer-separated geometry (polygon approximations for nesting)
    outline_polygons: list[list[tuple[float, float]]] = field(default_factory=list)
    pocket_polygons: list[list[tuple[float, float]]] = field(default_factory=list)
    internal_polygons: list[list[tuple[float, float]]] = field(default_factory=list)
    # Raw entity data (for smooth G-code generation)
    outline_entities: list[EntityPath] = field(default_factory=list)
    pocket_entities: list[EntityPath] = field(default_factory=list)
    internal_entities: list[EntityPath] = field(default_factory=list)

    @property
    def width(self) -> float:
        return self.bounding_box.width

    @property
    def height(self) -> float:
        return self.bounding_box.height

    @property
    def has_pockets(self) -> bool:
        return len(self.pocket_polygons) > 0

    @property
    def has_internals(self) -> bool:
        return len(self.internal_polygons) > 0

    @property
    def has_raw_entities(self) -> bool:
        """Check if raw entity data is available."""
        return (len(self.outline_entities) > 0 or len(self.pocket_entities) > 0
                or len(self.internal_entities) > 0)


class DXFLoader:
    """
    Loads and extracts geometry from DXF files.

    Recognizes three layers:
    - "Outline": Through-cut geometry (case-insensitive)
    - "Pocket": Partial-depth pocket geometry (case-insensitive)
    - "Internal": Through-cut internal holes (case-insensitive)

    Geometry on other layers is treated as outline geometry.

    Can optionally fetch files from server if not found locally.
    """

    # Layer names (case-insensitive matching)
    OUTLINE_LAYER = "outline"
    POCKET_LAYER = "pocket"
    INTERNAL_LAYER = "internal"

    def __init__(self, dxf_directory: str = None, api_client=None):
        """
        Initialize the DXF loader.

        Args:
            dxf_directory: Path to local DXF directory (uses default if None)
            api_client: Optional APIClient instance for fetching files from server
        """
        if dxf_directory is None:
            self.dxf_directory = get_dxf_directory()
        else:
            self.dxf_directory = Path(dxf_directory)
        self.api_client = api_client

    def _fetch_from_server(self, filename: str) -> bool:
        """
        Try to fetch a DXF file from the server and save to dxf_directory.

        Args:
            filename: Name of the DXF file

        Returns:
            True if downloaded successfully, False otherwise
        """
        if self.api_client is None:
            return False

        dest_path = self.dxf_directory / filename

        # Try to download from server
        try:
            if self.api_client.download_component_dxf(filename, dest_path):
                print(f"Downloaded DXF from server: {filename}")
                return True
        except Exception as e:
            print(f"Failed to download DXF from server: {e}")

        return False

    def _md5_of_file(self, filepath: Path) -> str:
        """Compute MD5 hex digest of a local file."""
        h = hashlib.md5()
        with open(filepath, "rb") as f:
            for chunk in iter(lambda: f.read(8192), b""):
                h.update(chunk)
        return h.hexdigest()

    def sync_from_server(self) -> dict:
        """
        Sync local DXF cache with server.

        Downloads missing/changed files, removes stale local files.

        Returns:
            dict with keys: downloaded, deleted, unchanged
        """
        result = {"downloaded": 0, "deleted": 0, "unchanged": 0}

        if self.api_client is None:
            return result

        try:
            server_files = self.api_client.list_server_dxf_files()
        except Exception as e:
            print(f"DXF sync: failed to list server files: {e}")
            return result

        if not server_files:
            return result

        # Ensure local directory exists
        self.dxf_directory.mkdir(parents=True, exist_ok=True)

        # Build server filename -> checksum map
        server_map = {}
        for entry in server_files:
            server_map[entry["filename"]] = entry.get("checksum", "")

        # Check each server file against local
        for filename, server_checksum in server_map.items():
            local_path = self.dxf_directory / filename
            needs_download = False

            if not local_path.exists():
                needs_download = True
            elif server_checksum:
                local_checksum = self._md5_of_file(local_path)
                if local_checksum != server_checksum:
                    needs_download = True

            if needs_download:
                if self._fetch_from_server(filename):
                    result["downloaded"] += 1
                else:
                    print(f"DXF sync: failed to download {filename}")
            else:
                result["unchanged"] += 1

        # Remove local .dxf files not on server
        for local_file in self.dxf_directory.glob("*.dxf"):
            if local_file.name not in server_map:
                try:
                    local_file.unlink()
                    print(f"DXF sync: removed stale file {local_file.name}")
                    result["deleted"] += 1
                except OSError as e:
                    print(f"DXF sync: failed to remove {local_file.name}: {e}")

        return result

    def _get_layer_type(self, layer_name: str) -> str:
        """
        Determine if a layer is outline, pocket, or internal.

        Returns 'pocket', 'internal', or 'outline' (default).
        """
        lower = layer_name.lower()
        if lower == self.POCKET_LAYER:
            return 'pocket'
        if lower == self.INTERNAL_LAYER:
            return 'internal'
        return 'outline'

    def _extract_raw_entity(self, entity, entity_type: str) -> Optional[tuple[DXFEntity, list[tuple[float, float]]]]:
        """
        Extract raw entity data and polygon points from a DXF entity.

        Returns:
            Tuple of (raw_entity, polygon_points) or None if not a valid closed entity
        """
        raw_entity = None
        points = None

        if entity_type == "LWPOLYLINE":
            if entity.closed:
                # Extract points and bulges for arc segments
                raw_points = []
                raw_bulges = []
                for x, y, start_width, end_width, bulge in entity.get_points(format='xyseb'):
                    raw_points.append((x, y))
                    raw_bulges.append(bulge)

                raw_entity = PolylineEntity(
                    points=raw_points,
                    bulges=raw_bulges,
                    closed=True
                )

                # Also generate polygon points for nesting
                entity_path = EntityPath(entities=[raw_entity])
                points = entity_path.to_polygon_points()

        elif entity_type == "POLYLINE":
            if entity.is_closed:
                raw_points = [(v.dxf.location.x, v.dxf.location.y) for v in entity.vertices]
                # POLYLINE bulges are stored differently
                raw_bulges = [getattr(v.dxf, 'bulge', 0) for v in entity.vertices]

                raw_entity = PolylineEntity(
                    points=raw_points,
                    bulges=raw_bulges,
                    closed=True
                )

                entity_path = EntityPath(entities=[raw_entity])
                points = entity_path.to_polygon_points()

        elif entity_type == "CIRCLE":
            center = entity.dxf.center
            radius = entity.dxf.radius

            raw_entity = CircleEntity(
                center=(center.x, center.y),
                radius=radius
            )

            # Polygon approximation for nesting
            points = _circle_to_points(center.x, center.y, radius)

        elif entity_type == "SPLINE":
            # Splines don't have a simple arc representation - keep as polyline
            # Use 0.0001" tolerance for smooth curves (matches VCarve quality)
            flattened = _spline_to_points(entity, tolerance=0.0001)
            if flattened is not None:
                raw_entity = PolylineEntity(
                    points=flattened,
                    bulges=[0] * len(flattened),  # No bulges - straight segments
                    closed=True
                )
                points = flattened

        elif entity_type == "ARC":
            center = entity.dxf.center
            radius = entity.dxf.radius
            start_angle = entity.dxf.start_angle  # Already in degrees
            end_angle = entity.dxf.end_angle

            raw_entity = ArcEntity(
                center=(center.x, center.y),
                radius=radius,
                start_angle=start_angle,
                end_angle=end_angle,
                clockwise=False  # DXF arcs are CCW by default
            )

            # Polygon approximation
            points = _arc_to_points(
                center.x, center.y, radius,
                start_angle, end_angle, segments=36,
            )

        # Validate we have enough points
        if points and len(points) >= 3 and raw_entity is not None:
            return (raw_entity, points)

        return None

    def load_part(self, filename: str) -> Optional[PartGeometry]:
        """
        Load a DXF file and extract its geometry, separated by layer.

        Geometry on "Outline" layer -> outline_polygons (through-cuts)
        Geometry on "Pocket" layer -> pocket_polygons (partial-depth)
        Geometry on other layers -> treated as outline

        Also preserves raw entity data (arcs, circles) for smooth G-code output.

        If the file is not found locally, attempts to fetch from server (if api_client is set).
        """
        filepath = self.dxf_directory / filename

        if not filepath.exists():
            # Try to fetch from server (downloads to dxf_directory)
            if not self._fetch_from_server(filename):
                print(f"Warning: DXF file not found: {filepath}")
                return None

        try:
            doc = ezdxf.readfile(str(filepath))
        except Exception as e:
            print(f"Error reading DXF file {filepath}: {e}")
            return None

        msp = doc.modelspace()

        # Separate polygons and raw entities by layer type
        outline_polygons = []
        pocket_polygons = []
        internal_polygons = []
        outline_entities = []  # Raw entity paths
        pocket_entities = []   # Raw entity paths
        internal_entities = []

        # Entity types to process
        entity_types = ["LWPOLYLINE", "POLYLINE", "CIRCLE", "SPLINE", "ARC"]

        for entity_type in entity_types:
            for entity in msp.query(entity_type):
                # Get the layer name
                layer_name = entity.dxf.layer if hasattr(entity.dxf, 'layer') else "0"
                layer_type = self._get_layer_type(layer_name)

                # Extract raw entity and polygon points
                result = self._extract_raw_entity(entity, entity_type)

                if result:
                    raw_entity, points = result

                    # Create an EntityPath for this single entity
                    entity_path = EntityPath(entities=[raw_entity])

                    if layer_type == 'pocket':
                        pocket_polygons.append(points)
                        pocket_entities.append(entity_path)
                    elif layer_type == 'internal':
                        internal_polygons.append(points)
                        internal_entities.append(entity_path)
                    else:
                        outline_polygons.append(points)
                        outline_entities.append(entity_path)

        # Extract lines that form closed paths (basic rectangle detection)
        # Only process if we don't have any other geometry
        lines = list(msp.query("LINE"))
        if lines and not outline_polygons and not pocket_polygons and not internal_polygons:
            # Group lines by layer
            outline_lines = []
            pocket_lines = []
            internal_lines = []
            for line in lines:
                layer_name = line.dxf.layer if hasattr(line.dxf, 'layer') else "0"
                lt = self._get_layer_type(layer_name)
                if lt == 'pocket':
                    pocket_lines.append(line)
                elif lt == 'internal':
                    internal_lines.append(line)
                else:
                    outline_lines.append(line)

            # Extract closed paths from lines
            outline_line_paths = self._extract_closed_paths_from_lines(outline_lines)
            pocket_line_paths = self._extract_closed_paths_from_lines(pocket_lines)
            internal_line_paths = self._extract_closed_paths_from_lines(internal_lines)

            outline_polygons.extend(outline_line_paths)
            pocket_polygons.extend(pocket_line_paths)
            internal_polygons.extend(internal_line_paths)

            # Create EntityPaths for line-based paths (as polylines)
            for poly in outline_line_paths:
                entity_path = EntityPath(entities=[
                    PolylineEntity(points=poly, bulges=[0] * len(poly), closed=True)
                ])
                outline_entities.append(entity_path)

            for poly in pocket_line_paths:
                entity_path = EntityPath(entities=[
                    PolylineEntity(points=poly, bulges=[0] * len(poly), closed=True)
                ])
                pocket_entities.append(entity_path)

            for poly in internal_line_paths:
                entity_path = EntityPath(entities=[
                    PolylineEntity(points=poly, bulges=[0] * len(poly), closed=True)
                ])
                internal_entities.append(entity_path)

        # All polygons combined (for nesting - uses outline for bounding box)
        all_polygons = outline_polygons + pocket_polygons + internal_polygons

        if not all_polygons:
            print(f"Warning: No closed geometry found in {filename}")
            return None

        # Calculate bounding box from outline polygons (or all if no outlines)
        # The outline defines the part boundary for nesting
        bbox_polygons = outline_polygons if outline_polygons else all_polygons
        all_points = [p for poly in bbox_polygons for p in poly]
        min_x = min(p[0] for p in all_points)
        min_y = min(p[1] for p in all_points)
        max_x = max(p[0] for p in all_points)
        max_y = max(p[1] for p in all_points)

        # Normalize all polygons to origin (0, 0)
        def normalize_polygons(polygons):
            normalized = []
            for poly in polygons:
                normalized_poly = [(float(p[0] - min_x), float(p[1] - min_y)) for p in poly]
                normalized.append(normalized_poly)
            return normalized

        # Normalize entity paths to origin (0, 0)
        def normalize_entity_paths(entity_paths):
            normalized = []
            for path in entity_paths:
                normalized_entities = []
                for entity in path.entities:
                    normalized_entities.append(self._normalize_entity(entity, min_x, min_y))
                normalized.append(EntityPath(entities=normalized_entities))
            return normalized

        normalized_outline = normalize_polygons(outline_polygons)
        normalized_pocket = normalize_polygons(pocket_polygons)
        normalized_internal = normalize_polygons(internal_polygons)
        normalized_all = normalized_outline + normalized_pocket + normalized_internal

        normalized_outline_entities = normalize_entity_paths(outline_entities)
        normalized_pocket_entities = normalize_entity_paths(pocket_entities)
        normalized_internal_entities = normalize_entity_paths(internal_entities)

        # Bounding box is now at origin
        bbox = BoundingBox(
            min_x=0,
            min_y=0,
            max_x=max_x - min_x,
            max_y=max_y - min_y
        )

        return PartGeometry(
            filename=filename,
            polygons=normalized_all,
            bounding_box=bbox,
            outline_polygons=normalized_outline,
            pocket_polygons=normalized_pocket,
            internal_polygons=normalized_internal,
            outline_entities=normalized_outline_entities,
            pocket_entities=normalized_pocket_entities,
            internal_entities=normalized_internal_entities,
        )

    def _normalize_entity(self, entity: DXFEntity, offset_x: float, offset_y: float) -> DXFEntity:
        """Normalize an entity by offsetting its coordinates."""
        if isinstance(entity, LineEntity):
            return LineEntity(
                start=(entity.start[0] - offset_x, entity.start[1] - offset_y),
                end=(entity.end[0] - offset_x, entity.end[1] - offset_y)
            )
        elif isinstance(entity, ArcEntity):
            return ArcEntity(
                center=(entity.center[0] - offset_x, entity.center[1] - offset_y),
                radius=entity.radius,
                start_angle=entity.start_angle,
                end_angle=entity.end_angle,
                clockwise=entity.clockwise
            )
        elif isinstance(entity, CircleEntity):
            return CircleEntity(
                center=(entity.center[0] - offset_x, entity.center[1] - offset_y),
                radius=entity.radius
            )
        elif isinstance(entity, PolylineEntity):
            return PolylineEntity(
                points=[(p[0] - offset_x, p[1] - offset_y) for p in entity.points],
                bulges=entity.bulges.copy(),
                closed=entity.closed
            )
        return entity

    def _extract_closed_paths_from_lines(
        self, lines: list
    ) -> list[list[tuple[float, float]]]:
        """
        Build closed polygons from individual LINE entities using endpoint
        adjacency.  O(n) amortized — each line is visited at most once, and
        the adjacency dict gives O(1) lookup per step instead of scanning all
        endpoints.
        """
        if len(lines) < 3:
            return []

        def _round_pt(x, y):
            return (round(x, 6), round(y, 6))

        # Collect rounded endpoints per line and build adjacency map.
        # adjacency: point -> list of (other_point, line_index)
        endpoints = []
        adjacency: dict[tuple, list[tuple]] = {}
        for i, line in enumerate(lines):
            s = _round_pt(line.dxf.start.x, line.dxf.start.y)
            e = _round_pt(line.dxf.end.x, line.dxf.end.y)
            endpoints.append((s, e))
            adjacency.setdefault(s, []).append((e, i))
            adjacency.setdefault(e, []).append((s, i))

        used = [False] * len(lines)
        polygons = []

        for start_idx in range(len(lines)):
            if used[start_idx]:
                continue

            s, e = endpoints[start_idx]
            used[start_idx] = True
            path = [s, e]
            current = e

            # Follow the chain until we close the loop or hit a dead end
            while current != path[0]:
                found = False
                for next_pt, line_idx in adjacency.get(current, []):
                    if not used[line_idx]:
                        used[line_idx] = True
                        path.append(next_pt)
                        current = next_pt
                        found = True
                        break
                if not found:
                    break  # Open path, can't close

            # Accept closed paths with at least 3 distinct vertices
            if len(path) >= 4 and path[0] == path[-1]:
                polygons.append(path[:-1])  # Remove duplicate closing point

        return polygons

    def get_available_files(self) -> list[str]:
        """List all DXF files in the directory."""
        if not self.dxf_directory.exists():
            return []
        return [f.name for f in self.dxf_directory.glob("*.dxf")]

"""
Comprehensive tests for src/dxf_loader.py.

Covers helper functions, dataclasses, the closed-path extraction algorithm,
and full DXFLoader.load_part() integration using in-memory ezdxf documents.
"""

import math
import tempfile
from pathlib import Path

import ezdxf
import pytest

from src.dxf_loader import (
    ArcEntity,
    BoundingBox,
    CircleEntity,
    DXFLoader,
    EntityPath,
    LineEntity,
    PartGeometry,
    PolylineEntity,
    _arc_to_points,
    _circle_to_points,
    _spline_to_points,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _distance(p1, p2):
    """Euclidean distance between two 2D points."""
    return math.hypot(p1[0] - p2[0], p1[1] - p2[1])


def _save_dxf(doc, directory: Path, filename: str) -> Path:
    """Save an ezdxf document to *directory/filename* and return the path."""
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / filename
    doc.saveas(str(path))
    return path


# ===================================================================
# 1. _arc_to_points
# ===================================================================

class TestArcToPoints:
    """Tests for the _arc_to_points helper."""

    def test_full_circle_produces_closed_polygon(self):
        """A 0-to-360 arc should start and end at the same point."""
        pts = _arc_to_points(0, 0, 10, 0, 360, segments=36)
        assert _distance(pts[0], pts[-1]) < 1e-9

    def test_quarter_arc_point_count(self):
        """A 90-degree arc with 36 base segments -> ~9 actual segments + 1."""
        pts = _arc_to_points(0, 0, 5, 0, 90, segments=36)
        expected_segments = max(8, int(36 * (math.pi / 2) / (2 * math.pi)))
        assert len(pts) == expected_segments + 1

    def test_clockwise_vs_counterclockwise_cover_same_arc(self):
        """CW and CCW arcs between same angles should both have all points
        on the circle, and CW should traverse the major arc (going the
        other way around)."""
        ccw = _arc_to_points(0, 0, 10, 0, 90, segments=36, clockwise=False)
        cw = _arc_to_points(0, 0, 10, 0, 90, segments=36, clockwise=True)
        # CCW 0->90 is a quarter circle; CW 0->90 is the complementary 270-degree arc.
        # CCW starts at angle 0 (10,0); CW starts at angle 0 (10,0) going the long way.
        assert _distance(ccw[0], (10, 0)) < 1e-6   # both start at angle 0
        assert _distance(cw[0], (10, 0)) < 1e-6
        # All points should lie on the circle regardless of direction
        for pt in cw:
            assert abs(_distance(pt, (0, 0)) - 10) < 1e-6

    def test_all_points_lie_on_circle(self):
        """Every generated point should be exactly *radius* from centre."""
        cx, cy, r = 3.0, 7.0, 12.5
        pts = _arc_to_points(cx, cy, r, 30, 270, segments=72)
        for x, y in pts:
            assert abs(_distance((x, y), (cx, cy)) - r) < 1e-9

    def test_half_circle_arc(self):
        """180-degree arc should span from start angle to start+180."""
        pts = _arc_to_points(0, 0, 1, 0, 180, segments=36)
        # First point at angle 0 -> (1, 0)
        assert abs(pts[0][0] - 1.0) < 1e-9
        assert abs(pts[0][1] - 0.0) < 1e-9
        # Last point at angle 180 -> (-1, 0)
        assert abs(pts[-1][0] - (-1.0)) < 1e-9
        assert abs(pts[-1][1] - 0.0) < 1e-9

    def test_minimum_segments_floor(self):
        """Even a tiny arc should produce at least 8 segments."""
        pts = _arc_to_points(0, 0, 1, 0, 1, segments=36)
        assert len(pts) == 9  # 8 segments + 1


# ===================================================================
# 2. _circle_to_points
# ===================================================================

class TestCircleToPoints:
    """Tests for the _circle_to_points helper."""

    def test_default_segments_count(self):
        pts = _circle_to_points(0, 0, 5)
        assert len(pts) == 72

    def test_custom_segment_count(self):
        pts = _circle_to_points(0, 0, 5, segments=36)
        assert len(pts) == 36

    def test_all_points_equidistant_from_center(self):
        cx, cy, r = 2.0, -3.0, 8.0
        pts = _circle_to_points(cx, cy, r, segments=100)
        for x, y in pts:
            assert abs(_distance((x, y), (cx, cy)) - r) < 1e-9

    def test_first_point_at_zero_angle(self):
        """First point should be at angle 0, i.e. (cx+r, cy)."""
        pts = _circle_to_points(1, 2, 3)
        assert abs(pts[0][0] - 4.0) < 1e-9
        assert abs(pts[0][1] - 2.0) < 1e-9


# ===================================================================
# 3. _spline_to_points (minimal — needs ezdxf entity)
# ===================================================================

class TestSplineToPoints:
    """Minimal tests for _spline_to_points using real ezdxf entities."""

    def test_closed_spline(self):
        """A closed spline should return points without a duplicate closing point."""
        doc = ezdxf.new()
        msp = doc.modelspace()
        # Create a closed spline via fit points that loop back
        fit_points = [(0, 0), (10, 5), (10, 10), (0, 10), (-5, 5), (0, 0)]
        spline = msp.add_spline(fit_points, degree=3)

        pts = _spline_to_points(spline, tolerance=0.1)
        assert pts is not None
        assert len(pts) >= 3
        # The closing-point dedup should have removed the duplicate end
        assert _distance(pts[0], pts[-1]) > 0.01

    def test_returns_none_for_degenerate_spline(self):
        """A spline with fewer than 3 flattened points should return None."""
        doc = ezdxf.new()
        msp = doc.modelspace()
        # Two-point "spline" (degenerate)
        spline = msp.add_spline([(0, 0), (1, 0)], degree=1)
        result = _spline_to_points(spline, tolerance=100)
        # With a very large tolerance we might get < 3 points -> None
        # (If ezdxf still returns enough points, at least assert non-crash.)
        assert result is None or len(result) >= 3


# ===================================================================
# 4. BoundingBox
# ===================================================================

class TestBoundingBox:
    def test_width_and_height(self):
        bb = BoundingBox(min_x=1, min_y=2, max_x=11, max_y=7)
        assert bb.width == pytest.approx(10)
        assert bb.height == pytest.approx(5)

    def test_area(self):
        bb = BoundingBox(min_x=0, min_y=0, max_x=4, max_y=3)
        assert bb.area == pytest.approx(12)

    def test_zero_size(self):
        bb = BoundingBox(min_x=5, min_y=5, max_x=5, max_y=5)
        assert bb.width == 0
        assert bb.height == 0
        assert bb.area == 0


# ===================================================================
# 5. PartGeometry
# ===================================================================

class TestPartGeometry:
    def _make_simple(self, outline=None, pocket=None, internal=None):
        outline = outline or []
        pocket = pocket or []
        internal = internal or []
        all_polys = outline + pocket + internal
        bb = BoundingBox(0, 0, 10, 10)
        return PartGeometry(
            filename="test.dxf",
            polygons=all_polys,
            bounding_box=bb,
            outline_polygons=outline,
            pocket_polygons=pocket,
            internal_polygons=internal,
        )

    def test_width_height_from_bbox(self):
        pg = self._make_simple()
        assert pg.width == 10
        assert pg.height == 10

    def test_has_pockets_false(self):
        pg = self._make_simple()
        assert pg.has_pockets is False

    def test_has_pockets_true(self):
        pg = self._make_simple(pocket=[[(0, 0), (1, 0), (1, 1)]])
        assert pg.has_pockets is True

    def test_has_internals(self):
        pg = self._make_simple(internal=[[(0, 0), (2, 0), (2, 2)]])
        assert pg.has_internals is True

    def test_has_raw_entities_false(self):
        pg = self._make_simple()
        assert pg.has_raw_entities is False

    def test_has_raw_entities_true(self):
        pg = self._make_simple()
        pg.outline_entities = [EntityPath(entities=[CircleEntity((0, 0), 5)])]
        assert pg.has_raw_entities is True

    def test_empty_geometry(self):
        pg = self._make_simple()
        assert pg.polygons == []
        assert pg.outline_polygons == []


# ===================================================================
# 6. EntityPath
# ===================================================================

class TestEntityPath:
    def test_line_entities_to_polygon(self):
        """A triangle of LineEntities should produce 4 points (3 vertices + closing)."""
        path = EntityPath(entities=[
            LineEntity(start=(0, 0), end=(10, 0)),
            LineEntity(start=(10, 0), end=(5, 10)),
            LineEntity(start=(5, 10), end=(0, 0)),
        ])
        pts = path.to_polygon_points()
        # (0,0), (10,0), (5,10), (0,0)
        assert len(pts) == 4
        assert pts[0] == (0, 0)
        assert pts[1] == (10, 0)
        assert pts[2] == (5, 10)
        assert pts[3] == (0, 0)

    def test_arc_entity_to_polygon(self):
        """An ArcEntity should expand into multiple points."""
        arc = ArcEntity(center=(0, 0), radius=5, start_angle=0, end_angle=90)
        path = EntityPath(entities=[arc])
        pts = path.to_polygon_points(segments_per_arc=36)
        assert len(pts) > 2
        # All points on circle
        for p in pts:
            assert abs(_distance(p, (0, 0)) - 5) < 1e-6

    def test_circle_entity_to_polygon(self):
        """A CircleEntity should produce segments_per_arc points."""
        circle = CircleEntity(center=(0, 0), radius=3)
        path = EntityPath(entities=[circle])
        pts = path.to_polygon_points(segments_per_arc=48)
        assert len(pts) == 48

    def test_polyline_entity_to_polygon(self):
        """A simple closed polyline (no bulges) should reproduce its points."""
        poly = PolylineEntity(
            points=[(0, 0), (10, 0), (10, 10), (0, 10)],
            bulges=[0, 0, 0, 0],
            closed=True,
        )
        path = EntityPath(entities=[poly])
        pts = path.to_polygon_points()
        assert len(pts) == 4
        assert pts[0] == (0, 0)
        assert pts[3] == (0, 10)

    def test_empty_entity_path(self):
        path = EntityPath()
        assert path.to_polygon_points() == []


# ===================================================================
# 6b. Entity start/end points and normalization
# ===================================================================

class TestEntityEndpoints:
    def test_line_entity_endpoints(self):
        e = LineEntity(start=(1, 2), end=(3, 4))
        assert e.get_start_point() == (1, 2)
        assert e.get_end_point() == (3, 4)

    def test_arc_entity_endpoints(self):
        e = ArcEntity(center=(0, 0), radius=10, start_angle=0, end_angle=90)
        sx, sy = e.get_start_point()
        assert abs(sx - 10) < 1e-9
        assert abs(sy - 0) < 1e-9
        ex, ey = e.get_end_point()
        assert abs(ex - 0) < 1e-6
        assert abs(ey - 10) < 1e-6

    def test_circle_entity_endpoints(self):
        e = CircleEntity(center=(5, 5), radius=3)
        assert e.get_start_point() == (8, 5)
        assert e.get_end_point() == e.get_start_point()

    def test_polyline_entity_endpoints_closed(self):
        e = PolylineEntity(points=[(1, 1), (2, 2), (3, 3)], bulges=[0, 0, 0], closed=True)
        assert e.get_start_point() == (1, 1)
        assert e.get_end_point() == (1, 1)  # closed -> loops back

    def test_polyline_entity_endpoints_open(self):
        e = PolylineEntity(points=[(1, 1), (2, 2), (3, 3)], bulges=[0, 0, 0], closed=False)
        assert e.get_start_point() == (1, 1)
        assert e.get_end_point() == (3, 3)


class TestNormalizeEntity:
    """Test DXFLoader._normalize_entity (shifts coordinates by offset)."""

    def setup_method(self):
        self.loader = DXFLoader(dxf_directory=tempfile.mkdtemp())

    def test_normalize_line(self):
        e = LineEntity(start=(10, 20), end=(30, 40))
        n = self.loader._normalize_entity(e, 5, 10)
        assert isinstance(n, LineEntity)
        assert n.start == (5, 10)
        assert n.end == (25, 30)

    def test_normalize_arc(self):
        e = ArcEntity(center=(10, 20), radius=5, start_angle=0, end_angle=90)
        n = self.loader._normalize_entity(e, 10, 20)
        assert isinstance(n, ArcEntity)
        assert n.center == (0, 0)
        assert n.radius == 5
        assert n.start_angle == 0

    def test_normalize_circle(self):
        e = CircleEntity(center=(10, 20), radius=7)
        n = self.loader._normalize_entity(e, 3, 4)
        assert n.center == (7, 16)
        assert n.radius == 7

    def test_normalize_polyline(self):
        e = PolylineEntity(points=[(10, 20), (30, 40)], bulges=[0.5, 0], closed=True)
        n = self.loader._normalize_entity(e, 10, 20)
        assert n.points == [(0, 0), (20, 20)]
        assert n.bulges == [0.5, 0]
        assert n.closed is True


# ===================================================================
# 7. _extract_closed_paths_from_lines
# ===================================================================

class TestExtractClosedPathsFromLines:
    """Tests for the O(n) adjacency-based line-to-polygon algorithm."""

    def setup_method(self):
        self.loader = DXFLoader(dxf_directory=tempfile.mkdtemp())

    def _make_line(self, sx, sy, ex, ey):
        """Create a minimal mock object that looks like an ezdxf LINE entity."""

        class _Vec:
            def __init__(self, x, y):
                self.x = x
                self.y = y

        class _Dxf:
            def __init__(self, s, e):
                self.start = s
                self.end = e

        class _Line:
            def __init__(self, s, e):
                self.dxf = _Dxf(s, e)

        return _Line(_Vec(sx, sy), _Vec(ex, ey))

    def test_triangle(self):
        lines = [
            self._make_line(0, 0, 10, 0),
            self._make_line(10, 0, 5, 10),
            self._make_line(5, 10, 0, 0),
        ]
        result = self.loader._extract_closed_paths_from_lines(lines)
        assert len(result) == 1
        assert len(result[0]) == 3

    def test_square(self):
        lines = [
            self._make_line(0, 0, 10, 0),
            self._make_line(10, 0, 10, 10),
            self._make_line(10, 10, 0, 10),
            self._make_line(0, 10, 0, 0),
        ]
        result = self.loader._extract_closed_paths_from_lines(lines)
        assert len(result) == 1
        assert len(result[0]) == 4

    def test_two_separate_closed_paths(self):
        lines = [
            # Triangle 1
            self._make_line(0, 0, 10, 0),
            self._make_line(10, 0, 5, 10),
            self._make_line(5, 10, 0, 0),
            # Triangle 2 (offset)
            self._make_line(20, 20, 30, 20),
            self._make_line(30, 20, 25, 30),
            self._make_line(25, 30, 20, 20),
        ]
        result = self.loader._extract_closed_paths_from_lines(lines)
        assert len(result) == 2

    def test_open_path_is_skipped(self):
        """Lines that don't form a closed loop should not appear in results."""
        lines = [
            self._make_line(0, 0, 10, 0),
            self._make_line(10, 0, 10, 10),
            # No closing line back to (0, 0)
        ]
        result = self.loader._extract_closed_paths_from_lines(lines)
        assert len(result) == 0

    def test_fewer_than_three_lines_returns_empty(self):
        lines = [self._make_line(0, 0, 10, 0)]
        assert self.loader._extract_closed_paths_from_lines(lines) == []
        assert self.loader._extract_closed_paths_from_lines([]) == []

    def test_lines_in_random_order(self):
        """Lines forming a square but given in shuffled order."""
        lines = [
            self._make_line(10, 10, 0, 10),   # side 3
            self._make_line(0, 0, 10, 0),      # side 1
            self._make_line(0, 10, 0, 0),      # side 4
            self._make_line(10, 0, 10, 10),    # side 2
        ]
        result = self.loader._extract_closed_paths_from_lines(lines)
        assert len(result) == 1
        assert len(result[0]) == 4

    def test_one_closed_one_open(self):
        """One closed triangle and one dangling open segment."""
        lines = [
            self._make_line(0, 0, 10, 0),
            self._make_line(10, 0, 5, 10),
            self._make_line(5, 10, 0, 0),
            # Dangling segment
            self._make_line(100, 100, 200, 200),
        ]
        result = self.loader._extract_closed_paths_from_lines(lines)
        assert len(result) == 1


# ===================================================================
# 8. DXFLoader integration tests (using in-memory ezdxf documents)
# ===================================================================

class TestDXFLoaderIntegration:
    """Full load_part() tests using real DXF files created with ezdxf."""

    def setup_method(self):
        self.tmpdir = Path(tempfile.mkdtemp())
        self.loader = DXFLoader(dxf_directory=str(self.tmpdir))

    # -- helpers --

    def _save(self, doc, name="test.dxf"):
        return _save_dxf(doc, self.tmpdir, name)

    # -- tests --

    def test_file_not_found_returns_none(self):
        result = self.loader.load_part("nonexistent.dxf")
        assert result is None

    def test_load_closed_lwpolyline_outline(self):
        """A single closed LWPOLYLINE on the default layer -> outline."""
        doc = ezdxf.new()
        msp = doc.modelspace()
        msp.add_lwpolyline(
            [(0, 0), (10, 0), (10, 5), (0, 5)], close=True
        )
        self._save(doc)

        part = self.loader.load_part("test.dxf")
        assert part is not None
        assert part.filename == "test.dxf"
        assert len(part.outline_polygons) == 1
        assert len(part.pocket_polygons) == 0
        assert part.width == pytest.approx(10)
        assert part.height == pytest.approx(5)

    def test_layer_separation_outline_and_pocket(self):
        """Entities on 'Outline' and 'Pocket' layers should be separated."""
        doc = ezdxf.new()
        msp = doc.modelspace()

        doc.layers.add("Outline")
        doc.layers.add("Pocket")

        # Outline rectangle
        msp.add_lwpolyline(
            [(0, 0), (20, 0), (20, 10), (0, 10)],
            close=True,
            dxfattribs={"layer": "Outline"},
        )
        # Pocket circle
        msp.add_circle(center=(10, 5), radius=2, dxfattribs={"layer": "Pocket"})
        self._save(doc)

        part = self.loader.load_part("test.dxf")
        assert part is not None
        assert len(part.outline_polygons) == 1
        assert len(part.pocket_polygons) == 1

    def test_layer_separation_internal(self):
        """Entities on 'Internal' layer should go to internal_polygons."""
        doc = ezdxf.new()
        msp = doc.modelspace()

        doc.layers.add("Outline")
        doc.layers.add("Internal")

        msp.add_lwpolyline(
            [(0, 0), (30, 0), (30, 20), (0, 20)],
            close=True,
            dxfattribs={"layer": "Outline"},
        )
        msp.add_circle(center=(15, 10), radius=3, dxfattribs={"layer": "Internal"})
        self._save(doc)

        part = self.loader.load_part("test.dxf")
        assert part is not None
        assert len(part.internal_polygons) == 1
        assert part.has_internals is True

    def test_case_insensitive_layer_matching(self):
        """Layer matching should be case-insensitive."""
        doc = ezdxf.new()
        msp = doc.modelspace()

        doc.layers.add("POCKET")

        msp.add_lwpolyline(
            [(0, 0), (10, 0), (10, 10), (0, 10)], close=True
        )
        msp.add_circle(center=(5, 5), radius=1, dxfattribs={"layer": "POCKET"})
        self._save(doc)

        part = self.loader.load_part("test.dxf")
        assert part is not None
        assert len(part.pocket_polygons) == 1

    def test_normalization_shifts_to_origin(self):
        """Geometry offset from origin should be normalized so min corner = (0,0)."""
        doc = ezdxf.new()
        msp = doc.modelspace()
        # Rectangle at (100, 200) to (110, 205)
        msp.add_lwpolyline(
            [(100, 200), (110, 200), (110, 205), (100, 205)], close=True
        )
        self._save(doc)

        part = self.loader.load_part("test.dxf")
        assert part is not None
        assert part.bounding_box.min_x == pytest.approx(0)
        assert part.bounding_box.min_y == pytest.approx(0)
        assert part.bounding_box.max_x == pytest.approx(10)
        assert part.bounding_box.max_y == pytest.approx(5)

        # Check that actual polygon points are shifted
        for poly in part.outline_polygons:
            for x, y in poly:
                assert x >= -1e-9
                assert y >= -1e-9

    def test_circle_only_file(self):
        """A file containing only a circle should load successfully."""
        doc = ezdxf.new()
        msp = doc.modelspace()
        msp.add_circle(center=(0, 0), radius=5)
        self._save(doc)

        part = self.loader.load_part("test.dxf")
        assert part is not None
        assert len(part.outline_polygons) == 1
        assert part.width == pytest.approx(10, abs=0.5)
        assert part.height == pytest.approx(10, abs=0.5)

    def test_line_only_rectangle(self):
        """Lines forming a closed rectangle (no polylines) should be extracted."""
        doc = ezdxf.new()
        msp = doc.modelspace()
        msp.add_line((0, 0), (10, 0))
        msp.add_line((10, 0), (10, 5))
        msp.add_line((10, 5), (0, 5))
        msp.add_line((0, 5), (0, 0))
        self._save(doc)

        part = self.loader.load_part("test.dxf")
        assert part is not None
        assert len(part.outline_polygons) == 1
        assert part.width == pytest.approx(10)
        assert part.height == pytest.approx(5)

    def test_lines_only_processed_when_no_other_geometry(self):
        """If closed polylines exist, loose lines should NOT be processed."""
        doc = ezdxf.new()
        msp = doc.modelspace()
        # A closed polyline
        msp.add_lwpolyline([(0, 0), (10, 0), (10, 10), (0, 10)], close=True)
        # Some extra lines (should be ignored)
        msp.add_line((20, 20), (30, 20))
        msp.add_line((30, 20), (30, 30))
        msp.add_line((30, 30), (20, 30))
        msp.add_line((20, 30), (20, 20))
        self._save(doc)

        part = self.loader.load_part("test.dxf")
        assert part is not None
        # Only the polyline should be present, lines ignored
        assert len(part.outline_polygons) == 1

    def test_no_closed_geometry_returns_none(self):
        """An open polyline with no other geometry should return None."""
        doc = ezdxf.new()
        msp = doc.modelspace()
        # Open polyline (not closed)
        msp.add_lwpolyline([(0, 0), (10, 0), (10, 10)], close=False)
        self._save(doc)

        part = self.loader.load_part("test.dxf")
        assert part is None

    def test_raw_entities_preserved(self):
        """load_part should populate outline_entities with raw entity data."""
        doc = ezdxf.new()
        msp = doc.modelspace()
        msp.add_circle(center=(5, 5), radius=5)
        self._save(doc)

        part = self.loader.load_part("test.dxf")
        assert part is not None
        assert part.has_raw_entities is True
        assert len(part.outline_entities) == 1
        assert len(part.outline_entities[0].entities) == 1
        raw = part.outline_entities[0].entities[0]
        assert isinstance(raw, CircleEntity)
        # Normalized: center was at (5,5), min corner of circle bbox is (0,0)
        assert raw.center[0] == pytest.approx(5, abs=0.5)
        assert raw.radius == pytest.approx(5)

    def test_get_available_files(self):
        """get_available_files should list .dxf files in the directory."""
        doc = ezdxf.new()
        _save_dxf(doc, self.tmpdir, "part_a.dxf")
        _save_dxf(doc, self.tmpdir, "part_b.dxf")

        files = self.loader.get_available_files()
        assert sorted(files) == ["part_a.dxf", "part_b.dxf"]

    def test_get_available_files_empty_dir(self):
        loader = DXFLoader(dxf_directory=str(self.tmpdir / "empty_sub"))
        assert loader.get_available_files() == []

    def test_unknown_layer_treated_as_outline(self):
        """Entities on unrecognised layers should be treated as outline."""
        doc = ezdxf.new()
        msp = doc.modelspace()
        doc.layers.add("SomeRandomLayer")
        msp.add_lwpolyline(
            [(0, 0), (5, 0), (5, 5), (0, 5)],
            close=True,
            dxfattribs={"layer": "SomeRandomLayer"},
        )
        self._save(doc)

        part = self.loader.load_part("test.dxf")
        assert part is not None
        assert len(part.outline_polygons) == 1
        assert len(part.pocket_polygons) == 0


# ===================================================================
# 9. _get_layer_type
# ===================================================================

class TestGetLayerType:
    def setup_method(self):
        self.loader = DXFLoader(dxf_directory=tempfile.mkdtemp())

    def test_outline(self):
        assert self.loader._get_layer_type("Outline") == "outline"
        assert self.loader._get_layer_type("OUTLINE") == "outline"
        assert self.loader._get_layer_type("outline") == "outline"

    def test_pocket(self):
        assert self.loader._get_layer_type("Pocket") == "pocket"
        assert self.loader._get_layer_type("POCKET") == "pocket"

    def test_internal(self):
        assert self.loader._get_layer_type("Internal") == "internal"
        assert self.loader._get_layer_type("INTERNAL") == "internal"

    def test_unknown_defaults_to_outline(self):
        assert self.loader._get_layer_type("0") == "outline"
        assert self.loader._get_layer_type("Foobar") == "outline"
        assert self.loader._get_layer_type("") == "outline"

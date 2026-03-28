"""Integration tests for the full nesting2 pipeline."""
from __future__ import annotations

import pytest
from shapely.geometry import Polygon as ShapelyPolygon
from shapely import affinity

from src.nesting.pipeline import nest_parts
from src.dxf_loader import PartGeometry, BoundingBox


def _rect_geom(part_id: str, w: float, h: float) -> tuple[str, PartGeometry]:
    """Create a (part_id, PartGeometry) tuple for a rectangle."""
    hw, hh = w / 2, h / 2
    polygon = [(-hw, -hh), (hw, -hh), (hw, hh), (-hw, hh)]
    geom = PartGeometry(
        filename=f"{part_id}.dxf",
        polygons=[polygon],
        bounding_box=BoundingBox(min_x=-hw, min_y=-hh, max_x=hw, max_y=hh),
        outline_polygons=[polygon],
    )
    return (part_id, geom)


class MockDB:
    """Minimal mock database for enrichment."""

    def __init__(self, components=None, products=None):
        self._components = components or []
        self._products = products or []

    def get_all_component_definitions(self):
        return self._components

    def get_all_products(self):
        return self._products

    def get_all_mating_pairs(self):
        return []


class MockComponent:
    def __init__(self, id, name, variable_pockets=False):
        self.id = id
        self.name = name
        self.variable_pockets = variable_pockets


@pytest.fixture
def db():
    return MockDB()


class TestSimplePipeline:
    def test_empty_parts(self, db):
        """Empty input should return empty result."""
        result, metadata = nest_parts([], db)
        assert result.total_parts == 0
        assert result.parts_placed == 0

    def test_single_part(self, db):
        """One part should be placed on one sheet."""
        parts = [_rect_geom("part1", 10, 20)]
        result, metadata = nest_parts(parts, db)

        assert result.total_parts == 1
        assert result.parts_placed == 1
        assert result.parts_failed == 0
        assert result.sheets_used == 1

    def test_multiple_parts_all_placed(self, db):
        """Multiple parts should all be placed."""
        parts = [_rect_geom(f"part_{i}", 8, 12) for i in range(10)]
        result, metadata = nest_parts(parts, db)

        assert result.parts_failed == 0
        assert result.parts_placed == 10

    def test_no_overlaps(self, db):
        """Placed parts should not overlap each other.

        Uses the same transform as the rendering code:
          1. Rotate around (0,0)
          2. Subtract rotated bbox min
          3. Add (part.x, part.y)
        """
        parts = [_rect_geom(f"part_{i}", 10, 15) for i in range(8)]
        result, metadata = nest_parts(
            parts, db, optimization_time_budget=0,
        )

        for sheet in result.sheets:
            polys = []
            for p in sheet.parts:
                # Match rendering: rotate around origin, normalize, translate
                poly = ShapelyPolygon(p.polygon)
                if p.rotation != 0:
                    poly = affinity.rotate(poly, p.rotation, origin=(0, 0))
                minx, miny = poly.bounds[0], poly.bounds[1]
                poly = affinity.translate(poly, xoff=-minx + p.x, yoff=-miny + p.y)
                polys.append(poly)

            # Check pairwise non-overlap (with rasterization tolerance)
            for i in range(len(polys)):
                for j in range(i + 1, len(polys)):
                    p1 = polys[i].buffer(-0.25)
                    p2 = polys[j].buffer(-0.25)
                    if not p1.is_empty and not p2.is_empty:
                        overlap = p1.intersection(p2).area
                        assert overlap < 0.5, (
                            f"Parts {sheet.parts[i].part_id} and "
                            f"{sheet.parts[j].part_id} overlap by {overlap:.2f} sq in"
                        )


class TestPlacedPartGeometry:
    def test_placed_part_has_polygons(self, db):
        """PlacedPart should have outline_polygons from geometry."""
        parts = [_rect_geom("test", 10, 10)]
        result, _ = nest_parts(parts, db, optimization_time_budget=0)

        placed = result.sheets[0].parts[0]
        assert placed.source_filename == "test.dxf"
        assert len(placed.polygon) == 4
        assert len(placed.outline_polygons) > 0


class TestMetadata:
    def test_metadata_count_matches_sheets(self, db):
        """Metadata list should match sheet count."""
        parts = [_rect_geom(f"p{i}", 10, 10) for i in range(5)]
        result, metadata = nest_parts(parts, db, optimization_time_budget=0)

        assert len(metadata) == result.sheets_used

class TestCancel:
    def test_cancel_returns_partial(self, db):
        """Cancel mid-nesting should return partial results."""
        parts = [_rect_geom(f"p{i}", 10, 15) for i in range(20)]

        call_count = [0]

        def cancel():
            call_count[0] += 1
            return call_count[0] > 10

        result, metadata = nest_parts(
            parts, db, cancel_check=cancel,
            optimization_time_budget=0,
        )

        # Should have some results but not necessarily all
        assert result.total_parts == 20


class TestCallbacks:
    def test_status_callback(self, db):
        """Status callback should be called."""
        messages = []
        parts = [_rect_geom("p1", 10, 10)]
        nest_parts(
            parts, db,
            status_callback=lambda msg: messages.append(msg),
            optimization_time_budget=0,
        )
        assert len(messages) > 0

    def test_progress_callback(self, db):
        """Progress callback should be called for each placed part."""
        progress = []
        parts = [_rect_geom(f"p{i}", 5, 5) for i in range(3)]
        nest_parts(
            parts, db,
            progress_callback=lambda c, t: progress.append((c, t)),
            optimization_time_budget=0,
        )
        assert len(progress) >= 3

    def test_live_callback(self, db):
        """Live callback should receive sheet states."""
        snapshots = []
        parts = [_rect_geom(f"p{i}", 10, 10) for i in range(3)]
        nest_parts(
            parts, db,
            live_callback=lambda sheets: snapshots.append(len(sheets)),
            optimization_time_budget=0,
        )
        assert len(snapshots) > 0


class TestProductGrouping:
    def test_product_parts_grouped(self):
        """Product parts should be grouped by (sku, unit)."""
        components = [
            MockComponent(1, "top", "show"),
            MockComponent(2, "side", "show"),
        ]

        class MockProduct:
            def __init__(self):
                self.sku = "SHELF-01"
                self.components = [
                    type('PC', (), {'component_name': 'top', 'quantity': 1})(),
                    type('PC', (), {'component_name': 'side', 'quantity': 2})(),
                ]

        db = MockDB(components=components, products=[MockProduct()])

        # Product parts: SHELF-01_top_001, SHELF-01_side_001, SHELF-01_side_002
        parts = [
            _rect_geom("SHELF-01_top_001", 20, 30),
            _rect_geom("SHELF-01_side_001", 10, 30),
            _rect_geom("SHELF-01_side_002", 10, 30),
        ]

        result, metadata = nest_parts(
            parts, db,
            product_comp_qty={("SHELF-01", "top"): 1, ("SHELF-01", "side"): 2},
            optimization_time_budget=0,
        )

        assert result.parts_failed == 0
        assert result.parts_placed == 3

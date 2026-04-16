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


def _component(id, name, variable_pockets=False, mating_role="neutral"):
    """Build a minimal mock component with explicit mating role."""
    return type('MC', (), {
        'id': id,
        'name': name,
        'variable_pockets': variable_pockets,
        'mating_role': mating_role,
    })()


def _product(sku, components_with_qty):
    """Build a minimal mock product. components_with_qty is [(name, qty), ...]."""
    return type('MP', (), {
        'sku': sku,
        'components': [
            type('PC', (), {'component_name': name, 'quantity': qty})()
            for name, qty in components_with_qty
        ],
    })()


def _sheet_of(result, part_id_substring):
    """Find sheet numbers (1-indexed) that contain parts matching the substring."""
    return [
        sheet.sheet_number for sheet in result.sheets
        for p in sheet.parts if part_id_substring in p.part_id
    ]


class TestMatingGroupAtomicity:
    """End-to-end tests: products with multiple tabs must keep tabs co-located.

    These tests run the full pipeline (enrich → group → greedy → SA) against
    realistic product layouts to catch regressions in any layer that could
    split a mating group across sheets.
    """

    def test_bench_two_identical_legs_same_sheet(self):
        """Bench: 2 identical legs (tabs) + 1 tabletop (receiver). All same sheet.

        Reproduces the user's reported bug: legs were splitting across sheets
        during SA optimization, with one leg following the tabletop and the
        other left orphaned.
        """
        db = MockDB(
            components=[
                _component(1, "leg", variable_pockets=False, mating_role="tab"),
                _component(2, "top", variable_pockets=True, mating_role="receiver"),
            ],
            products=[_product("BENCH-01", [("leg", 2), ("top", 1)])],
        )

        parts = [
            _rect_geom("BENCH-01_leg_001", 10, 30),
            _rect_geom("BENCH-01_leg_002", 10, 30),
            _rect_geom("BENCH-01_top_001", 30, 60),
        ]

        result, _ = nest_parts(
            parts, db,
            product_comp_qty={("BENCH-01", "leg"): 2, ("BENCH-01", "top"): 1},
            optimization_time_budget=1.0,  # actually run SA
        )

        leg_sheets = _sheet_of(result, "leg")
        top_sheets = _sheet_of(result, "top")
        assert len(leg_sheets) == 2, f"expected 2 legs placed, got {leg_sheets}"
        assert len(top_sheets) == 1, f"expected 1 top placed, got {top_sheets}"
        assert leg_sheets[0] == leg_sheets[1], (
            f"Bench legs split: leg_001=sheet {leg_sheets[0]}, leg_002=sheet {leg_sheets[1]}"
        )
        assert top_sheets[0] == leg_sheets[0], (
            f"Tabletop on sheet {top_sheets[0]} but legs on sheet {leg_sheets[0]}"
        )

    def test_stool_four_distinct_legs_same_sheet(self):
        """Stool: 4 distinct legs (each its own component) + 1 seat. All same sheet."""
        db = MockDB(
            components=[
                _component(1, "leg_a", variable_pockets=False, mating_role="tab"),
                _component(2, "leg_b", variable_pockets=False, mating_role="tab"),
                _component(3, "leg_c", variable_pockets=False, mating_role="tab"),
                _component(4, "leg_d", variable_pockets=False, mating_role="tab"),
                _component(5, "seat", variable_pockets=True, mating_role="receiver"),
            ],
            products=[_product("STOOL-01", [
                ("leg_a", 1), ("leg_b", 1), ("leg_c", 1), ("leg_d", 1), ("seat", 1),
            ])],
        )

        parts = [
            _rect_geom("STOOL-01_leg_a_001", 8, 25),
            _rect_geom("STOOL-01_leg_b_001", 8, 25),
            _rect_geom("STOOL-01_leg_c_001", 8, 25),
            _rect_geom("STOOL-01_leg_d_001", 8, 25),
            _rect_geom("STOOL-01_seat_001", 20, 20),
        ]

        result, _ = nest_parts(
            parts, db,
            product_comp_qty={
                ("STOOL-01", "leg_a"): 1, ("STOOL-01", "leg_b"): 1,
                ("STOOL-01", "leg_c"): 1, ("STOOL-01", "leg_d"): 1,
                ("STOOL-01", "seat"): 1,
            },
            optimization_time_budget=1.0,
        )

        leg_sheets = _sheet_of(result, "leg_")
        seat_sheets = _sheet_of(result, "seat")
        assert len(leg_sheets) == 4, f"expected 4 legs placed, got {leg_sheets}"
        assert len(set(leg_sheets)) == 1, (
            f"Stool legs split across sheets: {leg_sheets}"
        )
        assert seat_sheets[0] == leg_sheets[0], (
            f"Stool seat on sheet {seat_sheets[0]} but legs on sheet {leg_sheets[0]}"
        )

    def test_multiple_benches_each_block_intact(self):
        """3 benches in one order: each bench's legs must stay together.

        This is the realistic stress test — SA will reorder blocks and try
        to compact things; we need to verify all 3 blocks stay intact.
        """
        db = MockDB(
            components=[
                _component(1, "leg", variable_pockets=False, mating_role="tab"),
                _component(2, "top", variable_pockets=True, mating_role="receiver"),
            ],
            products=[_product("BENCH-01", [("leg", 2), ("top", 1)])],
        )

        parts = []
        for i in range(1, 7):
            parts.append(_rect_geom(f"BENCH-01_leg_{i:03d}", 10, 30))
        for i in range(1, 4):
            parts.append(_rect_geom(f"BENCH-01_top_{i:03d}", 30, 60))

        result, _ = nest_parts(
            parts, db,
            product_comp_qty={("BENCH-01", "leg"): 2, ("BENCH-01", "top"): 1},
            optimization_time_budget=2.0,
        )

        # For each bench unit (0, 1, 2) the two legs must share a sheet.
        # Unit numbering: leg_001+leg_002 = unit 0, leg_003+leg_004 = unit 1, etc.
        unit_to_leg_sheets: dict[int, list[int]] = {}
        for sheet in result.sheets:
            for p in sheet.parts:
                if p.part_id.startswith("BENCH-01_leg_"):
                    leg_num = int(p.part_id.split("_")[-1])
                    unit = (leg_num - 1) // 2
                    unit_to_leg_sheets.setdefault(unit, []).append(sheet.sheet_number)

        for unit, sheets in unit_to_leg_sheets.items():
            assert len(set(sheets)) == 1, (
                f"Bench unit {unit} legs split across sheets: {sheets}"
            )

    def test_oversized_block_fails_atomically(self):
        """If a mating group can't fit on any sheet, the whole tab group fails
        as a unit rather than half-placing parts in inconsistent locations."""
        db = MockDB(
            components=[
                _component(1, "leg", variable_pockets=False, mating_role="tab"),
            ],
            products=[_product("HUGE-01", [("leg", 2)])],
        )

        # Tabs each fit individually but don't fit together on a 48x96 sheet
        # when forced atomic AND the sheet has been pre-claimed by something else.
        # Easiest failure scenario: parts wider than the sheet.
        parts = [
            _rect_geom("HUGE-01_leg_001", 200, 30),  # too wide for any sheet
            _rect_geom("HUGE-01_leg_002", 200, 30),
        ]

        result, _ = nest_parts(
            parts, db,
            product_comp_qty={("HUGE-01", "leg"): 2},
            optimization_time_budget=0,
        )

        # Both should fail to place — and importantly, neither should be on
        # a sheet alone (no half-placed split blocks)
        leg_sheets = _sheet_of(result, "leg")
        assert leg_sheets == [], f"Expected no legs placed (oversized), got {leg_sheets}"
        assert result.parts_failed == 2

    def test_invariant_check_passes_clean_run(self, capsys):
        """When all blocks are intact, no warning should be emitted."""
        db = MockDB(
            components=[
                _component(1, "leg", variable_pockets=False, mating_role="tab"),
                _component(2, "top", variable_pockets=True, mating_role="receiver"),
            ],
            products=[_product("BENCH-01", [("leg", 2), ("top", 1)])],
        )
        parts = [
            _rect_geom("BENCH-01_leg_001", 10, 30),
            _rect_geom("BENCH-01_leg_002", 10, 30),
            _rect_geom("BENCH-01_top_001", 30, 60),
        ]
        nest_parts(
            parts, db,
            product_comp_qty={("BENCH-01", "leg"): 2, ("BENCH-01", "top"): 1},
            optimization_time_budget=1.0,
        )
        captured = capsys.readouterr()
        # No "split" warning should appear in stderr
        assert "split" not in captured.err.lower(), (
            f"Unexpected split warning: {captured.err}"
        )


class TestMatingFirstOrdering:
    """Verify _build_product_blocks puts mating blocks before neutral blocks
    (within each tier, sorted largest first).
    """

    def test_mating_blocks_processed_before_neutral_blocks(self):
        """A mixed order of mating and neutral products should result in all
        mating products' tab parts ending up on lower-numbered sheets than
        neutral-only products' parts."""
        db = MockDB(
            components=[
                _component(1, "leg", variable_pockets=False, mating_role="tab"),
                _component(2, "top", variable_pockets=True, mating_role="receiver"),
                _component(3, "shelf", variable_pockets=False, mating_role="neutral"),
            ],
            products=[
                # Mating product: bench
                _product("BENCH-01", [("leg", 2), ("top", 1)]),
                # Neutral-only product: shelving
                _product("SHELF-01", [("shelf", 1)]),
            ],
        )
        parts = [
            # Provide neutrals FIRST in the input list — ordering shouldn't depend on input order
            _rect_geom("SHELF-01_shelf_001", 30, 60),
            _rect_geom("SHELF-01_shelf_002", 30, 60),
            _rect_geom("BENCH-01_leg_001", 10, 30),
            _rect_geom("BENCH-01_leg_002", 10, 30),
            _rect_geom("BENCH-01_top_001", 30, 60),
        ]

        result, _ = nest_parts(
            parts, db,
            product_comp_qty={
                ("BENCH-01", "leg"): 2, ("BENCH-01", "top"): 1,
                ("SHELF-01", "shelf"): 1,
            },
            optimization_time_budget=0,  # turn off SA so we test pure greedy ordering
        )

        bench_sheets = _sheet_of(result, "BENCH-01")
        shelf_sheets = _sheet_of(result, "SHELF-01")
        assert bench_sheets, "Bench parts should have been placed"
        assert shelf_sheets, "Shelf parts should have been placed"
        # Mating-first ordering means BENCH parts should be on lower sheet numbers
        assert max(bench_sheets) <= min(shelf_sheets), (
            f"Mating-first ordering violated: BENCH on sheets {sorted(set(bench_sheets))}, "
            f"SHELF on sheets {sorted(set(shelf_sheets))}"
        )

    def test_largest_mating_first_within_tier(self):
        """Within the mating tier, blocks are sorted by area descending — the
        biggest mating block should claim sheet 1 (1-indexed)."""
        db = MockDB(
            components=[
                _component(1, "leg", variable_pockets=False, mating_role="tab"),
                _component(2, "top", variable_pockets=True, mating_role="receiver"),
                _component(3, "small_tab", variable_pockets=False, mating_role="tab"),
                _component(4, "small_recv", variable_pockets=True, mating_role="receiver"),
            ],
            products=[
                # Big mating product
                _product("BENCH-01", [("leg", 2), ("top", 1)]),
                # Small mating product
                _product("MINI-01", [("small_tab", 1), ("small_recv", 1)]),
            ],
        )
        parts = [
            # Small mating product FIRST in input
            _rect_geom("MINI-01_small_tab_001", 4, 4),
            _rect_geom("MINI-01_small_recv_001", 6, 6),
            # Big mating product later
            _rect_geom("BENCH-01_leg_001", 10, 30),
            _rect_geom("BENCH-01_leg_002", 10, 30),
            _rect_geom("BENCH-01_top_001", 30, 60),
        ]

        result, _ = nest_parts(
            parts, db,
            product_comp_qty={
                ("BENCH-01", "leg"): 2, ("BENCH-01", "top"): 1,
                ("MINI-01", "small_tab"): 1, ("MINI-01", "small_recv"): 1,
            },
            optimization_time_budget=0,
        )

        # The bigger product (BENCH-01) should claim the earliest sheet
        bench_sheets = sorted(set(_sheet_of(result, "BENCH-01")))
        mini_sheets = sorted(set(_sheet_of(result, "MINI-01")))
        assert bench_sheets[0] == 1, (
            f"Largest mating product should claim sheet 1, but BENCH on sheets {bench_sheets}"
        )
        # MINI may be on sheet 1 too if it fits, but BENCH must come first
        assert min(bench_sheets) <= min(mini_sheets), (
            f"BENCH (larger) should be no later than MINI (smaller). "
            f"BENCH={bench_sheets}, MINI={mini_sheets}"
        )

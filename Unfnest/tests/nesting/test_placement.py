"""Tests for Layer 2: BLFPlacer — placement correctness."""
from __future__ import annotations

import pytest

from src.nesting.placement import BLFPlacer, Placement
from src.enrichment import EnrichedPart
from src.dxf_loader import PartGeometry, BoundingBox


def _make_part(part_id: str, w: float, h: float, area: float = None) -> EnrichedPart:
    """Create a mock EnrichedPart with a rectangular polygon."""
    hw, hh = w / 2, h / 2
    polygon = [(-hw, -hh), (hw, -hh), (hw, hh), (-hw, hh)]
    if area is None:
        area = w * h
    geom = PartGeometry(
        filename=f"{part_id}.dxf",
        polygons=[polygon],
        bounding_box=BoundingBox(min_x=-hw, min_y=-hh, max_x=hw, max_y=hh),
    )
    return EnrichedPart(
        part_id=part_id,
        geometry=geom,
        polygon=polygon,
        area=area,
        component_id=0,
        component_name=part_id,
        product_sku=None,
        variable_pockets=False,
        mating_role="neutral",
    )


@pytest.fixture
def placer():
    return BLFPlacer(
        sheet_w=48.0, sheet_h=96.0,
        spacing=0.75, edge_margin=0.75,
        rotation_count=4,
    )


class TestGreedyBLF:
    def test_single_rectangle(self, placer):
        """One rectangle should be placed on one sheet."""
        part = _make_part("rect1", 10, 20)
        sheets, failed = placer.greedy_blf([part])

        assert len(sheets) == 1
        assert len(failed) == 0
        assert sheets[0].part_count == 1

    def test_two_rectangles(self, placer):
        """Two rectangles should fit on one sheet."""
        parts = [
            _make_part("rect1", 10, 20),
            _make_part("rect2", 10, 20),
        ]
        sheets, failed = placer.greedy_blf(parts)

        assert len(failed) == 0
        total_placed = sum(s.part_count for s in sheets)
        assert total_placed == 2

    def test_multiple_small_parts(self, placer):
        """Many small parts should fit on fewer sheets than one-per-sheet."""
        parts = [_make_part(f"small_{i}", 5, 5) for i in range(20)]
        sheets, failed = placer.greedy_blf(parts)

        assert len(failed) == 0
        total_placed = sum(s.part_count for s in sheets)
        assert total_placed == 20
        # 20 parts of 5x5=25 sq in each = 500 sq in total
        # Sheet = 48*96 = 4608 sq in → should fit on 1 sheet
        assert len(sheets) <= 2

    def test_overflow_creates_new_sheet(self, placer):
        """Parts that fill a sheet should overflow to a new sheet."""
        # Each part is 20x40 = 800 sq in. Sheet is 4608 sq in.
        # With spacing and margins, about 3-4 should fit per sheet.
        parts = [_make_part(f"big_{i}", 20, 40) for i in range(8)]
        sheets, failed = placer.greedy_blf(parts)

        assert len(failed) == 0
        assert len(sheets) >= 2
        total_placed = sum(s.part_count for s in sheets)
        assert total_placed == 8

    def test_oversized_part_fails(self, placer):
        """A part larger than the sheet should fail."""
        part = _make_part("huge", 100, 200)
        sheets, failed = placer.greedy_blf([part])

        assert len(failed) == 1
        assert failed[0].part_id == "huge"

    def test_max_sheets_respected(self, placer):
        """max_sheets limit should be respected."""
        parts = [_make_part(f"big_{i}", 20, 40) for i in range(20)]
        sheets, failed = placer.greedy_blf(parts, max_sheets=2)

        assert len(sheets) <= 2


class TestSheetState:
    def test_utilization(self, placer):
        """Utilization should be computed correctly."""
        sheet = placer.new_sheet()
        assert sheet.utilization == 0.0

        # Place a part manually
        part = _make_part("test", 10, 10, area=100.0)
        sheet.placed.append(Placement(part=part, x=0, y=0, rotation=0))
        assert abs(sheet.utilization - (100.0 / (48 * 96) * 100)) < 0.01

    def test_to_nested_sheet(self, placer):
        """to_nested_sheet should produce valid NestedSheet."""
        sheet = placer.new_sheet()
        part = _make_part("test", 10, 10, area=100.0)
        sheet.placed.append(Placement(part=part, x=5.0, y=5.0, rotation=0))

        ns = sheet.to_nested_sheet(sheet_number=1)
        assert ns.sheet_number == 1
        assert len(ns.parts) == 1
        assert ns.parts[0].part_id == "test"
        assert ns.parts[0].x == 5.0

    def test_to_metadata(self, placer):
        """to_metadata should produce valid SheetMetadata."""
        sheet = placer.new_sheet(bundle_group=3)
        meta = sheet.to_metadata()
        assert meta.bundle_group == 3


class TestRotations:
    def test_rotation_picks_best(self, placer):
        """BLF should try rotations and pick the best position."""
        # A tall narrow piece might pack better rotated 90°
        part = _make_part("narrow", 5, 40)
        sheets, failed = placer.greedy_blf([part])
        assert len(failed) == 0
        assert sheets[0].placed[0].rotation in placer.rotations


class TestCallbacks:
    def test_progress_callback(self, placer):
        """Progress callback should be called for each placed part."""
        calls = []
        parts = [_make_part(f"p{i}", 5, 5) for i in range(3)]
        placer.greedy_blf(
            parts,
            progress_callback=lambda c, t: calls.append((c, t)),
        )
        assert len(calls) == 3

    def test_cancel_check(self, placer):
        """Cancel check should stop placement early."""
        cancel_after = [2]

        def cancel():
            cancel_after[0] -= 1
            return cancel_after[0] <= 0

        parts = [_make_part(f"p{i}", 5, 5) for i in range(10)]
        sheets, failed = placer.greedy_blf(parts, cancel_check=cancel)

        total_placed = sum(s.part_count for s in sheets)
        assert total_placed < 10

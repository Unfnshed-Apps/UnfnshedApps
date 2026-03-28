"""Tests for Layer 1: RasterEngine — collision detection correctness."""
from __future__ import annotations

import math
import pytest
import numpy as np

from src.nesting.geometry import RasterEngine


@pytest.fixture
def engine():
    """Standard full-resolution engine for a 48x96" sheet."""
    return RasterEngine(
        sheet_w=48.0, sheet_h=96.0,
        resolution=0.25, spacing=0.75, edge_margin=0.75,
    )


@pytest.fixture
def fast_engine():
    """Fast-resolution engine for quick tests."""
    return RasterEngine(
        sheet_w=48.0, sheet_h=96.0,
        resolution=1.0, spacing=0.75, edge_margin=0.75,
    )


def _rect_polygon(w, h, cx=0, cy=0):
    """Create a rectangle polygon centered at (cx, cy)."""
    hw, hh = w / 2, h / 2
    return [
        (cx - hw, cy - hh),
        (cx + hw, cy - hh),
        (cx + hw, cy + hh),
        (cx - hw, cy + hh),
    ]


def _triangle_polygon(base, height, cx=0, cy=0):
    """Create a triangle polygon."""
    return [
        (cx - base / 2, cy - height / 3),
        (cx + base / 2, cy - height / 3),
        (cx, cy + 2 * height / 3),
    ]


class TestRasterize:
    def test_rectangle_dimensions(self, engine):
        """Rasterize a rectangle and verify dimensions roughly match."""
        poly = _rect_polygon(10, 20)
        raster, *_ = engine.rasterize(poly, rotation=0)

        # Expected raster size: (piece_size + 2*buffer) / resolution
        buffer = engine.piece_buffer  # spacing/2 + R/2
        expected_w = math.ceil((10 + 2 * buffer) / engine.resolution)
        expected_h = math.ceil((20 + 2 * buffer) / engine.resolution)

        # Allow ±2 cells tolerance for rasterization
        assert abs(raster.shape[1] - expected_w) <= 2
        assert abs(raster.shape[0] - expected_h) <= 2

    def test_rectangle_area(self, engine):
        """Rasterized area roughly matches analytical buffered area."""
        poly = _rect_polygon(10, 20)
        raster, *_ = engine.rasterize(poly, rotation=0)

        raster_area = np.sum(raster) * (engine.resolution ** 2)
        # Analytical buffered area ≈ (10 + 2*buf) * (20 + 2*buf) roughly
        # (corners are rounded from buffer, so actual < rectangular)
        buf = engine.piece_buffer
        max_area = (10 + 2 * buf) * (20 + 2 * buf)
        assert raster_area > 0
        assert raster_area <= max_area * 1.1  # Some rasterization padding OK

    def test_triangle_area(self, engine):
        """Rasterized triangle area roughly matches analytical."""
        poly = _triangle_polygon(12, 18)
        raster, *_ = engine.rasterize(poly, rotation=0)

        raster_area = np.sum(raster) * (engine.resolution ** 2)
        analytical_area = 0.5 * 12 * 18  # 108 sq in
        # Buffered area will be larger; just check it's reasonable
        assert raster_area > analytical_area * 0.8
        assert raster_area < analytical_area * 3.0

    def test_rotation_changes_raster(self, engine):
        """Rotating a non-square piece changes the raster shape."""
        poly = _rect_polygon(10, 30)
        r0, *_ = engine.rasterize(poly, rotation=0)
        r90, *_ = engine.rasterize(poly, rotation=90)

        # 90° rotation should roughly swap width and height
        assert abs(r0.shape[0] - r90.shape[1]) <= 4
        assert abs(r0.shape[1] - r90.shape[0]) <= 4

    def test_raster_is_binary(self, engine):
        """Raster values should be 0 or 1."""
        poly = _rect_polygon(5, 5)
        raster, *_ = engine.rasterize(poly)
        unique = np.unique(raster)
        assert set(unique).issubset({0, 1})


class TestFeasibilityMap:
    def test_empty_sheet_all_valid(self, fast_engine):
        """On an empty sheet, a small piece should fit at many positions."""
        grid = fast_engine.empty_grid()
        poly = _rect_polygon(5, 5)
        raster, *_ = fast_engine.rasterize(poly)

        fmap = fast_engine.feasibility_map(grid, raster)
        valid_count = np.sum(fmap < 0.5)
        assert valid_count > 0, "Small piece should fit on empty sheet"

    def test_overlapping_pieces_detected(self, fast_engine):
        """Placing a piece then checking feasibility should block the same spot."""
        grid = fast_engine.empty_grid()
        poly = _rect_polygon(10, 10)
        raster, *_ = fast_engine.rasterize(poly)

        # Find BLF position and place
        fmap = fast_engine.feasibility_map(grid, raster)
        pos = fast_engine.find_blf_position(fmap)
        assert pos is not None

        row, col = pos
        fast_engine.place_on_grid(grid, raster, row, col)

        # Now the same position should be blocked
        fmap2 = fast_engine.feasibility_map(grid, raster)
        if fmap2.shape[0] > row and fmap2.shape[1] > col:
            assert fmap2[row, col] >= 0.5, "Occupied position should be blocked"

    def test_non_overlapping_both_fit(self, fast_engine):
        """Two small pieces should both find valid positions."""
        grid = fast_engine.empty_grid()
        poly = _rect_polygon(5, 5)
        raster, *_ = fast_engine.rasterize(poly)

        # Place first piece
        fmap1 = fast_engine.feasibility_map(grid, raster)
        pos1 = fast_engine.find_blf_position(fmap1)
        assert pos1 is not None
        fast_engine.place_on_grid(grid, raster, pos1[0], pos1[1])

        # Second piece should still fit
        fmap2 = fast_engine.feasibility_map(grid, raster)
        pos2 = fast_engine.find_blf_position(fmap2)
        assert pos2 is not None
        assert pos2 != pos1, "Second piece should be at different position"


class TestBLFPosition:
    def test_single_piece_bottom_left(self, fast_engine):
        """First piece should go to bottom-left corner (accounting for edge margin)."""
        grid = fast_engine.empty_grid()
        poly = _rect_polygon(5, 5)
        raster, *_ = fast_engine.rasterize(poly)

        fmap = fast_engine.feasibility_map(grid, raster)
        pos = fast_engine.find_blf_position(fmap)

        assert pos is not None
        row, col = pos
        # Should be near bottom-left (small row and col values)
        assert row < fast_engine.grid_h // 2
        assert col < fast_engine.grid_w // 2

    def test_piece_too_large_returns_none(self, fast_engine):
        """A piece larger than the sheet should return None."""
        grid = fast_engine.empty_grid()
        # Make a piece larger than the sheet
        poly = _rect_polygon(100, 200)
        raster, *_ = fast_engine.rasterize(poly)

        if not fast_engine.piece_fits_on_sheet(raster):
            # Expected: piece doesn't fit
            pass
        else:
            fmap = fast_engine.feasibility_map(grid, raster)
            pos = fast_engine.find_blf_position(fmap)
            # Should be None since it can't fit
            assert pos is None


class TestPlaceOnGrid:
    def test_grid_updated(self, fast_engine):
        """Placing a piece should change the grid."""
        grid = fast_engine.empty_grid()
        boundary_sum = np.sum(grid)

        poly = _rect_polygon(10, 10)
        raster, *_ = fast_engine.rasterize(poly)

        fmap = fast_engine.feasibility_map(grid, raster)
        pos = fast_engine.find_blf_position(fmap)
        assert pos is not None

        fast_engine.place_on_grid(grid, raster, pos[0], pos[1])
        assert np.sum(grid) > boundary_sum


class TestGridToInches:
    def test_origin(self, engine):
        """(0,0) should map to (0.0, 0.0)."""
        x, y = engine.grid_to_inches(0, 0)
        assert x == 0.0
        assert y == 0.0

    def test_conversion(self, engine):
        """Known grid position should map to correct inches."""
        x, y = engine.grid_to_inches(4, 8)
        assert abs(x - 8 * 0.25) < 1e-6
        assert abs(y - 4 * 0.25) < 1e-6


class TestPieceFits:
    def test_small_piece_fits(self, engine):
        """A small piece should fit on the sheet."""
        poly = _rect_polygon(10, 10)
        raster, *_ = engine.rasterize(poly)
        assert engine.piece_fits_on_sheet(raster)

    def test_huge_piece_doesnt_fit(self, engine):
        """A piece larger than the sheet shouldn't fit."""
        poly = _rect_polygon(100, 200)
        raster, *_ = engine.rasterize(poly)
        assert not engine.piece_fits_on_sheet(raster)

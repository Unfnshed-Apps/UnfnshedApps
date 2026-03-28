"""
Layer 1: Raster-based collision detection via FFT convolution.

Rasterizes polygons onto numpy grids and uses scipy FFT cross-correlation
to compute feasibility maps — checking ALL candidate positions simultaneously
in O(N log N) time.
"""
from __future__ import annotations

import math
from typing import Optional

import numpy as np
from PIL import Image, ImageDraw
from scipy.signal import fftconvolve
from shapely.geometry import Polygon as ShapelyPolygon
from shapely import affinity


class RasterEngine:
    """Raster-based collision detection engine.

    Two resolution modes:
      - Full (default R=0.25"): 192×384 grid for a 48×96" sheet. Used for
        greedy BLF and final placement verification.
      - Fast (R=1.0"): 48×96 grid. Used for SA evaluation (~50x faster).
    """

    def __init__(
        self,
        sheet_w: float,
        sheet_h: float,
        resolution: float,
        spacing: float,
        edge_margin: float,
    ):
        self.sheet_w = sheet_w
        self.sheet_h = sheet_h
        self.resolution = resolution
        self.spacing = spacing
        self.edge_margin = edge_margin

        # Grid dimensions
        self.grid_w = math.ceil(sheet_w / resolution)
        self.grid_h = math.ceil(sheet_h / resolution)

        # Buffer applied to each piece: spacing/2 + R/2 for rasterization error
        self.piece_buffer = spacing / 2.0 + resolution / 2.0

        # Usable area inset: edge_margin - spacing/2 ensures the gap from
        # sheet edge to original piece outline = edge_margin
        self.usable_inset = max(0.0, edge_margin - spacing / 2.0)
        inset_cells = math.ceil(self.usable_inset / resolution)

        # Pre-build the sheet boundary mask (1 = forbidden zone at edges)
        self._boundary = np.zeros((self.grid_h, self.grid_w), dtype=np.uint8)
        if inset_cells > 0:
            self._boundary[:inset_cells, :] = 1
            self._boundary[-inset_cells:, :] = 1
            self._boundary[:, :inset_cells] = 1
            self._boundary[:, -inset_cells:] = 1

    def empty_grid(self) -> np.ndarray:
        """Return a fresh sheet grid with boundary mask applied."""
        return self._boundary.copy()

    def rasterize(
        self,
        polygon_pts: list[tuple[float, float]],
        rotation: float = 0.0,
    ) -> tuple[np.ndarray, float, float, float, float]:
        """Rasterize a polygon at a given rotation.

        Rotation is applied around the ORIGIN (0,0) to match the rendering
        code in sheet_preview_item.py and dxf_output.py, which does:
          1. Rotate points around (0,0)
          2. Subtract rotated bbox min (normalize to positive quadrant)
          3. Add (part.x, part.y)

        Returns:
            (raster, rot_min_x, rot_min_y, buf_min_x, buf_min_y)
            - raster: 2D uint8 array with piece footprint
            - rot_min_x/rot_min_y: bbox min of ROTATED unbuffered polygon
            - buf_min_x/buf_min_y: bbox min of BUFFERED polygon (raster origin)
        """
        poly = ShapelyPolygon(polygon_pts)
        if not poly.is_valid:
            poly = poly.buffer(0)

        # Apply rotation around ORIGIN (0,0) — matching the rendering code
        if rotation != 0.0:
            poly = affinity.rotate(poly, rotation, origin=(0, 0), use_radians=False)

        # Record rotated (unbuffered) bbox min — needed for coordinate mapping
        rot_minx, rot_miny = poly.bounds[0], poly.bounds[1]

        # Buffer for spacing
        buffered = poly.buffer(self.piece_buffer)
        if buffered.is_empty:
            return np.zeros((1, 1), dtype=np.uint8), 0.0, 0.0, 0.0, 0.0

        # Get bounding box of buffered polygon
        minx, miny, maxx, maxy = buffered.bounds

        # Compute raster dimensions
        rw = max(1, math.ceil((maxx - minx) / self.resolution))
        rh = max(1, math.ceil((maxy - miny) / self.resolution))

        # Convert polygon coords to pixel space for PIL rasterization
        if buffered.geom_type == 'MultiPolygon':
            # Take the largest polygon from a potential multi-polygon result
            largest = max(buffered.geoms, key=lambda g: g.area)
            coords = list(largest.exterior.coords)
        else:
            coords = list(buffered.exterior.coords)

        pixel_coords = [
            ((x - minx) / self.resolution, (y - miny) / self.resolution)
            for x, y in coords
        ]

        # Rasterize with PIL (fast C-based scanline fill)
        img = Image.new('L', (rw, rh), 0)
        draw = ImageDraw.Draw(img)
        draw.polygon(pixel_coords, fill=1)
        raster = np.array(img, dtype=np.uint8)

        # PIL images are (width, height) but numpy is (rows, cols)
        # PIL Image.new('L', (w, h)) -> np.array shape is (h, w) which is correct
        return raster, rot_minx, rot_miny, minx, miny

    def feasibility_map(
        self,
        sheet_grid: np.ndarray,
        piece_raster: np.ndarray,
    ) -> np.ndarray:
        """Compute feasibility map via FFT cross-correlation.

        Returns a 2D array where 0 means the piece fits at that position
        and >0 means overlap. The array shape is
        (grid_h - piece_h + 1, grid_w - piece_w + 1).
        """
        # Cross-correlation: flip piece and convolve
        # fftconvolve with mode='valid' gives positions where piece fully fits
        result = fftconvolve(
            sheet_grid.astype(np.float32),
            piece_raster[::-1, ::-1].astype(np.float32),
            mode='valid',
        )
        return result

    def find_blf_position(
        self,
        fmap: np.ndarray,
        threshold: float = 0.5,
    ) -> Optional[tuple[int, int]]:
        """Find the bottom-left-fill position in a feasibility map.

        Scans for the first zero entry (below threshold), sweeping
        bottom-to-top (row 0 = bottom), then left-to-right.

        Returns (row, col) or None if no valid position exists.
        """
        if fmap.size == 0:
            return None

        # Find all valid positions (where convolution result < threshold)
        valid = fmap < threshold

        if not np.any(valid):
            return None

        # Get indices of valid positions
        rows, cols = np.where(valid)

        # BLF: lowest row first (bottom), then leftmost column
        # Row 0 = bottom of sheet
        # Find minimum row, then among those, minimum col
        min_row = rows.min()
        mask = rows == min_row
        min_col = cols[mask].min()

        return (int(min_row), int(min_col))

    def place_on_grid(
        self,
        sheet_grid: np.ndarray,
        piece_raster: np.ndarray,
        row: int,
        col: int,
    ) -> np.ndarray:
        """OR piece raster onto sheet grid at the given position.

        Returns the updated grid (modified in-place for efficiency).
        """
        ph, pw = piece_raster.shape
        sheet_grid[row:row + ph, col:col + pw] |= piece_raster
        return sheet_grid

    def grid_to_inches(self, row: int, col: int) -> tuple[float, float]:
        """Convert grid position (row, col) to real-world coordinates (x, y).

        Row 0 = bottom of sheet (y=0), Col 0 = left of sheet (x=0).
        """
        x = col * self.resolution
        y = row * self.resolution
        return (x, y)

    def piece_fits_on_sheet(self, piece_raster: np.ndarray) -> bool:
        """Quick check: can this piece physically fit on a blank sheet?"""
        ph, pw = piece_raster.shape
        return ph <= self.grid_h and pw <= self.grid_w

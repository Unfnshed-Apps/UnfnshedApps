"""
Layer 2: Bottom-Left Fill (BLF) placement heuristic.

Places pieces one at a time using feasibility maps from the RasterEngine.
For each piece, tries all candidate rotations and picks the one giving
the best (lowest y, then leftmost x) position.

Coordinate convention (matching sheet_preview_item.py / dxf_output.py):
  The rendering code does:
    1. Rotate polygon points around ORIGIN (0,0)
    2. Compute rotated bbox min (rot_min_x, rot_min_y)
    3. final_x = (rotated_x - rot_min_x) + part.x
    4. final_y = (rotated_y - rot_min_y) + part.y
  So part.x is where the rotated polygon's normalized min-corner sits on the sheet.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional, Callable

import numpy as np
from .geometry import RasterEngine
from ..enrichment import EnrichedPart, _polygon_area
from ..nesting_models import PlacedPart, NestedSheet, SheetMetadata


# Standard rotation presets (degrees)
ROTATION_PRESETS = {
    4: [0, 90, 180, 270],
    8: [0, 45, 90, 135, 180, 225, 270, 315],
    16: [float(i * 22.5) for i in range(16)],
    24: [float(i * 15) for i in range(24)],
}


@dataclass
class Placement:
    """A single piece placement record."""
    part: EnrichedPart
    x: float  # Real-world X coordinate (for rendering: rotated bbox min on sheet)
    y: float  # Real-world Y coordinate
    rotation: float  # Degrees


@dataclass
class PlacementResult:
    """Result from _find_best_placement — grid position and raster metadata."""
    row: int
    col: int
    rotation: float
    raster: np.ndarray
    rot_min_x: float
    rot_min_y: float
    buf_min_x: float
    buf_min_y: float


@dataclass
class SheetState:
    """Mutable state of a sheet during BLF packing."""
    grid: np.ndarray  # Occupancy raster (full resolution)
    fast_grid: Optional[np.ndarray]  # Occupancy raster (low resolution, for SA)
    placed: list[Placement] = field(default_factory=list)
    bundle_group: Optional[int] = None
    _sheet_w: float = 48.0
    _sheet_h: float = 96.0

    @property
    def utilization(self) -> float:
        """Sheet utilization percentage based on placed part areas."""
        if not self.placed:
            return 0.0
        total_area = sum(p.part.area for p in self.placed)
        sheet_area = self._sheet_w * self._sheet_h
        return (total_area / sheet_area) * 100.0

    @property
    def part_count(self) -> int:
        return len(self.placed)

    @property
    def has_variable_pockets(self) -> bool:
        return any(p.part.variable_pockets for p in self.placed)

    def to_nested_sheet(self, sheet_number: int = 0) -> NestedSheet:
        """Convert to output NestedSheet format with full layer geometries."""
        placed_parts = []
        for p in self.placed:
            placed_parts.append(PlacedPart(
                part_id=p.part.part_id,
                source_filename=p.part.geometry.filename,
                x=p.x,
                y=p.y,
                rotation=p.rotation,
                polygon=p.part.polygon,
                outline_polygons=p.part.geometry.outline_polygons,
                pocket_polygons=p.part.geometry.pocket_polygons,
                internal_polygons=p.part.geometry.internal_polygons,
                outline_entities=p.part.geometry.outline_entities,
                pocket_entities=p.part.geometry.pocket_entities,
                internal_entities=p.part.geometry.internal_entities,
            ))
        return NestedSheet(
            sheet_number=sheet_number,
            width=self._sheet_w,
            height=self._sheet_h,
            parts=placed_parts,
        )

    def to_metadata(self) -> SheetMetadata:
        """Convert to SheetMetadata format."""
        return SheetMetadata(
            has_variable_pockets=self.has_variable_pockets,
            bundle_group=self.bundle_group,
        )


def _compute_part_xy(
    grid_x: float, grid_y: float,
    rot_min_x: float, rot_min_y: float,
    buf_min_x: float, buf_min_y: float,
) -> tuple[float, float]:
    """Compute PlacedPart (x, y) from grid placement and raster metadata.

    The rendering code does:
      screen_x = (rotated_point_x - rot_min_x) + part.x

    The raster pixel (0,0) is at buf_min on the sheet when placed at grid pos.
    A rotated point at (rx, ry) has raster pixel at ((rx - buf_min_x)/R, ...).
    On the sheet it ends up at grid_x + rx - buf_min_x.
    Setting equal: grid_x + rx - buf_min_x = rx - rot_min_x + part.x
    => part.x = grid_x - buf_min_x + rot_min_x
    """
    part_x = grid_x - buf_min_x + rot_min_x
    part_y = grid_y - buf_min_y + rot_min_y
    return part_x, part_y


class BLFPlacer:
    """Bottom-Left Fill placement engine.

    Uses RasterEngine for collision detection. Supports two modes:
      - Full resolution: for greedy BLF initial solution and final verification
      - Fast resolution: for SA evaluation (~50x faster)
    """

    FULL_RESOLUTION = 0.25  # inches per cell
    FAST_RESOLUTION = 1.0   # inches per cell

    def __init__(
        self,
        sheet_w: float = 48.0,
        sheet_h: float = 96.0,
        spacing: float = 0.75,
        edge_margin: float = 0.75,
        rotation_count: int = 8,
    ):
        self.sheet_w = sheet_w
        self.sheet_h = sheet_h
        self.spacing = spacing
        self.edge_margin = edge_margin
        self.rotations = ROTATION_PRESETS.get(
            rotation_count,
            [float(i * (360.0 / rotation_count)) for i in range(rotation_count)],
        )

        # Full-resolution engine for greedy BLF + final placement
        self.full_engine = RasterEngine(
            sheet_w, sheet_h, self.FULL_RESOLUTION, spacing, edge_margin,
        )

        # Fast-resolution engine for SA evaluation
        self.fast_engine = RasterEngine(
            sheet_w, sheet_h, self.FAST_RESOLUTION, spacing, edge_margin,
        )

    def new_sheet(self, bundle_group: int = None) -> SheetState:
        """Create a fresh empty sheet."""
        return SheetState(
            grid=self.full_engine.empty_grid(),
            fast_grid=self.fast_engine.empty_grid(),
            bundle_group=bundle_group,
            _sheet_w=self.sheet_w,
            _sheet_h=self.sheet_h,
        )

    def greedy_blf(
        self,
        parts: list[EnrichedPart],
        bundle_group: int = None,
        max_sheets: int = 100,
        live_callback: Callable = None,
        cancel_check: Callable = None,
        progress_callback: Callable[[int, int], None] = None,
        progress_offset: int = 0,
        total_parts: int = None,
    ) -> tuple[list[SheetState], list[EnrichedPart]]:
        """Run greedy BLF placement.

        For each part (ordered by the caller, typically area descending):
          1. Try all rotation angles
          2. For each rotation, compute feasibility map via FFT convolution
          3. Pick the rotation giving the best BLF position (lowest y, leftmost x)
          4. Place on current sheet; if no position, open a new sheet

        Returns:
            (sheets, failed) — sheets with placements, and parts that couldn't fit
        """
        sheets: list[SheetState] = []
        failed: list[EnrichedPart] = []
        engine = self.full_engine
        placed_count = progress_offset

        if total_parts is None:
            total_parts = len(parts)

        for part in parts:
            if cancel_check and cancel_check():
                break

            placed = self._try_place_on_sheets(part, sheets, engine, max_sheets,
                                                bundle_group)
            if placed:
                placed_count += 1
                if live_callback:
                    live_callback(sheets)
                if progress_callback:
                    progress_callback(placed_count, total_parts)
            else:
                failed.append(part)

        return sheets, failed

    def _try_place_on_sheets(
        self,
        part: EnrichedPart,
        sheets: list[SheetState],
        engine: RasterEngine,
        max_sheets: int,
        bundle_group: int = None,
        start_from: int = 0,
        end_before: int = None,
    ) -> bool:
        """Try to place a part on existing sheets, creating a new one if needed.

        Args:
            start_from: Index into sheets to start searching from.
            end_before: Index to stop searching at (exclusive). None = all sheets.
                Used to keep receivers within 1 sheet of their tabs.
        """
        # Try existing sheets in the allowed range
        for sheet in sheets[start_from:end_before]:
            result = self._find_best_placement(part, sheet.grid, engine)
            if result is not None:
                self._commit_placement(part, sheet, result, engine)
                return True

        # Create new sheet if under limit
        if len(sheets) < max_sheets:
            sheet = self.new_sheet(bundle_group)
            result = self._find_best_placement(part, sheet.grid, engine)
            if result is not None:
                sheets.append(sheet)
                self._commit_placement(part, sheet, result, engine)
                return True

        return False

    def _find_best_placement(
        self,
        part: EnrichedPart,
        grid: np.ndarray,
        engine: RasterEngine,
    ) -> Optional[PlacementResult]:
        """Find the best BLF position across all rotations.

        Returns a PlacementResult or None.
        """
        best: Optional[PlacementResult] = None

        for rotation in self.rotations:
            raster, rot_min_x, rot_min_y, buf_min_x, buf_min_y = engine.rasterize(
                part.polygon, rotation,
            )

            if not engine.piece_fits_on_sheet(raster):
                continue

            fmap = engine.feasibility_map(grid, raster)
            pos = engine.find_blf_position(fmap)

            if pos is None:
                continue

            row, col = pos

            # BLF criterion: prefer lowest row, then leftmost col
            if best is None or (row, col) < (best.row, best.col):
                best = PlacementResult(
                    row=row, col=col, rotation=rotation, raster=raster,
                    rot_min_x=rot_min_x, rot_min_y=rot_min_y,
                    buf_min_x=buf_min_x, buf_min_y=buf_min_y,
                )

        return best

    def _commit_placement(
        self,
        part: EnrichedPart,
        sheet: SheetState,
        result: PlacementResult,
        engine: RasterEngine,
    ):
        """Record a placement on a sheet, updating grids."""
        # Update full-resolution grid
        engine.place_on_grid(sheet.grid, result.raster, result.row, result.col)

        # Convert grid position to inches
        grid_x, grid_y = engine.grid_to_inches(result.row, result.col)

        # Compute PlacedPart coordinates matching the rendering pipeline
        part_x, part_y = _compute_part_xy(
            grid_x, grid_y, result.rot_min_x, result.rot_min_y,
            result.buf_min_x, result.buf_min_y,
        )

        # Also update fast grid for SA evaluation (approximate position)
        self._sync_fast_grid(sheet, part.polygon, result.rotation)

        sheet.placed.append(Placement(
            part=part,
            x=part_x,
            y=part_y,
            rotation=result.rotation,
        ))

    def _sync_fast_grid(self, sheet: SheetState, polygon, rotation: float):
        """Update the fast grid to approximately match a full-res placement."""
        if sheet.fast_grid is None:
            return
        fr, _, _, _, _ = self.fast_engine.rasterize(polygon, rotation)
        if self.fast_engine.piece_fits_on_sheet(fr):
            ff = self.fast_engine.feasibility_map(sheet.fast_grid, fr)
            fp = self.fast_engine.find_blf_position(ff)
            if fp is not None:
                self.fast_engine.place_on_grid(sheet.fast_grid, fr, fp[0], fp[1])

    def _rasterize_and_place(
        self,
        part: EnrichedPart,
        rotation: float,
        sheets: list[SheetState],
        engine: RasterEngine,
        grid_attr: str,
        max_sheets: int,
        bundle_group: int = None,
        sync_fast_grid: bool = False,
    ) -> Optional[SheetState]:
        """Rasterize a part and place it on the first available sheet.

        Returns the sheet it was placed on, or None if it couldn't fit.
        Creates a new sheet if needed (up to max_sheets).

        Args:
            grid_attr: Which grid to use on SheetState ("grid" or "fast_grid").
            sync_fast_grid: Whether to also update the fast grid after placement.
        """
        raster, rot_min_x, rot_min_y, buf_min_x, buf_min_y = engine.rasterize(
            part.polygon, rotation,
        )

        if not engine.piece_fits_on_sheet(raster):
            return None

        # Try existing sheets
        for sheet in sheets:
            grid = getattr(sheet, grid_attr)
            fmap = engine.feasibility_map(grid, raster)
            pos = engine.find_blf_position(fmap)
            if pos is not None:
                row, col = pos
                engine.place_on_grid(grid, raster, row, col)
                gx, gy = engine.grid_to_inches(row, col)
                px, py = _compute_part_xy(gx, gy, rot_min_x, rot_min_y,
                                          buf_min_x, buf_min_y)
                if sync_fast_grid:
                    self._sync_fast_grid(sheet, part.polygon, rotation)
                sheet.placed.append(Placement(
                    part=part, x=px, y=py, rotation=rotation,
                ))
                return sheet

        # Create new sheet if under limit
        if len(sheets) < max_sheets:
            sheet = self.new_sheet(bundle_group)
            grid = getattr(sheet, grid_attr)
            fmap = engine.feasibility_map(grid, raster)
            pos = engine.find_blf_position(fmap)
            if pos is not None:
                row, col = pos
                engine.place_on_grid(grid, raster, row, col)
                gx, gy = engine.grid_to_inches(row, col)
                px, py = _compute_part_xy(gx, gy, rot_min_x, rot_min_y,
                                          buf_min_x, buf_min_y)
                if sync_fast_grid:
                    self._sync_fast_grid(sheet, part.polygon, rotation)
                sheet.placed.append(Placement(
                    part=part, x=px, y=py, rotation=rotation,
                ))
                sheets.append(sheet)
                return sheet

        return None

    def _try_place_all(
        self,
        parts: list[EnrichedPart],
        sheet: SheetState,
        engine: RasterEngine,
    ) -> Optional[list[PlacementResult]]:
        """Dry-run: try placing all parts on a sheet using a grid copy.

        Returns list of PlacementResults if ALL parts fit, or None.
        """
        grid_copy = sheet.grid.copy()
        results = []
        for part in parts:
            result = self._find_best_placement(part, grid_copy, engine)
            if result is None:
                return None
            engine.place_on_grid(grid_copy, result.raster, result.row, result.col)
            results.append(result)
        return results

    def greedy_blf_blocks(
        self,
        blocks: list[list[EnrichedPart]],
        loose_parts: list[EnrichedPart] = None,
        max_sheets: int = 100,
        live_callback: Callable = None,
        cancel_check: Callable = None,
        progress_callback: Callable[[int, int], None] = None,
        total_parts: int = None,
    ) -> tuple[list[SheetState], list[EnrichedPart]]:
        """Block-aware greedy BLF placement.

        Each block's tab parts are placed atomically on the same sheet.
        Receivers/neutrals go on the same sheet if they fit, otherwise next.
        Loose parts fill remaining gaps after all blocks are placed.
        """
        sheets: list[SheetState] = []
        failed: list[EnrichedPart] = []
        engine = self.full_engine
        placed_count = 0

        if total_parts is None:
            total_parts = sum(len(b) for b in blocks) + (len(loose_parts) if loose_parts else 0)

        for block in blocks:
            if cancel_check and cancel_check():
                break

            tabs = [p for p in block if p.mating_role == "tab"]
            others = [p for p in block if p.mating_role != "tab"]

            # Find a sheet where all tabs fit (dry-run check)
            placed_sheet = None
            tab_results = None

            for sheet in sheets:
                results = self._try_place_all(tabs, sheet, engine)
                if results is not None:
                    placed_sheet = sheet
                    tab_results = results
                    break

            if placed_sheet is None and len(sheets) < max_sheets:
                sheet = self.new_sheet()
                results = self._try_place_all(tabs, sheet, engine)
                if results is not None:
                    sheets.append(sheet)
                    placed_sheet = sheet
                    tab_results = results

            if placed_sheet is None:
                failed.extend(block)
                continue

            # Commit tab placements
            for tab, result in zip(tabs, tab_results):
                self._commit_placement(tab, placed_sheet, result, engine)
                placed_count += 1
                if progress_callback:
                    progress_callback(placed_count, total_parts)

            # Place others: prefer the same sheet, fall back to next sheet only
            # (receivers must never land on a sheet before their tabs)
            tab_sheet_idx = sheets.index(placed_sheet)
            for part in others:
                result = self._find_best_placement(part, placed_sheet.grid, engine)
                if result is not None:
                    self._commit_placement(part, placed_sheet, result, engine)
                    placed_count += 1
                else:
                    placed = self._try_place_on_sheets(
                        part, sheets, engine, max_sheets,
                        start_from=tab_sheet_idx,
                        end_before=tab_sheet_idx + 2,
                    )
                    if placed:
                        placed_count += 1
                    else:
                        failed.append(part)

                if progress_callback:
                    progress_callback(placed_count, total_parts)

            if live_callback:
                live_callback(sheets)

        # Fill loose parts into remaining space
        if loose_parts:
            for part in loose_parts:
                if cancel_check and cancel_check():
                    break
                placed = self._try_place_on_sheets(
                    part, sheets, engine, max_sheets
                )
                if placed:
                    placed_count += 1
                else:
                    failed.append(part)
                if progress_callback:
                    progress_callback(placed_count, total_parts)
            if live_callback:
                live_callback(sheets)

        return sheets, failed

    def fast_blf(
        self,
        parts_with_rotations: list[tuple[EnrichedPart, float]],
        max_sheets: int = 100,
    ) -> list[SheetState]:
        """Fast BLF at low resolution for SA evaluation.

        Args:
            parts_with_rotations: Ordered list of (part, rotation_angle) tuples
            max_sheets: Maximum sheets

        Returns:
            List of SheetStates with placements
        """
        sheets: list[SheetState] = []
        for part, rotation in parts_with_rotations:
            self._rasterize_and_place(
                part, rotation, sheets, self.fast_engine, "fast_grid", max_sheets,
            )
        return sheets

    def repack_full_resolution(
        self,
        parts_with_rotations: list[tuple[EnrichedPart, float]],
        bundle_group: int = None,
        max_sheets: int = 100,
    ) -> tuple[list[SheetState], list[EnrichedPart]]:
        """Re-evaluate a solution at full resolution.

        Takes the SA-optimized ordering + rotations and packs at R=0.25".

        Returns:
            (sheets, failed) — final placement at full resolution
        """
        sheets: list[SheetState] = []
        failed: list[EnrichedPart] = []
        for part, rotation in parts_with_rotations:
            result = self._rasterize_and_place(
                part, rotation, sheets, self.full_engine, "grid", max_sheets,
                bundle_group=bundle_group, sync_fast_grid=True,
            )
            if result is None:
                failed.append(part)
        return sheets, failed

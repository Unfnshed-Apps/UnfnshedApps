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
class AtomicRecord:
    """Dry-run placement record — a PlacementResult with the part attached,
    ready for _commit_atomic_records to apply to a sheet."""
    part: EnrichedPart
    row: int
    col: int
    rotation: float
    raster: np.ndarray
    rot_min_x: float
    rot_min_y: float
    buf_min_x: float
    buf_min_y: float

    @classmethod
    def from_result(cls, part: EnrichedPart, result: PlacementResult) -> AtomicRecord:
        return cls(
            part=part,
            row=result.row, col=result.col,
            rotation=result.rotation, raster=result.raster,
            rot_min_x=result.rot_min_x, rot_min_y=result.rot_min_y,
            buf_min_x=result.buf_min_x, buf_min_y=result.buf_min_y,
        )


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
        max_sheets: int = 999999,
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
        preferred_sheets: Optional[list[SheetState]] = None,
    ) -> bool:
        """Try to place a part on existing sheets, creating a new one if needed.

        Searches rotations per sheet via `_find_best_placement`.

        Args:
            start_from: Index into `sheets` to start the general search from.
            preferred_sheets: If given, these sheets are tried BEFORE the
                general sheets[start_from:] search.
        """
        tried = set()
        if preferred_sheets:
            for sheet in preferred_sheets:
                result = self._find_best_placement(part, sheet.grid, engine)
                if result is not None:
                    self._commit_placement(part, sheet, result, engine)
                    return True
                tried.add(id(sheet))

        # Try existing sheets (from start_from onwards), skipping already-tried
        for sheet in sheets[start_from:]:
            if id(sheet) in tried:
                continue
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
        start_from: int = 0,
        preferred_sheets: Optional[list[SheetState]] = None,
    ) -> Optional[SheetState]:
        """Rasterize a part and place it on the first available sheet.

        Returns the sheet it was placed on, or None if it couldn't fit.
        Creates a new sheet if needed (up to max_sheets).

        Args:
            grid_attr: Which grid to use on SheetState ("grid" or "fast_grid").
            sync_fast_grid: Whether to also update the fast grid after placement.
            start_from: Index into `sheets` to start the general search from.
            preferred_sheets: If given, these sheets are tried BEFORE the
                general sheets[start_from:] search. Useful for "prefer these
                specific sheets but fall back to anywhere" semantics.
        """
        raster, rot_min_x, rot_min_y, buf_min_x, buf_min_y = engine.rasterize(
            part.polygon, rotation,
        )

        if not engine.piece_fits_on_sheet(raster):
            return None

        def try_sheet(sheet: SheetState) -> Optional[SheetState]:
            grid = getattr(sheet, grid_attr)
            fmap = engine.feasibility_map(grid, raster)
            pos = engine.find_blf_position(fmap)
            if pos is None:
                return None
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

        # Try preferred sheets first (if given), tracking which we tried
        tried = set()
        if preferred_sheets:
            for sheet in preferred_sheets:
                placed = try_sheet(sheet)
                if placed is not None:
                    return placed
                tried.add(id(sheet))

        # Try general sheets (skipping any already tried above)
        for sheet in sheets[start_from:]:
            if id(sheet) in tried:
                continue
            placed = try_sheet(sheet)
            if placed is not None:
                return placed

        # Create new sheet if under limit
        if len(sheets) < max_sheets:
            sheet = self.new_sheet(bundle_group)
            placed = try_sheet(sheet)
            if placed is not None:
                sheets.append(sheet)
                return sheet

        return None

    def _dry_run_atomic(
        self,
        parts_with_rotations: list[tuple[EnrichedPart, Optional[float]]],
        sheet: SheetState,
        engine: RasterEngine,
        grid_attr: str = "grid",
    ) -> Optional[list[AtomicRecord]]:
        """Dry-run atomic placement of multiple parts on one sheet.

        For each (part, rotation) tuple:
          - rotation=None  → search all rotations for the best BLF position
                              (used by greedy)
          - rotation=float → use the given rotation directly
                              (used by SA, which picks rotations itself)

        Works at either resolution via grid_attr ('grid' or 'fast_grid').

        Returns a list of AtomicRecord if all parts fit on the sheet, else
        None. Does NOT modify the sheet — caller must commit via
        `_commit_atomic_records`.
        """
        if not parts_with_rotations:
            return []
        grid_copy = getattr(sheet, grid_attr).copy()
        records: list[AtomicRecord] = []
        for part, rotation in parts_with_rotations:
            if rotation is None:
                result = self._find_best_placement(part, grid_copy, engine)
                if result is None:
                    return None
                records.append(AtomicRecord.from_result(part, result))
            else:
                raster, rot_min_x, rot_min_y, buf_min_x, buf_min_y = engine.rasterize(
                    part.polygon, rotation,
                )
                if not engine.piece_fits_on_sheet(raster):
                    return None
                fmap = engine.feasibility_map(grid_copy, raster)
                pos = engine.find_blf_position(fmap)
                if pos is None:
                    return None
                row, col = pos
                records.append(AtomicRecord(
                    part=part, row=row, col=col, rotation=rotation, raster=raster,
                    rot_min_x=rot_min_x, rot_min_y=rot_min_y,
                    buf_min_x=buf_min_x, buf_min_y=buf_min_y,
                ))
            engine.place_on_grid(grid_copy, records[-1].raster,
                                 records[-1].row, records[-1].col)
        return records

    def _commit_atomic_records(
        self,
        records: list[AtomicRecord],
        sheet: SheetState,
        engine: RasterEngine,
        grid_attr: str,
        sync_fast_grid: bool,
    ) -> None:
        """Commit a list of dry-run records to a sheet."""
        grid = getattr(sheet, grid_attr)
        for r in records:
            engine.place_on_grid(grid, r.raster, r.row, r.col)
            gx, gy = engine.grid_to_inches(r.row, r.col)
            px, py = _compute_part_xy(
                gx, gy, r.rot_min_x, r.rot_min_y,
                r.buf_min_x, r.buf_min_y,
            )
            if sync_fast_grid:
                self._sync_fast_grid(sheet, r.part.polygon, r.rotation)
            sheet.placed.append(Placement(
                part=r.part, x=px, y=py, rotation=r.rotation,
            ))

    def _try_place_mating_block(
        self,
        tabs_with_rotations: list[tuple[EnrichedPart, Optional[float]]],
        receivers_with_rotations: list[tuple[EnrichedPart, Optional[float]]],
        sheets: list[SheetState],
        engine: RasterEngine,
        grid_attr: str = "grid",
        max_sheets: int = 999999,
        bundle_group: int = None,
        sync_fast_grid: bool = False,
    ) -> Optional[tuple[SheetState, SheetState]]:
        """Atomically place a mating block within 1-2 consecutive sheets.

        Joinery invariant: every tab and receiver of a product block must be
        cut from the same physical material. This function enforces that by
        keeping all tabs on a single sheet and the receivers either on that
        same sheet OR the immediately-following sheet — never further apart.

        Two strategies are tried for each candidate sheet (each existing sheet
        in order, then a fresh new sheet):
          A. Full atomic — all tabs + receivers on the candidate sheet.
          B. Split — tabs on the candidate sheet, receivers on candidate+1
             (existing if it has room, or freshly created when the candidate
             is the last sheet).

        Uses dry-run-then-commit: nothing is committed until both placements
        for a strategy are confirmed. If no candidate works, returns None and
        no parts are placed (the caller adds them to the failed list).

        Returns:
            (tab_sheet, receiver_sheet) on success — may be the same sheet for
            Strategy A; receiver_sheet is None if there are no receivers in
            the block.
            None on failure — no commits made.
        """
        full_group = tabs_with_rotations + receivers_with_rotations
        if not full_group:
            return None  # nothing to place

        has_receivers = bool(receivers_with_rotations)
        has_tabs = bool(tabs_with_rotations)

        def commit_records(records, sheet):
            self._commit_atomic_records(
                records, sheet, engine, grid_attr, sync_fast_grid,
            )

        # Iterate over each existing sheet, trying A then B.
        for cand_idx, cand_sheet in enumerate(sheets):
            # Strategy A: full mating group on this candidate sheet
            records = self._dry_run_atomic(full_group, cand_sheet, engine, grid_attr)
            if records is not None:
                commit_records(records, cand_sheet)
                return cand_sheet, cand_sheet if has_receivers else None

            # Strategy B: tabs on candidate, receivers on candidate+1.
            # Skip if no tabs (Strategy A is the only meaningful try) or no
            # receivers (no need to span 2 sheets).
            if not has_tabs or not has_receivers:
                continue

            tab_records = self._dry_run_atomic(
                tabs_with_rotations, cand_sheet, engine, grid_attr,
            )
            if tab_records is None:
                continue

            next_idx = cand_idx + 1
            if next_idx < len(sheets):
                # Try the existing next sheet
                recv_sheet = sheets[next_idx]
                recv_records = self._dry_run_atomic(
                    receivers_with_rotations, recv_sheet, engine, grid_attr,
                )
                if recv_records is not None:
                    commit_records(tab_records, cand_sheet)
                    commit_records(recv_records, recv_sheet)
                    return cand_sheet, recv_sheet
                # else: K+1 exists but can't hold receivers. Don't try later
                # sheets — that would violate the strict 2-sheet constraint.
            elif len(sheets) < max_sheets:
                # candidate is the last sheet; create a fresh K+1 for receivers
                recv_sheet = self.new_sheet(bundle_group)
                recv_records = self._dry_run_atomic(
                    receivers_with_rotations, recv_sheet, engine, grid_attr,
                )
                if recv_records is not None:
                    commit_records(tab_records, cand_sheet)
                    sheets.append(recv_sheet)
                    commit_records(recv_records, recv_sheet)
                    return cand_sheet, recv_sheet

        # No existing sheet candidate worked. Try a fresh new tab sheet.
        if len(sheets) >= max_sheets:
            return None
        new_tab_sheet = self.new_sheet(bundle_group)

        # Strategy A on fresh sheet (best case: everything fits on one new sheet)
        records = self._dry_run_atomic(full_group, new_tab_sheet, engine, grid_attr)
        if records is not None:
            sheets.append(new_tab_sheet)
            commit_records(records, new_tab_sheet)
            return new_tab_sheet, new_tab_sheet if has_receivers else None

        # Strategy B on fresh sheets — need 2 fresh sheets if both tabs and receivers
        if not has_tabs or not has_receivers or len(sheets) + 1 >= max_sheets:
            return None
        tab_records = self._dry_run_atomic(
            tabs_with_rotations, new_tab_sheet, engine, grid_attr,
        )
        if tab_records is None:
            # Tabs don't fit on a fresh sheet — block intrinsically too large
            return None
        new_recv_sheet = self.new_sheet(bundle_group)
        recv_records = self._dry_run_atomic(
            receivers_with_rotations, new_recv_sheet, engine, grid_attr,
        )
        if recv_records is None:
            # Receivers don't fit on a fresh sheet — same intrinsic failure
            return None

        sheets.append(new_tab_sheet)
        commit_records(tab_records, new_tab_sheet)
        sheets.append(new_recv_sheet)
        commit_records(recv_records, new_recv_sheet)
        return new_tab_sheet, new_recv_sheet

    def greedy_blf_blocks(
        self,
        blocks: list[list[EnrichedPart]],
        loose_parts: list[EnrichedPart] = None,
        max_sheets: int = 999999,
        live_callback: Callable = None,
        cancel_check: Callable = None,
        progress_callback: Callable[[int, int], None] = None,
        total_parts: int = None,
    ) -> tuple[list[SheetState], list[EnrichedPart]]:
        """Block-aware greedy BLF placement.

        Joinery invariant for each block:
          - All tab parts are placed atomically on a single sheet.
          - All receiver parts are on the tab sheet OR the immediately-following
            sheet (existing-with-room or freshly created at the end of the list).
          - If neither constraint can be satisfied, the WHOLE mating block fails
            atomically (no half-committed parts).
        Neutrals are placed individually without joinery constraints.
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
            receivers = [p for p in block if p.mating_role == "receiver"]
            neutrals = [p for p in block if p.mating_role == "neutral"]

            tab_sheet = recv_sheet = None
            mating_failed = False

            if tabs or receivers:
                # Atomic mating-block placement (rotation=None → search best)
                placement = self._try_place_mating_block(
                    [(p, None) for p in tabs],
                    [(p, None) for p in receivers],
                    sheets, engine, "grid", max_sheets,
                )
                if placement is None:
                    failed.extend(tabs)
                    failed.extend(receivers)
                    mating_failed = True
                else:
                    tab_sheet, recv_sheet = placement
                    placed_count += len(tabs) + len(receivers)
                    if progress_callback:
                        progress_callback(placed_count, total_parts)

            # Place neutrals — prefer the mating sheets if available, else any
            preferred = [s for s in (tab_sheet, recv_sheet) if s is not None]
            for part in neutrals:
                if self._try_place_on_sheets(
                    part, sheets, engine, max_sheets,
                    preferred_sheets=preferred or None,
                ):
                    placed_count += 1
                else:
                    failed.append(part)
                if progress_callback:
                    progress_callback(placed_count, total_parts)

            if live_callback and (not mating_failed or neutrals):
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

    def _place_with_block_awareness(
        self,
        parts_with_rotations: list[tuple[EnrichedPart, float]],
        block_boundaries: list[tuple[int, int]],
        sheets: list[SheetState],
        engine: RasterEngine,
        grid_attr: str,
        max_sheets: int,
        bundle_group: int = None,
        sync_fast_grid: bool = False,
    ) -> list[EnrichedPart]:
        """Place parts respecting block receiver constraints.

        For each block, tabs are placed first. Receivers in that block
        are then constrained to start searching from the tab's sheet.
        Neutrals are unconstrained.

        Args:
            block_boundaries: List of (start_idx, tab_count) tuples marking
                where each block begins and how many tabs it has.

        Returns:
            List of parts that failed to place.
        """
        failed = []

        # Precompute block end indices
        block_ranges = []
        for idx, (block_start, tab_count) in enumerate(block_boundaries):
            if idx + 1 < len(block_boundaries):
                block_end = block_boundaries[idx + 1][0]
            else:
                block_end = len(parts_with_rotations)
            block_ranges.append((block_start, tab_count, block_end))

        for block_start, tab_count, block_end in block_ranges:
            # Tabs are the first tab_count entries (per the boundaries convention).
            # The remaining "other" entries split into receivers (joinery-constrained)
            # and neutrals (unconstrained) by mating_role.
            tabs_with_rotations = parts_with_rotations[block_start:block_start + tab_count]
            others = parts_with_rotations[block_start + tab_count:block_end]
            receivers_with_rotations = [(p, r) for p, r in others if p.mating_role == "receiver"]
            neutrals_with_rotations = [(p, r) for p, r in others if p.mating_role != "receiver"]

            # Atomic mating-block placement (tabs + receivers within 1-2 sheets)
            tab_sheet = recv_sheet = None
            if tabs_with_rotations or receivers_with_rotations:
                placement = self._try_place_mating_block(
                    tabs_with_rotations, receivers_with_rotations,
                    sheets, engine, grid_attr, max_sheets,
                    bundle_group=bundle_group, sync_fast_grid=sync_fast_grid,
                )
                if placement is None:
                    # Whole mating block fails — no half-committed parts
                    for p, _ in tabs_with_rotations:
                        failed.append(p)
                    for p, _ in receivers_with_rotations:
                        failed.append(p)
                else:
                    tab_sheet, recv_sheet = placement

            # Place neutrals — unconstrained, prefer mating sheets if present
            preferred = [s for s in (tab_sheet, recv_sheet) if s is not None]
            for part, rotation in neutrals_with_rotations:
                result = self._rasterize_and_place(
                    part, rotation, sheets, engine, grid_attr, max_sheets,
                    bundle_group=bundle_group, sync_fast_grid=sync_fast_grid,
                    preferred_sheets=preferred or None,
                )
                if result is None:
                    failed.append(part)

        return failed

    def fast_blf(
        self,
        parts_with_rotations: list[tuple[EnrichedPart, float]],
        max_sheets: int = 999999,
        block_boundaries: list[tuple[int, int]] = None,
    ) -> list[SheetState]:
        """Fast BLF at low resolution for SA evaluation.

        Args:
            parts_with_rotations: Ordered list of (part, rotation_angle) tuples
            max_sheets: Maximum sheets
            block_boundaries: Optional list of (start_idx, tab_count) for
                block-aware receiver placement

        Returns:
            List of SheetStates with placements
        """
        sheets: list[SheetState] = []
        if block_boundaries:
            self._place_with_block_awareness(
                parts_with_rotations, block_boundaries, sheets,
                self.fast_engine, "fast_grid", max_sheets,
            )
        else:
            for part, rotation in parts_with_rotations:
                self._rasterize_and_place(
                    part, rotation, sheets, self.fast_engine, "fast_grid", max_sheets,
                )
        return sheets

    def repack_full_resolution(
        self,
        parts_with_rotations: list[tuple[EnrichedPart, float]],
        bundle_group: int = None,
        max_sheets: int = 999999,
        block_boundaries: list[tuple[int, int]] = None,
    ) -> tuple[list[SheetState], list[EnrichedPart]]:
        """Re-evaluate a solution at full resolution.

        Takes the SA-optimized ordering + rotations and packs at R=0.25".

        Returns:
            (sheets, failed) — final placement at full resolution
        """
        sheets: list[SheetState] = []
        if block_boundaries:
            failed = self._place_with_block_awareness(
                parts_with_rotations, block_boundaries, sheets,
                self.full_engine, "grid", max_sheets,
                bundle_group=bundle_group, sync_fast_grid=True,
            )
        else:
            failed: list[EnrichedPart] = []
            for part, rotation in parts_with_rotations:
                result = self._rasterize_and_place(
                    part, rotation, sheets, self.full_engine, "grid", max_sheets,
                    bundle_group=bundle_group, sync_fast_grid=True,
                )
                if result is None:
                    failed.append(part)
        return sheets, failed

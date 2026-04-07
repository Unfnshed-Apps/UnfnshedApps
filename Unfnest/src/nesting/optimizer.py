"""
Layer 3b: Simulated Annealing optimizer.

Searches over piece ordering + rotation assignment to minimize sheet count
and maximize utilization.

Supports block-aware mode where product-unit blocks are treated as atomic
units that can be reordered but not split.
"""
from __future__ import annotations

import math
import random
import time
from dataclasses import dataclass
from typing import Callable, Optional

from .placement import BLFPlacer, SheetState
from ..enrichment import EnrichedPart


@dataclass
class Solution:
    """An SA solution: ordered list of unit indices + per-part rotations.

    In block mode, `order` contains block indices.
    In flat mode, `order` contains part indices.
    `rotations` always maps part index -> rotation angle.
    """
    order: list[int]
    rotations: dict[int, float]

    def copy(self) -> Solution:
        return Solution(
            order=list(self.order),
            rotations=dict(self.rotations),
        )


def _compute_cost(sheets: list[SheetState], sheet_area: float) -> float:
    """Cost function: sheets_used * 1000 - total_utilization.

    Lower is better. Sheet count dominates; utilization breaks ties.
    """
    if not sheets:
        return float('inf')
    n_sheets = len(sheets)
    total_util = sum(s.utilization for s in sheets)
    return n_sheets * 1000.0 - total_util


class SimulatedAnnealing:
    """SA optimizer for piece ordering and rotation.

    Supports two modes:
      - Flat mode (default): each part is an independent unit
      - Block mode: parts are grouped into blocks that move together

    Neighborhood moves:
      - Swap: exchange two units in ordering (p=0.6)
      - Rotate: change one part's rotation angle (p=0.3)
      - Relocate: remove a unit and insert elsewhere (p=0.1)
    """

    def __init__(
        self,
        placer: BLFPlacer,
        parts: list[EnrichedPart],
        blocks: Optional[list[list[int]]] = None,
        time_budget: float = 10.0,
        cooling_rate: float = 0.995,
        iterations_per_temp: int = 20,
    ):
        self.placer = placer
        self.parts = parts
        self.blocks = blocks  # list of lists of part indices, or None for flat mode
        self.time_budget = time_budget
        self.cooling_rate = cooling_rate
        self.iterations_per_temp = iterations_per_temp
        self.sheet_area = placer.sheet_w * placer.sheet_h
        self.rotations = placer.rotations
        self._rng = random.Random(42)

        # Collect all part indices for rotation moves
        if blocks:
            self._all_part_indices = [idx for block in blocks for idx in block]
        else:
            self._all_part_indices = list(range(len(parts)))

    def _expand_solution(self, sol: Solution) -> list[tuple[EnrichedPart, float]]:
        """Expand a solution into an ordered list of (part, rotation) tuples."""
        result = []
        if self.blocks:
            for block_idx in sol.order:
                for part_idx in self.blocks[block_idx]:
                    rot = sol.rotations.get(part_idx, 0.0)
                    result.append((self.parts[part_idx], rot))
        else:
            for part_idx in sol.order:
                rot = sol.rotations.get(part_idx, 0.0)
                result.append((self.parts[part_idx], rot))
        return result

    def _expand_with_boundaries(self, sol: Solution):
        """Expand a solution and return block boundaries for receiver constraints.

        Returns:
            (parts_with_rotations, block_boundaries) where block_boundaries
            is a list of (start_idx, tab_count) tuples.
        """
        parts = []
        boundaries = []
        if self.blocks:
            for block_idx in sol.order:
                start = len(parts)
                tab_count = 0
                for part_idx in self.blocks[block_idx]:
                    rot = sol.rotations.get(part_idx, 0.0)
                    part = self.parts[part_idx]
                    parts.append((part, rot))
                    if part.mating_role == "tab":
                        tab_count += 1
                boundaries.append((start, tab_count))
        else:
            for part_idx in sol.order:
                rot = sol.rotations.get(part_idx, 0.0)
                parts.append((self.parts[part_idx], rot))
        return parts, boundaries

    def _initial_solution(
        self,
        greedy_sheets: list[SheetState],
    ) -> Solution:
        """Build initial solution from greedy BLF result."""
        part_to_idx = {id(p): i for i, p in enumerate(self.parts)}

        # Extract rotations from greedy result
        rotations: dict[int, float] = {}
        seen_parts: set[int] = set()
        for sheet in greedy_sheets:
            for placement in sheet.placed:
                idx = part_to_idx.get(id(placement.part))
                if idx is not None and idx not in seen_parts:
                    rotations[idx] = placement.rotation
                    seen_parts.add(idx)

        # Fill defaults for any parts not placed
        for idx in self._all_part_indices:
            if idx not in rotations:
                rotations[idx] = 0.0

        if self.blocks:
            # Build block order from greedy result
            # Track which block index each part belongs to
            part_to_block: dict[int, int] = {}
            for block_idx, block in enumerate(self.blocks):
                for part_idx in block:
                    part_to_block[part_idx] = block_idx

            # Order blocks by first appearance in greedy sheets
            ordered_blocks: list[int] = []
            seen_blocks: set[int] = set()
            for sheet in greedy_sheets:
                for placement in sheet.placed:
                    idx = part_to_idx.get(id(placement.part))
                    if idx is not None:
                        block_idx = part_to_block.get(idx)
                        if block_idx is not None and block_idx not in seen_blocks:
                            ordered_blocks.append(block_idx)
                            seen_blocks.add(block_idx)

            # Add any blocks not in greedy result
            for block_idx in range(len(self.blocks)):
                if block_idx not in seen_blocks:
                    ordered_blocks.append(block_idx)

            return Solution(order=ordered_blocks, rotations=rotations)
        else:
            # Flat mode: order is part indices from greedy result
            order = list(seen_parts)
            for i in range(len(self.parts)):
                if i not in seen_parts:
                    order.append(i)
            return Solution(order=order, rotations=rotations)

    def _neighbor(self, sol: Solution) -> Solution:
        """Generate a neighbor solution."""
        n = len(sol.order)
        if n < 2:
            return sol.copy()

        new = sol.copy()
        r = self._rng.random()

        if r < 0.6:
            # Swap two units
            i, j = self._rng.sample(range(n), 2)
            new.order[i], new.order[j] = new.order[j], new.order[i]
        elif r < 0.9:
            # Rotate one part to a different angle
            part_idx = self._rng.choice(self._all_part_indices)
            current = new.rotations.get(part_idx, 0.0)
            candidates = [a for a in self.rotations if a != current]
            if candidates:
                new.rotations[part_idx] = self._rng.choice(candidates)
        else:
            # Relocate: remove a unit and reinsert
            i = self._rng.randrange(n)
            unit = new.order.pop(i)
            j = self._rng.randrange(n)
            new.order.insert(j, unit)

        return new

    def _evaluate(self, sol: Solution) -> float:
        """Evaluate a solution using fast BLF."""
        parts, boundaries = self._expand_with_boundaries(sol)
        sheets = self.placer.fast_blf(
            parts, block_boundaries=boundaries or None,
        )
        return _compute_cost(sheets, self.sheet_area)

    def _calibrate_temperature(self, sol: Solution) -> float:
        """Calibrate initial temperature so ~80% of worsening moves accepted."""
        current_cost = self._evaluate(sol)
        deltas = []

        for _ in range(min(20, max(5, len(sol.order)))):
            neighbor = self._neighbor(sol)
            neighbor_cost = self._evaluate(neighbor)
            delta = neighbor_cost - current_cost
            if delta > 0:
                deltas.append(delta)

        if not deltas:
            return 100.0

        avg_delta = sum(deltas) / len(deltas)
        return -avg_delta / math.log(0.8)

    def optimize(
        self,
        greedy_sheets: list[SheetState],
        bundle_group: int = None,
        live_callback: Callable = None,
        cancel_check: Callable = None,
    ) -> tuple[list[SheetState], list[EnrichedPart]]:
        """Run SA optimization starting from greedy BLF result.

        Returns (sheets, failed) at full resolution after SA search.
        """
        n_units = len(self.blocks) if self.blocks else len(self.parts)
        if self.time_budget <= 0 or n_units < 2:
            return greedy_sheets, []

        current = self._initial_solution(greedy_sheets)
        current_cost = self._evaluate(current)
        best = current.copy()
        best_cost = current_cost

        # Calibrate temperature
        temp = self._calibrate_temperature(current)
        start_time = time.monotonic()
        iterations = 0

        while time.monotonic() - start_time < self.time_budget:
            if cancel_check and cancel_check():
                break

            for _ in range(self.iterations_per_temp):
                if cancel_check and cancel_check():
                    break
                if time.monotonic() - start_time >= self.time_budget:
                    break

                neighbor = self._neighbor(current)
                neighbor_cost = self._evaluate(neighbor)
                delta = neighbor_cost - current_cost

                if delta <= 0 or self._rng.random() < math.exp(-delta / max(temp, 1e-10)):
                    current = neighbor
                    current_cost = neighbor_cost

                    if current_cost < best_cost:
                        best = current.copy()
                        best_cost = current_cost

                        if live_callback:
                            preview_parts, preview_bounds = self._expand_with_boundaries(best)
                            preview_sheets = self.placer.fast_blf(
                                preview_parts,
                                block_boundaries=preview_bounds or None,
                            )
                            live_callback(preview_sheets)

                iterations += 1

            temp *= self.cooling_rate

        # Final: re-evaluate best at full resolution
        parts_with_rotations, boundaries = self._expand_with_boundaries(best)
        sheets, failed = self.placer.repack_full_resolution(
            parts_with_rotations, bundle_group,
            block_boundaries=boundaries or None,
        )

        return sheets, failed

"""
Layer 3b: Simulated Annealing optimizer.

Searches over piece ordering + rotation assignment to minimize sheet count
and maximize utilization.
"""
from __future__ import annotations

import math
import random
import time
from dataclasses import dataclass
from typing import Callable

from .placement import BLFPlacer, SheetState
from ..enrichment import EnrichedPart


@dataclass
class Solution:
    """An SA solution: ordered list of (part_index, rotation_angle) pairs."""
    order: list[int]  # Indices into the original parts list
    rotations: list[float]  # Rotation angle per part

    def copy(self) -> Solution:
        return Solution(
            order=list(self.order),
            rotations=list(self.rotations),
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

    Neighborhood moves:
      - Swap: exchange two pieces in ordering (p=0.6)
      - Rotate: change one piece's rotation angle (p=0.3)
      - Relocate: remove a piece and insert elsewhere (p=0.1)
    """

    def __init__(
        self,
        placer: BLFPlacer,
        parts: list[EnrichedPart],
        time_budget: float = 10.0,
        cooling_rate: float = 0.995,
        iterations_per_temp: int = 20,
    ):
        self.placer = placer
        self.parts = parts
        self.time_budget = time_budget
        self.cooling_rate = cooling_rate
        self.iterations_per_temp = iterations_per_temp
        self.sheet_area = placer.sheet_w * placer.sheet_h
        self.rotations = placer.rotations
        self._rng = random.Random(42)

    def _initial_solution(
        self,
        greedy_sheets: list[SheetState],
    ) -> Solution:
        """Build initial solution from greedy BLF result."""
        # Map parts to indices
        part_to_idx = {id(p): i for i, p in enumerate(self.parts)}

        order = []
        rotations_map = {}

        # Extract ordering and rotations from greedy result
        for sheet in greedy_sheets:
            for placement in sheet.placed:
                idx = part_to_idx.get(id(placement.part))
                if idx is not None and idx not in rotations_map:
                    order.append(idx)
                    rotations_map[idx] = placement.rotation

        # Add any parts not in greedy result (failed parts)
        for i in range(len(self.parts)):
            if i not in rotations_map:
                order.append(i)
                rotations_map[i] = 0.0

        rotations = [rotations_map.get(i, 0.0) for i in order]
        return Solution(order=order, rotations=rotations)

    def _neighbor(self, sol: Solution) -> Solution:
        """Generate a neighbor solution."""
        n = len(sol.order)
        if n < 2:
            return sol.copy()

        new = sol.copy()
        r = self._rng.random()

        if r < 0.6:
            # Swap two pieces
            i, j = self._rng.sample(range(n), 2)
            new.order[i], new.order[j] = new.order[j], new.order[i]
            new.rotations[i], new.rotations[j] = new.rotations[j], new.rotations[i]
        elif r < 0.9:
            # Rotate one piece to a different angle
            i = self._rng.randrange(n)
            current = new.rotations[i]
            candidates = [a for a in self.rotations if a != current]
            if candidates:
                new.rotations[i] = self._rng.choice(candidates)
        else:
            # Relocate: remove and reinsert
            i = self._rng.randrange(n)
            idx = new.order.pop(i)
            rot = new.rotations.pop(i)
            j = self._rng.randrange(n)  # n-1 elements now, but randrange(n) is fine
            new.order.insert(j, idx)
            new.rotations.insert(j, rot)

        return new

    def _evaluate(self, sol: Solution) -> float:
        """Evaluate a solution using fast BLF."""
        parts_with_rotations = [
            (self.parts[idx], rot)
            for idx, rot in zip(sol.order, sol.rotations)
        ]
        sheets = self.placer.fast_blf(parts_with_rotations)
        return _compute_cost(sheets, self.sheet_area)

    def _calibrate_temperature(self, sol: Solution) -> float:
        """Calibrate initial temperature so ~80% of worsening moves accepted."""
        current_cost = self._evaluate(sol)
        deltas = []

        for _ in range(min(20, max(5, len(self.parts)))):
            neighbor = self._neighbor(sol)
            neighbor_cost = self._evaluate(neighbor)
            delta = neighbor_cost - current_cost
            if delta > 0:
                deltas.append(delta)

        if not deltas:
            return 100.0  # Default if no worsening moves found

        avg_delta = sum(deltas) / len(deltas)
        # T such that exp(-avg_delta / T) = 0.8
        # T = -avg_delta / ln(0.8)
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
        if self.time_budget <= 0 or len(self.parts) < 2:
            # No optimization — return greedy result as-is
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

                # Accept better solutions always; worse with probability
                if delta <= 0 or self._rng.random() < math.exp(-delta / max(temp, 1e-10)):
                    current = neighbor
                    current_cost = neighbor_cost

                    if current_cost < best_cost:
                        best = current.copy()
                        best_cost = current_cost

                        # Emit live preview on improvement
                        if live_callback:
                            preview_sheets = self.placer.fast_blf(
                                [(self.parts[i], r) for i, r in
                                 zip(best.order, best.rotations)],
                            )
                            live_callback(preview_sheets)

                iterations += 1

            temp *= self.cooling_rate

        # Final: re-evaluate best at full resolution
        parts_with_rotations = [
            (self.parts[idx], rot)
            for idx, rot in zip(best.order, best.rotations)
        ]
        sheets, failed = self.placer.repack_full_resolution(
            parts_with_rotations, bundle_group,
        )

        return sheets, failed

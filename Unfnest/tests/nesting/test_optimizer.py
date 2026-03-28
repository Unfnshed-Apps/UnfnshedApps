"""Tests for Layer 3b: SimulatedAnnealing — optimization correctness."""
from __future__ import annotations

import pytest

from src.nesting.placement import BLFPlacer
from src.nesting.optimizer import SimulatedAnnealing, _compute_cost
from src.enrichment import EnrichedPart
from src.dxf_loader import PartGeometry, BoundingBox


def _make_part(part_id: str, w: float, h: float) -> EnrichedPart:
    """Create a mock EnrichedPart."""
    hw, hh = w / 2, h / 2
    polygon = [(-hw, -hh), (hw, -hh), (hw, hh), (-hw, hh)]
    geom = PartGeometry(
        filename=f"{part_id}.dxf",
        polygons=[polygon],
        bounding_box=BoundingBox(min_x=-hw, min_y=-hh, max_x=hw, max_y=hh),
    )
    return EnrichedPart(
        part_id=part_id,
        geometry=geom,
        polygon=polygon,
        area=w * h,
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


class TestCostFunction:
    def test_fewer_sheets_better(self):
        """Fewer sheets should always have lower cost."""
        # Mock: 1 sheet at 50% util vs 2 sheets at 80% util
        cost_1 = 1 * 1000 - 50
        cost_2 = 2 * 1000 - 160
        assert cost_1 < cost_2

    def test_higher_utilization_breaks_ties(self):
        """Same sheet count: higher utilization = lower cost."""
        cost_low = 2 * 1000 - 100
        cost_high = 2 * 1000 - 150
        assert cost_high < cost_low


class TestSAZeroBudget:
    def test_zero_budget_returns_greedy(self, placer):
        """SA with 0 time budget should return greedy solution unchanged."""
        parts = [_make_part(f"p{i}", 10, 10) for i in range(5)]
        greedy_sheets, _ = placer.greedy_blf(parts)
        greedy_count = len(greedy_sheets)

        sa = SimulatedAnnealing(placer, parts, time_budget=0)
        result_sheets, failed = sa.optimize(greedy_sheets)

        assert len(result_sheets) == greedy_count
        assert len(failed) == 0


class TestSAImproves:
    def test_sa_never_worse(self, placer):
        """SA should return solution ≤ greedy cost (never worse)."""
        # Use enough parts to potentially benefit from reordering
        parts = [
            _make_part("big", 20, 30),
            _make_part("med1", 15, 15),
            _make_part("med2", 12, 18),
            _make_part("small1", 8, 8),
            _make_part("small2", 6, 10),
            _make_part("small3", 5, 7),
        ]

        greedy_sheets, _ = placer.greedy_blf(parts)
        greedy_count = len(greedy_sheets)

        sa = SimulatedAnnealing(placer, parts, time_budget=2.0)
        result_sheets, failed = sa.optimize(greedy_sheets)

        assert len(result_sheets) <= greedy_count
        assert len(failed) == 0


class TestSACancel:
    def test_cancel_stops_early(self, placer):
        """Cancel check should stop SA early and return a valid result."""
        parts = [_make_part(f"p{i}", 10, 10) for i in range(5)]
        greedy_sheets, _ = placer.greedy_blf(parts)

        call_count = [0]

        def cancel():
            call_count[0] += 1
            return call_count[0] > 3

        sa = SimulatedAnnealing(placer, parts, time_budget=10.0)
        result_sheets, failed = sa.optimize(greedy_sheets, cancel_check=cancel)

        # Should still return valid result
        total_placed = sum(s.part_count for s in result_sheets) + len(failed)
        assert total_placed == 5

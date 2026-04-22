"""Tests for the Manual Nest feature — model helpers + pipeline override matching."""
from __future__ import annotations

from typing import Optional

import pytest

from bridge.models.manual_nest_model import _summarize_parts
from src.nesting.pipeline import _apply_manual_overrides, _compute_nest_supply


# ==================== _summarize_parts ====================

class TestSummarizeParts:
    def test_empty_returns_placeholder(self):
        assert _summarize_parts([]) == "(empty)"

    def test_sheet_without_parts(self):
        assert _summarize_parts([{"parts": []}]) == "(empty)"

    def test_single_product_single_unit(self):
        sheets = [{"parts": [
            {"component_id": 1, "product_sku": "BENCH-01", "product_unit": 0},
            {"component_id": 2, "product_sku": "BENCH-01", "product_unit": 0},
        ]}]
        # 2 parts but one unit — should read "BENCH-01 x1"
        assert _summarize_parts(sheets) == "BENCH-01 x1"

    def test_multiple_units_same_sku(self):
        sheets = [{"parts": [
            {"component_id": 1, "product_sku": "BENCH-01", "product_unit": 0},
            {"component_id": 1, "product_sku": "BENCH-01", "product_unit": 1},
            {"component_id": 1, "product_sku": "BENCH-01", "product_unit": 2},
        ]}]
        assert _summarize_parts(sheets) == "BENCH-01 x3"

    def test_multiple_skus_sorted_alphabetically(self):
        sheets = [{"parts": [
            {"component_id": 1, "product_sku": "STOOL-01", "product_unit": 0},
            {"component_id": 2, "product_sku": "BENCH-01", "product_unit": 0},
        ]}]
        # Output is sorted by SKU — BENCH-01 comes before STOOL-01
        assert _summarize_parts(sheets) == "BENCH-01 x1, STOOL-01 x1"

    def test_mixed_product_and_loose_components(self):
        sheets = [{"parts": [
            {"component_id": 1, "product_sku": "BENCH-01", "product_unit": 0},
            {"component_id": 9, "product_sku": None, "product_unit": None},
            {"component_id": 10, "product_sku": None, "product_unit": None},
        ]}]
        assert _summarize_parts(sheets) == "BENCH-01 x1, 2 loose"

    def test_units_deduplicated_across_sheets(self):
        # Same (sku, unit) appearing on two sheets = still one unit
        sheets = [
            {"parts": [{"component_id": 1, "product_sku": "BENCH-01", "product_unit": 0}]},
            {"parts": [{"component_id": 2, "product_sku": "BENCH-01", "product_unit": 0}]},
        ]
        assert _summarize_parts(sheets) == "BENCH-01 x1"


# ==================== _compute_nest_supply ====================

class TestComputeNestSupply:
    def test_empty_nest_has_empty_supply(self):
        assert _compute_nest_supply({"sheets": []}) == {}

    def test_loose_parts_dont_count_toward_supply(self):
        # Parts without a product_sku can't be matched — the nest's supply
        # is only the product-tagged components.
        supply = _compute_nest_supply({"sheets": [{"parts": [
            {"component_id": 1, "product_sku": None},
            {"component_id": 2, "product_sku": None},
        ]}]})
        assert supply == {}

    def test_single_bench_supply(self):
        supply = _compute_nest_supply({"sheets": [{"parts": [
            {"component_id": 1, "product_sku": "BENCH-01"},
            {"component_id": 1, "product_sku": "BENCH-01"},
            {"component_id": 2, "product_sku": "BENCH-01"},
        ]}]})
        assert supply == {("BENCH-01", 1): 2, ("BENCH-01", 2): 1}

    def test_supply_sums_across_sheets(self):
        supply = _compute_nest_supply({"sheets": [
            {"parts": [{"component_id": 1, "product_sku": "BENCH-01"}]},
            {"parts": [{"component_id": 1, "product_sku": "BENCH-01"}]},
        ]})
        assert supply == {("BENCH-01", 1): 2}


# ==================== _apply_manual_overrides ====================
#
# Uses sentinel `object()` instances for enriched parts to verify only the
# matching semantics — we assert which indices get consumed, without
# depending on the EnrichedPart dataclass's full shape.


class _EnrichedStub:
    """Minimal stand-in for EnrichedPart for matching-only tests."""

    def __init__(self, component_id, product_sku, label=""):
        self.component_id = component_id
        self.product_sku = product_sku
        self.label = label


class _FakeComponentDef:
    def __init__(self, id, dxf_filename):
        self.id = id
        self.dxf_filename = dxf_filename


class _FakeBBox:
    def __init__(self):
        self.min_x = 0; self.min_y = 0
        self.max_x = 6; self.max_y = 8


class _FakePartGeom:
    def __init__(self):
        self.polygons = [[(0, 0), (6, 0), (6, 8), (0, 8)]]
        self.bounding_box = _FakeBBox()
        self.outline_polygons = [[(0, 0), (6, 0), (6, 8), (0, 8)]]
        self.pocket_polygons: list = []
        self.internal_polygons: list = []
        self.outline_entities: list = []
        self.pocket_entities: list = []
        self.internal_entities: list = []


class _FakeDxfLoader:
    """Returns a small rectangle geometry for any filename."""

    def __init__(self, resolve_all: bool = True):
        self._resolve_all = resolve_all

    def load_part(self, filename):
        return _FakePartGeom() if self._resolve_all else None


class _OverrideDb:
    """Mock db exposing enabled nests + component defs."""

    def __init__(self, nests=None, components=None):
        self._nests = list(nests or [])
        self._components = list(components or [])

    def get_enabled_manual_nests(self):
        return self._nests

    def get_all_component_definitions(self):
        return list(self._components)


def _bench_nest(
    name: str = "Bench",
    legs_per_bench: int = 2, tops_per_bench: int = 1,
    units: int = 1,
) -> dict:
    """Build a manual nest dict holding N benches — 2 legs + 1 top each."""
    parts: list[dict] = []
    for u in range(units):
        for _ in range(legs_per_bench):
            parts.append({"component_id": 1, "product_sku": "BENCH-01",
                          "product_unit": u, "x": 2.0, "y": 2.0, "rotation_deg": 0.0})
        for _ in range(tops_per_bench):
            parts.append({"component_id": 2, "product_sku": "BENCH-01",
                          "product_unit": u, "x": 20.0, "y": 2.0, "rotation_deg": 0.0})
    return {
        "id": hash(name) & 0xFFFF,
        "name": name,
        "override_enabled": True,
        "sheets": [{
            "sheet_index": 0, "width": 48, "height": 96,
            "part_spacing": 0.75, "edge_margin": 0.75,
            "parts": parts,
        }],
    }


def _bench_demand(count: int) -> list[_EnrichedStub]:
    """Build an enriched-parts list for N benches (2 legs + 1 top per unit)."""
    enriched: list[_EnrichedStub] = []
    for _ in range(count):
        enriched.append(_EnrichedStub(1, "BENCH-01", "leg"))
        enriched.append(_EnrichedStub(1, "BENCH-01", "leg"))
        enriched.append(_EnrichedStub(2, "BENCH-01", "top"))
    return enriched


_COMPONENTS = [
    _FakeComponentDef(1, "bench_leg.dxf"),
    _FakeComponentDef(2, "bench_top.dxf"),
]


class TestApplyManualOverridesBasics:
    def test_no_db_returns_empty_overrides(self):
        enriched = [_EnrichedStub(1, "BENCH-01")]
        reduced, sheets, meta = _apply_manual_overrides(enriched, None, None)
        assert reduced is enriched
        assert sheets == []
        assert meta == []

    def test_db_without_enabled_hook_returns_empty_overrides(self):
        class _NoHook: pass
        reduced, sheets, _ = _apply_manual_overrides([], _NoHook(), None)
        assert sheets == []

    def test_no_enabled_nests_returns_unchanged(self):
        db = _OverrideDb(nests=[], components=_COMPONENTS)
        reduced, sheets, meta = _apply_manual_overrides(
            _bench_demand(1), db, _FakeDxfLoader(),
        )
        assert len(reduced) == 3   # no consumption
        assert sheets == []
        assert meta == []

    def test_fetch_exception_returns_unchanged(self):
        class _BrokenDb:
            def get_enabled_manual_nests(self):
                raise RuntimeError("server down")
        reduced, sheets, meta = _apply_manual_overrides(
            _bench_demand(1), _BrokenDb(), _FakeDxfLoader(),
        )
        assert len(reduced) == 3 and sheets == [] and meta == []

    def test_missing_dxf_loader_skips_overrides(self):
        db = _OverrideDb(nests=[_bench_nest()], components=_COMPONENTS)
        msgs: list[str] = []
        reduced, sheets, meta = _apply_manual_overrides(
            _bench_demand(1), db, dxf_loader=None,
            status_callback=msgs.append,
        )
        assert sheets == []
        # Operator is told WHY nothing was applied
        assert msgs and "DXF loader unavailable" in msgs[0]


class TestApplyManualOverridesMatching:
    def test_exact_match_consumes_all_parts(self):
        db = _OverrideDb(nests=[_bench_nest()], components=_COMPONENTS)
        reduced, sheets, meta = _apply_manual_overrides(
            _bench_demand(1), db, _FakeDxfLoader(),
        )
        assert reduced == []  # fully consumed
        assert len(sheets) == 1
        assert len(meta) == 1
        # Sheet contains 3 parts (2 legs + 1 top)
        assert len(sheets[0].parts) == 3

    def test_scale_matches_to_demand(self):
        # Nest = 1 bench; demand = 3 benches → use nest 3 times
        db = _OverrideDb(nests=[_bench_nest()], components=_COMPONENTS)
        reduced, sheets, _ = _apply_manual_overrides(
            _bench_demand(3), db, _FakeDxfLoader(),
        )
        assert reduced == []
        assert len(sheets) == 3

    def test_partial_demand_leaves_leftovers(self):
        # Nest = 2 benches; demand = 5 benches → 2 fits, 1 leftover bench
        db = _OverrideDb(nests=[_bench_nest(units=2)], components=_COMPONENTS)
        reduced, sheets, _ = _apply_manual_overrides(
            _bench_demand(5), db, _FakeDxfLoader(),
        )
        # 5 benches = 15 enriched parts; 2 applications consume 12; 3 remain
        assert len(reduced) == 3
        # Each application produces 1 sheet → 2 sheets total
        assert len(sheets) == 2

    def test_nest_does_not_fit_when_demand_too_small(self):
        # Nest = 2 benches; demand = 1 bench → doesn't fit (can't use a half-nest)
        db = _OverrideDb(nests=[_bench_nest(units=2)], components=_COMPONENTS)
        reduced, sheets, _ = _apply_manual_overrides(
            _bench_demand(1), db, _FakeDxfLoader(),
        )
        assert len(reduced) == 3
        assert sheets == []

    def test_greedy_picks_bigger_nest_first(self):
        # Two nests: small (1 bench) + big (2 benches). Demand = 5 benches.
        # Greedy biggest-first: big twice (4) + small once (1) → 3 total sheets
        nests = [
            _bench_nest(name="Small", units=1),
            _bench_nest(name="Big", units=2),
        ]
        db = _OverrideDb(nests=nests, components=_COMPONENTS)
        reduced, sheets, _ = _apply_manual_overrides(
            _bench_demand(5), db, _FakeDxfLoader(),
        )
        assert reduced == []
        assert len(sheets) == 3

    def test_unrelated_parts_pass_through(self):
        # Nest handles only BENCH-01. SHELF parts flow untouched through reduced.
        db = _OverrideDb(nests=[_bench_nest()], components=_COMPONENTS)
        shelf_parts = [_EnrichedStub(9, "SHELF-01") for _ in range(4)]
        enriched = _bench_demand(1) + shelf_parts
        reduced, sheets, _ = _apply_manual_overrides(
            enriched, db, _FakeDxfLoader(),
        )
        # All 4 shelf parts should remain
        assert len(reduced) == 4
        assert all(p.product_sku == "SHELF-01" for p in reduced)
        assert len(sheets) == 1

    def test_loose_parts_never_consumed(self):
        # Enriched parts without a product_sku can't be matched
        loose = [_EnrichedStub(99, None) for _ in range(3)]
        db = _OverrideDb(nests=[_bench_nest()], components=_COMPONENTS)
        reduced, sheets, _ = _apply_manual_overrides(
            loose + _bench_demand(1), db, _FakeDxfLoader(),
        )
        # Loose neutrals remain; bench parts consumed
        assert len(reduced) == 3
        assert all(p.product_sku is None for p in reduced)
        assert len(sheets) == 1

    def test_status_message_describes_application(self):
        db = _OverrideDb(nests=[_bench_nest(name="My bench")], components=_COMPONENTS)
        msgs: list[str] = []
        _apply_manual_overrides(
            _bench_demand(3), db, _FakeDxfLoader(),
            status_callback=msgs.append,
        )
        assert msgs and "Applied" in msgs[0]
        assert "My bench" in msgs[0]
        assert "×3" in msgs[0]

    def test_unloadable_dxfs_degrade_gracefully(self):
        # Loader returns None for every filename — sheet should be skipped,
        # demand stays untouched, no crash, and the enriched parts are
        # returned to the auto-nester untouched.
        db = _OverrideDb(nests=[_bench_nest()], components=_COMPONENTS)
        demand = _bench_demand(1)
        reduced, sheets, _ = _apply_manual_overrides(
            demand, db, _FakeDxfLoader(resolve_all=False),
        )
        assert sheets == []
        # Parts are NOT lost — the override short-circuits to pass-through
        # when it can't produce any sheets, so auto-nest sees full demand.
        assert reduced is demand

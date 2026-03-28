"""
Utilization benchmark for nesting2.

Creates representative input and measures performance:
  - 5 product SKUs, 2-4 components each, 3-5 units per SKU
  - Reports: total sheets, per-sheet utilization, avg utilization, time
  - Compares vs theoretical minimum (total part area / sheet area)
"""
from __future__ import annotations

import time
import sys

sys.path.insert(0, '.')

from src.nesting.pipeline import nest_parts
from src.dxf_loader import PartGeometry, BoundingBox


def _rect_geom(part_id: str, w: float, h: float) -> tuple[str, PartGeometry]:
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
    def get_all_component_definitions(self):
        return []

    def get_all_products(self):
        return []

    def get_all_mating_pairs(self):
        return []


# Product definitions: SKU -> [(component_name, width, height, qty)]
PRODUCT_CATALOG = {
    "SHELF-01": [
        ("shelf_top", 24, 12, 1),
        ("shelf_side", 12, 36, 2),
        ("shelf_back", 24, 36, 1),
    ],
    "DESK-02": [
        ("desk_top", 30, 48, 1),
        ("desk_leg", 4, 28, 4),
        ("desk_support", 20, 4, 2),
    ],
    "TABLE-03": [
        ("table_top", 36, 36, 1),
        ("table_leg", 3, 24, 4),
    ],
    "CABINET-04": [
        ("cab_top", 18, 18, 1),
        ("cab_side", 18, 30, 2),
        ("cab_door", 16, 28, 2),
        ("cab_shelf", 16, 16, 3),
    ],
    "BOOKCASE-05": [
        ("bc_side", 10, 72, 2),
        ("bc_shelf", 30, 10, 5),
        ("bc_back", 30, 72, 1),
    ],
}

UNITS_PER_SKU = {
    "SHELF-01": 5,
    "DESK-02": 3,
    "TABLE-03": 4,
    "CABINET-04": 3,
    "BOOKCASE-05": 2,
}


def build_parts():
    """Build the benchmark part list."""
    parts = []
    total_area = 0.0

    for sku, components in PRODUCT_CATALOG.items():
        n_units = UNITS_PER_SKU[sku]
        for unit in range(n_units):
            for comp_name, w, h, qty in components:
                for q in range(qty):
                    instance = unit * qty + q + 1
                    part_id = f"{sku}_{comp_name}_{instance:03d}"
                    parts.append(_rect_geom(part_id, w, h))
                    total_area += w * h

    return parts, total_area


def run_benchmark():
    """Run the benchmark and report results."""
    parts, total_area = build_parts()
    sheet_area = 48.0 * 96.0
    theoretical_min = total_area / sheet_area

    print(f"Benchmark: {len(parts)} parts, {total_area:.0f} sq in total area")
    print(f"Theoretical minimum: {theoretical_min:.1f} sheets")
    print(f"Sheet size: 48\" x 96\" = {sheet_area:.0f} sq in")
    print()

    db = MockDB()

    # Run without optimization
    print("--- Greedy BLF only (no SA) ---")
    t0 = time.monotonic()
    result_greedy, meta = nest_parts(
        parts, db, optimization_time_budget=0,
    )
    t_greedy = time.monotonic() - t0

    print(f"  Sheets: {result_greedy.sheets_used}")
    print(f"  Placed: {result_greedy.parts_placed}/{result_greedy.total_parts}")
    print(f"  Failed: {result_greedy.parts_failed}")
    for sheet in result_greedy.sheets:
        print(f"    Sheet {sheet.sheet_number}: {sheet.utilization:.1f}% "
              f"({len(sheet.parts)} parts)")
    avg_util = sum(s.utilization for s in result_greedy.sheets) / max(1, len(result_greedy.sheets))
    print(f"  Avg utilization: {avg_util:.1f}%")
    print(f"  Time: {t_greedy:.2f}s")
    print()

    # Run with SA optimization
    print("--- Greedy BLF + SA (10s budget) ---")
    t0 = time.monotonic()
    result_sa, meta = nest_parts(
        parts, db, optimization_time_budget=10.0,
    )
    t_sa = time.monotonic() - t0

    print(f"  Sheets: {result_sa.sheets_used}")
    print(f"  Placed: {result_sa.parts_placed}/{result_sa.total_parts}")
    print(f"  Failed: {result_sa.parts_failed}")
    for sheet in result_sa.sheets:
        print(f"    Sheet {sheet.sheet_number}: {sheet.utilization:.1f}% "
              f"({len(sheet.parts)} parts)")
    avg_util = sum(s.utilization for s in result_sa.sheets) / max(1, len(result_sa.sheets))
    print(f"  Avg utilization: {avg_util:.1f}%")
    print(f"  Time: {t_sa:.2f}s")
    print()

    # Summary
    print("=== Summary ===")
    print(f"  Theoretical min sheets: {theoretical_min:.1f}")
    print(f"  Greedy: {result_greedy.sheets_used} sheets in {t_greedy:.2f}s")
    print(f"  SA:     {result_sa.sheets_used} sheets in {t_sa:.2f}s")
    improvement = result_greedy.sheets_used - result_sa.sheets_used
    if improvement > 0:
        print(f"  SA saved {improvement} sheet(s)")
    else:
        print(f"  SA matched greedy result")


if __name__ == "__main__":
    run_benchmark()

"""
Orchestrator — wires enrichment, grouping, placement, and optimization.
"""
from __future__ import annotations

from typing import Callable

from .placement import BLFPlacer, SheetState
from .optimizer import SimulatedAnnealing
from ..enrichment import (
    EnrichedPart, enrich_parts, compute_mating_clusters,
)
from ..nesting_models import (
    NestingResult, SheetMetadata,
)
from ..dxf_loader import PartGeometry


def nest_parts(
    parts: list[tuple[str, PartGeometry]],
    db,
    sheet_width: float = 48.0,
    sheet_height: float = 96.0,
    part_spacing: float = 0.75,
    edge_margin: float = None,
    progress_callback: Callable[[int, int], None] = None,
    status_callback: Callable[[str], None] = None,
    product_comp_qty: dict = None,
    live_callback: Callable = None,
    cancel_check: Callable = None,
    optimization_time_budget: float = 10.0,
    rotation_count: int = 4,
    **kwargs,
) -> tuple[NestingResult, list[SheetMetadata]]:
    """Nesting v2 entry point — drop-in replacement for nest_parts_constrained.

    Uses raster-based FFT collision detection + BLF placement + SA optimization.

    Routes to:
      - Cluster-aware path if mating pairs exist
      - Product-groups path if product SKUs exist
      - Simple path otherwise

    Returns:
        (NestingResult, list[SheetMetadata])
    """
    if edge_margin is None:
        edge_margin = part_spacing

    # Step 0: Enrich parts with metadata
    if status_callback:
        status_callback("Enriching parts...")

    enriched, mating_pairs = enrich_parts(parts, db, product_comp_qty=product_comp_qty)

    if not enriched:
        return NestingResult(
            sheets=[], total_parts=len(parts),
            parts_placed=0, parts_failed=len(parts),
        ), []

    # Create placer
    placer = BLFPlacer(
        sheet_w=sheet_width,
        sheet_h=sheet_height,
        spacing=part_spacing,
        edge_margin=edge_margin,
        rotation_count=rotation_count,
    )

    # Decide path
    clusters = compute_mating_clusters(mating_pairs) if mating_pairs else {}
    has_product_parts = any(p.product_sku is not None for p in enriched)

    if clusters:
        return _nest_cluster_aware(
            enriched, clusters, placer,
            progress_callback, status_callback,
            len(parts), live_callback, cancel_check,
            optimization_time_budget,
        )
    elif has_product_parts:
        return _nest_product_groups(
            enriched, placer,
            progress_callback, status_callback,
            len(parts), live_callback, cancel_check,
            optimization_time_budget,
        )
    else:
        return _nest_simple(
            enriched, placer,
            progress_callback, status_callback,
            len(parts), live_callback, cancel_check,
            optimization_time_budget,
        )


def _nest_simple(
    enriched: list[EnrichedPart],
    placer: BLFPlacer,
    progress_callback: Callable,
    status_callback: Callable,
    total_input_parts: int,
    live_callback: Callable = None,
    cancel_check: Callable = None,
    optimization_time_budget: float = 10.0,
) -> tuple[NestingResult, list[SheetMetadata]]:
    """Simple path: all parts in one group, BLF + SA."""
    if status_callback:
        status_callback("Packing parts...")

    # Sort: receivers (variable-pocket parts) last so tabs are cut first
    all_parts = sorted(enriched, key=lambda p: (p.mating_role == "receiver", -p.area))

    all_sheets: list[SheetState] = []
    all_failed: list[EnrichedPart] = []

    # Pack all parts together
    if all_parts:
        sheets, failed = placer.greedy_blf(
            all_parts,
            live_callback=live_callback,
            cancel_check=cancel_check,
            progress_callback=progress_callback,
            total_parts=len(enriched),
        )
        all_sheets.extend(sheets)
        all_failed.extend(failed)

    # SA optimization
    if optimization_time_budget > 0 and not (cancel_check and cancel_check()):
        if status_callback:
            status_callback("Optimizing placement...")
        all_sheets = _optimize_sheets_sa(
            all_sheets, enriched, placer,
            optimization_time_budget, live_callback, cancel_check,
        )

    return _build_result(all_sheets, all_failed, total_input_parts)


def _nest_product_groups(
    enriched: list[EnrichedPart],
    placer: BLFPlacer,
    progress_callback: Callable,
    status_callback: Callable,
    total_input_parts: int,
    live_callback: Callable = None,
    cancel_check: Callable = None,
    optimization_time_budget: float = 10.0,
) -> tuple[NestingResult, list[SheetMetadata]]:
    """Product-groups path: packs ALL parts together for maximum efficiency.

    Rather than splitting into restrictive ≤4-sheet groups (which fragments
    packing space), packs all parts using greedy BLF + SA.
    Bundle group metadata is assigned post-hoc based on product SKU.
    """
    if status_callback:
        status_callback("Packing parts...")

    # Sort: receivers (variable-pocket parts) last so tabs are cut first
    all_parts = sorted(enriched, key=lambda p: (p.mating_role == "receiver", -p.area))

    all_sheets: list[SheetState] = []
    all_failed: list[EnrichedPart] = []

    # Pack all parts together
    if all_parts:
        sheets, failed = placer.greedy_blf(
            all_parts,
            live_callback=live_callback,
            cancel_check=cancel_check,
            progress_callback=progress_callback,
            total_parts=len(enriched),
        )
        all_sheets.extend(sheets)
        all_failed.extend(failed)

    # SA optimization on all sheets together
    if optimization_time_budget > 0 and not (cancel_check and cancel_check()):
        if status_callback:
            status_callback("Optimizing placement...")
        all_sheets = _optimize_sheets_sa(
            all_sheets, enriched, placer,
            optimization_time_budget, live_callback, cancel_check,
        )

    # Assign bundle_group metadata post-hoc based on which products
    # share each sheet, so bundling at export still works
    _assign_bundle_groups(all_sheets)

    return _build_result(all_sheets, all_failed, total_input_parts)


def _assign_bundle_groups(sheets: list[SheetState]):
    """Assign bundle_group IDs post-hoc so sheets with the same product SKUs
    share a bundle group. This preserves export bundling without constraining
    the packing algorithm."""
    # Build a signature for each sheet based on which SKUs it contains
    sku_to_group: dict[str, int] = {}
    next_group = 1

    for sheet in sheets:
        skus = set()
        for p in sheet.placed:
            if p.part.product_sku is not None:
                skus.add(p.part.product_sku)

        if not skus:
            continue

        # Find existing group for any of these SKUs, or create new one
        group_id = None
        for sku in skus:
            if sku in sku_to_group:
                group_id = sku_to_group[sku]
                break

        if group_id is None:
            group_id = next_group
            next_group += 1

        # Assign all SKUs on this sheet to the same group
        for sku in skus:
            sku_to_group[sku] = group_id

        sheet.bundle_group = group_id


def _nest_cluster_aware(
    enriched: list[EnrichedPart],
    clusters: dict[int, int],
    placer: BLFPlacer,
    progress_callback: Callable,
    status_callback: Callable,
    total_input_parts: int,
    live_callback: Callable = None,
    cancel_check: Callable = None,
    optimization_time_budget: float = 10.0,
) -> tuple[NestingResult, list[SheetMetadata]]:
    """Cluster-aware packing: co-locate mating parts on same sheets."""
    if status_callback:
        status_callback("Packing cluster groups...")

    # Partition into cluster groups
    cluster_groups: dict[int, list[EnrichedPart]] = {}
    noncluster: list[EnrichedPart] = []

    for part in enriched:
        cluster_id = clusters.get(part.component_id)
        if cluster_id is not None:
            cluster_groups.setdefault(cluster_id, []).append(part)
        else:
            noncluster.append(part)

    # Sort: receivers (variable-pocket parts) last within each group
    for parts_list in cluster_groups.values():
        parts_list.sort(key=lambda p: (p.mating_role == "receiver", -p.area))
    noncluster.sort(key=lambda p: (p.mating_role == "receiver", -p.area))

    all_failed: list[EnrichedPart] = []
    cluster_sheets: list[SheetState] = []
    noncluster_sheets: list[SheetState] = []
    placed_count = 0

    # Pack each cluster group
    for cluster_id, parts_list in sorted(cluster_groups.items()):
        if cancel_check and cancel_check():
            break

        sheets, failed = placer.greedy_blf(
            parts_list,
            bundle_group=cluster_id,
            live_callback=lambda s: live_callback(cluster_sheets + s) if live_callback else None,
            cancel_check=cancel_check,
            progress_callback=progress_callback,
            progress_offset=placed_count,
            total_parts=len(enriched),
        )
        all_failed.extend(failed)
        cluster_sheets.extend(sheets)
        placed_count += sum(s.part_count for s in sheets)

    # Fill cluster sheets with non-cluster parts, then overflow to new sheets
    _cancelled = cancel_check and cancel_check()

    if not _cancelled:
        remaining: list[EnrichedPart] = []
        engine = placer.full_engine
        for part in noncluster:
            placed = False
            for sheet in cluster_sheets:
                result = placer._find_best_placement(part, sheet.grid, engine)
                if result is not None:
                    placer._commit_placement(part, sheet, result, engine)
                    placed = True
                    placed_count += 1
                    break
            if not placed:
                remaining.append(part)

        # Pack overflow non-cluster parts onto new sheets
        if remaining:
            sheets, failed = placer.greedy_blf(
                remaining,
                live_callback=lambda s: live_callback(cluster_sheets + noncluster_sheets + s) if live_callback else None,
                cancel_check=cancel_check,
            )
            noncluster_sheets.extend(sheets)
            all_failed.extend(failed)

    all_sheet_states = cluster_sheets + noncluster_sheets
    return _build_result(all_sheet_states, all_failed, total_input_parts)


def _optimize_sheets_sa(
    sheets: list[SheetState],
    parts: list[EnrichedPart],
    placer: BLFPlacer,
    time_budget: float,
    live_callback: Callable = None,
    cancel_check: Callable = None,
) -> list[SheetState]:
    """Run SA on the full part set to try to reduce sheet count."""
    if len(parts) < 2 or time_budget <= 0:
        return sheets

    sa = SimulatedAnnealing(placer, parts, time_budget=time_budget)
    optimized, failed = sa.optimize(
        sheets,
        live_callback=live_callback,
        cancel_check=cancel_check,
    )

    # Only accept if not worse
    if len(optimized) <= len(sheets) and not failed:
        return optimized
    return sheets


def _build_result(
    sheets: list[SheetState],
    failed: list[EnrichedPart],
    total_input_parts: int,
) -> tuple[NestingResult, list[SheetMetadata]]:
    """Convert SheetStates to final NestingResult + SheetMetadata."""
    nested_sheets = [s.to_nested_sheet(sheet_number=i)
                     for i, s in enumerate(sheets, 1)]
    sheet_metadata = [s.to_metadata() for s in sheets]
    total_placed = sum(len(s.parts) for s in nested_sheets)

    return NestingResult(
        sheets=nested_sheets,
        total_parts=total_input_parts,
        parts_placed=total_placed,
        parts_failed=len(failed),
    ), sheet_metadata

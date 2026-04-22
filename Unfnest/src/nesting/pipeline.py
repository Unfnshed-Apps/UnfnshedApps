"""
Orchestrator — wires enrichment, grouping, placement, and optimization.
"""
from __future__ import annotations

import sys
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
from ..nesting_models import NestedSheet, PlacedPart


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
    product_unit_map: dict = None,
    live_callback: Callable = None,
    cancel_check: Callable = None,
    optimization_time_budget: float = 10.0,
    rotation_count: int = 4,
    dxf_loader=None,
    **kwargs,
) -> tuple[NestingResult, list[SheetMetadata]]:
    """Nesting v2 entry point.

    Uses raster-based FFT collision detection + BLF placement + SA optimization.

    Routes to:
      - Product-unit block path if parts have product SKUs (keeps product
        components together, tabs atomically co-located on same sheet)
      - Simple path otherwise

    Returns:
        (NestingResult, list[SheetMetadata])
    """
    if edge_margin is None:
        edge_margin = part_spacing

    # Step 0: Enrich parts with metadata
    if status_callback:
        status_callback("Enriching parts...")

    enriched, mating_pairs = enrich_parts(
        parts, db, product_comp_qty=product_comp_qty,
        product_unit_map=product_unit_map,
    )

    if not enriched:
        return NestingResult(
            sheets=[], total_parts=len(parts),
            parts_placed=0, parts_failed=len(parts),
        ), []

    # Step 0.5: Apply manual-nest overrides. Any enabled manual nest whose
    # product-SKU contents match (or fit into) the current demand is consumed
    # as pre-placed sheets — those sheets short-circuit the nesting pass and
    # get prepended to the final result.
    enriched, override_sheets, override_metadata = _apply_manual_overrides(
        enriched, db, dxf_loader, status_callback,
    )

    # If overrides consumed every part, short-circuit — no auto-nest needed.
    if not enriched:
        for i, s in enumerate(override_sheets, 1):
            s.sheet_number = i
        return NestingResult(
            sheets=override_sheets,
            total_parts=len(parts),
            parts_placed=sum(len(s.parts) for s in override_sheets),
            parts_failed=0,
        ), override_metadata

    # Create placer
    placer = BLFPlacer(
        sheet_w=sheet_width,
        sheet_h=sheet_height,
        spacing=part_spacing,
        edge_margin=edge_margin,
        rotation_count=rotation_count,
    )

    # Route based on whether parts have product context
    has_product_parts = any(p.product_sku is not None for p in enriched)

    if has_product_parts:
        result, metadata = _nest_with_product_blocks(
            enriched, placer,
            progress_callback, status_callback,
            len(parts), live_callback, cancel_check,
            optimization_time_budget,
        )
    else:
        result, metadata = _nest_simple(
            enriched, placer,
            progress_callback, status_callback,
            len(parts), live_callback, cancel_check,
            optimization_time_budget,
        )

    if override_sheets:
        # Prepend pre-placed override sheets to the auto-nest result.
        # Renumber contiguously so operators see a continuous 1..N sequence.
        merged_sheets = list(override_sheets) + list(result.sheets)
        for i, s in enumerate(merged_sheets, 1):
            s.sheet_number = i
        result = NestingResult(
            sheets=merged_sheets,
            total_parts=len(parts),
            parts_placed=sum(len(s.parts) for s in merged_sheets),
            parts_failed=result.parts_failed,
        )
        metadata = list(override_metadata) + list(metadata)
    return result, metadata


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

    # Sort: receivers last so tabs are cut first, then by area descending
    all_parts = sorted(enriched, key=lambda p: (p.mating_role == "receiver", -p.area))

    all_sheets: list[SheetState] = []
    all_failed: list[EnrichedPart] = []

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


def _build_product_blocks(
    enriched: list[EnrichedPart],
) -> tuple[list[list[EnrichedPart]], list[EnrichedPart]]:
    """Group parts into product-unit blocks.

    Each block contains all parts for one product instance, ordered:
    tabs first (by area desc), then neutrals (by area desc), then receivers.

    Returns:
        (blocks, loose_parts) — blocks for product parts, loose for the rest
    """
    groups: dict[tuple[str, int], list[EnrichedPart]] = {}
    loose: list[EnrichedPart] = []

    for part in enriched:
        if part.product_sku is not None and part.product_unit is not None:
            key = (part.product_sku, part.product_unit)
            groups.setdefault(key, []).append(part)
        else:
            loose.append(part)

    # Sort within each block: tabs first, neutrals, receivers last; by area desc within role
    blocks = []
    for key in groups:
        parts = groups[key]
        parts.sort(key=lambda p: (
            0 if p.mating_role == "tab" else (2 if p.mating_role == "receiver" else 1),
            -p.area,
        ))
        blocks.append(parts)

    # Two-tier ordering:
    #   Tier 1: blocks with mating constraints (tabs or receivers), largest first.
    #     These get first claim on empty sheets — gives the strict
    #     "tab sheet OR tab_sheet+1" receiver constraint room to succeed.
    #   Tier 2: neutral-only blocks, largest first. They fill remaining gaps
    #     with no joinery cost.
    def _has_mating(block):
        return any(p.mating_role in ("tab", "receiver") for p in block)

    mating_blocks = [b for b in blocks if _has_mating(b)]
    neutral_blocks = [b for b in blocks if not _has_mating(b)]
    mating_blocks.sort(key=lambda b: max(p.area for p in b), reverse=True)
    neutral_blocks.sort(key=lambda b: max(p.area for p in b), reverse=True)
    blocks = mating_blocks + neutral_blocks

    # Sort loose parts: by area descending
    loose.sort(key=lambda p: -p.area)

    return blocks, loose


def _nest_with_product_blocks(
    enriched: list[EnrichedPart],
    placer: BLFPlacer,
    progress_callback: Callable,
    status_callback: Callable,
    total_input_parts: int,
    live_callback: Callable = None,
    cancel_check: Callable = None,
    optimization_time_budget: float = 10.0,
) -> tuple[NestingResult, list[SheetMetadata]]:
    """Product-unit block path: keeps product components together.

    Tabs for the same product unit are placed atomically on the same sheet.
    Receivers follow immediately (same sheet if they fit, next if not).
    SA optimizes block ordering while preserving co-location.
    """
    if status_callback:
        status_callback("Grouping product units...")

    blocks, loose = _build_product_blocks(enriched)

    if status_callback:
        status_callback("Packing product blocks...")

    # Greedy BLF with block-aware placement
    all_sheets, all_failed = placer.greedy_blf_blocks(
        blocks,
        loose_parts=loose,
        live_callback=live_callback,
        cancel_check=cancel_check,
        progress_callback=progress_callback,
        total_parts=len(enriched),
    )

    # SA optimization with block constraints
    if optimization_time_budget > 0 and not (cancel_check and cancel_check()):
        if status_callback:
            status_callback("Optimizing placement...")

        # Build block index structure for SA: list of lists of part indices
        part_to_idx = {id(p): i for i, p in enumerate(enriched)}
        sa_blocks = []
        for block in blocks:
            indices = []
            for part in block:
                idx = part_to_idx.get(id(part))
                if idx is not None:
                    indices.append(idx)
            if indices:
                sa_blocks.append(indices)

        # Add loose parts as singleton blocks
        for part in loose:
            idx = part_to_idx.get(id(part))
            if idx is not None:
                sa_blocks.append([idx])

        sa = SimulatedAnnealing(
            placer, enriched, blocks=sa_blocks,
            time_budget=optimization_time_budget,
        )
        optimized, failed = sa.optimize(
            all_sheets,
            live_callback=live_callback,
            cancel_check=cancel_check,
        )

        if len(optimized) <= len(all_sheets) and not failed:
            all_sheets = optimized

    # Joinery invariant: verify every product block's tabs share a sheet.
    # This is a tripwire for placement-code regressions; mated parts cut from
    # different material won't fit, so any split is a real bug.
    violations = _check_block_atomicity(all_sheets)
    if violations:
        msg = (
            f"⚠ Joinery invariant broken in {len(violations)} block(s):\n  - "
            + "\n  - ".join(violations)
        )
        if status_callback:
            status_callback(msg)
        # Also print so it shows up in dev logs / stdout-watching tooling
        print(msg, file=sys.stderr)
    elif status_callback:
        n_blocks = sum(
            1 for s in all_sheets for p in s.placed
            if p.part.product_sku is not None and p.part.mating_role == "tab"
        )
        if n_blocks:
            status_callback(f"✓ All product blocks intact (tabs co-located)")

    # Assign bundle groups post-hoc based on product SKUs
    _assign_bundle_groups(all_sheets)

    return _build_result(all_sheets, all_failed, total_input_parts)


def _apply_manual_overrides(
    enriched: list[EnrichedPart],
    db,
    dxf_loader,
    status_callback: Callable = None,
) -> tuple[list[EnrichedPart], list[NestedSheet], list[SheetMetadata]]:
    """Consume enriched parts that match enabled manual nests and produce
    pre-placed sheets from their stored layouts.

    Returns a tuple of:
      - The enriched list with consumed parts removed
      - A list of pre-placed NestedSheet records (no auto-nester needed)
      - A list of SheetMetadata parallel to those sheets

    Greedy, biggest-first matching: a nest is applied as many times as it
    fits the remaining demand, subtracting its supply (product SKU ×
    component count) from the demand on each application. Any exceptions
    or missing dependencies degrade silently — overrides must never break
    a real nesting run.
    """
    empty: tuple[list[EnrichedPart], list[NestedSheet], list[SheetMetadata]] = (
        enriched, [], [],
    )
    if db is None or not hasattr(db, "get_enabled_manual_nests"):
        return empty
    try:
        enabled = db.get_enabled_manual_nests() or []
    except Exception:
        return empty
    if not enabled or dxf_loader is None:
        if enabled and status_callback:
            status_callback(
                f"ℹ {len(enabled)} manual nest override(s) enabled but "
                "DXF loader unavailable — overrides skipped."
            )
        return empty

    # Load component definitions once so we can map stored component_id
    # references to DXF filenames. A failed fetch degrades to no overrides
    # (better than a 500 in the middle of a nesting run).
    try:
        comp_defs = db.get_all_component_definitions() or []
    except Exception:
        return empty
    comp_filename: dict[int, str] = {
        int(c.id): getattr(c, "dxf_filename", "") for c in comp_defs
    }

    # Biggest-first — by total placed parts across all sheets
    enabled.sort(
        key=lambda n: sum(len(s.get("parts") or []) for s in n.get("sheets") or []),
        reverse=True,
    )

    # Build demand index: (sku, cid) → list of indices into enriched
    demand_index: dict[tuple[str, int], list[int]] = {}
    for i, part in enumerate(enriched):
        if part.product_sku is None or part.component_id is None:
            continue
        demand_index.setdefault((part.product_sku, part.component_id), []).append(i)

    consumed: set[int] = set()
    override_sheets: list[NestedSheet] = []
    override_metadata: list[SheetMetadata] = []
    applied: list[tuple[str, int]] = []

    for nest in enabled:
        supply = _compute_nest_supply(nest)
        if not supply:
            continue
        fits = min(
            len(demand_index.get(k, [])) // count
            for k, count in supply.items()
        )
        if fits <= 0:
            continue

        # Apply the nest `fits` times: consume matching parts + emit sheets
        for _ in range(fits):
            for key, count in supply.items():
                for _ in range(count):
                    consumed.add(demand_index[key].pop())
            for nest_sheet in nest.get("sheets") or []:
                ns, sm = _build_override_sheet(nest_sheet, dxf_loader, comp_filename)
                if ns is not None:
                    override_sheets.append(ns)
                    override_metadata.append(sm)
        applied.append((nest.get("name", "?"), fits))

    if not override_sheets:
        return empty

    if status_callback:
        names = "; ".join(f"{name} ×{n}" for name, n in applied[:3])
        if len(applied) > 3:
            names += "; …"
        status_callback(
            f"✓ Applied {len(override_sheets)} manual override sheet(s) ({names})."
        )

    reduced = [p for i, p in enumerate(enriched) if i not in consumed]
    return reduced, override_sheets, override_metadata


def _compute_nest_supply(nest: dict) -> dict[tuple[str, int], int]:
    """Count (product_sku, component_id) occurrences across a nest's sheets.

    Parts without a product_sku (loose neutrals) can't be override-matched,
    so they're skipped here and will flow through the auto-nester as usual.
    """
    supply: dict[tuple[str, int], int] = {}
    for sheet in nest.get("sheets") or []:
        for part in sheet.get("parts") or []:
            sku = part.get("product_sku")
            cid = part.get("component_id")
            if sku is None or cid is None:
                continue
            supply[(sku, cid)] = supply.get((sku, cid), 0) + 1
    return supply


def _build_override_sheet(
    nest_sheet: dict, dxf_loader, comp_filename: dict[int, str],
) -> tuple[NestedSheet | None, SheetMetadata | None]:
    """Construct a NestedSheet + SheetMetadata from a stored manual-nest sheet.

    Loads DXF geometry for every placement via the shared dxf_loader. Parts
    whose DXF can't be located are skipped (logged) — the override still
    ships the rest of the sheet so the operator isn't blocked by one missing
    file. Returns (None, None) if nothing loadable is found.
    """
    width = float(nest_sheet.get("width") or 48.0)
    height = float(nest_sheet.get("height") or 96.0)
    placed: list[PlacedPart] = []
    for raw in nest_sheet.get("parts") or []:
        cid = int(raw.get("component_id") or 0)
        filename = comp_filename.get(cid) or ""
        if not filename:
            continue
        try:
            geom = dxf_loader.load_part(filename)
        except Exception:
            geom = None
        if geom is None:
            print(
                f"⚠ Manual override: DXF '{filename}' not loadable — "
                "part skipped on pre-placed sheet.",
                file=sys.stderr,
            )
            continue
        polygon = geom.polygons[0] if geom.polygons else []
        placed.append(PlacedPart(
            part_id=(
                f"manual_{raw.get('product_sku', '')}"
                f"_u{raw.get('product_unit', 0)}"
                f"_c{raw.get('component_id', 0)}"
            ),
            source_filename=filename,
            x=float(raw.get("x") or 0.0),
            y=float(raw.get("y") or 0.0),
            rotation=float(raw.get("rotation_deg") or 0.0),
            polygon=list(polygon),
            outline_polygons=list(geom.outline_polygons),
            pocket_polygons=list(geom.pocket_polygons),
            internal_polygons=list(geom.internal_polygons),
            outline_entities=list(geom.outline_entities),
            pocket_entities=list(geom.pocket_entities),
            internal_entities=list(geom.internal_entities),
        ))
    if not placed:
        return None, None
    return (
        NestedSheet(sheet_number=0, width=width, height=height, parts=placed),
        SheetMetadata(has_variable_pockets=False, bundle_group=None),
    )


def _check_block_atomicity(sheets: list[SheetState]) -> list[str]:
    """Verify the joinery invariant for each product block.

    Two checks:
      1. All tabs of a block share a single sheet.
      2. All receivers of a block are on the tab sheet OR the immediately-following
         sheet (tab_sheet_idx or tab_sheet_idx + 1). No further drift.

    Walks the final sheets and groups placed parts by (product_sku, product_unit).
    Returns a list of human-readable violation descriptions — empty if all blocks
    satisfy both invariants. Violations indicate placement bugs that would break
    joinery (mated parts cut from different/distant material won't fit).
    """
    # Group tabs and receivers per block, recording which sheet each landed on
    block_tabs: dict[tuple[str, int], list[tuple[int, str]]] = {}
    block_receivers: dict[tuple[str, int], list[tuple[int, str]]] = {}
    for sheet_idx, sheet in enumerate(sheets):
        for placement in sheet.placed:
            part = placement.part
            if part.product_sku is None or part.product_unit is None:
                continue
            key = (part.product_sku, part.product_unit)
            if part.mating_role == "tab":
                block_tabs.setdefault(key, []).append((sheet_idx, part.part_id))
            elif part.mating_role == "receiver":
                block_receivers.setdefault(key, []).append((sheet_idx, part.part_id))

    violations = []

    # Check 1: tabs co-located on one sheet
    for (sku, unit), tabs in block_tabs.items():
        sheet_set = set(s for s, _ in tabs)
        if len(sheet_set) > 1:
            # Build "sheet N: [tab_a, tab_b], sheet M: [tab_c]" summary
            by_sheet: dict[int, list[str]] = {}
            for s, pid in tabs:
                by_sheet.setdefault(s, []).append(pid)
            parts_summary = "; ".join(
                f"sheet {s+1}: {by_sheet[s]}"
                for s in sorted(by_sheet)
            )
            violations.append(
                f"{sku} unit {unit} tabs split across sheets — {parts_summary}"
            )

    # Check 2: receivers within tab_sheet or tab_sheet+1
    for (sku, unit), receivers in block_receivers.items():
        tabs = block_tabs.get((sku, unit))
        if not tabs:
            continue  # no tabs in this block, no constraint to check
        # Tab sheet — Check 1 already flags split tabs; for distance check we
        # use the lowest tab sheet as reference (any choice is fine if tabs
        # are co-located).
        tab_sheet_idx = min(s for s, _ in tabs)
        bad_receivers = [
            (s, pid) for s, pid in receivers
            if s != tab_sheet_idx and s != tab_sheet_idx + 1
        ]
        if bad_receivers:
            recv_summary = "; ".join(
                f"sheet {s+1}: {pid}" for s, pid in bad_receivers
            )
            violations.append(
                f"{sku} unit {unit} receivers too far from tabs "
                f"(tabs on sheet {tab_sheet_idx + 1}, "
                f"expected receiver on sheet {tab_sheet_idx + 1} or {tab_sheet_idx + 2}) — "
                f"{recv_summary}"
            )

    return violations


def _assign_bundle_groups(sheets: list[SheetState]):
    """Assign bundle_group IDs post-hoc so sheets with the same product SKUs
    share a bundle group. This preserves export bundling."""
    sku_to_group: dict[str, int] = {}
    next_group = 1

    for sheet in sheets:
        skus = set()
        for p in sheet.placed:
            if p.part.product_sku is not None:
                skus.add(p.part.product_sku)

        if not skus:
            continue

        group_id = None
        for sku in skus:
            if sku in sku_to_group:
                group_id = sku_to_group[sku]
                break

        if group_id is None:
            group_id = next_group
            next_group += 1

        for sku in skus:
            sku_to_group[sku] = group_id

        sheet.bundle_group = group_id


def _optimize_sheets_sa(
    sheets: list[SheetState],
    parts: list[EnrichedPart],
    placer: BLFPlacer,
    time_budget: float,
    live_callback: Callable = None,
    cancel_check: Callable = None,
) -> list[SheetState]:
    """Run SA on the full part set (flat mode) to try to reduce sheet count."""
    if len(parts) < 2 or time_budget <= 0:
        return sheets

    sa = SimulatedAnnealing(placer, parts, time_budget=time_budget)
    optimized, failed = sa.optimize(
        sheets,
        live_callback=live_callback,
        cancel_check=cancel_check,
    )

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

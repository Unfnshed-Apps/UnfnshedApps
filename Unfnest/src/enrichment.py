"""
Part enrichment layer for constrained nesting.

Attaches metadata (mating role, product SKU) to parts
before they enter the constraint-aware nesting pipeline.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import Optional

from .dxf_loader import PartGeometry

logger = logging.getLogger(__name__)


@dataclass
class MatingPair:
    """A mating relationship between two components, scoped to a product."""
    pocket_component_id: int
    mating_component_id: int
    pocket_index: int = 0
    clearance_inches: float = 0.0079
    product_sku: str = ""


@dataclass
class EnrichedPart:
    """A part with full metadata for constrained nesting."""
    part_id: str
    geometry: PartGeometry
    polygon: list[tuple[float, float]]
    area: float
    component_id: int
    component_name: str
    product_sku: Optional[str]
    variable_pockets: bool
    mating_role: str  # "tab", "receiver", "neutral"
    product_unit: Optional[int] = None


def classify_mating_role(
    component_id: int,
    mating_pairs: list[MatingPair],
    has_variable_pockets: bool,
) -> str:
    """Classify a component's role in the mating system.

    Returns:
        "tab" — component's tabs go into other components' pockets (cut first)
        "receiver" — component has variable pockets that receive tabs (cut last)
        "neutral" — no mating relationships affecting cut ordering
    """
    is_tab = any(mp.mating_component_id == component_id for mp in mating_pairs)
    is_pocket = any(mp.pocket_component_id == component_id for mp in mating_pairs)

    # Tab role takes priority: tabs must be cut before their receivers
    if is_tab:
        return "tab"

    if is_pocket and has_variable_pockets:
        return "receiver"

    return "neutral"


def detect_circular_mating(mating_pairs: list[MatingPair]) -> list[list[int]]:
    """Detect circular dependencies in mating pairs using DFS.

    A cycle means A tabs into B and B tabs into A (directly or transitively).
    Returns list of cycles as lists of component IDs.
    """
    # Build adjacency: mating (tab) component → pocket component
    graph: dict[int, list[int]] = {}
    all_nodes: set[int] = set()
    for mp in mating_pairs:
        tab = mp.mating_component_id
        pocket = mp.pocket_component_id
        graph.setdefault(tab, []).append(pocket)
        all_nodes.add(tab)
        all_nodes.add(pocket)

    cycles = []
    WHITE, GRAY, BLACK = 0, 1, 2
    color = {node: WHITE for node in all_nodes}
    path = []

    def dfs(node):
        color[node] = GRAY
        path.append(node)

        for neighbor in graph.get(node, []):
            if color[neighbor] == GRAY:
                cycle_start = path.index(neighbor)
                cycles.append(list(path[cycle_start:]))
            elif color[neighbor] == WHITE:
                dfs(neighbor)

        path.pop()
        color[node] = BLACK

    for node in all_nodes:
        if color[node] == WHITE:
            dfs(node)

    return cycles


def _polygon_area(points: list[tuple[float, float]]) -> float:
    """Calculate polygon area using shoelace formula."""
    n = len(points)
    if n < 3:
        return 0.0
    area = 0.0
    for i in range(n):
        j = (i + 1) % n
        area += points[i][0] * points[j][1]
        area -= points[j][0] * points[i][1]
    return abs(area) / 2.0


def _extract_product_sku(part_id: str, component_name: str) -> Optional[str]:
    """Extract the product SKU prefix from a part_id.

    Part ID formats (see order_processor.py):
        "SHELF-01_tabletop_003" → product_sku="SHELF-01"
        "tabletop_003"          → product_sku=None (component-only)
        "repl_tabletop_003"     → product_sku=None (replenishment)
        "fill_tabletop_003"     → product_sku=None (fill)
    """
    idx = part_id.find(component_name)
    if idx <= 0:
        return None
    prefix = part_id[:idx].rstrip('_')
    if not prefix or prefix in ('repl', 'fill'):
        return None
    return prefix


def compute_mating_clusters(mating_pairs: list[MatingPair]) -> dict[int, int]:
    """Map component_id -> cluster_id for components in mating relationships.

    Uses union-find on pocket_component_id <-> mating_component_id to identify
    connected component groups. Components not in any mating pair are absent
    from the result.

    Returns:
        {component_id: cluster_root_id}
    """
    if not mating_pairs:
        return {}

    parent: dict[int, int] = {}

    def find(x: int) -> int:
        if x not in parent:
            parent[x] = x
        while parent[x] != x:
            parent[x] = parent[parent[x]]  # path compression
            x = parent[x]
        return x

    def union(a: int, b: int) -> None:
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[ra] = rb

    for mp in mating_pairs:
        union(mp.pocket_component_id, mp.mating_component_id)

    return {cid: find(cid) for cid in parent}


def _mp_field(mp, name, default=None):
    """Get a field from a mating pair, whether it's a dict or object."""
    if isinstance(mp, dict):
        return mp.get(name, default)
    return getattr(mp, name, default)


def fetch_mating_pairs(db) -> list[MatingPair]:
    """Fetch and convert mating pairs from a database/API source.

    Handles both dict and object representations from the API.
    Returns empty list if unavailable.
    """
    if not hasattr(db, 'get_all_mating_pairs'):
        return []
    try:
        raw_pairs = db.get_all_mating_pairs()
        return [
            MatingPair(
                pocket_component_id=_mp_field(mp, 'pocket_component_id'),
                mating_component_id=_mp_field(mp, 'mating_component_id'),
                pocket_index=_mp_field(mp, 'pocket_index', 0),
                clearance_inches=_mp_field(mp, 'clearance_inches', 0.0079),
                product_sku=_mp_field(mp, 'product_sku', ''),
            )
            for mp in raw_pairs
        ]
    except Exception:
        logger.exception("Failed to fetch mating pairs")
        return []


def enrich_parts(
    parts: list[tuple[str, PartGeometry]],
    db,
    product_comp_qty: dict[tuple[str, str], int] = None,
    product_unit_map: dict[str, int] = None,
    _components: list = None,
    _mating_pairs: list = None,
) -> tuple[list[EnrichedPart], list[MatingPair]]:
    """Enrich parts with metadata from the database.

    Args:
        parts: List of (part_id, PartGeometry) tuples
        db: Database or APIClient instance with get_all_component_definitions()
            and optionally get_all_mating_pairs()
        product_comp_qty: Optional pre-built {(sku, component_name): quantity} map.
            If provided, skips the get_all_products() call.
        _components: Optional pre-fetched component definitions. If provided,
            skips the db.get_all_component_definitions() call.
        _mating_pairs: Optional pre-fetched mating pairs (already MatingPair
            objects). If provided, skips the db.get_all_mating_pairs() call.

    Returns:
        Tuple of (enriched parts list, mating pairs list).
    """
    if _components is not None:
        components = _components
    else:
        components = db.get_all_component_definitions()
    comp_by_name = {c.name: c for c in components}

    # Build product component quantity lookup for unit numbering
    if product_comp_qty is None:
        product_comp_qty = {}
        if hasattr(db, 'get_all_products'):
            try:
                for product in db.get_all_products():
                    for pc in product.components:
                        product_comp_qty[(product.sku, pc.component_name)] = pc.quantity
            except Exception:
                logger.exception("Failed to build product component quantity map")

    # Fetch mating pairs if available (APIClient has them, local SQLite may not)
    if _mating_pairs is not None:
        mating_pairs = _mating_pairs
    else:
        mating_pairs = fetch_mating_pairs(db)

    # Check for circular mating (log warning if found)
    if mating_pairs:
        cycles = detect_circular_mating(mating_pairs)
        if cycles:
            print(f"Warning: Circular mating dependencies detected: {cycles}")

    enriched = []
    for part_id, geom in parts:
        if not geom.polygons:
            continue

        polygon = geom.polygons[0]
        area = _polygon_area(polygon)

        # Strip trailing instance number to get base name for matching
        comp_name_base = re.sub(r'_\d+$', '', part_id)

        # Match to component definition (exact name first, then substring)
        comp = comp_by_name.get(comp_name_base)
        if not comp:
            for name, c in comp_by_name.items():
                if name in part_id:
                    comp = c
                    break

        if not comp:
            enriched.append(EnrichedPart(
                part_id=part_id,
                geometry=geom,
                polygon=polygon,
                area=area,
                component_id=0,
                component_name=comp_name_base,
                product_sku=None,
                variable_pockets=False,
                mating_role="neutral",
            ))
            continue

        variable_pockets = getattr(comp, 'variable_pockets', False)
        product_sku = _extract_product_sku(part_id, comp.name)

        # Use mating_role from component definition if available,
        # otherwise fall back to mating_pairs-based classification
        role = getattr(comp, 'mating_role', None)
        if not role or role == "neutral":
            # Filter mating pairs to this part's product for correct classification
            relevant_pairs = [mp for mp in mating_pairs if mp.product_sku == product_sku] if product_sku else mating_pairs
            role = classify_mating_role(comp.id, relevant_pairs, variable_pockets)

        # Compute product unit index — prefer explicit map from order processor
        product_unit = None
        if product_sku:
            if product_unit_map and part_id in product_unit_map:
                product_unit = product_unit_map[part_id]
            else:
                # Fallback: compute from instance numbering (works for base products)
                m = re.search(r'_(\d+)$', part_id)
                if m:
                    instance = int(m.group(1))
                    qty = product_comp_qty.get((product_sku, comp.name), 1)
                    product_unit = (instance - 1) // qty

        enriched.append(EnrichedPart(
            part_id=part_id,
            geometry=geom,
            polygon=polygon,
            area=area,
            component_id=comp.id,
            component_name=comp.name,
            product_sku=product_sku,
            variable_pockets=variable_pockets,
            mating_role=role,
            product_unit=product_unit,
        ))

    return enriched, mating_pairs

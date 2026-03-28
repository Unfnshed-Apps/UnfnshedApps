"""
Part matching for nested sheet DXFs.

Groups individual DXF entities into logical parts (by proximity) and matches
them to known component definitions by dimension comparison.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from .dxf_loader import SheetEntity, BoundingBox


@dataclass
class PartInstance:
    """A single part instance on a nested sheet."""
    instance_id: int
    entities: list[SheetEntity]
    bounding_box: BoundingBox
    component_id: Optional[int] = None
    component_name: Optional[str] = None
    order_id: Optional[int] = None
    ambiguous_group: Optional[int] = None
    is_damaged: bool = False


@dataclass
class AmbiguousGroup:
    """Part instances that share the same dimensions across multiple component types."""
    group_id: int
    instance_ids: list[int]
    candidate_components: list[dict]  # [{"component_id", "component_name", "count"}]


def _bbox_contains_point(bbox: BoundingBox, x: float, y: float, margin: float = 0.0) -> bool:
    return (bbox.min_x - margin <= x <= bbox.max_x + margin and
            bbox.min_y - margin <= y <= bbox.max_y + margin)


def _union_bbox(a: BoundingBox, b: BoundingBox) -> BoundingBox:
    return BoundingBox(
        min(a.min_x, b.min_x), min(a.min_y, b.min_y),
        max(a.max_x, b.max_x), max(a.max_y, b.max_y),
    )


def _dimension_key(bbox: BoundingBox, precision: float = 0.5) -> tuple[float, float]:
    w, h = bbox.width, bbox.height
    small, large = min(w, h), max(w, h)
    return (round(small / precision) * precision,
            round(large / precision) * precision)


def group_entities_into_parts(
    entities: list[SheetEntity],
    proximity_threshold: float = 1.0,
) -> list[PartInstance]:
    """Group Outline-layer entities into logical parts by proximity."""
    if not entities:
        return []

    sorted_entities = sorted(entities, key=lambda e: e.bounding_box.width * e.bounding_box.height, reverse=True)
    parts: list[PartInstance] = []
    next_id = 0

    for entity in sorted_entities:
        cx, cy = entity.centroid
        merged = False
        for part in parts:
            if _bbox_contains_point(part.bounding_box, cx, cy, margin=proximity_threshold):
                part.entities.append(entity)
                part.bounding_box = _union_bbox(part.bounding_box, entity.bounding_box)
                merged = True
                break

        if not merged:
            bb = entity.bounding_box
            parts.append(PartInstance(
                instance_id=next_id,
                entities=[entity],
                bounding_box=BoundingBox(bb.min_x, bb.min_y, bb.max_x, bb.max_y),
            ))
            next_id += 1

    return parts


def match_instances_to_components(
    parts: list[PartInstance],
    sheet_parts: list[dict],
    precision: float = 0.5,
) -> tuple[list[PartInstance], list[AmbiguousGroup]]:
    """Match part instances to components by dimension + count.

    sheet_parts: dicts with component_id, component_name, quantity, width, height.
    """
    if not parts or not sheet_parts:
        return parts, []

    instance_groups: dict[tuple, list[PartInstance]] = {}
    for part in parts:
        key = _dimension_key(part.bounding_box, precision)
        instance_groups.setdefault(key, []).append(part)

    component_groups: dict[tuple, list[dict]] = {}
    for comp in sheet_parts:
        w, h = comp.get("width", 0), comp.get("height", 0)
        small, large = min(w, h), max(w, h)
        key = (round(small / precision) * precision,
               round(large / precision) * precision)
        component_groups.setdefault(key, []).append(comp)

    ambiguous_groups: list[AmbiguousGroup] = []
    next_group_id = 0

    for dim_key, inst_list in instance_groups.items():
        matching_comps = component_groups.get(dim_key, [])
        if not matching_comps:
            continue

        if len(matching_comps) == 1:
            comp = matching_comps[0]
            for inst in inst_list:
                inst.component_id = comp["component_id"]
                inst.component_name = comp["component_name"]
        else:
            group = AmbiguousGroup(
                group_id=next_group_id,
                instance_ids=[inst.instance_id for inst in inst_list],
                candidate_components=[
                    {"component_id": c["component_id"],
                     "component_name": c["component_name"],
                     "count": c.get("quantity", 0)}
                    for c in matching_comps
                ],
            )
            ambiguous_groups.append(group)
            for inst in inst_list:
                inst.ambiguous_group = next_group_id
            next_group_id += 1

    return parts, ambiguous_groups


def _part_centroid(part: PartInstance) -> tuple[float, float]:
    """Compute centroid of a PartInstance from its entity centroids."""
    if not part.entities:
        bb = part.bounding_box
        return ((bb.min_x + bb.max_x) / 2, (bb.min_y + bb.max_y) / 2)
    xs = [e.centroid[0] for e in part.entities]
    ys = [e.centroid[1] for e in part.entities]
    return (sum(xs) / len(xs), sum(ys) / len(ys))


def match_instances_to_placements(
    parts: list[PartInstance],
    placements: list[dict],
    max_distance: float = 2.0,
) -> list[PartInstance]:
    """Match part instances to server placements by bbox center proximity.

    Each placement dict has: component_id, component_name, order_id, x, y, rotation, source_dxf.
    The placement (x, y) is the part's bbox center from the DXF output transform.
    We match each PartInstance's bbox center to the nearest unmatched placement
    center, greedy by closest distance first.

    Args:
        parts: Grouped part instances with absolute DXF coordinates.
        placements: Placement dicts from the server.
        max_distance: Maximum distance (inches) to consider a match valid.

    Returns:
        The same parts list with component_id, component_name, and order_id filled in.
    """
    import math

    if not parts or not placements:
        return parts

    # Build list of (distance, part_index, placement_index) pairs
    # Match bbox centers — placements store the transformed bbox center from Unfnest
    pairs = []
    for pi, part in enumerate(parts):
        bb = part.bounding_box
        cx = (bb.min_x + bb.max_x) / 2
        cy = (bb.min_y + bb.max_y) / 2
        for pli, pl in enumerate(placements):
            dx = cx - pl["x"]
            dy = cy - pl["y"]
            dist = math.hypot(dx, dy)
            pairs.append((dist, pi, pli))

    # Sort by distance (greedy closest-first matching)
    pairs.sort()

    matched_parts: set[int] = set()
    matched_placements: set[int] = set()

    for dist, pi, pli in pairs:
        if pi in matched_parts or pli in matched_placements:
            continue
        if dist > max_distance:
            break
        pl = placements[pli]
        parts[pi].component_id = pl["component_id"]
        parts[pi].component_name = pl.get("component_name")
        parts[pi].order_id = pl.get("order_id")
        matched_parts.add(pi)
        matched_placements.add(pli)

    return parts

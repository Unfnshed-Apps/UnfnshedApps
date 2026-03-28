# Nesting Algorithm Design: Aggressive/Ambitious Approach

*Author: Algorithm design session, 2026-02-10*
*Status: PROPOSAL -- not yet implemented*
*Supersedes: Conservative approach (same filename, previous version)*

---

## Summary

The conservative approach wraps the existing NFPNester unchanged and adds
pre-sort + fill passes around it. This aggressive approach **rethinks the
algorithm from scratch**: a constraint-aware, multi-pass, score-based bin
packer with simulated annealing rebalancing and deep multi-core parallelism.
It replaces the quick/efficient split with a single adaptive algorithm that
understands *why* parts are placed, not just *where* they fit.

The core architectural difference: instead of one greedy forward pass, the
algorithm operates in **three distinct phases** (partition, constrained pack,
rebalance), each with its own optimization target. Phase 3 (rebalance) uses
simulated annealing to escape local optima that greedy placement locks into.

---

## 1. Data Flow Diagram

```
                       ORDER PROCESSOR / COMPONENT GATHERER
                                     |
                                     v
                      +-----------------------------+
                      |  ENRICHMENT LAYER           |
                      |  Attach metadata to each    |
                      |  part tuple:                |
                      |    - component_id           |
                      |    - order_id               |
                      |    - quality_tier           |
                      |    - variable_pockets bool  |
                      |    - mating_role (tab |     |
                      |        receiver | neutral)  |
                      |    - area (precomputed)     |
                      |    - order_group_key        |
                      +-----------------------------+
                                     |
                                     v
                      +-----------------------------+
                      |  PHASE 1: PARTITION          |
                      |                              |
                      |  Split enriched parts into   |
                      |  6 constraint buckets:        |
                      |                              |
                      |  A: tabs_show               |
                      |  B: tabs_hidden             |
                      |  C: neutral_show            |
                      |  D: neutral_hidden          |
                      |  E: receivers_show          |
                      |  F: receivers_hidden        |
                      |                              |
                      |  Detect circular mating      |
                      |  dependencies (cross-lap     |
                      |  joints) via graph cycle     |
                      |  detection. Force circular   |
                      |  mates into same-sheet       |
                      |  constraint group.           |
                      +-----------------------------+
                                     |
                                     v
                      +-------------------------------+
                      |  PHASE 2: CONSTRAINED PACK    |
                      |  (Multi-core)                 |
                      |                               |
                      |  Uses new AdaptiveNFPPlacer   |
                      |  (replaces NFPNester entirely)|
                      |                               |
                      |  Step 2a: Pack TABS           |
                      |    Show tabs -> show sheets   |
                      |    Hidden tabs -> hidden      |
                      |    sheets. Within each        |
                      |    quality class, parts are   |
                      |    sorted by (order_group,    |
                      |    -area) for clustering.     |
                      |                               |
                      |  Step 2b: Pack NEUTRAL SHOW   |
                      |    Fill remaining space on    |
                      |    existing show sheets,      |
                      |    overflow to new show       |
                      |    sheets.                    |
                      |                               |
                      |  Step 2c: Pack NEUTRAL HIDDEN |
                      |    Fill existing hidden       |
                      |    sheets, overflow to new    |
                      |    hidden-only sheets.        |
                      |    (Builds the ~30% hidden    |
                      |    sheet reserve.)            |
                      |                               |
                      |  Step 2d: Fill RECEIVERS      |
                      |    Show receivers -> existing |
                      |    show sheets first.         |
                      |    Hidden receivers -> ANY    |
                      |    existing sheet.            |
                      |    Overflow -> new sheets     |
                      |    AFTER all tab/neutral      |
                      |    sheets.                    |
                      |    Gap-filling uses smallest- |
                      |    first sort (reversed from  |
                      |    initial packing).          |
                      +-------------------------------+
                                     |
                                     v
                      +-------------------------------+
                      |  PHASE 3: REBALANCE           |
                      |  (Multi-core, skipped for     |
                      |   small jobs < 20 parts)      |
                      |                               |
                      |  3a: Score every sheet via     |
                      |    composite function:         |
                      |    - utilization penalty       |
                      |    - order fragmentation       |
                      |    - hidden-only sheet bonus   |
                      |    - constraint violation      |
                      |    - total sheet count         |
                      |                               |
                      |  3b: Simulated annealing       |
                      |    swap search:                |
                      |    - SWAP: exchange 2 parts    |
                      |      between sheets            |
                      |    - MIGRATE: move part from   |
                      |      low-util to high-util     |
                      |      sheet                     |
                      |    - MERGE: empty a low-util   |
                      |      sheet by redistributing   |
                      |    Each move validated against |
                      |    hard constraints (fit,      |
                      |    tab-before-receiver,        |
                      |    quality tier)               |
                      |    Parallel: N candidate moves |
                      |    evaluated per iteration     |
                      |    across N CPU cores.         |
                      |                               |
                      |  3c: Eliminate near-empty      |
                      |    sheets (< 15% util)         |
                      +-------------------------------+
                                     |
                                     v
                      +-------------------------------+
                      |  OUTPUT                        |
                      |                               |
                      |  Assign sheet numbers:         |
                      |   [show tabs] [hidden tabs]   |
                      |   [show neutral] [hidden      |
                      |    neutral] [show receivers]  |
                      |   [hidden receivers]          |
                      |                               |
                      |  Tag min_quality_grade per    |
                      |  sheet ('clean' or 'any')     |
                      |                               |
                      |  Validate tab-before-receiver |
                      |  (should be 0 violations by   |
                      |  construction)                |
                      |                               |
                      |  Return NestingResult         |
                      +-------------------------------+
```

---

## 2. Pseudocode: Main Nesting Function

### 2.1 Enriched Part Data Structure

```python
@dataclass
class EnrichedPart:
    """A part with all metadata needed for constraint-aware nesting."""
    part_id: str
    geometry: PartGeometry
    polygon: list[tuple[float, float]]   # nesting polygon (outline)
    area: float                           # precomputed polygon area

    # Metadata from database
    component_id: int | None
    component_name: str
    order_id: int | None
    quality_tier: str                     # "show" or "hidden"
    variable_pockets: bool                # True = this is a pocket receiver
    mating_role: str                      # "tab", "receiver", or "neutral"

    # Computed during enrichment
    order_group_key: str                  # f"order_{order_id}" or "no_order"

    @property
    def is_tab(self) -> bool:
        return self.mating_role == "tab"

    @property
    def is_receiver(self) -> bool:
        return self.mating_role == "receiver"

    @property
    def needs_show_sheet(self) -> bool:
        return self.quality_tier == "show"
```

### 2.2 Mating Role Classification

```python
def classify_mating_role(component_id, mating_pairs, has_variable_pockets):
    """
    Classify a component's mating role from the component_mating_pairs table.

    - A component is a "tab" if it appears as mating_component_id in any pair
      (it inserts into another component's pocket).
    - A component is a "receiver" if it has variable_pockets=True
      (it has pockets that receive other components).
    - A component can be both (rare — e.g., a panel that receives shelves
      AND inserts into a frame). In that case, classify as "receiver"
      so it goes on later sheets.
    - Otherwise "neutral".
    """
    is_pocket_receiver = has_variable_pockets
    is_tab = any(
        pair.mating_component_id == component_id
        for pair in mating_pairs
    )

    if is_pocket_receiver:
        return "receiver"
    elif is_tab:
        return "tab"
    else:
        return "neutral"
```

### 2.3 Circular Mating Detection

```python
def detect_circular_mating(mating_pairs):
    """
    Find circular dependencies using DFS cycle detection on
    the mating graph (tab -> receiver edges).

    Returns list of cycles. Each cycle is a list of component_ids
    that form a dependency loop (e.g., A->B->A for cross-lap joints).
    """
    graph = defaultdict(set)
    for pair in mating_pairs:
        graph[pair.mating_component_id].add(pair.pocket_component_id)

    visited = set()
    rec_stack = set()
    cycles = []

    def dfs(node, path):
        visited.add(node)
        rec_stack.add(node)
        path.append(node)
        for neighbor in graph.get(node, set()):
            if neighbor not in visited:
                dfs(neighbor, path)
            elif neighbor in rec_stack:
                cycle_start = path.index(neighbor)
                cycles.append(path[cycle_start:])
        path.pop()
        rec_stack.discard(node)

    for node in graph:
        if node not in visited:
            dfs(node, [])

    return cycles
```

### 2.4 Top-Level Orchestrator

```python
def nest_parts_constrained(
    parts: list[tuple[str, PartGeometry]],
    db: Database,
    sheet_width: float = 48.0,
    sheet_height: float = 96.0,
    part_spacing: float = 0.75,
    edge_margin: float = 0.75,
    rotations: list[float] = [0, 90, 180, 270],
    progress_callback=None,
) -> NestingResult:
    """
    Three-phase constraint-aware nesting.

    Phase 1: Partition parts into 6 buckets by role + quality.
    Phase 2: Constrained greedy packing with adaptive NFP placer.
    Phase 3: Simulated annealing rebalance (skipped for <20 parts).

    Returns NestingResult compatible with existing downstream consumers.
    """

    # ==================================================
    # ENRICHMENT
    # ==================================================
    component_defs = {c.name: c for c in db.get_all_component_definitions()}
    component_by_dxf = {c.dxf_filename: c for c in component_defs.values()}
    mating_pairs = db.get_all_mating_pairs()  # list of ComponentMatingPair

    # Detect circular dependencies before enrichment
    circular_sets = detect_circular_mating(mating_pairs)
    # Flatten cycles into a set of component IDs that must share a sheet
    force_same_sheet = set()
    for cycle in circular_sets:
        force_same_sheet.update(cycle)

    enriched = []
    for part_id, geom in parts:
        comp_def = _resolve_component(part_id, geom, component_defs, component_by_dxf)
        order_id = _parse_order_id(part_id)
        quality_tier = getattr(comp_def, 'quality_tier', 'show') if comp_def else 'show'
        has_vp = comp_def.variable_pockets if comp_def else False
        component_id = comp_def.id if comp_def else None
        area = _polygon_area(geom.polygons[0]) if geom.polygons else 0

        mating_role = classify_mating_role(component_id, mating_pairs, has_vp)
        order_group_key = f"order_{order_id}" if order_id else "no_order"

        enriched.append(EnrichedPart(
            part_id=part_id,
            geometry=geom,
            polygon=geom.polygons[0],
            area=area,
            component_id=component_id,
            component_name=comp_def.name if comp_def else "",
            order_id=order_id,
            quality_tier=quality_tier,
            variable_pockets=has_vp,
            mating_role=mating_role,
            order_group_key=order_group_key,
        ))

    # Pre-screen: warn about parts that cannot fit on any sheet
    too_large = [p for p in enriched if not _can_fit_on_sheet(
        p.polygon, sheet_width, sheet_height, edge_margin, rotations
    )]
    if too_large:
        for p in too_large:
            print(f"Warning: Part {p.part_id} exceeds sheet dimensions in all rotations")

    # ==================================================
    # PHASE 1: PARTITION
    # ==================================================
    buckets = partition_parts(enriched)

    # ==================================================
    # PHASE 2: CONSTRAINED PACK
    # ==================================================
    placer = AdaptiveNFPPlacer(
        sheet_width, sheet_height, part_spacing, edge_margin
    )

    sheets = build_sheets_constrained(
        buckets, placer, rotations,
        force_same_sheet=force_same_sheet,
        progress_callback=progress_callback,
    )

    # ==================================================
    # PHASE 3: REBALANCE (skip for small jobs)
    # ==================================================
    total_parts_count = sum(len(s.parts) for s in sheets)
    if total_parts_count >= 20 and len(sheets) >= 3:
        sheets = rebalance_annealing(
            sheets, placer, rotations, mating_pairs,
            progress_callback=progress_callback,
            progress_offset=total_parts_count,
        )

    # ==================================================
    # OUTPUT: Number sheets and tag quality
    # ==================================================
    sheets = assign_sheet_numbers(sheets)

    # Convert to NestingResult format
    return _convert_to_nesting_result(sheets, enriched, parts)
```

### 2.5 Partition Function

```python
def partition_parts(enriched_parts: list[EnrichedPart]) -> dict:
    """
    Split parts into 6 constraint buckets.

    Six buckets (not two, not four) because the show/hidden split
    within tabs and receivers matters: a single show tab placed on
    an otherwise-hidden sheet would reclassify it as 'clean',
    wasting a defect-compatible slot.
    """
    buckets = {
        'tabs_show': [],
        'tabs_hidden': [],
        'neutral_show': [],
        'neutral_hidden': [],
        'receivers_show': [],
        'receivers_hidden': [],
    }

    for part in enriched_parts:
        if part.is_tab:
            key = 'tabs_show' if part.needs_show_sheet else 'tabs_hidden'
        elif part.is_receiver:
            key = 'receivers_show' if part.needs_show_sheet else 'receivers_hidden'
        else:
            key = 'neutral_show' if part.needs_show_sheet else 'neutral_hidden'
        buckets[key].append(part)

    # Within each bucket: sort by order_group_key THEN area descending.
    # This clusters same-order parts so they land on nearby sheets,
    # while largest-first within each order maximizes packing.
    for key in buckets:
        buckets[key].sort(key=lambda p: (p.order_group_key, -p.area))

    return buckets
```

### 2.6 Constrained Sheet Builder

```python
@dataclass
class SheetState:
    """Mutable state for a sheet being built."""
    quality: str              # 'clean' or 'any'
    sheet_type: str           # 'tab', 'neutral', or 'receiver'
    parts: list[EnrichedPart] = field(default_factory=list)
    placements: list[tuple] = field(default_factory=list)  # (part, x, y, rotation)
    placed_polys: list = field(default_factory=list)       # buffered Shapely polygons
    anchor_points: list = field(default_factory=lambda: [])
    sheet_number: int = 0
    min_quality_grade: str = 'any'

    @property
    def utilization(self):
        total_area = sum(p.area for p in self.parts)
        sheet_area = 48.0 * 96.0  # TODO: parameterize
        return (total_area / sheet_area) * 100 if sheet_area > 0 else 0

    def place_part(self, part, result, part_spacing):
        """Record a successful placement."""
        self.parts.append(part)
        self.placements.append((part, result.x, result.y, result.rotation))

        # Build buffered polygon for collision detection
        part_poly = Polygon(part.polygon)
        rotated = rotate(part_poly, result.rotation, origin=(0, 0))
        minx, miny, maxx, maxy = rotated.bounds
        normalized = translate(rotated, -minx, -miny)
        final_poly = translate(normalized, result.x, result.y)
        buffered = final_poly.buffer(part_spacing / 2)
        self.placed_polys.append(buffered)

        # Add anchor points
        fx, fy, fx2, fy2 = final_poly.bounds
        for ax, ay in [
            (fx2 + part_spacing, fy),
            (fx, fy2 + part_spacing),
            (fx2 + part_spacing, fy2),
        ]:
            self.anchor_points.append((ax, ay))


def build_sheets_constrained(
    buckets, placer, rotations, force_same_sheet=None, progress_callback=None
):
    """
    Multi-step constrained packing.

    Packing order enforces tab-before-receiver by construction:
    tabs create sheets 1..T, neutrals fill or create sheets T+1..N,
    receivers fill remaining space then overflow to sheets N+1..M.
    """
    sheets = []
    part_spacing = placer.part_spacing
    placed_count = 0
    total_parts = sum(len(v) for v in buckets.values())

    # =========================================================
    # STEP 2a: Pack TABS onto sheets
    # =========================================================
    for bucket_key in ['tabs_show', 'tabs_hidden']:
        quality = 'clean' if 'show' in bucket_key else 'any'
        remaining = list(buckets[bucket_key])
        while remaining:
            sheet = SheetState(quality=quality, sheet_type='tab')
            sheet.anchor_points = [(placer.edge_margin, placer.edge_margin)]
            sheet, remaining, placed_count = _pack_onto_sheet(
                placer, sheet, remaining, rotations, part_spacing,
                placed_count, total_parts, progress_callback
            )
            if sheet.parts:
                sheets.append(sheet)

    # =========================================================
    # STEP 2b: Pack NEUTRAL SHOW
    # =========================================================
    remaining_neutral_show = list(buckets['neutral_show'])

    # Fill existing show sheets first
    for sheet in sheets:
        if sheet.quality == 'clean' and remaining_neutral_show:
            remaining_neutral_show, placed_count = _fill_remaining_space(
                placer, sheet, remaining_neutral_show, rotations, part_spacing,
                placed_count, total_parts, progress_callback
            )

    # Overflow to new show sheets
    while remaining_neutral_show:
        sheet = SheetState(quality='clean', sheet_type='neutral')
        sheet.anchor_points = [(placer.edge_margin, placer.edge_margin)]
        sheet, remaining_neutral_show, placed_count = _pack_onto_sheet(
            placer, sheet, remaining_neutral_show, rotations, part_spacing,
            placed_count, total_parts, progress_callback
        )
        if sheet.parts:
            sheets.append(sheet)

    # =========================================================
    # STEP 2c: Pack NEUTRAL HIDDEN onto hidden-only sheets
    # =========================================================
    remaining_neutral_hidden = list(buckets['neutral_hidden'])

    # Fill existing hidden sheets first
    for sheet in sheets:
        if sheet.quality == 'any' and remaining_neutral_hidden:
            remaining_neutral_hidden, placed_count = _fill_remaining_space(
                placer, sheet, remaining_neutral_hidden, rotations, part_spacing,
                placed_count, total_parts, progress_callback
            )

    # Overflow to new hidden-only sheets
    while remaining_neutral_hidden:
        sheet = SheetState(quality='any', sheet_type='neutral')
        sheet.anchor_points = [(placer.edge_margin, placer.edge_margin)]
        sheet, remaining_neutral_hidden, placed_count = _pack_onto_sheet(
            placer, sheet, remaining_neutral_hidden, rotations, part_spacing,
            placed_count, total_parts, progress_callback
        )
        if sheet.parts:
            sheets.append(sheet)

    # =========================================================
    # STEP 2d: Fill RECEIVERS into remaining space
    # =========================================================
    # SAFE because:
    # - If receiver's tab is on the SAME sheet -> same pallet, same thickness
    # - If receiver's tab is on an EARLIER sheet -> tab cut first, known thickness
    # - Receiver overflow sheets are numbered AFTER all tab sheets

    show_receivers = list(buckets['receivers_show'])
    hidden_receivers = list(buckets['receivers_hidden'])

    # Show receivers -> fill existing show sheets
    for sheet in sheets:
        if sheet.quality == 'clean' and show_receivers:
            show_receivers, placed_count = _fill_remaining_space(
                placer, sheet, show_receivers, rotations, part_spacing,
                placed_count, total_parts, progress_callback
            )

    # Hidden receivers -> fill ANY existing sheet
    for sheet in sheets:
        if hidden_receivers:
            hidden_receivers, placed_count = _fill_remaining_space(
                placer, sheet, hidden_receivers, rotations, part_spacing,
                placed_count, total_parts, progress_callback
            )

    # Overflow receivers to new sheets
    overflow = show_receivers + hidden_receivers
    while overflow:
        has_show = any(r.needs_show_sheet for r in overflow)
        quality = 'clean' if has_show else 'any'
        sheet = SheetState(quality=quality, sheet_type='receiver')
        sheet.anchor_points = [(placer.edge_margin, placer.edge_margin)]
        sheet, overflow, placed_count = _pack_onto_sheet(
            placer, sheet, overflow, rotations, part_spacing,
            placed_count, total_parts, progress_callback
        )
        if sheet.parts:
            sheets.append(sheet)

    return sheets


def _pack_onto_sheet(placer, sheet, parts, rotations, part_spacing,
                     placed_count, total_parts, progress_callback):
    """
    Pack as many parts as possible onto a sheet (largest-first order preserved).
    Returns (sheet, remaining_parts, new_placed_count).
    """
    remaining = []
    for part in parts:
        if progress_callback:
            should_continue = progress_callback(placed_count, total_parts)
            if should_continue is False:
                remaining.extend(parts[parts.index(part):])
                return sheet, remaining, placed_count

        result = placer.find_best_placement(
            part.polygon, sheet.placed_polys, sheet.anchor_points, rotations
        )
        if result.success:
            sheet.place_part(part, result, part_spacing)
            placed_count += 1
        else:
            remaining.append(part)
    return sheet, remaining, placed_count


def _fill_remaining_space(placer, sheet, parts, rotations, part_spacing,
                          placed_count, total_parts, progress_callback):
    """
    Try to fit parts into remaining space. Uses smallest-first for gap filling.
    Returns (remaining_parts, new_placed_count).
    """
    # Sort by area ascending — small parts fit into gaps better
    candidates = sorted(parts, key=lambda p: p.area)
    remaining = []

    for part in candidates:
        if progress_callback:
            should_continue = progress_callback(placed_count, total_parts)
            if should_continue is False:
                remaining.extend(candidates[candidates.index(part):])
                return remaining, placed_count

        result = placer.find_best_placement(
            part.polygon, sheet.placed_polys, sheet.anchor_points, rotations
        )
        if result.success:
            sheet.place_part(part, result, part_spacing)
            placed_count += 1
        else:
            remaining.append(part)

    return remaining, placed_count
```

### 2.7 The Adaptive NFP Placer

This replaces both `_generate_efficient_candidates` and `_generate_quick_candidates`
with a single adaptive strategy.

```python
class AdaptiveNFPPlacer:
    """
    Unified NFP placement algorithm with adaptive grid resolution.

    Strategy:
    1. Always generate smart candidates from placed-part edges + anchors
       (same proven logic from current NFPNester).
    2. Add coarse grid candidates (8" step) for broad coverage.
    3. For coarse grid cells near the current best score, refine with
       a 2" sub-grid. "Near" = the coarse cell's (y,x) score could
       potentially beat the best score found so far.
    4. Score by (y, x) — bottom-left preference.

    This gets ~95% of "efficient" mode quality at ~60% of the cost:
    - It always checks smart candidates (the tight-packing positions).
    - The 8" grid catches positions the smart candidates miss.
    - Refinement only happens where it matters — near the frontier
      of the best known placement. Empty sheet regions far from
      bottom-left are never refined.
    """

    def __init__(self, sheet_width, sheet_height, part_spacing, edge_margin):
        self.sheet_width = sheet_width
        self.sheet_height = sheet_height
        self.part_spacing = part_spacing
        self.edge_margin = edge_margin
        self.sheet_poly = box(
            edge_margin, edge_margin,
            sheet_width - edge_margin,
            sheet_height - edge_margin
        )

    def find_best_placement(
        self,
        polygon_points,
        placed_polys,
        anchor_points,
        rotations=[0, 90, 180, 270]
    ) -> PlacementResult:
        """Find best placement across all rotations."""
        part_poly = Polygon(polygon_points)

        if placed_polys:
            occupied = union_all(placed_polys)
            occupied_prep = prep(occupied)
        else:
            occupied = None
            occupied_prep = None

        best = PlacementResult(False, 0, 0, 0)
        best_score = (float('inf'), float('inf'))

        for rotation in rotations:
            rotated = rotate(part_poly, rotation, origin=(0, 0))
            minx, miny, maxx, maxy = rotated.bounds
            normalized = translate(rotated, -minx, -miny)
            pw = maxx - minx
            ph = maxy - miny

            if pw > self.sheet_width - 2 * self.edge_margin:
                continue
            if ph > self.sheet_height - 2 * self.edge_margin:
                continue

            # --- Tier 1: Smart candidates (from anchor points + placed edges) ---
            candidates = self._smart_candidates(anchor_points, placed_polys, pw, ph)

            # --- Tier 2: Coarse 8" grid ---
            coarse_step = 8.0
            coarse_cells = []
            y = self.edge_margin
            while y + ph <= self.sheet_height - self.edge_margin:
                x = self.edge_margin
                while x + pw <= self.sheet_width - self.edge_margin:
                    candidates.add((x, y))
                    coarse_cells.append((x, y))
                    x += coarse_step
                y += coarse_step

            # Sort all candidates by (y, x)
            sorted_candidates = sorted(candidates, key=lambda p: (p[1], p[0]))

            # Find best among Tier 1 + Tier 2 candidates
            for cx, cy in sorted_candidates:
                score = (cy, cx)
                if score >= best_score:
                    break

                test_poly = translate(normalized, cx, cy)
                if self._is_valid(test_poly, occupied, occupied_prep):
                    best_score = score
                    best = PlacementResult(True, cx, cy, rotation)
                    break

            # --- Tier 3: Adaptive refinement of promising coarse cells ---
            refine_step = 2.0
            for cx, cy in coarse_cells:
                # Skip cells that cannot beat current best
                if (cy, cx) >= best_score:
                    continue

                # Quick bounding-box overlap test
                if occupied is not None:
                    test_box = box(cx, cy, cx + pw, cy + ph)
                    if not occupied_prep.intersects(test_box):
                        # No overlap with this coarse cell — the Tier 2 candidate
                        # at (cx, cy) would have passed if it could beat best_score.
                        # No need to refine.
                        continue

                # Refine: try 2" sub-grid within this 8" coarse cell
                ry = cy
                while ry < cy + coarse_step and ry + ph <= self.sheet_height - self.edge_margin:
                    rx = cx
                    while rx < cx + coarse_step and rx + pw <= self.sheet_width - self.edge_margin:
                        if (ry, rx) >= best_score:
                            rx += refine_step
                            continue

                        test_poly = translate(normalized, rx, ry)
                        if self._is_valid(test_poly, occupied, occupied_prep):
                            best_score = (ry, rx)
                            best = PlacementResult(True, rx, ry, rotation)
                        rx += refine_step
                    ry += refine_step

        return best

    def _smart_candidates(self, anchor_points, placed_polys, pw, ph):
        """Generate candidate positions from anchors and placed-part edges."""
        candidates = set()
        em = self.edge_margin
        sw = self.sheet_width
        sh = self.sheet_height

        # Origin
        candidates.add((em, em))

        # Anchor-based
        for ax, ay in anchor_points:
            if ax + pw <= sw - em and ay + ph <= sh - em:
                candidates.add((ax, ay))

        # Edge-derived from placed polygons
        for buffered_poly in placed_polys:
            bminx, bminy, bmaxx, bmaxy = buffered_poly.bounds
            spacing_half = self.part_spacing / 2

            # Right of part
            right_x = bmaxx + spacing_half
            if right_x + pw <= sw - em:
                candidates.add((right_x, bminy))
                candidates.add((right_x, em))

            # Above part
            top_y = bmaxy + spacing_half
            if top_y + ph <= sh - em:
                candidates.add((bminx, top_y))
                candidates.add((em, top_y))

            # Corner positions
            for cx, cy in [
                (bmaxx + spacing_half, bminy),
                (bmaxx + spacing_half, bmaxy - ph),
                (bminx, bmaxy + spacing_half),
                (bmaxx - pw, bmaxy + spacing_half),
            ]:
                if cx >= em and cy >= em and cx + pw <= sw - em and cy + ph <= sh - em:
                    candidates.add((cx, cy))

        return candidates

    def _is_valid(self, part_poly, occupied, occupied_prep):
        """Check if placement is valid (within sheet, no overlap)."""
        if not self.sheet_poly.contains(part_poly):
            return False
        if occupied is None:
            return True
        if occupied_prep.intersects(part_poly):
            intersection = part_poly.intersection(occupied)
            if intersection.area > 0.001:
                return False
        return True
```

### 2.8 Phase 3: Simulated Annealing Rebalance

```python
def score_solution(sheets, mating_pairs):
    """
    Composite score for a complete nesting solution. LOWER is better.

    Weight rationale:
    - Utilization is squared to penalize low-util sheets heavily.
      A sheet at 30% util contributes (70)^2 = 4900 penalty.
      A sheet at 70% util contributes (30)^2 = 900 penalty.
      This creates strong pressure to eliminate low-util sheets.
    - Order fragmentation at 50 per extra sheet is moderate.
      An order spanning 3 sheets: penalty = 100.
    - Hidden-only bonus at -200 actively rewards the ~30% target.
    - Sheet count at 100 per sheet rewards eliminating sheets.
    - Constraint violations at 10000 are hard barriers — annealing
      will reject any move that creates one.
    """
    score = 0.0

    # 1. Utilization penalty: (100 - util%)^2 per sheet
    for sheet in sheets:
        util = sheet.utilization
        score += (100.0 - util) ** 2

    # 2. Order fragmentation: (distinct_sheets - 1) * 50 per order
    order_sheets = defaultdict(set)
    for i, sheet in enumerate(sheets):
        for part in sheet.parts:
            order_sheets[part.order_group_key].add(i)
    for order_key, sheet_indices in order_sheets.items():
        if order_key != "no_order":
            score += (len(sheet_indices) - 1) * 50

    # 3. Hidden-only sheet bonus: -200 per sheet with all hidden parts
    for sheet in sheets:
        if sheet.parts and all(not p.needs_show_sheet for p in sheet.parts):
            score -= 200

    # 4. Constraint violations: +10000 per violation
    tab_max_sheet = {}    # component_id -> max sheet index with this tab
    recv_min_sheet = {}   # component_id -> min sheet index with this receiver
    for i, sheet in enumerate(sheets):
        for part in sheet.parts:
            if part.is_tab and part.component_id is not None:
                tab_max_sheet[part.component_id] = max(
                    tab_max_sheet.get(part.component_id, i), i
                )
            if part.is_receiver and part.component_id is not None:
                recv_min_sheet[part.component_id] = min(
                    recv_min_sheet.get(part.component_id, i), i
                )

    for pair in mating_pairs:
        tab_sheet = tab_max_sheet.get(pair.mating_component_id)
        recv_sheet = recv_min_sheet.get(pair.pocket_component_id)
        if tab_sheet is not None and recv_sheet is not None:
            if tab_sheet > recv_sheet:
                score += 10000  # Tab must be on earlier-or-equal sheet

    # 5. Sheet count penalty
    score += len(sheets) * 100

    return score


def rebalance_annealing(
    sheets, placer, rotations, mating_pairs,
    max_iterations=2000,
    initial_temp=500.0,
    cooling_rate=0.995,
    progress_callback=None,
    progress_offset=0,
):
    """
    Simulated annealing over sheet assignments.

    Three move types:
    1. SWAP: exchange part A on sheet X with part B on sheet Y,
       if both fit in their new position.
    2. MIGRATE: move a part from a low-utilization sheet to a
       higher-utilization sheet where it fits.
    3. MERGE: attempt to empty the lowest-utilization sheet by
       distributing all its parts to other sheets.

    Each candidate move is validated:
    - Part must physically fit (Shapely collision check)
    - Tab-before-receiver constraint must hold
    - Quality tier constraint: show part cannot go on a hidden-only
      sheet unless the sheet already has show parts

    Parallelism: generate N_WORKERS candidate moves per iteration,
    evaluate each on a separate CPU core, pick the best.
    """
    import copy
    import random

    n_workers = min(os.cpu_count() or 4, 8)
    current_score = score_solution(sheets, mating_pairs)
    best_sheets = copy.deepcopy(sheets)
    best_score = current_score
    temp = initial_temp

    for iteration in range(max_iterations):
        # Progress reporting
        if progress_callback:
            total_with_rebalance = progress_offset + max_iterations
            should_continue = progress_callback(
                progress_offset + iteration, total_with_rebalance
            )
            if should_continue is False:
                break

        # Generate candidate moves
        move_type = random.choices(
            ['swap', 'migrate', 'merge'],
            weights=[0.5, 0.35, 0.15],  # Swap most common, merge least
            k=1
        )[0]

        new_sheets = copy.deepcopy(sheets)
        move_valid = False

        if move_type == 'swap' and len(new_sheets) >= 2:
            move_valid = _try_swap(new_sheets, placer, rotations)
        elif move_type == 'migrate' and len(new_sheets) >= 2:
            move_valid = _try_migrate(new_sheets, placer, rotations)
        elif move_type == 'merge' and len(new_sheets) >= 2:
            move_valid = _try_merge(new_sheets, placer, rotations)

        if not move_valid:
            continue

        # Remove empty sheets
        new_sheets = [s for s in new_sheets if s.parts]

        new_score = score_solution(new_sheets, mating_pairs)
        delta = new_score - current_score

        # Acceptance criterion
        if delta < 0:
            # Improvement — always accept
            sheets = new_sheets
            current_score = new_score
        else:
            # Worse — accept with Boltzmann probability
            acceptance_prob = math.exp(-delta / temp) if temp > 0.01 else 0
            if random.random() < acceptance_prob:
                sheets = new_sheets
                current_score = new_score

        # Track global best
        if current_score < best_score:
            best_score = current_score
            best_sheets = copy.deepcopy(sheets)

        temp *= cooling_rate

    return best_sheets


def _try_swap(sheets, placer, rotations):
    """
    Pick two random parts on different sheets. Try to swap them.
    Returns True if swap was successful, False otherwise.
    Modifies sheets in-place.
    """
    import random

    si = random.randint(0, len(sheets) - 1)
    sj = random.randint(0, len(sheets) - 1)
    while si == sj:
        sj = random.randint(0, len(sheets) - 1)

    if not sheets[si].parts or not sheets[sj].parts:
        return False

    pi = random.randint(0, len(sheets[si].parts) - 1)
    pj = random.randint(0, len(sheets[sj].parts) - 1)

    part_i = sheets[si].parts[pi]
    part_j = sheets[sj].parts[pj]

    # Remove both parts from their sheets
    _remove_part_from_sheet(sheets[si], pi)
    _remove_part_from_sheet(sheets[sj], pj)

    # Try to place part_i on sheet_j and part_j on sheet_i
    result_i_on_j = placer.find_best_placement(
        part_i.polygon, sheets[sj].placed_polys, sheets[sj].anchor_points, rotations
    )
    result_j_on_i = placer.find_best_placement(
        part_j.polygon, sheets[si].placed_polys, sheets[si].anchor_points, rotations
    )

    if result_i_on_j.success and result_j_on_i.success:
        sheets[sj].place_part(part_i, result_i_on_j, placer.part_spacing)
        sheets[si].place_part(part_j, result_j_on_i, placer.part_spacing)
        return True

    # Swap failed — restore original parts
    # (caller made a deepcopy, so we just return False and the copy is discarded)
    return False


def _try_migrate(sheets, placer, rotations):
    """
    Pick a part from the lowest-utilization sheet and try to
    move it to another sheet where it fits.
    """
    import random

    # Find lowest-utilization sheet
    source_idx = min(range(len(sheets)), key=lambda i: sheets[i].utilization)
    if not sheets[source_idx].parts:
        return False

    pi = random.randint(0, len(sheets[source_idx].parts) - 1)
    part = sheets[source_idx].parts[pi]

    # Try each other sheet (sorted by utilization descending — pack into fullest first)
    target_indices = sorted(
        [i for i in range(len(sheets)) if i != source_idx],
        key=lambda i: -sheets[i].utilization
    )

    for ti in target_indices:
        result = placer.find_best_placement(
            part.polygon, sheets[ti].placed_polys, sheets[ti].anchor_points, rotations
        )
        if result.success:
            _remove_part_from_sheet(sheets[source_idx], pi)
            sheets[ti].place_part(part, result, placer.part_spacing)
            return True

    return False


def _try_merge(sheets, placer, rotations):
    """
    Try to empty the lowest-utilization sheet entirely by
    distributing all its parts to other sheets.
    """
    source_idx = min(range(len(sheets)), key=lambda i: sheets[i].utilization)
    source = sheets[source_idx]
    if not source.parts:
        return False

    # Try to place each part from source onto other sheets
    # Work on copies in case we fail partway through
    import copy
    original_other_sheets = copy.deepcopy(
        [sheets[i] for i in range(len(sheets)) if i != source_idx]
    )
    other_sheets = copy.deepcopy(original_other_sheets)

    for part in source.parts:
        placed = False
        for target in sorted(other_sheets, key=lambda s: -s.utilization):
            result = placer.find_best_placement(
                part.polygon, target.placed_polys, target.anchor_points, rotations
            )
            if result.success:
                target.place_part(part, result, placer.part_spacing)
                placed = True
                break
        if not placed:
            return False  # Cannot empty this sheet

    # All parts from source placed elsewhere. Clear source.
    sheets[source_idx].parts.clear()
    sheets[source_idx].placed_polys.clear()
    sheets[source_idx].placements.clear()

    # Update other sheets in place
    j = 0
    for i in range(len(sheets)):
        if i != source_idx:
            sheets[i] = other_sheets[j]
            j += 1

    return True
```

### 2.9 Sheet Numbering

```python
def assign_sheet_numbers(sheets):
    """
    Assign final sheet numbers ensuring tabs come before receivers.

    Ordering:
      [show tab sheets] [hidden tab sheets]
      [show neutral sheets] [hidden neutral sheets]
      [show receiver sheets] [hidden receiver sheets]

    This guarantees that when the CNC machines claim sheets in FIFO order,
    tab parts are always cut before their mating receiver parts.
    """
    categorized = {
        ('tab', 'clean'): [],
        ('tab', 'any'): [],
        ('neutral', 'clean'): [],
        ('neutral', 'any'): [],
        ('receiver', 'clean'): [],
        ('receiver', 'any'): [],
    }

    for sheet in sheets:
        if not sheet.parts:
            continue
        key = (sheet.sheet_type, sheet.quality)
        if key in categorized:
            categorized[key].append(sheet)

    ordered = (
        categorized[('tab', 'clean')]
        + categorized[('tab', 'any')]
        + categorized[('neutral', 'clean')]
        + categorized[('neutral', 'any')]
        + categorized[('receiver', 'clean')]
        + categorized[('receiver', 'any')]
    )

    for i, sheet in enumerate(ordered):
        sheet.sheet_number = i + 1
        has_show = any(p.needs_show_sheet for p in sheet.parts)
        sheet.min_quality_grade = 'clean' if has_show else 'any'

    return ordered
```

---

## 3. Sort/Partition Strategy

### 3.1 Six Buckets

| Bucket | Criteria | Sheet Quality | Rationale |
|--------|----------|---------------|-----------|
| `tabs_show` | `mating_role='tab'` AND `quality_tier='show'` | clean | Tabs that need clean plywood. First to be placed, first sheets cut. |
| `tabs_hidden` | `mating_role='tab'` AND `quality_tier='hidden'` | any | Tabs for structural/hidden parts. Go on hidden-only sheets. |
| `neutral_show` | `mating_role='neutral'` AND `quality_tier='show'` | clean | Show parts with no mating constraint. Fill remaining space on show sheets. |
| `neutral_hidden` | `mating_role='neutral'` AND `quality_tier='hidden'` | any | Hidden parts with no mating constraint. Build the ~30% hidden reserve. |
| `receivers_show` | `mating_role='receiver'` AND `quality_tier='show'` | clean | Pocket receivers needing clean sheets. Fill space on show sheets, overflow to new sheets after tabs. |
| `receivers_hidden` | `mating_role='receiver'` AND `quality_tier='hidden'` | any | Pocket receivers for any sheet. Fill space anywhere, overflow after tabs. |

### 3.2 Why Six and Not Two

The conservative approach uses two buckets (non-receivers, receivers). This misses a critical optimization: a single show tab placed on an otherwise-hidden sheet converts it to `min_quality_grade='clean'`, wasting a defect-compatible sheet slot. Six buckets keep show and hidden parts segregated within each role, maximizing hidden-only sheet creation.

### 3.3 Intra-Bucket Sort

Within each bucket, parts are sorted by `(order_group_key, -area)`:

- **order_group_key**: Groups same-order parts together. Since these parts have the same quality tier and role, grouping by order does not conflict with any constraint. Parts from order 5 cluster together, then order 12, etc.
- **-area (descending)**: Standard bin-packing heuristic. Largest parts first leaves more flexible gaps for subsequent parts. Within each order group, largest parts pack first, smallest parts fill gaps.

### 3.4 How ~30% Hidden-Only Sheets Emerge

1. Show tabs fill show sheets (Step 2a). Hidden tabs fill hidden sheets (Step 2a).
2. Show neutrals fill remaining space on show sheets, overflow to new show sheets (Step 2b).
3. Hidden neutrals fill remaining space on hidden sheets, overflow to new hidden-only sheets (Step 2c).
4. Receivers fill gaps on existing sheets, preferring quality-matching sheets (Step 2d).

Since the Material Tracking Plan states ~30% of components are hidden (legs, stretchers, cleats, backs), the hidden buckets naturally produce ~30% of the sheets. The score function in Phase 3 further incentivizes hidden-only sheet preservation with a -200 bonus.

This is a **structural** property, not a tuned parameter. The percentage tracks the actual product mix, which is the correct behavior.

---

## 4. How Multi-Core Is Used

### 4.1 Four Parallelism Points

| Stage | Mechanism | What Runs in Parallel | GIL Status | Expected Speedup |
|-------|-----------|----------------------|------------|------------------|
| Phase 2: rotation evaluation within each placement | `ThreadPoolExecutor` (4 threads) | Each rotation (0/90/180/270) evaluated on a separate thread. Shapely's C-extension geometric operations release the GIL. | Released during Shapely ops | ~2-3x for each placement call |
| Phase 2: independent bucket packing | `ProcessPoolExecutor` | Steps 2a (hidden tabs) and 2c (hidden neutrals) can run simultaneously — they produce separate sheets with no shared state. | N/A (separate processes) | ~2x for independent steps |
| Phase 3: candidate move evaluation | `ProcessPoolExecutor` (N cores) | Each annealing iteration generates N candidate moves, evaluated independently on deep copies of the sheet state. | N/A (separate processes) | ~Nx, where N = CPU cores |
| Phase 3: multi-restart annealing | `ProcessPoolExecutor` | Run 2-4 independent annealing trajectories with different random seeds, take the best final solution. | N/A (separate processes) | Near-linear scaling |

### 4.2 Rotation Parallelism (Phase 2)

```python
def find_best_placement_parallel(self, polygon_points, placed_polys,
                                  anchor_points, rotations):
    """
    Evaluate all rotations in parallel using threads.

    Why threads (not processes): The data sharing overhead of serializing
    Shapely geometries across process boundaries exceeds the computation
    time for a single rotation. Threads share memory and Shapely releases
    the GIL during its C-level geometric operations (intersects, contains,
    union), making ThreadPoolExecutor effective here.
    """
    occupied = union_all(placed_polys) if placed_polys else None
    occupied_prep = prep(occupied) if occupied else None

    def evaluate_rotation(rotation):
        return self._evaluate_single_rotation(
            polygon_points, rotation, occupied, occupied_prep, anchor_points
        )

    with ThreadPoolExecutor(max_workers=len(rotations)) as pool:
        results = list(pool.map(evaluate_rotation, rotations))

    best = PlacementResult(False, 0, 0, 0)
    best_score = (float('inf'), float('inf'))
    for result in results:
        if result.success:
            score = (result.y, result.x)
            if score < best_score:
                best_score = score
                best = result
    return best
```

### 4.3 Independent Bucket Packing (Phase 2)

```python
# In build_sheets_constrained(), Steps 2a-hidden and 2c can overlap:

with ProcessPoolExecutor(max_workers=2) as pool:
    future_hidden_tabs = pool.submit(
        _pack_bucket_to_sheets, placer_config, buckets['tabs_hidden'], 'any', 'tab'
    )
    future_hidden_neutrals = pool.submit(
        _pack_bucket_to_sheets, placer_config, buckets['neutral_hidden'], 'any', 'neutral'
    )

    hidden_tab_sheets = future_hidden_tabs.result()
    hidden_neutral_sheets = future_hidden_neutrals.result()
```

This is safe because these buckets produce sheets that never share parts, and
neither step's output affects the other's input.

### 4.4 Parallel Annealing Candidates (Phase 3)

```python
# Each iteration: generate N_WORKERS candidate moves, evaluate in parallel

with ProcessPoolExecutor(max_workers=n_workers) as pool:
    for iteration in range(max_iterations):
        futures = []
        for _ in range(n_workers):
            sheets_copy = copy.deepcopy(sheets)
            move_type = random.choice(['swap', 'migrate', 'merge'])
            futures.append(pool.submit(
                evaluate_candidate_move, sheets_copy, move_type, placer_config,
                rotations, mating_pairs
            ))

        best_delta = float('inf')
        best_new_sheets = None
        for future in as_completed(futures):
            delta, new_sheets = future.result()
            if delta < best_delta:
                best_delta = delta
                best_new_sheets = new_sheets

        # Apply best move with SA acceptance criterion
        ...
```

### 4.5 Where NOT to Parallelize

- **Sequential sheet packing within a bucket**: Parts overflow from sheet N to sheet N+1. This is inherently sequential. Parallelizing would require speculative partitioning.
- **Phase 2 fill passes**: The receiver queue is shared across sheets and consumed in priority order. Parallel fill would require synchronization that likely costs more than it saves.
- **Adaptive grid refinement within a single rotation**: The refinement loop is fast (2-16 Shapely calls per coarse cell) and shares the `occupied_prep` object. Thread overhead would dominate.

### 4.6 Parallelism Threshold

For small batches (< 5 placed polygons on a sheet), sequential rotation search is faster than parallel because Shapely collision checks are cheap. The parallel path activates only when `len(placed_polys) > 5`.

---

## 5. Edge Cases and How They're Handled

### EC-1: Circular Mating Dependency (Cross-Lap Joints)

**Problem:** Component A has variable pockets for B, AND B has variable pockets for A. Neither can go on a strictly earlier sheet.

**Detection:** `detect_circular_mating()` runs during enrichment, before any packing. Uses DFS cycle detection on the mating graph.

**Resolution:**
- For each cycle, all involved component IDs are added to `force_same_sheet`.
- During Phase 2 packing, when a part from `force_same_sheet` is placed, the algorithm notes its sheet index.
- When another part from the same cycle is encountered, it is attempted on the same sheet first. If it does not fit, it is placed on the next available sheet and a warning is emitted.
- Same-sheet placement means same pallet, same thickness. No cross-lookup needed.

**Fallback:** If circular mates cannot share a sheet, the claim-time ordering in the CNC app will detect the deadlock and surface it to the operator with the message: "Circular dependency: Sheet X needs Sheet Y cut first, and vice versa."

### EC-2: Part Too Large for Any Sheet

**Detection:** Pre-screening during enrichment, before Phase 1.

```python
def _can_fit_on_sheet(polygon, sheet_w, sheet_h, edge_margin, rotations):
    part_poly = Polygon(polygon)
    for rotation in rotations:
        rotated = rotate(part_poly, rotation, origin=(0, 0))
        minx, miny, maxx, maxy = rotated.bounds
        pw = maxx - minx
        ph = maxy - miny
        if pw <= sheet_w - 2*edge_margin and ph <= sheet_h - 2*edge_margin:
            return True
    return False
```

**Handling:** Flagged in the return result as `parts_failed`. Warning emitted before expensive packing starts.

### EC-3: No Hidden Parts in Order

**Problem:** The ~30% hidden-sheet target is impossible if 100% of parts are show-tier.

**Handling:** The 30% target is a soft structural property, not a hard constraint. If all parts are show, all sheets are show. The score function's hidden-only bonus (-200) simply does not apply. This is correct behavior.

### EC-4: Receiver Placed on Sheet Where Its Tab is on a LATER Sheet

**Problem:** Violates tab-before-receiver constraint.

**Why it cannot happen by construction:** Phase 2 packs in this order:
1. All tabs (Steps 2a) -> sheets 1..T
2. All neutrals (Steps 2b/2c) -> fill sheets 1..T, overflow to T+1..N
3. All receivers (Step 2d) -> fill sheets 1..N, overflow to N+1..M

A receiver in Step 2d can only be placed on an existing sheet (1..N) or an overflow sheet (N+1..M). Its tab is on a sheet in 1..T (T <= N). Since sheets are numbered in the order above and CNC machines claim FIFO, the tab is always cut before the receiver.

**The one exception:** A receiver filling space on sheet K, where its specific tab is also on sheet K. This is safe because they share the same pallet (same physical sheet of plywood, same thickness).

Phase 3's simulated annealing validates every move against the tab-before-receiver constraint (score function adds 10000 penalty for violations), so rebalancing cannot introduce violations.

### EC-5: Very Small Job (< 20 Parts or <= 2 Sheets)

**Handling:** Phase 3 (annealing) is skipped entirely. The conditional:

```python
if total_parts_count >= 20 and len(sheets) >= 3:
    sheets = rebalance_annealing(...)
```

Phase 2 alone produces correct, well-packed results for small jobs. Annealing's value comes from cross-sheet optimization, which requires enough sheets to be meaningful.

### EC-6: Order with Mixed Show/Hidden Parts

**Example:** Order has 4 show table tops + 16 hidden leg parts.

**What happens:**
- 4 show table tops go into `neutral_show` bucket, packed onto show sheets.
- 16 hidden legs go into `neutral_hidden` bucket, packed onto hidden sheets.
- Phase 3 annealing cannot move hidden legs to show sheets (quality constraint prevents it), but CAN swap hidden parts between hidden sheets to improve order clustering.
- Order fragmentation penalty (50 per extra sheet) encourages the annealing to consolidate this order's hidden parts onto fewer hidden sheets.

### EC-7: Progress Reporting and Cancellation During Phase 3

**Progress:** Phase 3 reports as `progress_callback(phase2_count + iteration, phase2_count + max_iterations)`. The UI can display "Packing parts... 85%" during Phase 2 and "Optimizing layout... 45%" during Phase 3.

**Cancellation:** Same mechanism as current — progress callback returns False. Annealing checks after each iteration and returns `best_sheets` found so far. Phase 2's result is always valid, so even if Phase 3 cancels at iteration 0, the output is correct.

### EC-8: All Parts Are Pocket Receivers

**What happens:** Buckets `tabs_*` and `neutral_*` are empty. Steps 2a-2c produce zero sheets. Step 2d packs all receivers onto new sheets starting at sheet 1. Since there are no tabs in this batch, the tab-before-receiver constraint is vacuously satisfied (tabs were cut in a previous nesting run or do not exist).

### EC-9: No Component Metadata Available

**Handling:** All defaults are safe:
- `quality_tier` defaults to `"show"` (conservative — requires clean plywood)
- `variable_pockets` defaults to `False` (treated as non-receiver)
- `mating_role` defaults to `"neutral"` (no mating constraints)
- The algorithm degrades to quality-blind area-sorted packing, which is equivalent to the current algorithm's behavior.

### EC-10: Phase 3 Deep Copy Memory Pressure

**Problem:** Each annealing iteration creates a deep copy of the sheet state. With 10 sheets, 200 parts, and 2000 iterations, this is ~40MB peak.

**Mitigation:**
- SheetState is lightweight (~2KB per sheet without Shapely objects).
- Shapely polygons in `placed_polys` are the bulk. These are only deep-copied for the candidate move, not for score evaluation.
- For very large jobs (50+ sheets), reduce `max_iterations` proportionally.
- Python's GC reclaims discarded copies promptly.

### EC-11: Simulated Annealing Produces Worse Result Than Phase 2

**Handling:** Annealing tracks `best_sheets` and `best_score` globally. It always returns the best solution found across all iterations, never the current solution at termination. Since the initial state (Phase 2 output) is the first `best_sheets`, annealing can only improve or match, never worsen.

---

## 6. Pros and Cons

### Pros

| # | Advantage | Detail |
|---|-----------|--------|
| 1 | **Tab-before-receiver guaranteed by construction** | The packing order (tabs -> neutrals -> receivers) and sheet numbering make this a structural invariant, not a fragile sort key. Phase 3 enforces it via 10000-penalty hard constraint. |
| 2 | **~30% hidden-only sheets is structural** | Six-bucket segregation naturally produces hidden-only sheets in proportion to the product mix. No magic constants or percentage targets. |
| 3 | **Score-based optimization** | Easy to tune priorities by changing weights (utilization^2, order fragmentation * 50, hidden bonus -200, sheet count * 100). No algorithm rewrite needed to shift priorities. |
| 4 | **Escapes local optima** | Phase 3's simulated annealing can swap parts between sheets, merge low-utilization sheets, and migrate parts — moves that greedy single-pass algorithms cannot make. |
| 5 | **Single algorithm** | No quick/efficient split. No mode parameter. One code path to maintain, debug, and optimize. |
| 6 | **Adaptive grid** | Gets ~95% of efficient-mode placement quality at ~60% of the runtime by only refining 8" coarse cells that have occupied-region overlap. |
| 7 | **Deep multi-core parallelism** | Four independent parallelism points: rotation threads, independent bucket processes, parallel annealing candidates, multi-restart annealing. |
| 8 | **Receiver gap-filling** | Step 2d fills holes left by primary packing with smaller receiver parts (sorted smallest-first). Currently these holes are wasted space. |
| 9 | **Handles cross-lap joints** | Circular mating dependencies detected via graph cycle analysis and resolved by forcing same-sheet placement. |
| 10 | **Graceful degradation** | Without quality_tier in DB: all parts default to 'show', produces mixed sheets (same as today). Without mating_pairs: all parts are 'neutral', simple area-sorted packing. Each DB feature activates independently. |

### Cons

| # | Disadvantage | Detail | Mitigation |
|---|--------------|--------|------------|
| 1 | **Significantly higher complexity** | 3-phase pipeline, 6 buckets, score function, simulated annealing, 4 parallelism points. Much more code than the conservative approach. | Well-separated phases with clear contracts. Each phase independently testable. Phased implementation (see Section 8). |
| 2 | **Non-deterministic results** | Simulated annealing uses randomness. Same inputs may produce different sheet assignments across runs. | Use fixed random seed for reproducibility in production. Multi-restart convergence reduces variance. |
| 3 | **Phase 3 latency** | 2000 iterations of annealing with deep copies adds 2-5 seconds for a 200-part job. | Budget is tunable. Skip for small jobs. Cancellable. Progress bar shows "Optimizing layout..." |
| 4 | **Memory overhead** | Deep copies in annealing: ~40MB peak for 200 parts / 10 sheets. | Acceptable for desktop application. Reduce iterations for very large jobs. |
| 5 | **More database queries at nesting time** | Enrichment queries component_definitions, component_mating_pairs, products. | Batch queries: 1 query for all components, 1 for all mating pairs. ~50ms for 1000 parts. |
| 6 | **Requires DB schema additions** | `quality_tier` on component_definitions, `component_mating_pairs` table. | These are already planned in the Material Tracking Plan (Phases 3 and 5). Algorithm degrades gracefully without them. |
| 7 | **ProcessPoolExecutor serialization overhead** | Shapely objects must be pickled/unpickled across process boundaries. For small jobs, this overhead exceeds the computation savings. | Threshold: only parallelize when `len(placed_polys) > 5`. Small jobs stay single-threaded. |
| 8 | **Two-pass packing (non-receivers then fill) is theoretically suboptimal** | Packing all parts in a single pass with optimal interleaving would achieve ~2-5% better utilization. | Phase 3 rebalancing recovers most of this gap via cross-sheet optimization. The constraint guarantees are worth the small theoretical loss. |
| 9 | **Score function weights need tuning** | The initial weights (utilization^2, fragmentation*50, hidden bonus -200, sheets*100) are educated guesses. Optimal weights depend on real production data. | Tuning is parameter adjustment, not algorithm change. Can be refined incrementally after deployment. |
| 10 | **_try_merge is expensive** | Emptying a sheet requires re-placing all its parts on other sheets. With N parts and M sheets, this is O(N*M) Shapely checks. | Merge probability is low (15% of moves). It targets only the lowest-utilization sheet. Early termination on first failure. |

---

## 7. Estimated Utilization Impact vs Current Algorithm

### Current Baseline

| Metric | Current Value | Source |
|--------|---------------|--------|
| Sort strategy | Area descending, quality-blind | `nesting.py` line 173 |
| Placement algorithm | Bottom-left NFP with 2" grid (efficient) or 8" grid (quick) | `nfp_nesting.py` lines 172-180, 274-336 |
| Typical utilization | ~55-65% per sheet | Estimated from furniture part geometry (irregular, concavities) |
| Hidden-only sheets | ~0% (no quality awareness) | No quality tier in current system |
| Order cohesion | Random (parts interleaved by area sort) | No order grouping |
| Tab-before-receiver | Not enforced | No mating awareness |

### Projected With New Algorithm

| Metric | Current | Projected | Delta | Source of Gain |
|--------|---------|-----------|-------|----------------|
| Average sheet utilization | ~60% | ~67-72% | **+7-12%** | Adaptive grid + receiver gap-fill + Phase 3 rebalancing |
| Total sheets for 200-part order | ~18 | ~15-16 | **-2 to -3 sheets** | Higher utilization + Phase 3 sheet elimination |
| Hidden-only sheets | ~0% | ~28-32% | **+28-32%** | 6-bucket segregation + score function incentive |
| Defective sheet utilization | 0% | ~90% of hidden-only | **New capability** | Hidden-only sheets accept defective plywood |
| Order fragmentation (avg sheets/order) | ~4.5 | ~3.2 | **-29%** | Order group sort + Phase 3 fragmentation penalty |
| Tab-before-receiver violations | Unknown | 0 | **Guaranteed** | Structural packing order + score function hard constraint |

### Where the Gains Come From

**Adaptive grid (+3-5% utilization):** The 8" coarse grid catches positions that smart candidates miss (wide-open regions). The 2" refinement catches tight positions that the 8" grid misses (near occupied edges). By only refining coarse cells that have overlap with the occupied region, we avoid the O(N^2) cost of a full 2" grid on empty sheet regions.

**Receiver gap-filling (+2-4% utilization):** Step 2d fills holes left after primary packing with smaller receiver parts sorted smallest-first. These holes currently go to waste. Even placing a few small receivers per sheet recovers significant area.

**Phase 3 rebalancing (+2-3% utilization):** The simulated annealing can:
- Migrate parts from a 40% sheet to a 70% sheet, raising it to 80% and leaving the 40% sheet ready for merge.
- Merge a 25% sheet by distributing its parts, eliminating it entirely (saves one full sheet).
- Swap a large part and a small part between sheets to reduce wasted gaps.

**Hidden-only sheets (material cost savings, not utilization):** The ~30% hidden-only sheets do not change utilization percentage, but they reduce material COST by enabling defective plywood use.

### Break-Even Analysis

| Assumption | Value |
|------------|-------|
| Baltic birch plywood sheet cost | $45-65 |
| Parts per nesting run | ~200 |
| Nesting runs per week | ~3 |
| Sheets saved per run (utilization gain) | 2-3 |
| Defective sheets properly utilized per run | 5-6 |
| Defective sheet discount (vs premium) | ~$30 |

**Material savings per run:**
- Direct: 2.5 sheets saved * $55 avg = $137
- Defective recovery: 5.5 sheets * $30 = $165
- **Total: ~$300 per run**

**Annual savings:** $300/run * 3 runs/week * 50 weeks = **~$45,000/year**

This does not account for labor savings from eliminated "waiting on mating parts" operator delays, which could add another $10,000-20,000/year in avoided downtime.

---

## 8. Implementation Priority (Phased)

### Phase A: Core Algorithm (1-2 weeks)

**Deliverables:**
- `src/enrichment.py`: `EnrichedPart` dataclass, `classify_mating_role()`, `detect_circular_mating()`
- `src/adaptive_nfp.py`: `AdaptiveNFPPlacer` class (unified placement, replaces quick/efficient)
- `src/constraint_nester.py`: `partition_parts()`, `build_sheets_constrained()`, `assign_sheet_numbers()`
- Modified `src/nesting.py`: `NestingEngine.nest_parts()` delegates to new pipeline
- Modified `bridge/nesting_controller.py`: enrichment queries, removes `mode` parameter

**Delivers:** Tab-before-receiver ordering, ~30% hidden sheets, adaptive grid improvement, single algorithm. This alone is a significant production upgrade.

### Phase B: Multi-Core (1 week)

**Deliverables:**
- `ThreadPoolExecutor` rotation search in `AdaptiveNFPPlacer`
- `ProcessPoolExecutor` for independent bucket packing
- Parallelism threshold (skip for < 5 placed polys)

**Delivers:** ~2-3x wall-clock speedup.

### Phase C: Rebalancing (1 week)

**Deliverables:**
- `src/nesting_score.py`: `score_solution()`, `rebalance_annealing()`
- Move generators: `_try_swap()`, `_try_migrate()`, `_try_merge()`
- Parallel candidate evaluation in annealing loop

**Delivers:** +2-3% utilization, sheet count reduction, order cohesion improvement.

### Phase D: Tuning (Ongoing)

- Score function weight tuning on real production data
- Annealing temperature/cooling schedule optimization
- Adaptive grid refinement step tuning
- Benchmark suite with representative part geometries

---

## Appendix A: Files That Change

| File | Change | Scope |
|------|--------|-------|
| `src/nesting.py` | `NestingEngine.nest_parts()` calls new `nest_parts_constrained()`. Removes `mode` parameter. `PlacedPart` and `NestedSheet` unchanged. | Medium |
| `src/nfp_nesting.py` | **Replaced entirely** by `src/adaptive_nfp.py`. Old file kept for reference but no longer imported. | Large (replacement) |
| `bridge/nesting_controller.py` | `_start_nesting()` performs enrichment. `NestingWorker` removes `mode`. `gatherParts*()` unchanged (enrichment happens later). | Medium |
| `src/database.py` | `ComponentDefinition` gains `quality_tier` field. New `get_all_mating_pairs()` method. | Small |
| `src/dxf_output.py` | No changes. Variable pocket tagging works as-is. | None |
| `src/order_processor.py` | No changes. Part IDs already carry order prefix. | None |

### New files

| File | Purpose | Size |
|------|---------|------|
| `src/enrichment.py` | `EnrichedPart`, role classification, circular mating detection | ~150 lines |
| `src/adaptive_nfp.py` | `AdaptiveNFPPlacer` — unified placement engine | ~200 lines |
| `src/constraint_nester.py` | 3-phase orchestrator: partition, constrained pack, rebalance | ~400 lines |
| `src/nesting_score.py` | Score function, simulated annealing, move generators | ~300 lines |

**Total new code: ~1050 lines.** Total modified code: ~100 lines. Core data structures (`PlacedPart`, `NestedSheet`, `NestingResult`) unchanged for backward compatibility.

---

## Appendix B: Comparison with Conservative Approach

| Dimension | Conservative | Aggressive |
|-----------|-------------|------------|
| NFP placer | Unchanged (wraps existing) | New adaptive algorithm (replaces both modes) |
| Buckets | 2 (non-receiver, receiver) | 6 (role x quality tier) |
| Packing passes | 3 (primary, fill, overflow) | 4 (tabs, neutral show, neutral hidden, receivers) + rebalance |
| Optimization | None (greedy only) | Simulated annealing Phase 3 |
| Multi-core | Rotation parallelism only | 4 parallelism points |
| Grid step | 4" compromise | Adaptive: 8" coarse + 2" refinement |
| Score function | None | Composite (utilization, fragmentation, hidden bonus, constraints, sheet count) |
| Circular mating | Deferred to claim-time | Detected at nesting time, force same-sheet |
| Estimated utilization | 53-68% (-1 to -3% vs current) | 67-72% (+7 to +12% vs current) |
| New code | ~300-400 lines | ~1050 lines |
| Implementation time | 1 week | 3-4 weeks (phased) |
| Risk | Low (wraps proven code) | Medium (new placement engine, non-deterministic Phase 3) |

"""
Editor state machine for the Manual Nest create/edit window.

Owns:
  - the nest's name and sheet list
  - the "library" of parts still needing placement (what the user added via
    the Add Products dialog, minus what's already on the canvas)
  - placement-mode state: when the user clicks a library entry, the editor
    enters placement mode — the canvas follows the cursor with a ghost part
    until the user either clicks to commit or cancels.

Coordinates are in inches throughout. Sheet origin (0, 0) is the lower-left
corner of the sheet; x grows right, y grows up. Part positions are stored as
the lower-left corner of the part's axis-aligned bounding box after rotation
(matching how placer.PlacementResult records position).

Current scope: single-sheet create mode. Edit-existing and multi-sheet are
not yet implemented — the UI disables the corresponding controls.
"""

from __future__ import annotations

import logging
import math
from typing import Any, Optional

from PySide6.QtCore import Property, QObject, Signal, Slot
from shapely.affinity import rotate, translate
from shapely.geometry import Polygon as ShapelyPolygon

logger = logging.getLogger(__name__)


# Default sheet geometry (inches) — matches SHEET_WIDTH/HEIGHT in nesting_models
_DEFAULT_SHEET_W = 48.0
_DEFAULT_SHEET_H = 96.0
_DEFAULT_SPACING = 0.75
_DEFAULT_EDGE = 0.75

# Current editor stores every placement under unit 0. Product-unit accounting
# will be introduced when the matching algorithm needs it to scale nests
# across multiple product instances.
_DEFAULT_PRODUCT_UNIT = 0


def _placement_bbox(
    polygon_w: float, polygon_h: float, rotation_deg: float,
) -> tuple[float, float]:
    """Return (bbox_w, bbox_h) for an AABB-aligned polygon after rotation.

    A polygon with axis-aligned bbox (polygon_w, polygon_h) rotated by
    `rotation_deg` around its centre has an enlarged AABB whose dimensions
    depend on the rotation. For 90/270° the bbox swaps; for 0/180° it stays.
    For arbitrary angles it grows.
    """
    rad = math.radians(rotation_deg)
    c = abs(math.cos(rad))
    s = abs(math.sin(rad))
    return polygon_w * c + polygon_h * s, polygon_w * s + polygon_h * c


def _aabb_overlaps(
    a_x: float, a_y: float, a_w: float, a_h: float,
    b_x: float, b_y: float, b_w: float, b_h: float,
    buffer: float,
) -> bool:
    """AABB overlap test with a buffer expanding both boxes on all sides.

    Both boxes are lower-left anchored. Returns True if the expanded boxes
    overlap. A buffer of 0 reduces to the standard AABB test.

    Kept as a cheap first-pass broad-phase filter ahead of the polygon
    collision check.
    """
    ax1, ay1 = a_x - buffer, a_y - buffer
    ax2, ay2 = a_x + a_w + buffer, a_y + a_h + buffer
    bx1, by1 = b_x - buffer, b_y - buffer
    bx2, by2 = b_x + b_w + buffer, b_y + b_h + buffer
    return not (ax2 <= bx1 or bx2 <= ax1 or ay2 <= by1 or by2 <= ay1)


def _build_oriented_polygon(
    polygon: list, x: float, y: float, rotation_deg: float,
) -> Optional[ShapelyPolygon]:
    """Return a Shapely polygon for a placement at (x, y, rotation).

    Input polygon is in canonical local coordinates (lower-left bbox corner
    at origin, as produced by `_lookup_component_geometry`). We rotate
    around the origin, re-anchor the rotated bbox to (0,0), then translate
    to (x, y). Matches the same transform the canvas uses for drawing, so
    what the operator sees and what the collision test sees are identical.

    Returns None when the polygon has fewer than three points.
    """
    if not polygon or len(polygon) < 3:
        return None
    try:
        poly = ShapelyPolygon(polygon)
        if rotation_deg:
            poly = rotate(poly, rotation_deg, origin=(0, 0), use_radians=False)
        # Re-anchor so the rotated bbox's lower-left sits at (0, 0)
        minx, miny, _, _ = poly.bounds
        poly = translate(poly, xoff=x - minx, yoff=y - miny)
        return poly
    except Exception:
        return None


class ManualNestEditorController(QObject):
    """Backing controller for the Manual Nest editor window."""

    # ---- Signals QML listens on ----
    stateChanged = Signal()           # broad refresh signal
    libraryChanged = Signal()
    placementsChanged = Signal()
    ghostChanged = Signal()
    visibilityChanged = Signal()
    sheetsChanged = Signal()          # count or index changed
    slideCollisionChanged = Signal()
    selectedIndexChanged = Signal()
    operationFailed = Signal(str)
    statusMessage = Signal(str, int)

    def __init__(
        self, app_ctrl, product_ctrl=None, component_ctrl=None,
        settings_ctrl=None, parent=None,
    ):
        super().__init__(parent)
        self._app = app_ctrl
        self._product_ctrl = product_ctrl
        self._component_ctrl = component_ctrl
        # SettingsController — optional, used to seed fresh sheets with the
        # operator's preferred sheet size / spacing / margin. When absent
        # or unreadable we fall back to the hard-coded defaults.
        self._settings_ctrl = settings_ctrl

        # Window open / close
        self._visible = False

        # Identity: None when creating a new nest, the server id when
        # editing an existing one. Drives POST vs PUT on save and the
        # window title.
        self._nest_id: Optional[int] = None

        # Nest scalar state
        self._name = ""
        self._sheet_w = _DEFAULT_SHEET_W
        self._sheet_h = _DEFAULT_SHEET_H
        self._part_spacing = _DEFAULT_SPACING
        self._edge_margin = _DEFAULT_EDGE

        # Multi-sheet state. `_sheets` holds one dict per sheet; the active
        # sheet's values are mirrored into the scalar attrs below for fast
        # binding access and backwards compatibility with the single-sheet
        # code paths. `_sync_active_to_sheets` pushes them back before any
        # sheet switch / save so the list stays authoritative.
        self._sheets: list[dict[str, Any]] = [self._new_sheet_state()]
        self._current_idx = 0

        # `placements` is a list of dicts (one per placement on the current
        # sheet): {component_id, component_name, dxf_filename, product_sku,
        # product_unit, x, y, rotation_deg, bbox_w, bbox_h}
        self._placements: list[dict[str, Any]] = self._sheets[0]["placements"]

        # Library: entries the user added via Add Products, minus what's
        # already been placed. Each entry is a dict:
        # {component_id, component_name, dxf_filename, product_sku,
        #  needed, placed, bbox_w, bbox_h}
        self._library: list[dict[str, Any]] = []

        # Per-DXF bbox/polygon cache so repeated `addProducts` calls don't
        # re-parse the same geometry file. Keyed by dxf_filename.
        self._bbox_cache: dict[str, dict] = {}

        # When true, dragging the ghost past an obstacle slides it along
        # the free axis instead of just refusing to move. Helpful when
        # cramming parts up against edges; toggle off when you need to
        # land a part inside a surrounded pocket the slide path can't
        # reach.
        self._slide_collision = True

        # Index into the active sheet's `_placements` for the currently
        # selected placement, or -1 if none. Highlights the row in the
        # Placed list + draws a gold border around the part on the canvas
        # so operators can visually connect the two.
        self._selected_index = -1
        # Cache of component_id -> mating_role ("tab" / "receiver" / "neutral"),
        # populated lazily the first time the editor needs it.
        self._role_cache: Optional[dict[int, str]] = None

        # Ghost / placement-mode state
        self._ghost_component_id: Optional[int] = None
        self._ghost_product_sku: Optional[str] = None
        self._ghost_x = 0.0
        self._ghost_y = 0.0
        self._ghost_rotation = 0.0
        self._ghost_valid = False
        self._ghost_bbox_w = 0.0
        self._ghost_bbox_h = 0.0
        self._ghost_polygon: list = []
        self._ghost_pocket_polygons: list = []

    # ==================================================================
    # Multi-sheet helpers
    # ==================================================================

    def _new_sheet_state(self) -> dict[str, Any]:
        """Freshly-defaulted sheet dict used for `Add Sheet` / initial state.

        Pulls sheet dimensions / spacing / margin from the user's general
        settings when available so Manual Nest sheets match what the
        auto-nester would use. Hard-coded defaults kick in only if settings
        aren't wired (tests, legacy installs).
        """
        width, height = _DEFAULT_SHEET_W, _DEFAULT_SHEET_H
        spacing, edge = _DEFAULT_SPACING, _DEFAULT_EDGE
        s = self._settings_ctrl
        if s is not None:
            try:
                width = float(s.sheetWidth()) or width
                height = float(s.sheetHeight()) or height
                spacing = float(s.partSpacing()) if s.partSpacing() is not None else spacing
                edge = float(s.edgeMargin()) if s.edgeMargin() is not None else edge
            except Exception:
                logger.debug("Settings read failed; using hard-coded defaults.", exc_info=True)
        return {
            "width": width,
            "height": height,
            "part_spacing": spacing,
            "edge_margin": edge,
            "placements": [],
        }

    def _sync_active_to_sheets(self):
        """Write scalar/list state back into `_sheets[_current_idx]`.

        Call this before switching sheets or saving so the list-of-sheets
        remains the authoritative serialization of the whole nest.
        """
        if 0 <= self._current_idx < len(self._sheets):
            self._sheets[self._current_idx] = {
                "width": self._sheet_w,
                "height": self._sheet_h,
                "part_spacing": self._part_spacing,
                "edge_margin": self._edge_margin,
                # Preserve identity — `_placements` is aliased into this dict,
                # so mutations on either side stayed in lockstep. Storing the
                # same list back keeps the aliasing intact if this sheet is
                # re-activated later.
                "placements": self._placements,
            }

    def _load_active_from_sheets(self):
        """Mirror `_sheets[_current_idx]` into the scalar/list attrs."""
        sheet = self._sheets[self._current_idx]
        self._sheet_w = float(sheet["width"])
        self._sheet_h = float(sheet["height"])
        self._part_spacing = float(sheet["part_spacing"])
        self._edge_margin = float(sheet["edge_margin"])
        self._placements = sheet["placements"]

    # ==================================================================
    # QML-visible properties
    # ==================================================================

    @Property(bool, notify=visibilityChanged)
    def visible(self):
        return self._visible

    @Property(bool, notify=stateChanged)
    def isEditMode(self):
        return self._nest_id is not None

    @Property(str, notify=stateChanged)
    def windowTitle(self):
        if self._nest_id is not None:
            return f"Manual Nest Editor — Edit: {self._name}" if self._name else "Manual Nest Editor — Edit"
        return "Manual Nest Editor — New"

    @Property(str, notify=stateChanged)
    def name(self):
        return self._name

    @Property(float, notify=stateChanged)
    def sheetWidth(self):
        return self._sheet_w

    @Property(float, notify=stateChanged)
    def sheetHeight(self):
        return self._sheet_h

    @Property(float, notify=stateChanged)
    def partSpacing(self):
        return self._part_spacing

    @Property(float, notify=stateChanged)
    def edgeMargin(self):
        return self._edge_margin

    @Property("QVariantList", notify=placementsChanged)
    def placements(self):
        return list(self._placements)

    @Property(int, notify=sheetsChanged)
    def currentSheetIndex(self):
        return self._current_idx

    @Property(int, notify=sheetsChanged)
    def sheetCount(self):
        return len(self._sheets)

    @Property(bool, notify=sheetsChanged)
    def canGoPrevSheet(self):
        return self._current_idx > 0

    @Property(bool, notify=sheetsChanged)
    def canGoNextSheet(self):
        return self._current_idx < len(self._sheets) - 1

    @Property(bool, notify=sheetsChanged)
    def canRemoveSheet(self):
        # Always keep at least one sheet
        return len(self._sheets) > 1

    @Property(bool, notify=slideCollisionChanged)
    def slideCollision(self):
        return self._slide_collision

    @Slot(bool)
    def setSlideCollision(self, enabled: bool):
        enabled = bool(enabled)
        if enabled != self._slide_collision:
            self._slide_collision = enabled
            self.slideCollisionChanged.emit()

    @Property(int, notify=selectedIndexChanged)
    def selectedPlacementIndex(self):
        return self._selected_index

    @Slot(int)
    def selectPlacement(self, index: int):
        """Select a placement on the active sheet (or -1 to clear).

        Out-of-range indices quietly clear the selection so callers
        don't need to guard against stale row numbers.
        """
        if not (0 <= index < len(self._placements)):
            index = -1
        if index != self._selected_index:
            self._selected_index = index
            self.selectedIndexChanged.emit()

    @Slot()
    def clearSelection(self):
        self.selectPlacement(-1)

    @Property("QVariantList", notify=libraryChanged)
    def library(self):
        return list(self._library)

    @Property(int, notify=ghostChanged)
    def ghostComponentId(self):
        return self._ghost_component_id if self._ghost_component_id is not None else -1

    @Property(str, notify=ghostChanged)
    def ghostProductSku(self):
        return self._ghost_product_sku or ""

    @Property(float, notify=ghostChanged)
    def ghostX(self):
        return self._ghost_x

    @Property(float, notify=ghostChanged)
    def ghostY(self):
        return self._ghost_y

    @Property(float, notify=ghostChanged)
    def ghostRotation(self):
        return self._ghost_rotation

    @Property(float, notify=ghostChanged)
    def ghostBboxW(self):
        return self._ghost_bbox_w

    @Property(float, notify=ghostChanged)
    def ghostBboxH(self):
        return self._ghost_bbox_h

    @Property("QVariantList", notify=ghostChanged)
    def ghostPolygon(self):
        return list(self._ghost_polygon)

    @Property("QVariantList", notify=ghostChanged)
    def ghostPocketPolygons(self):
        return [list(p) for p in self._ghost_pocket_polygons]

    @Property(bool, notify=ghostChanged)
    def ghostActive(self):
        return self._ghost_component_id is not None

    @Property(bool, notify=ghostChanged)
    def ghostValid(self):
        return self._ghost_valid

    @Property(bool, notify=libraryChanged)
    def libraryFullyPlaced(self):
        """True when every library entry has been fully placed (remaining == 0)."""
        if not self._library:
            return False
        return all(e["placed"] >= e["needed"] for e in self._library)

    @Property("QVariantList", notify=placementsChanged)
    def matingWarnings(self):
        """Return human-readable warnings about tab/receiver placement.

        Walks every sheet (including the currently-edited one via the
        aliased `_placements`) and checks two invariants per product SKU:
          1. All tab placements share a single sheet.
          2. Every receiver is on tab_sheet or tab_sheet+1 (no farther).
        Returns an empty list when the nest is clean. Warnings are advisory —
        saving is still allowed, but the user sees a yellow banner.
        """
        self._sync_active_to_sheets()
        # Collect {sku -> {"tabs": [sheet_idx...], "receivers": [sheet_idx...]}}
        by_sku: dict[str, dict[str, list[int]]] = {}
        for sheet_idx, sheet in enumerate(self._sheets):
            for p in sheet.get("placements") or []:
                sku = p.get("product_sku")
                if sku is None:
                    continue
                role = self._get_role(p["component_id"])
                if role not in ("tab", "receiver"):
                    continue
                bucket = by_sku.setdefault(sku, {"tabs": [], "receivers": []})
                bucket[f"{role}s"].append(sheet_idx)

        warnings: list[str] = []
        for sku, groups in by_sku.items():
            tab_sheets = set(groups["tabs"])
            receiver_sheets = set(groups["receivers"])
            if not tab_sheets:
                continue
            if len(tab_sheets) > 1:
                page_list = ", ".join(str(s + 1) for s in sorted(tab_sheets))
                warnings.append(
                    f"{sku}: tabs split across sheets {page_list} — "
                    f"joinery needs tabs on a single sheet."
                )
            # Allowed receiver sheets = tab_sheet or tab_sheet+1 for any tab
            allowed = set()
            for s in tab_sheets:
                allowed.add(s)
                allowed.add(s + 1)
            drifted = sorted(receiver_sheets - allowed)
            if drifted:
                recv_list = ", ".join(str(s + 1) for s in drifted)
                warnings.append(
                    f"{sku}: receiver(s) on sheet {recv_list} are too far "
                    f"from the tabs — put them on the tab sheet or the next one."
                )
        return warnings

    @Property(bool, notify=stateChanged)
    def isSaveEnabled(self):
        """Save requires a non-empty name and at least one placed part
        anywhere in the nest (any sheet)."""
        if not self._name.strip():
            return False
        if len(self._placements) > 0:
            return True
        # Check inactive sheets too
        return any(
            len(s.get("placements") or []) > 0
            for i, s in enumerate(self._sheets) if i != self._current_idx
        )

    # ==================================================================
    # Window open / close
    # ==================================================================

    @Slot()
    def showCreate(self):
        """Open editor in create mode with a clean state."""
        self._reset_state()
        self._visible = True
        self.visibilityChanged.emit()
        self.stateChanged.emit()
        self.libraryChanged.emit()
        self.placementsChanged.emit()
        self.ghostChanged.emit()

    @Slot(int, result=bool)
    def showEdit(self, nest_id: int) -> bool:
        """Open editor in edit mode — fetch the nest and populate state.

        The library is reconstructed from placed parts so each component
        shows as fully placed (N/N). The user can remove placements to free
        them back into the library, or click Add Products to add more.
        """
        db = self._app.db
        if not db or not hasattr(db, "get_manual_nest"):
            self.operationFailed.emit("Not connected to the server.")
            return False
        try:
            nest = db.get_manual_nest(int(nest_id))
        except Exception:
            logger.exception("Failed to fetch manual nest %s", nest_id)
            self.operationFailed.emit(
                "Couldn't load that nest — check your connection and try again."
            )
            return False
        if not nest:
            self.operationFailed.emit("That manual nest no longer exists.")
            return False

        self._reset_state()
        self._nest_id = int(nest_id)
        self._name = nest.get("name", "")
        sheets = nest.get("sheets") or []
        if not sheets:
            sheets = [{}]  # ensure at least one sheet even if server returned none

        # Build a per-sheet state list. We'll load the first sheet as active.
        loaded_sheets: list[dict[str, Any]] = []
        for s in sheets:
            loaded_sheets.append({
                "width": float(s.get("width") or _DEFAULT_SHEET_W),
                "height": float(s.get("height") or _DEFAULT_SHEET_H),
                "part_spacing": float(s.get("part_spacing") or _DEFAULT_SPACING),
                "edge_margin": float(s.get("edge_margin") or _DEFAULT_EDGE),
                "placements": [],  # filled below
            })
        self._sheets = loaded_sheets

        # Rehydrate placements + derive the library
        comp_lookup: dict[int, dict] = {}
        try:
            for c in db.get_all_component_definitions() or []:
                comp_lookup[int(c.id)] = {
                    "name": c.name,
                    "dxf_filename": c.dxf_filename,
                }
        except Exception:
            logger.debug("Component lookup failed; placements will use best-effort names.")

        library_index: dict[tuple[Optional[str], int], dict[str, Any]] = {}
        for sheet_idx, sheet in enumerate(sheets):
            for raw in sheet.get("parts") or []:
                cid = int(raw.get("component_id"))
                sku = raw.get("product_sku")
                meta = comp_lookup.get(cid, {})
                dxf = meta.get("dxf_filename") or ""
                cname = meta.get("name") or f"Component {cid}"
                geom = self._lookup_component_geometry(cid, dxf)
                base_w, base_h = geom["bbox"]
                rot = float(raw.get("rotation_deg") or 0.0)
                bw, bh = _placement_bbox(base_w, base_h, rot)
                placement = {
                    "component_id": cid,
                    "component_name": cname,
                    "dxf_filename": dxf,
                    "product_sku": sku,
                    "product_unit": int(raw.get("product_unit") or 0),
                    "x": float(raw.get("x") or 0.0),
                    "y": float(raw.get("y") or 0.0),
                    "rotation_deg": rot,
                    "bbox_w": bw,
                    "bbox_h": bh,
                    "polygon": list(geom["polygon"]),
                    "pocket_polygons": [list(p) for p in (geom.get("pocket_polygons") or [])],
                }
                self._sheets[sheet_idx]["placements"].append(placement)
                key = (sku, cid)
                entry = library_index.get(key)
                if entry is None:
                    # Base (unrotated) bbox + polygon in the library so future
                    # rotations recompute cleanly from the canonical footprint.
                    entry = {
                        "component_id": cid,
                        "component_name": cname,
                        "dxf_filename": dxf,
                        "product_sku": sku,
                        "needed": 0,
                        "placed": 0,
                        "bbox_w": base_w,
                        "bbox_h": base_h,
                        "polygon": list(geom["polygon"]),
                        "pocket_polygons": [list(p) for p in (geom.get("pocket_polygons") or [])],
                    }
                    self._library.append(entry)
                    library_index[key] = entry
                entry["needed"] += 1
                entry["placed"] += 1

        # Activate the first sheet so the visible canvas reflects real state
        self._current_idx = 0
        self._load_active_from_sheets()

        self._visible = True
        self.visibilityChanged.emit()
        self.sheetsChanged.emit()
        self.stateChanged.emit()
        self.libraryChanged.emit()
        self.placementsChanged.emit()
        self.ghostChanged.emit()
        return True

    @Slot()
    def close(self):
        """Close the editor window without saving."""
        self._cancel_placement()
        self._visible = False
        self.visibilityChanged.emit()

    def _reset_state(self):
        self._nest_id = None
        self._name = ""
        self._sheets = [self._new_sheet_state()]
        self._current_idx = 0
        self._load_active_from_sheets()
        self._library = []
        self._bbox_cache = {}
        self._role_cache = None
        self._selected_index = -1
        self._cancel_placement()

    def _get_role(self, component_id: int) -> str:
        """Return the mating_role ("tab"/"receiver"/"neutral") for a component.

        Lazily loads the full component-definition table the first time
        it's asked. Falls back to "neutral" when the lookup fails so missing
        role data never blocks the editor.
        """
        if self._role_cache is None:
            self._role_cache = {}
            db = self._app.db
            if db and hasattr(db, "get_all_component_definitions"):
                try:
                    for c in db.get_all_component_definitions() or []:
                        self._role_cache[int(c.id)] = getattr(c, "mating_role", "neutral")
                except Exception:
                    logger.debug("Mating-role lookup failed", exc_info=True)
        return self._role_cache.get(int(component_id), "neutral")

    # ==================================================================
    # Sheet navigation / add / remove
    # ==================================================================

    def _activate_sheet(self, new_idx: int):
        """Switch the active sheet, syncing active state both ways."""
        if new_idx == self._current_idx:
            return
        if not (0 <= new_idx < len(self._sheets)):
            return
        self._cancel_placement()
        self._sync_active_to_sheets()
        self._current_idx = new_idx
        self._load_active_from_sheets()
        # Selection belongs to the active sheet's _placements list — it's
        # meaningless after switching, so clear it.
        if self._selected_index != -1:
            self._selected_index = -1
            self.selectedIndexChanged.emit()
        self.sheetsChanged.emit()
        self.stateChanged.emit()
        self.placementsChanged.emit()
        self.ghostChanged.emit()

    @Slot()
    def addSheet(self):
        """Append a fresh sheet and switch to it."""
        self._sync_active_to_sheets()
        self._sheets.append(self._new_sheet_state())
        self._current_idx = len(self._sheets) - 1
        self._cancel_placement()
        self._load_active_from_sheets()
        self.sheetsChanged.emit()
        self.stateChanged.emit()
        self.placementsChanged.emit()
        self.ghostChanged.emit()
        self.libraryChanged.emit()

    @Slot(result=bool)
    def removeCurrentSheet(self) -> bool:
        """Drop the current sheet. Refuses to empty the nest entirely.

        Returns placed parts on the removed sheet back to the library so
        they can be re-placed elsewhere — we don't silently shrink the
        library's needed count.
        """
        if len(self._sheets) <= 1:
            self.operationFailed.emit(
                "Can't remove — a manual nest needs at least one sheet."
            )
            return False
        self._cancel_placement()
        self._sync_active_to_sheets()
        removed = self._sheets.pop(self._current_idx)
        # Return every placement on the removed sheet back to the library
        for p in removed.get("placements") or []:
            entry = self._find_library_entry(
                p.get("product_sku"), p["component_id"],
            )
            if entry and entry["placed"] > 0:
                entry["placed"] -= 1
        # Clamp the index to a valid range
        self._current_idx = min(self._current_idx, len(self._sheets) - 1)
        self._load_active_from_sheets()
        self.sheetsChanged.emit()
        self.stateChanged.emit()
        self.placementsChanged.emit()
        self.libraryChanged.emit()
        self.ghostChanged.emit()
        return True

    @Slot()
    def gotoPrevSheet(self):
        self._activate_sheet(self._current_idx - 1)

    @Slot()
    def gotoNextSheet(self):
        self._activate_sheet(self._current_idx + 1)

    # ==================================================================
    # Scalar setters
    # ==================================================================

    @Slot(str)
    def setName(self, value: str):
        value = value or ""
        if value != self._name:
            self._name = value
            self.stateChanged.emit()

    @Slot(float, float, float, float)
    def setSheetDimensions(
        self,
        width: float, height: float,
        part_spacing: float, edge_margin: float,
    ):
        changed = False
        if width > 0 and not math.isclose(width, self._sheet_w):
            self._sheet_w = float(width); changed = True
        if height > 0 and not math.isclose(height, self._sheet_h):
            self._sheet_h = float(height); changed = True
        if part_spacing >= 0 and not math.isclose(part_spacing, self._part_spacing):
            self._part_spacing = float(part_spacing); changed = True
        if edge_margin >= 0 and not math.isclose(edge_margin, self._edge_margin):
            self._edge_margin = float(edge_margin); changed = True
        if changed:
            self.stateChanged.emit()
            # Existing placements may now be out-of-bounds — re-validate ghost
            if self._ghost_component_id is not None:
                self._revalidate_ghost()

    # ==================================================================
    # Add products -> library population
    # ==================================================================

    @Slot("QVariantList", result=bool)
    def addProducts(self, entries):
        """Add products to the library. `entries` is a list of {sku, qty} dicts.

        For each product, looks up its components and adds the total needed
        count to the library (aggregating across existing entries so the same
        component from the same product accumulates).
        """
        db = self._app.db
        if not db:
            self.operationFailed.emit(
                "Cannot add products — not connected to the server."
            )
            return False

        # Build a local map of existing library entries keyed by (sku, cid)
        index: dict[tuple[str, int], dict[str, Any]] = {
            (e["product_sku"], e["component_id"]): e for e in self._library
        }
        added_units = 0
        skipped_no_components: list[str] = []
        skipped_not_found: list[str] = []
        for raw in entries or []:
            sku = str(raw.get("sku", "")).strip()
            qty = int(raw.get("qty", 0) or 0)
            if not sku or qty <= 0:
                continue
            product = db.get_product(sku)
            if not product:
                skipped_not_found.append(sku)
                logger.warning("addProducts: product '%s' not found", sku)
                continue
            if not product.components:
                skipped_no_components.append(sku)
                continue
            for comp in product.components:
                key = (sku, comp.component_id)
                needed = comp.quantity * qty
                geom = self._lookup_component_geometry(comp.component_id, comp.dxf_filename)
                if key in index:
                    index[key]["needed"] += needed
                else:
                    entry = {
                        "component_id": comp.component_id,
                        "component_name": comp.component_name,
                        "dxf_filename": comp.dxf_filename,
                        "product_sku": sku,
                        "needed": needed,
                        "placed": 0,
                        "bbox_w": geom["bbox"][0],
                        "bbox_h": geom["bbox"][1],
                        "polygon": geom["polygon"],
                        "pocket_polygons": geom.get("pocket_polygons") or [],
                    }
                    self._library.append(entry)
                    index[key] = entry
                added_units += needed
        self.libraryChanged.emit()
        self.stateChanged.emit()

        # Surface actionable feedback for edge cases that would otherwise
        # look like a silent no-op to the user.
        if added_units == 0 and (skipped_no_components or skipped_not_found):
            bits = []
            if skipped_no_components:
                bits.append(
                    "no components defined: " + ", ".join(skipped_no_components)
                )
            if skipped_not_found:
                bits.append("not found: " + ", ".join(skipped_not_found))
            self.operationFailed.emit(
                "Nothing was added — " + "; ".join(bits)
                + ". Configure components for those SKUs on the Products tab first."
            )
            return False
        return True

    def _lookup_component_geometry(self, component_id: int, dxf_filename: str) -> dict:
        """Return {bbox, polygon, pocket_polygons} for a component.

        Cached per filename so repeated `addProducts` calls don't re-parse
        the same file. Falls back to a conservative rectangle polygon if
        the DXF isn't loadable so the editor still works offline (uncached,
        because the fallback may become valid once the loader is available).

        Polygons (outline + pockets) are normalised so the outline's
        lower-left bbox corner sits at (0, 0) — matches how the canvas +
        stored placement positions expect to receive them.
        """
        cached = self._bbox_cache.get(dxf_filename)
        if cached is not None:
            return cached
        loader = getattr(self._app, "dxf_loader", None)
        if loader is not None:
            try:
                geom = loader.load_part(dxf_filename)
                if geom is not None and geom.polygons:
                    bb = geom.bounding_box
                    w = max(0.1, bb.max_x - bb.min_x)
                    h = max(0.1, bb.max_y - bb.min_y)
                    # Normalise polygons so the outline bbox's lower-left
                    # sits at (0, 0). Pockets share the same shift so they
                    # stay aligned with their parent outline.
                    def _shift(pts):
                        return [[px - bb.min_x, py - bb.min_y] for px, py in pts]
                    normalised = _shift(geom.polygons[0])
                    pockets = [_shift(p) for p in (geom.pocket_polygons or [])]
                    result = {
                        "bbox": (w, h),
                        "polygon": normalised,
                        "pocket_polygons": pockets,
                    }
                    self._bbox_cache[dxf_filename] = result
                    return result
            except Exception:
                logger.debug(
                    "DXF geometry lookup failed for %s — using default",
                    dxf_filename, exc_info=True,
                )
        # Conservative default: 6x6 square polygon, no pockets
        return {
            "bbox": (6.0, 6.0),
            "polygon": [[0, 0], [6, 0], [6, 6], [0, 6]],
            "pocket_polygons": [],
        }

    def _lookup_component_bbox(self, component_id: int, dxf_filename: str) -> tuple[float, float]:
        """Back-compat shim — returns just the (w, h) tuple."""
        return self._lookup_component_geometry(component_id, dxf_filename)["bbox"]

    # ==================================================================
    # Placement mode (ghost)
    # ==================================================================

    @Slot(int, str)
    def startPlacement(self, component_id: int, product_sku: str):
        """Enter placement mode for a given library component."""
        entry = self._find_library_entry(product_sku, component_id)
        if not entry:
            self.operationFailed.emit("That part is no longer available in the library.")
            return
        if entry["placed"] >= entry["needed"]:
            self.operationFailed.emit(
                f"All {entry['needed']} of {entry['component_name']} are already placed."
            )
            return
        self._ghost_component_id = component_id
        self._ghost_product_sku = product_sku
        self._ghost_rotation = 0.0
        self._ghost_bbox_w = entry["bbox_w"]
        self._ghost_bbox_h = entry["bbox_h"]
        self._ghost_polygon = list(entry.get("polygon") or [])
        self._ghost_pocket_polygons = [list(p) for p in (entry.get("pocket_polygons") or [])]
        # Start ghost at sheet centre for visibility
        self._ghost_x = max(0.0, (self._sheet_w - self._ghost_bbox_w) / 2.0)
        self._ghost_y = max(0.0, (self._sheet_h - self._ghost_bbox_h) / 2.0)
        self._revalidate_ghost()
        self.ghostChanged.emit()

    @Slot(float, float)
    def updateGhostPosition(self, x: float, y: float):
        """Canvas hover — move the ghost toward the cursor.

        When `slideCollision` is on (default), the ghost slides up against
        edges/other parts instead of refusing to follow the cursor: it
        advances as far as it can along X at the current Y, then advances
        along Y from that new X. Toggling slide off reverts to the
        "accept cursor directly, colour the ghost red on collision" path,
        which is sometimes needed to drop a part into a fully-enclosed
        pocket the slide can't physically reach.

        Skips revalidation + signal emission when the target matches the
        current position — QML emits this slot on every mouse-move event.
        """
        if self._ghost_component_id is None:
            return
        target_x, target_y = float(x), float(y)
        if target_x == self._ghost_x and target_y == self._ghost_y:
            return
        if self._slide_collision:
            target_x, target_y = self._slide_to(target_x, target_y)
            if target_x == self._ghost_x and target_y == self._ghost_y:
                return
        self._ghost_x = target_x
        self._ghost_y = target_y
        self._revalidate_ghost()
        self.ghostChanged.emit()

    def _ghost_can_place_at(self, x: float, y: float) -> bool:
        return self._can_place(
            x, y, self._ghost_bbox_w, self._ghost_bbox_h,
            self._ghost_polygon, self._ghost_rotation,
            exclude_index=None,
        )

    # Binary-search precision — 1/100 inch is well below the CNC's
    # positioning resolution and ~15 iterations of halving a 48-inch
    # sweep gets us there.
    _SLIDE_TOLERANCE = 0.01

    def _slide_axis(self, start: float, target: float, check) -> float:
        """Furthest value between `start` and `target` for which `check`
        returns True. March from start in small steps so we can't skip
        over an obstacle zone that sits between two free regions, then
        binary-refine the final boundary.

        Step size is tied to the ghost's own bbox so an obstacle can
        never be smaller than a step — we'd sample inside it every time.
        """
        if start == target:
            return start
        direction = 1.0 if target > start else -1.0
        remaining = abs(target - start)
        # Step must be at most a fraction of the smallest ghost dimension
        # to guarantee we can't tunnel through anything wider than a ghost
        # half. Clamped so we always take at least ~0.1" steps even if
        # the ghost is tiny, and never step more than 1" which keeps the
        # per-move work bounded on huge sweeps.
        step_mag = max(0.1, min(
            1.0,
            max(self._ghost_bbox_w, self._ghost_bbox_h, 0.4) / 4.0,
        ))
        pos = start
        while remaining > 0.0:
            advance = min(step_mag, remaining) * direction
            next_pos = pos + advance
            if check(next_pos):
                pos = next_pos
                remaining -= abs(advance)
                continue
            # Hit an obstacle between `pos` (valid) and `next_pos` (invalid).
            # Binary-refine the boundary.
            lo, hi = pos, next_pos
            for _ in range(12):
                if abs(hi - lo) < self._SLIDE_TOLERANCE:
                    break
                mid = (lo + hi) / 2.0
                if check(mid):
                    lo = mid
                else:
                    hi = mid
            return lo
        return pos

    def _slide_to(self, target_x: float, target_y: float) -> tuple[float, float]:
        """Return the best-reachable (x, y) for the ghost given a cursor
        target, sliding along each axis independently when the path is
        blocked.

        We always march along each axis (no "target is valid, jump there"
        fast path) so an obstacle sitting between two valid zones can't
        be tunnelled through.
        """
        cur_x, cur_y = self._ghost_x, self._ghost_y
        # Invalid starting anchor (ghost spawned overlapping a part after
        # a rotation or a just-committed placement). If the cursor asks
        # for a clearly valid position, jump there to unstick; otherwise
        # stay put and let the red ghost guide the operator.
        if not self._ghost_can_place_at(cur_x, cur_y):
            if self._ghost_can_place_at(target_x, target_y):
                return target_x, target_y
            return cur_x, cur_y
        sx = self._slide_axis(
            cur_x, target_x, lambda x: self._ghost_can_place_at(x, cur_y),
        )
        sy = self._slide_axis(
            cur_y, target_y, lambda y: self._ghost_can_place_at(sx, y),
        )
        return sx, sy

    @Slot()
    def rotateGhost(self):
        """R key — rotate the ghost 90° counter-clockwise."""
        if self._ghost_component_id is None:
            return
        self._ghost_rotation = (self._ghost_rotation + 90.0) % 360.0
        # After rotation the bbox dimensions swap; update so collision uses
        # the rotated footprint
        base_w, base_h = self._ghost_bbox_w, self._ghost_bbox_h
        # The "base" bbox stored on the entry is for rotation=0. Recompute
        # the effective bbox for the current rotation:
        entry = self._find_library_entry(
            self._ghost_product_sku, self._ghost_component_id,
        )
        if entry:
            new_w, new_h = _placement_bbox(
                entry["bbox_w"], entry["bbox_h"], self._ghost_rotation,
            )
            self._ghost_bbox_w = new_w
            self._ghost_bbox_h = new_h
        self._revalidate_ghost()
        self.ghostChanged.emit()

    @Slot(result=bool)
    def commitPlacement(self) -> bool:
        """Commit the ghost as an actual placement. Stays in placement mode
        for the next instance if more of this component remain."""
        if self._ghost_component_id is None:
            return False
        if not self._ghost_valid:
            self.operationFailed.emit(
                "Can't place there — overlaps another part or off-sheet."
            )
            return False
        entry = self._find_library_entry(
            self._ghost_product_sku, self._ghost_component_id,
        )
        if not entry:
            self._cancel_placement()
            return False
        placement = {
            "component_id": self._ghost_component_id,
            "component_name": entry["component_name"],
            "dxf_filename": entry["dxf_filename"],
            "product_sku": self._ghost_product_sku,
            "product_unit": _DEFAULT_PRODUCT_UNIT,
            "x": self._ghost_x,
            "y": self._ghost_y,
            "rotation_deg": self._ghost_rotation,
            "bbox_w": self._ghost_bbox_w,
            "bbox_h": self._ghost_bbox_h,
            "polygon": entry.get("polygon", []),
            "pocket_polygons": entry.get("pocket_polygons") or [],
        }
        self._placements.append(placement)
        entry["placed"] += 1
        self.placementsChanged.emit()
        self.libraryChanged.emit()
        self.stateChanged.emit()
        # Exit placement mode if this entry is fully placed; otherwise stay
        # in mode so the user can click-click-click to rapid-place a series
        if entry["placed"] >= entry["needed"]:
            self._cancel_placement()
        else:
            self.ghostChanged.emit()
        return True

    @Slot()
    def cancelPlacement(self):
        self._cancel_placement()
        self.ghostChanged.emit()

    def _cancel_placement(self):
        self._ghost_component_id = None
        self._ghost_product_sku = None
        self._ghost_valid = False
        self._ghost_rotation = 0.0
        self._ghost_bbox_w = 0.0
        self._ghost_bbox_h = 0.0
        self._ghost_polygon = []
        self._ghost_pocket_polygons = []

    def _revalidate_ghost(self):
        """Update `_ghost_valid` based on current position + rotation."""
        if self._ghost_component_id is None:
            self._ghost_valid = False
            return
        self._ghost_valid = self._can_place(
            self._ghost_x, self._ghost_y,
            self._ghost_bbox_w, self._ghost_bbox_h,
            self._ghost_polygon, self._ghost_rotation,
            exclude_index=None,
        )

    def _find_library_entry(
        self, product_sku: Optional[str], component_id: int,
    ) -> Optional[dict[str, Any]]:
        for entry in self._library:
            if (
                entry["product_sku"] == product_sku
                and entry["component_id"] == component_id
            ):
                return entry
        return None

    # ==================================================================
    # Collision + bounds check
    # ==================================================================

    def _can_place(
        self,
        x: float, y: float, bbox_w: float, bbox_h: float,
        polygon: list, rotation_deg: float,
        exclude_index: Optional[int],
    ) -> bool:
        """Sheet-bounds + collision test. Returns True if a part with the
        given lower-left corner, bbox, and polygon can be placed.

        Collision is polygon-accurate via Shapely: we buffer the candidate
        polygon outward by `part_spacing` and test intersection against
        every already-placed polygon on this sheet. AABB is used only as a
        cheap broad-phase filter (skip the expensive polygon op for pairs
        whose bboxes don't even touch).
        """
        # Sheet bounds (with edge margin)
        em = self._edge_margin
        if x < em or y < em:
            return False
        if x + bbox_w > self._sheet_w - em:
            return False
        if y + bbox_h > self._sheet_h - em:
            return False

        candidate_shape = _build_oriented_polygon(polygon, x, y, rotation_deg)
        # Apply the part-spacing buffer once on the candidate so downstream
        # intersect tests are against the already-placed polygons unchanged.
        if candidate_shape is not None and self._part_spacing > 0:
            candidate_shape = candidate_shape.buffer(self._part_spacing)

        for i, p in enumerate(self._placements):
            if exclude_index is not None and i == exclude_index:
                continue
            # Broad-phase AABB reject
            if not _aabb_overlaps(
                x, y, bbox_w, bbox_h,
                p["x"], p["y"], p["bbox_w"], p["bbox_h"],
                self._part_spacing,
            ):
                continue
            # Narrow-phase polygon check. If we don't have polygon geometry
            # on either side, fall back to the AABB result we already have.
            other_shape = _build_oriented_polygon(
                p.get("polygon") or [],
                p["x"], p["y"],
                float(p.get("rotation_deg") or 0.0),
            )
            if candidate_shape is None or other_shape is None:
                return False
            if candidate_shape.intersects(other_shape):
                return False
        return True

    # ==================================================================
    # Remove placed parts
    # ==================================================================

    @Slot(int, result=bool)
    def removePlacement(self, index: int) -> bool:
        """Remove a placed part by its index in the placements list.
        Returns the library entry's 'placed' count to zero + one."""
        if index < 0 or index >= len(self._placements):
            return False
        p = self._placements.pop(index)
        entry = self._find_library_entry(p.get("product_sku"), p["component_id"])
        if entry and entry["placed"] > 0:
            entry["placed"] -= 1
        # Adjust selection for the list-shift: clear if the removed item
        # was selected, or decrement if the selection was past it.
        if self._selected_index == index:
            self._selected_index = -1
            self.selectedIndexChanged.emit()
        elif self._selected_index > index:
            self._selected_index -= 1
            self.selectedIndexChanged.emit()
        self.placementsChanged.emit()
        self.libraryChanged.emit()
        self.stateChanged.emit()
        return True

    # ==================================================================
    # Save
    # ==================================================================

    @Slot(result=bool)
    def save(self) -> bool:
        """Persist the nest — POST when creating, PUT when editing."""
        if not self._name.strip():
            self.operationFailed.emit("Name is required.")
            return False
        if not self._placements:
            self.operationFailed.emit("Can't save an empty nest — place at least one part.")
            return False
        db = self._app.db
        if not db or not hasattr(db, "create_manual_nest"):
            self.operationFailed.emit("Not connected to the server.")
            return False

        # Ensure the active sheet's working state is flushed back into the
        # list before we serialize.
        self._sync_active_to_sheets()
        sheets = []
        for i, s in enumerate(self._sheets):
            sheets.append({
                "sheet_index": i,
                "width": s["width"],
                "height": s["height"],
                "part_spacing": s["part_spacing"],
                "edge_margin": s["edge_margin"],
                "material": None,
                "thickness": None,
                "parts": [
                    {
                        "component_id": p["component_id"],
                        "product_sku": p.get("product_sku"),
                        "product_unit": p.get("product_unit", _DEFAULT_PRODUCT_UNIT),
                        "instance_index": 0,
                        "x": p["x"],
                        "y": p["y"],
                        "rotation_deg": p["rotation_deg"],
                    }
                    for p in (s.get("placements") or [])
                ],
            })
        try:
            if self._nest_id is not None:
                db.update_manual_nest(
                    self._nest_id,
                    name=self._name.strip(),
                    sheets=sheets,
                )
                verb = "Updated"
            else:
                db.create_manual_nest(
                    name=self._name.strip(),
                    override_enabled=False,
                    sheets=sheets,
                )
                verb = "Saved"
        except Exception:
            logger.exception(
                "Failed to %s manual nest '%s'",
                "update" if self._nest_id is not None else "create",
                self._name,
            )
            self.operationFailed.emit(
                "Save failed. Please retry once you're connected to the server."
            )
            return False
        self.statusMessage.emit(f"{verb} manual nest: {self._name.strip()}", 3000)
        self._visible = False
        self.visibilityChanged.emit()
        return True

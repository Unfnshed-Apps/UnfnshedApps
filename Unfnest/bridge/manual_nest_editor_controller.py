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
    """
    ax1, ay1 = a_x - buffer, a_y - buffer
    ax2, ay2 = a_x + a_w + buffer, a_y + a_h + buffer
    bx1, by1 = b_x - buffer, b_y - buffer
    bx2, by2 = b_x + b_w + buffer, b_y + b_h + buffer
    return not (ax2 <= bx1 or bx2 <= ax1 or ay2 <= by1 or by2 <= ay1)


class ManualNestEditorController(QObject):
    """Backing controller for the Manual Nest editor window."""

    # ---- Signals QML listens on ----
    stateChanged = Signal()           # broad refresh signal
    libraryChanged = Signal()
    placementsChanged = Signal()
    ghostChanged = Signal()
    visibilityChanged = Signal()
    operationFailed = Signal(str)
    statusMessage = Signal(str, int)

    def __init__(self, app_ctrl, product_ctrl=None, component_ctrl=None, parent=None):
        super().__init__(parent)
        self._app = app_ctrl
        self._product_ctrl = product_ctrl
        self._component_ctrl = component_ctrl

        # Window open / close
        self._visible = False

        # Nest scalar state
        self._name = ""
        self._sheet_w = _DEFAULT_SHEET_W
        self._sheet_h = _DEFAULT_SHEET_H
        self._part_spacing = _DEFAULT_SPACING
        self._edge_margin = _DEFAULT_EDGE

        # `placements` is a list of dicts:
        # {component_id, component_name, dxf_filename, product_sku,
        #  product_unit, x, y, rotation_deg, bbox_w, bbox_h}
        self._placements: list[dict[str, Any]] = []

        # Library: entries the user added via Add Products, minus what's
        # already been placed. Each entry is a dict:
        # {component_id, component_name, dxf_filename, product_sku,
        #  needed, placed, bbox_w, bbox_h}
        self._library: list[dict[str, Any]] = []

        # Per-DXF bbox cache so repeated `addProducts` calls don't re-parse
        # the same geometry file. Keyed by dxf_filename.
        self._bbox_cache: dict[str, tuple[float, float]] = {}

        # Ghost / placement-mode state
        self._ghost_component_id: Optional[int] = None
        self._ghost_product_sku: Optional[str] = None
        self._ghost_x = 0.0
        self._ghost_y = 0.0
        self._ghost_rotation = 0.0
        self._ghost_valid = False
        self._ghost_bbox_w = 0.0
        self._ghost_bbox_h = 0.0

    # ==================================================================
    # QML-visible properties
    # ==================================================================

    @Property(bool, notify=visibilityChanged)
    def visible(self):
        return self._visible

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

    @Property("QVariantList", notify=libraryChanged)
    def library(self):
        return list(self._library)

    @Property(int, notify=ghostChanged)
    def ghostComponentId(self):
        return self._ghost_component_id if self._ghost_component_id is not None else -1

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

    @Property(bool, notify=stateChanged)
    def isSaveEnabled(self):
        """Save requires a non-empty name and at least one placed part."""
        return bool(self._name.strip()) and len(self._placements) > 0

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

    @Slot()
    def close(self):
        """Close the editor window without saving."""
        self._cancel_placement()
        self._visible = False
        self.visibilityChanged.emit()

    def _reset_state(self):
        self._name = ""
        self._sheet_w = _DEFAULT_SHEET_W
        self._sheet_h = _DEFAULT_SHEET_H
        self._part_spacing = _DEFAULT_SPACING
        self._edge_margin = _DEFAULT_EDGE
        self._placements = []
        self._library = []
        self._bbox_cache = {}
        self._cancel_placement()

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
        for raw in entries or []:
            sku = str(raw.get("sku", "")).strip()
            qty = int(raw.get("qty", 0) or 0)
            if not sku or qty <= 0:
                continue
            product = db.get_product(sku)
            if not product:
                logger.warning("addProducts: product '%s' not found", sku)
                continue
            for comp in product.components:
                key = (sku, comp.component_id)
                needed = comp.quantity * qty
                bbox = self._lookup_component_bbox(comp.component_id, comp.dxf_filename)
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
                        "bbox_w": bbox[0],
                        "bbox_h": bbox[1],
                    }
                    self._library.append(entry)
                    index[key] = entry
        self.libraryChanged.emit()
        self.stateChanged.emit()
        return True

    def _lookup_component_bbox(self, component_id: int, dxf_filename: str) -> tuple[float, float]:
        """Return (width, height) of the component's DXF bbox.

        Cached per filename so repeated `addProducts` calls don't re-parse
        the same file. Falls back to a conservative default if the DXF isn't
        loadable so the editor still works offline (uncached, because the
        fallback may become valid once the loader is available).
        """
        cached = self._bbox_cache.get(dxf_filename)
        if cached is not None:
            return cached
        loader = getattr(self._app, "dxf_loader", None)
        if loader is not None:
            try:
                geom = loader.load_geometry(dxf_filename)
                bb = geom.bounding_box
                w = max(0.1, bb.max_x - bb.min_x)
                h = max(0.1, bb.max_y - bb.min_y)
                self._bbox_cache[dxf_filename] = (w, h)
                return (w, h)
            except Exception:
                logger.debug(
                    "DXF bbox lookup failed for %s — using default",
                    dxf_filename, exc_info=True,
                )
        return (6.0, 6.0)  # conservative default — always fits on 48x96 sheets

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
        # Start ghost at sheet centre for visibility
        self._ghost_x = max(0.0, (self._sheet_w - self._ghost_bbox_w) / 2.0)
        self._ghost_y = max(0.0, (self._sheet_h - self._ghost_bbox_h) / 2.0)
        self._revalidate_ghost()
        self.ghostChanged.emit()

    @Slot(float, float)
    def updateGhostPosition(self, x: float, y: float):
        """Canvas hover — sets the ghost position to cursor-aligned sheet coords.

        Skips the expensive collision revalidation + signal emission when the
        position hasn't changed — QML emits this slot on every mouse-move
        pixel, including idle hovers.
        """
        if self._ghost_component_id is None:
            return
        x, y = float(x), float(y)
        if x == self._ghost_x and y == self._ghost_y:
            return
        self._ghost_x = x
        self._ghost_y = y
        self._revalidate_ghost()
        self.ghostChanged.emit()

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

    def _revalidate_ghost(self):
        """Update `_ghost_valid` based on current position + rotation."""
        if self._ghost_component_id is None:
            self._ghost_valid = False
            return
        self._ghost_valid = self._can_place(
            self._ghost_x, self._ghost_y,
            self._ghost_bbox_w, self._ghost_bbox_h,
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
        exclude_index: Optional[int],
    ) -> bool:
        """AABB collision + sheet-bounds test. Returns True if a part with
        the given lower-left corner and bbox can be placed without overlap."""
        # Sheet bounds (with edge margin)
        em = self._edge_margin
        if x < em or y < em:
            return False
        if x + bbox_w > self._sheet_w - em:
            return False
        if y + bbox_h > self._sheet_h - em:
            return False
        # Overlap with existing placements (with part spacing buffer)
        for i, p in enumerate(self._placements):
            if exclude_index is not None and i == exclude_index:
                continue
            if _aabb_overlaps(
                x, y, bbox_w, bbox_h,
                p["x"], p["y"], p["bbox_w"], p["bbox_h"],
                self._part_spacing,
            ):
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
        self.placementsChanged.emit()
        self.libraryChanged.emit()
        self.stateChanged.emit()
        return True

    # ==================================================================
    # Save
    # ==================================================================

    @Slot(result=bool)
    def save(self) -> bool:
        """POST the current state as a new manual nest."""
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

        sheets = [{
            "sheet_index": 0,
            "width": self._sheet_w,
            "height": self._sheet_h,
            "part_spacing": self._part_spacing,
            "edge_margin": self._edge_margin,
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
                for p in self._placements
            ],
        }]
        try:
            db.create_manual_nest(
                name=self._name.strip(),
                override_enabled=False,
                sheets=sheets,
            )
        except Exception:
            logger.exception("Failed to create manual nest '%s'", self._name)
            self.operationFailed.emit(
                "Save failed. Please retry once you're connected to the server."
            )
            return False
        self.statusMessage.emit(f"Saved manual nest: {self._name.strip()}", 3000)
        self._visible = False
        self.visibilityChanged.emit()
        return True

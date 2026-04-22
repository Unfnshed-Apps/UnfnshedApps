"""
QQuickPaintedItem for the editable sheet canvas in the Manual Nest editor.

This item is a pure painter — it renders the sheet outline, already-placed
parts (as rotated DXF polygons), and the placement "ghost" that follows
the cursor while in placement mode. Mouse input is handled on the QML side
via a MouseArea that converts pixel coordinates to sheet inches (using
this item's scale-factor properties) and calls slots on the
ManualNestEditorController.

Placement rendering follows the same coordinate convention as the nesting
engine: sheet origin lower-left, inches. For each placement, the polygon
is rotated, translated so the rotated bounding box's lower-left sits at
(x, y), scaled to pixels, and flipped on Y.
"""

from __future__ import annotations

import math

from PySide6.QtCore import Property, QPointF, Signal, Qt
from PySide6.QtGui import QBrush, QColor, QPainter, QPen, QPolygonF
from PySide6.QtQml import qmlRegisterType
from PySide6.QtQuick import QQuickPaintedItem

from bridge.canvas_utils import compute_sheet_scale


# Fixed margin (pixels) around the sheet when drawn inside the canvas widget.
_PIXEL_MARGIN = 12


class ManualNestCanvasItem(QQuickPaintedItem):
    darkModeChanged = Signal()
    sheetSizeChanged = Signal()
    placementsChanged = Signal()
    ghostChanged = Signal()
    # `scale` is already a built-in QQuickItem property; our sheet-pixel scale
    # is exposed under a different name so the meta-object cache doesn't clash.
    sheetScaleChanged = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAntialiasing(True)

        self._dark_mode = False

        # Sheet geometry in inches
        self._sheet_w = 48.0
        self._sheet_h = 96.0
        self._edge_margin = 0.75

        # List of placement dicts (see ManualNestEditorController.placements)
        self._placements: list = []

        # Index of the highlighted placement in `_placements`, or -1 for
        # none. Matches the editor controller's selectedPlacementIndex.
        self._selected_index = -1

        # Ghost state
        self._ghost_active = False
        self._ghost_valid = False
        self._ghost_x = 0.0
        self._ghost_y = 0.0
        self._ghost_w = 0.0
        self._ghost_h = 0.0
        self._ghost_rotation = 0.0
        self._ghost_polygon: list = []
        self._ghost_pocket_polygons: list = []

        # Cached scale/offset — recomputed each paint, exposed for hit-testing
        self._scale = 1.0
        self._offset_x = 0.0
        self._offset_y = 0.0

    @staticmethod
    def register():
        qmlRegisterType(ManualNestCanvasItem, "Unfnest", 1, 0, "ManualNestCanvasItem")

    # ==================================================================
    # Exposed properties — set from QML, mirror controller state
    # ==================================================================

    def _get_dark_mode(self):
        return self._dark_mode

    def _set_dark_mode(self, val):
        if self._dark_mode != val:
            self._dark_mode = val
            self.darkModeChanged.emit()
            self.update()

    darkMode = Property(bool, _get_dark_mode, _set_dark_mode, notify=darkModeChanged)

    def _get_sheet_w(self):
        return self._sheet_w

    def _set_sheet_w(self, val):
        val = float(val) if val > 0 else self._sheet_w
        if val != self._sheet_w:
            self._sheet_w = val
            self.sheetSizeChanged.emit()
            self.update()

    sheetWidth = Property(float, _get_sheet_w, _set_sheet_w, notify=sheetSizeChanged)

    def _get_sheet_h(self):
        return self._sheet_h

    def _set_sheet_h(self, val):
        val = float(val) if val > 0 else self._sheet_h
        if val != self._sheet_h:
            self._sheet_h = val
            self.sheetSizeChanged.emit()
            self.update()

    sheetHeight = Property(float, _get_sheet_h, _set_sheet_h, notify=sheetSizeChanged)

    def _get_edge_margin(self):
        return self._edge_margin

    def _set_edge_margin(self, val):
        val = max(0.0, float(val))
        if val != self._edge_margin:
            self._edge_margin = val
            self.sheetSizeChanged.emit()
            self.update()

    edgeMargin = Property(
        float, _get_edge_margin, _set_edge_margin, notify=sheetSizeChanged,
    )

    def _get_placements(self):
        return list(self._placements)

    def _set_placements(self, val):
        self._placements = list(val) if val else []
        self.placementsChanged.emit()
        self.update()

    placements = Property("QVariantList", _get_placements, _set_placements, notify=placementsChanged)

    def _get_selected_index(self):
        return self._selected_index

    def _set_selected_index(self, val):
        val = int(val)
        if val != self._selected_index:
            self._selected_index = val
            self.placementsChanged.emit()
            self.update()

    selectedIndex = Property(
        int, _get_selected_index, _set_selected_index, notify=placementsChanged,
    )

    def _get_ghost_active(self):
        return self._ghost_active

    def _set_ghost_active(self, val):
        val = bool(val)
        if val != self._ghost_active:
            self._ghost_active = val
            self.ghostChanged.emit()
            self.update()

    ghostActive = Property(bool, _get_ghost_active, _set_ghost_active, notify=ghostChanged)

    def _get_ghost_valid(self):
        return self._ghost_valid

    def _set_ghost_valid(self, val):
        val = bool(val)
        if val != self._ghost_valid:
            self._ghost_valid = val
            self.ghostChanged.emit()
            self.update()

    ghostValid = Property(bool, _get_ghost_valid, _set_ghost_valid, notify=ghostChanged)

    def _get_ghost_x(self):
        return self._ghost_x

    def _set_ghost_x(self, val):
        val = float(val)
        if val != self._ghost_x:
            self._ghost_x = val
            self.ghostChanged.emit()
            self.update()

    ghostX = Property(float, _get_ghost_x, _set_ghost_x, notify=ghostChanged)

    def _get_ghost_y(self):
        return self._ghost_y

    def _set_ghost_y(self, val):
        val = float(val)
        if val != self._ghost_y:
            self._ghost_y = val
            self.ghostChanged.emit()
            self.update()

    ghostY = Property(float, _get_ghost_y, _set_ghost_y, notify=ghostChanged)

    def _get_ghost_w(self):
        return self._ghost_w

    def _set_ghost_w(self, val):
        val = float(val)
        if val != self._ghost_w:
            self._ghost_w = val
            self.ghostChanged.emit()
            self.update()

    ghostBboxW = Property(float, _get_ghost_w, _set_ghost_w, notify=ghostChanged)

    def _get_ghost_h(self):
        return self._ghost_h

    def _set_ghost_h(self, val):
        val = float(val)
        if val != self._ghost_h:
            self._ghost_h = val
            self.ghostChanged.emit()
            self.update()

    ghostBboxH = Property(float, _get_ghost_h, _set_ghost_h, notify=ghostChanged)

    def _get_ghost_rotation(self):
        return self._ghost_rotation

    def _set_ghost_rotation(self, val):
        val = float(val)
        if val != self._ghost_rotation:
            self._ghost_rotation = val
            self.ghostChanged.emit()
            self.update()

    ghostRotation = Property(float, _get_ghost_rotation, _set_ghost_rotation, notify=ghostChanged)

    def _get_ghost_polygon(self):
        return list(self._ghost_polygon)

    def _set_ghost_polygon(self, val):
        self._ghost_polygon = list(val) if val else []
        self.ghostChanged.emit()
        self.update()

    ghostPolygon = Property(
        "QVariantList", _get_ghost_polygon, _set_ghost_polygon, notify=ghostChanged,
    )

    def _get_ghost_pockets(self):
        return [list(p) for p in self._ghost_pocket_polygons]

    def _set_ghost_pockets(self, val):
        self._ghost_pocket_polygons = [list(p) for p in val] if val else []
        self.ghostChanged.emit()
        self.update()

    ghostPocketPolygons = Property(
        "QVariantList", _get_ghost_pockets, _set_ghost_pockets, notify=ghostChanged,
    )

    # Sheet-pixel scale + draw offset exposed to QML so the MouseArea can
    # convert pixel coordinates into sheet inches.
    @Property(float, notify=sheetScaleChanged)
    def sheetScale(self):
        return self._scale

    @Property(float, notify=sheetScaleChanged)
    def offsetX(self):
        return self._offset_x

    @Property(float, notify=sheetScaleChanged)
    def offsetY(self):
        return self._offset_y

    # ==================================================================
    # Paint
    # ==================================================================

    def paint(self, painter: QPainter):
        self._recompute_scale()

        dark = self._dark_mode
        # Sheet background + border
        sheet_fill = QColor(30, 30, 30) if dark else QColor(250, 250, 250)
        sheet_border = QColor(180, 180, 180) if dark else QColor(90, 90, 90)
        painter.setBrush(QBrush(sheet_fill))
        painter.setPen(QPen(sheet_border, 2))
        painter.drawRect(
            int(self._offset_x),
            int(self._offset_y),
            int(self._sheet_w * self._scale),
            int(self._sheet_h * self._scale),
        )

        # Edge-margin indicator — dashed rect at (em, em) → (w-em, h-em).
        # Helps the operator see where parts are actually allowed to land.
        if self._edge_margin > 0:
            margin_pen = QColor(180, 150, 60) if dark else QColor(180, 120, 30)
            inner_px, inner_py, inner_pw, inner_ph = self._inches_to_pixel_rect(
                self._edge_margin, self._edge_margin,
                max(0.0, self._sheet_w - 2 * self._edge_margin),
                max(0.0, self._sheet_h - 2 * self._edge_margin),
            )
            painter.setBrush(QBrush(Qt.NoBrush))
            painter.setPen(QPen(margin_pen, 1, Qt.DashLine))
            painter.drawRect(inner_px, inner_py, inner_pw, inner_ph)

        # Placed parts — draw selected one LAST so its highlight stays
        # on top of any neighbours.
        for i, p in enumerate(self._placements):
            if i == self._selected_index:
                continue
            self._draw_placement(painter, p, dark, highlighted=False)
        if 0 <= self._selected_index < len(self._placements):
            self._draw_placement(
                painter, self._placements[self._selected_index], dark,
                highlighted=True,
            )

        # Ghost
        if self._ghost_active:
            self._draw_ghost(painter, dark)

    def _recompute_scale(self):
        new_scale, new_ox, new_oy = compute_sheet_scale(
            self.width(), self.height(),
            self._sheet_w, self._sheet_h,
            margin_px=_PIXEL_MARGIN,
        )
        if (new_scale, new_ox, new_oy) != (self._scale, self._offset_x, self._offset_y):
            self._scale = new_scale
            self._offset_x = new_ox
            self._offset_y = new_oy
            self.sheetScaleChanged.emit()

    def _inches_to_pixel_rect(self, x: float, y: float, w: float, h: float):
        """Convert a sheet-space AABB (lower-left x/y + w/h) to screen rect.
        Screen y grows downward, sheet y grows upward — we flip."""
        px = self._offset_x + x * self._scale
        py = self._offset_y + (self._sheet_h - (y + h)) * self._scale
        pw = w * self._scale
        ph = h * self._scale
        return int(px), int(py), int(pw), int(ph)

    def _rotate_points(self, points: list, rotation_deg: float):
        """Rotate (x, y) tuples around the origin."""
        if not points:
            return []
        rad = math.radians(rotation_deg)
        cos_r = math.cos(rad)
        sin_r = math.sin(rad)
        return [
            (px * cos_r - py * sin_r, px * sin_r + py * cos_r)
            for px, py in points
        ]

    def _pixel_qpoly(
        self, rotated_points: list,
        anchor_min_x: float, anchor_min_y: float,
        origin_x: float, origin_y: float,
    ) -> QPolygonF | None:
        """Convert already-rotated points into a pixel-space QPolygonF.

        `anchor_min_x/y` shifts the rotated set so that anchor sits at
        (0, 0); then `origin_x/y` moves the whole thing to its placement
        position. Keeps pockets locked to the same local frame as their
        parent outline when the caller passes the outline's anchor for
        both.
        """
        if not rotated_points or len(rotated_points) < 3:
            return None
        qpoly = QPolygonF()
        for rx, ry in rotated_points:
            sheet_x = rx - anchor_min_x + origin_x
            sheet_y = ry - anchor_min_y + origin_y
            qx = self._offset_x + sheet_x * self._scale
            qy = self._offset_y + (self._sheet_h - sheet_y) * self._scale
            qpoly.append(QPointF(qx, qy))
        return qpoly

    def _build_oriented_polygon(
        self, polygon: list, origin_x: float, origin_y: float, rotation_deg: float,
    ) -> QPolygonF | None:
        """Rotate the polygon, translate so its rotated bbox sits at
        (origin_x, origin_y), and convert to pixel-space QPolygonF. Returns
        None if the polygon has fewer than 3 points (nothing to draw).

        Use this when the polygon stands alone. For outline + pocket pairs,
        rotate each with `_rotate_points`, compute the OUTLINE's anchor
        once, and pass it through `_pixel_qpoly` for all sibling shapes.
        """
        rotated = self._rotate_points(polygon, rotation_deg)
        if not rotated or len(rotated) < 3:
            return None
        min_x = min(rx for rx, _ in rotated)
        min_y = min(ry for _, ry in rotated)
        return self._pixel_qpoly(rotated, min_x, min_y, origin_x, origin_y)

    def _fallback_rect_qpoly(self, x: float, y: float, w: float, h: float) -> QPolygonF:
        """Return a 4-point pixel-space rectangle for placements that don't
        have polygon geometry (edge cases before the DXF loads)."""
        px, py, pw, ph = self._inches_to_pixel_rect(x, y, w, h)
        qpoly = QPolygonF()
        qpoly.append(QPointF(px, py))
        qpoly.append(QPointF(px + pw, py))
        qpoly.append(QPointF(px + pw, py + ph))
        qpoly.append(QPointF(px, py + ph))
        return qpoly

    def _draw_pockets(
        self, painter, pockets, anchor_min_x, anchor_min_y,
        origin_x, origin_y, rotation_deg, dark,
    ):
        """Draw pocket polygons on top of a placement / ghost. Mirrors the
        look of `SheetPreviewItem` — dashed outline + semi-transparent fill
        in the standard pocket blue.

        Pockets are rotated and placed in the SAME local frame as their
        parent outline — the caller passes the outline's anchor so the
        re-anchoring step is identical for both shapes.
        """
        if not pockets:
            return
        if dark:
            pocket_color = QColor(100, 180, 255)
            fill_alpha = 50
        else:
            pocket_color = QColor(0, 100, 200)
            fill_alpha = 30
        painter.setPen(QPen(pocket_color, 1, Qt.DashLine))
        painter.setBrush(QBrush(QColor(
            pocket_color.red(), pocket_color.green(), pocket_color.blue(),
            fill_alpha,
        )))
        for pocket in pockets:
            rotated = self._rotate_points(pocket, rotation_deg)
            qpoly = self._pixel_qpoly(
                rotated, anchor_min_x, anchor_min_y, origin_x, origin_y,
            )
            if qpoly is not None:
                painter.drawPolygon(qpoly)

    def _draw_placement(self, painter, p, dark, highlighted=False):
        polygon = p.get("polygon") or []
        rot = float(p.get("rotation_deg") or 0.0)
        rotated_outline = self._rotate_points(polygon, rot)
        if rotated_outline and len(rotated_outline) >= 3:
            anchor_x = min(rx for rx, _ in rotated_outline)
            anchor_y = min(ry for _, ry in rotated_outline)
            qpoly = self._pixel_qpoly(
                rotated_outline, anchor_x, anchor_y, p["x"], p["y"],
            )
        else:
            bw = p.get("bbox_w") or 0.0
            bh = p.get("bbox_h") or 0.0
            if bw <= 0 or bh <= 0:
                return
            qpoly = self._fallback_rect_qpoly(p["x"], p["y"], bw, bh)
            anchor_x, anchor_y = 0.0, 0.0
        if highlighted:
            # Selected placement — tint the body and draw a bold gold
            # outline so it's obvious which row in the Placed list it
            # corresponds to.
            body = QColor(255, 210, 90, 180) if dark else QColor(255, 220, 110, 200)
            border = QColor(255, 180, 40) if dark else QColor(200, 130, 0)
            pen = QPen(border, 3)
        else:
            body = QColor(100, 140, 200, 120) if dark else QColor(120, 160, 220, 180)
            border = QColor(200, 220, 255) if dark else QColor(40, 80, 150)
            pen = QPen(border, 1)
        painter.setBrush(QBrush(body))
        painter.setPen(pen)
        painter.drawPolygon(qpoly)
        self._draw_pockets(
            painter, p.get("pocket_polygons") or [],
            anchor_x, anchor_y, p["x"], p["y"], rot, dark,
        )

    def _draw_ghost(self, painter, dark):
        if self._ghost_w <= 0 or self._ghost_h <= 0:
            return
        rotated_outline = self._rotate_points(
            self._ghost_polygon, self._ghost_rotation,
        )
        if rotated_outline and len(rotated_outline) >= 3:
            anchor_x = min(rx for rx, _ in rotated_outline)
            anchor_y = min(ry for _, ry in rotated_outline)
            qpoly = self._pixel_qpoly(
                rotated_outline, anchor_x, anchor_y,
                self._ghost_x, self._ghost_y,
            )
        else:
            qpoly = self._fallback_rect_qpoly(
                self._ghost_x, self._ghost_y, self._ghost_w, self._ghost_h,
            )
            anchor_x, anchor_y = 0.0, 0.0
        if self._ghost_valid:
            body = QColor(80, 200, 100, 100)
            border = QColor(60, 180, 80)
        else:
            body = QColor(220, 80, 80, 100)
            border = QColor(200, 40, 40)
        painter.setBrush(QBrush(body))
        painter.setPen(QPen(border, 2, Qt.DashLine))
        painter.drawPolygon(qpoly)
        self._draw_pockets(
            painter, self._ghost_pocket_polygons,
            anchor_x, anchor_y, self._ghost_x, self._ghost_y,
            self._ghost_rotation, dark,
        )

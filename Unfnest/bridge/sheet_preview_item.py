"""
QQuickPaintedItem for rendering sheet layout previews in QML.
"""

import math

from PySide6.QtCore import Qt, Property, Signal, QPointF
from PySide6.QtGui import QPainter, QPen, QBrush, QColor, QPolygonF
from PySide6.QtQuick import QQuickPaintedItem
from PySide6.QtQml import qmlRegisterType

from bridge.canvas_utils import compute_sheet_scale


class SheetPreviewItem(QQuickPaintedItem):
    darkModeChanged = Signal()
    sheetDataChanged = Signal()

    # Class-level nesting controller shared by all instances
    _shared_nesting_ctrl = None

    @classmethod
    def set_shared_nesting_controller(cls, ctrl):
        cls._shared_nesting_ctrl = ctrl

    def __init__(self, parent=None):
        super().__init__(parent)
        self._dark_mode = False
        self._sheet = None
        self._nesting_ctrl = None
        self.setAntialiasing(True)
        # Connect to shared controller if already set
        if SheetPreviewItem._shared_nesting_ctrl:
            self.set_nesting_controller(SheetPreviewItem._shared_nesting_ctrl)

    @staticmethod
    def register():
        qmlRegisterType(SheetPreviewItem, "Unfnest", 1, 0, "SheetPreviewItem")

    def _get_dark_mode(self):
        return self._dark_mode

    def _set_dark_mode(self, val):
        if self._dark_mode != val:
            self._dark_mode = val
            self.darkModeChanged.emit()
            self.update()

    darkMode = Property(bool, _get_dark_mode, _set_dark_mode, notify=darkModeChanged)

    def set_nesting_controller(self, ctrl):
        """Connect to nesting controller to get sheet data."""
        self._nesting_ctrl = ctrl
        ctrl.sheetChanged.connect(self._refresh_sheet)
        ctrl.resultChanged.connect(self._refresh_sheet)

    def _refresh_sheet(self):
        if self._nesting_ctrl:
            self._sheet = self._nesting_ctrl.get_current_sheet()
        else:
            self._sheet = None
        self.sheetDataChanged.emit()
        self.update()

    def paint(self, painter: QPainter):
        sheet = self._sheet
        if not sheet:
            return

        if self.width() <= 0 or self.height() <= 0:
            return
        scale, ox, oy = compute_sheet_scale(
            self.width(), self.height(),
            sheet.width, sheet.height,
            margin_px=10,
        )

        dark = self._dark_mode

        # Sheet border
        sheet_color = QColor(150, 150, 150) if dark else QColor(100, 100, 100)
        sheet_pen = QPen(sheet_color, 2)
        painter.setPen(sheet_pen)
        painter.setBrush(QBrush(Qt.NoBrush))
        painter.drawRect(int(ox), int(oy), int(drawn_w), int(drawn_h))

        # Draw parts
        for part in sheet.parts:
            self._draw_part(painter, part, scale, sheet.height, ox, oy, dark)

    def _draw_part(self, painter, part, scale, sheet_height, ox, oy, dark):
        if not part.polygon:
            return

        rad = math.radians(part.rotation)
        cos_r = math.cos(rad)
        sin_r = math.sin(rad)

        # Rotate main polygon to get bounds
        main_rotated = []
        for px, py in part.polygon:
            rx = px * cos_r - py * sin_r
            ry = px * sin_r + py * cos_r
            main_rotated.append((rx, ry))
        min_rx = min(p[0] for p in main_rotated)
        min_ry = min(p[1] for p in main_rotated)

        def transform_and_draw(points, pen, brush):
            qpoly = QPolygonF()
            for px, py in points:
                rx = px * cos_r - py * sin_r
                ry = px * sin_r + py * cos_r
                tx = (rx - min_rx + part.x) * scale + ox
                cnc_y = ry - min_ry + part.y
                ty = (sheet_height - cnc_y) * scale + oy
                qpoly.append(QPointF(tx, ty))
            painter.setPen(pen)
            painter.setBrush(brush)
            painter.drawPolygon(qpoly)

        # Colors
        if dark:
            outline_color = QColor(255, 255, 255)
            pocket_color = QColor(100, 180, 255)
            pocket_fill_alpha = 50
        else:
            outline_color = QColor(0, 0, 0)
            pocket_color = QColor(0, 100, 200)
            pocket_fill_alpha = 30

        outline_pen = QPen(outline_color, 1)
        outline_brush = QBrush(Qt.NoBrush)

        if hasattr(part, 'outline_polygons') and part.outline_polygons:
            for pts in part.outline_polygons:
                transform_and_draw(pts, outline_pen, outline_brush)
        else:
            transform_and_draw(part.polygon, outline_pen, outline_brush)

        if hasattr(part, 'pocket_polygons') and part.pocket_polygons:
            pocket_pen = QPen(pocket_color, 1, Qt.DashLine)
            pocket_brush = QBrush(QColor(pocket_color.red(), pocket_color.green(), pocket_color.blue(), pocket_fill_alpha))
            for pts in part.pocket_polygons:
                transform_and_draw(pts, pocket_pen, pocket_brush)

        if hasattr(part, 'internal_polygons') and part.internal_polygons:
            if dark:
                internal_color = QColor(255, 100, 100)
            else:
                internal_color = QColor(204, 0, 0)
            internal_pen = QPen(internal_color, 1)
            internal_brush = QBrush(Qt.NoBrush)
            for pts in part.internal_polygons:
                transform_and_draw(pts, internal_pen, internal_brush)

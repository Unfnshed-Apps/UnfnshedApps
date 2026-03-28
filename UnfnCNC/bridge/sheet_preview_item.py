"""
QQuickPaintedItem for rendering the read-only sheet layout preview in QML.
"""

from PySide6.QtCore import Qt, Property, Signal
from PySide6.QtGui import QPainter, QPen, QBrush, QColor
from PySide6.QtQuick import QQuickPaintedItem
from PySide6.QtQml import qmlRegisterType

from bridge.preview_utils import compute_preview_transform, draw_polygon_group


class SheetPreviewItem(QQuickPaintedItem):
    darkModeChanged = Signal()

    _shared_cutting_ctrl = None

    @classmethod
    def set_shared_cutting_ctrl(cls, ctrl):
        cls._shared_cutting_ctrl = ctrl

    def __init__(self, parent=None):
        super().__init__(parent)
        self._dark_mode = False
        self.setAntialiasing(True)
        if SheetPreviewItem._shared_cutting_ctrl:
            SheetPreviewItem._shared_cutting_ctrl.previewChanged.connect(self.update)

    @staticmethod
    def register():
        qmlRegisterType(SheetPreviewItem, "UnfnCNC", 1, 0, "SheetPreviewItem")

    def _get_dark_mode(self):
        return self._dark_mode

    def _set_dark_mode(self, val):
        if self._dark_mode != val:
            self._dark_mode = val
            self.darkModeChanged.emit()
            self.update()

    darkMode = Property(bool, _get_dark_mode, _set_dark_mode, notify=darkModeChanged)

    def paint(self, painter: QPainter):
        ctrl = SheetPreviewItem._shared_cutting_ctrl
        geometry = ctrl.current_geometry if ctrl else None

        if not geometry or not geometry.polygons:
            painter.setPen(QColor("#888888"))
            painter.drawText(
                0, 0, int(self.width()), int(self.height()),
                Qt.AlignCenter, "No sheet loaded"
            )
            return

        bbox = geometry.bounding_box
        min_x, min_y = bbox.min_x, bbox.min_y
        max_x, max_y = bbox.max_x, bbox.max_y

        if geometry.sheet_boundary:
            for x, y in geometry.sheet_boundary:
                min_x = min(min_x, x)
                min_y = min(min_y, y)
                max_x = max(max_x, x)
                max_y = max(max_y, y)

        t = compute_preview_transform(
            min_x, min_y, max_x, max_y,
            self.width(), self.height(), padding=10
        )
        if t is None:
            return

        dark = self._dark_mode
        if dark:
            line_color = QColor("#ffffff")
            fill_color = QColor("#404040")
            pocket_line_color = QColor("#aaaaaa")
            pocket_fill_color = QColor("#505050")
        else:
            line_color = QColor("#333333")
            fill_color = QColor("#f0f0f0")
            pocket_line_color = QColor("#666666")
            pocket_fill_color = QColor("#e0e0e0")

        # Sheet boundary
        if geometry.sheet_boundary and len(geometry.sheet_boundary) >= 3:
            boundary_pen = QPen(QColor("#888888") if dark else QColor("#aaaaaa"))
            boundary_pen.setWidthF(1.0)
            boundary_pen.setStyle(Qt.DashLine)
            draw_polygon_group(
                painter, [geometry.sheet_boundary], t,
                boundary_pen, QBrush(Qt.NoBrush)
            )

        # Outline polygons
        pen = QPen(line_color)
        pen.setWidthF(1.0)
        draw_polygon_group(
            painter, geometry.outline_polygons, t,
            pen, QBrush(fill_color)
        )

        # Internal polygons (through-cut holes) — dotted lines
        if geometry.internal_polygons:
            internal_pen = QPen(line_color)
            internal_pen.setWidthF(1.0)
            internal_pen.setStyle(Qt.DotLine)
            bg_color = QColor("#2b2b2b") if dark else QColor("#ffffff")
            draw_polygon_group(
                painter, geometry.internal_polygons, t,
                internal_pen, QBrush(bg_color)
            )

        # Pocket polygons
        if geometry.pocket_polygons:
            pocket_pen = QPen(pocket_line_color)
            pocket_pen.setWidthF(1.0)
            pocket_pen.setStyle(Qt.DashLine)
            draw_polygon_group(
                painter, geometry.pocket_polygons, t,
                pocket_pen, QBrush(pocket_fill_color)
            )

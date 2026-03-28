"""
Base DXF preview item for rendering 40x40 DXF thumbnails in QML.

Subclass and call register() with the app's QML module name.
"""

from PySide6.QtCore import Property, Signal, QPointF
from PySide6.QtGui import QPainter, QPen, QBrush, QColor, QPolygonF
from PySide6.QtQuick import QQuickPaintedItem


class DXFPreviewItemBase(QQuickPaintedItem):
    dxfFilenameChanged = Signal()
    darkModeChanged = Signal()

    _shared_dxf_loader = None

    @classmethod
    def set_shared_dxf_loader(cls, loader):
        cls._shared_dxf_loader = loader

    def __init__(self, parent=None):
        super().__init__(parent)
        self._dxf_filename = ""
        self._dark_mode = False
        self._geometry = None
        self.setAntialiasing(True)

    def _get_dxf_filename(self):
        return self._dxf_filename

    def _set_dxf_filename(self, val):
        if self._dxf_filename != val:
            self._dxf_filename = val
            self._load_geometry()
            self.dxfFilenameChanged.emit()
            self.update()

    dxfFilename = Property(str, _get_dxf_filename, _set_dxf_filename, notify=dxfFilenameChanged)

    def _get_dark_mode(self):
        return self._dark_mode

    def _set_dark_mode(self, val):
        if self._dark_mode != val:
            self._dark_mode = val
            self.darkModeChanged.emit()
            self.update()

    darkMode = Property(bool, _get_dark_mode, _set_dark_mode, notify=darkModeChanged)

    def _load_geometry(self):
        self._geometry = None
        loader = self.__class__._shared_dxf_loader
        if not self._dxf_filename or not loader:
            return
        try:
            self._geometry = loader.load_part(self._dxf_filename)
        except Exception:
            pass

    def paint(self, painter: QPainter):
        geom = self._geometry
        if not geom or not geom.polygons:
            return

        padding = 4
        widget_size = min(self.width(), self.height()) - 2 * padding
        geom_width = geom.width
        geom_height = geom.height
        if geom_width <= 0 or geom_height <= 0:
            return

        scale = widget_size / max(geom_width, geom_height)
        scaled_width = geom_width * scale
        scaled_height = geom_height * scale
        offset_x = padding + (widget_size - scaled_width) / 2
        offset_y = padding + (widget_size - scaled_height) / 2

        bbox = geom.bounding_box
        min_x = bbox.min_x
        min_y = bbox.min_y

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

        pen = QPen(line_color)
        pen.setWidthF(1.0)
        painter.setPen(pen)
        painter.setBrush(QBrush(fill_color))

        for polygon in geom.outline_polygons:
            if len(polygon) < 3:
                continue
            qpoly = QPolygonF()
            for x, y in polygon:
                px = offset_x + (x - min_x) * scale
                py = offset_y + scaled_height - (y - min_y) * scale
                qpoly.append(QPointF(px, py))
            painter.drawPolygon(qpoly)

        if geom.pocket_polygons:
            from PySide6.QtCore import Qt
            pen.setColor(pocket_line_color)
            pen.setStyle(Qt.DashLine)
            painter.setPen(pen)
            painter.setBrush(QBrush(pocket_fill_color))
            for polygon in geom.pocket_polygons:
                if len(polygon) < 3:
                    continue
                qpoly = QPolygonF()
                for x, y in polygon:
                    px = offset_x + (x - min_x) * scale
                    py = offset_y + scaled_height - (y - min_y) * scale
                    qpoly.append(QPointF(px, py))
                painter.drawPolygon(qpoly)

        if geom.internal_polygons:
            from PySide6.QtCore import Qt
            internal_color = QColor("#ff6666") if dark else QColor("#cc0000")
            pen.setColor(internal_color)
            pen.setStyle(Qt.SolidLine)
            painter.setPen(pen)
            painter.setBrush(QBrush(Qt.NoBrush))
            for polygon in geom.internal_polygons:
                if len(polygon) < 3:
                    continue
                qpoly = QPolygonF()
                for x, y in polygon:
                    px = offset_x + (x - min_x) * scale
                    py = offset_y + scaled_height - (y - min_y) * scale
                    qpoly.append(QPointF(px, py))
                painter.drawPolygon(qpoly)

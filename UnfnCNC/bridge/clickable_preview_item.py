"""
QQuickPaintedItem for interactive damage marking — operators click parts
to toggle their damaged state.
"""

from PySide6.QtCore import Qt, Property, Signal, QPointF
from PySide6.QtGui import QPainter, QPen, QBrush, QColor, QPolygonF, QPainterPath
from PySide6.QtQuick import QQuickPaintedItem
from PySide6.QtQml import qmlRegisterType

from bridge.preview_utils import compute_preview_transform, dxf_to_widget


class ClickablePreviewItem(QQuickPaintedItem):
    darkModeChanged = Signal()
    tooltipTextChanged = Signal()

    _shared_damage_ctrl = None

    @classmethod
    def set_shared_damage_ctrl(cls, ctrl):
        cls._shared_damage_ctrl = ctrl

    def __init__(self, parent=None):
        super().__init__(parent)
        self._dark_mode = False
        self._hovered_index = -1
        self._tooltip_text = ""
        self.setAntialiasing(True)
        self.setAcceptedMouseButtons(Qt.LeftButton)
        self.setAcceptHoverEvents(True)

        if ClickablePreviewItem._shared_damage_ctrl:
            ClickablePreviewItem._shared_damage_ctrl.previewPartsChanged.connect(self.update)

    @staticmethod
    def register():
        qmlRegisterType(ClickablePreviewItem, "UnfnCNC", 1, 0, "ClickablePreviewItem")

    # ---- Properties ----

    def _get_dark_mode(self):
        return self._dark_mode

    def _set_dark_mode(self, val):
        if self._dark_mode != val:
            self._dark_mode = val
            self.darkModeChanged.emit()
            self.update()

    darkMode = Property(bool, _get_dark_mode, _set_dark_mode, notify=darkModeChanged)

    @Property(str, notify=tooltipTextChanged)
    def tooltipText(self):
        return self._tooltip_text

    # ---- Transform helpers ----

    def _get_parts_and_boundary(self):
        ctrl = ClickablePreviewItem._shared_damage_ctrl
        if not ctrl:
            return [], None
        return ctrl.part_instances, ctrl.sheet_boundary

    def _get_transform(self):
        parts, boundary = self._get_parts_and_boundary()
        if not parts:
            return None

        all_min_x = all_min_y = float('inf')
        all_max_x = all_max_y = float('-inf')

        for part in parts:
            bb = part.bounding_box
            all_min_x = min(all_min_x, bb.min_x)
            all_min_y = min(all_min_y, bb.min_y)
            all_max_x = max(all_max_x, bb.max_x)
            all_max_y = max(all_max_y, bb.max_y)

        if boundary:
            for x, y in boundary:
                all_min_x = min(all_min_x, x)
                all_min_y = min(all_min_y, y)
                all_max_x = max(all_max_x, x)
                all_max_y = max(all_max_y, y)

        return compute_preview_transform(
            all_min_x, all_min_y, all_max_x, all_max_y,
            self.width(), self.height(), padding=20
        )

    def _build_widget_paths(self):
        parts, _ = self._get_parts_and_boundary()
        t = self._get_transform()
        if t is None:
            return [], None
        paths = []
        for part in parts:
            path = QPainterPath()
            for entity in part.entities:
                if len(entity.polygon) < 3:
                    continue
                poly = QPolygonF()
                for x, y in entity.polygon:
                    wx, wy = dxf_to_widget(x, y, t)
                    poly.append(QPointF(wx, wy))
                first = entity.polygon[0]
                wx, wy = dxf_to_widget(first[0], first[1], t)
                poly.append(QPointF(wx, wy))
                path.addPolygon(poly)
            paths.append(path)
        return paths, t

    # ---- Paint ----

    def paint(self, painter: QPainter):
        parts, boundary = self._get_parts_and_boundary()

        if not parts:
            painter.setPen(QColor("#888888"))
            painter.drawText(
                0, 0, int(self.width()), int(self.height()),
                Qt.AlignCenter, "No parts to display"
            )
            return

        widget_paths, t = self._build_widget_paths()
        if t is None:
            return

        # Sheet boundary
        if boundary and len(boundary) >= 3:
            painter.setPen(QPen(QColor(150, 150, 150), 1, Qt.DashLine))
            painter.setBrush(Qt.NoBrush)
            poly = QPolygonF()
            for x, y in boundary:
                wx, wy = dxf_to_widget(x, y, t)
                poly.append(QPointF(wx, wy))
            painter.drawPolygon(poly)

        for i, part in enumerate(parts):
            if part.is_damaged:
                fill = QColor(220, 50, 50, 80)
                outline = QColor(200, 0, 0)
                pw = 2.0
            elif i == self._hovered_index:
                fill = QColor(70, 130, 220, 60)
                outline = QColor(50, 100, 200)
                pw = 2.0
            else:
                fill = QColor(220, 220, 220, 40)
                outline = QColor(80, 80, 80)
                pw = 1.0

            painter.setPen(QPen(outline, pw))
            painter.setBrush(QBrush(fill))
            if i < len(widget_paths):
                painter.drawPath(widget_paths[i])

            # Red X for damaged parts
            if part.is_damaged:
                bb = part.bounding_box
                x1, y1 = dxf_to_widget(bb.min_x, bb.min_y, t)
                x2, y2 = dxf_to_widget(bb.max_x, bb.max_y, t)
                painter.setPen(QPen(QColor(200, 0, 0, 150), 2))
                painter.drawLine(QPointF(x1, y1), QPointF(x2, y2))
                painter.drawLine(QPointF(x1, y2), QPointF(x2, y1))

    # ---- Mouse handling ----

    def mousePressEvent(self, event):
        ctrl = ClickablePreviewItem._shared_damage_ctrl
        if not ctrl or event.button() != Qt.LeftButton:
            return

        pos = event.position()
        widget_paths, _ = self._build_widget_paths()
        for i, path in enumerate(widget_paths):
            if path.contains(QPointF(pos.x(), pos.y())):
                ctrl.toggleDamage(i)
                self.update()
                return

    def hoverMoveEvent(self, event):
        parts, _ = self._get_parts_and_boundary()
        pos = event.position()
        old = self._hovered_index
        self._hovered_index = -1

        widget_paths, _ = self._build_widget_paths()
        for i, path in enumerate(widget_paths):
            if path.contains(QPointF(pos.x(), pos.y())):
                self._hovered_index = i
                break

        if self._hovered_index != old:
            if self._hovered_index >= 0 and self._hovered_index < len(parts):
                p = parts[self._hovered_index]
                name = p.component_name or f"Part {p.instance_id}"
                status = "DAMAGED" if p.is_damaged else "OK"
                new_tip = f"{name} - {status}"
            else:
                new_tip = ""

            if new_tip != self._tooltip_text:
                self._tooltip_text = new_tip
                self.tooltipTextChanged.emit()
            self.update()

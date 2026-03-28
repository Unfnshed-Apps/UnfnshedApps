"""Controller for calculating utilization from manually nested DXF files."""

import math
from pathlib import Path
from urllib.parse import unquote
from urllib.parse import urlparse

import ezdxf
from PySide6.QtCore import QObject, Property, Signal, Slot


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


class UtilizationController(QObject):
    resultChanged = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._filename = ""
        self._sheet_area = 0.0
        self._usable_area = 0.0
        self._part_area = 0.0
        self._part_count = 0
        self._utilization = ""
        self._sheet_utilization = ""
        self._error_text = ""

    # --- Properties ---

    @Property(str, notify=resultChanged)
    def filename(self):
        return self._filename

    @Property(float, notify=resultChanged)
    def sheetArea(self):
        return self._sheet_area

    @Property(float, notify=resultChanged)
    def usableArea(self):
        return self._usable_area

    @Property(float, notify=resultChanged)
    def partArea(self):
        return self._part_area

    @Property(int, notify=resultChanged)
    def partCount(self):
        return self._part_count

    @Property(str, notify=resultChanged)
    def utilization(self):
        return self._utilization

    @Property(str, notify=resultChanged)
    def sheetUtilization(self):
        return self._sheet_utilization

    @Property(str, notify=resultChanged)
    def errorText(self):
        return self._error_text

    # --- Slots ---

    @Slot(str)
    def calculateFromFile(self, file_url: str):
        """Parse a DXF file and calculate utilization."""
        self._clear()

        try:
            # Convert QUrl string to path
            parsed = urlparse(file_url)
            path = unquote(parsed.path)
            self._filename = Path(path).name

            self._parse_dxf(path)
        except Exception as e:
            self._error_text = str(e)

        self.resultChanged.emit()

    # --- Private ---

    def _clear(self):
        self._filename = ""
        self._sheet_area = 0.0
        self._usable_area = 0.0
        self._part_area = 0.0
        self._part_count = 0
        self._utilization = ""
        self._sheet_utilization = ""
        self._error_text = ""

    def _parse_dxf(self, path: str):
        doc = ezdxf.readfile(path)
        msp = doc.modelspace()

        outline_areas = []
        internal_areas = []

        for entity in msp:
            layer = entity.dxf.layer.strip().lower()
            entity_type = entity.dxftype()

            if layer == "sheet boundary":
                points = self._get_polygon_points(entity, entity_type)
                if points:
                    self._sheet_area = _polygon_area(points)

            elif layer == "edge margin":
                points = self._get_polygon_points(entity, entity_type)
                if points:
                    self._usable_area = _polygon_area(points)

            elif layer == "outline":
                points = self._get_polygon_points(entity, entity_type)
                if points:
                    outline_areas.append(_polygon_area(points))

            elif layer == "internal":
                points = self._get_polygon_points(entity, entity_type)
                if points:
                    internal_areas.append(_polygon_area(points))
            # "pocket" and other layers → ignored

        if self._sheet_area == 0.0:
            self._error_text = "No 'Sheet Boundary' layer found in DXF file."
            return

        if self._usable_area == 0.0:
            # Fall back to sheet area if no edge margin defined
            self._usable_area = self._sheet_area

        self._part_count = len(outline_areas)
        total_outline = sum(outline_areas)
        total_internal = sum(internal_areas)
        self._part_area = total_outline - total_internal

        if self._usable_area > 0:
            util = (self._part_area / self._usable_area) * 100
            self._utilization = f"{util:.1f}%"

        if self._sheet_area > 0:
            sheet_util = (self._part_area / self._sheet_area) * 100
            self._sheet_utilization = f"{sheet_util:.1f}%"

    def _get_polygon_points(self, entity, entity_type: str):
        """Extract polygon points from a DXF entity."""
        if entity_type == "LWPOLYLINE":
            if entity.closed:
                return [(p[0], p[1]) for p in entity.get_points()]
        elif entity_type == "POLYLINE":
            if entity.is_closed:
                return [(v.dxf.location.x, v.dxf.location.y) for v in entity.vertices]
        elif entity_type == "CIRCLE":
            cx = entity.dxf.center.x
            cy = entity.dxf.center.y
            r = entity.dxf.radius
            # Approximate circle as polygon for area calculation
            n = 64
            return [
                (cx + r * math.cos(2 * math.pi * i / n),
                 cy + r * math.sin(2 * math.pi * i / n))
                for i in range(n)
            ]
        return None

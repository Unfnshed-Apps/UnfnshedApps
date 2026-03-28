"""
Shared coordinate-transform and polygon-rendering helpers used by both
SheetPreviewItem and ClickablePreviewItem.
"""

from PySide6.QtCore import QPointF
from PySide6.QtGui import QPolygonF


def compute_preview_transform(min_x, min_y, max_x, max_y,
                              widget_w, widget_h, padding=10):
    """Return transform parameters that map DXF coordinates into widget pixels.

    Returns a dict with keys:
        scale, offset_x, offset_y, scaled_width, scaled_height, min_x, min_y

    Returns None if the geometry is degenerate (zero-size).
    """
    geom_w = max_x - min_x
    geom_h = max_y - min_y
    if geom_w <= 0 or geom_h <= 0:
        return None

    avail_w = widget_w - 2 * padding
    avail_h = widget_h - 2 * padding
    scale = min(avail_w / geom_w, avail_h / geom_h)
    scaled_width = geom_w * scale
    scaled_height = geom_h * scale
    offset_x = padding + (avail_w - scaled_width) / 2
    offset_y = padding + (avail_h - scaled_height) / 2

    return {
        "scale": scale,
        "offset_x": offset_x,
        "offset_y": offset_y,
        "scaled_width": scaled_width,
        "scaled_height": scaled_height,
        "min_x": min_x,
        "min_y": min_y,
    }


def dxf_to_widget(x, y, t):
    """Convert a single (x, y) DXF coordinate to widget pixel coordinates.

    *t* is the transform dict returned by ``compute_preview_transform``.
    """
    wx = t["offset_x"] + (x - t["min_x"]) * t["scale"]
    wy = t["offset_y"] + t["scaled_height"] - (y - t["min_y"]) * t["scale"]
    return wx, wy


def draw_polygon_group(painter, polygons, t, pen, brush):
    """Draw a list of polygons through the given transform.

    Sets *pen* and *brush* on *painter*, then iterates over *polygons*
    (each an iterable of (x, y) tuples) and draws them.  Polygons with
    fewer than 3 vertices are skipped.
    """
    painter.setPen(pen)
    painter.setBrush(brush)
    for polygon in polygons:
        if len(polygon) < 3:
            continue
        qpoly = QPolygonF()
        for x, y in polygon:
            px, py = dxf_to_widget(x, y, t)
            qpoly.append(QPointF(px, py))
        painter.drawPolygon(qpoly)

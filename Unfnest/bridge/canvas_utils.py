"""Shared helpers for QQuickPaintedItem sheet canvases.

Both the read-only preview (`sheet_preview_item.py`) and the editable
canvas (`manual_nest_canvas_item.py`) need to fit a sheet-of-inches into
a pixel-sized widget and project sheet coordinates onto screen space with
a y-axis flip (sheet y-up → pixel y-down). Extracted here so the math
lives in one place.
"""
from __future__ import annotations


def compute_sheet_scale(
    widget_w: float, widget_h: float,
    sheet_w: float, sheet_h: float,
    margin_px: float,
) -> tuple[float, float, float]:
    """Return (scale, offset_x, offset_y) to fit a sheet of inches into a
    widget of pixels with a uniform margin. Scale preserves aspect ratio."""
    avail_w = max(1.0, widget_w - 2 * margin_px)
    avail_h = max(1.0, widget_h - 2 * margin_px)
    scale = min(
        avail_w / max(sheet_w, 0.001),
        avail_h / max(sheet_h, 0.001),
    )
    drawn_w = sheet_w * scale
    drawn_h = sheet_h * scale
    offset_x = margin_px + (avail_w - drawn_w) / 2.0
    offset_y = margin_px + (avail_h - drawn_h) / 2.0
    return scale, offset_x, offset_y

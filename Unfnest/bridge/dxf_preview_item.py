"""
QQuickPaintedItem for rendering 40x40 DXF thumbnails in QML.
"""

from PySide6.QtQml import qmlRegisterType
from shared.dxf_preview_base import DXFPreviewItemBase


class DXFPreviewItem(DXFPreviewItemBase):
    @staticmethod
    def register():
        qmlRegisterType(DXFPreviewItem, "Unfnest", 1, 0, "DXFPreviewItem")

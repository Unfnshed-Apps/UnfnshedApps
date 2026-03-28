"""
Settings controller — nesting settings + unit conversion.
"""

from PySide6.QtCore import QObject, Signal, Slot, QSettings

_SETTINGS_ORG = "NestingApp"
_SETTINGS_APP = "NestingApp"


class SettingsController(QObject):
    settingsChanged = Signal()

    INCH_TO_MM = 25.4

    def __init__(self, parent=None):
        super().__init__(parent)
        self._settings = QSettings(_SETTINGS_ORG, _SETTINGS_APP)

    @Slot(result=float)
    def sheetWidth(self):
        return self._settings.value("sheet_width", 48.0, type=float)

    @Slot(result=float)
    def sheetHeight(self):
        return self._settings.value("sheet_height", 96.0, type=float)

    @Slot(result=float)
    def partSpacing(self):
        return self._settings.value("part_spacing", 0.75, type=float)

    @Slot(result=float)
    def edgeMargin(self):
        return self._settings.value("edge_margin", 0.75, type=float)

    @Slot(result=bool)
    def isMetric(self):
        return self._settings.value("units_metric", False, type=bool)

    @Slot(float, float, float, float, bool)
    def saveSettings(self, sheet_width, sheet_height, part_spacing, edge_margin, is_metric):
        """Save settings. Values are in current display units."""
        factor = 1.0 / self.INCH_TO_MM if is_metric else 1.0
        self._settings.setValue("sheet_width", sheet_width * factor)
        self._settings.setValue("sheet_height", sheet_height * factor)
        self._settings.setValue("part_spacing", part_spacing * factor)
        self._settings.setValue("edge_margin", edge_margin * factor)
        self._settings.setValue("units_metric", is_metric)
        self.settingsChanged.emit()


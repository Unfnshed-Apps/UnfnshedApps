"""
Damage reporting controller — manages part instance state, clickable preview
data, and the ambiguous resolution flow.
"""

from __future__ import annotations

import json

from PySide6.QtCore import QObject, Property, Signal, Slot

from bridge.models.parts_model import PartsModel
from bridge.models.damage_summary_model import DamageSummaryModel


class DamageController(QObject):
    previewPartsChanged = Signal()
    summaryChanged = Signal()
    ordersTextChanged = Signal()
    hasClickablePreviewChanged = Signal()

    # Emitted when ambiguous resolution is needed
    # groupIndex, candidatesJson (JSON array of {component_id, component_name, count}), damagedCount
    ambiguousResolutionNeeded = Signal(int, str, int)

    # Final outputs
    damageReportReady = Signal(str)      # JSON of [{component_id, quantity}]
    damageReportCancelled = Signal()

    def __init__(self, app_ctrl, parent=None):
        super().__init__(parent)
        self._app = app_ctrl

        self._part_instances = []
        self._ambiguous_groups = []
        self._sheet_boundary = None
        self._dialog_parts = []
        self._has_clickable_preview = False
        self._orders_text = ""
        self._current_geometry = None

        # Pending ambiguous resolution state
        self._pending_damages = {}
        self._pending_groups = []
        self._current_group_index = 0

        self._summary_model = DamageSummaryModel()
        self._fallback_model = PartsModel()

    # ---- QML Properties ----

    @Property(bool, notify=hasClickablePreviewChanged)
    def hasClickablePreview(self):
        return self._has_clickable_preview

    @Property(QObject, constant=True)
    def summaryModel(self):
        return self._summary_model

    @Property(QObject, constant=True)
    def fallbackPartsModel(self):
        return self._fallback_model

    @Property(str, notify=ordersTextChanged)
    def ordersText(self):
        return self._orders_text

    # ---- Python accessors ----

    @property
    def part_instances(self):
        return self._part_instances

    @property
    def sheet_boundary(self):
        return self._sheet_boundary

    @property
    def current_geometry(self):
        return self._current_geometry

    # ---- Prepare data ----

    def prepareForSheet(self, dialog_parts, geometry, part_instances,
                        ambiguous_groups, sheet_boundary, orders_on_sheet):
        """Called from cutting controller with all data needed for damage dialog."""
        self._dialog_parts = dialog_parts
        self._current_geometry = geometry
        self._part_instances = part_instances or []
        self._ambiguous_groups = ambiguous_groups or []
        self._sheet_boundary = sheet_boundary
        self._has_clickable_preview = bool(self._part_instances)
        self._orders_text = ", ".join(orders_on_sheet) if orders_on_sheet else ""

        # Reset damage state
        for p in self._part_instances:
            p.is_damaged = False

        self._pending_damages = {}
        self._pending_groups = []
        self._current_group_index = 0

        if self._has_clickable_preview:
            self._summary_model.resetFromInstances(self._part_instances)
        else:
            self._fallback_model.resetItems(self._dialog_parts)

        self.hasClickablePreviewChanged.emit()
        self.previewPartsChanged.emit()
        self.summaryChanged.emit()
        self.ordersTextChanged.emit()

    # ---- Clickable mode ----

    @Slot(int)
    def toggleDamage(self, instance_index):
        """Toggle damage state for a part instance (called from clickable preview)."""
        if 0 <= instance_index < len(self._part_instances):
            p = self._part_instances[instance_index]
            p.is_damaged = not p.is_damaged
            self._summary_model.resetFromInstances(self._part_instances)
            self.summaryChanged.emit()
            self.previewPartsChanged.emit()

    # ---- Fallback mode ----

    @Slot(int, int)
    def setFallbackDamage(self, row, qty):
        """Set damage count for a row in fallback mode."""
        self._fallback_model.setDamaged(row, qty)

    # ---- Submit ----

    @Slot()
    def submitDamage(self):
        """Collect damages, check for ambiguous groups, emit result or start resolution."""
        if self._has_clickable_preview:
            self._submitFromPreview()
        else:
            self._submitFromFallback()

    def _submitFromFallback(self):
        result = []
        for row in range(self._fallback_model.rowCount()):
            item = self._fallback_model.getItemAtRow(row)
            if item and item["damaged"] > 0:
                result.append({
                    "component_id": item["component_id"],
                    "quantity": item["damaged"],
                })
        self.damageReportReady.emit(json.dumps(result))

    def _submitFromPreview(self):
        # Collect non-ambiguous damages
        damages = {}
        for part in self._part_instances:
            if part.is_damaged and part.component_id is not None and part.ambiguous_group is None:
                damages[part.component_id] = damages.get(part.component_id, 0) + 1

        self._pending_damages = dict(damages)

        # Check for ambiguous groups with damaged parts
        self._pending_groups = []
        for group in self._ambiguous_groups:
            damaged_in_group = sum(
                1 for p in self._part_instances
                if p.ambiguous_group == group.group_id and p.is_damaged
            )
            if damaged_in_group > 0:
                self._pending_groups.append((group, damaged_in_group))

        if self._pending_groups:
            self._current_group_index = 0
            self._requestNextAmbiguousResolution()
        else:
            self._emitFinalReport()

    def _requestNextAmbiguousResolution(self):
        if self._current_group_index >= len(self._pending_groups):
            self._emitFinalReport()
            return

        group, damaged_count = self._pending_groups[self._current_group_index]
        candidates_json = json.dumps(group.candidate_components)
        self.ambiguousResolutionNeeded.emit(
            self._current_group_index, candidates_json, damaged_count
        )

    @Slot(int, str)
    def resolveAmbiguous(self, group_index, resolution_json):
        """Process resolution for an ambiguous group and continue."""
        try:
            resolutions = json.loads(resolution_json)
        except (json.JSONDecodeError, ValueError):
            resolutions = []

        for entry in resolutions:
            cid = entry["component_id"]
            qty = entry["quantity"]
            if qty > 0:
                self._pending_damages[cid] = self._pending_damages.get(cid, 0) + qty

        self._current_group_index += 1
        self._requestNextAmbiguousResolution()

    def _emitFinalReport(self):
        result = [
            {"component_id": cid, "quantity": qty}
            for cid, qty in self._pending_damages.items() if qty > 0
        ]
        self.damageReportReady.emit(json.dumps(result))

    @Slot()
    def cancelDamage(self):
        self.damageReportCancelled.emit()

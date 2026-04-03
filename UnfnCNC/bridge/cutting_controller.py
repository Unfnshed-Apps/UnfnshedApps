"""
Cutting state machine controller — manages IDLE/CUTTING states, sheet claiming,
G-code generation, queue refresh, and orchestrates the damage reporting flow.
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import QObject, Property, Signal, Slot, QTimer
from src.config import load_gcode_settings, load_gcode_and_tools, ZERO_FROM_TOP, POCKET_DEPTH_OFFSET
from src.gcode_generator import GCodeGenerator, GCodeSettings
from src.part_matcher import (
    group_entities_into_parts,
    match_instances_to_components,
    match_instances_to_placements,
)


class CuttingController(QObject):
    # State
    stateChanged = Signal()
    sheetInfoChanged = Signal()
    queueInfoChanged = Signal()
    previewChanged = Signal()

    # Busy overlay
    busyChanged = Signal()

    # Status
    statusMessage = Signal(str, int)  # message, timeout_ms
    operationFailed = Signal(str)     # error message for QML dialog

    # Damage flow
    damageCheckRequested = Signal()   # QML opens "Were any parts damaged?" dialog

    # Thickness workflow
    thicknessNeeded = Signal()    # QML opens thickness dialog

    # Settings changed (zero reference etc.)
    settingsRefreshed = Signal()

    # Orphan detection
    orphanDetected = Signal(str, str, int, int)  # jobName, sheetText, jobId, sheetId

    def __init__(self, app_ctrl, parent=None):
        super().__init__(parent)
        self._app = app_ctrl

        self._state = "idle"
        self._is_prototype = False
        self._is_busy = False
        self._busy_text = ""

        self._current_job = None
        self._current_sheet = None
        self._current_geometry = None
        self._actual_thickness = None
        self._pocket_targets = None

        # Info text properties
        self._job_name = ""
        self._sheet_text = ""
        self._gcode_text = ""
        self._parts_text = ""
        self._orders_text = ""
        self._queue_text = "Queue: loading..."
        self._completed_text = ""
        self._bundle_text = ""

        # Cached zero reference string
        self._zero_reference = self._compute_zero_reference()

        # Queue auto-refresh every 5 seconds
        self._queue_timer = QTimer(self)
        self._queue_timer.setInterval(5000)
        self._queue_timer.timeout.connect(self.refreshQueue)

    def start(self):
        """Start queue timer. Call after initialization."""
        self._queue_timer.start()

    # ==================== QML Properties ====================

    @Property(bool, notify=stateChanged)
    def isIdle(self):
        return self._state == "idle"

    @Property(bool, notify=stateChanged)
    def isCutting(self):
        return self._state == "cutting"

    @Property(bool, notify=stateChanged)
    def isPrototype(self):
        return self._is_prototype

    @Property(bool, notify=busyChanged)
    def isBusy(self):
        return self._is_busy

    @Property(str, notify=busyChanged)
    def busyText(self):
        return self._busy_text

    @Property(str, notify=sheetInfoChanged)
    def jobName(self):
        return self._job_name

    @Property(str, notify=sheetInfoChanged)
    def sheetText(self):
        return self._sheet_text

    @Property(str, notify=sheetInfoChanged)
    def gcodeText(self):
        return self._gcode_text

    @Property(str, notify=sheetInfoChanged)
    def partsText(self):
        return self._parts_text

    @Property(str, notify=sheetInfoChanged)
    def ordersText(self):
        return self._orders_text

    @Property(str, notify=queueInfoChanged)
    def queueText(self):
        return self._queue_text

    @Property(str, notify=queueInfoChanged)
    def completedText(self):
        return self._completed_text

    @Property(str, notify=sheetInfoChanged)
    def bundleText(self):
        return self._bundle_text

    @Property(str, notify=settingsRefreshed)
    def zeroReference(self):
        """Current zero reference for display in UI."""
        return self._zero_reference

    def _compute_zero_reference(self):
        settings = load_gcode_settings()
        zero = settings.get('zero_from', 'spoilboard')
        if zero == ZERO_FROM_TOP:
            return "Current zero is from top of sheet"
        return "Current zero is from spoilboard"

    def _on_settings_refreshed(self):
        """Recompute cached values when settings change."""
        self._zero_reference = self._compute_zero_reference()
        self.settingsRefreshed.emit()

    # ==================== State Machine ====================

    def _set_state(self, new_state):
        if new_state == "idle":
            self._current_job = None
            self._current_sheet = None
            self._current_geometry = None
            self._actual_thickness = None
            self._pocket_targets = None
            self._is_prototype = False
            self._job_name = "No sheet loaded"
            self._sheet_text = ""
            self._gcode_text = ""
            self._parts_text = ""
            self._orders_text = ""
            self._bundle_text = ""
            self.sheetInfoChanged.emit()
            self.previewChanged.emit()

        self._state = new_state
        self.stateChanged.emit()

    def _set_busy(self, busy, text=""):
        self._is_busy = busy
        self._busy_text = text
        self.busyChanged.emit()

    # ==================== Helpers ====================

    def _prepare_gcode_settings(self):
        """Load G-code settings with sheet thickness applied."""
        gcode_dict, tools = load_gcode_and_tools()
        if self._actual_thickness:
            thick = self._actual_thickness
            gcode_dict['material_thickness'] = thick
        # Pocket depth is always derived: thickness minus 4mm
        mat_thick = gcode_dict.get('material_thickness', 0.7087)
        gcode_dict['pocket_depth'] = mat_thick - POCKET_DEPTH_OFFSET
        tool_diameters = {t["number"]: t["diameter"] for t in tools}
        outline_tool_num = gcode_dict.pop('outline_tool', 5)
        pocket_tool_num = gcode_dict.pop('pocket_tool', 5)
        return GCodeSettings(
            tool_number=outline_tool_num,
            tool_diameter=tool_diameters.get(outline_tool_num, 0.375),
            pocket_tool_number=pocket_tool_num,
            pocket_tool_diameter=tool_diameters.get(pocket_tool_num, 0.375),
            **gcode_dict,
        )

    # ==================== IDLE → CUTTING ====================

    @Slot()
    def loadNextSheet(self):
        self._load_sheet(prototype=False)

    @Slot()
    def loadPrototypeSheet(self):
        self._load_sheet(prototype=True)

    def _load_sheet(self, prototype=False):
        self._is_prototype = prototype
        label = "prototype sheet" if prototype else "sheet"
        self._set_busy(True, f"Claiming {label}...")

        try:
            job_data = self._app.api.claim_next_sheet(
                self._app.config.machine_letter, prototype=prototype
            )
        except Exception as e:
            self._set_busy(False)
            self.operationFailed.emit(f"Failed to claim sheet:\n{e}")
            return

        if job_data is None:
            self._set_busy(False)
            queue_type = "prototype" if prototype else "production"
            self.operationFailed.emit(f"No pending {queue_type} sheets in the queue.")
            return

        self._current_job = job_data
        claimed_sheet = None
        for sheet in job_data.get("sheets", []):
            if (sheet.get("claimed_by") == self._app.config.machine_letter
                    and sheet.get("status") == "cutting"):
                claimed_sheet = sheet
                break

        if not claimed_sheet:
            self._set_busy(False)
            self.operationFailed.emit("Sheet was claimed but could not find it in the response.")
            return

        self._current_sheet = claimed_sheet

        # Always prompt operator for sheet thickness
        self._set_busy(False)
        self.thicknessNeeded.emit()

    def _after_thickness_resolved(self):
        """Complete sheet load after thickness is resolved."""
        self._complete_sheet_load()

    def _complete_sheet_load(self):
        """Finish sheet loading: pocket targets, DXF, G-code, UI update."""
        claimed_sheet = self._current_sheet
        job_data = self._current_job

        # Fetch per-pocket mating thicknesses for variable-pocket sheets
        self._pocket_targets = None
        if claimed_sheet.get("has_variable_pockets"):
            try:
                targets = self._app.api.get_pocket_targets(claimed_sheet.get("id"))
                if targets:
                    self._pocket_targets = targets
            except Exception:
                self.statusMessage.emit(
                    "Warning: Could not fetch pocket targets. Using default thickness.", 5000
                )

        # Load DXF geometry
        dxf_filename = claimed_sheet.get("dxf_filename")
        has_placements = bool(claimed_sheet.get("placements"))
        if dxf_filename:
            try:
                self._current_geometry = self._app.dxf_loader.load_part(
                    dxf_filename, normalize=not has_placements
                )
                if self._current_geometry and self._current_geometry.variable_pocket_polygons:
                    gen = GCodeGenerator(self._prepare_gcode_settings())
                    # Use mating tab's actual thickness if known
                    preview_thickness = None
                    preview_clearance = None
                    if self._pocket_targets:
                        thicknesses = [pt["mating_thickness_inches"]
                                       for pt in self._pocket_targets
                                       if pt.get("mating_thickness_inches")]
                        if thicknesses:
                            preview_thickness = thicknesses[0]
                            preview_clearance = self._pocket_targets[0].get("clearance_inches")
                    scaled = [
                        gen.scale_variable_pocket_polygon(
                            poly, preview_thickness, preview_clearance
                        )
                        for poly in self._current_geometry.variable_pocket_polygons
                    ]
                    self._current_geometry.pocket_polygons.extend(scaled)
                if self._current_geometry:
                    print(f"[DXF Preview] outlines={len(self._current_geometry.outline_polygons)}"
                          f" pockets={len(self._current_geometry.pocket_polygons)}"
                          f" internals={len(self._current_geometry.internal_polygons)}"
                          f" var_pockets={len(self._current_geometry.variable_pocket_polygons)}")
            except Exception as e:
                print(f"[DXF Load Error] {e}")
                import traceback
                traceback.print_exc()

        # Generate G-code
        if dxf_filename:
            try:
                self._set_busy(True, "Generating G-code...")

                entities = self._app.dxf_loader.load_nesting_dxf_entities(dxf_filename)
                if entities:
                    settings = self._prepare_gcode_settings()

                    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                    sheet_num = claimed_sheet.get("sheet_number", 1)
                    gcode_filename = (
                        f"{self._app.config.machine_letter}_{timestamp}_sheet_{sheet_num}.tap"
                    )

                    hot_folder = Path(self._app.config.hot_folder_path)
                    if hot_folder.is_dir():
                        gcode_path = hot_folder / gcode_filename
                        tmp_path = hot_folder / f".{gcode_filename}.tmp"

                        generator = GCodeGenerator(settings)
                        generator.generate_from_nesting_dxf(
                            entities, tmp_path,
                            pocket_targets=self._pocket_targets,
                        )
                        tmp_path.rename(gcode_path)

                        try:
                            self._app.api.upload_gcode(gcode_path)
                        except Exception:
                            pass

                        try:
                            self._app.api.update_sheet_gcode_filename(
                                self._current_job.get("id"),
                                claimed_sheet.get("id"),
                                gcode_filename,
                            )
                        except Exception:
                            pass

                        self._current_sheet["gcode_filename"] = gcode_filename
                    else:
                        self.statusMessage.emit(f"Hot folder not found: {hot_folder}", 5000)
                else:
                    self.statusMessage.emit("Could not parse nesting DXF for G-code generation.", 5000)
            except Exception as e:
                self.statusMessage.emit(f"G-code generation failed: {e}", 5000)

        # Update info
        job_name = job_data.get("name", f"Job #{job_data.get('id', '?')}")
        total_sheets = job_data.get("total_sheets", 0)
        sheet_num = claimed_sheet.get("sheet_number", "?")
        self._job_name = f"Job: {job_name}"
        self._sheet_text = f"Sheet: {sheet_num} of {total_sheets}"
        self._gcode_text = f"G-code: {self._current_sheet.get('gcode_filename') or 'N/A'}"

        parts = claimed_sheet.get("parts", [])
        if parts:
            lines = []
            for p in parts:
                name = p.get("component_name") or f"Component #{p['component_id']}"
                lines.append(f"  {name} x{p['quantity']}")
            self._parts_text = "\n".join(lines)

        order_ids = claimed_sheet.get("order_ids", [])
        if order_ids:
            self._orders_text = f"Orders: {', '.join(f'#{oid}' for oid in order_ids)}"

        # Bundle info
        bundle_id = claimed_sheet.get("bundle_id")
        if bundle_id:
            try:
                bundle_data = self._app.api.get_bundle(bundle_id)
                if bundle_data:
                    total_in_bundle = bundle_data.get("sheet_count", 0)
                    cut_count = sum(
                        1 for s in bundle_data.get("sheets", [])
                        if s.get("status") == "cut"
                    )
                    remaining = total_in_bundle - cut_count
                    self._bundle_text = (
                        f"Bundle #{bundle_id}: {remaining} of {total_in_bundle} remaining"
                    )
            except Exception:
                self._bundle_text = f"Bundle #{bundle_id}"
        else:
            self._bundle_text = ""

        self._set_busy(False)
        self.sheetInfoChanged.emit()
        self.previewChanged.emit()
        self._set_state("cutting")
        self.refreshQueue()

    # ==================== Thickness Workflow ====================

    @Slot(float, float, float)
    def setSheetThickness(self, m1, m2, m3):
        """Set sheet thickness from 3 measurements, then continue loading."""
        thickness = (m1 + m2 + m3) / 3.0
        self._actual_thickness = thickness
        if self._current_sheet:
            try:
                self._app.api.set_sheet_thickness(
                    self._current_sheet.get("id"), thickness
                )
            except Exception:
                pass
        self.statusMessage.emit(f"Sheet thickness: {thickness:.4f}\"", 3000)
        self._after_thickness_resolved()

    @Slot()
    def cancelThickness(self):
        """Cancel sheet load — release the claimed sheet back to the queue."""
        if self._current_sheet and self._current_job:
            try:
                self._app.api.release_sheet(
                    self._current_job.get("id"),
                    self._current_sheet.get("id"),
                )
            except Exception:
                pass
        self._set_state("idle")
        self.refreshQueue()
        self.statusMessage.emit("Sheet released back to queue.", 3000)

    # ==================== CUTTING → IDLE ====================

    @Slot()
    def cutComplete(self):
        """Called when operator presses Cut Complete. If prototype, skip damage; else ask."""
        if not self._current_sheet or not self._current_job:
            self._set_state("idle")
            return

        if self._is_prototype:
            self._markCutWithDamage([])
        else:
            self.damageCheckRequested.emit()

    @Slot()
    def cutCompleteNoDamage(self):
        """Mark cut with no damage (user answered No to damage question)."""
        self._markCutWithDamage([])

    @Slot(str)
    def finalizeCutWithDamage(self, damages_json):
        """Called via damage controller signal with JSON damage data."""
        try:
            damages = json.loads(damages_json)
        except (json.JSONDecodeError, ValueError):
            damages = []
        self._markCutWithDamage(damages)

    @Slot()
    def cancelCutComplete(self):
        """Cancel — stay in CUTTING state."""
        pass

    def _markCutWithDamage(self, damaged_parts):
        self._set_busy(True, "Marking cut...")

        job_id = self._current_job.get("id")
        sheet_id = self._current_sheet.get("id")

        try:
            self._app.api.mark_sheet_cut(job_id, sheet_id, damaged_parts)
        except Exception as e:
            self._set_busy(False)
            self.operationFailed.emit(f"Failed to mark sheet as cut:\n{e}")
            return

        self._set_busy(False)

        if damaged_parts:
            dmg_summary = ", ".join(f"{d['quantity']} damaged" for d in damaged_parts)
            self.statusMessage.emit(f"Sheet completed. Damaged: {dmg_summary}", 5000)

        self._set_state("idle")
        self.refreshQueue()

    # ==================== Release Sheet ====================

    @Slot()
    def releaseSheet(self):
        """Called from QML after user confirms release."""
        if not self._current_sheet or not self._current_job:
            return

        try:
            self._app.api.release_sheet(
                self._current_job.get("id"),
                self._current_sheet.get("id"),
            )
        except Exception as e:
            self.operationFailed.emit(f"Failed to release sheet:\n{e}")
            return

        gcode_filename = self._current_sheet.get("gcode_filename")
        if gcode_filename:
            gcode_path = Path(self._app.config.hot_folder_path) / gcode_filename
            try:
                gcode_path.unlink(missing_ok=True)
            except OSError:
                pass
            try:
                self._app.api.delete_gcode(gcode_filename)
            except Exception:
                pass

        self._set_state("idle")
        self.refreshQueue()

    # ==================== Queue Refresh ====================

    @Slot()
    def refreshQueue(self):
        try:
            queue = self._app.api.get_queue()
            pending = queue.get("pending_sheets", 0)
            cutting = queue.get("cutting_sheets", 0)
            completed = queue.get("completed_today", 0)
            proto_pending = queue.get("prototype_pending_sheets", 0)
            proto_cutting = queue.get("prototype_cutting_sheets", 0)

            remaining = pending + cutting
            text = f"Queue: {remaining} sheet{'s' if remaining != 1 else ''} remaining"
            proto_total = proto_pending + proto_cutting
            if proto_total > 0:
                text += f" | Prototypes: {proto_total}"
            self._queue_text = text
            self._completed_text = f"Completed today: {completed}"
        except Exception:
            self._queue_text = "Queue: unable to refresh"
            self._completed_text = ""
        self.queueInfoChanged.emit()

    # ==================== Orphan Detection ====================

    @Slot()
    def checkOrphanedSheets(self):
        try:
            claimed = self._app.api.get_claimed_sheets(self._app.config.machine_letter)
        except Exception:
            return

        if not claimed:
            return

        sheet = claimed[0]
        job_name = sheet.get("job_name") or f"Job #{sheet['job_id']}"
        sheet_text = f"Sheet #{sheet['sheet_number']}"
        self.orphanDetected.emit(
            job_name, sheet_text, sheet["job_id"], sheet["sheet_id"]
        )

    @Slot(int, int)
    def releaseOrphan(self, job_id, sheet_id):
        try:
            self._app.api.release_sheet(job_id, sheet_id)
            self.statusMessage.emit("Orphaned sheet released", 3000)
        except Exception as e:
            self.operationFailed.emit(f"Could not release sheet:\n{e}")
        self.refreshQueue()

    # ==================== Damage Data Preparation ====================

    @Slot()
    def prepareDamageData(self):
        """Build part_instances and pass to damage controller.

        Called from QML when the user answers "Yes" to damage question.
        The damage controller reference is set via main.py wiring.
        """
        if not self._current_sheet:
            return

        parts = self._current_sheet.get("parts", [])
        dialog_parts = [
            {
                "component_id": p["component_id"],
                "component_name": p.get("component_name", f"Component #{p['component_id']}"),
                "quantity": p["quantity"],
            }
            for p in parts
        ]

        part_instances = None
        ambiguous_groups = None
        sheet_boundary = None

        try:
            if self._current_geometry and self._current_geometry.sheet_entities:
                part_instances = group_entities_into_parts(
                    self._current_geometry.sheet_entities
                )
                sheet_boundary = self._current_geometry.sheet_boundary

                placements = self._current_sheet.get("placements", [])
                if placements:
                    part_instances = match_instances_to_placements(
                        part_instances, placements
                    )
                    ambiguous_groups = []
                else:
                    sheet_parts_with_dims = []
                    for p in dialog_parts:
                        sp = dict(p)
                        sp["width"] = 0
                        sp["height"] = 0
                        sheet_parts_with_dims.append(sp)

                    for sp in sheet_parts_with_dims:
                        for orig_p in parts:
                            if orig_p["component_id"] == sp["component_id"]:
                                sp["width"] = orig_p.get("width", 0)
                                sp["height"] = orig_p.get("height", 0)
                                break

                    part_instances, ambiguous_groups = match_instances_to_components(
                        part_instances, sheet_parts_with_dims
                    )
        except Exception as e:
            print(f"Could not build clickable preview: {e}")
            part_instances = None

        orders_on_sheet = [
            f"#{oid}" for oid in self._current_sheet.get("order_ids", [])
        ]

        # Pass data to damage controller (set by main.py)
        if self._damage_ctrl:
            self._damage_ctrl.prepareForSheet(
                dialog_parts,
                self._current_geometry,
                part_instances,
                ambiguous_groups,
                sheet_boundary,
                orders_on_sheet,
            )

    # Set by main.py
    _damage_ctrl = None

    def set_damage_controller(self, ctrl):
        self._damage_ctrl = ctrl

    # ==================== App Close ====================

    def releaseOnClose(self):
        """Auto-release any claimed sheet when the app closes."""
        if self._state == "cutting" and self._current_job and self._current_sheet:
            try:
                self._app.api.release_sheet(
                    self._current_job.get("id"),
                    self._current_sheet.get("id"),
                )
            except Exception:
                pass

            gcode_filename = self._current_sheet.get("gcode_filename")
            if gcode_filename:
                gcode_path = Path(self._app.config.hot_folder_path) / gcode_filename
                try:
                    gcode_path.unlink(missing_ok=True)
                except OSError:
                    pass

    # ==================== Accessors for preview items ====================

    @property
    def current_geometry(self):
        return self._current_geometry

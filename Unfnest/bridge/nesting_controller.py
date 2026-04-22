"""
Nesting controller — nest/stop/export + worker thread + preview data.
"""

import logging
import tempfile
from pathlib import Path
from datetime import datetime

from PySide6.QtCore import QObject, Property, Signal, Slot, QThread, QSettings

logger = logging.getLogger(__name__)

from src.nesting import nest_parts
from src.nesting_models import NestingResult, SHEET_WIDTH, SHEET_HEIGHT, PART_SPACING
from src.order_processor import OrderItem

_SETTINGS_ORG = "NestingApp"
_SETTINGS_APP = "NestingApp"


class NestingWorker(QThread):
    """Background thread for nesting operations."""
    finished = Signal(object)
    progress = Signal(int, int)
    status = Signal(str)
    error = Signal(str)
    cancelled = Signal()
    live_update = Signal(object)  # emits list of NestedSheet snapshots

    def __init__(self, parts, nesting_config, db=None, dxf_loader=None,
                 product_comp_qty=None, product_unit_map=None):
        super().__init__()
        self.parts = parts
        self.nesting_config = nesting_config
        self.db = db
        self.dxf_loader = dxf_loader
        self.product_comp_qty = product_comp_qty
        self.product_unit_map = product_unit_map
        self._stop_requested = False
        self._last_live_emit = 0

    def request_stop(self):
        self._stop_requested = True

    def _on_progress(self, current, total):
        self.progress.emit(current, total)
        return not self._stop_requested

    def _on_status(self, message):
        self.status.emit(message)

    def _on_live_update(self, sheet_states):
        """Called from worker thread. Throttle + snapshot + emit."""
        import time
        now = time.monotonic()
        if now - self._last_live_emit < 0.030:  # 30ms throttle
            return
        self._last_live_emit = now
        snapshots = [ss.to_nested_sheet() for ss in sheet_states]
        self.live_update.emit(snapshots)

    def run(self):
        try:
            # Sync DXF files before nesting (runs on worker thread)
            if self.dxf_loader:
                try:
                    if self._stop_requested:
                        self.cancelled.emit()
                        return
                    self.dxf_loader.sync_from_server()
                except Exception:
                    logger.exception("Failed to sync DXF files from server")

            result, metadata = nest_parts(
                self.parts,
                self.db,
                progress_callback=self._on_progress,
                status_callback=self._on_status,
                product_comp_qty=self.product_comp_qty,
                product_unit_map=self.product_unit_map,
                live_callback=self._on_live_update,
                cancel_check=lambda: self._stop_requested,
                dxf_loader=self.dxf_loader,
                **self.nesting_config,
            )
            result.sheet_metadata = metadata
            if self._stop_requested:
                self.cancelled.emit()
            else:
                self.finished.emit(result)
        except Exception as e:
            logger.exception("Nesting failed")
            self.error.emit(str(e))



class NestingController(QObject):
    isRunningChanged = Signal()
    progressCurrentChanged = Signal()
    progressTotalChanged = Signal()
    resultChanged = Signal()
    sheetChanged = Signal()
    autoFollowChanged = Signal()
    statusMessage = Signal(str, int)

    def __init__(self, app_ctrl, settings_ctrl, parent=None):
        super().__init__(parent)
        self._app = app_ctrl
        self._settings_ctrl = settings_ctrl
        self._worker = None
        self._result = None
        self._current_sheet = 0
        self._is_running = False
        self._progress_current = 0
        self._progress_total = 0
        self._component_name_to_id = {}
        self._bundle_map = {}
        self._product_ctrl = None
        self._component_ctrl = None
        # Live preview state
        self._live_sheets = []
        self._live_mode = False
        self._auto_follow = True
        self._user_navigated = False

    # --- Properties ---

    @Property(bool, notify=isRunningChanged)
    def isRunning(self):
        return self._is_running

    @Property(int, notify=progressCurrentChanged)
    def progressCurrent(self):
        return self._progress_current

    @Property(int, notify=progressTotalChanged)
    def progressTotal(self):
        return self._progress_total

    @Property(bool, notify=resultChanged)
    def hasResult(self):
        return len(self._get_active_sheets()) > 0

    @Property(bool, notify=autoFollowChanged)
    def autoFollow(self):
        return self._auto_follow

    @Slot(bool)
    def setAutoFollow(self, value):
        if self._auto_follow != value:
            self._auto_follow = value
            self._user_navigated = not value
            self.autoFollowChanged.emit()
            # When re-enabled, jump to the last sheet immediately
            if value and self._live_mode and self._live_sheets:
                self._current_sheet = len(self._live_sheets) - 1
                self.sheetChanged.emit()

    @Property(int, notify=sheetChanged)
    def currentSheetIndex(self):
        return self._current_sheet

    @Property(int, notify=sheetChanged)
    def totalSheets(self):
        return len(self._get_active_sheets())

    @Property(bool, notify=sheetChanged)
    def canGoPrev(self):
        return self._current_sheet > 0

    @Property(bool, notify=sheetChanged)
    def canGoNext(self):
        return self._current_sheet < len(self._get_active_sheets()) - 1

    @Property(str, notify=resultChanged)
    def resultsText(self):
        if not self._result:
            return "Run nesting to see results"
        return (
            f"Parts: {self._result.parts_placed}/{self._result.total_parts} placed\n"
            f"Sheets: {self._result.sheets_used}\n"
            f"Failed: {self._result.parts_failed}"
        )

    @Property(str, notify=sheetChanged)
    def currentSheetUtilization(self):
        sheet = self.get_current_sheet()
        if sheet is None:
            return ""
        util = getattr(sheet, 'utilization', None)
        if util is None:
            return ""
        return f"{util:.1f}%"

    @Property(str, notify=sheetChanged)
    def sheetGroupText(self):
        if not self._result or not self._bundle_map:
            return ""
        sheet_num = self._current_sheet + 1  # 1-based
        sorted_keys = sorted(self._bundle_map.keys())
        for group_idx, key in enumerate(sorted_keys, 1):
            group_sheets = self._bundle_map[key]
            if sheet_num in group_sheets:
                pos = group_sheets.index(sheet_num) + 1
                return f"Group {group_idx}: {pos} of {len(group_sheets)}"
        return ""

    # --- Sheet navigation ---

    @Slot()
    def nextSheet(self):
        if self._current_sheet < len(self._get_active_sheets()) - 1:
            self._current_sheet += 1
            if self._live_mode and self._auto_follow:
                self._user_navigated = True
                self._auto_follow = False
                self.autoFollowChanged.emit()
            self.sheetChanged.emit()

    @Slot()
    def prevSheet(self):
        if self._current_sheet > 0:
            self._current_sheet -= 1
            if self._live_mode and self._auto_follow:
                self._user_navigated = True
                self._auto_follow = False
                self.autoFollowChanged.emit()
            self.sheetChanged.emit()

    def _get_active_sheets(self):
        """Get the currently active sheet list (live or final result)."""
        if self._live_mode and self._live_sheets:
            return self._live_sheets
        if self._result:
            return self._result.sheets
        return []

    def get_current_sheet(self):
        """Get the current NestedSheet object for the preview item."""
        sheets = self._get_active_sheets()
        if 0 <= self._current_sheet < len(sheets):
            return sheets[self._current_sheet]
        return None

    # --- Nesting ---

    def _create_nesting_config(self):
        """Build nesting config dict from QSettings."""
        s = QSettings(_SETTINGS_ORG, _SETTINGS_APP)
        return {
            "sheet_width": s.value("sheet_width", SHEET_WIDTH, type=float),
            "sheet_height": s.value("sheet_height", SHEET_HEIGHT, type=float),
            "part_spacing": s.value("part_spacing", PART_SPACING, type=float),
            "edge_margin": s.value("edge_margin", PART_SPACING, type=float),
            "optimization_time_budget": s.value("optimization_time_budget", 10.0, type=float),
            "rotation_count": s.value("rotation_count", 4, type=int),
        }

    def _get_dxf_loader_for_sync(self):
        """Return dxf_loader if API sync should happen, else None."""
        if self._app.usingApi:
            return self._app.dxf_loader
        return None

    @Slot()
    def runFromProducts(self):
        """Nest from product quantities."""
        quantities = self._product_ctrl.model.getQuantities() if self._product_ctrl else {}
        parts, product_comp_qty, product_unit_map = self.gatherPartsFromProducts(quantities)
        if not parts:
            self.statusMessage.emit("No parts to nest. Set quantities first.", 5000)
            return
        self._start_nesting(
            parts, product_comp_qty=product_comp_qty,
            product_unit_map=product_unit_map,
        )

    @Slot()
    def runFromComponents(self):
        """Nest from component quantities."""
        quantities = self._component_ctrl.model.getQuantities() if self._component_ctrl else {}
        parts = self.gatherPartsFromComponents(quantities)
        if not parts:
            self.statusMessage.emit("No parts to nest. Set quantities first.", 5000)
            return
        self._start_nesting(parts)

    def set_product_controller(self, ctrl):
        self._product_ctrl = ctrl

    def set_component_controller(self, ctrl):
        self._component_ctrl = ctrl

    def _on_live_update(self, sheet_snapshots):
        """Receive live sheet state from worker thread."""
        # Resume auto-follow when a new sheet appears
        if len(sheet_snapshots) > len(self._live_sheets):
            if not self._auto_follow:
                self._auto_follow = True
                self._user_navigated = False
                self.autoFollowChanged.emit()

        was_empty = not self._live_sheets
        old_sheets = self._live_sheets
        self._live_sheets = sheet_snapshots

        # Emit resultChanged on first live update so hasResult becomes True
        if was_empty and sheet_snapshots:
            self.resultChanged.emit()

        # Auto-follow: find which sheet changed and navigate there
        if self._auto_follow and sheet_snapshots:
            changed_idx = len(sheet_snapshots) - 1  # default to last
            # Compare part counts to find which sheet gained a part
            for i, snap in enumerate(sheet_snapshots):
                old_count = len(old_sheets[i].parts) if i < len(old_sheets) else 0
                if len(snap.parts) != old_count:
                    changed_idx = i
                    break
            self._current_sheet = changed_idx
        elif self._current_sheet >= len(sheet_snapshots):
            # User's sheet was removed (e.g. re-pack) — clamp to last
            self._current_sheet = max(0, len(sheet_snapshots) - 1)

        self.sheetChanged.emit()

    def _start_nesting(self, parts, product_comp_qty=None, product_unit_map=None):
        if self._is_running:
            self.statusMessage.emit("Cannot nest while another operation is in progress.", 5000)
            return
        config = self._create_nesting_config()

        # Use constrained nesting when connected to the API server
        db = self._app.db if self._app.usingApi else None
        self.statusMessage.emit(f"Nesting {len(parts)} parts...", 0)

        # Initialize live preview state
        self._live_mode = True
        self._live_sheets = []
        self._auto_follow = True
        self._user_navigated = False
        self._result = None
        self._current_sheet = 0

        self._is_running = True
        self.isRunningChanged.emit()
        self.resultChanged.emit()
        self._progress_total = len(parts)
        self._progress_current = 0
        self.progressTotalChanged.emit()
        self.progressCurrentChanged.emit()

        self._worker = NestingWorker(
            parts, config, db=db,
            dxf_loader=self._get_dxf_loader_for_sync(),
            product_comp_qty=product_comp_qty,
            product_unit_map=product_unit_map,
        )
        self._worker.finished.connect(self._on_finished)
        self._worker.progress.connect(self._on_progress)
        self._worker.status.connect(self._on_status)
        self._worker.error.connect(self._on_error)
        self._worker.cancelled.connect(self._on_cancelled)
        self._worker.live_update.connect(self._on_live_update)
        self._worker.start()

    @Slot()
    def stopNesting(self):
        if self._is_running and self._worker:
            self._worker.request_stop()
            self.statusMessage.emit("Stopping nesting...", 0)

    def _on_progress(self, current, total):
        self._progress_current = current
        self.progressCurrentChanged.emit()
        percent = int((current / total) * 100) if total > 0 else 0
        self.statusMessage.emit(f"Nesting... {percent}% ({current}/{total} parts)", 0)

    def _on_status(self, message):
        self.statusMessage.emit(message, 0)

    def _compute_bundle_map(self, result):
        """Compute bundle_map from sheet_metadata bundle_group values."""
        if not result.sheet_metadata:
            return {}
        groups = {}
        for i, meta in enumerate(result.sheet_metadata):
            if meta.bundle_group is not None:
                groups.setdefault(meta.bundle_group, []).append(
                    result.sheets[i].sheet_number)
        return {k: v for k, v in groups.items() if len(v) >= 2}

    def _on_finished(self, result):
        self._live_mode = False
        self._live_sheets = []
        self._result = result
        self._current_sheet = 0
        self._auto_follow = True
        self._is_running = False
        self._worker = None
        self._bundle_map = self._compute_bundle_map(result)
        self.isRunningChanged.emit()
        self.resultChanged.emit()
        self.sheetChanged.emit()
        self.statusMessage.emit(
            f"Nesting complete: {result.parts_placed} parts on {result.sheets_used} sheets",
            5000,
        )

    def _on_error(self, error_msg):
        self._live_mode = False
        self._is_running = False
        self._worker = None
        self.isRunningChanged.emit()
        self.statusMessage.emit(f"Nesting failed: {error_msg}", 5000)

    def _on_cancelled(self):
        self._live_mode = False
        self._live_sheets = []
        self._result = None
        self._current_sheet = 0
        self._is_running = False
        self._worker = None
        self.isRunningChanged.emit()
        self.resultChanged.emit()
        self.sheetChanged.emit()
        self.statusMessage.emit("Nesting cancelled", 5000)

    # --- Export ---

    @Slot(bool, result=str)
    def exportResult(self, prototype):
        """Export nesting result. Returns status message."""
        if not self._result or not self._result.sheets:
            return "No result to export"

        track = not prototype
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)

            # Variable pocket sources
            variable_pocket_sources = set()
            for comp in self._app.db.get_all_component_definitions():
                if comp.variable_pockets:
                    variable_pocket_sources.add(comp.dxf_filename)
            self._app.output_gen.set_variable_pocket_sources(variable_pocket_sources)

            self._app.output_gen.output_directory = tmp_path
            dxf_results = self._app.output_gen.generate_all_sheets(
                self._result.sheets,
                filename_prefix=f"{timestamp}_nested_sheet",
            )
            dxf_paths = [r[0] for r in dxf_results]
            sheet_centroids = [r[1] for r in dxf_results]

            uploaded_dxf = 0
            job_created = False

            if self._app.usingApi:
                for dxf_path in dxf_paths:
                    try:
                        self._app.db.upload_nesting_dxf(Path(dxf_path))
                        uploaded_dxf += 1
                    except Exception:
                        logger.exception("Failed to upload nesting DXF %s", dxf_path)

                job_created = self._create_nesting_job(dxf_paths, sheet_centroids, prototype=not track)

        message = f"Uploaded {uploaded_dxf} nesting DXF files to server."
        if job_created and not track:
            message += "\nPrototype job created (no inventory tracking)."
        elif job_created:
            message += "\nNesting job created for inventory tracking."
        elif self._app.usingApi:
            message += "\nWarning: Failed to create nesting job."

        self.statusMessage.emit(f"Exported {uploaded_dxf} files to server", 5000)
        return message

    @Slot("QVariantMap", bool, result=str)
    def exportManualNest(self, nest_dict, prototype):
        """Queue a saved manual nest as a nesting job — mirrors exportResult
        but operates on nest_dict returned by `/manual-nests/{id}` instead
        of the current auto-nest result.

        Uses the pipeline's `_build_override_sheet` to rehydrate NestedSheet
        objects (which the output generator can turn into DXFs), then
        constructs the nesting-job payload directly from the stored
        component_ids — no part_id string matching required.
        """
        if not nest_dict or not nest_dict.get("sheets"):
            return "That manual nest has no sheets."
        dxf_loader = getattr(self._app, "dxf_loader", None)
        if not dxf_loader:
            return "Can't queue — DXF loader isn't available."

        # Rebuild NestedSheet objects for DXF generation.
        try:
            from src.nesting.pipeline import _build_override_sheet
        except Exception:
            logger.exception("Couldn't import _build_override_sheet")
            return "Couldn't prepare the manual-nest export."

        try:
            comp_defs = self._app.db.get_all_component_definitions() or []
        except Exception:
            logger.exception("Failed to load component definitions")
            return "Couldn't load component definitions from the server."
        comp_filename = {int(c.id): c.dxf_filename for c in comp_defs}

        nested_sheets = []
        for stored in nest_dict.get("sheets") or []:
            ns, _ = _build_override_sheet(stored, dxf_loader, comp_filename)
            if ns is not None:
                nested_sheets.append(ns)
        if not nested_sheets:
            return "Couldn't load any parts — check that the DXF files are available."

        # Variable-pocket sources for the output generator (same as
        # exportResult's setup).
        variable_pocket_sources = set()
        for comp in comp_defs:
            if getattr(comp, "variable_pockets", False):
                variable_pocket_sources.add(comp.dxf_filename)
        self._app.output_gen.set_variable_pocket_sources(variable_pocket_sources)

        nest_name = nest_dict.get("name", "manual")
        safe_name = "".join(c if c.isalnum() or c in "-_" else "_" for c in nest_name)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

        uploaded_dxf = 0
        job_created = False

        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            self._app.output_gen.output_directory = tmp_path
            dxf_results = self._app.output_gen.generate_all_sheets(
                nested_sheets,
                filename_prefix=f"{timestamp}_manual_{safe_name}_sheet",
            )
            dxf_paths = [r[0] for r in dxf_results]
            sheet_centroids = [r[1] for r in dxf_results]

            if self._app.usingApi:
                for dxf_path in dxf_paths:
                    try:
                        self._app.db.upload_nesting_dxf(Path(dxf_path))
                        uploaded_dxf += 1
                    except Exception:
                        logger.exception(
                            "Failed to upload manual-nest DXF %s", dxf_path,
                        )

                # Build sheets_data from the stored nest structure directly —
                # we already have real component_ids, no need for part_id
                # string parsing.
                sheets_data = []
                for i, stored_sheet in enumerate(nest_dict.get("sheets") or []):
                    if i >= len(nested_sheets):
                        break
                    centroids = sheet_centroids[i] if sheet_centroids and i < len(sheet_centroids) else None
                    component_counts: dict = {}
                    placements_list = []
                    for j, raw in enumerate(stored_sheet.get("parts") or []):
                        cid = int(raw.get("component_id"))
                        sku = raw.get("product_sku")
                        if centroids and j < len(centroids):
                            cx, cy = centroids[j]
                        else:
                            cx = float(raw.get("x") or 0.0)
                            cy = float(raw.get("y") or 0.0)
                        component_counts[(cid, sku)] = component_counts.get((cid, sku), 0) + 1
                        placements_list.append({
                            "component_id": cid,
                            "product_sku": sku,
                            "instance_index": j,
                            "x": round(cx, 4),
                            "y": round(cy, 4),
                            "rotation": round(float(raw.get("rotation_deg") or 0.0), 2),
                            "source_dxf": comp_filename.get(cid) or "",
                        })
                    parts_list = [
                        {"component_id": c, "product_sku": s, "quantity": q}
                        for (c, s), q in component_counts.items()
                    ]
                    sheet_data = {
                        "sheet_number": i + 1,
                        "parts": parts_list,
                        "placements": placements_list,
                    }
                    if dxf_paths and i < len(dxf_paths) and dxf_paths[i]:
                        sheet_data["dxf_filename"] = Path(dxf_paths[i]).name
                    sheets_data.append(sheet_data)

                if sheets_data:
                    job_name = f"Manual: {nest_name} {datetime.now():%Y-%m-%d %H:%M:%S}"
                    if prototype:
                        job_name = f"[PROTO] {job_name}"
                    try:
                        self._app.db.create_nesting_job(
                            job_name, sheets_data, prototype=prototype,
                        )
                        job_created = True
                    except Exception:
                        logger.exception("Failed to create manual-nest job")

        msg = f"Uploaded {uploaded_dxf} sheet DXF(s) to server."
        if job_created and prototype:
            msg += "\nPrototype job queued (no inventory tracking)."
        elif job_created:
            msg += "\nNesting job queued for inventory tracking."
        elif self._app.usingApi:
            msg += "\nWarning: Could not create the job on the server."

        self.statusMessage.emit(f"Queued manual nest: {nest_name}", 5000)
        return msg

    def _create_nesting_job(self, dxf_paths=None, sheet_centroids=None, prototype=False):
        if not self._result or not self._result.sheets:
            return False
        try:
            # Lazy-build component name->ID mapping (only needed at export time)
            if not self._component_name_to_id:
                for comp in self._app.db.get_all_component_definitions():
                    self._component_name_to_id[comp.name] = comp.id
            sheets_data = []
            for i, sheet in enumerate(self._result.sheets):
                centroids = sheet_centroids[i] if sheet_centroids and i < len(sheet_centroids) else None
                component_counts = {}  # (component_id, product_sku) -> count
                placements_list = []
                placement_counter = 0
                for j, part in enumerate(sheet.parts):
                    part_id = part.part_id
                    component_id = None
                    matched_comp_name = None
                    # part_id format: "{sku}_{component_name}_{NNN}" or "{component_name}_{NNN}"
                    # Strip the trailing instance number to get the prefix
                    prefix = part_id.rsplit("_", 1)[0] if "_" in part_id else part_id
                    for comp_name, comp_id in self._component_name_to_id.items():
                        # prefix must either equal the component name (component mode)
                        # or end with "_{component_name}" (product mode)
                        if prefix == comp_name or prefix.endswith(f"_{comp_name}"):
                            component_id = comp_id
                            matched_comp_name = comp_name
                            break
                    if component_id:
                        # Extract product_sku from part_id
                        product_sku = None
                        if matched_comp_name:
                            idx = prefix.find(matched_comp_name)
                            if idx > 0:
                                sku_prefix = prefix[:idx].rstrip('_')
                                if sku_prefix and sku_prefix not in ('repl', 'fill'):
                                    product_sku = sku_prefix

                        if centroids and j < len(centroids):
                            cx, cy = centroids[j]
                        else:
                            cx, cy = part.x, part.y
                        key = (component_id, product_sku)
                        component_counts[key] = component_counts.get(key, 0) + 1
                        placements_list.append({
                            "component_id": component_id,
                            "product_sku": product_sku,
                            "instance_index": placement_counter,
                            "x": round(cx, 4),
                            "y": round(cy, 4),
                            "rotation": round(getattr(part, 'rotation', 0), 2),
                            "source_dxf": getattr(part, 'source_filename', None),
                        })
                        placement_counter += 1

                parts_list = [
                    {"component_id": comp_id, "quantity": qty, "product_sku": sku}
                    for (comp_id, sku), qty in component_counts.items()
                ]
                sheet_data = {
                    "sheet_number": i + 1,
                    "parts": parts_list,
                    "placements": placements_list,
                }
                if dxf_paths and i < len(dxf_paths) and dxf_paths[i]:
                    sheet_data["dxf_filename"] = Path(dxf_paths[i]).name

                # Include mating metadata if available
                if self._result and self._result.sheet_metadata and i < len(self._result.sheet_metadata):
                    meta = self._result.sheet_metadata[i]
                    sheet_data["has_variable_pockets"] = meta.has_variable_pockets

                sheets_data.append(sheet_data)

            job_name = f"Nest {datetime.now():%Y-%m-%d %H:%M:%S}"
            if prototype:
                job_name = f"[PROTO] {job_name}"
            job_response = self._app.db.create_nesting_job(job_name, sheets_data, prototype=prototype)
            self._create_bundles(job_response)
            return True
        except Exception:
            logger.exception("Failed to create nesting job")
            return False

    def _create_bundles(self, job_response):
        """Create bundles from sheet metadata bundle groups."""
        if not job_response or not self._result or not self._result.sheet_metadata:
            return

        # Map sheet_number -> server sheet_id from the job response
        server_sheets = {}
        for s in job_response.get("sheets", []):
            server_sheets[s["sheet_number"]] = s["id"]

        # Group by bundle_group
        groups: dict[int, list[int]] = {}
        for i, meta in enumerate(self._result.sheet_metadata):
            if meta.bundle_group is not None:
                sheet_num = self._result.sheets[i].sheet_number
                server_id = server_sheets.get(sheet_num)
                if server_id:
                    groups.setdefault(meta.bundle_group, []).append(server_id)

        # Create bundles for multi-sheet groups
        for bundle_group, sheet_ids in groups.items():
            if len(sheet_ids) >= 2:
                try:
                    self._app.db.create_bundle(sheet_ids)
                except Exception:
                    logger.exception("Failed to create bundle for group %s", bundle_group)

    def nestProducts(self, quantities):
        """
        Public entry point: gather parts from product SKU quantities and nest.
        Used by ReplenishmentController and any caller that has a {sku: qty} dict.
        """
        parts, product_comp_qty, product_unit_map = self.gatherPartsFromProducts(quantities)
        if not parts:
            return False
        self._start_nesting(
            parts, product_comp_qty=product_comp_qty,
            product_unit_map=product_unit_map,
        )
        return True

    def gatherPartsFromProducts(self, quantities):
        """
        Gather part tuples from product SKU -> quantity dict.
        Returns (parts, product_comp_qty, product_unit_map) where parts is
        list of (part_id, geometry), product_comp_qty is {(sku, component_name):
        quantity}, and product_unit_map is {part_id: product_unit} for enrichment.
        """
        items = [OrderItem(sku=sku, quantity=qty) for sku, qty in quantities.items()]
        if not items:
            return [], {}, {}
        part_instances = self._app.processor.process_order(items)
        parts = [(p.part_id, p.geometry) for p in part_instances if p.geometry]
        # process_order already fetched each product — reuse its captured data
        product_comp_qty = getattr(self._app.processor, 'last_product_comp_qty', {})
        product_unit_map = {
            p.part_id: p.product_unit
            for p in part_instances
            if p.product_unit is not None
        }
        return parts, product_comp_qty, product_unit_map

    def gatherPartsFromComponents(self, quantities):
        """
        Gather part tuples from component_id -> quantity dict.
        Returns list of (part_id, geometry) tuples.
        """
        db = self._app.db
        dxf_loader = self._app.dxf_loader
        components = db.get_all_component_definitions()
        comp_map = {c.id: c for c in components}
        parts = []
        counter = 0
        for comp_id, qty in quantities.items():
            comp = comp_map.get(comp_id)
            if not comp:
                continue
            geom = dxf_loader.load_part(comp.dxf_filename)
            if not geom:
                continue
            for i in range(qty):
                counter += 1
                part_id = f"{comp.name}_{counter:03d}"
                parts.append((part_id, geom))
        return parts

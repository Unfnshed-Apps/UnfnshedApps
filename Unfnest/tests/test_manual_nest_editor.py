"""Tests for the Manual Nest editor controller.

Focuses on the state machine (library population, placement validity,
save payload shape) — does not launch a Qt application. The controller is
exercised directly through its Python slots/properties.
"""
from __future__ import annotations

import pytest

from bridge.manual_nest_editor_controller import (
    ManualNestEditorController, _aabb_overlaps, _placement_bbox,
)


# ==================================================================
# Test scaffolding
# ==================================================================

class _FakeComponent:
    def __init__(self, component_id, component_name, dxf_filename, quantity):
        self.component_id = component_id
        self.component_name = component_name
        self.dxf_filename = dxf_filename
        self.quantity = quantity


class _FakeProduct:
    def __init__(self, sku, components):
        self.sku = sku
        self.components = components


class _FakeBoundingBox:
    def __init__(self, min_x, min_y, max_x, max_y):
        self.min_x = min_x
        self.min_y = min_y
        self.max_x = max_x
        self.max_y = max_y


class _FakeGeom:
    def __init__(self, bbox):
        self.bounding_box = bbox


class _FakeDxfLoader:
    """Returns fixed geometry for any DXF filename lookup."""

    def __init__(self, w=6.0, h=10.0):
        self._w = w
        self._h = h

    def load_geometry(self, dxf_filename):
        return _FakeGeom(_FakeBoundingBox(0.0, 0.0, self._w, self._h))


class _FakeDb:
    def __init__(self, products=None):
        self._products = {p.sku: p for p in (products or [])}
        self.created_nests: list[dict] = []

    def get_product(self, sku):
        return self._products.get(sku)

    def create_manual_nest(self, name, override_enabled=False, sheets=None):
        entry = {"name": name, "override_enabled": override_enabled, "sheets": sheets or []}
        self.created_nests.append(entry)
        return {"id": 1, **entry}


class _FakeAppController:
    def __init__(self, db, dxf_loader):
        self.db = db
        self.dxf_loader = dxf_loader


@pytest.fixture
def app_ctrl():
    bench_components = [
        _FakeComponent(1, "Bench leg", "bench_leg.dxf", quantity=2),
        _FakeComponent(2, "Bench top", "bench_top.dxf", quantity=1),
    ]
    shelf_components = [
        _FakeComponent(3, "Shelf side", "shelf_side.dxf", quantity=2),
    ]
    db = _FakeDb(products=[
        _FakeProduct("BENCH-01", bench_components),
        _FakeProduct("SHELF-02", shelf_components),
    ])
    return _FakeAppController(db, _FakeDxfLoader(w=4.0, h=8.0))


@pytest.fixture
def editor(qtbot_app, app_ctrl):
    """Editor controller wrapped in a fixture that ensures a QCoreApplication
    exists (PySide6 properties need one)."""
    ctrl = ManualNestEditorController(app_ctrl)
    ctrl.showCreate()
    return ctrl


@pytest.fixture(scope="session")
def qtbot_app():
    """Create a QCoreApplication once per session so Qt properties/signals
    on the controller can live without needing a full QGuiApplication."""
    from PySide6.QtCore import QCoreApplication
    app = QCoreApplication.instance()
    if app is None:
        app = QCoreApplication([])
    return app


# ==================================================================
# Pure helpers
# ==================================================================

class TestAabbOverlaps:
    def test_non_overlapping_rects(self):
        # Two rects far apart
        assert not _aabb_overlaps(0, 0, 5, 5, 10, 10, 5, 5, buffer=0)

    def test_touching_edges_no_buffer_do_not_overlap(self):
        # Strict AABB test treats edge-touching as non-overlapping
        assert not _aabb_overlaps(0, 0, 5, 5, 5, 0, 5, 5, buffer=0)

    def test_overlapping_rects(self):
        assert _aabb_overlaps(0, 0, 5, 5, 3, 3, 5, 5, buffer=0)

    def test_buffer_pushes_rects_apart(self):
        # Touching edges with a 1" buffer should register as overlap
        assert _aabb_overlaps(0, 0, 5, 5, 5, 0, 5, 5, buffer=1.0)


class TestPlacementBbox:
    def test_zero_rotation_is_identity(self):
        w, h = _placement_bbox(6.0, 10.0, 0.0)
        assert w == pytest.approx(6.0)
        assert h == pytest.approx(10.0)

    def test_ninety_swaps_dimensions(self):
        w, h = _placement_bbox(6.0, 10.0, 90.0)
        assert w == pytest.approx(10.0)
        assert h == pytest.approx(6.0)

    def test_one_eighty_preserves_dimensions(self):
        w, h = _placement_bbox(6.0, 10.0, 180.0)
        assert w == pytest.approx(6.0)
        assert h == pytest.approx(10.0)


# ==================================================================
# Editor state machine
# ==================================================================

class TestShowCreateAndReset:
    def test_fresh_create_starts_empty(self, editor):
        assert editor.visible is True
        assert editor.name == ""
        assert editor.placements == []
        assert editor.library == []
        assert not editor.ghostActive

    def test_show_create_twice_clears_state(self, editor):
        editor.setName("first")
        editor.showCreate()
        assert editor.name == ""


class TestAddProducts:
    def test_single_product_populates_library(self, editor):
        ok = editor.addProducts([{"sku": "BENCH-01", "qty": 1}])
        assert ok is True
        lib = editor.library
        # One bench = 2 legs + 1 top → 2 library entries (aggregated by component)
        assert len(lib) == 2
        by_name = {e["component_name"]: e for e in lib}
        assert by_name["Bench leg"]["needed"] == 2
        assert by_name["Bench top"]["needed"] == 1
        # bbox filled from the fake dxf loader
        assert by_name["Bench leg"]["bbox_w"] == pytest.approx(4.0)
        assert by_name["Bench leg"]["bbox_h"] == pytest.approx(8.0)

    def test_multiple_qty_multiplies_needed(self, editor):
        editor.addProducts([{"sku": "BENCH-01", "qty": 3}])
        by_name = {e["component_name"]: e for e in editor.library}
        assert by_name["Bench leg"]["needed"] == 6   # 2 per bench × 3
        assert by_name["Bench top"]["needed"] == 3

    def test_second_add_accumulates_into_existing_entries(self, editor):
        editor.addProducts([{"sku": "BENCH-01", "qty": 1}])
        editor.addProducts([{"sku": "BENCH-01", "qty": 2}])
        by_name = {e["component_name"]: e for e in editor.library}
        assert by_name["Bench leg"]["needed"] == 6
        assert len(editor.library) == 2  # no duplicate rows

    def test_multiple_products_keep_separate_entries(self, editor):
        editor.addProducts([
            {"sku": "BENCH-01", "qty": 1},
            {"sku": "SHELF-02", "qty": 1},
        ])
        skus = {e["product_sku"] for e in editor.library}
        assert skus == {"BENCH-01", "SHELF-02"}

    def test_unknown_sku_is_ignored(self, editor):
        editor.addProducts([{"sku": "NOPE-99", "qty": 5}])
        assert editor.library == []

    def test_empty_list_is_noop(self, editor):
        editor.addProducts([])
        assert editor.library == []


class TestPlacementMode:
    def test_start_placement_activates_ghost(self, editor):
        editor.addProducts([{"sku": "BENCH-01", "qty": 1}])
        editor.startPlacement(1, "BENCH-01")
        assert editor.ghostActive
        assert editor.ghostComponentId == 1

    def test_start_placement_for_fully_placed_component_fails(self, editor):
        editor.addProducts([{"sku": "BENCH-01", "qty": 1}])
        # Place both legs by moving and committing repeatedly
        editor.startPlacement(1, "BENCH-01")
        editor.updateGhostPosition(2, 2)
        assert editor.commitPlacement()
        editor.startPlacement(1, "BENCH-01")
        editor.updateGhostPosition(20, 20)
        assert editor.commitPlacement()
        # Now attempt to start placement for legs again — should refuse
        msgs = []
        editor.operationFailed.connect(msgs.append)
        editor.startPlacement(1, "BENCH-01")
        assert msgs and "already placed" in msgs[0]

    def test_rotate_swaps_ghost_bbox(self, editor):
        editor.addProducts([{"sku": "BENCH-01", "qty": 1}])
        editor.startPlacement(1, "BENCH-01")
        w0 = editor.ghostBboxW
        h0 = editor.ghostBboxH
        editor.rotateGhost()
        assert editor.ghostBboxW == pytest.approx(h0)
        assert editor.ghostBboxH == pytest.approx(w0)
        assert editor.ghostRotation == pytest.approx(90.0)

    def test_cancel_placement_clears_ghost(self, editor):
        editor.addProducts([{"sku": "BENCH-01", "qty": 1}])
        editor.startPlacement(1, "BENCH-01")
        editor.cancelPlacement()
        assert not editor.ghostActive


class TestCommitPlacement:
    def test_valid_commit_adds_placement_and_decrements_remaining(self, editor):
        editor.addProducts([{"sku": "BENCH-01", "qty": 1}])
        editor.startPlacement(1, "BENCH-01")
        editor.updateGhostPosition(2, 2)
        ok = editor.commitPlacement()
        assert ok
        assert len(editor.placements) == 1
        p = editor.placements[0]
        assert p["component_id"] == 1
        assert p["x"] == pytest.approx(2)
        # Library "placed" counter advances
        leg = [e for e in editor.library if e["component_id"] == 1][0]
        assert leg["placed"] == 1

    def test_commit_fails_when_overlap(self, editor):
        editor.addProducts([{"sku": "BENCH-01", "qty": 1}])
        # Place leg #1
        editor.startPlacement(1, "BENCH-01")
        editor.updateGhostPosition(2, 2)
        editor.commitPlacement()
        # Try to overlap it with leg #2
        editor.startPlacement(1, "BENCH-01")
        editor.updateGhostPosition(2.5, 2.5)  # clearly overlapping leg #1
        msgs = []
        editor.operationFailed.connect(msgs.append)
        ok = editor.commitPlacement()
        assert not ok
        assert msgs and "overlaps" in msgs[0]

    def test_commit_fails_off_sheet(self, editor):
        editor.addProducts([{"sku": "BENCH-01", "qty": 1}])
        editor.startPlacement(1, "BENCH-01")
        editor.updateGhostPosition(-5, -5)  # negative == off-sheet
        ok = editor.commitPlacement()
        assert not ok

    def test_commit_exits_placement_when_entry_fully_placed(self, editor):
        editor.addProducts([{"sku": "BENCH-01", "qty": 1}])  # needs 2 legs
        editor.startPlacement(1, "BENCH-01")
        editor.updateGhostPosition(2, 2)
        editor.commitPlacement()
        # Still have 1 remaining — ghost stays active
        assert editor.ghostActive
        editor.updateGhostPosition(20, 20)
        editor.commitPlacement()
        # Now all placed — ghost deactivates
        assert not editor.ghostActive


class TestRemovePlacement:
    def test_remove_restores_library_count(self, editor):
        editor.addProducts([{"sku": "BENCH-01", "qty": 1}])
        editor.startPlacement(1, "BENCH-01")
        editor.updateGhostPosition(2, 2)
        editor.commitPlacement()
        leg = [e for e in editor.library if e["component_id"] == 1][0]
        assert leg["placed"] == 1
        editor.removePlacement(0)
        leg = [e for e in editor.library if e["component_id"] == 1][0]
        assert leg["placed"] == 0
        assert editor.placements == []

    def test_remove_invalid_index_noop(self, editor):
        assert editor.removePlacement(0) is False
        assert editor.removePlacement(-1) is False


class TestSaveEnabledAndSave:
    def test_save_disabled_without_name(self, editor):
        editor.addProducts([{"sku": "BENCH-01", "qty": 1}])
        editor.startPlacement(1, "BENCH-01")
        editor.updateGhostPosition(2, 2)
        editor.commitPlacement()
        assert editor.isSaveEnabled is False

    def test_save_disabled_without_placements(self, editor):
        editor.setName("Empty nest")
        assert editor.isSaveEnabled is False

    def test_save_enabled_with_name_and_placements(self, editor):
        editor.setName("Bench set")
        editor.addProducts([{"sku": "BENCH-01", "qty": 1}])
        editor.startPlacement(1, "BENCH-01")
        editor.updateGhostPosition(2, 2)
        editor.commitPlacement()
        assert editor.isSaveEnabled is True

    def test_save_posts_to_db_with_correct_payload(self, editor, app_ctrl):
        editor.setName("Bench set")
        editor.addProducts([{"sku": "BENCH-01", "qty": 1}])
        editor.startPlacement(1, "BENCH-01")
        editor.updateGhostPosition(2, 2)
        editor.commitPlacement()
        ok = editor.save()
        assert ok
        # DB got one POST
        assert len(app_ctrl.db.created_nests) == 1
        payload = app_ctrl.db.created_nests[0]
        assert payload["name"] == "Bench set"
        assert payload["override_enabled"] is False
        # Single-sheet mode: one sheet dict with one part
        assert len(payload["sheets"]) == 1
        sheet = payload["sheets"][0]
        assert sheet["width"] == pytest.approx(48.0)
        assert sheet["height"] == pytest.approx(96.0)
        assert len(sheet["parts"]) == 1
        p = sheet["parts"][0]
        assert p["component_id"] == 1
        assert p["product_sku"] == "BENCH-01"
        # Editor closes after save
        assert not editor.visible

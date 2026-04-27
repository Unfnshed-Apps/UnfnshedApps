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
    """Mirrors ProductComponent — used inside a Product's .components list."""

    def __init__(self, component_id, component_name, dxf_filename, quantity):
        self.component_id = component_id
        self.component_name = component_name
        self.dxf_filename = dxf_filename
        self.quantity = quantity


class _FakeComponentDef:
    """Mirrors ComponentDefinition — returned by get_all_component_definitions()."""

    def __init__(self, id, name, dxf_filename, mating_role="neutral"):
        self.id = id
        self.name = name
        self.dxf_filename = dxf_filename
        self.mating_role = mating_role


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
    def __init__(self, bbox, polygon=None, pocket_polygons=None):
        self.bounding_box = bbox
        # Mirror the real PartGeometry: `polygons` is a list of outline
        # polygons, each a list of (x, y) tuples.
        self.polygons = [polygon] if polygon is not None else []
        self.pocket_polygons = list(pocket_polygons or [])


class _FakeDxfLoader:
    """Returns fixed geometry for any DXF filename lookup."""

    def __init__(self, w=6.0, h=10.0):
        self._w = w
        self._h = h

    def load_part(self, dxf_filename):
        bb = _FakeBoundingBox(0.0, 0.0, self._w, self._h)
        rect = [(0.0, 0.0), (self._w, 0.0), (self._w, self._h), (0.0, self._h)]
        return _FakeGeom(bb, polygon=rect)


class _FakeDb:
    def __init__(self, products=None, nests=None, components=None):
        self._products = {p.sku: p for p in (products or [])}
        self._nests = {n["id"]: n for n in (nests or [])}
        self._components = list(components or [])
        self.created_nests: list[dict] = []
        self.updated_nests: list[tuple[int, dict]] = []

    def get_product(self, sku):
        return self._products.get(sku)

    def get_all_component_definitions(self):
        return list(self._components)

    def create_manual_nest(self, name, override_enabled=False, sheets=None):
        entry = {"name": name, "override_enabled": override_enabled, "sheets": sheets or []}
        self.created_nests.append(entry)
        return {"id": 1, **entry}

    def update_manual_nest(self, nest_id, **fields):
        self.updated_nests.append((nest_id, dict(fields)))
        existing = self._nests.get(nest_id, {"id": nest_id})
        merged = {**existing, **fields}
        self._nests[nest_id] = merged
        return merged

    def get_manual_nest(self, nest_id):
        return self._nests.get(nest_id)


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
    db = _FakeDb(
        products=[
            _FakeProduct("BENCH-01", bench_components),
            _FakeProduct("SHELF-02", shelf_components),
        ],
        components=[
            # Legs have tenons → tabs; top has pockets → receiver.
            _FakeComponentDef(1, "Bench leg", "bench_leg.dxf", mating_role="tab"),
            _FakeComponentDef(2, "Bench top", "bench_top.dxf", mating_role="receiver"),
            _FakeComponentDef(3, "Shelf side", "shelf_side.dxf"),
        ],
    )
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
        # Slide off — we're testing the commit-time validation here, not
        # the drag-to-clear-spot helper.
        editor.setSlideCollision(False)
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

    def test_polygon_collision_allows_AABB_adjacent_non_overlapping_shapes(self, editor, app_ctrl):
        """Two shapes whose AABBs touch but polygons don't — must be allowed.

        Build a component whose polygon is a skinny triangle in the bottom-
        left half of its 4x4 bbox. Place two copies with their AABBs edge-
        touching: an AABB-only test would reject (edges touch + nonzero
        part-spacing). A polygon-accurate test accepts (triangles on
        opposite sides of the shared edge don't touch).
        """
        # Rebuild library with a triangle polygon that occupies < 50% of its bbox
        tri_component = _FakeComponent(50, "Triangle", "tri.dxf", quantity=1)
        tri_product = _FakeProduct("TRI-01", [tri_component])
        app_ctrl.db._products["TRI-01"] = tri_product
        # Replace the loader so geometry for "tri.dxf" returns a triangle
        # filling the lower-left half of a 4x4 bbox.
        class _TriLoader:
            def load_part(self, filename):
                if filename == "tri.dxf":
                    return _FakeGeom(
                        _FakeBoundingBox(0, 0, 4, 4),
                        polygon=[(0, 0), (4, 0), (0, 4)],
                    )
                return _FakeDxfLoader(w=4, h=8).load_part(filename)
        app_ctrl.dxf_loader = _TriLoader()
        editor.showCreate()
        editor.addProducts([{"sku": "TRI-01", "qty": 2}])
        # Place first triangle clear of the edge margin
        editor.startPlacement(50, "TRI-01")
        editor.updateGhostPosition(1, 1)
        assert editor.commitPlacement()
        # Second triangle with 1" of separation: their AABBs still overlap
        # (the default part_spacing=0.75 buffer pushes them into each other
        # when treated as rectangles), but the triangles point away from
        # each other so polygon-accurate collision gives them clearance.
        editor.startPlacement(50, "TRI-01")
        editor.updateGhostPosition(6, 1)
        assert editor.ghostValid

    def test_commit_fails_off_sheet(self, editor):
        # Slide off — this test verifies commit rejects an off-sheet
        # ghost, which sliding would have otherwise pulled back onto the
        # sheet before commit.
        editor.setSlideCollision(False)
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


class TestShowEditAndUpdate:
    @pytest.fixture
    def seeded_db(self, app_ctrl):
        """Seed the fake db with one existing manual nest."""
        app_ctrl.db._nests = {
            42: {
                "id": 42,
                "name": "Bench set — existing",
                "override_enabled": True,
                "sheets": [{
                    "sheet_index": 0,
                    "width": 48,
                    "height": 96,
                    "part_spacing": 0.75,
                    "edge_margin": 0.75,
                    "material": None,
                    "thickness": None,
                    "parts": [
                        {"component_id": 1, "product_sku": "BENCH-01",
                         "product_unit": 0, "instance_index": 0,
                         "x": 2.0, "y": 2.0, "rotation_deg": 0.0},
                        {"component_id": 1, "product_sku": "BENCH-01",
                         "product_unit": 0, "instance_index": 1,
                         "x": 20.0, "y": 2.0, "rotation_deg": 90.0},
                        {"component_id": 2, "product_sku": "BENCH-01",
                         "product_unit": 0, "instance_index": 0,
                         "x": 2.0, "y": 30.0, "rotation_deg": 0.0},
                    ],
                }],
            },
        }
        return app_ctrl.db

    def test_show_edit_populates_state(self, editor, seeded_db):
        editor.showEdit(42)
        assert editor.visible
        assert editor.isEditMode
        assert editor.name == "Bench set — existing"
        assert len(editor.placements) == 3
        assert editor.windowTitle.startswith("Manual Nest Editor — Edit")

    def test_show_edit_rebuilds_library_from_placements(self, editor, seeded_db):
        editor.showEdit(42)
        # 2 legs + 1 top, each fully placed
        by_name = {e["component_name"]: e for e in editor.library}
        assert by_name["Bench leg"]["needed"] == 2
        assert by_name["Bench leg"]["placed"] == 2
        assert by_name["Bench top"]["needed"] == 1
        assert by_name["Bench top"]["placed"] == 1

    def test_show_edit_rotation_keeps_oriented_bbox_on_placement(self, editor, seeded_db):
        editor.showEdit(42)
        # Second leg was saved at rotation 90° — its stored bbox should be
        # swapped (height on x, width on y) while the library entry retains
        # the canonical base bbox.
        rotated = [p for p in editor.placements
                   if p["component_id"] == 1 and p["rotation_deg"] == 90.0]
        assert len(rotated) == 1
        unrotated = [p for p in editor.placements
                     if p["component_id"] == 1 and p["rotation_deg"] == 0.0]
        assert len(unrotated) == 1
        # After 90° rotation, bbox w and h swap
        assert rotated[0]["bbox_w"] == pytest.approx(unrotated[0]["bbox_h"])
        assert rotated[0]["bbox_h"] == pytest.approx(unrotated[0]["bbox_w"])

    def test_show_edit_unknown_id_returns_false(self, editor, seeded_db):
        msgs = []
        editor.operationFailed.connect(msgs.append)
        ok = editor.showEdit(9999)
        assert ok is False
        assert msgs and "no longer exists" in msgs[0]
        # State is not mutated on failure — keep whatever mode the editor
        # was already in (create-mode here, per the fixture).
        assert not editor.isEditMode

    def test_show_edit_overwrites_prior_state(self, editor, seeded_db):
        # Open create mode first and dirty the state
        editor.setName("draft that should get discarded")
        editor.addProducts([{"sku": "SHELF-02", "qty": 1}])
        # Now switch to edit mode — state should be replaced wholesale
        editor.showEdit(42)
        assert editor.name == "Bench set — existing"
        assert all(e["product_sku"] == "BENCH-01" for e in editor.library)

    def test_save_in_edit_mode_issues_put(self, editor, seeded_db):
        editor.showEdit(42)
        editor.setName("Bench set — renamed")
        ok = editor.save()
        assert ok
        # No POST happened; one PUT landed
        assert seeded_db.created_nests == []
        assert len(seeded_db.updated_nests) == 1
        nest_id, fields = seeded_db.updated_nests[0]
        assert nest_id == 42
        assert fields["name"] == "Bench set — renamed"
        assert "sheets" in fields
        assert len(fields["sheets"]) == 1
        # The 3 placements from the seeded nest round-trip correctly
        assert len(fields["sheets"][0]["parts"]) == 3

    def test_remove_placement_in_edit_mode_restores_library_count(self, editor, seeded_db):
        editor.showEdit(42)
        # Legs start at 2/2 placed
        leg_entry = [e for e in editor.library if e["component_id"] == 1][0]
        assert leg_entry["placed"] == 2
        # Remove one leg placement
        leg_index = next(i for i, p in enumerate(editor.placements)
                         if p["component_id"] == 1)
        assert editor.removePlacement(leg_index)
        leg_entry = [e for e in editor.library if e["component_id"] == 1][0]
        assert leg_entry["placed"] == 1
        # Still needs 2, so the library entry shows 1 remaining
        assert leg_entry["needed"] == 2

    def test_show_create_after_edit_resets_edit_mode(self, editor, seeded_db):
        editor.showEdit(42)
        assert editor.isEditMode
        editor.showCreate()
        assert not editor.isEditMode
        assert editor.name == ""
        assert editor.placements == []


class TestPlacementSelection:
    def _place_one(self, editor, x=2, y=2):
        editor.addProducts([{"sku": "BENCH-01", "qty": 1}])
        editor.startPlacement(1, "BENCH-01")
        editor.updateGhostPosition(x, y)
        assert editor.commitPlacement()

    def test_default_no_selection(self, editor):
        assert editor.selectedPlacementIndex == -1

    def test_select_and_clear(self, editor):
        self._place_one(editor)
        editor.selectPlacement(0)
        assert editor.selectedPlacementIndex == 0
        editor.clearSelection()
        assert editor.selectedPlacementIndex == -1

    def test_invalid_index_clears_selection(self, editor):
        self._place_one(editor)
        editor.selectPlacement(99)         # out of range
        assert editor.selectedPlacementIndex == -1

    def test_remove_selected_clears_selection(self, editor):
        self._place_one(editor)
        editor.selectPlacement(0)
        editor.removePlacement(0)
        assert editor.selectedPlacementIndex == -1

    def test_remove_earlier_item_shifts_selection(self, editor):
        # Two placements; select the second; remove the first → selection
        # stays on the "same" part, now at index 0.
        editor.addProducts([{"sku": "BENCH-01", "qty": 1}])
        editor.startPlacement(1, "BENCH-01")
        editor.updateGhostPosition(2, 2)
        editor.commitPlacement()
        editor.startPlacement(1, "BENCH-01")
        editor.updateGhostPosition(10, 10)
        editor.commitPlacement()
        editor.selectPlacement(1)
        editor.removePlacement(0)
        assert editor.selectedPlacementIndex == 0

    def test_switching_sheet_clears_selection(self, editor):
        self._place_one(editor)
        editor.selectPlacement(0)
        editor.addSheet()
        assert editor.selectedPlacementIndex == -1


class TestSlideCollision:
    """Axis-separated sliding lets a user drag a ghost up against edges and
    neighbours instead of hitting a hard stop."""

    def _setup(self, editor):
        editor.addProducts([{"sku": "BENCH-01", "qty": 1}])  # 2 legs + 1 top
        editor.startPlacement(1, "BENCH-01")

    def test_default_is_on(self, editor):
        assert editor.slideCollision is True

    def test_toggle_updates_property(self, editor):
        editor.setSlideCollision(False)
        assert editor.slideCollision is False
        editor.setSlideCollision(True)
        assert editor.slideCollision is True

    def test_free_move_accepts_cursor_directly(self, editor):
        self._setup(editor)
        editor.updateGhostPosition(10, 10)
        assert editor.ghostX == pytest.approx(10)
        assert editor.ghostY == pytest.approx(10)
        assert editor.ghostValid is True

    def test_slide_stops_at_left_edge(self, editor):
        self._setup(editor)
        editor.updateGhostPosition(10, 10)
        # Target a negative X — way past the edge margin
        editor.updateGhostPosition(-50, 10)
        # Ghost should have settled right at the edge margin (0.75)
        assert editor.ghostX == pytest.approx(0.75, abs=0.05)
        # Y unchanged because only X was aimed past the edge
        assert editor.ghostY == pytest.approx(10)
        assert editor.ghostValid is True

    def test_slide_allows_independent_axis_movement(self, editor):
        """If X is blocked but Y is clear, Y still advances."""
        self._setup(editor)
        # Place a leg across the middle of the sheet so a ghost at the
        # same Y has its x-path blocked.
        editor.updateGhostPosition(20, 20)
        editor.commitPlacement()                 # leg #1 committed at (20,20)
        editor.startPlacement(1, "BENCH-01")     # leg #2 ghost
        # Land the ghost on the right side of the committed leg at the
        # same Y, then try to slide far left — the committed leg's AABB
        # blocks the path.
        editor.updateGhostPosition(30, 20)
        editor.updateGhostPosition(0, 20)
        # X should settle right next to the committed leg (with buffer),
        # Y unchanged.
        assert editor.ghostX > 20.0
        assert editor.ghostY == pytest.approx(20)
        assert editor.ghostValid is True

    def test_slide_off_reverts_to_raw_cursor_tracking(self, editor):
        """With sliding disabled, the ghost follows the cursor even into
        invalid positions — it just turns red."""
        self._setup(editor)
        editor.setSlideCollision(False)
        editor.updateGhostPosition(10, 10)
        # Ask for an off-sheet position — without sliding, we should land
        # exactly there and be invalid.
        editor.updateGhostPosition(-50, 10)
        assert editor.ghostX == pytest.approx(-50)
        assert editor.ghostValid is False

    def test_slide_respects_part_spacing_buffer(self, editor):
        """Slide shouldn't let parts touch — part_spacing buffer applies
        even when start and target are both in valid zones with a
        blocked strip in the middle."""
        self._setup(editor)
        editor.updateGhostPosition(20, 20)
        editor.commitPlacement()
        editor.startPlacement(1, "BENCH-01")
        # Start well left, then aim far right past the committed leg.
        editor.updateGhostPosition(2, 20)
        editor.updateGhostPosition(40, 20)
        # The sliding should stop against the buffered neighbour — it
        # shouldn't tunnel through the committed leg and land past it.
        assert editor.ghostValid is True
        assert editor.ghostX < 20.0

    def test_slide_no_ops_when_both_current_and_target_invalid(self, editor):
        """When the ghost spawns on top of another part and the cursor
        asks for another invalid position, sliding stays put (there's no
        sensible valid anchor to slide from)."""
        self._setup(editor)
        # Place a leg near centre then start a fresh ghost that spawns
        # overlapping it.
        editor.updateGhostPosition(22, 44)
        editor.commitPlacement()
        editor.startPlacement(1, "BENCH-01")
        assert editor.ghostValid is False       # ghost overlaps the committed leg
        prev_x, prev_y = editor.ghostX, editor.ghostY
        # Ask for a target that's ALSO blocked (off-sheet). Slide should
        # neither move nor crash.
        editor.updateGhostPosition(-50, -50)
        assert editor.ghostX == pytest.approx(prev_x)
        assert editor.ghostY == pytest.approx(prev_y)


class TestMultiSheet:
    def test_default_has_one_sheet(self, editor):
        assert editor.sheetCount == 1
        assert editor.currentSheetIndex == 0
        assert editor.canGoPrevSheet is False
        assert editor.canGoNextSheet is False
        assert editor.canRemoveSheet is False

    def test_add_sheet_increments_count_and_switches(self, editor):
        editor.addSheet()
        assert editor.sheetCount == 2
        assert editor.currentSheetIndex == 1
        assert editor.placements == []  # fresh sheet is empty
        assert editor.canGoPrevSheet is True
        assert editor.canRemoveSheet is True

    def test_navigation_switches_sheets(self, editor):
        editor.addSheet()
        editor.gotoPrevSheet()
        assert editor.currentSheetIndex == 0
        editor.gotoNextSheet()
        assert editor.currentSheetIndex == 1

    def test_navigation_clamped_at_boundaries(self, editor):
        # Only one sheet — nav buttons are no-ops
        editor.gotoPrevSheet()
        assert editor.currentSheetIndex == 0
        editor.gotoNextSheet()
        assert editor.currentSheetIndex == 0

    def test_placements_are_per_sheet(self, editor):
        editor.addProducts([{"sku": "BENCH-01", "qty": 1}])
        # Place a leg on sheet 0
        editor.startPlacement(1, "BENCH-01")
        editor.updateGhostPosition(2, 2)
        editor.commitPlacement()
        assert len(editor.placements) == 1

        # Add sheet 1 — should be empty
        editor.addSheet()
        assert editor.placements == []

        # Switch back — the leg should still be there
        editor.gotoPrevSheet()
        assert len(editor.placements) == 1

    def test_remove_current_sheet_returns_placed_parts_to_library(self, editor):
        editor.addProducts([{"sku": "BENCH-01", "qty": 1}])
        # Place a leg on sheet 0
        editor.startPlacement(1, "BENCH-01")
        editor.updateGhostPosition(2, 2)
        editor.commitPlacement()
        # Add and switch to sheet 1, then place the other leg there
        editor.addSheet()
        editor.startPlacement(1, "BENCH-01")
        editor.updateGhostPosition(2, 2)
        editor.commitPlacement()
        # Before removal: both legs placed (2/2)
        leg = [e for e in editor.library if e["component_id"] == 1][0]
        assert leg["placed"] == 2
        # Remove the current (sheet 1) — library returns to 1/2 placed
        assert editor.removeCurrentSheet()
        leg = [e for e in editor.library if e["component_id"] == 1][0]
        assert leg["placed"] == 1
        assert editor.sheetCount == 1

    def test_cannot_remove_last_sheet(self, editor):
        msgs = []
        editor.operationFailed.connect(msgs.append)
        assert editor.removeCurrentSheet() is False
        assert msgs and "at least one sheet" in msgs[0]
        assert editor.sheetCount == 1

    def test_save_serializes_all_sheets(self, editor, app_ctrl):
        editor.setName("Two-sheet nest")
        editor.addProducts([{"sku": "BENCH-01", "qty": 1}])
        # Place legs on two different sheets
        editor.startPlacement(1, "BENCH-01")
        editor.updateGhostPosition(2, 2)
        editor.commitPlacement()
        editor.addSheet()
        editor.startPlacement(1, "BENCH-01")
        editor.updateGhostPosition(2, 2)
        editor.commitPlacement()
        assert editor.save()
        payload = app_ctrl.db.created_nests[0]
        assert len(payload["sheets"]) == 2
        assert payload["sheets"][0]["sheet_index"] == 0
        assert payload["sheets"][1]["sheet_index"] == 1
        # Each sheet has exactly one part
        assert len(payload["sheets"][0]["parts"]) == 1
        assert len(payload["sheets"][1]["parts"]) == 1

    def test_save_enabled_when_any_sheet_has_placements(self, editor):
        editor.setName("Nest")
        # Sheet 0: one placement
        editor.addProducts([{"sku": "BENCH-01", "qty": 1}])
        editor.startPlacement(1, "BENCH-01")
        editor.updateGhostPosition(2, 2)
        editor.commitPlacement()
        # Switch to an empty sheet 1
        editor.addSheet()
        assert editor.placements == []
        # Save is still enabled because sheet 0 has a placement
        assert editor.isSaveEnabled is True

    def test_sheet_dimensions_persist_per_sheet(self, editor):
        # Make sheet 0 bigger than default
        editor.setSheetDimensions(72, 48, 0.5, 0.5)
        assert editor.sheetWidth == pytest.approx(72.0)
        editor.addSheet()  # new sheet inherits defaults
        assert editor.sheetWidth == pytest.approx(48.0)
        editor.gotoPrevSheet()
        assert editor.sheetWidth == pytest.approx(72.0)

class TestMatingWarnings:
    def _place_leg(self, editor, x=2, y=2):
        editor.startPlacement(1, "BENCH-01")
        editor.updateGhostPosition(x, y)
        assert editor.commitPlacement()

    def _place_top(self, editor, x=5, y=5):
        editor.startPlacement(2, "BENCH-01")
        editor.updateGhostPosition(x, y)
        assert editor.commitPlacement()

    def test_no_warnings_on_empty_nest(self, editor):
        assert editor.matingWarnings == []

    def test_no_warnings_when_all_on_one_sheet(self, editor):
        editor.addProducts([{"sku": "BENCH-01", "qty": 1}])
        self._place_leg(editor, 2, 2)
        self._place_leg(editor, 2, 20)
        self._place_top(editor, 20, 2)
        assert editor.matingWarnings == []

    def test_no_warnings_when_receiver_on_next_sheet(self, editor):
        editor.addProducts([{"sku": "BENCH-01", "qty": 1}])
        # Both legs (tabs) on sheet 0
        self._place_leg(editor, 2, 2)
        self._place_leg(editor, 2, 20)
        # Top (receiver) on sheet 1 (tab_sheet + 1)
        editor.addSheet()
        self._place_top(editor, 2, 2)
        assert editor.matingWarnings == []

    def test_warns_when_tabs_split_across_sheets(self, editor):
        editor.addProducts([{"sku": "BENCH-01", "qty": 1}])
        # One leg on sheet 0, the second on sheet 1 — tabs split
        self._place_leg(editor, 2, 2)
        editor.addSheet()
        self._place_leg(editor, 2, 2)
        warnings = editor.matingWarnings
        assert len(warnings) == 1
        assert "BENCH-01" in warnings[0]
        assert "split" in warnings[0]

    def test_warns_when_receiver_drifts_too_far(self, editor):
        editor.addProducts([{"sku": "BENCH-01", "qty": 1}])
        # Tabs on sheet 0
        self._place_leg(editor, 2, 2)
        self._place_leg(editor, 2, 20)
        # Jump over sheet 1 — top lands on sheet 2
        editor.addSheet()  # sheet 1 — empty
        editor.addSheet()  # sheet 2
        self._place_top(editor, 2, 2)
        warnings = editor.matingWarnings
        assert len(warnings) == 1
        assert "BENCH-01" in warnings[0]
        assert "too far" in warnings[0]

    def test_warnings_recompute_after_remove(self, editor):
        editor.addProducts([{"sku": "BENCH-01", "qty": 1}])
        self._place_leg(editor, 2, 2)
        editor.addSheet()
        self._place_leg(editor, 2, 2)
        assert editor.matingWarnings  # split tabs → warning
        # Remove the leg on sheet 1 (currently active)
        editor.removePlacement(0)
        # Drop the now-empty sheet 1
        editor.removeCurrentSheet()
        assert editor.matingWarnings == []

    def test_loose_neutrals_dont_trigger_warnings(self, editor):
        # Shelf side has no mating role (neutral); any layout is OK.
        editor.addProducts([{"sku": "SHELF-02", "qty": 1}])
        editor.startPlacement(3, "SHELF-02")
        editor.updateGhostPosition(2, 2)
        editor.commitPlacement()
        editor.addSheet()
        editor.startPlacement(3, "SHELF-02")
        editor.updateGhostPosition(2, 2)
        editor.commitPlacement()
        assert editor.matingWarnings == []


class TestShowEditMultiSheet:
    def test_show_edit_loads_multiple_sheets(self, editor, app_ctrl):
        # Seed the DB with a 2-sheet nest
        app_ctrl.db._nests[99] = {
            "id": 99,
            "name": "Two-sheet",
            "override_enabled": False,
            "sheets": [
                {"sheet_index": 0, "width": 48, "height": 96,
                 "part_spacing": 0.75, "edge_margin": 0.75,
                 "parts": [{"component_id": 1, "product_sku": "BENCH-01",
                            "product_unit": 0, "x": 2, "y": 2,
                            "rotation_deg": 0}]},
                {"sheet_index": 1, "width": 48, "height": 96,
                 "part_spacing": 0.75, "edge_margin": 0.75,
                 "parts": [{"component_id": 2, "product_sku": "BENCH-01",
                            "product_unit": 0, "x": 2, "y": 2,
                            "rotation_deg": 0}]},
            ],
        }
        assert editor.showEdit(99)
        assert editor.sheetCount == 2
        assert editor.currentSheetIndex == 0
        assert len(editor.placements) == 1
        editor.gotoNextSheet()
        assert len(editor.placements) == 1


class TestSheetUtilization:
    """Utilization % reflects placed polygon areas over sheet area."""

    def test_empty_sheet_utilization_is_zero(self, editor):
        assert editor.sheetUtilization == "0.0%"

    def test_utilization_after_placement(self, editor, app_ctrl, monkeypatch):
        """Placing a 4x8 part on a 48x96 sheet should give 4*8 / 48*96 = 0.7%."""
        editor.setSheetDimensions(48.0, 96.0, 0.0, 0.0)
        # Simulate a placed 4x8 part with explicit polygon so area is known
        editor._placements.append({
            "component_id": 1, "component_name": "x", "dxf_filename": "x.dxf",
            "product_sku": "P", "product_unit": 0,
            "x": 0.0, "y": 0.0, "rotation_deg": 0.0,
            "bbox_w": 4.0, "bbox_h": 8.0,
            "polygon": [(0, 0), (4, 0), (4, 8), (0, 8)],
            "pocket_polygons": [],
        })
        editor.placementsChanged.emit()
        # 32 / 4608 * 100 = 0.694...
        assert editor.sheetUtilization == "0.7%"

    def test_utilization_ignores_invalid_polygons(self, editor):
        editor.setSheetDimensions(48.0, 96.0, 0.0, 0.0)
        editor._placements.append({
            "component_id": 1, "component_name": "x", "dxf_filename": "x.dxf",
            "product_sku": "P", "product_unit": 0,
            "x": 0, "y": 0, "rotation_deg": 0.0,
            "bbox_w": 4.0, "bbox_h": 8.0,
            "polygon": [(0, 0)],  # Invalid: only one point
            "pocket_polygons": [],
        })
        editor.placementsChanged.emit()
        assert editor.sheetUtilization == "0.0%"

    def test_utilization_signal_fires_on_placement_change(self, editor, qtbot_app):
        signals = []
        editor.utilizationChanged.connect(lambda: signals.append(True))
        editor.placementsChanged.emit()
        assert len(signals) >= 1

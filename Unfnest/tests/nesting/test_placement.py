"""Tests for Layer 2: BLFPlacer — placement correctness."""
from __future__ import annotations

import pytest

from src.nesting.placement import BLFPlacer, Placement
from src.enrichment import EnrichedPart
from src.dxf_loader import PartGeometry, BoundingBox


def _make_part(part_id: str, w: float, h: float, area: float = None) -> EnrichedPart:
    """Create a mock EnrichedPart with a rectangular polygon."""
    hw, hh = w / 2, h / 2
    polygon = [(-hw, -hh), (hw, -hh), (hw, hh), (-hw, hh)]
    if area is None:
        area = w * h
    geom = PartGeometry(
        filename=f"{part_id}.dxf",
        polygons=[polygon],
        bounding_box=BoundingBox(min_x=-hw, min_y=-hh, max_x=hw, max_y=hh),
    )
    return EnrichedPart(
        part_id=part_id,
        geometry=geom,
        polygon=polygon,
        area=area,
        component_id=0,
        component_name=part_id,
        product_sku=None,
        variable_pockets=False,
        mating_role="neutral",
    )


@pytest.fixture
def placer():
    return BLFPlacer(
        sheet_w=48.0, sheet_h=96.0,
        spacing=0.75, edge_margin=0.75,
        rotation_count=4,
    )


class TestGreedyBLF:
    def test_single_rectangle(self, placer):
        """One rectangle should be placed on one sheet."""
        part = _make_part("rect1", 10, 20)
        sheets, failed = placer.greedy_blf([part])

        assert len(sheets) == 1
        assert len(failed) == 0
        assert sheets[0].part_count == 1

    def test_two_rectangles(self, placer):
        """Two rectangles should fit on one sheet."""
        parts = [
            _make_part("rect1", 10, 20),
            _make_part("rect2", 10, 20),
        ]
        sheets, failed = placer.greedy_blf(parts)

        assert len(failed) == 0
        total_placed = sum(s.part_count for s in sheets)
        assert total_placed == 2

    def test_multiple_small_parts(self, placer):
        """Many small parts should fit on fewer sheets than one-per-sheet."""
        parts = [_make_part(f"small_{i}", 5, 5) for i in range(20)]
        sheets, failed = placer.greedy_blf(parts)

        assert len(failed) == 0
        total_placed = sum(s.part_count for s in sheets)
        assert total_placed == 20
        # 20 parts of 5x5=25 sq in each = 500 sq in total
        # Sheet = 48*96 = 4608 sq in → should fit on 1 sheet
        assert len(sheets) <= 2

    def test_overflow_creates_new_sheet(self, placer):
        """Parts that fill a sheet should overflow to a new sheet."""
        # Each part is 20x40 = 800 sq in. Sheet is 4608 sq in.
        # With spacing and margins, about 3-4 should fit per sheet.
        parts = [_make_part(f"big_{i}", 20, 40) for i in range(8)]
        sheets, failed = placer.greedy_blf(parts)

        assert len(failed) == 0
        assert len(sheets) >= 2
        total_placed = sum(s.part_count for s in sheets)
        assert total_placed == 8

    def test_oversized_part_fails(self, placer):
        """A part larger than the sheet should fail."""
        part = _make_part("huge", 100, 200)
        sheets, failed = placer.greedy_blf([part])

        assert len(failed) == 1
        assert failed[0].part_id == "huge"

    def test_max_sheets_respected(self, placer):
        """max_sheets limit should be respected."""
        parts = [_make_part(f"big_{i}", 20, 40) for i in range(20)]
        sheets, failed = placer.greedy_blf(parts, max_sheets=2)

        assert len(sheets) <= 2


class TestSheetState:
    def test_utilization(self, placer):
        """Utilization should be computed correctly."""
        sheet = placer.new_sheet()
        assert sheet.utilization == 0.0

        # Place a part manually
        part = _make_part("test", 10, 10, area=100.0)
        sheet.placed.append(Placement(part=part, x=0, y=0, rotation=0))
        assert abs(sheet.utilization - (100.0 / (48 * 96) * 100)) < 0.01

    def test_to_nested_sheet(self, placer):
        """to_nested_sheet should produce valid NestedSheet."""
        sheet = placer.new_sheet()
        part = _make_part("test", 10, 10, area=100.0)
        sheet.placed.append(Placement(part=part, x=5.0, y=5.0, rotation=0))

        ns = sheet.to_nested_sheet(sheet_number=1)
        assert ns.sheet_number == 1
        assert len(ns.parts) == 1
        assert ns.parts[0].part_id == "test"
        assert ns.parts[0].x == 5.0

    def test_to_metadata(self, placer):
        """to_metadata should produce valid SheetMetadata."""
        sheet = placer.new_sheet(bundle_group=3)
        meta = sheet.to_metadata()
        assert meta.bundle_group == 3


class TestRotations:
    def test_rotation_picks_best(self, placer):
        """BLF should try rotations and pick the best position."""
        # A tall narrow piece might pack better rotated 90°
        part = _make_part("narrow", 5, 40)
        sheets, failed = placer.greedy_blf([part])
        assert len(failed) == 0
        assert sheets[0].placed[0].rotation in placer.rotations


class TestCallbacks:
    def test_progress_callback(self, placer):
        """Progress callback should be called for each placed part."""
        calls = []
        parts = [_make_part(f"p{i}", 5, 5) for i in range(3)]
        placer.greedy_blf(
            parts,
            progress_callback=lambda c, t: calls.append((c, t)),
        )
        assert len(calls) == 3

    def test_cancel_check(self, placer):
        """Cancel check should stop placement early."""
        cancel_after = [2]

        def cancel():
            cancel_after[0] -= 1
            return cancel_after[0] <= 0

        parts = [_make_part(f"p{i}", 5, 5) for i in range(10)]
        sheets, failed = placer.greedy_blf(parts, cancel_check=cancel)

        total_placed = sum(s.part_count for s in sheets)
        assert total_placed < 10


def _make_tab(part_id, w=10, h=10):
    """Create a tab part."""
    p = _make_part(part_id, w, h)
    p.mating_role = "tab"
    return p


def _make_receiver(part_id, w=10, h=10):
    """Create a receiver part."""
    p = _make_part(part_id, w, h)
    p.mating_role = "receiver"
    p.variable_pockets = True
    return p


def _make_neutral(part_id, w=10, h=10):
    """Create a neutral part."""
    return _make_part(part_id, w, h)


def _sheet_index_of(sheets, part_id):
    """Find which sheet a part_id landed on."""
    for i, sheet in enumerate(sheets):
        for p in sheet.placed:
            if p.part.part_id == part_id:
                return i
    return None


class TestBlockPlacement:
    """Tests for greedy_blf_blocks — block-aware placement."""

    def test_tabs_and_receiver_same_sheet(self, placer):
        """Tabs and receiver for the same block should land on the same sheet."""
        block = [_make_tab("tab1"), _make_tab("tab2"), _make_receiver("recv1")]
        sheets, failed = placer.greedy_blf_blocks([block])

        assert len(failed) == 0
        tab1_sheet = _sheet_index_of(sheets, "tab1")
        tab2_sheet = _sheet_index_of(sheets, "tab2")
        recv_sheet = _sheet_index_of(sheets, "recv1")

        assert tab1_sheet == tab2_sheet, "Tabs should be on the same sheet"
        assert recv_sheet == tab1_sheet, "Receiver should be on the tab sheet"

    def test_receiver_never_before_tabs(self, placer):
        """Receiver must never land on a sheet before its tabs."""
        # Fill sheets to force overflow:
        # Large tabs that mostly fill a sheet, then a receiver
        block = [_make_tab("tab1", 40, 80), _make_receiver("recv1", 20, 20)]
        sheets, failed = placer.greedy_blf_blocks([block])

        assert len(failed) == 0
        tab_sheet = _sheet_index_of(sheets, "tab1")
        recv_sheet = _sheet_index_of(sheets, "recv1")
        assert recv_sheet >= tab_sheet, "Receiver must be on tab sheet or later"

    def test_receiver_not_before_tabs_cross_block(self, placer):
        """Receivers from block B should not land on sheets before block B's tabs,
        even if block A left space on earlier sheets."""
        # Block A: small tabs on sheet 0
        block_a = [_make_tab("a_tab1", 5, 5), _make_tab("a_tab2", 5, 5)]
        # Block B: large tabs that need a new sheet, plus a small receiver
        block_b = [_make_tab("b_tab1", 40, 80), _make_receiver("b_recv1", 5, 5)]

        sheets, failed = placer.greedy_blf_blocks([block_a, block_b])

        assert len(failed) == 0
        b_tab_sheet = _sheet_index_of(sheets, "b_tab1")
        b_recv_sheet = _sheet_index_of(sheets, "b_recv1")
        assert b_recv_sheet >= b_tab_sheet, "Block B receiver must not precede Block B tabs"

    def test_neutral_only_block_no_constraint(self, placer):
        """Neutral-only blocks should fill available sheets without constraint."""
        # Create some initial sheets with space by placing a few parts
        block_with_tabs = [_make_tab("tab1", 10, 10)]
        neutral_blocks = [
            [_make_neutral(f"n{i}", 5, 5)] for i in range(10)
        ]
        all_blocks = [block_with_tabs] + neutral_blocks

        sheets, failed = placer.greedy_blf_blocks(all_blocks)

        assert len(failed) == 0
        # Neutral parts should pack efficiently, not one-per-sheet
        assert len(sheets) <= 2, f"Got {len(sheets)} sheets — neutrals should pack tightly"

    def test_neutral_in_tab_block_unconstrained(self, placer):
        """Neutral parts within a tab-containing block should not be constrained."""
        # Large tab fills most of sheet, neutral and receiver follow
        block = [
            _make_tab("tab1", 40, 80),
            _make_neutral("neut1", 10, 10),
            _make_receiver("recv1", 10, 10),
        ]
        sheets, failed = placer.greedy_blf_blocks([block])

        assert len(failed) == 0
        tab_sheet = _sheet_index_of(sheets, "tab1")
        recv_sheet = _sheet_index_of(sheets, "recv1")
        assert recv_sheet >= tab_sheet

    def test_loose_parts_fill_any_sheet(self, placer):
        """Loose parts (no block) should fill any available sheet."""
        blocks = [[_make_tab("tab1", 10, 10)]]
        loose = [_make_neutral(f"loose{i}", 5, 5) for i in range(5)]

        sheets, failed = placer.greedy_blf_blocks(blocks, loose_parts=loose)

        assert len(failed) == 0
        total = sum(s.part_count for s in sheets)
        assert total == 6  # 1 tab + 5 loose

    def test_multiple_blocks_correct_ordering(self, placer):
        """Multiple blocks should each maintain their own tab-receiver ordering."""
        blocks = [
            [_make_tab("a_tab", 15, 15), _make_receiver("a_recv", 10, 10)],
            [_make_tab("b_tab", 15, 15), _make_receiver("b_recv", 10, 10)],
            [_make_tab("c_tab", 15, 15), _make_receiver("c_recv", 10, 10)],
        ]
        sheets, failed = placer.greedy_blf_blocks(blocks)

        assert len(failed) == 0
        for prefix in ["a", "b", "c"]:
            tab_sheet = _sheet_index_of(sheets, f"{prefix}_tab")
            recv_sheet = _sheet_index_of(sheets, f"{prefix}_recv")
            assert recv_sheet >= tab_sheet, f"Block {prefix}: receiver before tabs"

    def test_empty_tabs_block(self, placer):
        """A block with no tabs (all neutrals) should place without errors."""
        block = [_make_neutral("n1", 10, 10), _make_neutral("n2", 10, 10)]
        sheets, failed = placer.greedy_blf_blocks([block])

        assert len(failed) == 0
        assert sum(s.part_count for s in sheets) == 2


class TestBlockAwareFastBLF:
    """Tests for fast_blf and repack_full_resolution with block boundaries."""

    def test_fast_blf_with_boundaries(self, placer):
        """fast_blf with block boundaries should respect receiver constraint."""
        tab = _make_tab("tab1", 40, 80)
        recv = _make_receiver("recv1", 10, 10)
        parts = [(tab, 0.0), (recv, 0.0)]
        boundaries = [(0, 1)]  # one block starting at 0 with 1 tab

        sheets = placer.fast_blf(parts, block_boundaries=boundaries)

        tab_sheet = _sheet_index_of(sheets, "tab1")
        recv_sheet = _sheet_index_of(sheets, "recv1")
        assert recv_sheet >= tab_sheet

    def test_fast_blf_without_boundaries(self, placer):
        """fast_blf without boundaries should work as before."""
        parts = [(_make_neutral(f"p{i}", 10, 10), 0.0) for i in range(5)]
        sheets = placer.fast_blf(parts)

        total = sum(s.part_count for s in sheets)
        assert total == 5

    def test_repack_with_boundaries(self, placer):
        """repack_full_resolution with boundaries should respect receiver constraint."""
        tab = _make_tab("tab1", 40, 80)
        recv = _make_receiver("recv1", 10, 10)
        parts = [(tab, 0.0), (recv, 0.0)]
        boundaries = [(0, 1)]

        sheets, failed = placer.repack_full_resolution(parts, block_boundaries=boundaries)

        assert len(failed) == 0
        tab_sheet = _sheet_index_of(sheets, "tab1")
        recv_sheet = _sheet_index_of(sheets, "recv1")
        assert recv_sheet >= tab_sheet

    def test_cross_block_receiver_constraint_in_fast_blf(self, placer):
        """fast_blf should prevent block B's receiver from landing before block B's tabs."""
        # Block A: small tab (leaves space on sheet 0)
        # Block B: large tab (needs sheet 1), small receiver
        a_tab = _make_tab("a_tab", 5, 5)
        b_tab = _make_tab("b_tab", 40, 80)
        b_recv = _make_receiver("b_recv", 5, 5)

        parts = [(a_tab, 0.0), (b_tab, 0.0), (b_recv, 0.0)]
        boundaries = [(0, 1), (1, 1)]  # block A: idx 0, 1 tab. block B: idx 1, 1 tab

        sheets = placer.fast_blf(parts, block_boundaries=boundaries)

        b_tab_sheet = _sheet_index_of(sheets, "b_tab")
        b_recv_sheet = _sheet_index_of(sheets, "b_recv")
        assert b_recv_sheet >= b_tab_sheet, "Block B receiver must not precede Block B tabs"

    def test_multiple_blocks_boundaries(self, placer):
        """Multiple blocks in fast_blf should each maintain ordering."""
        parts = []
        boundaries = []
        for i, prefix in enumerate(["a", "b", "c"]):
            start = len(parts)
            parts.append((_make_tab(f"{prefix}_tab", 15, 15), 0.0))
            parts.append((_make_receiver(f"{prefix}_recv", 10, 10), 0.0))
            boundaries.append((start, 1))  # 1 tab per block

        sheets = placer.fast_blf(parts, block_boundaries=boundaries)

        for prefix in ["a", "b", "c"]:
            tab_sheet = _sheet_index_of(sheets, f"{prefix}_tab")
            recv_sheet = _sheet_index_of(sheets, f"{prefix}_recv")
            assert recv_sheet >= tab_sheet, f"Block {prefix}: receiver before tabs"


class TestSheetCapRemoved:
    """Verify the 100-sheet cap no longer applies."""

    def test_no_hard_cap(self):
        """Should be able to create more than 100 sheets."""
        placer = BLFPlacer(sheet_w=10, sheet_h=10, spacing=0.25, edge_margin=0.25)
        # Each part nearly fills a tiny sheet
        parts = [_make_part(f"p{i}", 8, 8) for i in range(110)]
        sheets, failed = placer.greedy_blf(parts)

        total = sum(s.part_count for s in sheets) + len(failed)
        assert total == 110
        assert len(sheets) >= 100, "Should exceed old 100-sheet cap"


class TestMultiTabAtomicity:
    """All tabs (and receivers) of a block must land on one sheet — atomically.

    This is the joinery invariant: a tab and its receiving pocket must be cut
    from the same physical material, otherwise the joint won't fit. For a
    bench (2 identical legs + 1 tabletop) or a stool (4 distinct legs + 1 seat),
    every member of the mating group MUST share a sheet, even when sheet 0
    has space for one tab but not all of them.

    These tests construct adversarial geometry where exactly one tab from a
    multi-tab block fits in the leftover space on sheet 0, then verify that
    placement code keeps the whole mating group together (forced to a fresh
    sheet) rather than splitting them.
    """

    def _adversarial_placer(self):
        """Standard sheet — geometry below is sized so atomicity matters at BOTH
        fast (1.0") and full (0.25") resolutions."""
        return BLFPlacer(
            sheet_w=48.0, sheet_h=96.0,
            spacing=0.5, edge_margin=0.5,
            rotation_count=4,
        )

    def _adversarial_blocks(self):
        """Block A fills most of sheet 0, leaving a strip that only fits ONE Block B tab.

        Sheet usable area ≈ 47×95. Block A (40×60) leaves a strip of ≈ 47×34 above.
        Block B tabs (44×18) — one fits in the strip, two don't (18+0.5+18=36.5 > 34).
        Rotation doesn't help: 18×44 rotated stands 44 tall, won't fit in 34.

        So two Block B tabs can never coexist with Block A on sheet 0. Atomic
        placement forces all of Block B to sheet 1 together. The bug allows
        the first Block B tab to land on sheet 0 in the strip, splitting it
        from its sibling.
        """
        a_tab = _make_tab("a_tab", 40, 60)
        b_tab1 = _make_tab("b_tab1", 44, 18)
        b_tab2 = _make_tab("b_tab2", 44, 18)
        b_recv = _make_receiver("b_recv", 44, 18)
        return a_tab, b_tab1, b_tab2, b_recv

    def test_greedy_keeps_multi_tab_block_atomic(self):
        """greedy_blf_blocks enforces tab atomicity via _try_place_mating_block.

        This test guards against regressions in the greedy path.
        """
        placer = self._adversarial_placer()
        a_tab, b1, b2, recv = self._adversarial_blocks()

        sheets, failed = placer.greedy_blf_blocks([
            [a_tab],
            [b1, b2, recv],
        ])

        assert len(failed) == 0
        b1_sheet = _sheet_index_of(sheets, "b_tab1")
        b2_sheet = _sheet_index_of(sheets, "b_tab2")
        recv_sheet = _sheet_index_of(sheets, "b_recv")
        assert b1_sheet == b2_sheet, (
            f"Block B tabs split: b_tab1=sheet {b1_sheet}, b_tab2=sheet {b2_sheet}"
        )
        assert recv_sheet == b1_sheet, (
            f"Block B receiver split from tabs: tabs=sheet {b1_sheet}, recv=sheet {recv_sheet}"
        )

    def test_fast_blf_keeps_multi_tab_block_atomic(self):
        """fast_blf (used by SA evaluation) must also keep all tabs together.

        Regression test for the SA-path tab-split bug: _place_with_block_awareness
        used to place tabs one at a time without an atomic check, allowing the
        second tab to spill to a different sheet from the first.
        """
        placer = self._adversarial_placer()
        a_tab, b1, b2, recv = self._adversarial_blocks()

        parts = [
            (a_tab, 0.0),
            (b1, 0.0), (b2, 0.0), (recv, 0.0),
        ]
        # Block A starts at idx 0 (1 tab), Block B starts at idx 1 (2 tabs)
        boundaries = [(0, 1), (1, 2)]

        sheets = placer.fast_blf(parts, block_boundaries=boundaries)

        b1_sheet = _sheet_index_of(sheets, "b_tab1")
        b2_sheet = _sheet_index_of(sheets, "b_tab2")
        recv_sheet = _sheet_index_of(sheets, "b_recv")
        # Sanity: all parts must actually be placed (None == None would silently pass)
        assert b1_sheet is not None, "b_tab1 was not placed at all"
        assert b2_sheet is not None, "b_tab2 was not placed at all"
        assert recv_sheet is not None, "b_recv was not placed at all"
        assert b1_sheet == b2_sheet, (
            f"Block B tabs split in fast_blf: b_tab1=sheet {b1_sheet}, b_tab2=sheet {b2_sheet}"
        )
        assert recv_sheet == b1_sheet, (
            f"Block B receiver split from tabs in fast_blf: "
            f"tabs=sheet {b1_sheet}, recv=sheet {recv_sheet}"
        )

    def test_repack_full_resolution_keeps_multi_tab_block_atomic(self):
        """repack_full_resolution (used by SA's final pass) must also keep tabs together."""
        placer = self._adversarial_placer()
        a_tab, b1, b2, recv = self._adversarial_blocks()

        parts = [
            (a_tab, 0.0),
            (b1, 0.0), (b2, 0.0), (recv, 0.0),
        ]
        boundaries = [(0, 1), (1, 2)]

        sheets, failed = placer.repack_full_resolution(parts, block_boundaries=boundaries)

        assert len(failed) == 0
        b1_sheet = _sheet_index_of(sheets, "b_tab1")
        b2_sheet = _sheet_index_of(sheets, "b_tab2")
        recv_sheet = _sheet_index_of(sheets, "b_recv")
        assert b1_sheet is not None, "b_tab1 was not placed at all"
        assert b2_sheet is not None, "b_tab2 was not placed at all"
        assert recv_sheet is not None, "b_recv was not placed at all"
        assert b1_sheet == b2_sheet, (
            f"Block B tabs split in repack: b_tab1=sheet {b1_sheet}, b_tab2=sheet {b2_sheet}"
        )
        assert recv_sheet == b1_sheet, (
            f"Block B receiver split from tabs in repack: "
            f"tabs=sheet {b1_sheet}, recv=sheet {recv_sheet}"
        )


class TestStrictReceiverConstraint:
    """Receivers must land on tab_sheet OR tab_sheet+1 — never further."""

    def test_receiver_on_next_sheet_when_tab_sheet_full(self):
        """When tabs fill a sheet, the receiver gets the immediately-next sheet
        (created fresh if none exists) rather than drifting far away.
        """
        placer = BLFPlacer(
            sheet_w=48.0, sheet_h=96.0,
            spacing=0.5, edge_margin=0.5,
            rotation_count=4,
        )
        # Tab fills most of the sheet, leaving no room for the (large) receiver
        tab = _make_tab("tab1", 46, 90)
        recv = _make_receiver("recv1", 40, 80)

        sheets, failed = placer.greedy_blf_blocks([[tab, recv]])

        assert len(failed) == 0
        tab_sheet = _sheet_index_of(sheets, "tab1")
        recv_sheet = _sheet_index_of(sheets, "recv1")
        # Receiver must be on tab_sheet (impossible here due to size) or tab_sheet+1
        assert recv_sheet == tab_sheet + 1, (
            f"Receiver must be on tab_sheet+1 (={tab_sheet + 1}), got {recv_sheet}"
        )

    def test_block_fails_atomically_when_max_sheets_exhausted(self):
        """When the constraint can't be satisfied because no fresh sheets
        are available (max_sheets exhausted), the WHOLE block fails — no
        half-placed parts left behind."""
        placer = BLFPlacer(
            sheet_w=48.0, sheet_h=96.0,
            spacing=0.5, edge_margin=0.5,
            rotation_count=4,
        )
        # Block A consumes both available sheets via strict K + K+1 split
        a_tab = _make_tab("a_tab", 46, 90)
        a_recv = _make_receiver("a_recv", 46, 90)

        # Block B has a small tab that COULD fit in leftover space, but its
        # large receiver has nowhere to go (max_sheets=2 prevents a fresh K+1)
        b_tab = _make_tab("b_tab", 5, 5)
        b_recv = _make_receiver("b_recv", 46, 90)

        sheets, failed = placer.greedy_blf_blocks(
            [
                [a_tab, a_recv],
                [b_tab, b_recv],
            ],
            max_sheets=2,
        )

        # Block A succeeds (uses both allowed sheets via Strategy B)
        assert _sheet_index_of(sheets, "a_tab") is not None
        assert _sheet_index_of(sheets, "a_recv") is not None

        # Block B fails atomically — tab is NOT half-placed
        assert _sheet_index_of(sheets, "b_tab") is None, (
            "Block B's tab should NOT have been committed when receiver "
            "couldn't satisfy the constraint"
        )
        assert _sheet_index_of(sheets, "b_recv") is None
        b_failed_ids = {p.part_id for p in failed}
        assert "b_tab" in b_failed_ids
        assert "b_recv" in b_failed_ids

    def test_split_K_and_K_plus_1_succeeds(self):
        """When the receiver doesn't fit alongside tabs but fits on the next
        sheet, the block succeeds with tabs on K and receiver on K+1."""
        placer = BLFPlacer(
            sheet_w=48.0, sheet_h=96.0,
            spacing=0.5, edge_margin=0.5,
            rotation_count=4,
        )
        # Tabs are small but the receiver is too big to fit beside them
        tab1 = _make_tab("tab1", 10, 30)
        tab2 = _make_tab("tab2", 10, 30)
        recv = _make_receiver("recv", 46, 90)

        sheets, failed = placer.greedy_blf_blocks([[tab1, tab2, recv]])

        assert len(failed) == 0
        t1 = _sheet_index_of(sheets, "tab1")
        t2 = _sheet_index_of(sheets, "tab2")
        r = _sheet_index_of(sheets, "recv")
        assert t1 == t2, f"Tabs not co-located: t1={t1}, t2={t2}"
        assert r == t1 + 1, f"Receiver should be on tab_sheet+1 ({t1 + 1}), got {r}"

    def test_oversized_part_fails_block(self):
        """A tab that's bigger than any sheet causes its block to fail entirely,
        no parts placed."""
        placer = BLFPlacer(
            sheet_w=48.0, sheet_h=96.0,
            spacing=0.5, edge_margin=0.5,
            rotation_count=4,
        )
        oversized_tab = _make_tab("huge_tab", 200, 300)
        recv = _make_receiver("recv", 10, 10)

        sheets, failed = placer.greedy_blf_blocks([[oversized_tab, recv]])

        assert _sheet_index_of(sheets, "huge_tab") is None
        assert _sheet_index_of(sheets, "recv") is None
        failed_ids = {p.part_id for p in failed}
        assert "huge_tab" in failed_ids
        assert "recv" in failed_ids

    def test_sa_path_enforces_strict_constraint(self):
        """fast_blf and repack_full_resolution also fail blocks atomically when
        max_sheets is exhausted and the strict K+K+1 constraint can't be met."""
        placer = BLFPlacer(
            sheet_w=48.0, sheet_h=96.0,
            spacing=0.5, edge_margin=0.5,
            rotation_count=4,
        )
        a_tab = _make_tab("a_tab", 46, 90)
        a_recv = _make_receiver("a_recv", 46, 90)
        b_tab = _make_tab("b_tab", 5, 5)
        b_recv = _make_receiver("b_recv", 46, 90)

        # Greedy block ordering within each block: tabs first, then receivers
        parts = [
            (a_tab, 0.0), (a_recv, 0.0),
            (b_tab, 0.0), (b_recv, 0.0),
        ]
        # Block A: starts at idx 0, 1 tab. Block B: starts at idx 2, 1 tab.
        boundaries = [(0, 1), (2, 1)]

        sheets, failed = placer.repack_full_resolution(
            parts, block_boundaries=boundaries, max_sheets=2,
        )

        # Block B must fail atomically — neither tab nor receiver placed
        assert _sheet_index_of(sheets, "b_tab") is None
        assert _sheet_index_of(sheets, "b_recv") is None
        failed_ids = {p.part_id for p in failed}
        assert "b_tab" in failed_ids
        assert "b_recv" in failed_ids

"""Tests for the Manual Nest feature — model helpers + pipeline override stub."""
from __future__ import annotations

import pytest

from bridge.models.manual_nest_model import _summarize_parts
from src.nesting.pipeline import _apply_manual_overrides


# ==================== _summarize_parts ====================

class TestSummarizeParts:
    def test_empty_returns_placeholder(self):
        assert _summarize_parts([]) == "(empty)"

    def test_sheet_without_parts(self):
        assert _summarize_parts([{"parts": []}]) == "(empty)"

    def test_single_product_single_unit(self):
        sheets = [{"parts": [
            {"component_id": 1, "product_sku": "BENCH-01", "product_unit": 0},
            {"component_id": 2, "product_sku": "BENCH-01", "product_unit": 0},
        ]}]
        # 2 parts but one unit — should read "BENCH-01 x1"
        assert _summarize_parts(sheets) == "BENCH-01 x1"

    def test_multiple_units_same_sku(self):
        sheets = [{"parts": [
            {"component_id": 1, "product_sku": "BENCH-01", "product_unit": 0},
            {"component_id": 1, "product_sku": "BENCH-01", "product_unit": 1},
            {"component_id": 1, "product_sku": "BENCH-01", "product_unit": 2},
        ]}]
        assert _summarize_parts(sheets) == "BENCH-01 x3"

    def test_multiple_skus_sorted_alphabetically(self):
        sheets = [{"parts": [
            {"component_id": 1, "product_sku": "STOOL-01", "product_unit": 0},
            {"component_id": 2, "product_sku": "BENCH-01", "product_unit": 0},
        ]}]
        # Output is sorted by SKU — BENCH-01 comes before STOOL-01
        assert _summarize_parts(sheets) == "BENCH-01 x1, STOOL-01 x1"

    def test_mixed_product_and_loose_components(self):
        sheets = [{"parts": [
            {"component_id": 1, "product_sku": "BENCH-01", "product_unit": 0},
            {"component_id": 9, "product_sku": None, "product_unit": None},
            {"component_id": 10, "product_sku": None, "product_unit": None},
        ]}]
        assert _summarize_parts(sheets) == "BENCH-01 x1, 2 loose"

    def test_units_deduplicated_across_sheets(self):
        # Same (sku, unit) appearing on two sheets = still one unit
        sheets = [
            {"parts": [{"component_id": 1, "product_sku": "BENCH-01", "product_unit": 0}]},
            {"parts": [{"component_id": 2, "product_sku": "BENCH-01", "product_unit": 0}]},
        ]
        assert _summarize_parts(sheets) == "BENCH-01 x1"


# ==================== _apply_manual_overrides stub ====================

class _DbWithOverrides:
    """Mock db that returns a configurable list of enabled manual nests."""

    def __init__(self, enabled_nests):
        self._nests = enabled_nests

    def get_enabled_manual_nests(self):
        return self._nests


class _DbWithoutHook:
    """Mock db (like legacy SQLite) that has no manual-nest endpoints."""


class TestApplyManualOverridesStub:
    def test_returns_enriched_unchanged_when_no_db(self):
        enriched = ["part_a", "part_b"]  # sentinel values, not real EnrichedParts
        result = _apply_manual_overrides(enriched, None)
        assert result is enriched

    def test_returns_enriched_unchanged_when_db_has_no_hook(self):
        enriched = ["part_a"]
        result = _apply_manual_overrides(enriched, _DbWithoutHook())
        assert result is enriched

    def test_returns_enriched_unchanged_when_no_nests_enabled(self):
        enriched = ["part_a"]
        messages: list[str] = []
        result = _apply_manual_overrides(
            enriched, _DbWithOverrides([]),
            status_callback=messages.append,
        )
        assert result is enriched
        # No status message should fire when no overrides are active
        assert messages == []

    def test_status_message_fires_when_overrides_active(self):
        enriched = ["part_a"]
        messages: list[str] = []
        result = _apply_manual_overrides(
            enriched,
            _DbWithOverrides([{"id": 1, "name": "Bench set"}]),
            status_callback=messages.append,
        )
        # Stub doesn't consume parts yet
        assert result is enriched
        # Operator gets told wiring is live
        assert len(messages) == 1
        assert "1 manual nest override" in messages[0]
        assert "Bench set" in messages[0]

    def test_status_message_truncates_long_lists(self):
        messages: list[str] = []
        _apply_manual_overrides(
            ["p"],
            _DbWithOverrides([{"id": i, "name": f"Nest {i}"} for i in range(5)]),
            status_callback=messages.append,
        )
        assert "5 manual nest override" in messages[0]
        # Truncation ellipsis indicates names 4+ were elided
        assert "…" in messages[0]

    def test_exception_during_fetch_is_swallowed(self):
        class _BrokenDb:
            def get_enabled_manual_nests(self):
                raise RuntimeError("server unreachable")

        enriched = ["part_a"]
        # Must not raise — lookup failures cannot break a real nesting run
        result = _apply_manual_overrides(enriched, _BrokenDb())
        assert result is enriched

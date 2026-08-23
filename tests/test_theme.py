"""Tests for pixelpixoo.theme coercion and layout math."""

from __future__ import annotations

import pytest

from pixelpixoo.theme import (
    coerce_layout,
    coerce_text_scale,
    coerce_view_layout,
    fit_row_pattern,
    layout_rects,
    pattern_pane_count,
    row_pattern_rects,
    theme_for,
)


class TestCoercion:
    def test_valid_values_pass_through(self) -> None:
        assert coerce_text_scale("TINY") == "tiny"
        assert coerce_layout("dashboard") == "dashboard"
        assert coerce_view_layout("grid_4") == "grid_4"

    def test_invalid_falls_back(self) -> None:
        assert coerce_text_scale("huge") == "normal"
        assert coerce_layout("banana", default="split") == "split"
        assert coerce_view_layout(42) == "list"

    def test_none_uses_default(self) -> None:
        assert coerce_text_scale(None) == "normal"


class TestTheme:
    def test_known_and_unknown_scales(self) -> None:
        tiny = theme_for("tiny")
        assert tiny.use_tiny_font is True
        assert tiny.body_h == 5
        # Unknown strings fall back to normal.
        assert theme_for("bogus").text_scale == "normal"

    def test_height_properties(self) -> None:
        t = theme_for("normal")
        assert t.hero == 2
        assert t.hero_h == 14
        assert t.micro_h == 7


class TestLayoutRects:
    def test_focus_single_pane(self) -> None:
        rects = layout_rects("focus", header=False)
        assert rects == [(0, 0, 64, 64)]

    def test_header_shrinks_height(self) -> None:
        (rect,) = layout_rects("focus", header=True, header_h=10)
        assert rect == (0, 10, 64, 54)

    def test_split_h_two_bands(self) -> None:
        rects = layout_rects("split_h", header=False)
        assert len(rects) == 2
        assert all(r[2] == 64 for r in rects)

    def test_split_v_two_columns(self) -> None:
        rects = layout_rects("split_v", header=True, header_h=8)
        assert [r[:2] for r in rects] == [(0, 8), (32, 8)]

    def test_grid4_covers_canvas(self) -> None:
        rects = layout_rects("grid_4", header=False)
        assert len(rects) == 4
        total = sum(r[2] * r[3] for r in rects)
        assert total == 64 * 64


class TestFitRowPattern:
    def test_pane_count(self) -> None:
        assert pattern_pane_count([1, 2, 2]) == 5

    def test_exact_fit_unchanged(self) -> None:
        assert fit_row_pattern([1, 2], 3) == [1, 2]

    def test_trims_excess_capacity(self) -> None:
        # Conditional tiles dropped: no trailing blank band remains.
        assert pattern_pane_count(fit_row_pattern([1, 2, 2], 4)) == 4

    def test_grows_when_more_tiles(self) -> None:
        fitted = fit_row_pattern([1], 5)
        assert pattern_pane_count(fitted) == 5

    def test_empty_pattern_defaults(self) -> None:
        assert fit_row_pattern([], 3) == [1, 1, 1]
        assert fit_row_pattern([1, 2], 0) == [1]

    def test_split_halved_to_match_odd_count(self) -> None:
        assert fit_row_pattern([2], 1) == [1]


class TestRowPatternRects:
    def test_example_from_docs(self) -> None:
        rects = row_pattern_rects([1, 1, 1, 2], header=False, tile_count=None)
        # Three full-width rows then a split pair.
        full = [r for r in rects if r[2] == 64]
        split = [r for r in rects if r[2] == 32]
        assert len(full) == 3 and len(split) == 2

    def test_rects_stay_within_canvas(self) -> None:
        rects = row_pattern_rects([2, 2, 1, 2], header=True, tile_count=7)
        for x, y, w, h in rects:
            assert x >= 0 and y >= 0
            assert x + w <= 64
            assert y + h <= 64

    def test_tile_count_fit_removes_blank_rows(self) -> None:
        rects = row_pattern_rects([1, 2, 2, 2], header=False, tile_count=4)
        assert len(rects) == 4

    def test_empty_pattern_single_band(self) -> None:
        (rect,) = row_pattern_rects([], header=False)
        assert rect == (0, 0, 64, 64)


def test_min_band_height_enforced() -> None:
    # Many rows must not collapse below the 8px floor.
    rects = row_pattern_rects([1] * 20, header=False)
    assert all(h >= 8 for _, _, _, h in rects)


@pytest.mark.parametrize(
    ("pattern", "expected"),
    [
        ([1, 2, -3], 3),
        ([], 0),
        ([2, 2, 2, 2], 8),
    ],
)
def test_pattern_pane_count_filters_invalid(pattern: list[int], expected: int) -> None:
    assert pattern_pane_count(pattern) == expected

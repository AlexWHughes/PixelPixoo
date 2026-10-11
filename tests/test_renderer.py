"""Tests for pixelpixoo.renderer color parsing, fonts, and canvas helpers."""

from __future__ import annotations

import pytest

from pixelpixoo.renderer import (
    SIZE,
    draw_centered,
    draw_text,
    error_frame,
    fit_scale,
    hex_to_rgb,
    new_canvas,
    parse_hex_color,
    text_width,
)


class TestParseHexColor:
    @pytest.mark.parametrize(
        ("raw", "expected"),
        [
            ("#FF0000", "#ff0000"),
            ("ff0000", "#ff0000"),
            ("#F00", "#ff0000"),
            ("abc", "#aabbcc"),
            ("  #00FF00  ", "#00ff00"),
            ("", ""),
            (None, ""),
            ("12345", ""),  # wrong length
            ("zzzzzz", ""),  # not hex
            ("#", ""),
        ],
    )
    def test_cases(self, raw: object, expected: str) -> None:
        assert parse_hex_color(raw) == expected


class TestHexToRgb:
    def test_round_trip(self) -> None:
        assert hex_to_rgb("#3CC864") == (60, 200, 100)

    def test_invalid_returns_none(self) -> None:
        assert hex_to_rgb("nope") is None
        assert hex_to_rgb("") is None


def test_new_canvas_is_black_64() -> None:
    img = new_canvas()
    assert img.size == (SIZE, SIZE)
    assert img.getpixel((0, 0)) == (0, 0, 0)


class TestTextMetrics:
    def test_empty_text_width(self) -> None:
        assert text_width("") == 0
        assert draw_text(new_canvas(), "", 0, 0) == 0

    def test_known_glyph_width(self) -> None:
        # Tiny glyphs are 3 columns wide; "N" is deliberately 4.
        assert text_width("1", spacing=0, tiny=True) == 3
        assert text_width("N", spacing=0, tiny=True) == 4

    def test_spacing_between_glyphs_only(self) -> None:
        one = text_width("A", spacing=2)
        two = text_width("AA", spacing=2)
        assert two == one * 2 + 2

    def test_unknown_char_falls_back_to_question_mark(self) -> None:
        assert text_width("@") == text_width("?")


class TestDrawText:
    def test_returns_consumed_width(self) -> None:
        img = new_canvas()
        w = draw_text(img, "HI", 10, 10)
        assert w == text_width("HI")

    def test_clipping_does_not_crash(self) -> None:
        img = new_canvas()
        # Start off-canvas and run past the edge.
        draw_text(img, "LONGSTRINGOFLONGTEXT", -20, -20)

    def test_paints_pixels(self) -> None:
        img = new_canvas()
        draw_text(img, "|", 0, 0, scale=1, spacing=0)  # fallback "?" paints
        colors = {img.getpixel((x, y)) for x in range(6) for y in range(7)}
        assert (255, 255, 255) in colors


def test_draw_centered_keeps_text_on_canvas() -> None:
    img = new_canvas()
    long_word = "MISISSIPPIBAND"
    assert text_width(long_word) > SIZE
    draw_centered(img, long_word, 30)  # must clamp x >= 0 and clip safely


def test_error_frame_layout() -> None:
    frame = error_frame("BOOM")
    assert frame.size == (SIZE, SIZE)
    # Label bar background painted at top-left.
    assert frame.getpixel((0, 0)) == (20, 20, 28)


class TestFitScale:
    def test_prefers_large_when_it_fits(self) -> None:
        assert fit_scale("OK", max_width=64) == 2

    def test_steps_down_until_it_fits(self) -> None:
        assert fit_scale("THISISTOOLONG", max_width=30) == 1

    def test_never_above_one(self) -> None:
        assert fit_scale("X" * 100, max_width=4) == 1

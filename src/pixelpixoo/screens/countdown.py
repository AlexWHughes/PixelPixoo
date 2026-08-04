"""Countdown-to-date screens."""

from __future__ import annotations

from PIL import Image

from pixelpixoo.config import CountdownTarget
from pixelpixoo.renderer import (
    BLACK,
    WHITE,
    draw_centered,
    draw_label_bar,
    draw_text,
    fit_scale,
    new_canvas,
    text_width,
)
from pixelpixoo.screens.base import BaseScreen
from pixelpixoo.theme import Theme, theme_for
from pixelpixoo.timeutil import (
    format_remaining_pair,
    parse_iso_datetime,
    remaining_seconds,
    urgency_color,
)

# Re-exports for widgets / callers
_parse_target = parse_iso_datetime


def _format_remaining(delta_seconds: float) -> tuple[str, str]:
    return format_remaining_pair(delta_seconds)


class CountdownScreen(BaseScreen):
    name = "countdown"
    error_label = "CD"

    def __init__(self, target: CountdownTarget, theme: Theme | None = None) -> None:
        super().__init__(need_client=False)
        self.target = target
        self.theme = theme or theme_for("normal")
        self.name = f"countdown:{target.label}"

    def _render(self) -> Image.Image:
        target = parse_iso_datetime(self.target.at)
        remaining = remaining_seconds(target)
        primary, secondary = format_remaining_pair(remaining)
        accent = urgency_color(remaining, use_week_band=True)

        img = new_canvas(BLACK)
        t = self.theme
        draw_label_bar(
            img,
            self.target.label.upper(),
            accent,
            height=t.header_h,
            tiny=t.use_tiny_font,
        )
        y = t.header_h + 2
        draw_centered(
            img, "UNTIL", y, WHITE, tiny=t.use_tiny_font, spacing=t.spacing
        )
        y += t.body_h + t.line_gap

        scale = fit_scale(primary, 60, prefer=t.hero, tiny=t.use_tiny_font)
        draw_centered(
            img,
            primary,
            y,
            accent,
            scale=scale,
            tiny=t.use_tiny_font,
            spacing=t.spacing,
        )
        draw_text(
            img,
            secondary,
            2,
            54,
            WHITE,
            tiny=t.use_tiny_font,
            spacing=t.spacing,
        )
        local_label = target.astimezone().strftime("%m/%d")
        draw_text(
            img,
            local_label,
            64 - text_width(local_label, tiny=t.use_tiny_font, spacing=t.spacing) - 2,
            54,
            WHITE,
            tiny=t.use_tiny_font,
            spacing=t.spacing,
        )
        return img

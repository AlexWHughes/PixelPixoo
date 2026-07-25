"""Countdown-to-date screens."""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from PIL import Image

from pixelpixoo.config import CountdownTarget
from pixelpixoo.renderer import (
    BLACK,
    GREEN,
    ORANGE,
    PURPLE,
    RED,
    WHITE,
    draw_centered,
    draw_label_bar,
    draw_text,
    error_frame,
    fit_scale,
    new_canvas,
    text_width,
)
from pixelpixoo.theme import Theme, theme_for

logger = logging.getLogger(__name__)


def _parse_target(at: str) -> datetime:
    value = at.strip()
    if value.endswith("Z"):
        value = value[:-1] + "+00:00"
    dt = datetime.fromisoformat(value)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def _format_remaining(delta_seconds: float) -> tuple[str, str]:
    if delta_seconds <= 0:
        return "NOW", "DONE"
    total = int(delta_seconds)
    days, rem = divmod(total, 86400)
    hours, rem = divmod(rem, 3600)
    minutes = rem // 60
    if days >= 100:
        return f"{days}D", "LEFT"
    if days >= 1:
        return f"{days}D {hours:02d}H", "LEFT"
    if hours >= 1:
        return f"{hours}H {minutes:02d}M", "LEFT"
    return f"{minutes}M", "LEFT"


class CountdownScreen:
    name = "countdown"

    def __init__(self, target: CountdownTarget, theme: Theme | None = None) -> None:
        self.target = target
        self.theme = theme or theme_for("normal")
        self.name = f"countdown:{target.label}"
        self._last: Image.Image | None = None

    def render(self) -> Image.Image:
        try:
            img = self._paint()
            self._last = img.copy()
            return img
        except Exception:
            logger.exception("Countdown render failed for %s", self.target.label)
            if self._last is not None:
                return self._last
            return error_frame("CD")

    def _paint(self) -> Image.Image:
        now = datetime.now(timezone.utc)
        target = _parse_target(self.target.at)
        remaining = (target - now).total_seconds()
        primary, secondary = _format_remaining(remaining)

        if remaining <= 0:
            accent = GREEN
        elif remaining < 86400:
            accent = RED
        elif remaining < 7 * 86400:
            accent = ORANGE
        else:
            accent = PURPLE

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

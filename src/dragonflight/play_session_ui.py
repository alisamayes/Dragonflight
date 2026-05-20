"""Shared Pygame drawing helpers for the play session shell.

Primitives used by the main session loop, map editor chrome, and side panels.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

import pygame

from .dragon_ui_theme import DragonUITheme

# --- Palette (shared across session screens) --------------------------------

_UI_BORDER_RGB: tuple[int, int, int] = (85, 90, 110)
_UI_TEXT_RGB: tuple[int, int, int] = (235, 235, 245)
_UI_MUTED_TEXT_RGB: tuple[int, int, int] = (175, 175, 190)
_UI_BUTTON_RGB: tuple[int, int, int] = (60, 66, 86)
_UI_BUTTON_HOVER_RGB: tuple[int, int, int] = (74, 82, 108)
_UI_BUTTON_ACTIVE_RGB: tuple[int, int, int] = (96, 106, 140)

# Full palette for screens that import this module only
_UI_BG_RGB: tuple[int, int, int] = (30, 32, 40)
_UI_PANEL_RGB: tuple[int, int, int] = (38, 41, 52)
_UI_INPUT_RGB: tuple[int, int, int] = (22, 24, 32)
_UI_INPUT_FOCUS_RGB: tuple[int, int, int] = (28, 30, 40)
_UI_DAMAGE_PREVIEW_RGB: tuple[int, int, int] = (200, 95, 95)


def max_text_pixel_width(font: pygame.font.Font, lines: tuple[str, ...]) -> int:
    return max((font.size(line)[0] for line in lines), default=0)


def draw_text(
    surface: pygame.Surface,
    font: pygame.font.Font,
    text: str,
    pos: tuple[int, int],
    rgb: tuple[int, int, int] = _UI_TEXT_RGB,
) -> None:
    surface.blit(font.render(text, True, rgb), pos)


def draw_button(
    surface: pygame.Surface,
    font: pygame.font.Font,
    rect: pygame.Rect,
    label: str,
    *,
    hovered: bool = False,
    active: bool = False,
    border_rgb: tuple[int, int, int] = _UI_BORDER_RGB,
) -> None:
    fill = (
        _UI_BUTTON_ACTIVE_RGB if active else (_UI_BUTTON_HOVER_RGB if hovered else _UI_BUTTON_RGB)
    )
    pygame.draw.rect(surface, fill, rect, border_radius=6)
    pygame.draw.rect(surface, border_rgb, rect, width=1, border_radius=6)
    text_surf = font.render(label, True, _UI_TEXT_RGB)
    tx = rect.x + (rect.w - text_surf.get_width()) // 2
    ty = rect.y + (rect.h - text_surf.get_height()) // 2
    surface.blit(text_surf, (tx, ty))


def draw_info_panel_chrome(
    surface: pygame.Surface,
    panel_rect: pygame.Rect,
    *,
    theme: DragonUITheme,
    stripe_edge: Literal["left", "right"],
) -> None:
    """Paint panel fill + pale border + thin dragon-accent edge stripe."""

    pygame.draw.rect(surface, theme.panel_tint_rgb, panel_rect)
    pygame.draw.rect(surface, theme.border_rgb, panel_rect, width=1)
    stripe_w = 4
    stripe_x = panel_rect.left if stripe_edge == "left" else panel_rect.right - stripe_w
    stripe = pygame.Rect(stripe_x, panel_rect.top, stripe_w, panel_rect.height)
    pygame.draw.rect(surface, theme.accent_rgb, stripe)


def wrap_text_to_width(font: pygame.font.Font, text: str, max_width: int) -> list[str]:
    words = text.split()
    lines: list[str] = []
    current = ""
    for word in words:
        trial = word if not current else f"{current} {word}"
        if font.size(trial)[0] <= max_width:
            current = trial
            continue
        if current:
            lines.append(current)
        current = word
    if current:
        lines.append(current)
    return lines


def clamp_panel_scroll(scroll_y: int, content_height: int, viewport_h: int) -> int:
    return max(0, min(int(scroll_y), max(0, content_height - viewport_h)))


@dataclass
class ScrollPanelLayout:
    """Content-layout helper for a clipped, vertically scrollable side panel."""

    panel_rect: pygame.Rect
    scroll_y: int
    pad: int = 12
    content_y: int = 0
    _clip_prev: pygame.Rect | None = None

    @property
    def x(self) -> int:
        return self.panel_rect.x + self.pad

    @property
    def inner_w(self) -> int:
        return max(1, self.panel_rect.w - 2 * self.pad)

    @property
    def viewport_h(self) -> int:
        return max(1, self.panel_rect.h - 2 * self.pad)

    def content_height_total(self) -> int:
        return self.content_y

    def max_scroll(self) -> int:
        return max(0, self.content_y - self.viewport_h)

    def screen_y(self, at_content_y: int | None = None) -> int:
        cy = self.content_y if at_content_y is None else at_content_y
        return self.panel_rect.y + self.pad + cy - self.scroll_y

    def is_visible(self, height: int, *, at_content_y: int | None = None) -> bool:
        sy = self.screen_y(at_content_y)
        return sy + height > self.panel_rect.top and sy < self.panel_rect.bottom

    def begin(self, surface: pygame.Surface) -> None:
        self.content_y = 0
        self._clip_prev = surface.get_clip()
        surface.set_clip(self.panel_rect)

    def end(self, surface: pygame.Surface) -> None:
        if self._clip_prev is not None:
            surface.set_clip(self._clip_prev)

    def advance(self, dy: int) -> None:
        self.content_y += dy


def draw_panel_scrollbar(
    surface: pygame.Surface,
    panel_rect: pygame.Rect,
    *,
    scroll_y: int,
    content_height: int,
    pad: int = 12,
    border_rgb: tuple[int, int, int] = _UI_BORDER_RGB,
) -> None:
    viewport_h = max(1, panel_rect.h - 2 * pad)
    max_scroll = max(0, content_height - viewport_h)
    if max_scroll <= 0:
        return
    track = pygame.Rect(panel_rect.right - 7, panel_rect.y + pad, 4, viewport_h)
    pygame.draw.rect(surface, border_rgb, track, border_radius=2)
    thumb_h = max(24, int(viewport_h * viewport_h / max(content_height, 1)))
    thumb_y = panel_rect.y + pad + int((viewport_h - thumb_h) * scroll_y / max_scroll)
    thumb = pygame.Rect(track.x, thumb_y, track.w, thumb_h)
    pygame.draw.rect(surface, _UI_MUTED_TEXT_RGB, thumb, border_radius=2)

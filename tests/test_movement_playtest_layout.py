"""Layout invariants for the movement playtest three-column HUD."""

from __future__ import annotations

import os
from collections.abc import Iterator

# Headless-friendly for CI / agents without a display.
os.environ.setdefault("SDL_VIDEODRIVER", "dummy")

import pygame
import pytest

from dragonflight.movement_playtest import (
    GAMEPLAY_MIN_MAP_VIEWPORT_H,
    GAMEPLAY_MIN_MAP_VIEWPORT_W,
    GAMEPLAY_PANEL_SPLITTER_HIT_HALFWIDTH,
    INSPECTOR_PANEL_MIN_WIDTH_FLOOR_PX,
    INSPECTOR_PANEL_MIN_WIDTH_SCALE_DEN,
    INSPECTOR_PANEL_MIN_WIDTH_SCALE_NUM,
    SETTINGS_BAR_HEIGHT,
    TIME_BAR_HEIGHT,
    _inspector_panel_raw_min_column_width,
    _map_viewport_rect,
    _min_dragon_panel_column_width,
    _min_inspector_panel_column_width,
    clamp_gameplay_side_panel_widths,
    hit_test_gameplay_panel_splitter,
)


@pytest.fixture(scope="module", autouse=True)
def _pygame_font_module() -> Iterator[None]:
    pygame.init()
    pygame.font.init()
    yield
    pygame.quit()


def test_map_viewport_rect_fills_space_between_panels() -> None:
    client_w, client_h = 1000, 700
    lw, rw = 211, 199
    vp = _map_viewport_rect(
        client_w,
        client_h,
        dragon_panel_w=lw,
        inspector_panel_w=rw,
    )
    assert vp.x == lw
    assert vp.y == TIME_BAR_HEIGHT
    assert vp.w == client_w - lw - rw
    assert vp.h == client_h - TIME_BAR_HEIGHT - SETTINGS_BAR_HEIGHT
    assert vp.right == client_w - rw


def test_map_viewport_does_not_overlap_side_columns() -> None:
    client_w, client_h = 900, 600
    lw, rw = 200, 220
    map_row_top = TIME_BAR_HEIGHT
    map_row_h = client_h - TIME_BAR_HEIGHT - SETTINGS_BAR_HEIGHT
    dragon_col = pygame.Rect(0, map_row_top, lw, map_row_h)
    inspector_col = pygame.Rect(client_w - rw, map_row_top, rw, map_row_h)
    vp = _map_viewport_rect(
        client_w,
        client_h,
        dragon_panel_w=lw,
        inspector_panel_w=rw,
    )
    assert dragon_col.right == vp.left
    assert inspector_col.left == vp.right
    assert not vp.colliderect(dragon_col)
    assert not vp.colliderect(inspector_col)


def test_font_metric_column_widths_are_positive_and_wide_enough() -> None:
    font = pygame.font.SysFont(None, 20)
    font_small = pygame.font.SysFont(None, 18)
    dw = _min_dragon_panel_column_width(font, font_small)
    raw_iw = _inspector_panel_raw_min_column_width(font, font_small)
    iw = _min_inspector_panel_column_width(font, font_small)
    assert dw >= 120
    assert iw >= INSPECTOR_PANEL_MIN_WIDTH_FLOOR_PX
    expected = max(
        INSPECTOR_PANEL_MIN_WIDTH_FLOOR_PX,
        raw_iw * INSPECTOR_PANEL_MIN_WIDTH_SCALE_NUM // INSPECTOR_PANEL_MIN_WIDTH_SCALE_DEN,
    )
    assert iw == expected
    assert iw < raw_iw or raw_iw <= INSPECTOR_PANEL_MIN_WIDTH_FLOOR_PX
    assert dw + iw <= 2000


def test_clamp_side_panels_keeps_map_viewport_minimum() -> None:
    d, i = clamp_gameplay_side_panel_widths(
        400,
        200,
        200,
        min_dragon=80,
        min_inspector=80,
        min_map_viewport_w=200,
    )
    assert d >= 80
    assert i >= 80
    assert d + i + 200 <= 400


def test_clamp_side_panels_when_impossibly_tight_returns_mins() -> None:
    d, i = clamp_gameplay_side_panel_widths(
        200,
        500,
        500,
        min_dragon=80,
        min_inspector=80,
        min_map_viewport_w=200,
    )
    assert (d, i) == (80, 80)


def test_hit_test_splitter_left_edge_in_map_row() -> None:
    y = TIME_BAR_HEIGHT + 10
    assert (
        hit_test_gameplay_panel_splitter(
            100,
            y,
            800,
            600,
            dragon_panel_w=100,
            inspector_panel_w=200,
        )
        == "left"
    )


def test_hit_test_splitter_right_edge() -> None:
    y = TIME_BAR_HEIGHT + 10
    assert (
        hit_test_gameplay_panel_splitter(
            800 - 200,
            y,
            800,
            600,
            dragon_panel_w=100,
            inspector_panel_w=200,
        )
        == "right"
    )


def test_hit_test_splitter_outside_map_row() -> None:
    assert (
        hit_test_gameplay_panel_splitter(
            100,
            TIME_BAR_HEIGHT - 1,
            800,
            600,
            dragon_panel_w=100,
            inspector_panel_w=200,
        )
        is None
    )


def test_hit_test_splitter_respects_halfwidth() -> None:
    y = TIME_BAR_HEIGHT + 10
    hx = 100 + GAMEPLAY_PANEL_SPLITTER_HIT_HALFWIDTH + 1
    assert (
        hit_test_gameplay_panel_splitter(
            hx,
            y,
            800,
            600,
            dragon_panel_w=100,
            inspector_panel_w=200,
        )
        is None
    )


def test_gameplay_floor_constants_sane() -> None:
    assert GAMEPLAY_MIN_MAP_VIEWPORT_W >= 64
    assert GAMEPLAY_MIN_MAP_VIEWPORT_H >= 64

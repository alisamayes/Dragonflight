"""Isometric viewport camera — zoom and pan for the preview module.

Mirrors :mod:`dragonflight.map_camera` but uses isometric footprint and extent
helpers from :mod:`isometric.isometric_render`.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Protocol

from dragonflight.map_camera import (
    MAP_EDGE_PAN_SLACK_HEX_WIDTH,
    MAP_PAN_SPEED_PX_PER_SEC,
    MAP_ZOOM_WHEEL_STEP,
    MAX_MAP_ZOOM_FACTOR,
    MIN_MAP_ZOOM_FACTOR,
    MapViewportCamera,
    _is_key_pressed,
    camera_is_pannable,
)
from dragonflight.map_state import GameMap

from .isometric_render import (
    _iso_origin_for,
    compute_iso_render_hex_size_for_canvas,
    compute_iso_window_size,
    iso_content_x_extent_rel,
    iso_content_y_extent_rel,
)


class KeyPressedLike(Protocol):
    def __getitem__(self, key: int, /) -> bool: ...


def _clamp_zoom(zoom: float) -> float:
    return max(MIN_MAP_ZOOM_FACTOR, min(MAX_MAP_ZOOM_FACTOR, zoom))


@dataclass(frozen=True, slots=True)
class ResolvedIsoMapView:
    hex_size: float
    origin_local: tuple[float, float]
    footprint: tuple[int, int]
    fit_hex_size: float


def _edge_pan_slack_px(hex_size: float) -> float:
    return MAP_EDGE_PAN_SLACK_HEX_WIDTH * hex_size


def _base_origin_with_padding(
    game_map: GameMap,
    hex_size: float,
    viewport_w: int,
    viewport_h: int,
) -> tuple[float, float, int, int]:
    map_w, map_h = compute_iso_window_size(game_map, hex_size)
    ox, oy = _iso_origin_for(game_map, hex_size)
    pad_x = max(0.0, (float(viewport_w) - float(map_w)) / 2.0)
    pad_y = max(0.0, (float(viewport_h) - float(map_h)) / 2.0)
    return ox + pad_x, oy + pad_y, map_w, map_h


def _clamp_pan(
    pan_x: float,
    pan_y: float,
    *,
    game_map: GameMap,
    viewport_w: int,
    viewport_h: int,
    map_w: int,
    map_h: int,
    base_x: float,
    base_y: float,
    hex_size: float,
) -> tuple[float, float]:
    if map_w <= viewport_w:
        pan_x = (float(viewport_w) - float(map_w)) / 2.0 - base_x
    else:
        edge_slack = _edge_pan_slack_px(hex_size)
        rel_min_x, rel_max_x = iso_content_x_extent_rel(game_map, hex_size)
        max_pan_x = edge_slack - base_x - rel_min_x
        min_pan_x = float(viewport_w) - edge_slack - base_x - rel_max_x
        pan_x = max(min_pan_x, min(max_pan_x, pan_x))

    if map_h <= viewport_h:
        pan_y = (float(viewport_h) - float(map_h)) / 2.0 - base_y
    else:
        edge_slack = _edge_pan_slack_px(hex_size)
        rel_min_y, rel_max_y = iso_content_y_extent_rel(game_map, hex_size)
        max_pan_y = edge_slack - base_y - rel_min_y
        min_pan_y = float(viewport_h) - edge_slack - base_y - rel_max_y
        pan_y = max(min_pan_y, min(max_pan_y, pan_y))

    return pan_x, pan_y


def resolve_iso_map_view(
    game_map: GameMap,
    viewport_w: int,
    viewport_h: int,
    camera: MapViewportCamera,
) -> ResolvedIsoMapView:
    fit_hex_size = compute_iso_render_hex_size_for_canvas(game_map, viewport_w, viewport_h)
    zoom_factor = _clamp_zoom(camera.zoom_factor)
    display_hex = fit_hex_size * zoom_factor
    footprint = compute_iso_window_size(game_map, display_hex)
    base_x, base_y, map_w, map_h = _base_origin_with_padding(
        game_map, display_hex, viewport_w, viewport_h
    )

    if zoom_factor <= MIN_MAP_ZOOM_FACTOR:
        pan_x, pan_y = 0.0, 0.0
    else:
        pan_x, pan_y = _clamp_pan(
            camera.pan_x,
            camera.pan_y,
            game_map=game_map,
            viewport_w=viewport_w,
            viewport_h=viewport_h,
            map_w=map_w,
            map_h=map_h,
            base_x=base_x,
            base_y=base_y,
            hex_size=display_hex,
        )

    origin_local = (base_x + pan_x, base_y + pan_y)
    return ResolvedIsoMapView(
        hex_size=display_hex,
        origin_local=origin_local,
        footprint=footprint,
        fit_hex_size=fit_hex_size,
    )


def apply_iso_wheel_zoom(
    camera: MapViewportCamera,
    game_map: GameMap,
    viewport_w: int,
    viewport_h: int,
    *,
    anchor_local: tuple[float, float],
    wheel_y: int,
) -> MapViewportCamera:
    if wheel_y == 0:
        return camera

    view_before = resolve_iso_map_view(game_map, viewport_w, viewport_h, camera)
    ax, ay = anchor_local
    map_w_before, map_h_before = view_before.footprint
    rel_x = (ax - view_before.origin_local[0]) / float(map_w_before)
    rel_y = (ay - view_before.origin_local[1]) / float(map_h_before)

    new_zoom = _clamp_zoom(camera.zoom_factor + float(wheel_y) * MAP_ZOOM_WHEEL_STEP)
    if new_zoom <= MIN_MAP_ZOOM_FACTOR:
        return MapViewportCamera()

    fit_hex_size = compute_iso_render_hex_size_for_canvas(game_map, viewport_w, viewport_h)
    display_hex = fit_hex_size * new_zoom
    base_x, base_y, map_w, map_h = _base_origin_with_padding(
        game_map, display_hex, viewport_w, viewport_h
    )
    pan_x = ax - base_x - rel_x * float(map_w)
    pan_y = ay - base_y - rel_y * float(map_h)
    pan_x, pan_y = _clamp_pan(
        pan_x,
        pan_y,
        game_map=game_map,
        viewport_w=viewport_w,
        viewport_h=viewport_h,
        map_w=map_w,
        map_h=map_h,
        base_x=base_x,
        base_y=base_y,
        hex_size=display_hex,
    )
    return MapViewportCamera(zoom_factor=new_zoom, pan_x=pan_x, pan_y=pan_y)


def apply_iso_keyboard_pan(
    camera: MapViewportCamera,
    keys_pressed: KeyPressedLike,
    dt_sec: float,
    game_map: GameMap,
    viewport_w: int,
    viewport_h: int,
) -> MapViewportCamera:
    if not camera_is_pannable(camera):
        return MapViewportCamera()

    import pygame

    dx = 0.0
    dy = 0.0
    speed = MAP_PAN_SPEED_PX_PER_SEC * dt_sec
    if _is_key_pressed(keys_pressed, pygame.K_w) or _is_key_pressed(keys_pressed, pygame.K_UP):
        dy += speed
    if _is_key_pressed(keys_pressed, pygame.K_s) or _is_key_pressed(keys_pressed, pygame.K_DOWN):
        dy -= speed
    if _is_key_pressed(keys_pressed, pygame.K_a) or _is_key_pressed(keys_pressed, pygame.K_LEFT):
        dx += speed
    if _is_key_pressed(keys_pressed, pygame.K_d) or _is_key_pressed(keys_pressed, pygame.K_RIGHT):
        dx -= speed

    if dx == 0.0 and dy == 0.0:
        return camera

    fit_hex_size = compute_iso_render_hex_size_for_canvas(game_map, viewport_w, viewport_h)
    display_hex = fit_hex_size * _clamp_zoom(camera.zoom_factor)
    base_x, base_y, map_w, map_h = _base_origin_with_padding(
        game_map, display_hex, viewport_w, viewport_h
    )
    pan_x = camera.pan_x + dx
    pan_y = camera.pan_y + dy
    pan_x, pan_y = _clamp_pan(
        pan_x,
        pan_y,
        game_map=game_map,
        viewport_w=viewport_w,
        viewport_h=viewport_h,
        map_w=map_w,
        map_h=map_h,
        base_x=base_x,
        base_y=base_y,
        hex_size=display_hex,
    )
    return replace(camera, pan_x=pan_x, pan_y=pan_y)

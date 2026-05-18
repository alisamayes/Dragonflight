"""Map viewport camera — zoom and pan for the gameplay map column.

Presentation-only: fits and scales the rendered map inside the central viewport
without touching simulation state. Hex sizing delegates to ``render`` helpers;
this module owns zoom factor, pan offsets, and clamping.

Wired from :mod:`dragonflight.movement_playtest` on the central map column:
mouse wheel zoom (1×–3×, cursor-anchored) and WASD / arrow pan while zoomed in.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, replace
from typing import Protocol

from .hex_coord import HEX_CORNERS, hex_corner_offset, offset_to_pixel
from .map_state import GameMap
from .render import MARGIN_PX, compute_render_hex_size_for_canvas, compute_window_size

#: Maximum zoom multiplier relative to the fit-to-viewport hex size.
MAX_MAP_ZOOM_FACTOR: float = 3.0
#: Minimum zoom (1× = entire map visible in the viewport).
MIN_MAP_ZOOM_FACTOR: float = 1.0
#: Zoom delta per mouse-wheel notch (added to ``zoom_factor`` before clamping).
MAP_ZOOM_WHEEL_STEP: float = 0.12
#: Keyboard pan speed in viewport pixels per second.
MAP_PAN_SPEED_PX_PER_SEC: float = 480.0
#: Extra horizontal pan slack in hex radii (flat-top corner overhang past footprint).
MAP_EDGE_PAN_SLACK_HEX_WIDTH: float = 1.0

_SQRT3: float = math.sqrt(3.0)


class KeyPressedLike(Protocol):
    """Key state indexed by ``pygame`` key constants (e.g. ``key.get_pressed()``)."""

    def __getitem__(self, key: int, /) -> bool: ...


@dataclass(slots=True)
class MapViewportCamera:
    """Session camera state for the gameplay map viewport.

    Attributes:
        zoom_factor: Multiplier on the fit-to-viewport hex size (clamped to
            ``MIN_MAP_ZOOM_FACTOR``–``MAX_MAP_ZOOM_FACTOR``).
        pan_x: Horizontal pan offset in viewport-local pixels (ignored at 1×).
        pan_y: Vertical pan offset in viewport-local pixels (ignored at 1×).
    """

    zoom_factor: float = 1.0
    pan_x: float = 0.0
    pan_y: float = 0.0


@dataclass(frozen=True, slots=True)
class ResolvedMapView:
    """Draw parameters for one map viewport frame.

    Attributes:
        hex_size: Render hex radius after zoom (``fit_hex_size * zoom_factor``).
        origin_local: Top-left of the map footprint in viewport-local pixels.
        footprint: ``(width_px, height_px)`` of the scaled map bitmap.
        fit_hex_size: Hex radius that fits the map in the viewport at 1× zoom.
    """

    hex_size: float
    origin_local: tuple[float, float]
    footprint: tuple[int, int]
    fit_hex_size: float


def camera_is_pannable(camera: MapViewportCamera) -> bool:
    """Return whether keyboard pan is allowed (zoomed past full fit).

    Args:
        camera: Current session camera.

    Returns:
        ``True`` when ``zoom_factor`` is above ``MIN_MAP_ZOOM_FACTOR``.
    """

    return camera.zoom_factor > MIN_MAP_ZOOM_FACTOR


def _clamp_zoom(zoom: float) -> float:
    return max(MIN_MAP_ZOOM_FACTOR, min(MAX_MAP_ZOOM_FACTOR, zoom))


def _edge_pan_slack_px(hex_size: float) -> float:
    """Extra pan slack at all edges for hex corner overhang past footprint."""

    return MAP_EDGE_PAN_SLACK_HEX_WIDTH * hex_size


def _is_key_pressed(keys_pressed: KeyPressedLike, key: int) -> bool:
    """Return whether ``key`` is down; tolerate short test key arrays."""

    try:
        return bool(keys_pressed[key])
    except IndexError:
        return False


def _offset_extent(game_map: GameMap) -> tuple[int, int, int, int]:
    if not game_map.tiles:
        return 0, 0, 0, 0
    cols = [coord.col for coord in game_map.tiles]
    rows = [coord.row for coord in game_map.tiles]
    return min(cols), max(cols), min(rows), max(rows)


def _content_x_extent_rel(game_map: GameMap, hex_size: float) -> tuple[float, float]:
    """Min/max screen-x of hex corners relative to the map render origin.

    Matches :func:`~dragonflight.render.render_map`: screen x =
    ``origin_x + rel`` for each corner at
    ``offset_to_pixel(coord, hex_size).x + hex_corner_offset(...).x``.
    """

    if not game_map.tiles:
        return 0.0, 0.0
    rel_min_x = float("inf")
    rel_max_x = float("-inf")
    for tile in game_map:
        cx_off, _ = offset_to_pixel(tile.coord, hex_size)
        for corner in range(HEX_CORNERS):
            dx, _ = hex_corner_offset(hex_size, corner)
            x = cx_off + dx
            rel_min_x = min(rel_min_x, x)
            rel_max_x = max(rel_max_x, x)
    return rel_min_x, rel_max_x


def _content_y_extent_rel(game_map: GameMap, hex_size: float) -> tuple[float, float]:
    """Min/max screen-y of hex corners relative to the map render origin.

    Matches :func:`~dragonflight.render.render_map`: screen y =
    ``origin_y + rel`` for each corner at
    ``offset_to_pixel(coord, hex_size).y + hex_corner_offset(...).y``.
    """

    if not game_map.tiles:
        return 0.0, 0.0
    rel_min_y = float("inf")
    rel_max_y = float("-inf")
    for tile in game_map:
        _, cy_off = offset_to_pixel(tile.coord, hex_size)
        for corner in range(HEX_CORNERS):
            _, dy = hex_corner_offset(hex_size, corner)
            y = cy_off + dy
            rel_min_y = min(rel_min_y, y)
            rel_max_y = max(rel_max_y, y)
    return rel_min_y, rel_max_y


def _map_origin_for_hex_size(game_map: GameMap, hex_size: float) -> tuple[float, float]:
    """Pixel offset for ``OffsetCoord(0, 0)`` — mirrors ``render._origin_for``."""

    col_min, _, row_min, _ = _offset_extent(game_map)
    min_centre_x = hex_size * 1.5 * col_min
    parity_shift = 0.5 * (col_min & 1)
    min_centre_y = hex_size * _SQRT3 * (row_min + parity_shift)
    origin_x = MARGIN_PX + hex_size - min_centre_x
    origin_y = MARGIN_PX + hex_size * _SQRT3 / 2.0 - min_centre_y
    return origin_x, origin_y


def _base_origin_with_padding(
    game_map: GameMap,
    hex_size: float,
    viewport_w: int,
    viewport_h: int,
) -> tuple[float, float, int, int]:
    map_w, map_h = compute_window_size(game_map, hex_size)
    ox, oy = _map_origin_for_hex_size(game_map, hex_size)
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
    """Keep visible map content from scrolling empty space into the viewport."""

    if map_w <= viewport_w:
        pan_x = (float(viewport_w) - float(map_w)) / 2.0 - base_x
    else:
        edge_slack = _edge_pan_slack_px(hex_size)
        rel_min_x, rel_max_x = _content_x_extent_rel(game_map, hex_size)
        max_pan_x = edge_slack - base_x - rel_min_x
        min_pan_x = float(viewport_w) - edge_slack - base_x - rel_max_x
        pan_x = max(min_pan_x, min(max_pan_x, pan_x))

    if map_h <= viewport_h:
        pan_y = (float(viewport_h) - float(map_h)) / 2.0 - base_y
    else:
        edge_slack = _edge_pan_slack_px(hex_size)
        rel_min_y, rel_max_y = _content_y_extent_rel(game_map, hex_size)
        max_pan_y = edge_slack - base_y - rel_min_y
        min_pan_y = float(viewport_h) - edge_slack - base_y - rel_max_y
        pan_y = max(min_pan_y, min(max_pan_y, pan_y))

    return pan_x, pan_y


def resolve_map_view(
    game_map: GameMap,
    viewport_w: int,
    viewport_h: int,
    camera: MapViewportCamera,
) -> ResolvedMapView:
    """Resolve hex size, local origin, and footprint for the current camera.

    At minimum zoom, pan is forced to zero so the map stays centered.

    Args:
        game_map: Map being drawn.
        viewport_w: Central map column width in pixels.
        viewport_h: Central map column height in pixels.
        camera: Session camera (zoom and pan).

    Returns:
        Clamped draw parameters for this frame.
    """

    fit_hex_size = compute_render_hex_size_for_canvas(game_map, viewport_w, viewport_h)
    zoom_factor = _clamp_zoom(camera.zoom_factor)
    display_hex = fit_hex_size * zoom_factor
    footprint = compute_window_size(game_map, display_hex)
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
    return ResolvedMapView(
        hex_size=display_hex,
        origin_local=origin_local,
        footprint=footprint,
        fit_hex_size=fit_hex_size,
    )


def apply_wheel_zoom(
    camera: MapViewportCamera,
    game_map: GameMap,
    viewport_w: int,
    viewport_h: int,
    *,
    anchor_local: tuple[float, float],
    wheel_y: int,
) -> MapViewportCamera:
    """Apply a mouse-wheel step with cursor-anchored zoom.

    The point under ``anchor_local`` stays fixed on screen when zoom changes.
    Zooming out to 1× resets pan and returns a default camera.

    Args:
        camera: Current session camera.
        game_map: Map being drawn.
        viewport_w: Central map column width in pixels.
        viewport_h: Central map column height in pixels.
        anchor_local: Cursor position in viewport-local pixels.
        wheel_y: Wheel delta from ``pygame.MOUSEWHEEL`` (``event.y``; positive
            zooms in).

    Returns:
        Updated camera, or ``camera`` unchanged when ``wheel_y == 0``.
    """

    if wheel_y == 0:
        return camera

    view_before = resolve_map_view(game_map, viewport_w, viewport_h, camera)
    ax, ay = anchor_local
    map_w_before, map_h_before = view_before.footprint
    # Normalized position under the cursor — kept stable across zoom changes.
    rel_x = (ax - view_before.origin_local[0]) / float(map_w_before)
    rel_y = (ay - view_before.origin_local[1]) / float(map_h_before)

    new_zoom = _clamp_zoom(camera.zoom_factor + float(wheel_y) * MAP_ZOOM_WHEEL_STEP)
    if new_zoom <= MIN_MAP_ZOOM_FACTOR:
        return MapViewportCamera()

    fit_hex_size = compute_render_hex_size_for_canvas(game_map, viewport_w, viewport_h)
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


def apply_zoom_step(
    camera: MapViewportCamera,
    game_map: GameMap,
    viewport_w: int,
    viewport_h: int,
    *,
    anchor_local: tuple[float, float],
    direction: int,
) -> MapViewportCamera:
    """Apply one discrete zoom step (same delta as one wheel notch).

    Args:
        camera: Current session camera.
        game_map: Map being drawn.
        viewport_w: Central map column width in pixels.
        viewport_h: Central map column height in pixels.
        anchor_local: Anchor in viewport-local pixels (e.g. viewport center).
        direction: ``+1`` zooms in, ``-1`` zooms out.

    Returns:
        Updated camera, or ``camera`` unchanged when ``direction == 0``.
    """

    if direction == 0:
        return camera
    return apply_wheel_zoom(
        camera,
        game_map,
        viewport_w,
        viewport_h,
        anchor_local=anchor_local,
        wheel_y=direction,
    )


def apply_keyboard_pan(
    camera: MapViewportCamera,
    keys_pressed: KeyPressedLike,
    dt_sec: float,
    game_map: GameMap,
    viewport_w: int,
    viewport_h: int,
) -> MapViewportCamera:
    """Pan the camera with WASD / arrow keys when zoomed in.

    At 1× zoom, returns a reset camera (same as wheel zoom-out). Movement uses
    ``MAP_PAN_SPEED_PX_PER_SEC``; pan is clamped so the map never leaves empty
    margins inside the viewport.

    Args:
        camera: Current session camera.
        keys_pressed: Boolean sequence indexed by ``pygame`` key constants
            (e.g. ``pygame.key.get_pressed()``).
        dt_sec: Frame delta in seconds.
        game_map: Map being drawn.
        viewport_w: Central map column width in pixels.
        viewport_h: Central map column height in pixels.

    Returns:
        Updated camera, or ``camera`` unchanged when no pan keys are held.
    """

    if not camera_is_pannable(camera):
        return MapViewportCamera()

    # Import here so unit tests avoid initializing pygame.
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

    fit_hex_size = compute_render_hex_size_for_canvas(game_map, viewport_w, viewport_h)
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

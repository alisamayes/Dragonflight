"""Unit tests for ``dragonflight.map_camera`` (no Pygame display)."""

from __future__ import annotations

from pathlib import Path

import pytest

from dragonflight.hex_coord import OffsetCoord
from dragonflight.map_camera import (
    MAP_EDGE_PAN_SLACK_HEX_WIDTH,
    MAP_ZOOM_WHEEL_STEP,
    MAX_MAP_ZOOM_FACTOR,
    MIN_MAP_ZOOM_FACTOR,
    MapViewportCamera,
    _content_x_extent_rel,
    _content_y_extent_rel,
    apply_keyboard_pan,
    apply_wheel_zoom,
    apply_zoom_step,
    camera_is_pannable,
    resolve_map_view,
)
from dragonflight.map_loader import load_map
from dragonflight.map_state import GameMap, Tile
from dragonflight.render import compute_window_size, layout_map_on_canvas
from dragonflight.terrain import Terrain

_EXAMPLE_MAP_PATH: Path = Path(__file__).resolve().parent.parent / "assets" / "example_hexmap.json"


@pytest.fixture(scope="module")
def example_map() -> GameMap:
    return load_map(_EXAMPLE_MAP_PATH)


@pytest.fixture
def small_map() -> GameMap:
    tiles = {
        OffsetCoord(col, 0): Tile(coord=OffsetCoord(col, 0), terrain=Terrain.GRASSLAND)
        for col in range(12)
    }
    return GameMap(
        width=12,
        height=1,
        hex_size=10.0,
        orientation="flat",
        tiles=tiles,
    )


class TestResolveMapView:
    def test_display_hex_equals_fit_times_zoom(self, example_map: GameMap) -> None:
        viewport_w, viewport_h = 640, 480
        camera = MapViewportCamera(zoom_factor=2.0)
        view = resolve_map_view(example_map, viewport_w, viewport_h, camera)
        assert view.hex_size == pytest.approx(view.fit_hex_size * 2.0)

    def test_zoom_clamps_to_max(self, example_map: GameMap) -> None:
        view = resolve_map_view(
            example_map,
            640,
            480,
            MapViewportCamera(zoom_factor=99.0),
        )
        assert view.hex_size == pytest.approx(view.fit_hex_size * MAX_MAP_ZOOM_FACTOR)

    def test_zoom_clamps_to_min(self, example_map: GameMap) -> None:
        view = resolve_map_view(
            example_map,
            640,
            480,
            MapViewportCamera(zoom_factor=0.1),
        )
        assert view.hex_size == pytest.approx(view.fit_hex_size * MIN_MAP_ZOOM_FACTOR)

    def test_pan_zeroed_at_minimum_zoom(self, example_map: GameMap) -> None:
        camera = MapViewportCamera(zoom_factor=1.0, pan_x=120.0, pan_y=-80.0)
        view = resolve_map_view(example_map, 640, 480, camera)
        fit_hex, fit_origin, _ = layout_map_on_canvas(example_map, 640, 480)
        assert view.hex_size == pytest.approx(fit_hex)
        assert view.origin_local == pytest.approx(fit_origin)

    def test_footprint_monotonic_with_zoom(self, example_map: GameMap) -> None:
        viewport = (720, 520)
        footprints: list[int] = []
        for zoom in (1.0, 1.5, 2.0, 3.0):
            view = resolve_map_view(
                example_map,
                viewport[0],
                viewport[1],
                MapViewportCamera(zoom_factor=zoom),
            )
            footprints.append(view.footprint[0] * view.footprint[1])
        assert footprints == sorted(footprints)
        assert footprints[0] < footprints[-1]

    def test_footprint_matches_compute_window_size(self, example_map: GameMap) -> None:
        view = resolve_map_view(example_map, 800, 600, MapViewportCamera(zoom_factor=1.75))
        assert view.footprint == compute_window_size(example_map, view.hex_size)


class TestCameraIsPannable:
    def test_not_pannable_at_fit(self) -> None:
        assert not camera_is_pannable(MapViewportCamera(zoom_factor=1.0))

    def test_pannable_when_zoomed(self) -> None:
        assert camera_is_pannable(MapViewportCamera(zoom_factor=1.01))


def _content_x_bounds(
    game_map: GameMap,
    view_origin_x: float,
    hex_size: float,
) -> tuple[float, float]:
    rel_min_x, rel_max_x = _content_x_extent_rel(game_map, hex_size)
    return view_origin_x + rel_min_x, view_origin_x + rel_max_x


def _content_y_bounds(
    game_map: GameMap,
    view_origin_y: float,
    hex_size: float,
) -> tuple[float, float]:
    rel_min_y, rel_max_y = _content_y_extent_rel(game_map, hex_size)
    return view_origin_y + rel_min_y, view_origin_y + rel_max_y


def _assert_content_west_pan_slack(
    game_map: GameMap,
    view,
    *,
    edge_slack: float,
) -> None:
    content_min_x, _ = _content_x_bounds(game_map, view.origin_local[0], view.hex_size)
    assert content_min_x >= edge_slack - 0.5


def _assert_content_east_pan_slack(
    game_map: GameMap,
    view,
    *,
    viewport_w: int,
    edge_slack: float,
) -> None:
    _, content_max_x = _content_x_bounds(game_map, view.origin_local[0], view.hex_size)
    assert content_max_x <= float(viewport_w) - edge_slack + 0.5


def _assert_content_north_pan_slack(
    game_map: GameMap,
    view,
    *,
    edge_slack: float,
) -> None:
    content_min_y, _ = _content_y_bounds(game_map, view.origin_local[1], view.hex_size)
    assert content_min_y >= edge_slack - 0.5


def _assert_content_south_pan_slack(
    game_map: GameMap,
    view,
    *,
    viewport_h: int,
    edge_slack: float,
) -> None:
    _, content_max_y = _content_y_bounds(game_map, view.origin_local[1], view.hex_size)
    assert content_max_y <= float(viewport_h) - edge_slack + 0.5


class TestPanClamping:
    def test_pan_stays_within_content_bounds_when_zoomed(self, small_map: GameMap) -> None:
        viewport_w, viewport_h = 200, 120
        base_view = resolve_map_view(
            small_map, viewport_w, viewport_h, MapViewportCamera(zoom_factor=3.0)
        )
        map_w, map_h = base_view.footprint
        edge_slack = MAP_EDGE_PAN_SLACK_HEX_WIDTH * base_view.hex_size

        extreme_west = MapViewportCamera(zoom_factor=3.0, pan_x=10_000.0, pan_y=0.0)
        extreme_east = MapViewportCamera(zoom_factor=3.0, pan_x=-10_000.0, pan_y=0.0)
        extreme_north = MapViewportCamera(zoom_factor=3.0, pan_x=0.0, pan_y=10_000.0)
        extreme_south = MapViewportCamera(zoom_factor=3.0, pan_x=0.0, pan_y=-10_000.0)
        west = resolve_map_view(small_map, viewport_w, viewport_h, extreme_west)
        east = resolve_map_view(small_map, viewport_w, viewport_h, extreme_east)
        north = resolve_map_view(small_map, viewport_w, viewport_h, extreme_north)
        south = resolve_map_view(small_map, viewport_w, viewport_h, extreme_south)

        if map_w > viewport_w:
            _assert_content_west_pan_slack(small_map, west, edge_slack=edge_slack)
            _assert_content_east_pan_slack(
                small_map, east, viewport_w=viewport_w, edge_slack=edge_slack
            )
        if map_h > viewport_h:
            _assert_content_north_pan_slack(small_map, north, edge_slack=edge_slack)
            _assert_content_south_pan_slack(
                small_map, south, viewport_h=viewport_h, edge_slack=edge_slack
            )

    def test_content_pan_slack_symmetric_at_max_zoom(self, small_map: GameMap) -> None:
        viewport_w, viewport_h = 200, 120
        zoom = MAX_MAP_ZOOM_FACTOR
        base_view = resolve_map_view(
            small_map, viewport_w, viewport_h, MapViewportCamera(zoom_factor=zoom)
        )
        edge_slack = MAP_EDGE_PAN_SLACK_HEX_WIDTH * base_view.hex_size

        max_west = resolve_map_view(
            small_map,
            viewport_w,
            viewport_h,
            MapViewportCamera(zoom_factor=zoom, pan_x=1_000_000.0),
        )
        max_east = resolve_map_view(
            small_map,
            viewport_w,
            viewport_h,
            MapViewportCamera(zoom_factor=zoom, pan_x=-1_000_000.0),
        )
        max_north = resolve_map_view(
            small_map,
            viewport_w,
            viewport_h,
            MapViewportCamera(zoom_factor=zoom, pan_y=1_000_000.0),
        )
        max_south = resolve_map_view(
            small_map,
            viewport_w,
            viewport_h,
            MapViewportCamera(zoom_factor=zoom, pan_y=-1_000_000.0),
        )
        _assert_content_west_pan_slack(small_map, max_west, edge_slack=edge_slack)
        _assert_content_east_pan_slack(
            small_map, max_east, viewport_w=viewport_w, edge_slack=edge_slack
        )
        west_min, _ = _content_x_bounds(small_map, max_west.origin_local[0], max_west.hex_size)
        _, east_max = _content_x_bounds(small_map, max_east.origin_local[0], max_east.hex_size)
        assert west_min == pytest.approx(edge_slack, abs=0.5)
        assert east_max == pytest.approx(float(viewport_w) - edge_slack, abs=0.5)
        if base_view.footprint[1] > viewport_h:
            _assert_content_north_pan_slack(small_map, max_north, edge_slack=edge_slack)
            _assert_content_south_pan_slack(
                small_map, max_south, viewport_h=viewport_h, edge_slack=edge_slack
            )
            north_min, _ = _content_y_bounds(
                small_map, max_north.origin_local[1], max_north.hex_size
            )
            _, south_max = _content_y_bounds(
                small_map, max_south.origin_local[1], max_south.hex_size
            )
            assert north_min == pytest.approx(edge_slack, abs=0.5)
            assert south_max == pytest.approx(float(viewport_h) - edge_slack, abs=0.5)

    def test_content_pan_slack_symmetric_on_example_map(self, example_map: GameMap) -> None:
        viewport_w, viewport_h = 800, 600
        zoom = MAX_MAP_ZOOM_FACTOR
        base_view = resolve_map_view(
            example_map, viewport_w, viewport_h, MapViewportCamera(zoom_factor=zoom)
        )
        edge_slack = MAP_EDGE_PAN_SLACK_HEX_WIDTH * base_view.hex_size

        max_west = resolve_map_view(
            example_map,
            viewport_w,
            viewport_h,
            MapViewportCamera(zoom_factor=zoom, pan_x=1_000_000.0),
        )
        max_east = resolve_map_view(
            example_map,
            viewport_w,
            viewport_h,
            MapViewportCamera(zoom_factor=zoom, pan_x=-1_000_000.0),
        )
        max_north = resolve_map_view(
            example_map,
            viewport_w,
            viewport_h,
            MapViewportCamera(zoom_factor=zoom, pan_y=1_000_000.0),
        )
        max_south = resolve_map_view(
            example_map,
            viewport_w,
            viewport_h,
            MapViewportCamera(zoom_factor=zoom, pan_y=-1_000_000.0),
        )
        _assert_content_west_pan_slack(example_map, max_west, edge_slack=edge_slack)
        _assert_content_east_pan_slack(
            example_map, max_east, viewport_w=viewport_w, edge_slack=edge_slack
        )
        _assert_content_north_pan_slack(example_map, max_north, edge_slack=edge_slack)
        _assert_content_south_pan_slack(
            example_map, max_south, viewport_h=viewport_h, edge_slack=edge_slack
        )
        north_min, _ = _content_y_bounds(example_map, max_north.origin_local[1], max_north.hex_size)
        _, south_max = _content_y_bounds(example_map, max_south.origin_local[1], max_south.hex_size)
        assert north_min == pytest.approx(edge_slack, abs=0.5)
        assert south_max == pytest.approx(float(viewport_h) - edge_slack, abs=0.5)

    def test_keyboard_pan_noop_at_fit(self, example_map: GameMap) -> None:
        keys = _keys_with_wasd()
        before = MapViewportCamera()
        after = apply_keyboard_pan(before, keys, 0.1, example_map, 640, 480)
        assert after == MapViewportCamera()

    def test_keyboard_pan_w_moves_view_up(self, example_map: GameMap) -> None:
        import pygame

        viewport_w, viewport_h = 640, 480
        keys = _TestKeysPressed(frozenset({pygame.K_w}))
        camera = MapViewportCamera(zoom_factor=3.0, pan_x=-50.0, pan_y=-80.0)
        before = resolve_map_view(example_map, viewport_w, viewport_h, camera)
        after_cam = apply_keyboard_pan(camera, keys, 0.25, example_map, viewport_w, viewport_h)
        after = resolve_map_view(example_map, viewport_w, viewport_h, after_cam)
        assert after.origin_local[1] > before.origin_local[1]

    def test_keyboard_pan_s_moves_view_down(self, example_map: GameMap) -> None:
        import pygame

        viewport_w, viewport_h = 640, 480
        keys = _TestKeysPressed(frozenset({pygame.K_s}))
        camera = MapViewportCamera(zoom_factor=3.0, pan_x=-50.0, pan_y=-80.0)
        before = resolve_map_view(example_map, viewport_w, viewport_h, camera)
        after_cam = apply_keyboard_pan(camera, keys, 0.25, example_map, viewport_w, viewport_h)
        after = resolve_map_view(example_map, viewport_w, viewport_h, after_cam)
        assert after.origin_local[1] < before.origin_local[1]


class TestWheelZoom:
    def test_wheel_anchor_stability(self, small_map: GameMap) -> None:
        viewport_w, viewport_h = 200, 120
        camera = MapViewportCamera(zoom_factor=2.0)
        anchor = (viewport_w / 2.0, viewport_h / 2.0)
        before = resolve_map_view(small_map, viewport_w, viewport_h, camera)
        map_w_before, map_h_before = before.footprint
        rel = (
            (anchor[0] - before.origin_local[0]) / map_w_before,
            (anchor[1] - before.origin_local[1]) / map_h_before,
        )

        zoomed = apply_wheel_zoom(
            camera,
            small_map,
            viewport_w,
            viewport_h,
            anchor_local=anchor,
            wheel_y=1,
        )
        after = resolve_map_view(small_map, viewport_w, viewport_h, zoomed)
        map_w_after, map_h_after = after.footprint
        assert after.origin_local[0] + rel[0] * map_w_after == pytest.approx(anchor[0], abs=0.5)
        assert after.origin_local[1] + rel[1] * map_h_after == pytest.approx(anchor[1], abs=0.5)

    def test_wheel_zoom_out_clamps_to_fit(self, example_map: GameMap) -> None:
        camera = MapViewportCamera(zoom_factor=MIN_MAP_ZOOM_FACTOR + MAP_ZOOM_WHEEL_STEP)
        out = apply_wheel_zoom(
            camera,
            example_map,
            640,
            480,
            anchor_local=(320.0, 240.0),
            wheel_y=-1,
        )
        assert out.zoom_factor == MIN_MAP_ZOOM_FACTOR
        assert out.pan_x == 0.0
        assert out.pan_y == 0.0


class TestZoomStep:
    def test_zoom_step_in_matches_wheel(self, small_map: GameMap) -> None:
        viewport_w, viewport_h = 200, 120
        camera = MapViewportCamera(zoom_factor=2.0)
        anchor = (viewport_w / 2.0, viewport_h / 2.0)
        stepped = apply_zoom_step(
            camera,
            small_map,
            viewport_w,
            viewport_h,
            anchor_local=anchor,
            direction=1,
        )
        wheeled = apply_wheel_zoom(
            camera,
            small_map,
            viewport_w,
            viewport_h,
            anchor_local=anchor,
            wheel_y=1,
        )
        assert stepped == wheeled


class _TestKeysPressed:
    """Minimal key state for pan tests (supports pygame arrow key constants)."""

    def __init__(self, active: frozenset[int] = frozenset()) -> None:
        self._active = active

    def __getitem__(self, key: int) -> bool:
        return key in self._active


def _keys_with_wasd() -> _TestKeysPressed:
    import pygame

    return _TestKeysPressed(frozenset({pygame.K_w, pygame.K_a}))

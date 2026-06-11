"""Unit tests for isometric projection helpers (no Pygame display)."""

from __future__ import annotations

from pathlib import Path

import pytest

from dragonflight.hex_coord import (
    AxialCoord,
    OffsetCoord,
    axial_to_offset,
    neighbours,
    offset_to_axial,
)
from dragonflight.map_loader import load_map
from dragonflight.map_state import GameMap, Tile
from dragonflight.terrain import Terrain
from isometric.isometric_render import (
    _iso_content_extent_rel,
    _iso_pixel_bbox_size,
    axial_to_iso_pixel,
    compute_iso_render_hex_size_for_canvas,
    compute_iso_window_size,
    iso_hex_polygon_points,
    offset_to_iso_pixel,
)

_EXAMPLE_MAP_PATH: Path = Path(__file__).resolve().parent.parent / "assets" / "example_hexmap.json"


@pytest.fixture(scope="module")
def example_map() -> GameMap:
    return load_map(_EXAMPLE_MAP_PATH)


class TestAxialToIsoPixel:
    def test_monotonic_in_q(self) -> None:
        a = axial_to_iso_pixel(AxialCoord(0, 0), 10.0)
        b = axial_to_iso_pixel(AxialCoord(1, 0), 10.0)
        assert b[0] > a[0]

    def test_monotonic_in_r(self) -> None:
        a = axial_to_iso_pixel(AxialCoord(0, 0), 10.0)
        b = axial_to_iso_pixel(AxialCoord(0, 1), 10.0)
        assert b[0] < a[0]
        assert b[1] > a[1]

    def test_offset_matches_axial_path(self) -> None:
        coord = OffsetCoord(col=3, row=5)
        axial = offset_to_axial(coord)
        assert offset_to_iso_pixel(coord, 12.0) == axial_to_iso_pixel(axial, 12.0)


def _polygon_edges(
    points: list[tuple[float, float]],
) -> list[tuple[tuple[float, float], tuple[float, float]]]:
    return [(points[i], points[(i + 1) % len(points)]) for i in range(len(points))]


def _edges_share_segment(
    edge_a: tuple[tuple[float, float], tuple[float, float]],
    edge_b: tuple[tuple[float, float], tuple[float, float]],
    *,
    tol: float = 1e-9,
) -> bool:
    (a0, a1), (b0, b1) = edge_a, edge_b

    def _close(p: tuple[float, float], q: tuple[float, float]) -> bool:
        return abs(p[0] - q[0]) <= tol and abs(p[1] - q[1]) <= tol

    return (_close(a0, b0) and _close(a1, b1)) or (_close(a0, b1) and _close(a1, b0))


def _polygons_share_edge(
    poly_a: list[tuple[float, float]],
    poly_b: list[tuple[float, float]],
) -> bool:
    edges_a = _polygon_edges(poly_a)
    edges_b = _polygon_edges(poly_b)
    return any(_edges_share_segment(ea, eb) for ea in edges_a for eb in edges_b)


class TestIsoHexTessellation:
    def test_hex_has_six_vertices(self) -> None:
        center = offset_to_iso_pixel(OffsetCoord(col=0, row=0), 10.0)
        poly = iso_hex_polygon_points(center, 10.0)
        assert len(poly) == 6

    def test_adjacent_offset_neighbors_share_edge(self) -> None:
        hex_size = 12.0
        center_offset = OffsetCoord(col=5, row=4)
        center = offset_to_iso_pixel(center_offset, hex_size)
        poly_center = iso_hex_polygon_points(center, hex_size)
        axial = offset_to_axial(center_offset)
        for neighbor_axial in neighbours(axial):
            neighbor_offset = axial_to_offset(neighbor_axial)
            neighbor_center = offset_to_iso_pixel(neighbor_offset, hex_size)
            poly_neighbor = iso_hex_polygon_points(neighbor_center, hex_size)
            assert _polygons_share_edge(poly_center, poly_neighbor)

    def test_adjacent_column_neighbors_share_edge(self) -> None:
        hex_size = 10.0
        center_a = offset_to_iso_pixel(OffsetCoord(col=0, row=0), hex_size)
        center_b = offset_to_iso_pixel(OffsetCoord(col=1, row=0), hex_size)
        poly_a = iso_hex_polygon_points(center_a, hex_size)
        poly_b = iso_hex_polygon_points(center_b, hex_size)
        assert _polygons_share_edge(poly_a, poly_b)


class TestIsoBbox:
    def test_bbox_non_empty(self, example_map: GameMap) -> None:
        w, h = _iso_pixel_bbox_size(example_map, example_map.hex_size)
        assert w > 0.0
        assert h > 0.0

    def test_content_extent_non_degenerate(self, example_map: GameMap) -> None:
        min_x, max_x, min_y, max_y = _iso_content_extent_rel(example_map, example_map.hex_size)
        assert max_x > min_x
        assert max_y > min_y

    def test_window_size_positive(self, example_map: GameMap) -> None:
        hex_size = compute_iso_render_hex_size_for_canvas(example_map, 800, 600)
        win_w, win_h = compute_iso_window_size(example_map, hex_size)
        assert win_w > 0
        assert win_h > 0

    def test_never_upscales_above_authored(self, example_map: GameMap) -> None:
        size = compute_iso_render_hex_size_for_canvas(example_map, 4000, 3000)
        assert size <= example_map.hex_size


class TestSmallMap:
    def test_single_row_extent(self) -> None:
        tiles = {
            OffsetCoord(col, 0): Tile(coord=OffsetCoord(col, 0), terrain=Terrain.GRASSLAND)
            for col in range(6)
        }
        game_map = GameMap(
            width=6,
            height=1,
            hex_size=10.0,
            orientation="flat",
            tiles=tiles,
        )
        w, h = _iso_pixel_bbox_size(game_map, 10.0)
        assert w > 0.0
        assert h > 0.0

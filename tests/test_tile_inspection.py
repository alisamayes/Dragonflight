"""Tests for tile inspection view helpers."""

from __future__ import annotations

from dragonflight.hex_coord import OffsetCoord
from dragonflight.map_state import GameMap, Tile
from dragonflight.settlement import Village
from dragonflight.terrain import Terrain
from dragonflight.tile_inspection import (
    terrain_display_name,
    tile_inspect_info,
    tile_inspector_lines,
)


def _tiny_map_with_settlement(coord: OffsetCoord) -> GameMap:
    return GameMap(
        width=5,
        height=5,
        hex_size=30.0,
        orientation="flat",
        tiles={
            coord: Tile(coord=coord, terrain=Terrain.SETTLEMENT),
        },
    )


def test_tile_inspect_info_includes_live_settlement_stats() -> None:
    coord = OffsetCoord(2, 3)
    game_map = _tiny_map_with_settlement(coord)
    village = Village(coord)
    settlements = {coord: village}

    info = tile_inspect_info(game_map, coord, settlements)

    assert info is not None
    assert info.coord == coord
    assert info.terrain is Terrain.SETTLEMENT
    assert info.settlement is not None
    assert info.settlement.settlement_type.value == "village"
    assert info.settlement.eco == village.eco
    assert info.settlement.hp == village.hp


def test_tile_inspect_info_returns_none_off_map() -> None:
    game_map = _tiny_map_with_settlement(OffsetCoord(0, 0))
    info = tile_inspect_info(game_map, OffsetCoord(9, 9), {})
    assert info is None


def test_terrain_display_name_readable() -> None:
    assert terrain_display_name(Terrain.GRASSLAND) == "Grassland"


def test_tile_inspector_lines_non_settlement_shows_terrain_only() -> None:
    coord = OffsetCoord(1, 1)
    game_map = GameMap(
        width=5,
        height=5,
        hex_size=30.0,
        orientation="flat",
        tiles={coord: Tile(coord=coord, terrain=Terrain.GRASSLAND)},
    )
    info = tile_inspect_info(game_map, coord, {})
    assert info is not None
    lines = tile_inspector_lines(info)
    assert len(lines) == 1
    assert lines[0].kind == "terrain"
    assert "Grassland" in lines[0].text
    assert all("Eco" not in ln.text for ln in lines)


def test_tile_inspector_lines_live_settlement_includes_stat_block() -> None:
    coord = OffsetCoord(2, 3)
    game_map = _tiny_map_with_settlement(coord)
    village = Village(coord)
    info = tile_inspect_info(game_map, coord, {coord: village})
    assert info is not None
    lines = tile_inspector_lines(info)
    kinds = [ln.kind for ln in lines]
    assert "terrain" in kinds
    assert kinds.count("settlement") >= 4
    assert any("Settlement type" in ln.text for ln in lines)
    assert any("Eco:" in ln.text for ln in lines)


def test_tile_inspector_lines_settlement_hex_without_entity_is_notice_only() -> None:
    coord = OffsetCoord(0, 0)
    game_map = _tiny_map_with_settlement(coord)
    info = tile_inspect_info(game_map, coord, {})
    assert info is not None
    lines = tile_inspector_lines(info)
    assert any(ln.kind == "notice" for ln in lines)
    assert not any(ln.kind == "settlement" for ln in lines)

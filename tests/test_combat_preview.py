"""Tests for read-only combat damage preview helpers."""

from __future__ import annotations

from dragonflight.army import Army
from dragonflight.combat_preview import preview_army_round, preview_settlement_round
from dragonflight.dragon import Dragon, DragonKind
from dragonflight.hex_coord import OffsetCoord
from dragonflight.map_state import GameMap, Tile
from dragonflight.settlement import Village
from dragonflight.terrain import Terrain


def _tiny_map(coord: OffsetCoord) -> GameMap:
    return GameMap(
        width=coord.col + 1,
        height=coord.row + 1,
        hex_size=30.0,
        orientation="flat",
        tiles={coord: Tile(coord=coord, terrain=Terrain.GRASSLAND)},
    )


class TestCombatPreview:
    def test_army_preview_timestop_blocks_enemy_damage(self) -> None:
        coord = OffsetCoord(0, 0)
        army = Army(
            hp=100,
            max_hp=100,
            atk=50,
            dfn=10,
            movement_speed=8,
            position=coord,
        )
        dragon = Dragon(DragonKind.YELLOW_CHRONO, coord, hours_remaining=24.0)
        dragon.active_ability_hours["Timestop"] = 1.0
        prev = preview_army_round(dragon, army, _tiny_map(coord))
        assert prev.damage_to_dragon == 0
        assert prev.damage_to_enemy > 0

    def test_settlement_preview_timestop_blocks_enemy_damage(self) -> None:
        coord = OffsetCoord(0, 0)
        settlement = Village(coord)
        dragon = Dragon(DragonKind.YELLOW_CHRONO, coord, hours_remaining=24.0)
        dragon.active_ability_hours["Timestop"] = 1.0
        prev = preview_settlement_round(dragon, settlement, _tiny_map(coord))
        assert prev.damage_to_dragon == 0
        assert prev.damage_to_enemy > 0

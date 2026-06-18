"""Tests for army spawning, pathfinding, phase resolution, and combat."""

from __future__ import annotations

from dragonflight.army import (
    DEFAULT_ARMY_MOVEMENT_SPEED,
    Army,
    ArmyKind,
    merge_army_stacks,
    resolve_army_combat_round,
    run_army_phase,
    validate_dragon_vs_army,
)
from dragonflight.army_pathfinding import (
    advance_along_path,
    army_terrain_move_cost,
    path_cost_to_goal,
    shortest_path,
)
from dragonflight.citadel import DEFAULT_CITADEL_HP, CitadelState
from dragonflight.dragon import DamageRoundExchange, Dragon, DragonKind
from dragonflight.dragon_playables import Browngon
from dragonflight.hex_coord import OffsetCoord
from dragonflight.map_state import GameMap, Tile
from dragonflight.settlement import City, Fort, Village
from dragonflight.terrain import Terrain


def _coord_map(*entries: tuple[int, int, Terrain]) -> GameMap:
    """Build a map from explicit ``(col, row, terrain)`` entries (odd-q connected layouts)."""

    tiles: dict[OffsetCoord, Tile] = {}
    max_col = 0
    max_row = 0
    for col, row, terrain in entries:
        max_col = max(max_col, col)
        max_row = max(max_row, row)
        coord = OffsetCoord(col, row)
        tiles[coord] = Tile(coord=coord, terrain=terrain)
    return GameMap(
        width=max_col + 1,
        height=max_row + 1,
        hex_size=30.0,
        orientation="flat",
        tiles=tiles,
    )


class TestArmySpawnStats:
    def test_spawn_from_village_uses_spec_ratios(self) -> None:
        village = Village(OffsetCoord(2, 3))
        army = Army.spawn_from_settlement(village)

        assert army.hp == village.max_hp * 66 // 100
        assert army.max_hp == army.hp
        assert army.max_hp == village.max_hp * 66 // 100
        assert army.atk == village.atk * 90 // 100
        assert army.dfn == village.dfn * 50 // 100
        assert army.movement_speed == DEFAULT_ARMY_MOVEMENT_SPEED
        assert army.position == village.position
        assert army.kind == ArmyKind.VILLAGE

    def test_spawn_from_fort_and_city_set_kind(self) -> None:
        fort = Fort(OffsetCoord(1, 1))
        city = City(OffsetCoord(2, 2))
        assert Army.spawn_from_settlement(fort).kind == ArmyKind.FORT
        assert Army.spawn_from_settlement(city).kind == ArmyKind.CITY

    def test_threshold_spawn_returns_army(self) -> None:
        fort = Fort(OffsetCoord(4, 4), aggression=250)
        army = fort.add_aggression(50)

        assert army is not None
        assert army == Army.spawn_from_settlement(fort)
        assert fort.aggression == 0


class TestTerrainCosts:
    def test_impassable_terrains(self) -> None:
        assert army_terrain_move_cost(Terrain.MOUNTAIN) is None
        assert army_terrain_move_cost(Terrain.RIVER) is None

    def test_woodland_costs_two(self) -> None:
        assert army_terrain_move_cost(Terrain.WOODLAND) == 2
        assert army_terrain_move_cost(Terrain.GRASSLAND) == 1
        assert army_terrain_move_cost(Terrain.BRIDGE) == 1


class TestPathfinding:
    def test_shortest_path_avoids_river_uses_bridge(self) -> None:
        # Row 0: grass, river, (gap), grass, citadel — armies detour via row 1 bridge.
        game_map = _coord_map(
            (0, 0, Terrain.GRASSLAND),
            (1, 0, Terrain.RIVER),
            (3, 0, Terrain.GRASSLAND),
            (4, 0, Terrain.CITADEL),
            (0, 1, Terrain.GRASSLAND),
            (1, 1, Terrain.GRASSLAND),
            (2, 1, Terrain.BRIDGE),
            (3, 1, Terrain.GRASSLAND),
            (4, 1, Terrain.GRASSLAND),
        )
        start = OffsetCoord(0, 0)
        goal = OffsetCoord(4, 0)
        path = shortest_path(start, goal, game_map)

        assert path[0] == start
        assert path[-1] == goal
        assert OffsetCoord(1, 0) not in path
        assert OffsetCoord(2, 1) in path

    def test_woodland_increases_path_cost(self) -> None:
        start = OffsetCoord(0, 0)
        goal = OffsetCoord(2, 0)
        grass_map = _coord_map(
            (0, 0, Terrain.GRASSLAND),
            (1, 0, Terrain.GRASSLAND),
            (2, 0, Terrain.CITADEL),
        )
        wood_map = _coord_map(
            (0, 0, Terrain.GRASSLAND),
            (1, 0, Terrain.WOODLAND),
            (2, 0, Terrain.CITADEL),
        )
        assert path_cost_to_goal(start, goal, grass_map) == 2
        assert path_cost_to_goal(start, goal, wood_map) == 3

    def test_advance_respects_movement_budget_in_woodland(self) -> None:
        game_map = _coord_map(
            (0, 0, Terrain.GRASSLAND),
            (1, 0, Terrain.WOODLAND),
            (2, 0, Terrain.WOODLAND),
            (3, 0, Terrain.CITADEL),
        )
        end = advance_along_path(OffsetCoord(0, 0), OffsetCoord(3, 0), 3, game_map)
        assert end == OffsetCoord(1, 0)


class TestArmyPhase:
    def test_closest_army_moves_first(self) -> None:
        game_map = _coord_map(
            (0, 1, Terrain.GRASSLAND),
            (1, 1, Terrain.GRASSLAND),
            (2, 1, Terrain.GRASSLAND),
            (3, 1, Terrain.CITADEL),
        )
        citadel = OffsetCoord(3, 1)
        near = Army(
            hp=10,
            max_hp=10,
            atk=1,
            dfn=1,
            movement_speed=1,
            position=OffsetCoord(2, 1),
        )
        far = Army(
            hp=10,
            max_hp=10,
            atk=1,
            dfn=1,
            movement_speed=1,
            position=OffsetCoord(0, 1),
        )

        result = run_army_phase(
            game_map, [far, near], citadel_coord=citadel, citadel_hp=DEFAULT_CITADEL_HP
        )

        assert result.citadel_attacks == 1
        assert result.citadel_hp == DEFAULT_CITADEL_HP - 1
        assert len(result.armies) == 1
        assert result.armies[0].position == OffsetCoord(1, 1)
        assert not result.game_over

    def test_merge_sums_stats_keeps_max_speed(self) -> None:
        merged = merge_army_stacks(
            [
                Army(
                    hp=10,
                    max_hp=10,
                    atk=5,
                    dfn=2,
                    movement_speed=4,
                    position=OffsetCoord(0, 0),
                ),
                Army(
                    hp=20,
                    max_hp=25,
                    atk=7,
                    dfn=3,
                    movement_speed=8,
                    position=OffsetCoord(0, 0),
                ),
            ]
        )
        assert len(merged) == 1
        assert merged[0].hp == 30
        assert merged[0].max_hp == 35
        assert merged[0].atk == 12
        assert merged[0].dfn == 5
        assert merged[0].movement_speed == 8

    def test_each_army_on_citadel_deals_one_damage_before_merge(self) -> None:
        game_map = _coord_map(
            (0, 1, Terrain.GRASSLAND),
            (1, 1, Terrain.GRASSLAND),
            (2, 1, Terrain.CITADEL),
        )
        citadel = OffsetCoord(2, 1)
        near = Army(
            hp=10,
            max_hp=10,
            atk=1,
            dfn=1,
            movement_speed=1,
            position=OffsetCoord(1, 1),
        )
        far = Army(
            hp=10,
            max_hp=10,
            atk=1,
            dfn=1,
            movement_speed=2,
            position=OffsetCoord(0, 1),
        )

        result = run_army_phase(
            game_map, [far, near], citadel_coord=citadel, citadel_hp=DEFAULT_CITADEL_HP
        )

        assert result.citadel_attacks == 2
        assert result.citadel_hp == DEFAULT_CITADEL_HP - 2
        assert result.armies == ()
        assert len(result.messages) == 2

    def test_citadel_game_over_at_zero_hp(self) -> None:
        game_map = _coord_map((0, 1, Terrain.GRASSLAND), (1, 1, Terrain.CITADEL))
        army = Army(
            hp=1,
            max_hp=1,
            atk=1,
            dfn=1,
            movement_speed=8,
            position=OffsetCoord(0, 1),
        )
        result = run_army_phase(game_map, [army], citadel_coord=OffsetCoord(1, 1), citadel_hp=1)

        assert result.game_over
        assert result.citadel_hp == 0


class TestCitadelState:
    def test_apply_army_attack_and_destroyed(self) -> None:
        citadel = CitadelState(position=OffsetCoord(0, 0), hp=3)
        citadel.apply_army_attack()
        assert citadel.hp == 2
        assert not citadel.is_destroyed()
        citadel.apply_army_attack()
        citadel.apply_army_attack()
        assert citadel.hp == 0
        assert citadel.is_destroyed()


class TestArmyCombat:
    def test_validate_requires_same_hex(self) -> None:
        army = Army(
            hp=100,
            max_hp=100,
            atk=10,
            dfn=10,
            movement_speed=8,
            position=OffsetCoord(1, 0),
        )
        dragon = Dragon(DragonKind.RED_FIRE, OffsetCoord(0, 0))
        world = _coord_map((0, 0, Terrain.GRASSLAND), (1, 0, Terrain.GRASSLAND))
        ok, reason = validate_dragon_vs_army(dragon, army, world)
        assert not ok
        assert "hex" in reason

    def test_combat_round_updates_army_hp(self) -> None:
        coord = OffsetCoord(0, 0)
        army = Army(
            hp=500,
            max_hp=500,
            atk=50,
            dfn=30,
            movement_speed=8,
            position=coord,
        )
        dragon = Dragon(
            kind=DragonKind.RED_FIRE,
            position=coord,
            hp=500,
            atk=120,
            dfn=90,
            hours_remaining=24.0,
        )
        world = _coord_map((0, 0, Terrain.GRASSLAND))
        exchange = resolve_army_combat_round(dragon, army, world, citadel_coord=OffsetCoord(5, 0))
        assert isinstance(exchange, DamageRoundExchange)
        assert army.hp == exchange.target_hp_after
        assert army.hp < 500
        assert army.max_hp == 500

    def test_defeated_army_at_zero_hp(self) -> None:
        army = Army(
            hp=0,
            max_hp=100,
            atk=1,
            dfn=1,
            movement_speed=8,
            position=OffsetCoord(0, 0),
        )
        assert army.is_defeated()

    def test_tremors_tile_halves_army_movement_that_day(self) -> None:
        game_map = _coord_map(
            (0, 0, Terrain.GRASSLAND),
            (1, 0, Terrain.GRASSLAND),
            (2, 0, Terrain.GRASSLAND),
            (3, 0, Terrain.GRASSLAND),
            (4, 0, Terrain.GRASSLAND),
            (5, 0, Terrain.GRASSLAND),
            (6, 0, Terrain.CITADEL),
        )
        tremors_tile = OffsetCoord(0, 0)
        citadel = OffsetCoord(6, 0)
        dragon = Browngon.new_at(citadel)
        dragon.marked_ability_tiles["Tremors"] = (tremors_tile,)
        army = Army(
            hp=10,
            max_hp=10,
            atk=1,
            dfn=1,
            movement_speed=10,
            position=tremors_tile,
        )

        slowed = run_army_phase(
            game_map,
            [army],
            citadel_coord=citadel,
            citadel_hp=DEFAULT_CITADEL_HP,
            dragon=dragon,
        )

        assert len(slowed.armies) == 1
        assert slowed.armies[0].position == OffsetCoord(5, 0)
        assert slowed.citadel_attacks == 0

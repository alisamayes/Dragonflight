"""Tests for the dragon entity scaffolding."""

from __future__ import annotations

from pathlib import Path

import pytest

from dragonflight.dragon import DamageRoundExchange, Dragon, DragonKind, MoveAttempt
from dragonflight.dragon_playables import Blackgon, Greengon, Redgon, new_playable_dragon
from dragonflight.hex_coord import OffsetCoord, axial_to_offset, neighbours, offset_to_axial
from dragonflight.map_loader import load_map
from dragonflight.map_state import GameMap
from dragonflight.terrain import Terrain

_EXAMPLE_MAP_PATH: Path = Path(__file__).resolve().parent.parent / "assets" / "example_hexmap.json"


@pytest.fixture(scope="module")
def example_map() -> GameMap:
    return load_map(_EXAMPLE_MAP_PATH)


def _citadel_coord(game_map: GameMap) -> OffsetCoord:
    for tile in game_map.tiles.values():
        if tile.terrain == Terrain.CITADEL:
            return tile.coord
    raise AssertionError("example map missing citadel tile")


def _first_neighbor_on_map(game_map: GameMap, origin: OffsetCoord) -> OffsetCoord:
    axial = offset_to_axial(origin)
    for neighbour in neighbours(axial):
        candidate = axial_to_offset(neighbour)
        if game_map.get(candidate) is not None:
            return candidate
    raise AssertionError("could not locate neighbour tile")


class TestDragonHp:
    def test_current_hp_mirrors_hp_and_clamps_to_max(self) -> None:
        dragon = Dragon(DragonKind.RED_FIRE, OffsetCoord(0, 0), hp=100, max_hp=200)
        assert dragon.current_hp == dragon.hp == 100
        dragon.current_hp = 150
        assert dragon.hp == 150
        dragon.current_hp = 999
        assert dragon.hp == 200
        dragon.current_hp = -5
        assert dragon.hp == 0


class TestDragonDefaults:
    def test_redgon_factory_matches_dragon_types_doc(self) -> None:
        citadel = OffsetCoord(col=5, row=5)
        dragon = Dragon.new_red_fire_at(citadel)
        assert dragon.kind is DragonKind.RED_FIRE
        assert isinstance(dragon, Redgon)
        assert dragon.hp == 500 == dragon.max_hp
        assert dragon.atk == 120
        assert dragon.dfn == 90
        assert dragon.flight_range_hexes == 15
        assert dragon.speed_hexes_per_hour == 8.0
        assert dragon.hours_remaining == 24.0

    def test_new_playable_dragon_blackgon_stats(self) -> None:
        citadel = OffsetCoord(col=0, row=0)
        d = new_playable_dragon(DragonKind.BLACK_TANK, citadel)
        assert isinstance(d, Blackgon)
        assert d.max_hp == 500
        assert d.atk == 100
        assert d.dfn == 140
        assert d.flight_range_hexes == 10
        assert d.speed_hexes_per_hour == 4.0

    def test_greengon_hp_pool(self) -> None:
        c = OffsetCoord(1, 1)
        g = new_playable_dragon(DragonKind.GREEN_LIFE, c)
        assert isinstance(g, Greengon)
        assert g.max_hp == 600


class TestMovement:
    def test_move_updates_position_and_budget(self, example_map: GameMap) -> None:
        citadel = _citadel_coord(example_map)
        destination = _first_neighbor_on_map(example_map, citadel)
        dragon = Dragon.new_red_fire_at(citadel)
        hours_before = dragon.hours_remaining
        outcome = dragon.move(destination, example_map, citadel)
        assert outcome.ok is True
        assert dragon.position == destination
        assert outcome.hours_spent > 0
        assert dragon.hours_remaining == pytest.approx(hours_before - outcome.hours_spent)

    def test_move_out_of_range_fails_without_state_change(self, example_map: GameMap) -> None:
        citadel = _citadel_coord(example_map)
        dragon = Dragon.new_red_fire_at(citadel)
        dragon.flight_range_hexes = 0
        neighbour = _first_neighbor_on_map(example_map, citadel)
        outcome = dragon.move(neighbour, example_map, citadel)
        assert isinstance(outcome, MoveAttempt)
        assert outcome.ok is False
        assert dragon.position == citadel


class TestValidateMove:
    def test_validate_matches_successful_move_hours(self, example_map: GameMap) -> None:
        citadel = _citadel_coord(example_map)
        neighbour = _first_neighbor_on_map(example_map, citadel)
        dragon = Dragon.new_red_fire_at(citadel)
        preview = dragon.validate_move(neighbour, example_map, citadel)
        assert preview.ok is True
        hours_before = dragon.hours_remaining
        committed = dragon.move(neighbour, example_map, citadel)
        assert committed.ok is True
        assert dragon.hours_remaining == pytest.approx(hours_before - committed.hours_spent)

    def test_validate_rejects_same_tile(self, example_map: GameMap) -> None:
        citadel = _citadel_coord(example_map)
        dragon = Dragon.new_red_fire_at(citadel)
        preview = dragon.validate_move(citadel, example_map, citadel)
        assert preview.ok is False


class TestCombatRound:
    def test_attack_round_balances_hours_and_hp(self) -> None:
        citadel = OffsetCoord(10, 10)
        dragon = Dragon.new_red_fire_at(citadel)
        resolved = dragon.attack_round_vs_target(target_hp=300, target_atk=4, target_dfn=8)
        assert isinstance(resolved, DamageRoundExchange)
        assert resolved.damage_to_dragon == 2  # 4 * 100 // (100 + 90)
        assert resolved.damage_to_target == 111  # 120 * 100 // (100 + 8)
        assert dragon.hours_remaining == 24.0 - 0.5


class TestCitadelEndOfDayHealing:
    def test_low_hp_ten_hours_matches_design_example(self) -> None:
        citadel = OffsetCoord(0, 0)
        dragon = Dragon(DragonKind.RED_FIRE, citadel, hp=50, max_hp=500)
        dragon.hours_remaining = 10.0

        dragon.begin_new_day_at_citadel(citadel)

        assert dragon.hp == 400
        assert dragon.hours_remaining == 24.0
        assert dragon.position == citadel

    def test_healing_clamps_to_max_hp(self) -> None:
        citadel = OffsetCoord(1, 0)
        dragon = Dragon(DragonKind.RED_FIRE, citadel, hp=490, max_hp=500)
        dragon.hours_remaining = 10.0

        dragon.begin_new_day_at_citadel(citadel)

        assert dragon.hp == 500

    def test_zero_hours_remaining_heals_base_only(self) -> None:
        citadel = OffsetCoord(2, 0)
        dragon = Dragon(DragonKind.RED_FIRE, citadel, hp=10, max_hp=100)
        dragon.hours_remaining = 0.0

        dragon.begin_new_day_at_citadel(citadel)

        assert dragon.hp == 60


class TestDamageRoundReturnHome:
    def test_validates_when_slack_insufficient_after_round(self) -> None:
        dragon = Dragon(
            DragonKind.RED_FIRE,
            OffsetCoord(0, 0),
            hours_remaining=0.5,
            speed_hexes_per_hour=10.0,
        )
        blocked = dragon.validate_damage_round_preserves_return_to_citadel(OffsetCoord(5, 0))
        assert not blocked.ok
        assert "citadel" in blocked.reason.lower()

    def test_validates_ok_when_home_reachable_after_round(self) -> None:
        dragon = Dragon(
            DragonKind.RED_FIRE,
            OffsetCoord(0, 0),
            hours_remaining=0.5,
            speed_hexes_per_hour=10.0,
        )
        ok = dragon.validate_damage_round_preserves_return_to_citadel(OffsetCoord(0, 0))
        assert ok.ok

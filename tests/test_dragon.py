"""Tests for the dragon entity scaffolding."""

from __future__ import annotations

from pathlib import Path

import pytest

from dragonflight.dragon import DamageRoundExchange, Dragon, MoveAttempt
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


class TestDragonDefaults:
    def test_initializer_stats_match_scaffolding_brief(self) -> None:
        citadel = OffsetCoord(col=5, row=5)
        dragon = Dragon.new_red_fire_at(citadel)
        assert dragon.kind.value == "red_fire"
        assert dragon.hp == 50 == dragon.max_hp
        assert dragon.atk == dragon.dfn == dragon.flight_range_hexes == 10
        assert dragon.speed_hexes_per_hour == 10.0
        assert dragon.hours_remaining == 24.0


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
        resolved = dragon.attack_round_vs_target(target_hp=30, target_atk=4, target_dfn=8)
        assert isinstance(resolved, DamageRoundExchange)
        assert resolved.damage_to_dragon == 0
        assert resolved.damage_to_target == 2  # atk 10 - dfn 8, dragon floors at ≥1 → 2
        assert dragon.hours_remaining == 24.0 - 0.5

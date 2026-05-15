"""Tests for runtime draconic ability unlocks, cooldowns, and combat hooks."""

from __future__ import annotations

import pytest

from dragonflight.army import Army, resolve_army_combat_round
from dragonflight.combat_preview import preview_army_round, preview_settlement_round
from dragonflight.dragon import DamageRoundExchange
from dragonflight.dragon_abilities import (
    VIVIFY_SACRIFICE_EFFECT_NAME,
    ability_ui_detail_lines,
    active_effect_hours_remaining,
    apply_time_spent,
    cooldown_remaining,
    effective_attack,
    on_combat_ended,
    synchronize_unlocked_abilities,
    try_use_ability,
    vivify_attack_bonus,
)
from dragonflight.dragon_playables import Greengon, Purplegon, Redgon
from dragonflight.hex_coord import OffsetCoord
from dragonflight.map_state import GameMap, Tile
from dragonflight.settlement import Fort, resolve_settlement_combat_round
from dragonflight.terrain import Terrain


def _world(*tiles: Tile) -> GameMap:
    return GameMap(
        width=10,
        height=10,
        hex_size=30.0,
        orientation="flat",
        tiles={tile.coord: tile for tile in tiles},
    )


def test_unlocks_persist_on_dragon_state() -> None:
    dragon = Redgon.new_at(OffsetCoord(0, 0))
    dragon.level = 10

    synchronize_unlocked_abilities(dragon)

    assert dragon.unlocked_ability_names == ("Flame buffer", "Plasma Lance")


def test_plasma_lance_uses_turn_cooldown_and_resets_next_day() -> None:
    coord = OffsetCoord(0, 0)
    dragon = Redgon.new_at(coord)
    dragon.level = 10
    settlement = Fort(coord)
    world = _world(Tile(coord=coord, terrain=Terrain.SETTLEMENT))

    result = try_use_ability(
        dragon,
        "Plasma Lance",
        world=world,
        citadel_coord=coord,
        settlements_by_coord={coord: settlement},
        target=coord,
    )

    assert result.ok
    assert settlement.hp == 680
    assert cooldown_remaining(dragon, "Plasma Lance") == 1

    blocked = try_use_ability(
        dragon,
        "Plasma Lance",
        world=world,
        citadel_coord=coord,
        settlements_by_coord={coord: settlement},
        target=coord,
    )
    assert not blocked.ok

    dragon.begin_new_day_at_citadel(coord)
    assert cooldown_remaining(dragon, "Plasma Lance") == 0


def test_redgon_flame_buffer_stacks_per_settlement_engagement() -> None:
    coord = OffsetCoord(0, 0)
    dragon = Redgon.new_at(coord)
    dragon.level = 5
    settlement = Fort(coord)
    world = _world(Tile(coord=coord, terrain=Terrain.SETTLEMENT))

    first = resolve_settlement_combat_round(dragon, settlement, world, citadel_coord=coord)
    second = resolve_settlement_combat_round(dragon, settlement, world, citadel_coord=coord)

    assert isinstance(first, DamageRoundExchange)
    assert isinstance(second, DamageRoundExchange)
    assert first.damage_to_target == 68
    assert second.damage_to_target == 70
    on_combat_ended(dragon)
    assert dragon.passive_stacks["Flame buffer"] == 2

    dragon.begin_new_day_at_citadel(coord)

    assert dragon.passive_stacks["Flame buffer"] == 0


def test_ability_ui_detail_lines_include_flame_buffer_numbers() -> None:
    dragon = Redgon.new_at(OffsetCoord(0, 0))
    dragon.level = 5
    dragon.passive_stacks["Flame buffer"] = 3
    synchronize_unlocked_abilities(dragon)
    spec = next(spec for spec in type(dragon).ABILITIES if spec.name == "Flame buffer")

    lines = ability_ui_detail_lines(dragon, spec, world=None)

    assert "3/10" in lines[0]
    assert "+9%" in lines[1]


def test_greengon_healing_crystal_heals_for_hours_spent() -> None:
    origin = OffsetCoord(0, 0)
    destination = OffsetCoord(1, 0)
    dragon = Greengon.new_at(origin)
    dragon.level = 5
    dragon.hp = 300
    world = _world(
        Tile(coord=origin, terrain=Terrain.CITADEL),
        Tile(coord=destination, terrain=Terrain.GRASSLAND),
    )

    outcome = dragon.move(destination, world, origin)

    assert outcome.ok
    assert outcome.hours_spent == pytest.approx(1 / 6)
    assert dragon.hp == 302


def test_vivify_sacrifice_expires_before_temp_max_hp() -> None:
    coord = OffsetCoord(0, 0)
    dragon = Greengon.new_at(coord)
    dragon.level = 15
    world = _world(Tile(coord=coord, terrain=Terrain.CITADEL))

    result = try_use_ability(
        dragon,
        "Vivify",
        world=world,
        citadel_coord=coord,
        settlements_by_coord={},
    )

    assert result.ok
    assert dragon.max_hp == 720
    assert dragon.hp == 720
    assert dragon.passive_stacks["Vivify max hp bonus"] == 120
    assert active_effect_hours_remaining(dragon, VIVIFY_SACRIFICE_EFFECT_NAME) == 5.0

    apply_time_spent(dragon, 6.0)

    assert active_effect_hours_remaining(dragon, VIVIFY_SACRIFICE_EFFECT_NAME) == 0.0
    assert dragon.max_hp == 720
    assert vivify_attack_bonus(dragon) == 0

    dragon.begin_new_day_at_citadel(coord)

    assert dragon.max_hp == 600
    assert "Vivify max hp bonus" not in dragon.passive_stacks


def test_vivify_ui_lines_use_base_max_and_sacrifice_timer() -> None:
    coord = OffsetCoord(0, 0)
    dragon = Greengon.new_at(coord)
    dragon.level = 15
    world = _world(Tile(coord=coord, terrain=Terrain.CITADEL))
    result = try_use_ability(
        dragon,
        "Vivify",
        world=world,
        citadel_coord=coord,
        settlements_by_coord={},
    )
    assert result.ok
    spec = next(spec for spec in type(dragon).ABILITIES if spec.name == "Vivify")

    lines = ability_ui_detail_lines(dragon, spec, world=world)

    assert "+120 max HP" in lines[0]
    assert "5.0h / 5h" in lines[1]
    assert "2× rule" in lines[2]


def test_vivify_attack_bonus_is_twice_sacrifice_while_window_active() -> None:
    coord = OffsetCoord(0, 0)
    dragon = Greengon.new_at(coord)
    dragon.level = 15
    world = _world(Tile(coord=coord, terrain=Terrain.CITADEL))
    assert try_use_ability(
        dragon,
        "Vivify",
        world=world,
        citadel_coord=coord,
        settlements_by_coord={},
    ).ok
    assert dragon.hp == 720
    bonus = vivify_attack_bonus(dragon)
    assert bonus == 144
    assert dragon.hp == 648


def test_army_combat_increments_flame_buffer_stacks() -> None:
    coord = OffsetCoord(0, 0)
    dragon = Redgon.new_at(coord)
    dragon.level = 5
    army = Army(hp=800, max_hp=800, atk=50, dfn=8, movement_speed=8, position=coord)
    world = _world(Tile(coord=coord, terrain=Terrain.GRASSLAND))

    first = resolve_army_combat_round(dragon, army, world, citadel_coord=coord)
    second = resolve_army_combat_round(dragon, army, world, citadel_coord=coord)
    assert isinstance(first, DamageRoundExchange)
    assert isinstance(second, DamageRoundExchange)
    on_combat_ended(dragon)
    assert dragon.passive_stacks["Flame buffer"] == 2


def test_plasma_lance_damages_army_when_no_settlement() -> None:
    coord = OffsetCoord(1, 0)
    dragon = Redgon.new_at(coord)
    dragon.level = 10
    army = Army(hp=200, max_hp=200, atk=10, dfn=5, movement_speed=8, position=coord)
    world = _world(
        Tile(coord=OffsetCoord(0, 0), terrain=Terrain.CITADEL),
        Tile(coord=coord, terrain=Terrain.GRASSLAND),
    )
    result = try_use_ability(
        dragon,
        "Plasma Lance",
        world=world,
        citadel_coord=OffsetCoord(0, 0),
        settlements_by_coord={},
        target=coord,
        armies_by_coord={coord: army},
    )
    assert result.ok
    dmg = max(1, effective_attack(dragon, world=world))
    assert army.hp == 200 - dmg


def test_ice_talons_reduces_army_attack_after_round() -> None:
    coord = OffsetCoord(0, 0)
    dragon = Purplegon.new_at(coord)
    dragon.level = 5
    army = Army(hp=400, max_hp=400, atk=100, dfn=20, movement_speed=8, position=coord)
    world = _world(Tile(coord=coord, terrain=Terrain.GRASSLAND))
    assert resolve_army_combat_round(dragon, army, world, citadel_coord=OffsetCoord(5, 0))
    assert army.atk == 90


def test_combat_preview_matches_first_army_round_damage() -> None:
    coord = OffsetCoord(0, 0)
    dragon = Redgon.new_at(coord)
    dragon.level = 5
    army = Army(hp=800, max_hp=800, atk=50, dfn=8, movement_speed=8, position=coord)
    world = _world(Tile(coord=coord, terrain=Terrain.GRASSLAND))
    preview = preview_army_round(dragon, army, world)
    exchange = resolve_army_combat_round(dragon, army, world, citadel_coord=coord)
    assert isinstance(exchange, DamageRoundExchange)
    assert preview.damage_to_enemy == exchange.damage_to_target
    assert preview.damage_to_dragon == exchange.damage_to_dragon


def test_combat_preview_matches_first_settlement_round_damage() -> None:
    coord = OffsetCoord(0, 0)
    dragon = Redgon.new_at(coord)
    dragon.level = 5
    settlement = Fort(coord)
    world = _world(Tile(coord=coord, terrain=Terrain.SETTLEMENT))
    preview = preview_settlement_round(dragon, settlement, world)
    exchange = resolve_settlement_combat_round(dragon, settlement, world, citadel_coord=coord)
    assert isinstance(exchange, DamageRoundExchange)
    assert preview.damage_to_enemy == exchange.damage_to_target
    assert preview.damage_to_dragon == exchange.damage_to_dragon

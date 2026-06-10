"""Tests for random world events."""

from __future__ import annotations

import random

import pytest

from dragonflight.army import Army, ArmyKind, run_army_phase
from dragonflight.dragon import Dragon, DragonKind
from dragonflight.entity_stats import StatKey
from dragonflight.fog_of_war import FogOfWarState, is_revealed
from dragonflight.game_tuning import GameTuning, default_game_tuning
from dragonflight.hex_coord import OffsetCoord
from dragonflight.map_state import GameMap, Tile
from dragonflight.settlement import Village
from dragonflight.terrain import Terrain
from dragonflight.world_events import (
    WorldEventDayState,
    apply_world_event,
    roll_world_event,
    settlement_phase_world_event_hooks,
    spawn_raider_army,
)


def _terrain_at(c: int, r: int) -> Terrain:
    if c == 1 and r == 1:
        return Terrain.CITADEL
    if c == 2 and r == 2:
        return Terrain.SETTLEMENT
    if r == 0:
        return Terrain.RIVER
    return Terrain.GRASSLAND


def _tiny_map() -> GameMap:
    tiles = {
        OffsetCoord(c, r): Tile(
            coord=OffsetCoord(c, r),
            terrain=_terrain_at(c, r),
        )
        for c in range(4)
        for r in range(3)
    }
    return GameMap(width=4, height=3, hex_size=10.0, orientation="flat", tiles=tiles)


def _dragon(level: int = 3) -> Dragon:
    d = Dragon.new_red_fire_at(OffsetCoord(1, 1))
    d.level = level
    return d


class TestRollWorldEvent:
    def test_zero_chance_never_triggers(self) -> None:
        rng = random.Random(0)
        for _ in range(20):
            assert roll_world_event(0, rng).triggered is False

    def test_full_chance_always_triggers(self) -> None:
        rng = random.Random(1)
        for _ in range(10):
            result = roll_world_event(100, rng)
            assert result.triggered is True
            assert result.event_id is not None
            assert result.description


class TestApplyWorldEvent:
    def test_heatwave_buffs_dragon_attack(self) -> None:
        dragon = _dragon()
        state = WorldEventDayState()
        apply_world_event(
            "heatwave",
            dragon=dragon,
            game_map=_tiny_map(),
            settlements=[],
            day_state=state,
            citadel_hp=3,
            max_citadel_hp=3,
        )
        from dragonflight.dragon_abilities import effective_attack

        assert effective_attack(dragon) > dragon.atk

    def test_citadel_vigor_heals_when_damaged(self) -> None:
        dragon = _dragon()
        state = WorldEventDayState()
        hp, _, _ = apply_world_event(
            "citadel_vigor",
            dragon=dragon,
            game_map=_tiny_map(),
            settlements=[],
            day_state=state,
            citadel_hp=2,
            max_citadel_hp=3,
        )
        assert hp == 3

    def test_arcane_fog_resets_fog(self) -> None:
        dragon = _dragon()
        dragon.flight_range_hexes = 1
        gmap = _tiny_map()
        fog = FogOfWarState()
        far_tile = OffsetCoord(3, 2)
        fog.reveal(far_tile)
        state = WorldEventDayState()
        apply_world_event(
            "arcane_fog",
            dragon=dragon,
            game_map=gmap,
            settlements=[],
            day_state=state,
            citadel_hp=3,
            max_citadel_hp=3,
            fog=fog,
        )
        assert not is_revealed(fog, far_tile)

    def test_raider_spawns_on_edge(self) -> None:
        gmap = _tiny_map()
        army = spawn_raider_army(gmap, dragon_level=2, rng=random.Random(0))
        assert army is not None
        assert army.kind is ArmyKind.RAIDER
        assert army.max_hp == 420
        assert army.movement_speed == 15
        assert army.position.col in (0, gmap.width - 1) or army.position.row in (
            0,
            gmap.height - 1,
        )

    def test_settlement_investments_hooks(self) -> None:
        state = WorldEventDayState()
        apply_world_event(
            "settlement_investments",
            dragon=_dragon(),
            game_map=_tiny_map(),
            settlements=[],
            day_state=state,
            citadel_hp=3,
            max_citadel_hp=3,
        )
        double_g, double_h, eco = settlement_phase_world_event_hooks(state)
        assert double_g and double_h and eco == 1.0


class TestSettlementPhaseHooks:
    def test_heavy_rain_eco_multiplier(self) -> None:
        village = Village(OffsetCoord(0, 0))
        village.hp = village.max_hp
        state = WorldEventDayState()
        apply_world_event(
            "heavy_rain",
            dragon=_dragon(),
            game_map=_tiny_map(),
            settlements=[village],
            day_state=state,
            citadel_hp=3,
            max_citadel_hp=3,
        )
        eco_before = village.eco
        _, _, eco_mult = settlement_phase_world_event_hooks(state)
        village.on_settlement_phase_end(
            tuning=default_game_tuning(),
            eco_growth_mult=eco_mult,
        )
        assert village.eco > eco_before


class TestRaiderCitadelAttack:
    def test_raider_loots_gold_at_citadel(self) -> None:
        gmap = _tiny_map()
        citadel = OffsetCoord(1, 1)
        dragon = _dragon()
        dragon.gold = 500
        raider = Army(
            hp=100,
            max_hp=100,
            atk=10,
            dfn=5,
            movement_speed=99,
            position=citadel,
            kind=ArmyKind.RAIDER,
        )
        result = run_army_phase(
            gmap,
            [raider],
            citadel_coord=citadel,
            citadel_hp=3,
            dragon=dragon,
        )
        assert dragon.gold == 0
        assert result.citadel_hp == 2
        assert any("loot" in m.lower() for m in result.messages)

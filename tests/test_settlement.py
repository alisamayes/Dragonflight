"""Tests for settlement growth, combat, and raid defeat rules."""

from __future__ import annotations

from collections.abc import Callable

import pytest

from dragonflight.army import Army
from dragonflight.dragon import DamageRoundExchange, Dragon, DragonKind, MoveAttempt
from dragonflight.hex_coord import OffsetCoord
from dragonflight.map_state import GameMap, Tile
from dragonflight.settlement import (
    City,
    Fort,
    Settlement,
    SettlementType,
    Village,
    nearby_aggression_radius,
    raid_victory_gold_from_eco,
    resolve_settlement_combat_round,
    resolve_settlement_raid,
    run_settlement_combat_loop,
    validate_settlement_raid,
)
from dragonflight.terrain import Terrain


def _world() -> GameMap:
    coord = OffsetCoord(0, 0)
    return GameMap(
        width=30,
        height=30,
        hex_size=30.0,
        orientation="flat",
        tiles={coord: Tile(coord=coord, terrain=Terrain.SETTLEMENT)},
    )


class TestStartingStats:
    @pytest.mark.parametrize(
        ("settlement", "settlement_type", "hp", "eco", "atk", "dfn", "threshold"),
        [
            (Village(OffsetCoord(1, 1)), SettlementType.VILLAGE, 500, 500, 50, 30, 500),
            (City(OffsetCoord(2, 2)), SettlementType.CITY, 1000, 1000, 70, 80, 600),
            (Fort(OffsetCoord(3, 3)), SettlementType.FORT, 800, 100, 80, 80, 300),
        ],
    )
    def test_subclasses_have_specified_baselines(
        self,
        settlement: Settlement,
        settlement_type: SettlementType,
        hp: int,
        eco: int,
        atk: int,
        dfn: int,
        threshold: int,
    ) -> None:
        assert settlement.hp == hp
        assert settlement.max_hp == hp
        assert settlement.eco == eco
        assert settlement.starting_eco == eco
        assert settlement.atk == atk
        assert settlement.dfn == dfn
        assert settlement.defence == dfn
        assert settlement.aggression == 0
        assert settlement.aggression_threshold == threshold
        assert settlement.settlement_type is settlement_type

    def test_base_factories_return_subclasses(self) -> None:
        assert isinstance(Settlement.village(OffsetCoord(0, 0)), Village)
        assert isinstance(Settlement.city(OffsetCoord(0, 0)), City)
        assert isinstance(Settlement.fort(OffsetCoord(0, 0)), Fort)


class TestSettlementPhase:
    @pytest.mark.parametrize(
        "make_settlement",
        [
            lambda: City(OffsetCoord(0, 0)),
            lambda: Village(OffsetCoord(0, 0)),
            lambda: Fort(OffsetCoord(0, 0)),
        ],
    )
    def test_damaged_settlement_heals_and_does_not_grow_same_tick(
        self, make_settlement: Callable[[], Settlement]
    ) -> None:
        s = make_settlement()
        s.hp = 1

        outcome = s.on_settlement_phase_end()

        assert outcome.action == "healed"
        assert s.hp == s.max_hp * 40 // 100 + 1
        assert outcome.max_hp_delta == 0

    def test_damaged_city_heal_caps_at_max_hp(self) -> None:
        city = City(OffsetCoord(0, 0))
        city.hp = 100

        outcome = city.on_settlement_phase_end()

        assert outcome.action == "healed"
        assert city.hp == 500
        assert city.max_hp == 1000
        assert city.eco == 1000
        assert city.atk == 70
        assert city.dfn == 80

    def test_settlement_at_zero_heals_eighty_percent_of_max(self) -> None:
        fort = Fort(OffsetCoord(0, 0))
        fort.hp = 0

        outcome = fort.on_settlement_phase_end()

        assert outcome.action == "healed"
        assert fort.hp == fort.max_hp * 80 // 100
        assert fort.max_hp == 800

    def test_undamaged_city_grows_eco_and_stats_not_hp(self) -> None:
        city = City(OffsetCoord(0, 0))

        outcome = city.on_settlement_phase_end()

        assert outcome.action == "grew"
        assert city.max_hp == 1000
        assert city.hp == 1000
        assert outcome.hp_delta == 0
        assert outcome.max_hp_delta == 0
        assert city.eco == 1150
        assert city.atk == 75
        assert city.dfn == 85

    def test_undamaged_village_grows(self) -> None:
        village = Village(OffsetCoord(0, 0))

        outcome = village.on_settlement_phase_end()

        assert outcome.action == "grew"
        assert village.max_hp == 500
        assert village.hp == 500
        assert village.eco == 575
        assert village.atk == 55
        assert village.dfn == 35


class TestSettlementRaidResolution:
    def test_validate_settlement_raid_requires_dragon_on_hex(self) -> None:
        coord_a = OffsetCoord(0, 0)
        coord_b = OffsetCoord(1, 0)
        tiles = {
            coord_a: Tile(coord=coord_a, terrain=Terrain.SETTLEMENT),
            coord_b: Tile(coord=coord_b, terrain=Terrain.SETTLEMENT),
        }
        world = GameMap(width=5, height=5, hex_size=30.0, orientation="flat", tiles=tiles)
        village_b = Village(coord_b)
        dragon = Dragon(kind=DragonKind.RED_FIRE, position=coord_a)

        ok, reason = validate_settlement_raid(dragon, village_b, world)

        assert ok is False
        assert "occupy" in reason.lower()

    def test_resolve_settlement_raid_grants_gold_before_eco_halving(self) -> None:
        coord = OffsetCoord(0, 0)
        settlement = Fort(coord)
        dragon = Dragon(
            kind=DragonKind.RED_FIRE,
            position=coord,
            hp=500,
            atk=1000,
            dfn=90,
            gold=0,
        )
        world = GameMap(
            width=10,
            height=10,
            hex_size=30.0,
            orientation="flat",
            tiles={coord: Tile(coord=coord, terrain=Terrain.SETTLEMENT)},
        )

        assert settlement.eco == 100
        res = resolve_settlement_raid(
            dragon,
            settlement,
            world,
            [settlement],
            map_width=10,
            citadel_coord=coord,
        )

        expected_gold = raid_victory_gold_from_eco(100)
        assert res.gold_gained == expected_gold == 50
        assert dragon.gold == expected_gold
        assert settlement.hp == 0
        assert settlement.eco == 50


class TestSettlementCombat:
    def test_one_round_writes_settlement_hp_and_updates_real_dragon(self) -> None:
        settlement = Fort(OffsetCoord(0, 0))
        dragon = Dragon(
            kind=DragonKind.RED_FIRE, position=OffsetCoord(0, 0), hp=500, atk=120, dfn=90
        )

        exchange = settlement.run_combat_round(dragon, _world(), citadel_coord=OffsetCoord(0, 0))

        assert isinstance(exchange, DamageRoundExchange)
        assert exchange.damage_to_target == 66  # 120 * 100 // (100 + settlement_def_round)
        assert exchange.damage_to_dragon == 42  # 90 * 100 // (100 + effective_atk_proxy)
        assert settlement.hp == 734
        assert dragon.hp == 458
        assert dragon.hours_remaining == pytest.approx(23.5)

    def test_loop_callback_controls_continuation_without_stdin(self) -> None:
        settlement = Fort(OffsetCoord(0, 0))
        dragon = Dragon(
            kind=DragonKind.RED_FIRE, position=OffsetCoord(0, 0), hp=500, atk=120, dfn=90
        )
        calls = 0

        def should_continue() -> bool:
            nonlocal calls
            calls += 1
            return False

        result = run_settlement_combat_loop(
            dragon,
            settlement,
            _world(),
            should_continue,
            citadel_coord=OffsetCoord(0, 0),
        )

        assert result.rounds_resolved == 1
        assert result.retreated is True
        assert calls == 1
        assert settlement.hp == 734

    def test_loop_can_fire_raid_bundle_when_settlement_hp_hits_zero(self) -> None:
        settlement = Fort(OffsetCoord(0, 0))
        nearby = Village(OffsetCoord(1, 0), aggression=400)
        dragon = Dragon(
            kind=DragonKind.RED_FIRE, position=OffsetCoord(0, 0), hp=500, atk=1000, dfn=90
        )

        def should_continue() -> bool:
            return True

        result = run_settlement_combat_loop(
            dragon,
            settlement,
            _world(),
            should_continue,
            citadel_coord=OffsetCoord(0, 0),
            settlements=[settlement, nearby],
            map_width=10,
        )

        assert result.rounds_resolved == 2
        assert settlement.hp == 0
        assert settlement.eco == 50
        assert settlement.atk == 74
        assert settlement.dfn == 74
        assert result.spawn_events == (
            Army.spawn_from_settlement(settlement),
            Army.spawn_from_settlement(nearby),
        )
        assert settlement.aggression == 0
        assert nearby.aggression == 0

    def test_combat_round_blocked_when_no_time_to_return_home(self) -> None:
        coord = OffsetCoord(0, 0)
        settlement = Fort(coord)
        dragon = Dragon(
            kind=DragonKind.RED_FIRE,
            position=coord,
            hp=500,
            atk=120,
            dfn=90,
            hours_remaining=0.5,
            speed_hexes_per_hour=10.0,
        )
        world = GameMap(
            width=10,
            height=10,
            hex_size=30.0,
            orientation="flat",
            tiles={coord: Tile(coord=coord, terrain=Terrain.SETTLEMENT)},
        )
        citadel_far = OffsetCoord(5, 0)
        out = resolve_settlement_combat_round(dragon, settlement, world, citadel_coord=citadel_far)
        assert isinstance(out, MoveAttempt)
        assert not out.ok
        assert "citadel" in out.reason.lower() or "nightfall" in out.reason.lower()
        assert settlement.hp == 800
        assert dragon.hours_remaining == pytest.approx(0.5)


class TestRaidDefeat:
    def test_raid_defeat_halves_eco_reduces_power_and_spills_nearby_aggression(self) -> None:
        defeated = City(OffsetCoord(0, 0))
        nearby = Village(OffsetCoord(2, 0))
        outside = Fort(OffsetCoord(4, 0))
        settlements = [defeated, nearby, outside]

        events = defeated.on_raid_defeat(settlements, map_width=10)

        assert nearby_aggression_radius(10) == 3
        assert events == []
        assert defeated.eco == 500
        assert defeated.atk == 64
        assert defeated.dfn == 74
        assert defeated.aggression == 300
        assert nearby.aggression == 150
        assert outside.aggression == 0

    def test_threshold_spawn_resets_aggression(self) -> None:
        fort = Fort(OffsetCoord(4, 4), aggression=250)

        army = fort.add_aggression(50)

        assert army == Army.spawn_from_settlement(fort)
        assert fort.aggression == 0

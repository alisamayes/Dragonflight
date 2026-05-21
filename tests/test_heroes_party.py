"""Tests for Hero's Party wave spawning, stats, and defeat loot."""

from __future__ import annotations

import random
from dataclasses import replace

import pytest

from dragonflight.army import (
    Army,
    ArmyKind,
    HeroesPartyCityPool,
    eligible_heroes_party_cities,
    grant_army_victory_loot,
    heroes_party_victory_gold_from_eco,
    merge_army_stacks,
    pick_heroes_party_cities,
    should_spawn_heroes_party_wave,
    spawn_heroes_party_wave,
    standard_army_victory_gold_from_eco,
)
from dragonflight.dragon import Dragon, DragonKind
from dragonflight.game_tuning import apply_difficulty_preset, default_game_tuning
from dragonflight.hex_coord import OffsetCoord
from dragonflight.settlement import City, Fort, Village


class TestHeroesPartyWaveTiming:
    @pytest.mark.parametrize(
        ("day_index", "expected"),
        [
            (1, False),
            (4, False),
            (5, True),
            (10, True),
            (15, True),
            (0, False),
        ],
    )
    def test_should_spawn_every_fifth_turn_after_zero(self, day_index: int, expected: bool) -> None:
        assert should_spawn_heroes_party_wave(day_index) is expected


class TestHeroesPartyStats:
    def test_spawn_stats_from_city_at_turn_five(self) -> None:
        city = City(OffsetCoord(2, 1))
        city.eco = 1200
        city.atk = 80
        city.dfn = 90

        army = Army.spawn_heroes_party_from_city(city, turn_count=5)

        assert army.kind == ArmyKind.HEROES
        assert army.hp == city.max_hp
        assert army.max_hp == city.max_hp
        assert army.atk == city.atk + 10
        assert army.dfn == city.dfn + 10
        assert army.position == city.position
        assert army.victory_gold == heroes_party_victory_gold_from_eco(1200)
        assert army.victory_gold == 300

    def test_movement_speed_follows_tuning(self) -> None:
        tuning = replace(default_game_tuning(), army_movement_speed=9)
        city = City(OffsetCoord(0, 0))
        army = Army.spawn_heroes_party_from_city(city, turn_count=10, tuning=tuning)
        assert army.movement_speed == 9

    def test_village_spawn_sets_kind_and_ten_percent_loot(self) -> None:
        village = Village(OffsetCoord(0, 0))
        village.eco = 1000
        army = Army.spawn_from_settlement(village)
        assert army.kind == ArmyKind.VILLAGE
        assert army.victory_gold == standard_army_victory_gold_from_eco(1000)
        assert army.victory_gold == village.eco * 10 // 100
        assert army.source_coord == village.position


def _four_cities() -> list[City]:
    return [
        City(OffsetCoord(0, 0)),
        City(OffsetCoord(0, 2)),
        City(OffsetCoord(2, 0)),
        City(OffsetCoord(2, 2)),
    ]


class TestHeroesPartyCitySelection:
    def test_wave_only_spawns_from_live_cities(self) -> None:
        tuning = replace(default_game_tuning(), heroes_party_cities_per_wave=2)
        village = Village(OffsetCoord(0, 0))
        fort = Fort(OffsetCoord(2, 2))
        dead_city = City(OffsetCoord(3, 3))
        dead_city.hp = 0
        live = City(OffsetCoord(1, 0))

        wave, _ = spawn_heroes_party_wave(
            [village, fort, dead_city, live],
            5,
            tuning=tuning,
            rng=random.Random(0),
        )

        assert len(wave) == 1
        assert wave[0].position == live.position
        assert all(a.kind == ArmyKind.HEROES for a in wave)

    def test_rotating_pool_two_waves_cover_all_cities(self) -> None:
        tuning = replace(default_game_tuning(), heroes_party_cities_per_wave=2)
        cities = _four_cities()
        pool = HeroesPartyCityPool()
        rng = random.Random(0)

        wave1, pool = spawn_heroes_party_wave(
            cities, 5, tuning=tuning, pool=pool, rng=rng
        )
        wave2, pool = spawn_heroes_party_wave(
            cities, 10, tuning=tuning, pool=pool, rng=rng
        )

        pos1 = {a.position for a in wave1}
        pos2 = {a.position for a in wave2}
        all_positions = {c.position for c in cities}

        assert len(wave1) == 2
        assert len(wave2) == 2
        assert pos1.isdisjoint(pos2)
        assert pos1 | pos2 == all_positions
        assert all(a.kind == ArmyKind.HEROES for a in wave1 + wave2)
        assert not pool.queue

    def test_wave_three_refreshes_shuffled_pool(self) -> None:
        tuning = replace(default_game_tuning(), heroes_party_cities_per_wave=2)
        cities = _four_cities()
        pool = HeroesPartyCityPool()
        rng = random.Random(0)

        wave1, pool = spawn_heroes_party_wave(
            cities, 5, tuning=tuning, pool=pool, rng=rng
        )
        _, pool = spawn_heroes_party_wave(cities, 10, tuning=tuning, pool=pool, rng=rng)
        wave3, pool = spawn_heroes_party_wave(
            cities, 15, tuning=tuning, pool=pool, rng=rng
        )

        assert len(wave3) == 2
        assert len(pool.queue) == 2

    def test_pool_refresh_after_full_cycle(self) -> None:
        cities = _four_cities()
        eligible = cities
        pool = HeroesPartyCityPool()
        rng = random.Random(0)

        first, pool = pick_heroes_party_cities(eligible, 2, pool, rng)
        second, pool = pick_heroes_party_cities(eligible, 2, pool, rng)
        assert len(first) == 2
        assert len(second) == 2
        assert {c.position for c in first}.isdisjoint({c.position for c in second})
        assert not pool.queue

        third, pool = pick_heroes_party_cities(eligible, 2, pool, rng)
        assert len(third) == 2
        assert len(pool.queue) == 2

    def test_pool_drops_dead_city_coords(self) -> None:
        cities = _four_cities()
        pool = HeroesPartyCityPool(
            queue=[c.position for c in cities] + [OffsetCoord(9, 9)]
        )
        cities[0].hp = 0
        rng = random.Random(0)
        eligible = eligible_heroes_party_cities(cities)

        picked, updated = pick_heroes_party_cities(eligible, 2, pool, rng)

        assert len(picked) == 2
        assert OffsetCoord(9, 9) not in updated.queue
        assert cities[0].position not in updated.queue

    @pytest.mark.parametrize(
        ("level", "expected_count"),
        [("easy", 1), ("normal", 2), ("hard", 3)],
    )
    def test_cities_per_wave_from_difficulty_preset(self, level: str, expected_count: int) -> None:
        tuning = default_game_tuning()
        apply_difficulty_preset(tuning, level)  # type: ignore[arg-type]
        cities = [City(OffsetCoord(i, 0)) for i in range(5)]
        wave, _ = spawn_heroes_party_wave(
            cities, 5, tuning=tuning, rng=random.Random(0)
        )
        assert len(wave) == expected_count

    def test_no_wave_on_non_trigger_turn(self) -> None:
        cities = [City(OffsetCoord(0, 0))]
        wave, pool = spawn_heroes_party_wave(cities, 4)
        assert wave == []
        assert pool.queue == []


class TestArmyVictoryLoot:
    def test_grant_gold_on_heroes_party_defeat(self) -> None:
        dragon = Dragon(DragonKind.RED_FIRE, OffsetCoord(0, 0), gold=100)
        army = Army(
            hp=1,
            max_hp=100,
            atk=1,
            dfn=1,
            movement_speed=8,
            position=OffsetCoord(1, 0),
            kind=ArmyKind.HEROES,
            victory_gold=250,
        )
        granted = grant_army_victory_loot(dragon, army)
        assert granted == 250
        assert dragon.gold == 350
        assert army.victory_gold == 0

    def test_standard_army_grants_stored_loot(self) -> None:
        dragon = Dragon(DragonKind.RED_FIRE, OffsetCoord(0, 0), gold=50)
        army = Army(
            hp=1,
            max_hp=100,
            atk=1,
            dfn=1,
            movement_speed=8,
            position=OffsetCoord(1, 0),
            victory_gold=80,
        )
        assert grant_army_victory_loot(dragon, army) == 80
        assert dragon.gold == 130
        assert army.victory_gold == 0

    def test_grant_only_pays_once(self) -> None:
        dragon = Dragon(DragonKind.RED_FIRE, OffsetCoord(0, 0), gold=0)
        army = Army(
            hp=1,
            max_hp=100,
            atk=1,
            dfn=1,
            movement_speed=8,
            position=OffsetCoord(1, 0),
            kind=ArmyKind.HEROES,
            victory_gold=300,
        )
        assert grant_army_victory_loot(dragon, army) == 300
        assert grant_army_victory_loot(dragon, army) == 0
        assert dragon.gold == 300


class TestHeroesPartyMerge:
    def test_merge_sums_victory_gold_and_keeps_heroes_kind(self) -> None:
        a = Army(
            hp=10,
            max_hp=10,
            atk=5,
            dfn=2,
            movement_speed=4,
            position=OffsetCoord(0, 0),
            kind=ArmyKind.HEROES,
            victory_gold=100,
        )
        b = Army(
            hp=20,
            max_hp=25,
            atk=7,
            dfn=3,
            movement_speed=8,
            position=OffsetCoord(0, 0),
            kind=ArmyKind.VILLAGE,
            victory_gold=50,
        )
        merged = merge_army_stacks([a, b])
        assert len(merged) == 1
        assert merged[0].kind == ArmyKind.HEROES
        assert merged[0].victory_gold == 150

    def test_merge_kind_precedence_city_over_fort_over_village(self) -> None:
        pos = OffsetCoord(0, 0)
        base = dict(hp=10, max_hp=10, atk=1, dfn=1, movement_speed=4, position=pos)
        village = Army(**base, kind=ArmyKind.VILLAGE)
        fort = Army(**base, kind=ArmyKind.FORT)
        city = Army(**base, kind=ArmyKind.CITY)
        assert merge_army_stacks([village, fort])[0].kind == ArmyKind.FORT
        assert merge_army_stacks([village, city])[0].kind == ArmyKind.CITY
        assert merge_army_stacks([fort, city])[0].kind == ArmyKind.CITY
        heroes = Army(**base, kind=ArmyKind.HEROES)
        assert merge_army_stacks([city, heroes])[0].kind == ArmyKind.HEROES

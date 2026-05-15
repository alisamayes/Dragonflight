"""Tests that :class:`~dragonflight.game_tuning.GameTuning` flows into rule outcomes."""

from __future__ import annotations

from dataclasses import replace

import pytest

from dragonflight.army import DEFAULT_ARMY_MOVEMENT_SPEED, Army
from dragonflight.dragon import Dragon, DragonKind
from dragonflight.game_tuning import GameTuning, default_game_tuning, resolve_tuning
from dragonflight.hex_coord import OffsetCoord
from dragonflight.settlement import (
    Village,
    nearby_aggression_radius,
)


def _baseline_tuning() -> GameTuning:
    return default_game_tuning()


class TestDefaultAndValidation:
    def test_default_game_tuning_matches_shipped_constants(self) -> None:
        t = default_game_tuning()
        assert t.army_movement_speed == DEFAULT_ARMY_MOVEMENT_SPEED
        t.validate()

    def test_validate_rejects_invalid_army_speed(self) -> None:
        t = replace(_baseline_tuning(), army_movement_speed=0)
        with pytest.raises(ValueError, match="army_movement_speed"):
            t.validate()

    def test_validate_rejects_invalid_raid_divisor(self) -> None:
        t = replace(_baseline_tuning(), raid_eco_loss_divisor=0)
        with pytest.raises(ValueError, match="raid_eco_loss_divisor"):
            t.validate()

    def test_resolve_tuning_round_trips(self) -> None:
        custom = replace(_baseline_tuning(), army_movement_speed=7)
        assert resolve_tuning(custom).army_movement_speed == 7
        assert resolve_tuning(None).army_movement_speed == DEFAULT_ARMY_MOVEMENT_SPEED


class TestSettlementPhaseTuning:
    def test_zero_hp_heal_follows_tuning(self) -> None:
        slow = replace(_baseline_tuning(), settlement_heal_percent_of_max_at_zero=10)
        fast = replace(_baseline_tuning(), settlement_heal_percent_of_max_at_zero=90)

        s_slow = Village(OffsetCoord(0, 0))
        s_slow.hp = 0
        s_slow.on_settlement_phase_end(tuning=slow)
        assert s_slow.hp == s_slow.max_hp * 10 // 100

        s_fast = Village(OffsetCoord(1, 0))
        s_fast.hp = 0
        s_fast.on_settlement_phase_end(tuning=fast)
        assert s_fast.hp == s_fast.max_hp * 90 // 100

    def test_growth_eco_follows_tuning(self) -> None:
        noneco = replace(_baseline_tuning(), settlement_growth_eco_percent=0)
        boosted = replace(_baseline_tuning(), settlement_growth_eco_percent=20)

        v0 = Village(OffsetCoord(0, 0))
        v0.on_settlement_phase_end(tuning=noneco)
        assert v0.eco == 500

        v1 = Village(OffsetCoord(1, 0))
        v1.on_settlement_phase_end(tuning=boosted)
        assert v1.eco == 600


class TestRaidDefeatTuning:
    def test_raid_eco_and_stat_penalties_follow_tuning(self) -> None:
        soft = replace(
            _baseline_tuning(),
            raid_eco_loss_divisor=10,
            raid_stat_loss=1,
        )
        defeated = Village(OffsetCoord(0, 0))
        defeated.hp = 0
        defeated.eco = 1000
        defeated.atk = 50

        defeated.on_raid_defeat([], map_width=10, tuning=soft)

        assert defeated.eco == 100
        assert defeated.atk == 49


class TestNearbyRadiusTuning:
    def test_nearby_aggression_radius_scales_with_tuning_percent(self) -> None:
        narrow = replace(_baseline_tuning(), nearby_radius_map_width_percent=10)
        wide = replace(_baseline_tuning(), nearby_radius_map_width_percent=50)

        assert nearby_aggression_radius(100, tuning=narrow) == 10
        assert nearby_aggression_radius(100, tuning=wide) == 50


class TestArmySpawnSpeedTuning:
    def test_spawn_from_settlement_speed_follows_tuning(self) -> None:
        snail = replace(_baseline_tuning(), army_movement_speed=3)
        speedy = replace(_baseline_tuning(), army_movement_speed=30)

        v = Village(OffsetCoord(0, 0))
        assert Army.spawn_from_settlement(v, tuning=snail).movement_speed == 3
        assert Army.spawn_from_settlement(v, tuning=speedy).movement_speed == 30


class TestDragonCitadelBaseHealTuning:
    def test_base_heal_percent_is_tunable_when_hours_zero(self) -> None:
        citadel = OffsetCoord(0, 0)
        stingy = replace(
            _baseline_tuning(),
            dragon_citadel_end_of_day_base_heal_percent_of_max=10,
        )
        generous = replace(
            _baseline_tuning(),
            dragon_citadel_end_of_day_base_heal_percent_of_max=80,
        )

        d_small = Dragon(DragonKind.RED_FIRE, citadel, hp=0, max_hp=100)
        d_small.hours_remaining = 0.0
        d_small.begin_new_day_at_citadel(citadel, tuning=stingy)
        assert d_small.hp == 10

        d_big = Dragon(DragonKind.RED_FIRE, citadel, hp=0, max_hp=100)
        d_big.hours_remaining = 0.0
        d_big.begin_new_day_at_citadel(citadel, tuning=generous)
        assert d_big.hp == 80

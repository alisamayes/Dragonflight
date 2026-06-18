"""Tests that :class:`~dragonflight.game_tuning.GameTuning` flows into rule outcomes."""

from __future__ import annotations

from dataclasses import replace

import pytest

from dragonflight.army import DEFAULT_ARMY_MOVEMENT_SPEED, Army
from dragonflight.dragon import Dragon, DragonKind
from dragonflight.game_tuning import (
    DifficultyLevel,
    GameTuning,
    apply_difficulty_preset,
    default_game_tuning,
    difficulty_preset_values,
    resolve_tuning,
)
from dragonflight.hex_coord import OffsetCoord
from dragonflight.settlement import (
    SETTLEMENT_GROWTH_STAT_BONUS,
    City,
    Village,
    max_spill_distance,
    raid_spill_aggression_amount,
)


def _baseline_tuning() -> GameTuning:
    return default_game_tuning()


def _preset_field_names() -> frozenset[str]:
    return frozenset(difficulty_preset_values("normal").keys())


class TestDifficultyPresets:
    @pytest.mark.parametrize("level", ["easy", "normal", "hard"])
    def test_preset_values_match_spec_table(self, level: DifficultyLevel) -> None:
        expected = {
            "easy": {
                "army_movement_speed": 8,
                "heroes_party_cities_per_wave": 1,
                "aggression_decay_per_day": 20,
                "raid_aggression_dropoff_per_tile": 20,
                "settlement_growth_eco_percent": 10,
                "settlement_growth_stat_bonus": 1,
                "raid_eco_loss_divisor": 1.5,
                "raid_stat_loss": 10,
                "settlement_heal_percent_of_max_at_zero": 50,
                "settlement_heal_percent_of_max_when_damaged": 20,
                "dragon_citadel_end_of_day_base_heal_percent_of_max": 70,
            },
            "normal": {
                "army_movement_speed": 12,
                "heroes_party_cities_per_wave": 2,
                "aggression_decay_per_day": 10,
                "raid_aggression_dropoff_per_tile": 10,
                "settlement_growth_eco_percent": 5,
                "settlement_growth_stat_bonus": 3,
                "raid_eco_loss_divisor": 2.0,
                "raid_stat_loss": 6,
                "settlement_heal_percent_of_max_at_zero": 80,
                "settlement_heal_percent_of_max_when_damaged": 40,
                "dragon_citadel_end_of_day_base_heal_percent_of_max": 50,
            },
            "hard": {
                "army_movement_speed": 16,
                "heroes_party_cities_per_wave": 3,
                "aggression_decay_per_day": 0,
                "raid_aggression_dropoff_per_tile": 5,
                "settlement_growth_eco_percent": 0,
                "settlement_growth_stat_bonus": 5,
                "raid_eco_loss_divisor": 3.0,
                "raid_stat_loss": 3,
                "settlement_heal_percent_of_max_at_zero": 100,
                "settlement_heal_percent_of_max_when_damaged": 60,
                "dragon_citadel_end_of_day_base_heal_percent_of_max": 30,
            },
        }[level]
        assert difficulty_preset_values(level) == expected

    def test_default_game_tuning_equals_normal_preset(self) -> None:
        t = default_game_tuning()
        normal = GameTuning(
            army_movement_speed=0,
            heroes_party_cities_per_wave=0,
            aggression_decay_per_day=0,
            raid_aggression_dropoff_per_tile=0,
            settlement_heal_percent_of_max_at_zero=0,
            settlement_heal_percent_of_max_when_damaged=0,
            settlement_growth_eco_percent=0,
            settlement_growth_stat_bonus=SETTLEMENT_GROWTH_STAT_BONUS,
            raid_eco_loss_divisor=1.0,
            raid_stat_loss=0,
            dragon_citadel_end_of_day_base_heal_percent_of_max=0,
            world_event_chance_percent=50,
        )
        apply_difficulty_preset(normal, "normal")
        for name in _preset_field_names():
            assert getattr(t, name) == getattr(normal, name)
        assert t.settlement_growth_stat_bonus == SETTLEMENT_GROWTH_STAT_BONUS

    def test_apply_preset_sets_stat_bonus_per_difficulty(self) -> None:
        t = default_game_tuning()
        apply_difficulty_preset(t, "easy")
        assert t.settlement_growth_stat_bonus == 1
        apply_difficulty_preset(t, "normal")
        assert t.settlement_growth_stat_bonus == 3
        apply_difficulty_preset(t, "hard")
        assert t.settlement_growth_stat_bonus == 5


class TestDefaultAndValidation:
    def test_default_game_tuning_matches_shipped_constants(self) -> None:
        t = default_game_tuning()
        assert t.army_movement_speed == DEFAULT_ARMY_MOVEMENT_SPEED
        t.validate()

    def test_validate_rejects_invalid_army_speed(self) -> None:
        t = replace(_baseline_tuning(), army_movement_speed=0)
        with pytest.raises(ValueError, match="army_movement_speed"):
            t.validate()

    def test_validate_rejects_negative_heroes_party_cities(self) -> None:
        t = replace(_baseline_tuning(), heroes_party_cities_per_wave=-1)
        with pytest.raises(ValueError, match="heroes_party_cities_per_wave"):
            t.validate()

    def test_validate_rejects_invalid_raid_divisor(self) -> None:
        t = replace(_baseline_tuning(), raid_eco_loss_divisor=0.5)
        with pytest.raises(ValueError, match="raid_eco_loss_divisor"):
            t.validate()

    def test_validate_rejects_stat_bonus_above_ten(self) -> None:
        t = replace(_baseline_tuning(), settlement_growth_stat_bonus=11)
        with pytest.raises(ValueError, match="settlement_growth_stat_bonus"):
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
        # growth uses (x% of current eco) + (10% of starting eco); x=0 leaves the floor term
        assert v0.eco == 550

        v1 = Village(OffsetCoord(1, 0))
        v1.on_settlement_phase_end(tuning=boosted)
        assert v1.eco == 650


class TestRaidDefeatTuning:
    def test_raid_eco_and_stat_penalties_follow_tuning(self) -> None:
        soft = replace(
            _baseline_tuning(),
            raid_eco_loss_divisor=10.0,
            raid_stat_loss=1,
        )
        defeated = Village(OffsetCoord(0, 0))
        defeated.hp = 0
        defeated.eco = 1000
        defeated.atk = 50

        defeated.on_raid_defeat([], tuning=soft)

        assert defeated.eco == 100
        assert defeated.atk == 49

    def test_raid_eco_loss_supports_fractional_divisor(self) -> None:
        easy = replace(_baseline_tuning(), raid_eco_loss_divisor=1.5)
        defeated = Village(OffsetCoord(0, 0))
        defeated.hp = 0
        defeated.eco = 1000

        defeated.on_raid_defeat([], tuning=easy)

        assert defeated.eco == 666


class TestAggressionDecayTuning:
    def test_validate_rejects_aggression_decay_out_of_range(self) -> None:
        low = replace(_baseline_tuning(), aggression_decay_per_day=-1)
        high = replace(_baseline_tuning(), aggression_decay_per_day=51)
        with pytest.raises(ValueError, match="aggression_decay_per_day"):
            low.validate()
        with pytest.raises(ValueError, match="aggression_decay_per_day"):
            high.validate()

    def test_default_includes_normal_decay_preset(self) -> None:
        t = default_game_tuning()
        assert t.aggression_decay_per_day == 10


class TestRaidAggressionDropoffTuning:
    def test_raid_spill_amount_scales_with_dropoff(self) -> None:
        steep = replace(_baseline_tuning(), raid_aggression_dropoff_per_tile=20)
        gentle = replace(_baseline_tuning(), raid_aggression_dropoff_per_tile=5)

        assert (
            raid_spill_aggression_amount(2, dropoff=steep.raid_aggression_dropoff_per_tile) == 260
        )
        assert (
            raid_spill_aggression_amount(2, dropoff=gentle.raid_aggression_dropoff_per_tile) == 290
        )

    def test_max_spill_distance_matches_normal_preset(self) -> None:
        t = _baseline_tuning()
        assert t.raid_aggression_dropoff_per_tile == 10
        assert max_spill_distance(t.raid_aggression_dropoff_per_tile) == 29
        assert raid_spill_aggression_amount(30, dropoff=t.raid_aggression_dropoff_per_tile) == 0

    def test_validate_rejects_dropoff_out_of_range(self) -> None:
        low = replace(_baseline_tuning(), raid_aggression_dropoff_per_tile=0)
        high = replace(_baseline_tuning(), raid_aggression_dropoff_per_tile=51)
        with pytest.raises(ValueError, match="raid_aggression_dropoff_per_tile"):
            low.validate()
        with pytest.raises(ValueError, match="raid_aggression_dropoff_per_tile"):
            high.validate()

    def test_on_raid_defeat_spill_follows_custom_dropoff(self) -> None:
        hard = replace(_baseline_tuning(), raid_aggression_dropoff_per_tile=5)
        defeated = City(OffsetCoord(0, 0))
        nearby = Village(OffsetCoord(1, 0))

        defeated.on_raid_defeat([defeated, nearby], tuning=hard)

        assert nearby.aggression == raid_spill_aggression_amount(1, dropoff=5)


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

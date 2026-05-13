"""Tests for dragon stat upgrade pricing and draft application (spec §7)."""

from __future__ import annotations

from dragonflight.dragon import Dragon, DragonKind
from dragonflight.dragon_progression import (
    DragonUpgradeBaseline,
    DragonUpgradeStat,
    apply_dragon_upgrade_draft,
    dragon_stat_upgrade_gold_cost,
    dragon_upgrade_baseline_from_dragon,
    marginal_dragon_stat_upgrade_cost,
    total_dragon_upgrade_draft_cost,
)
from dragonflight.hex_coord import OffsetCoord


def test_spec_cost_level_9_fifth_atk_is_480() -> None:
    baseline = DragonUpgradeBaseline(
        level=9,
        gold=10_000,
        hp=100,
        max_hp=100,
        atk=10,
        dfn=10,
        flight_range_hexes=10,
        speed_hexes_per_hour=5.0,
        hp_upgrades=0,
        atk_upgrades=4,
        dfn_upgrades=0,
        flight_range_upgrades=0,
        speed_upgrades=0,
    )
    cost = marginal_dragon_stat_upgrade_cost(baseline, [], DragonUpgradeStat.ATK)
    assert cost == 480
    assert dragon_stat_upgrade_gold_cost(9, 5) == 480


def test_sequential_pricing_first_two_atk_at_level_1() -> None:
    baseline = DragonUpgradeBaseline(
        level=1,
        gold=10_000,
        hp=50,
        max_hp=50,
        atk=10,
        dfn=10,
        flight_range_hexes=10,
        speed_hexes_per_hour=10.0,
        hp_upgrades=0,
        atk_upgrades=0,
        dfn_upgrades=0,
        flight_range_upgrades=0,
        speed_upgrades=0,
    )
    first = marginal_dragon_stat_upgrade_cost(baseline, [], DragonUpgradeStat.ATK)
    second = marginal_dragon_stat_upgrade_cost(
        baseline, [DragonUpgradeStat.ATK], DragonUpgradeStat.ATK
    )
    assert first == 200 + 1 * 20 + 1 * 20
    assert second == 200 + 2 * 20 + 2 * 20
    draft = [DragonUpgradeStat.ATK, DragonUpgradeStat.ATK]
    assert total_dragon_upgrade_draft_cost(baseline, draft) == first + second


def test_apply_draft_updates_gold_stats_level_and_counters() -> None:
    c = OffsetCoord(0, 0)
    dragon = Dragon(
        DragonKind.RED_FIRE,
        c,
        level=3,
        hp=100,
        max_hp=100,
        atk=50,
        dfn=40,
        flight_range_hexes=12,
        speed_hexes_per_hour=6.0,
        gold=900,
    )
    baseline = dragon_upgrade_baseline_from_dragon(dragon)
    draft = [DragonUpgradeStat.HP, DragonUpgradeStat.ATK]
    total = total_dragon_upgrade_draft_cost(baseline, draft)
    assert total > 0
    apply_dragon_upgrade_draft(dragon, draft)
    assert dragon.gold == baseline.gold - total
    assert dragon.level == baseline.level + 2
    assert dragon.max_hp == baseline.max_hp + 50
    assert dragon.hp == baseline.hp + 50
    assert dragon.atk == baseline.atk + 10
    assert dragon.hp_upgrades == 1
    assert dragon.atk_upgrades == 1

"""Tests for deterministic combat arithmetic (spec §8)."""

from __future__ import annotations

from dragonflight.combat_math import damage_dragon_attacks, damage_human_or_army_attacks


def test_human_damage_floors_at_zero() -> None:
    assert damage_human_or_army_attacks(0, 50) == 0
    assert damage_human_or_army_attacks(1, 1900) == 0
    assert damage_human_or_army_attacks(12, 4) == 11  # 1200 // 104


def test_dragon_damage_floors_at_one() -> None:
    assert damage_dragon_attacks(1, 999_999) == 1
    assert damage_dragon_attacks(20, 5) == 19  # 2000 // 105

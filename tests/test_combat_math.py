"""Tests for deterministic combat arithmetic (spec §8)."""

from __future__ import annotations

from dragonflight.combat_math import damage_dragon_attacks, damage_human_or_army_attacks


def test_human_damage_floors_at_zero() -> None:
    assert damage_human_or_army_attacks(3, 9) == 0
    assert damage_human_or_army_attacks(12, 4) == 8


def test_dragon_damage_floors_at_one() -> None:
    assert damage_dragon_attacks(5, 20) == 1
    assert damage_dragon_attacks(20, 5) == 15

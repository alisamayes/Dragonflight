"""Pure combat arithmetic for stat-based exchanges (spec §8).

Keeps floors and formulae centralised so the dragon and army/settlement combat
loops share one rule surface once those systems arrive.
"""

from __future__ import annotations


def damage_human_or_army_attacks(attacker_atk: int, defender_dfn: int) -> int:
    """Damage from a human/army attacker; floors at zero (negative becomes 0)."""
    dealt = attacker_atk - defender_dfn
    return dealt if dealt > 0 else 0


def damage_dragon_attacks(dragon_atk: int, defender_dfn: int) -> int:
    """Damage from the dragon toward a defender; dragon-dealt floors at 1 (spec §8)."""
    dealt = dragon_atk - defender_dfn
    return max(1, dealt)

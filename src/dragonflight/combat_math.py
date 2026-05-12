"""Pure combat arithmetic for stat-based exchanges (spec §8).

Each damage round uses multiplicative mitigation (integer division)::

    damage = attacker_ATK * 100 // (100 + defender_DFN)

Human/army outgoing damage uses this value, floored at 0. Dragon outgoing damage
uses the same base value, then ``max(1, …)`` so dragon-dealt damage never drops
below 1 in MVP (spec §8).
"""

from __future__ import annotations


def damage_human_or_army_attacks(attacker_atk: int, defender_dfn: int) -> int:
    """Damage from a human/army attacker; floors at zero."""
    dealt = attacker_atk * 100 // (100 + defender_dfn)
    return dealt if dealt > 0 else 0


def damage_dragon_attacks(dragon_atk: int, defender_dfn: int) -> int:
    """Damage from the dragon toward a defender; dragon-dealt floors at 1 (spec §8)."""
    dealt = dragon_atk * 100 // (100 + defender_dfn)
    return max(1, dealt)

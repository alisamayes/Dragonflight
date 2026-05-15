"""Citadel defence state for army-phase attacks (spec §§2, 10)."""

from __future__ import annotations

from dataclasses import dataclass

from .hex_coord import OffsetCoord

DEFAULT_CITADEL_HP: int = 3
CITADEL_HP_LOSS_PER_ARMY_ATTACK: int = 1


@dataclass(slots=True)
class CitadelState:
    """Mutable citadel HP tracked by the simulation loop."""

    position: OffsetCoord
    hp: int = DEFAULT_CITADEL_HP

    def apply_army_attack(self) -> None:
        """Reduce HP by one per attacking army stack (spec §10)."""

        self.hp = max(0, self.hp - CITADEL_HP_LOSS_PER_ARMY_ATTACK)

    def is_destroyed(self) -> bool:
        """Return whether the citadel has been reduced to zero HP."""

        return self.hp <= 0


__all__ = [
    "CITADEL_HP_LOSS_PER_ARMY_ATTACK",
    "DEFAULT_CITADEL_HP",
    "CitadelState",
]

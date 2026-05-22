"""Session-scoped gameplay tuning (game options).

Pass a shared :class:`GameTuning` instance from the play session into simulation
routes; omit it to use shipped defaults mirrored from legacy module constants.

``default_game_tuning()`` loads values lazily inside the function body to avoid
import cycles between this module and :mod:`~dragonflight.settlement`.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

DifficultyLevel = Literal["easy", "normal", "hard"]

_DIFFICULTY_PRESETS: dict[DifficultyLevel, dict[str, int | float]] = {
    "easy": {
        "army_movement_speed": 8,
        "heroes_party_cities_per_wave": 1,
        "raid_aggression_dropoff_per_tile": 20,
        "settlement_growth_eco_percent": 10,
        "raid_eco_loss_divisor": 1.5,
        "raid_stat_loss": 10,
        "settlement_heal_percent_of_max_at_zero": 50,
        "settlement_heal_percent_of_max_when_damaged": 20,
        "dragon_citadel_end_of_day_base_heal_percent_of_max": 70,
    },
    "normal": {
        "army_movement_speed": 10,
        "heroes_party_cities_per_wave": 2,
        "raid_aggression_dropoff_per_tile": 10,
        "settlement_growth_eco_percent": 5,
        "raid_eco_loss_divisor": 2.0,
        "raid_stat_loss": 6,
        "settlement_heal_percent_of_max_at_zero": 80,
        "settlement_heal_percent_of_max_when_damaged": 40,
        "dragon_citadel_end_of_day_base_heal_percent_of_max": 50,
    },
    "hard": {
        "army_movement_speed": 14,
        "heroes_party_cities_per_wave": 3,
        "raid_aggression_dropoff_per_tile": 5,
        "settlement_growth_eco_percent": 0,
        "raid_eco_loss_divisor": 3.0,
        "raid_stat_loss": 3,
        "settlement_heal_percent_of_max_at_zero": 100,
        "settlement_heal_percent_of_max_when_damaged": 60,
        "dragon_citadel_end_of_day_base_heal_percent_of_max": 30,
    },
}


@dataclass(slots=True)
class GameTuning:
    """Adjustable rule scalars; defaults mirror shipped ``DEFAULT_*`` constants."""

    army_movement_speed: int
    heroes_party_cities_per_wave: int
    raid_aggression_dropoff_per_tile: int
    settlement_heal_percent_of_max_at_zero: int
    settlement_heal_percent_of_max_when_damaged: int
    settlement_growth_eco_percent: int
    settlement_growth_stat_bonus: int
    raid_eco_loss_divisor: float
    raid_stat_loss: int
    dragon_citadel_end_of_day_base_heal_percent_of_max: int

    def validate(self) -> None:
        """Raise :exc:`ValueError` if any field is outside supported ranges."""

        def _pct(label: str, v: int) -> None:
            if not (0 <= v <= 100):
                raise ValueError(f"{label} must be between 0 and 100 inclusive, got {v}")

        if self.army_movement_speed < 1:
            raise ValueError(
                f"army_movement_speed must be >= 1, got {self.army_movement_speed}",
            )
        if self.heroes_party_cities_per_wave < 0:
            raise ValueError(
                "heroes_party_cities_per_wave must be >= 0, "
                f"got {self.heroes_party_cities_per_wave}",
            )
        if not (1 <= self.raid_aggression_dropoff_per_tile <= 50):
            raise ValueError(
                "raid_aggression_dropoff_per_tile must be between 1 and 50 inclusive, "
                f"got {self.raid_aggression_dropoff_per_tile}",
            )
        _pct(
            "settlement_heal_percent_of_max_at_zero",
            self.settlement_heal_percent_of_max_at_zero,
        )
        _pct(
            "settlement_heal_percent_of_max_when_damaged",
            self.settlement_heal_percent_of_max_when_damaged,
        )
        _pct("settlement_growth_eco_percent", self.settlement_growth_eco_percent)
        if self.settlement_growth_stat_bonus < 0:
            raise ValueError(
                "settlement_growth_stat_bonus must be >= 0, "
                f"got {self.settlement_growth_stat_bonus}",
            )
        if self.raid_eco_loss_divisor < 1.0:
            raise ValueError(
                f"raid_eco_loss_divisor must be >= 1, got {self.raid_eco_loss_divisor}",
            )
        if self.raid_stat_loss < 0:
            raise ValueError(f"raid_stat_loss must be >= 0, got {self.raid_stat_loss}")
        _pct(
            "dragon_citadel_end_of_day_base_heal_percent_of_max",
            self.dragon_citadel_end_of_day_base_heal_percent_of_max,
        )


def difficulty_preset_values(level: DifficultyLevel) -> dict[str, int | float]:
    """Return a copy of the scalar fields set by ``apply_difficulty_preset``."""

    return dict(_DIFFICULTY_PRESETS[level])


def apply_difficulty_preset(tuning: GameTuning, level: DifficultyLevel) -> None:
    """Apply Easy / Normal / Hard scalars; leaves ``settlement_growth_stat_bonus`` unchanged."""

    for key, value in _DIFFICULTY_PRESETS[level].items():
        setattr(tuning, key, value)


def default_game_tuning() -> GameTuning:
    """Build tuning at the Normal difficulty preset (shipped default)."""

    from .settlement import SETTLEMENT_GROWTH_STAT_BONUS

    tuning = GameTuning(
        army_movement_speed=0,
        heroes_party_cities_per_wave=0,
        raid_aggression_dropoff_per_tile=0,
        settlement_heal_percent_of_max_at_zero=0,
        settlement_heal_percent_of_max_when_damaged=0,
        settlement_growth_eco_percent=0,
        settlement_growth_stat_bonus=SETTLEMENT_GROWTH_STAT_BONUS,
        raid_eco_loss_divisor=1.0,
        raid_stat_loss=0,
        dragon_citadel_end_of_day_base_heal_percent_of_max=0,
    )
    apply_difficulty_preset(tuning, "normal")
    return tuning


def resolve_tuning(tuning: GameTuning | None) -> GameTuning:
    """Return ``tuning`` or :func:`default_game_tuning` when ``None``."""

    return tuning if tuning is not None else default_game_tuning()


__all__ = [
    "DifficultyLevel",
    "GameTuning",
    "apply_difficulty_preset",
    "default_game_tuning",
    "difficulty_preset_values",
    "resolve_tuning",
]

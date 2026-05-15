"""Session-scoped gameplay tuning (game options).

Pass a shared :class:`GameTuning` instance from the play session into simulation
routes; omit it to use shipped defaults mirrored from legacy module constants.

``default_game_tuning()`` loads values lazily inside the function body to avoid
import cycles between this module and :mod:`~dragonflight.settlement`.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(slots=True)
class GameTuning:
    """Adjustable rule scalars; defaults mirror shipped ``DEFAULT_*`` constants."""

    army_movement_speed: int
    nearby_radius_map_width_percent: int
    settlement_heal_percent_of_max_at_zero: int
    settlement_heal_percent_of_max_when_damaged: int
    settlement_growth_eco_percent: int
    settlement_growth_stat_bonus: int
    settlement_eco_growth_scale_percent: int
    raid_eco_loss_divisor: int
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
        _pct("nearby_radius_map_width_percent", self.nearby_radius_map_width_percent)
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
        if not (1 <= self.settlement_eco_growth_scale_percent <= 300):
            raise ValueError(
                "settlement_eco_growth_scale_percent must be between 1 and 300 inclusive, "
                f"got {self.settlement_eco_growth_scale_percent}",
            )
        if self.raid_eco_loss_divisor < 1:
            raise ValueError(
                f"raid_eco_loss_divisor must be >= 1, got {self.raid_eco_loss_divisor}",
            )
        if self.raid_stat_loss < 0:
            raise ValueError(f"raid_stat_loss must be >= 0, got {self.raid_stat_loss}")
        _pct(
            "dragon_citadel_end_of_day_base_heal_percent_of_max",
            self.dragon_citadel_end_of_day_base_heal_percent_of_max,
        )


def default_game_tuning() -> GameTuning:
    """Build tuning from ``DEFAULT_*`` / ``SETTLEMENT_*`` / ``RAID_*`` constants."""

    from .army import DEFAULT_ARMY_MOVEMENT_SPEED
    from .dragon_defaults import DRAGON_CITADEL_END_OF_DAY_BASE_HEAL_PERCENT_OF_MAX
    from .settlement import (
        DEFAULT_NEARBY_RADIUS_MAP_WIDTH_PERCENT,
        RAID_ECO_LOSS_DIVISOR,
        RAID_STAT_LOSS,
        SETTLEMENT_GROWTH_ECO_PERCENT,
        SETTLEMENT_GROWTH_STAT_BONUS,
        SETTLEMENT_HEAL_PERCENT_OF_MAX_AT_ZERO,
        SETTLEMENT_HEAL_PERCENT_OF_MAX_WHEN_DAMAGED,
    )

    return GameTuning(
        army_movement_speed=DEFAULT_ARMY_MOVEMENT_SPEED,
        nearby_radius_map_width_percent=DEFAULT_NEARBY_RADIUS_MAP_WIDTH_PERCENT,
        settlement_heal_percent_of_max_at_zero=SETTLEMENT_HEAL_PERCENT_OF_MAX_AT_ZERO,
        settlement_heal_percent_of_max_when_damaged=(SETTLEMENT_HEAL_PERCENT_OF_MAX_WHEN_DAMAGED),
        settlement_growth_eco_percent=SETTLEMENT_GROWTH_ECO_PERCENT,
        settlement_growth_stat_bonus=SETTLEMENT_GROWTH_STAT_BONUS,
        settlement_eco_growth_scale_percent=100,
        raid_eco_loss_divisor=RAID_ECO_LOSS_DIVISOR,
        raid_stat_loss=RAID_STAT_LOSS,
        dragon_citadel_end_of_day_base_heal_percent_of_max=(
            DRAGON_CITADEL_END_OF_DAY_BASE_HEAL_PERCENT_OF_MAX
        ),
    )


def resolve_tuning(tuning: GameTuning | None) -> GameTuning:
    """Return ``tuning`` or :func:`default_game_tuning` when ``None``."""

    return tuning if tuning is not None else default_game_tuning()


__all__ = ["GameTuning", "default_game_tuning", "resolve_tuning"]

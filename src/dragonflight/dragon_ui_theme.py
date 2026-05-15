"""Dragon-specific UI theme tokens for gameplay chrome.

This module is the single source of truth for per-dragon presentation colors:
accent stripe, tinted panel fill, pale gameplay border, and remaining-hour bar.
"""

from __future__ import annotations

from dataclasses import dataclass

from .dragon import DragonKind


@dataclass(frozen=True, slots=True)
class DragonUITheme:
    """Gameplay UI colors for one dragon archetype."""

    accent_rgb: tuple[int, int, int]
    panel_tint_rgb: tuple[int, int, int]
    border_rgb: tuple[int, int, int]
    hour_remain_rgb: tuple[int, int, int]


_THEME_BY_KIND: dict[DragonKind, DragonUITheme] = {
    DragonKind.RED_FIRE: DragonUITheme(
        accent_rgb=(220, 70, 66),
        panel_tint_rgb=(71, 46, 54),
        border_rgb=(222, 160, 158),
        hour_remain_rgb=(232, 92, 88),
    ),
    DragonKind.BLACK_TANK: DragonUITheme(
        accent_rgb=(96, 96, 104),
        panel_tint_rgb=(49, 50, 58),
        border_rgb=(180, 182, 192),
        hour_remain_rgb=(140, 144, 160),
    ),
    DragonKind.GREEN_LIFE: DragonUITheme(
        accent_rgb=(72, 175, 96),
        panel_tint_rgb=(44, 63, 56),
        border_rgb=(163, 217, 174),
        hour_remain_rgb=(95, 194, 118),
    ),
    DragonKind.YELLOW_CHRONO: DragonUITheme(
        accent_rgb=(214, 171, 66),
        panel_tint_rgb=(66, 59, 47),
        border_rgb=(228, 209, 154),
        hour_remain_rgb=(230, 188, 78),
    ),
    DragonKind.PURPLE_FROST: DragonUITheme(
        accent_rgb=(158, 98, 214),
        panel_tint_rgb=(58, 50, 74),
        border_rgb=(204, 176, 232),
        hour_remain_rgb=(176, 122, 228),
    ),
    DragonKind.BROWN_EARTH: DragonUITheme(
        accent_rgb=(150, 100, 64),
        panel_tint_rgb=(58, 50, 45),
        border_rgb=(205, 178, 154),
        hour_remain_rgb=(173, 122, 83),
    ),
}


def dragon_ui_theme_for_kind(kind: DragonKind) -> DragonUITheme:
    """Return the gameplay UI theme for ``kind``."""
    return _THEME_BY_KIND[kind]

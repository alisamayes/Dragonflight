"""Army portrait / map sprite paths (``assets/Armies/…`` under the project root).

Paths are resolved from :func:`repository_root` so they stay portable across machines
(no hard-coded drive letters).
"""

from __future__ import annotations

from pathlib import Path

import pygame

from .army import ArmyKind
from .dragon_art import repository_root, scaled_to_fit

_PIXEL_DIR = "112 - pixel art"
_DETAILED_DIR = "256 - detailed"

# Pixel basename, detailed basename (filenames on disk, including typos).
_ARMY_ART_FILENAMES: dict[ArmyKind, tuple[str, str]] = {
    ArmyKind.VILLAGE: ("village_peasants", "village_peasants"),
    ArmyKind.FORT: ("fort_footsoldier_pixel", "fort_footsoldiers"),
    ArmyKind.CITY: ("city_knights_pixel", "city_kights"),
    ArmyKind.HEROES: ("heros_army_pixel", "heros_army"),
}

_pixel_loaded: dict[ArmyKind, pygame.Surface | None] = {}
_detailed_loaded: dict[ArmyKind, pygame.Surface | None] = {}
_marker_scaled: dict[tuple[ArmyKind, int], pygame.Surface] = {}


def armies_assets_dir() -> Path:
    return repository_root() / "assets" / "Armies"


def pixel_sprite_path(kind: ArmyKind) -> Path:
    name = _ARMY_ART_FILENAMES[kind][0]
    return armies_assets_dir() / _PIXEL_DIR / f"{name}.png"


def detailed_sprite_path(kind: ArmyKind) -> Path:
    name = _ARMY_ART_FILENAMES[kind][1]
    return armies_assets_dir() / _DETAILED_DIR / f"{name}.png"


def _load_png(path: Path) -> pygame.Surface | None:
    if not path.is_file():
        return None
    return pygame.image.load(str(path)).convert_alpha()


def load_pixel_sprite(kind: ArmyKind) -> pygame.Surface | None:
    """Cached pixel sprite for ``kind``; ``None`` if the file is missing."""

    if kind in _pixel_loaded:
        return _pixel_loaded[kind]
    surf = _load_png(pixel_sprite_path(kind))
    _pixel_loaded[kind] = surf
    return surf


def load_detailed_sprite(kind: ArmyKind) -> pygame.Surface | None:
    """Cached detailed portrait for ``kind``; ``None`` if the file is missing."""

    if kind in _detailed_loaded:
        return _detailed_loaded[kind]
    surf = _load_png(detailed_sprite_path(kind))
    _detailed_loaded[kind] = surf
    return surf


def map_marker_surface(kind: ArmyKind, side_px: int) -> pygame.Surface | None:
    """Square map marker scaled to ``side_px`` (cached by kind and pixel size)."""

    base = load_pixel_sprite(kind)
    if base is None:
        return None
    side_px = max(4, int(side_px))
    key = (kind, side_px)
    cached = _marker_scaled.get(key)
    if cached is not None:
        return cached
    scaled = pygame.transform.smoothscale(base, (side_px, side_px))
    if len(_marker_scaled) > 96:
        _marker_scaled.clear()
    _marker_scaled[key] = scaled
    return scaled


def clear_art_caches() -> None:
    """Drop loaded / scaled art (for tests or hot reload)."""

    _pixel_loaded.clear()
    _detailed_loaded.clear()
    _marker_scaled.clear()


__all__ = [
    "armies_assets_dir",
    "clear_art_caches",
    "detailed_sprite_path",
    "load_detailed_sprite",
    "load_pixel_sprite",
    "map_marker_surface",
    "pixel_sprite_path",
    "scaled_to_fit",
]

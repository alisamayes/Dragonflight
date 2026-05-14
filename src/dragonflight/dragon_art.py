"""Dragon portrait / map sprite paths (``assets/Dragons/…`` under the project root).

Paths are resolved from :func:`repository_root` so they stay portable across machines
(no hard-coded drive letters).
"""

from __future__ import annotations

from pathlib import Path

import pygame

from .dragon import DragonKind

# Basenames under ``assets/Dragons/Pixel`` and ``assets/Dragons/Detailed``.
_DRAGON_ART_STEMS: dict[DragonKind, str] = {
    DragonKind.RED_FIRE: "Redgon",
    DragonKind.BLACK_TANK: "Blackgon",
    DragonKind.GREEN_LIFE: "Greengon",
    DragonKind.YELLOW_CHRONO: "Yellowgon",
    DragonKind.PURPLE_FROST: "Purplegon",
    DragonKind.BROWN_EARTH: "Browngon",
}

_pixel_loaded: dict[DragonKind, pygame.Surface | None] = {}
_detailed_loaded: dict[DragonKind, pygame.Surface | None] = {}
_marker_scaled: dict[tuple[DragonKind, int], pygame.Surface] = {}


def repository_root() -> Path:
    """Directory that contains ``src/`` and ``assets/`` (the Dragonflight project root)."""

    return Path(__file__).resolve().parents[2]


def dragons_assets_dir() -> Path:
    return repository_root() / "assets" / "Dragons"


def pixel_sprite_path(kind: DragonKind) -> Path:
    stem = _DRAGON_ART_STEMS[kind]
    return dragons_assets_dir() / "Pixel" / f"{stem} Pixel.png"


def detailed_sprite_path(kind: DragonKind) -> Path:
    stem = _DRAGON_ART_STEMS[kind]
    return dragons_assets_dir() / "Detailed" / f"{stem} Sprite.png"


def _load_png(path: Path) -> pygame.Surface | None:
    if not path.is_file():
        return None
    return pygame.image.load(str(path)).convert_alpha()


def load_pixel_sprite(kind: DragonKind) -> pygame.Surface | None:
    """Cached pixel sprite for ``kind``; ``None`` if the file is missing."""

    if kind in _pixel_loaded:
        return _pixel_loaded[kind]
    surf = _load_png(pixel_sprite_path(kind))
    _pixel_loaded[kind] = surf
    return surf


def load_detailed_sprite(kind: DragonKind) -> pygame.Surface | None:
    """Cached detailed portrait for ``kind``; ``None`` if the file is missing."""

    if kind in _detailed_loaded:
        return _detailed_loaded[kind]
    surf = _load_png(detailed_sprite_path(kind))
    _detailed_loaded[kind] = surf
    return surf


def map_marker_surface(kind: DragonKind, side_px: int) -> pygame.Surface | None:
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


def scaled_to_fit(
    source: pygame.Surface,
    max_width: int,
    max_height: int,
) -> pygame.Surface:
    """Uniform scale so the image fits inside ``max_width × max_height``."""

    w, h = source.get_size()
    mw, mh = max(1, int(max_width)), max(1, int(max_height))
    scale = min(mw / float(w), mh / float(h))
    if scale >= 1.0:
        return source
    tw = max(1, int(round(w * scale)))
    th = max(1, int(round(h * scale)))
    return pygame.transform.smoothscale(source, (tw, th))


def clear_art_caches() -> None:
    """Drop loaded / scaled art (for tests or hot reload)."""

    _pixel_loaded.clear()
    _detailed_loaded.clear()
    _marker_scaled.clear()


__all__ = [
    "clear_art_caches",
    "detailed_sprite_path",
    "dragons_assets_dir",
    "load_detailed_sprite",
    "load_pixel_sprite",
    "map_marker_surface",
    "pixel_sprite_path",
    "repository_root",
    "scaled_to_fit",
]

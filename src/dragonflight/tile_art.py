"""Settlement / citadel map tile sprites (``assets/Tiles/…`` under the project root).

Paths are resolved from :func:`dragon_art.repository_root` so they stay portable
across machines (no hard-coded drive letters).
"""

from __future__ import annotations

from pathlib import Path
from typing import Literal, TypeAlias

import pygame

from .dragon_art import repository_root, scaled_to_fit
from .settlement import SettlementType
from .terrain import Terrain

TileArtKey: TypeAlias = SettlementType | Literal[Terrain.CITADEL]

_TILE_BASENAMES: dict[TileArtKey, str] = {
    SettlementType.VILLAGE: "Village",
    SettlementType.CITY: "City",
    SettlementType.FORT: "Fort",
    Terrain.CITADEL: "Citadel",
}

#: Matches :data:`play_session._MUTE_FACTOR` for unreachable hex muting.
TILE_SPRITE_MUTE_FACTOR: float = 0.42

#: Scale sprite to fit inside a hex (``hex_size`` is centre-to-corner radius).
TILE_SPRITE_HEX_SCALE: float = 1.6

_loaded: dict[TileArtKey, pygame.Surface | None] = {}
_map_scaled: dict[tuple[TileArtKey, int, bool], pygame.Surface] = {}


def tiles_assets_dir() -> Path:
    return repository_root() / "assets" / "Tiles"


def tile_sprite_path(key: TileArtKey) -> Path:
    return tiles_assets_dir() / f"{_TILE_BASENAMES[key]}.png"


def _load_png(path: Path) -> pygame.Surface | None:
    if not path.is_file():
        return None
    return pygame.image.load(str(path)).convert_alpha()


def load_tile_sprite(key: TileArtKey) -> pygame.Surface | None:
    """Cached PNG for ``key``; ``None`` if the file is missing."""

    if key in _loaded:
        return _loaded[key]
    surf = _load_png(tile_sprite_path(key))
    _loaded[key] = surf
    return surf


def _mute_surface(source: pygame.Surface, factor: float) -> pygame.Surface:
    """Darken ``source`` to mirror unreachable-hex RGB muting."""

    overlay = pygame.Surface(source.get_size(), pygame.SRCALPHA)
    v = max(0, min(255, int(round(255 * factor))))
    overlay.fill((v, v, v, 255))
    muted = source.copy()
    muted.blit(overlay, (0, 0), special_flags=pygame.BLEND_RGBA_MULT)
    return muted


def _tile_sprite_max_side(hex_size: float) -> int:
    return max(8, int(round(hex_size * TILE_SPRITE_HEX_SCALE * 2.0)))


def map_tile_surface(
    key: TileArtKey,
    hex_size: float,
    *,
    muted: bool = False,
) -> pygame.Surface | None:
    """Hex-centred tile sprite scaled to fit the hex (cached by kind, size, mute)."""

    base = load_tile_sprite(key)
    if base is None:
        return None
    max_side = _tile_sprite_max_side(hex_size)
    cache_key = (key, max_side, muted)
    cached = _map_scaled.get(cache_key)
    if cached is not None:
        return cached
    scaled = scaled_to_fit(base, max_side, max_side)
    if muted:
        scaled = _mute_surface(scaled, TILE_SPRITE_MUTE_FACTOR)
    if len(_map_scaled) > 96:
        _map_scaled.clear()
    _map_scaled[cache_key] = scaled
    return scaled


def clear_art_caches() -> None:
    """Drop loaded / scaled art (for tests or hot reload)."""

    _loaded.clear()
    _map_scaled.clear()


__all__ = [
    "TileArtKey",
    "TILE_SPRITE_HEX_SCALE",
    "TILE_SPRITE_MUTE_FACTOR",
    "clear_art_caches",
    "load_tile_sprite",
    "map_tile_surface",
    "tile_sprite_path",
    "tiles_assets_dir",
]

"""Settlement / citadel tile art paths and loaders (requires ``assets/Tiles``)."""

from __future__ import annotations

import os
from collections.abc import Iterator

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")

import pygame
import pytest

from dragonflight.dragon_art import repository_root, scaled_to_fit
from dragonflight.settlement import SettlementType
from dragonflight.terrain import Terrain
from dragonflight.tile_art import (
    TILE_SPRITE_HEX_SCALE,
    clear_art_caches,
    load_tile_sprite,
    map_tile_surface,
    tile_sprite_path,
    tiles_assets_dir,
)


@pytest.fixture(autouse=True)
def _pygame() -> Iterator[None]:
    pygame.init()
    pygame.display.init()
    try:
        pygame.display.set_mode((64, 64))
    except pygame.error:
        pass
    yield
    clear_art_caches()
    pygame.quit()


def test_repository_root_contains_tiles_assets() -> None:
    root = repository_root()
    assert (root / "assets" / "Tiles").is_dir()


def test_tile_art_paths_are_under_tiles_folder() -> None:
    base = tiles_assets_dir()
    for key in (*SettlementType, Terrain.CITADEL):
        path = tile_sprite_path(key)
        assert path.parent == base
        assert path.suffix == ".png"


def test_tile_png_assets_exist_on_disk() -> None:
    for key in (SettlementType.VILLAGE, SettlementType.CITY, SettlementType.FORT, Terrain.CITADEL):
        assert tile_sprite_path(key).is_file(), f"missing tile art for {key}"


def test_load_and_scale_helpers() -> None:
    clear_art_caches()
    village = load_tile_sprite(SettlementType.VILLAGE)
    assert village is not None
    assert load_tile_sprite(SettlementType.VILLAGE) is village
    hex_size = 24.0
    max_side = max(8, int(round(hex_size * TILE_SPRITE_HEX_SCALE * 2.0)))
    m = map_tile_surface(SettlementType.CITY, hex_size)
    assert m is not None
    assert m.get_width() <= max_side
    assert m.get_height() <= max_side
    muted = map_tile_surface(SettlementType.FORT, hex_size, muted=True)
    assert muted is not None
    assert muted.get_size() == map_tile_surface(SettlementType.FORT, hex_size).get_size()
    citadel = load_tile_sprite(Terrain.CITADEL)
    assert citadel is not None
    small = scaled_to_fit(citadel, 80, 60)
    assert small.get_width() <= 80
    assert small.get_height() <= 60

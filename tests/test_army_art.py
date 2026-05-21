"""Army art paths and loaders (requires ``assets/Armies`` in the repo)."""

from __future__ import annotations

import os
from collections.abc import Iterator

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")

import pygame
import pytest

from dragonflight.army import ArmyKind
from dragonflight.army_art import (
    armies_assets_dir,
    clear_art_caches,
    detailed_sprite_path,
    load_detailed_sprite,
    load_pixel_sprite,
    map_marker_surface,
    pixel_sprite_path,
)
from dragonflight.dragon_art import repository_root, scaled_to_fit


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


def test_repository_root_contains_armies_assets() -> None:
    root = repository_root()
    assert (root / "assets" / "Armies").is_dir()


def test_army_art_paths_are_under_armies_folder() -> None:
    base = armies_assets_dir()
    for kind in ArmyKind:
        pp = pixel_sprite_path(kind)
        dp = detailed_sprite_path(kind)
        assert "112 - pixel art" in str(pp)
        assert "256 - detailed" in str(dp)
        assert base in pp.parents
        assert base in dp.parents


def test_army_png_assets_exist_on_disk() -> None:
    for kind in ArmyKind:
        assert pixel_sprite_path(kind).is_file(), f"missing pixel art for {kind}"
        assert detailed_sprite_path(kind).is_file(), f"missing detailed art for {kind}"


def test_load_and_scale_helpers() -> None:
    clear_art_caches()
    px = load_pixel_sprite(ArmyKind.VILLAGE)
    assert px is not None
    assert load_pixel_sprite(ArmyKind.VILLAGE) is px
    m = map_marker_surface(ArmyKind.FORT, 32)
    assert m is not None
    assert m.get_size() == (32, 32)
    det = load_detailed_sprite(ArmyKind.HEROES)
    assert det is not None
    small = scaled_to_fit(det, 80, 60)
    assert small.get_width() <= 80
    assert small.get_height() <= 60

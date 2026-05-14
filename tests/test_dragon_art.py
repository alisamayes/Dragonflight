"""Dragon art paths and loaders (requires ``assets/Dragons`` in the repo)."""

from __future__ import annotations

import os
from collections.abc import Iterator

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")

import pygame
import pytest

from dragonflight.dragon import DragonKind
from dragonflight.dragon_art import (
    clear_art_caches,
    detailed_sprite_path,
    dragons_assets_dir,
    load_detailed_sprite,
    load_pixel_sprite,
    map_marker_surface,
    pixel_sprite_path,
    repository_root,
    scaled_to_fit,
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


def test_repository_root_contains_src_and_assets() -> None:
    root = repository_root()
    assert (root / "src" / "dragonflight").is_dir()
    assert (root / "assets").is_dir()


def test_dragon_art_paths_are_under_dragons_folder() -> None:
    base = dragons_assets_dir()
    for kind in DragonKind:
        pp = pixel_sprite_path(kind)
        dp = detailed_sprite_path(kind)
        assert pp.parent.name == "Pixel"
        assert dp.parent.name == "Detailed"
        assert base in pp.parents
        assert base in dp.parents


def test_dragon_png_assets_exist_on_disk() -> None:
    for kind in DragonKind:
        assert pixel_sprite_path(kind).is_file(), f"missing pixel art for {kind}"
        assert detailed_sprite_path(kind).is_file(), f"missing detailed art for {kind}"


def test_load_and_scale_helpers() -> None:
    clear_art_caches()
    px = load_pixel_sprite(DragonKind.RED_FIRE)
    assert px is not None
    assert load_pixel_sprite(DragonKind.RED_FIRE) is px
    m = map_marker_surface(DragonKind.RED_FIRE, 32)
    assert m is not None
    assert m.get_size() == (32, 32)
    det = load_detailed_sprite(DragonKind.RED_FIRE)
    assert det is not None
    small = scaled_to_fit(det, 80, 60)
    assert small.get_width() <= 80
    assert small.get_height() <= 60

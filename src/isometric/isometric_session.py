"""Pygame session: map picker and isometric map preview."""

from __future__ import annotations

from pathlib import Path

import pygame

from dragonflight.map_camera import MapViewportCamera
from dragonflight.map_loader import MapLoadError, load_map
from dragonflight.map_state import GameMap
from dragonflight.play_session_ui import draw_button, draw_text
from dragonflight.render import (
    BACKGROUND_COLOR,
    MIN_CLIENT_HEIGHT,
    MIN_CLIENT_WIDTH,
    clamp_client_window_size,
    client_size_from_resize_event,
)

from .isometric_camera import (
    apply_iso_keyboard_pan,
    apply_iso_wheel_zoom,
    resolve_iso_map_view,
)
from .isometric_render import render_iso_map

_FRAME_RATE: int = 30
_WINDOW_TITLE: str = "Dragonflight — isometric map preview"

_UI_BG_RGB: tuple[int, int, int] = (30, 32, 40)
_UI_PANEL_RGB: tuple[int, int, int] = (38, 41, 52)
_UI_BORDER_RGB: tuple[int, int, int] = (85, 90, 110)
_UI_TEXT_RGB: tuple[int, int, int] = (235, 235, 245)
_UI_MUTED_TEXT_RGB: tuple[int, int, int] = (175, 175, 190)
_UI_ERROR_RGB: tuple[int, int, int] = (240, 120, 120)


def _project_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _assets_dir() -> Path:
    return _project_root() / "assets"


def validate_map_path_under_assets(path: Path) -> tuple[bool, str]:
    """Return whether ``path`` resolves under ``assets/``."""
    try:
        assets_resolved = _assets_dir().resolve()
        path.resolve().relative_to(assets_resolved)
    except (OSError, ValueError):
        return False, "Please choose a map file inside assets/."
    return True, ""


def list_map_files_in_assets() -> list[Path]:
    """Return sorted ``*.json`` map paths confined to ``assets/``."""
    assets = _assets_dir()
    try:
        assets.mkdir(parents=True, exist_ok=True)
    except OSError:
        pass
    try:
        assets_resolved = assets.resolve()
    except OSError:
        return []
    safe: list[Path] = []
    for candidate in sorted(assets.glob("*.json")):
        if not candidate.is_file():
            continue
        try:
            candidate.resolve().relative_to(assets_resolved)
        except ValueError:
            continue
        safe.append(candidate)
    return safe


def load_map_from_assets(path: Path) -> tuple[GameMap | None, str]:
    """Load a map via ``load_map`` after validating the path is under ``assets/``."""
    ok_path, err_path = validate_map_path_under_assets(path)
    if not ok_path:
        return None, err_path
    try:
        game_map = load_map(path.resolve())
    except MapLoadError as exc:
        return None, f"Failed to load map: {exc}"
    except OSError as exc:
        return None, f"Failed to read file: {exc}"
    return game_map, f"Loaded assets/{path.name}"


def _draw_map_picker(
    surf: pygame.Surface,
    *,
    font: pygame.font.Font,
    font_big: pygame.font.Font,
    maps: list[Path],
    scroll: int,
    status: str,
    hovered_path: Path | None,
) -> None:
    win_w, win_h = surf.get_size()
    surf.fill(_UI_BG_RGB)
    draw_text(surf, font_big, "Choose a map (isometric preview)", (60, 48), _UI_TEXT_RGB)
    draw_text(surf, font, "JSON files in assets/", (60, 88), _UI_MUTED_TEXT_RGB)
    mx, my = pygame.mouse.get_pos()

    list_rect = pygame.Rect(40, 120, win_w - 80, win_h - 180)
    pygame.draw.rect(surf, _UI_PANEL_RGB, list_rect, border_radius=8)
    pygame.draw.rect(surf, _UI_BORDER_RGB, list_rect, width=1, border_radius=8)

    if not maps:
        draw_text(
            surf,
            font,
            "No .json maps found in assets/.",
            (list_rect.x + 16, list_rect.y + 20),
            _UI_MUTED_TEXT_RGB,
        )
    else:
        row_h = 38
        y = list_rect.y + 8 - scroll
        for path in maps:
            pick_rect = pygame.Rect(list_rect.x + 8, y, list_rect.w - 16, row_h - 4)
            y += row_h
            if pick_rect.bottom < list_rect.top or pick_rect.top > list_rect.bottom:
                continue
            hovered = pick_rect.collidepoint(mx, my)
            active = hovered_path is not None and path.resolve() == hovered_path.resolve()
            draw_button(surf, font, pick_rect, path.name, hovered=hovered, active=active)

    draw_text(
        surf,
        font,
        "Click a map · Esc — quit",
        (60, win_h - 48),
        _UI_MUTED_TEXT_RGB,
    )
    if status:
        draw_text(surf, font, status, (60, win_h - 88), _UI_ERROR_RGB)


def _pick_map_at(
    maps: list[Path],
    mx: int,
    my: int,
    *,
    win_w: int,
    win_h: int,
    scroll: int,
) -> Path | None:
    list_rect = pygame.Rect(40, 120, win_w - 80, win_h - 180)
    if not list_rect.collidepoint(mx, my):
        return None
    row_h = 38
    y = list_rect.y + 8 - scroll
    for path in maps:
        pick_rect = pygame.Rect(list_rect.x + 8, y, list_rect.w - 16, row_h - 4)
        y += row_h
        if pick_rect.collidepoint(mx, my):
            return path
    return None


def _run_map_view(game_map: GameMap) -> None:
    try:
        desktop = pygame.display.get_desktop_sizes()[0]
    except (IndexError, pygame.error):
        desktop = (
            pygame.display.Info().current_w,
            pygame.display.Info().current_h,
        )

    client_w = max(MIN_CLIENT_WIDTH, min(1200, desktop[0] - 80))
    client_h = max(MIN_CLIENT_HEIGHT, min(900, desktop[1] - 80))
    surf = pygame.display.set_mode((client_w, client_h), pygame.RESIZABLE)
    pygame.display.set_caption(_WINDOW_TITLE)

    font = pygame.font.SysFont(None, 22)
    camera = MapViewportCamera()
    clock = pygame.time.Clock()
    running = True

    while running:
        dt_sec = clock.tick(_FRAME_RATE) / 1000.0
        keys = pygame.key.get_pressed()
        camera = apply_iso_keyboard_pan(
            camera, keys, dt_sec, game_map, surf.get_width(), surf.get_height()
        )

        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                running = False
                break
            if event.type == pygame.KEYDOWN and event.key == pygame.K_ESCAPE:
                running = False
                break
            if event.type == pygame.MOUSEWHEEL:
                mx, my = pygame.mouse.get_pos()
                camera = apply_iso_wheel_zoom(
                    camera,
                    game_map,
                    surf.get_width(),
                    surf.get_height(),
                    anchor_local=(float(mx), float(my)),
                    wheel_y=event.y,
                )
            resized = client_size_from_resize_event(event)
            if resized is not None:
                nw, nh = clamp_client_window_size(*resized, desktop)
                surf = pygame.display.set_mode((nw, nh), pygame.RESIZABLE)

        view = resolve_iso_map_view(game_map, surf.get_width(), surf.get_height(), camera)
        surf.fill(BACKGROUND_COLOR)
        render_iso_map(
            surf,
            game_map,
            view.hex_size,
            view.origin_local,
            clear_background=False,
        )
        draw_text(
            surf,
            font,
            "Wheel — zoom · WASD/arrows — pan · Esc — quit",
            (16, surf.get_height() - 32),
            _UI_MUTED_TEXT_RGB,
        )
        pygame.display.flip()


def main() -> None:
    pygame.init()
    pygame.display.init()
    try:
        try:
            desktop = pygame.display.get_desktop_sizes()[0]
        except (IndexError, pygame.error):
            desktop = (
                pygame.display.Info().current_w,
                pygame.display.Info().current_h,
            )

        picker_w = max(MIN_CLIENT_WIDTH, min(900, desktop[0] - 80))
        picker_h = max(MIN_CLIENT_HEIGHT, min(700, desktop[1] - 80))
        surf = pygame.display.set_mode((picker_w, picker_h), pygame.RESIZABLE)
        pygame.display.set_caption(_WINDOW_TITLE)

        font = pygame.font.SysFont(None, 22)
        font_big = pygame.font.SysFont(None, 32)
        scroll = 0
        status = ""
        clock = pygame.time.Clock()
        running_picker = True

        while running_picker:
            clock.tick(_FRAME_RATE)
            maps = list_map_files_in_assets()
            hovered: Path | None = None
            mx, my = pygame.mouse.get_pos()
            hovered = _pick_map_at(
                maps, mx, my, win_w=surf.get_width(), win_h=surf.get_height(), scroll=scroll
            )

            for event in pygame.event.get():
                if event.type == pygame.QUIT:
                    running_picker = False
                    break
                if event.type == pygame.KEYDOWN and event.key == pygame.K_ESCAPE:
                    running_picker = False
                    break
                if event.type == pygame.MOUSEWHEEL:
                    scroll = max(0, scroll - event.y * 24)
                if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
                    chosen = _pick_map_at(
                        maps,
                        event.pos[0],
                        event.pos[1],
                        win_w=surf.get_width(),
                        win_h=surf.get_height(),
                        scroll=scroll,
                    )
                    if chosen is not None:
                        loaded, msg = load_map_from_assets(chosen)
                        if loaded is None:
                            status = msg
                        else:
                            running_picker = False
                            _run_map_view(loaded)
                            return
                resized = client_size_from_resize_event(event)
                if resized is not None:
                    nw, nh = clamp_client_window_size(*resized, desktop)
                    surf = pygame.display.set_mode((nw, nh), pygame.RESIZABLE)

            _draw_map_picker(
                surf,
                font=font,
                font_big=font_big,
                maps=maps,
                scroll=scroll,
                status=status,
                hovered_path=hovered,
            )
            pygame.display.flip()
    finally:
        pygame.quit()

"""Interactive map session — Pygame (pygame required).

Launched by default from ``python -m dragonflight`` (see ``__main__``). Click
reachable hexes to move the dragon from the bundled citadel. Invalid tiles
(due to flight range or mandatory return to citadel on the daily clock) are
drawn muted. A 24-segment hour bar at the top tracks remaining daylight.

This module couples presentation with :class:`~dragonflight.dragon.Dragon` for
the runnable prototype. A static map-only window is :func:`render.run_demo`.
"""

from __future__ import annotations

import json
import re
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

import pygame

from .dragon import Dragon
from .dragon_defaults import HOURS_PER_DRAGON_DAY
from .hex_coord import HEX_CORNERS, OffsetCoord, offset_to_pixel
from .hour_bar_layout import hour_bar_segment_layout
from .map_loader import MapLoadError, load_map
from .map_state import GameMap, Tile
from .render import (
    BACKGROUND_COLOR,
    MIN_CLIENT_HEIGHT,
    MIN_CLIENT_WIDTH,
    TERRAIN_COLORS,
    clamp_client_window_size,
    client_size_from_resize_event,
    compute_render_hex_size,
    compute_window_size,
    hex_corner_offset,
    layout_map_on_canvas,
    render_map,
)
from .terrain import Terrain

# --- Layout -------------------------------------------------------------------

#: Total height of the top chrome (caption + discrete hour bar).
TIME_BAR_HEIGHT: int = 52

#: Vertical position of the hour segments within the top chrome.
_BAR_TOP_Y: int = 30

#: Pixel height of each hour segment strip.
_BAR_SEGMENT_HEIGHT: int = 14

#: Gap between adjacent hour segments (pixels).
_SEGMENT_GAP: int = 1

#: Mute factor applied to unreachable terrain RGB components.
_MUTE_FACTOR: float = 0.42

#: Dragon marker colour (flat filled circle).
_DRAGON_DOT_RGB: tuple[int, int, int] = (0, 0, 0)

_FRAME_RATE: int = 60


SETTINGS_BAR_HEIGHT: int = 56

_UI_BG_RGB: tuple[int, int, int] = (30, 32, 40)
_UI_PANEL_RGB: tuple[int, int, int] = (38, 41, 52)
_UI_BORDER_RGB: tuple[int, int, int] = (85, 90, 110)
_UI_TEXT_RGB: tuple[int, int, int] = (235, 235, 245)
_UI_MUTED_TEXT_RGB: tuple[int, int, int] = (175, 175, 190)
_UI_BUTTON_RGB: tuple[int, int, int] = (60, 66, 86)
_UI_BUTTON_HOVER_RGB: tuple[int, int, int] = (74, 82, 108)
_UI_BUTTON_ACTIVE_RGB: tuple[int, int, int] = (96, 106, 140)
_UI_INPUT_RGB: tuple[int, int, int] = (22, 24, 32)
_UI_INPUT_FOCUS_RGB: tuple[int, int, int] = (28, 30, 40)

_MAP_EDITOR_HEX_OUTLINE: tuple[int, int, int] = (10, 10, 10)

_SURFACE_LAYER: str = "surface"
_SCHEMA_VERSION: int = 3
_DEFAULT_HEX_SIZE_HINT: int = 30
_DEFAULT_CUSTOM_HEX_TYPES: list[dict[str, str]] = [
    {"id": "custom-fe6e3b0a", "name": "Bridge", "color": "#8B4513"},
    {"id": "custom-0d9e6285", "name": "Citadel", "color": "#e31616"},
    {"id": "custom-5c5b120e", "name": "Settlement", "color": "#fff705"},
    {"id": "custom-river-0001", "name": "River", "color": "#3a7bd5"},
]
_CUSTOM_ID_BY_TERRAIN: dict[Terrain, str] = {
    Terrain.BRIDGE: "custom-fe6e3b0a",
    Terrain.CITADEL: "custom-0d9e6285",
    Terrain.SETTLEMENT: "custom-5c5b120e",
    Terrain.RIVER: "custom-river-0001",
}


@dataclass(slots=True)
class _TextField:
    label: str
    value: str
    rect: pygame.Rect


@dataclass(slots=True)
class _MapCreatorDraft:
    dims: _TextField
    name: _TextField
    error: str = ""


@dataclass(slots=True)
class _MapEditorState:
    width: int
    height: int
    name: str
    map_id: str
    created_at: str
    selected: Terrain
    tiles: dict[OffsetCoord, Terrain | None]
    status: str = ""


def _project_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _assets_dir() -> Path:
    return _project_root() / "assets"


def _sanitize_filename(name: str) -> str:
    base = name.strip()
    if not base:
        return "untitled_map"
    base = base.replace(" ", "_")
    base = re.sub(r"[^A-Za-z0-9._-]", "", base)
    base = base.strip("._-")
    return base or "untitled_map"


def _iso_utc_now() -> str:
    return datetime.now(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _parse_dims(text: str) -> tuple[int, int] | None:
    raw = text.strip().lower().replace(" ", "")
    m = re.fullmatch(r"(\d{1,4})x(\d{1,4})", raw)
    if m is None:
        return None
    w = int(m.group(1))
    h = int(m.group(2))
    if w <= 0 or h <= 0:
        return None
    if w > 1000 or h > 1000:
        return None
    return w, h


def _draw_text(
    surface: pygame.Surface,
    font: pygame.font.Font,
    text: str,
    pos: tuple[int, int],
    rgb: tuple[int, int, int] = _UI_TEXT_RGB,
) -> None:
    surface.blit(font.render(text, True, rgb), pos)


def _draw_button(
    surface: pygame.Surface,
    font: pygame.font.Font,
    rect: pygame.Rect,
    label: str,
    *,
    hovered: bool = False,
    active: bool = False,
) -> None:
    fill = _UI_BUTTON_ACTIVE_RGB if active else (_UI_BUTTON_HOVER_RGB if hovered else _UI_BUTTON_RGB)
    pygame.draw.rect(surface, fill, rect, border_radius=6)
    pygame.draw.rect(surface, _UI_BORDER_RGB, rect, width=1, border_radius=6)
    text_surf = font.render(label, True, _UI_TEXT_RGB)
    tx = rect.x + (rect.w - text_surf.get_width()) // 2
    ty = rect.y + (rect.h - text_surf.get_height()) // 2
    surface.blit(text_surf, (tx, ty))


def _draw_text_field(
    surface: pygame.Surface,
    font: pygame.font.Font,
    field: _TextField,
    *,
    focused: bool,
) -> None:
    _draw_text(surface, font, field.label, (field.rect.x, field.rect.y - 22), _UI_MUTED_TEXT_RGB)
    pygame.draw.rect(surface, _UI_INPUT_FOCUS_RGB if focused else _UI_INPUT_RGB, field.rect, border_radius=6)
    pygame.draw.rect(surface, _UI_BORDER_RGB, field.rect, width=1, border_radius=6)
    pad_x = 10
    pad_y = 8
    surface.blit(font.render(field.value, True, _UI_TEXT_RGB), (field.rect.x + pad_x, field.rect.y + pad_y))


def _map_json_for_editor(editor: _MapEditorState) -> dict:
    updated = _iso_utc_now()

    hexes: dict[str, dict] = {}
    for col in range(editor.width):
        for row in range(editor.height):
            coord = OffsetCoord(col=col, row=row)
            terrain = editor.tiles.get(coord)
            if terrain is None:
                hex_type = "grassland"
                custom_color = None
            elif terrain in (Terrain.GRASSLAND, Terrain.MOUNTAIN):
                hex_type = terrain.value
                custom_color = None
            elif terrain is Terrain.WOODLAND:
                hex_type = "forest"
                custom_color = None
            else:
                hex_type = _CUSTOM_ID_BY_TERRAIN[terrain]
                custom_color = None
                for ct in _DEFAULT_CUSTOM_HEX_TYPES:
                    if ct["id"] == hex_type:
                        custom_color = ct["color"]
                        break

            key = f"{col},{row},{_SURFACE_LAYER}"
            tile_obj: dict = {
                "q": col,
                "r": row,
                "layer": _SURFACE_LAYER,
                "hexType": hex_type,
                "fogState": "visible",
                "edgeData": {},
                "connections": [],
            }
            if custom_color is not None:
                tile_obj["customColor"] = custom_color
            hexes[key] = tile_obj

    return {
        "id": editor.map_id,
        "name": editor.name,
        "description": "",
        "ownerId": None,
        "settings": {
            "width": editor.width,
            "height": editor.height,
            "hexSize": _DEFAULT_HEX_SIZE_HINT,
            "orientation": "flat",
            "showGrid": True,
            "showLabels": False,
            "showCoordinates": False,
            "showBiomeBleed": True,
            "fogEnabled": False,
            "fogDistance": 2,
            "underdarkEnabled": False,
        },
        "hexes": hexes,
        "regions": [],
        "paths": [],
        "notes": [],
        "customHexTypes": list(_DEFAULT_CUSTOM_HEX_TYPES),
        "activeLayer": _SURFACE_LAYER,
        "schemaVersion": _SCHEMA_VERSION,
        "createdAt": editor.created_at,
        "updatedAt": updated,
    }


def _save_editor_map(editor: _MapEditorState) -> tuple[bool, str]:
    assets = _assets_dir()
    assets.mkdir(parents=True, exist_ok=True)

    filename = _sanitize_filename(editor.name) + ".json"
    out_path = (assets / filename).resolve()
    assets_resolved = assets.resolve()
    if assets_resolved not in out_path.parents:
        return False, "Refusing to write outside assets/"

    payload = _map_json_for_editor(editor)
    out_path.write_text(json.dumps(payload, indent=2, sort_keys=False) + "\n", encoding="utf-8")
    return True, f"Saved to assets/{filename}"


def _find_citadel_coord(game_map: GameMap) -> OffsetCoord:
    """Return the offset coordinate of the single citadel tile."""
    found: list = []
    for tile in game_map:
        if tile.terrain is Terrain.CITADEL:
            found.append(tile.coord)
    if len(found) != 1:
        msg = f"movement playtest expects exactly one citadel tile; found {len(found)}"
        raise RuntimeError(msg)
    return found[0]


def _mute_rgb(rgb: tuple[int, int, int], factor: float) -> tuple[int, int, int]:
    r, g, b = rgb
    return (
        int(r * factor),
        int(g * factor),
        int(b * factor),
    )


def _make_tile_color_fn(dragon: Dragon, citadel: OffsetCoord, game_map: GameMap):
    """Return a per-tile fill that mutes destinations failing :meth:`Dragon.validate_move`."""

    def tile_color(tile: Tile) -> tuple[int, int, int]:
        base = TERRAIN_COLORS[tile.terrain]
        if tile.coord == dragon.position:
            return base
        if dragon.validate_move(tile.coord, game_map, citadel).ok:
            return base
        return _mute_rgb(base, _MUTE_FACTOR)

    return tile_color


def _hex_polygon_screen(
    coord: OffsetCoord,
    hex_size: float,
    origin: tuple[float, float],
) -> list[tuple[float, float]]:
    ox, oy = origin
    cx_off, cy_off = offset_to_pixel(coord, hex_size)
    cx = ox + cx_off
    cy = oy + cy_off
    return [
        (cx + dx, cy + dy)
        for dx, dy in (hex_corner_offset(hex_size, i) for i in range(HEX_CORNERS))
    ]


def _point_in_polygon(px: float, py: float, verts: list[tuple[float, float]]) -> bool:
    """Point-in-polygon (even-odd) for flat-top hex hit-testing."""
    n = len(verts)
    inside = False
    for i in range(n):
        j = (i + 1) % n
        xi, yi = verts[i]
        xj, yj = verts[j]
        if abs(yj - yi) < 1e-12:
            continue
        if (yi > py) != (yj > py):
            xinters = (xj - xi) * (py - yi) / (yj - yi) + xi
            if px < xinters:
                inside = not inside
    return inside


def _pick_tile_at_pixel(
    px: float,
    py: float,
    game_map: GameMap,
    hex_size: float,
    origin: tuple[float, float],
) -> OffsetCoord | None:
    """Return the topmost tile whose screen hex contains ``(px, py)``, else ``None``."""
    for tile in game_map:
        poly = _hex_polygon_screen(tile.coord, hex_size, origin)
        if _point_in_polygon(px, py, poly):
            return tile.coord
    return None


def _dragon_screen_center(
    position: OffsetCoord,
    hex_size: float,
    origin: tuple[float, float],
) -> tuple[float, float]:
    ox, oy = origin
    cx_off, cy_off = offset_to_pixel(position, hex_size)
    return ox + cx_off, oy + cy_off


def _draw_hour_bar(surface: pygame.Surface, hours_remaining: float, bar_width: int) -> None:
    """Draw 24 equal hour segments; left-to-right shows **spent** (dark) then **left** (green)."""
    margin = 8
    inner_w = max(1, bar_width - 2 * margin)
    segment_widths, gap = hour_bar_segment_layout(inner_w, _SEGMENT_GAP)

    hr = max(0.0, min(HOURS_PER_DRAGON_DAY, hours_remaining))
    spent = HOURS_PER_DRAGON_DAY - hr

    spent_rgb = (45, 48, 58)
    remain_rgb = (72, 160, 96)

    x_pos = margin
    y = _BAR_TOP_Y
    for i in range(24):
        w = segment_widths[i]
        consumed_here = spent - float(i)
        rect = pygame.Rect(x_pos, y, w, _BAR_SEGMENT_HEIGHT)
        if consumed_here >= 1.0:
            pygame.draw.rect(surface, spent_rgb, rect)
        elif consumed_here <= 0.0:
            pygame.draw.rect(surface, remain_rgb, rect)
        else:
            pygame.draw.rect(surface, remain_rgb, rect)
            w_spent = min(w, int(round(consumed_here * w)))
            if w_spent > 0:
                pygame.draw.rect(
                    surface,
                    spent_rgb,
                    pygame.Rect(x_pos, y, w_spent, _BAR_SEGMENT_HEIGHT),
                )
        x_pos += w
        if i < 23:
            x_pos += gap


def run_movement_playtest(
    game_map: GameMap,
    *,
    window_title: str = "Dragonflight",
) -> None:
    """Open a resizable window with the map, dragon dot, reachability tinting, and hour bar.

    Map hex size scales to the map viewport (everything below the time bar) within
    :data:`~dragonflight.render.MIN_CLIENT_*` and the primary desktop resolution.
    """
    citadel_coord = _find_citadel_coord(game_map)
    dragon = Dragon.new_red_fire_at(citadel_coord)

    pygame.init()
    pygame.display.init()
    pygame.font.init()
    try:
        try:
            desktop = pygame.display.get_desktop_sizes()[0]
        except (IndexError, pygame.error):
            desktop = (
                pygame.display.Info().current_w,
                pygame.display.Info().current_h,
            )

        reserve_px = 80
        cap_w = max(MIN_CLIENT_WIDTH, desktop[0] - reserve_px)
        cap_h = max(MIN_CLIENT_HEIGHT, desktop[1] - reserve_px)

        natural_hex = compute_render_hex_size(game_map)
        natural_map_w, natural_map_h = compute_window_size(game_map, natural_hex)
        natural_win_w = natural_map_w
        natural_win_h = natural_map_h + TIME_BAR_HEIGHT

        initial_w = min(max(natural_win_w, MIN_CLIENT_WIDTH), cap_w)
        initial_h = min(max(natural_win_h, MIN_CLIENT_HEIGHT), cap_h)

        win_w = initial_w
        win_h = initial_h
        hex_size = float(natural_hex)
        origin: tuple[float, float] = (0.0, 0.0)

        def apply_layout(client_w: int, client_h: int) -> None:
            """Recompute hex size and origin for a client-area size."""
            nonlocal win_w, win_h, hex_size, origin
            win_w, win_h = client_w, client_h
            map_h = max(1, client_h - TIME_BAR_HEIGHT)
            hs, (ox, oy), _ = layout_map_on_canvas(game_map, client_w, map_h)
            hex_size = hs
            origin = (ox, oy + float(TIME_BAR_HEIGHT))

        pygame.display.set_mode((initial_w, initial_h), pygame.RESIZABLE)
        pygame.display.set_caption(window_title)
        font = pygame.font.SysFont(None, 20)
        font_big = pygame.font.SysFont(None, 34)
        font_mid = pygame.font.SysFont(None, 24)
        clock = pygame.time.Clock()

        apply_layout(initial_w, initial_h)

        day_index = 1
        screen: str = "game"  # game | settings | map_creator_setup | map_creator_editor
        focused_field: str | None = None  # dims | name
        settings_status: str = ""

        draft = _MapCreatorDraft(
            dims=_TextField("Map size (e.g. 50x50)", "30x30", pygame.Rect(60, 170, 260, 36)),
            name=_TextField("Map name", "New Map", pygame.Rect(60, 250, 260, 36)),
        )
        editor: _MapEditorState | None = None

        def _tile_types_for_toolbar() -> list[tuple[str, Terrain]]:
            return [
                ("Grassland", Terrain.GRASSLAND),
                ("Woodland", Terrain.WOODLAND),
                ("Mountain", Terrain.MOUNTAIN),
                ("River", Terrain.RIVER),
                ("Bridge", Terrain.BRIDGE),
                ("Settlement", Terrain.SETTLEMENT),
                ("Citadel", Terrain.CITADEL),
            ]

        def _pick_map_file_from_assets() -> Path | None:
            """Open a native file picker rooted at assets/ and return a selected path."""
            assets = _assets_dir()
            try:
                assets.mkdir(parents=True, exist_ok=True)
            except OSError:
                # If this fails, the dialog can still open, but initialdir may be ignored.
                pass

            try:
                import tkinter as tk
                from tkinter import filedialog
            except Exception:
                return None

            root = tk.Tk()
            root.withdraw()
            try:
                root.attributes("-topmost", True)
            except Exception:
                pass
            try:
                file_path = filedialog.askopenfilename(
                    title="Select a Dragonflight map",
                    initialdir=str(assets),
                    filetypes=[("Dragonflight map (*.json)", "*.json"), ("All files", "*.*")],
                )
            finally:
                try:
                    root.destroy()
                except Exception:
                    pass

            if not file_path:
                return None
            return Path(file_path)

        def _load_map_from_assets_path(path: Path) -> tuple[bool, str]:
            """Load a map file, refusing paths outside assets/."""
            try:
                assets_resolved = _assets_dir().resolve()
                selected_resolved = path.resolve()
                selected_resolved.relative_to(assets_resolved)
            except Exception:
                return False, "Please choose a map file inside assets/."

            try:
                new_map = load_map(selected_resolved)
            except MapLoadError as exc:
                return False, f"Failed to load map: {exc}"
            except OSError as exc:
                return False, f"Failed to read file: {exc}"

            _reset_session_for_map(new_map)
            rel = selected_resolved.name
            return True, f"Loaded assets/{rel}"

        def _reset_session_for_map(new_map: GameMap) -> None:
            nonlocal game_map, citadel_coord, dragon, day_index, screen, settings_status
            game_map = new_map
            citadel_coord = _find_citadel_coord(game_map)
            dragon = Dragon.new_red_fire_at(citadel_coord)
            day_index = 1
            settings_status = ""
            # Re-fit the map to current window.
            apply_layout(win_w, win_h)
            screen = "game"

        def redraw() -> None:
            surf = pygame.display.get_surface()
            surf.fill(BACKGROUND_COLOR)

            if screen == "game":
                caption = font.render(
                    (
                        f"Day {day_index}  |  Green bar = hours left  |  Muted = unreachable  |  "
                        "Citadel = new day"
                    ),
                    True,
                    (210, 210, 220),
                )
                surf.blit(caption, (8, 6))
                _draw_hour_bar(surf, dragon.hours_remaining, win_w)

                tile_color = _make_tile_color_fn(dragon, citadel_coord, game_map)
                render_map(
                    surf,
                    game_map,
                    hex_size,
                    origin,
                    tile_color=tile_color,
                    clear_background=False,
                )

                cx, cy = _dragon_screen_center(dragon.position, hex_size, origin)
                radius = max(3, int(hex_size * 0.18))
                pygame.draw.circle(surf, _DRAGON_DOT_RGB, (int(round(cx)), int(round(cy))), radius)

                bar_rect = pygame.Rect(0, win_h - SETTINGS_BAR_HEIGHT, win_w, SETTINGS_BAR_HEIGHT)
                pygame.draw.rect(surf, _UI_BG_RGB, bar_rect)
                pygame.draw.rect(surf, _UI_BORDER_RGB, bar_rect, width=1)
                btn = pygame.Rect(win_w - 140, win_h - SETTINGS_BAR_HEIGHT + 10, 120, 36)
                hovered = btn.collidepoint(pygame.mouse.get_pos())
                _draw_button(surf, font_mid, btn, "Settings", hovered=hovered)

            elif screen == "settings":
                surf.fill(_UI_BG_RGB)
                _draw_text(surf, font_big, "Settings", (60, 60), _UI_TEXT_RGB)

                mx, my = pygame.mouse.get_pos()
                btn_creator = pygame.Rect(60, 140, 260, 44)
                btn_loader = pygame.Rect(60, 200, 260, 44)
                btn_back = pygame.Rect(60, win_h - 70, 120, 36)

                _draw_button(surf, font_mid, btn_creator, "Map Creator", hovered=btn_creator.collidepoint(mx, my))
                _draw_button(surf, font_mid, btn_loader, "Map Loader", hovered=btn_loader.collidepoint(mx, my))
                _draw_button(surf, font_mid, btn_back, "Back", hovered=btn_back.collidepoint(mx, my))

                if settings_status:
                    _draw_text(surf, font, settings_status, (60, 260), _UI_MUTED_TEXT_RGB)

            elif screen == "map_creator_setup":
                surf.fill(_UI_BG_RGB)
                _draw_text(surf, font_big, "Map Creator", (60, 60), _UI_TEXT_RGB)
                _draw_text(surf, font, "Enter map dimensions and a name.", (60, 105), _UI_MUTED_TEXT_RGB)

                _draw_text_field(surf, font_mid, draft.dims, focused=(focused_field == "dims"))
                _draw_text_field(surf, font_mid, draft.name, focused=(focused_field == "name"))

                mx, my = pygame.mouse.get_pos()
                btn_create = pygame.Rect(60, 320, 140, 40)
                btn_back = pygame.Rect(220, 320, 100, 40)
                _draw_button(surf, font_mid, btn_create, "Create", hovered=btn_create.collidepoint(mx, my))
                _draw_button(surf, font_mid, btn_back, "Back", hovered=btn_back.collidepoint(mx, my))

                if draft.error:
                    _draw_text(surf, font, draft.error, (60, 380), (240, 120, 120))

            elif screen == "map_creator_editor" and editor is not None:
                surf.fill(_UI_BG_RGB)
                _draw_text(surf, font_big, f"Map Creator — {editor.name}", (24, 18), _UI_TEXT_RGB)

                toolbar_w = 240
                top_pad = 70
                bottom_pad = SETTINGS_BAR_HEIGHT

                map_view = pygame.Rect(0, top_pad, win_w - toolbar_w, win_h - top_pad - bottom_pad)
                toolbar = pygame.Rect(win_w - toolbar_w, top_pad, toolbar_w, win_h - top_pad - bottom_pad)
                bottom = pygame.Rect(0, win_h - SETTINGS_BAR_HEIGHT, win_w, SETTINGS_BAR_HEIGHT)

                pygame.draw.rect(surf, _UI_PANEL_RGB, toolbar)
                pygame.draw.rect(surf, _UI_BORDER_RGB, toolbar, width=1)
                pygame.draw.rect(surf, _UI_BG_RGB, bottom)
                pygame.draw.rect(surf, _UI_BORDER_RGB, bottom, width=1)

                tiles: dict[OffsetCoord, Tile] = {}
                for coord, terr in editor.tiles.items():
                    terrain = Terrain.GRASSLAND if terr is None else terr
                    tiles[coord] = Tile(coord=coord, terrain=terrain)
                edit_map = GameMap(
                    width=editor.width,
                    height=editor.height,
                    hex_size=float(_DEFAULT_HEX_SIZE_HINT),
                    orientation="flat",
                    tiles=tiles,
                )

                hs, (ox, oy), _ = layout_map_on_canvas(edit_map, map_view.w, map_view.h)
                origin_edit = (ox + float(map_view.x), oy + float(map_view.y))

                def tile_color(tile: Tile) -> tuple[int, int, int]:
                    terr = editor.tiles.get(tile.coord)
                    if terr is None:
                        return TERRAIN_COLORS[Terrain.GRASSLAND]
                    return TERRAIN_COLORS[tile.terrain]

                render_map(
                    surf,
                    edit_map,
                    hs,
                    origin_edit,
                    tile_color=tile_color,
                    clear_background=False,
                )

                y = toolbar.y + 16
                _draw_text(surf, font_mid, "Tiles", (toolbar.x + 14, y), _UI_TEXT_RGB)
                y += 36

                mx, my = pygame.mouse.get_pos()
                button_h = 34
                for label, terr in _tile_types_for_toolbar():
                    r = pygame.Rect(toolbar.x + 14, y, toolbar.w - 28, button_h)
                    hovered = r.collidepoint(mx, my)
                    active = editor.selected is terr
                    _draw_button(surf, font, r, label, hovered=hovered, active=active)
                    y += button_h + 10

                btn_save = pygame.Rect(toolbar.x + 14, toolbar.bottom - 54, toolbar.w - 28, 40)
                _draw_button(surf, font_mid, btn_save, "Save", hovered=btn_save.collidepoint(mx, my))

                btn_back = pygame.Rect(win_w - 130, win_h - SETTINGS_BAR_HEIGHT + 10, 110, 36)
                _draw_button(surf, font_mid, btn_back, "Back", hovered=btn_back.collidepoint(mx, my))

                if editor.status:
                    _draw_text(surf, font, editor.status, (24, win_h - SETTINGS_BAR_HEIGHT + 18), _UI_TEXT_RGB)

            pygame.display.flip()

        redraw()

        running = True
        while running:
            for event in pygame.event.get():
                if event.type == pygame.QUIT:
                    running = False
                    break
                if event.type == pygame.KEYDOWN and event.key == pygame.K_ESCAPE:
                    if screen == "game":
                        running = False
                        break
                    screen = "game"
                    focused_field = None
                    draft.error = ""
                    redraw()
                    continue
                resized = client_size_from_resize_event(event)
                if resized is not None:
                    nw, nh = clamp_client_window_size(*resized, desktop)
                    pygame.display.set_mode((nw, nh), pygame.RESIZABLE)
                    pygame.display.set_caption(window_title)
                    apply_layout(nw, nh)
                    redraw()

                if event.type == pygame.KEYDOWN and screen == "map_creator_setup":
                    if focused_field in ("dims", "name"):
                        field = draft.dims if focused_field == "dims" else draft.name
                        if event.key == pygame.K_BACKSPACE:
                            field.value = field.value[:-1]
                        elif event.key in (pygame.K_RETURN, pygame.K_KP_ENTER):
                            pass
                        else:
                            ch = getattr(event, "unicode", "")
                            if ch and ch.isprintable():
                                if focused_field == "dims":
                                    if ch.lower() in "0123456789x " and len(field.value) < 20:
                                        field.value += ch
                                else:
                                    if len(field.value) < 60:
                                        field.value += ch
                        redraw()

                if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
                    mx, my = event.pos

                    if screen == "game":
                        settings_btn = pygame.Rect(win_w - 140, win_h - SETTINGS_BAR_HEIGHT + 10, 120, 36)
                        if settings_btn.collidepoint(mx, my):
                            screen = "settings"
                            redraw()
                            continue
                        if my < TIME_BAR_HEIGHT or my > win_h - SETTINGS_BAR_HEIGHT:
                            continue
                        picked = _pick_tile_at_pixel(float(mx), float(my), game_map, hex_size, origin)
                        if picked is None:
                            continue
                        outcome = dragon.move(picked, game_map, citadel_coord)
                        if outcome.ok and dragon.position == citadel_coord:
                            dragon.begin_new_day_at_citadel(citadel_coord)
                            day_index += 1
                        redraw()
                        continue

                    if screen == "settings":
                        btn_creator = pygame.Rect(60, 140, 260, 44)
                        btn_loader = pygame.Rect(60, 200, 260, 44)
                        btn_back = pygame.Rect(60, win_h - 70, 120, 36)
                        if btn_creator.collidepoint(mx, my):
                            screen = "map_creator_setup"
                            focused_field = None
                            draft.error = ""
                            settings_status = ""
                            redraw()
                            continue
                        if btn_loader.collidepoint(mx, my):
                            chosen = _pick_map_file_from_assets()
                            if chosen is None:
                                settings_status = "No file selected."
                                redraw()
                                continue
                            ok, msg = _load_map_from_assets_path(chosen)
                            if ok:
                                redraw()
                                continue
                            settings_status = msg
                            redraw()
                            continue
                        if btn_back.collidepoint(mx, my):
                            screen = "game"
                            settings_status = ""
                            redraw()
                            continue

                    if screen == "map_creator_setup":
                        if draft.dims.rect.collidepoint(mx, my):
                            focused_field = "dims"
                            redraw()
                            continue
                        if draft.name.rect.collidepoint(mx, my):
                            focused_field = "name"
                            redraw()
                            continue

                        btn_create = pygame.Rect(60, 320, 140, 40)
                        btn_back = pygame.Rect(220, 320, 100, 40)
                        if btn_back.collidepoint(mx, my):
                            screen = "settings"
                            focused_field = None
                            draft.error = ""
                            redraw()
                            continue
                        if btn_create.collidepoint(mx, my):
                            dims = _parse_dims(draft.dims.value)
                            if dims is None:
                                draft.error = "Invalid size. Use format like 50x50 (max 1000x1000)."
                                redraw()
                                continue
                            w, h = dims
                            name = draft.name.value.strip()
                            if not name:
                                draft.error = "Please enter a map name."
                                redraw()
                                continue

                            tiles: dict[OffsetCoord, Terrain | None] = {}
                            for col in range(w):
                                for row in range(h):
                                    tiles[OffsetCoord(col=col, row=row)] = Terrain.GRASSLAND
                            editor = _MapEditorState(
                                width=w,
                                height=h,
                                name=name,
                                map_id=str(uuid.uuid4()),
                                created_at=_iso_utc_now(),
                                selected=Terrain.GRASSLAND,
                                tiles=tiles,
                            )
                            draft.error = ""
                            focused_field = None
                            screen = "map_creator_editor"
                            redraw()
                            continue

                    if screen == "map_creator_editor" and editor is not None:
                        toolbar_w = 240
                        top_pad = 70
                        bottom_pad = SETTINGS_BAR_HEIGHT
                        map_view = pygame.Rect(0, top_pad, win_w - toolbar_w, win_h - top_pad - bottom_pad)
                        toolbar = pygame.Rect(win_w - toolbar_w, top_pad, toolbar_w, win_h - top_pad - bottom_pad)
                        btn_back = pygame.Rect(win_w - 130, win_h - SETTINGS_BAR_HEIGHT + 10, 110, 36)
                        if btn_back.collidepoint(mx, my):
                            screen = "map_creator_setup"
                            editor = None
                            redraw()
                            continue

                        y = toolbar.y + 16 + 36
                        button_h = 34
                        for _, terr in _tile_types_for_toolbar():
                            r = pygame.Rect(toolbar.x + 14, y, toolbar.w - 28, button_h)
                            if r.collidepoint(mx, my):
                                editor.selected = terr
                                editor.status = ""
                                redraw()
                                break
                            y += button_h + 10
                        else:
                            btn_save = pygame.Rect(toolbar.x + 14, toolbar.bottom - 54, toolbar.w - 28, 40)
                            if btn_save.collidepoint(mx, my):
                                ok, msg = _save_editor_map(editor)
                                editor.status = msg
                                redraw()
                                continue

                            if map_view.collidepoint(mx, my):
                                tiles: dict[OffsetCoord, Tile] = {}
                                for coord, terr in editor.tiles.items():
                                    terrain = Terrain.GRASSLAND if terr is None else terr
                                    tiles[coord] = Tile(coord=coord, terrain=terrain)
                                edit_map = GameMap(
                                    width=editor.width,
                                    height=editor.height,
                                    hex_size=float(_DEFAULT_HEX_SIZE_HINT),
                                    orientation="flat",
                                    tiles=tiles,
                                )
                                hs, (ox, oy), _ = layout_map_on_canvas(edit_map, map_view.w, map_view.h)
                                origin_edit = (ox + float(map_view.x), oy + float(map_view.y))
                                picked = _pick_tile_at_pixel(float(mx), float(my), edit_map, hs, origin_edit)
                                if picked is not None:
                                    editor.tiles[picked] = editor.selected
                                    editor.status = ""
                                    redraw()

            clock.tick(_FRAME_RATE)
    finally:
        pygame.quit()

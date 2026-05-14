"""Interactive map session — Pygame (pygame required).

Launched by default from ``python -m dragonflight`` (see ``__main__``): main menu,
then new-game map and dragon selection, then the movement playtest. Settings →
Map Loader picks a file then the same dragon chooser before loading. Click
reachable hexes to move the dragon from the citadel. Invalid tiles (flight range
or mandatory return to citadel on the daily clock) are drawn muted. A 24-segment
hour bar tracks remaining daylight.

This module couples presentation with :class:`~dragonflight.dragon.Dragon` for
the runnable prototype. A static map-only window is :func:`render.run_demo`.
"""

from __future__ import annotations

import json
import re
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

import pygame

from .dragon import Dragon, DragonKind, MoveAttempt
from .dragon_art import load_detailed_sprite, map_marker_surface, scaled_to_fit
from .dragon_abilities import (
    ability_button_enabled,
    ability_requires_target,
    ability_status_label,
    ability_ui_detail_lines,
    effective_attack,
    effective_defence,
    effective_flight_range,
    effective_speed_hexes_per_hour,
    on_combat_ended,
    try_use_ability,
    unlocked_ability_specs,
)
from .dragon_defaults import HOURS_PER_DRAGON_DAY
from .dragon_playables import (
    default_playable_kind,
    display_name_for_kind,
    new_playable_dragon,
    playable_dragon_kinds,
)
from .dragon_progression import (
    DRAGON_UPGRADE_STAT_COLUMN_ORDER,
    DragonUpgradeBaseline,
    DragonUpgradeStat,
    apply_dragon_upgrade_draft,
    dragon_stat_pill_strings_from_totals,
    dragon_upgrade_baseline_from_dragon,
    marginal_dragon_stat_upgrade_cost,
    preview_dragon_stats_after_draft,
    total_dragon_upgrade_draft_cost,
)
from .hex_coord import HEX_CORNERS, OffsetCoord, offset_to_pixel
from .hour_bar_layout import hour_bar_segment_layout
from .map_loader import MapLoadError, load_map
from .map_state import GameMap, Tile
from .render import (
    BACKGROUND_COLOR,
    MIN_CLIENT_HEIGHT,
    MIN_CLIENT_WIDTH,
    SETTLEMENT_KIND_FILL,
    TERRAIN_COLORS,
    clamp_client_window_size,
    client_size_from_resize_event,
    compute_render_hex_size,
    compute_window_size,
    default_tile_fill_rgb,
    hex_corner_offset,
    layout_map_on_canvas,
    render_map,
)
from .settlement import (
    Settlement,
    SettlementType,
    apply_settlement_raid_victory_bundle,
    raid_victory_gold_from_eco,
    resolve_settlement_combat_round,
    validate_settlement_raid,
)
from .terrain import Terrain
from .tile_inspection import terrain_display_name, tile_inspect_info, tile_inspector_lines
from .world_settlements import settlements_by_coord_from_map

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

#: Fallback map marker when pixel art is missing.
_DRAGON_DOT_RGB: tuple[int, int, int] = (0, 0, 0)

_FRAME_RATE: int = 60


SETTINGS_BAR_HEIGHT: int = 56

#: Gold added by Settings → Dev Mode (local playtest only).
DEV_MODE_TEST_GOLD_GRANT: int = 10_000

#: Why the dragon-type screen was opened (controls Back / Play behaviour).
DragonPickContext = Literal["new_game", "load_map", "same_map_reset"]

#: Legacy design-time default width; new sessions start at font-metric mins instead.
MAP_SIDE_PANEL_WIDTH: int = 320

#: Half-width (pixels) of each vertical splitter hit zone, centered on the panel edge.
GAMEPLAY_PANEL_SPLITTER_HIT_HALFWIDTH: int = 3

#: Map column must stay at least this large (pixels) while a session map is loaded.
GAMEPLAY_MIN_MAP_VIEWPORT_W: int = 160
GAMEPLAY_MIN_MAP_VIEWPORT_H: int = 200

#: Inspector minimum column width uses this fraction of the font-metric text box (num/den).
#: Applied only to the right-hand inspector; dragon panel uses :func:`_min_dragon_panel_column_width` as-is.
INSPECTOR_PANEL_MIN_WIDTH_SCALE_NUM: int = 60
INSPECTOR_PANEL_MIN_WIDTH_SCALE_DEN: int = 100
INSPECTOR_PANEL_MIN_WIDTH_FLOOR_PX: int = 80

#: Raid combat overlay covers this fraction of the **map viewport** height (central column).
RAID_COMBAT_OVERLAY_HEIGHT_FRACTION: float = 0.5

#: After a terminal combat outcome message, auto-close the raid overlay (milliseconds).
RAID_COMBAT_OVERLAY_AUTO_CLOSE_MS: int = 3000

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


def _max_text_pixel_width(font: pygame.font.Font, lines: tuple[str, ...]) -> int:
    return max((font.size(line)[0] for line in lines), default=0)


def _min_dragon_panel_column_width(font: pygame.font.Font, font_small: pygame.font.Font) -> int:
    """Content-based minimum width for the dragon stats column (padding + widest sample lines)."""

    pad = 12
    header_w = _max_text_pixel_width(font, ("Dragon",))
    kind_w = max(
        _max_text_pixel_width(font_small, (display_name_for_kind(k),))
        for k in playable_dragon_kinds()
    )
    body_lines = (
        "Level: 999",
        "Gold: 9999999",
        "Stats",
        "HP: 99999 / 99999",
        "ATK: 999  |  DFN: 999",
        "Flight range: 999 hexes",
        "Speed: 99.9 hex/h",
        "Abilities",
        "Ability 1: —",
        "Ability 2: —",
    )
    body_w = _max_text_pixel_width(font_small, body_lines)
    inner = max(header_w, kind_w, body_w)
    return inner + 2 * pad


def _inspector_panel_raw_min_column_width(
    font: pygame.font.Font, font_small: pygame.font.Font
) -> int:
    """Unscaled font-metric minimum width for the inspector column (before :data:`INSPECTOR_PANEL_MIN_WIDTH_SCALE_NUM`)."""

    pad = 12
    title_w = _max_text_pixel_width(font, ("Tile inspector",))
    longest_terrain_line = max(
        (f"Terrain: {terrain_display_name(t)}" for t in Terrain),
        key=len,
    )
    sample_lines = (
        "Right-click the map for terrain details.",
        "Off-map.",
        "Offset col 9999, row 9999",
        longest_terrain_line,
        "Settlement type: village",
        "HP: 99999 / 99999",
        "Eco: 9999999",
        "Atk / Def: 999 / 999",
        "Aggression: 9999 / 9999",
        "Raid Spoils: 9999999",
        "Settlement hex — no live settlement data for this tile.",
        "Raid (stand on settlement)",
        "Raid (busy…)",
    )
    body_w = _max_text_pixel_width(font_small, sample_lines)
    inner = max(title_w, body_w)
    return inner + 2 * pad


def _min_inspector_panel_column_width(font: pygame.font.Font, font_small: pygame.font.Font) -> int:
    """Content-based minimum width for the tile inspector column.

    The font-derived width is scaled (see :data:`INSPECTOR_PANEL_MIN_WIDTH_SCALE_NUM`) so the
    map viewport keeps more horizontal room; the dragon column minimum is not scaled the same way.
    """

    raw = _inspector_panel_raw_min_column_width(font, font_small)
    scaled = raw * INSPECTOR_PANEL_MIN_WIDTH_SCALE_NUM // INSPECTOR_PANEL_MIN_WIDTH_SCALE_DEN
    return max(INSPECTOR_PANEL_MIN_WIDTH_FLOOR_PX, scaled)


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
    settlement_kinds: dict[OffsetCoord, SettlementType] = field(default_factory=dict)
    brush: Literal["terrain", "settlement"] = "terrain"
    selected_settlement_kind: SettlementType = SettlementType.VILLAGE
    save_path: Path | None = None
    status: str = ""


def _project_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _assets_dir() -> Path:
    return _project_root() / "assets"


def _validate_map_json_path_under_assets(path: Path) -> tuple[bool, str]:
    """True if ``path`` resolves under ``assets/`` (before attempting to load JSON)."""
    try:
        assets_resolved = _assets_dir().resolve()
        selected_resolved = path.resolve()
        selected_resolved.relative_to(assets_resolved)
    except Exception:
        return False, "Please choose a map file inside assets/."
    return True, ""


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
    fill = (
        _UI_BUTTON_ACTIVE_RGB if active else (_UI_BUTTON_HOVER_RGB if hovered else _UI_BUTTON_RGB)
    )
    pygame.draw.rect(surface, fill, rect, border_radius=6)
    pygame.draw.rect(surface, _UI_BORDER_RGB, rect, width=1, border_radius=6)
    text_surf = font.render(label, True, _UI_TEXT_RGB)
    tx = rect.x + (rect.w - text_surf.get_width()) // 2
    ty = rect.y + (rect.h - text_surf.get_height()) // 2
    surface.blit(text_surf, (tx, ty))


def _wrap_text_to_width(font: pygame.font.Font, text: str, max_width: int) -> list[str]:
    words = text.split()
    lines: list[str] = []
    current = ""
    for word in words:
        trial = word if not current else f"{current} {word}"
        if font.size(trial)[0] <= max_width:
            current = trial
            continue
        if current:
            lines.append(current)
        current = word
    if current:
        lines.append(current)
    return lines


def _draw_text_field(
    surface: pygame.Surface,
    font: pygame.font.Font,
    field: _TextField,
    *,
    focused: bool,
) -> None:
    _draw_text(surface, font, field.label, (field.rect.x, field.rect.y - 22), _UI_MUTED_TEXT_RGB)
    pygame.draw.rect(
        surface, _UI_INPUT_FOCUS_RGB if focused else _UI_INPUT_RGB, field.rect, border_radius=6
    )
    pygame.draw.rect(surface, _UI_BORDER_RGB, field.rect, width=1, border_radius=6)
    pad_x = 10
    pad_y = 8
    surface.blit(
        font.render(field.value, True, _UI_TEXT_RGB), (field.rect.x + pad_x, field.rect.y + pad_y)
    )


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
            if terrain is Terrain.SETTLEMENT:
                kind = editor.settlement_kinds.get(coord, SettlementType.VILLAGE)
                tile_obj["settlementType"] = kind.value
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
    assets_resolved = assets.resolve()

    if editor.save_path is not None:
        out_path = editor.save_path.resolve()
    else:
        filename = _sanitize_filename(editor.name) + ".json"
        out_path = (assets / filename).resolve()

    try:
        out_path.relative_to(assets_resolved)
    except ValueError:
        return False, "Refusing to write outside assets/"

    payload = _map_json_for_editor(editor)
    out_path.write_text(json.dumps(payload, indent=2, sort_keys=False) + "\n", encoding="utf-8")
    rel = out_path.relative_to(assets_resolved)
    return True, f"Saved to assets/{rel.as_posix()}"


def _open_editor_from_map_path(path: Path) -> tuple[bool, str, _MapEditorState | None]:
    """Load an existing map from ``assets/`` into editor state (overwrite save target)."""
    try:
        assets_resolved = _assets_dir().resolve()
        selected_resolved = path.resolve()
        selected_resolved.relative_to(assets_resolved)
    except Exception:
        return False, "Please choose a map file inside assets/.", None

    try:
        game_map = load_map(selected_resolved)
    except MapLoadError as exc:
        return False, f"Failed to load map: {exc}", None
    except OSError as exc:
        return False, f"Failed to read file: {exc}", None

    try:
        raw = json.loads(selected_resolved.read_text(encoding="utf-8"))
    except OSError as exc:
        return False, f"Failed to read file: {exc}", None
    except json.JSONDecodeError as exc:
        return False, f"Invalid JSON: {exc}", None

    name = str(raw.get("name", selected_resolved.stem))
    map_id = str(raw.get("id", str(uuid.uuid4())))
    created_at = str(raw.get("createdAt", _iso_utc_now()))

    tiles: dict[OffsetCoord, Terrain | None] = {}
    settlement_kinds: dict[OffsetCoord, SettlementType] = {}
    for coord, tile in game_map.tiles.items():
        tiles[coord] = tile.terrain
        if tile.terrain is Terrain.SETTLEMENT:
            settlement_kinds[coord] = tile.settlement_kind or SettlementType.VILLAGE

    editor = _MapEditorState(
        width=game_map.width,
        height=game_map.height,
        name=name,
        map_id=map_id,
        created_at=created_at,
        selected=Terrain.GRASSLAND,
        tiles=tiles,
        settlement_kinds=settlement_kinds,
        brush="terrain",
        selected_settlement_kind=SettlementType.VILLAGE,
        save_path=selected_resolved,
    )
    return True, f"Editing {selected_resolved.name}", editor


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
        base = default_tile_fill_rgb(tile)
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


def _map_viewport_rect(
    client_w: int,
    client_h: int,
    *,
    dragon_panel_w: int,
    inspector_panel_w: int,
) -> pygame.Rect:
    """Pixel rectangle of the central map column (between side panels)."""

    map_h = max(1, client_h - TIME_BAR_HEIGHT - SETTINGS_BAR_HEIGHT)
    inner_w = max(1, client_w - dragon_panel_w - inspector_panel_w)
    return pygame.Rect(dragon_panel_w, TIME_BAR_HEIGHT, inner_w, map_h)


def clamp_gameplay_side_panel_widths(
    client_w: int,
    dragon_panel_w: int,
    inspector_panel_w: int,
    *,
    min_dragon: int,
    min_inspector: int,
    min_map_viewport_w: int,
) -> tuple[int, int]:
    """Clamp ``dragon`` / ``inspector`` widths so the map keeps ``min_map_viewport_w``."""

    cap_total = client_w - min_map_viewport_w
    if cap_total < min_dragon + min_inspector:
        return min_dragon, min_inspector

    d = max(min_dragon, min(int(dragon_panel_w), cap_total - min_inspector))
    i = max(min_inspector, min(int(inspector_panel_w), cap_total - d))
    if d + i > cap_total:
        i = cap_total - d
    i = max(min_inspector, i)
    d = max(min_dragon, min(d, cap_total - i))
    return d, i


def hit_test_gameplay_panel_splitter(
    mx: int,
    my: int,
    client_w: int,
    client_h: int,
    *,
    dragon_panel_w: int,
    inspector_panel_w: int,
    hit_halfwidth: int = GAMEPLAY_PANEL_SPLITTER_HIT_HALFWIDTH,
) -> Literal["left", "right"] | None:
    """Return which vertical splitter edge ``(mx, my)`` hits, if any (map row only)."""

    map_row_top = TIME_BAR_HEIGHT
    map_row_bottom_excl = client_h - SETTINGS_BAR_HEIGHT
    if my < map_row_top or my >= map_row_bottom_excl:
        return None

    left_x = dragon_panel_w
    right_x = client_w - inspector_panel_w
    if abs(mx - left_x) <= hit_halfwidth:
        return "left"
    if abs(mx - right_x) <= hit_halfwidth:
        return "right"
    return None


def _draw_dragon_panel(
    surface: pygame.Surface,
    font: pygame.font.Font,
    font_small: pygame.font.Font,
    *,
    panel_rect: pygame.Rect,
    dragon: Dragon,
    world: GameMap,
) -> dict[str, pygame.Rect]:
    """Left column: dragon identity, level, combat/move stats, and unlocked abilities."""

    pygame.draw.rect(surface, _UI_PANEL_RGB, panel_rect)
    pygame.draw.rect(surface, _UI_BORDER_RGB, panel_rect, width=1)

    pad = 12
    x = panel_rect.x + pad
    y = panel_rect.y + pad
    line_gap = 22

    inner_w = max(1, panel_rect.w - 2 * pad)
    portrait = load_detailed_sprite(dragon.kind)
    if portrait is not None:
        art_max_h = min(200, max(72, int(inner_w * 0.75)))
        scaled = scaled_to_fit(portrait, inner_w, art_max_h)
        art_rect = scaled.get_rect()
        art_rect.topleft = (x, y)
        surface.blit(scaled, art_rect)
        y = art_rect.bottom + 10

    _draw_text(surface, font, "Dragon", (x, y), _UI_TEXT_RGB)
    y += 28
    _draw_text(
        surface,
        font_small,
        display_name_for_kind(dragon.kind),
        (x, y),
        _UI_TEXT_RGB,
    )
    y += line_gap
    _draw_text(surface, font_small, f"Level: {dragon.level}", (x, y), _UI_MUTED_TEXT_RGB)
    y += line_gap
    _draw_text(surface, font_small, f"Gold: {dragon.gold}", (x, y), _UI_MUTED_TEXT_RGB)
    y += line_gap + 6

    _draw_text(surface, font_small, "Base Stats", (x, y), _UI_TEXT_RGB)
    y += line_gap
    vivify_bonus = int(dragon.passive_stacks.get("Vivify max hp bonus", 0))
    base_max_hp = max(1, dragon.max_hp - vivify_bonus)
    base_stats = (
        f"HP: {dragon.hp} / {base_max_hp}",
        f"ATK: {dragon.atk}  |  DFN: {dragon.dfn}",
        f"Flight range: {dragon.flight_range_hexes} hexes",
        f"Speed: {dragon.speed_hexes_per_hour:g} hex/h",
    )
    for line in base_stats:
        _draw_text(surface, font_small, line, (x, y), _UI_MUTED_TEXT_RGB)
        y += line_gap

    y += 6
    _draw_text(surface, font_small, "Combat Stats", (x, y), _UI_TEXT_RGB)
    y += line_gap
    combat_atk = effective_attack(dragon, world=world)
    combat_dfn = effective_defence(dragon)
    combat_range = effective_flight_range(dragon)
    combat_speed = effective_speed_hexes_per_hour(dragon, world=world)
    boosted_rgb = (170, 230, 170)
    _draw_text(
        surface,
        font_small,
        f"HP: {dragon.hp} / {dragon.max_hp}",
        (x, y),
        boosted_rgb if dragon.max_hp > base_max_hp else _UI_MUTED_TEXT_RGB,
    )
    y += line_gap
    _draw_text(
        surface,
        font_small,
        f"ATK: {combat_atk}  |  DFN: {combat_dfn}",
        (x, y),
        boosted_rgb if combat_atk > dragon.atk or combat_dfn > dragon.dfn else _UI_MUTED_TEXT_RGB,
    )
    y += line_gap
    _draw_text(
        surface,
        font_small,
        f"Flight range: {combat_range} hexes",
        (x, y),
        boosted_rgb if combat_range > dragon.flight_range_hexes else _UI_MUTED_TEXT_RGB,
    )
    y += line_gap
    _draw_text(
        surface,
        font_small,
        f"Speed: {combat_speed:g} hex/h",
        (x, y),
        boosted_rgb if combat_speed > dragon.speed_hexes_per_hour else _UI_MUTED_TEXT_RGB,
    )
    y += line_gap

    y += 6
    _draw_text(surface, font_small, "Abilities", (x, y), _UI_TEXT_RGB)
    y += line_gap
    ability_buttons: dict[str, pygame.Rect] = {}
    max_text_w = panel_rect.w - 2 * pad
    mx, my = pygame.mouse.get_pos()
    specs = unlocked_ability_specs(dragon)
    if not specs:
        _draw_text(surface, font_small, "No abilities unlocked yet.", (x, y), _UI_MUTED_TEXT_RGB)
        return ability_buttons

    for spec in specs:
        if y > panel_rect.bottom - 32:
            _draw_text(surface, font_small, "…", (x, y), _UI_MUTED_TEXT_RGB)
            break
        label = f"{spec.name} ({'Passive' if spec.category == 'passive' else 'Ability'})"
        _draw_text(surface, font_small, label, (x, y), _UI_TEXT_RGB)
        y += 18
        for detail in ability_ui_detail_lines(dragon, spec, world=world):
            for line in _wrap_text_to_width(font_small, detail, max_text_w):
                if y > panel_rect.bottom - 18:
                    break
                _draw_text(surface, font_small, line, (x, y), _UI_MUTED_TEXT_RGB)
                y += 17
            if y > panel_rect.bottom - 18:
                break
        if spec.category == "passive":
            _draw_text(surface, font_small, "Active", (x, y), (170, 220, 170))
            y += 24
            continue
        status = ability_status_label(dragon, spec.name)
        _draw_text(surface, font_small, status, (x, y), _UI_MUTED_TEXT_RGB)
        y += 18
        btn = pygame.Rect(x, y, max(80, max_text_w), 28)
        enabled = ability_button_enabled(dragon, spec.name)
        _draw_button(
            surface,
            font_small,
            btn,
            "Target" if ability_requires_target(spec.name) else "Use",
            hovered=enabled and btn.collidepoint(mx, my),
            active=enabled,
        )
        ability_buttons[spec.name] = btn
        y += 36
    return ability_buttons


def _draw_raid_combat_overlay(
    surface: pygame.Surface,
    font: pygame.font.Font,
    font_small: pygame.font.Font,
    *,
    map_viewport: pygame.Rect,
    dragon: Dragon,
    settlement: Settlement,
    banner: str,
) -> tuple[pygame.Rect, pygame.Rect]:
    """Bottom-half overlay on the map viewport; returns (attack_rect, retreat_rect)."""

    oh = max(80, int(float(map_viewport.h) * RAID_COMBAT_OVERLAY_HEIGHT_FRACTION))
    overlay = pygame.Rect(map_viewport.x, map_viewport.bottom - oh, map_viewport.w, oh)

    shade = pygame.Surface((overlay.w, overlay.h), pygame.SRCALPHA)
    shade.fill((24, 26, 34, 236))
    surface.blit(shade, overlay.topleft)
    pygame.draw.rect(surface, _UI_BORDER_RGB, overlay, width=1)

    inner_pad = 14
    cx = overlay.x + inner_pad
    cy = overlay.y + inner_pad
    col_w = max(120, (overlay.w - 3 * inner_pad) // 2)

    _draw_text(surface, font, "Combat", (cx, cy), _UI_TEXT_RGB)
    cy += 26

    col_dragon_x = cx
    col_settle_x = cx + col_w + inner_pad
    y0 = cy
    d_portrait = load_detailed_sprite(dragon.kind)
    if d_portrait is not None:
        ph = min(72, max(40, overlay.h // 5))
        ps = scaled_to_fit(d_portrait, col_w, ph)
        surface.blit(ps, (col_dragon_x, y0))
        y0 += ps.get_height() + 6
    _draw_text(surface, font_small, "Dragon", (col_dragon_x, y0), _UI_TEXT_RGB)
    _draw_text(surface, font_small, "Settlement", (col_settle_x, y0), _UI_TEXT_RGB)
    y0 += 22
    d_lines = (
        f"HP: {dragon.hp} / {dragon.max_hp}",
        f"ATK: {dragon.atk}",
        f"DFN: {dragon.dfn}",
    )
    s_lines = (
        f"HP: {settlement.hp} / {settlement.max_hp}",
        f"ATK: {settlement.atk}",
        f"DFN: {settlement.dfn}",
    )
    yd = y0
    for line in d_lines:
        _draw_text(surface, font_small, line, (col_dragon_x, yd), _UI_MUTED_TEXT_RGB)
        yd += 20
    ys = y0
    for line in s_lines:
        _draw_text(surface, font_small, line, (col_settle_x, ys), _UI_MUTED_TEXT_RGB)
        ys += 20

    mid_y = max(yd, ys) + 10
    if banner:
        _draw_text(surface, font_small, banner, (cx, mid_y), (200, 220, 160))
        mid_y += 24

    btn_y = overlay.bottom - inner_pad - 40
    btn_w = max(100, (overlay.w - 3 * inner_pad) // 2)
    attack_rect = pygame.Rect(cx, btn_y, btn_w, 36)
    retreat_rect = pygame.Rect(cx + btn_w + inner_pad, btn_y, btn_w, 36)
    mx, my = pygame.mouse.get_pos()
    _draw_button(surface, font, attack_rect, "Attack", hovered=attack_rect.collidepoint(mx, my))
    _draw_button(surface, font, retreat_rect, "Retreat", hovered=retreat_rect.collidepoint(mx, my))
    return attack_rect, retreat_rect


@dataclass(slots=True)
class DragonUpgradeOverlayLayout:
    """Pixel geometry for :func:`_draw_dragon_upgrade_overlay`."""

    panel: pygame.Rect
    columns: tuple[tuple[pygame.Rect, pygame.Rect, pygame.Rect], ...]
    reset_btn: pygame.Rect
    next_day_btn: pygame.Rect
    title_pos: tuple[int, int]
    baseline_pos: tuple[int, int]
    current_label_pos: tuple[int, int]
    preview_label_pos: tuple[int, int]
    preview_line_pos: tuple[int, int]


@dataclass(slots=True)
class DragonUpgradeOverlayClickRects:
    cost: dict[DragonUpgradeStat, pygame.Rect]
    reset: pygame.Rect
    next_day: pygame.Rect


_DRAGON_UPGRADE_STAT_LABELS: dict[DragonUpgradeStat, str] = {
    DragonUpgradeStat.HP: "Health",
    DragonUpgradeStat.ATK: "Attack",
    DragonUpgradeStat.DFN: "Defence",
    DragonUpgradeStat.FLIGHT_RANGE: "Range",
    DragonUpgradeStat.SPEED: "Speed",
}


def dragon_upgrade_overlay_layout(client_w: int, client_h: int) -> DragonUpgradeOverlayLayout:
    """Compute centered panel and five stat columns (current pill, preview pill, cost button)."""

    row_pill_h = 40
    row_btn_h = 36
    col_gap = 8
    panel_pad = 22
    panel_w_cap = 700

    title_h = 34
    baseline_h = 22
    lbl_h = 18
    # Vertical order: current row, cost row, preview row (see layout body).
    pill_cost_preview_block = lbl_h + row_pill_h + 6 + row_btn_h + 14 + lbl_h + row_pill_h + 14
    preview_h = 24
    btn_row = 40
    gap = 8
    total_inner = title_h + baseline_h + pill_cost_preview_block + preview_h + btn_row + gap * 4
    panel_h = panel_pad * 2 + total_inner
    panel_w = min(panel_w_cap, client_w - 32)
    panel_x = max(8, (client_w - panel_w) // 2)
    panel_y = max(12, (client_h - panel_h) // 2)
    panel = pygame.Rect(panel_x, panel_y, panel_w, panel_h)

    inner_left = panel.x + panel_pad
    inner_w = panel_w - 2 * panel_pad
    col_w = max(52, (inner_w - 4 * col_gap) // 5)

    y = panel.y + panel_pad
    title_pos = (inner_left, y)
    y += title_h + gap
    baseline_pos = (inner_left, y)
    y += baseline_h + 10
    current_label_pos = (inner_left, y)
    y += lbl_h
    cur_pill_y = y
    y += row_pill_h + 6
    cost_y = y
    y += row_btn_h + 14
    preview_label_pos = (inner_left, y)
    y += lbl_h
    prv_pill_y = y
    y += row_pill_h + 14
    preview_line_pos = (inner_left, y)
    y += preview_h + 12
    btns_y = y

    columns: list[tuple[pygame.Rect, pygame.Rect, pygame.Rect]] = []
    for i in range(5):
        x = inner_left + i * (col_w + col_gap)
        columns.append(
            (
                pygame.Rect(x, cur_pill_y, col_w, row_pill_h),
                pygame.Rect(x, prv_pill_y, col_w, row_pill_h),
                pygame.Rect(x, cost_y, col_w, row_btn_h),
            )
        )

    reset_w = 120
    next_w = 150
    gap_btn = 14
    btns_total = reset_w + gap_btn + next_w
    btns_x0 = panel.x + (panel_w - btns_total) // 2
    reset_btn = pygame.Rect(btns_x0, btns_y, reset_w, row_btn_h)
    next_day_btn = pygame.Rect(btns_x0 + reset_w + gap_btn, btns_y, next_w, row_btn_h)

    return DragonUpgradeOverlayLayout(
        panel=panel,
        columns=tuple(columns),
        reset_btn=reset_btn,
        next_day_btn=next_day_btn,
        title_pos=title_pos,
        baseline_pos=baseline_pos,
        current_label_pos=current_label_pos,
        preview_label_pos=preview_label_pos,
        preview_line_pos=preview_line_pos,
    )


def _draw_dragon_upgrade_stat_pill(
    surface: pygame.Surface,
    font: pygame.font.Font,
    rect: pygame.Rect,
    *,
    title: str,
    value: str,
) -> None:
    pygame.draw.rect(surface, _UI_BUTTON_RGB, rect, border_radius=6)
    pygame.draw.rect(surface, _UI_BORDER_RGB, rect, width=1, border_radius=6)
    title_surf = font.render(title, True, _UI_MUTED_TEXT_RGB)
    value_surf = font.render(value, True, _UI_TEXT_RGB)
    line_gap = 2
    stack_h = title_surf.get_height() + line_gap + value_surf.get_height()
    y0 = rect.y + (rect.h - stack_h) // 2
    surface.blit(
        title_surf,
        (rect.x + (rect.w - title_surf.get_width()) // 2, y0),
    )
    surface.blit(
        value_surf,
        (
            rect.x + (rect.w - value_surf.get_width()) // 2,
            y0 + title_surf.get_height() + line_gap,
        ),
    )


def _draw_dragon_upgrade_cost_tile(
    surface: pygame.Surface,
    font: pygame.font.Font,
    rect: pygame.Rect,
    label: str,
    *,
    enabled: bool,
) -> None:
    mx, my = pygame.mouse.get_pos()
    hovered = enabled and rect.collidepoint(mx, my)
    if enabled:
        _draw_button(surface, font, rect, label, hovered=hovered)
    else:
        pygame.draw.rect(surface, _UI_INPUT_RGB, rect, border_radius=6)
        pygame.draw.rect(surface, _UI_BORDER_RGB, rect, width=1, border_radius=6)
        surf = font.render(label, True, _UI_MUTED_TEXT_RGB)
        surface.blit(
            surf,
            (rect.x + (rect.w - surf.get_width()) // 2, rect.y + (rect.h - surf.get_height()) // 2),
        )


def _draw_dragon_upgrade_overlay(
    surface: pygame.Surface,
    *,
    client_w: int,
    client_h: int,
    font_mid: pygame.font.Font,
    font_small: pygame.font.Font,
    font_small_bold: pygame.font.Font,
    baseline: DragonUpgradeBaseline,
    draft: list[DragonUpgradeStat],
) -> DragonUpgradeOverlayClickRects:
    """Full-window modal for end-of-day dragon stat purchases; returns click targets."""

    dim = pygame.Surface((client_w, client_h), pygame.SRCALPHA)
    dim.fill((12, 14, 20, 230))
    surface.blit(dim, (0, 0))

    layout = dragon_upgrade_overlay_layout(client_w, client_h)
    pygame.draw.rect(surface, _UI_PANEL_RGB, layout.panel)
    pygame.draw.rect(surface, _UI_BORDER_RGB, layout.panel, width=1)

    _draw_text(surface, font_mid, "Draconic Upgrades", layout.title_pos, _UI_TEXT_RGB)

    base_gold_line = f"Gold: {baseline.gold}    Level: {baseline.level}"
    base_surf = font_small_bold.render(base_gold_line, True, _UI_TEXT_RGB)
    surface.blit(base_surf, layout.baseline_pos)

    _draw_text(surface, font_small, "Current stats", layout.current_label_pos, _UI_MUTED_TEXT_RGB)
    cur_hp, cur_max, cur_a, cur_d, cur_fr, cur_spd = (
        baseline.hp,
        baseline.max_hp,
        baseline.atk,
        baseline.dfn,
        baseline.flight_range_hexes,
        baseline.speed_hexes_per_hour,
    )
    cur_pills = dragon_stat_pill_strings_from_totals(cur_hp, cur_max, cur_a, cur_d, cur_fr, cur_spd)
    prv_hp, prv_max, prv_a, prv_d, prv_fr, prv_spd = preview_dragon_stats_after_draft(
        baseline, draft
    )
    prv_pills = dragon_stat_pill_strings_from_totals(prv_hp, prv_max, prv_a, prv_d, prv_fr, prv_spd)

    total_cost = total_dragon_upgrade_draft_cost(baseline, draft)
    preview_gold = baseline.gold - total_cost
    preview_level = baseline.level + len(draft)
    preview_line = (
        f"Gold: {baseline.gold} \u2212 {total_cost} \u2192 {preview_gold}    Level: {preview_level}"
    )
    prv_surf = font_small_bold.render(preview_line, True, _UI_TEXT_RGB)

    cost_rects: dict[DragonUpgradeStat, pygame.Rect] = {}
    for i, stat in enumerate(DRAGON_UPGRADE_STAT_COLUMN_ORDER):
        r_cur, r_prv, r_cost = layout.columns[i]
        stat_title = _DRAGON_UPGRADE_STAT_LABELS[stat]
        _draw_dragon_upgrade_stat_pill(
            surface, font_small, r_cur, title=stat_title, value=cur_pills[i]
        )
        marginal = marginal_dragon_stat_upgrade_cost(baseline, draft, stat)
        draft_if = list(draft) + [stat]
        next_total = total_dragon_upgrade_draft_cost(baseline, draft_if)
        can_add = next_total <= baseline.gold
        _draw_dragon_upgrade_cost_tile(
            surface,
            font_small,
            r_cost,
            f"{marginal} g",
            enabled=can_add,
        )
        cost_rects[stat] = r_cost

    _draw_text(surface, font_small, "Preview stats", layout.preview_label_pos, _UI_MUTED_TEXT_RGB)
    for i, stat in enumerate(DRAGON_UPGRADE_STAT_COLUMN_ORDER):
        _, r_prv, _ = layout.columns[i]
        stat_title = _DRAGON_UPGRADE_STAT_LABELS[stat]
        _draw_dragon_upgrade_stat_pill(
            surface, font_small, r_prv, title=stat_title, value=prv_pills[i]
        )

    surface.blit(prv_surf, layout.preview_line_pos)

    mx, my = pygame.mouse.get_pos()
    can_next_day = preview_gold >= 0
    _draw_button(
        surface,
        font_small,
        layout.reset_btn,
        "Reset",
        hovered=layout.reset_btn.collidepoint(mx, my),
    )
    if can_next_day:
        _draw_button(
            surface,
            font_small,
            layout.next_day_btn,
            "Next day",
            hovered=layout.next_day_btn.collidepoint(mx, my),
        )
    else:
        _draw_dragon_upgrade_cost_tile(
            surface,
            font_small,
            layout.next_day_btn,
            "Next day",
            enabled=False,
        )

    return DragonUpgradeOverlayClickRects(
        cost=cost_rects,
        reset=layout.reset_btn,
        next_day=layout.next_day_btn,
    )


def _draw_tile_inspector_panel(
    surface: pygame.Surface,
    font: pygame.font.Font,
    font_small: pygame.font.Font,
    *,
    panel_rect: pygame.Rect,
    game_map: GameMap,
    settlements_by_coord: dict[OffsetCoord, Settlement],
    inspector_focus_coord: OffsetCoord | None,
    inspector_message: str,
    dragon: Dragon,
    raid_combat_active: bool,
) -> pygame.Rect | None:
    """Paint tile details and optional Raid control; returns Raid button rect when shown."""

    pygame.draw.rect(surface, _UI_PANEL_RGB, panel_rect)
    pygame.draw.rect(surface, _UI_BORDER_RGB, panel_rect, width=1)

    pad = 12
    x = panel_rect.x + pad
    y = panel_rect.y + pad
    line_gap = 22

    _draw_text(surface, font, "Tile inspector", (x, y), _UI_TEXT_RGB)
    y += 32

    raid_click_rect: pygame.Rect | None = None

    if inspector_focus_coord is None:
        _draw_text(
            surface,
            font_small,
            "Right-click the map for terrain details.",
            (x, y),
            _UI_MUTED_TEXT_RGB,
        )
    else:
        info = tile_inspect_info(game_map, inspector_focus_coord, settlements_by_coord)
        if info is None:
            _draw_text(surface, font_small, "Off-map.", (x, y), _UI_MUTED_TEXT_RGB)
        else:
            coord_label = f"Offset col {info.coord.col}, row {info.coord.row}"
            _draw_text(surface, font_small, coord_label, (x, y), _UI_MUTED_TEXT_RGB)
            y += line_gap

            for row in tile_inspector_lines(info):
                rgb = (240, 160, 120) if row.kind == "notice" else _UI_TEXT_RGB
                _draw_text(surface, font_small, row.text, (x, y), rgb)
                y += line_gap

            if info.settlement is not None:
                spoils_gold = raid_victory_gold_from_eco(info.settlement.eco)
                spoils = f"Raid Spoils: {spoils_gold}"
                _draw_text(surface, font_small, spoils, (x, y), _UI_MUTED_TEXT_RGB)
                y += line_gap

                settlement_entity = settlements_by_coord.get(inspector_focus_coord)
                can_raid = False
                if settlement_entity is not None and not raid_combat_active:
                    can_raid, _ = validate_settlement_raid(dragon, settlement_entity, game_map)

                btn_h = 38
                raid_rect = pygame.Rect(
                    panel_rect.x + pad,
                    panel_rect.bottom - pad - btn_h,
                    panel_rect.w - 2 * pad,
                    btn_h,
                )
                if can_raid:
                    mx, my = pygame.mouse.get_pos()
                    hovered = raid_rect.collidepoint(mx, my)
                    _draw_button(surface, font, raid_rect, "Raid", hovered=hovered)
                    raid_click_rect = raid_rect
                else:
                    pygame.draw.rect(surface, _UI_INPUT_RGB, raid_rect, border_radius=6)
                    pygame.draw.rect(surface, _UI_BORDER_RGB, raid_rect, width=1, border_radius=6)
                    lbl = "Raid (busy…)" if raid_combat_active else "Raid (stand on settlement)"
                    label_surf = font_small.render(lbl, True, _UI_MUTED_TEXT_RGB)
                    surface.blit(
                        label_surf,
                        (
                            raid_rect.x + (raid_rect.w - label_surf.get_width()) // 2,
                            raid_rect.y + (raid_rect.h - label_surf.get_height()) // 2,
                        ),
                    )

    if inspector_message:
        msg_y = panel_rect.bottom - SETTINGS_BAR_HEIGHT // 2 - 8
        _draw_text(
            surface,
            font_small,
            inspector_message,
            (x, min(msg_y, panel_rect.bottom - 24)),
            (200, 220, 160),
        )

    return raid_click_rect


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
    game_map: GameMap | None = None,
    *,
    window_title: str = "Dragonflight",
) -> None:
    """Open a resizable Pygame window.

    When ``game_map`` is ``None`` (default for ``python -m dragonflight``), the
    flow is: **Main menu** → **Start Game** → pick a map under ``assets/`` → pick
    a dragon type → then the movement playtest session.

    If ``game_map`` is provided, menus are skipped and play starts immediately
    with the default first playable dragon kind (for programmatic / test use).
    """
    citadel_coord: OffsetCoord | None = None
    dragon: Dragon | None = None
    session_dragon_kind: DragonKind = default_playable_kind()
    skip_menus = game_map is not None
    if skip_menus:
        assert game_map is not None
        citadel_coord = _find_citadel_coord(game_map)
        dragon = new_playable_dragon(session_dragon_kind, citadel_coord)

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

        _MENU_FALLBACK_W = 960
        _MENU_FALLBACK_H = 640

        font = pygame.font.SysFont(None, 20)
        font_big = pygame.font.SysFont(None, 34)
        font_mid = pygame.font.SysFont(None, 24)
        font_small = pygame.font.SysFont(None, 18)
        font_small_bold = pygame.font.SysFont(None, 18, bold=True)

        min_dragon_panel_w = _min_dragon_panel_column_width(font, font_small)
        min_inspector_panel_w = _min_inspector_panel_column_width(font, font_small)
        dragon_panel_w = min_dragon_panel_w
        inspector_panel_w = min_inspector_panel_w

        def gameplay_client_floors() -> tuple[int, int]:
            """Minimum client size while a map session is active (readable panels + map strip)."""

            return (
                max(
                    MIN_CLIENT_WIDTH,
                    dragon_panel_w + inspector_panel_w + GAMEPLAY_MIN_MAP_VIEWPORT_W,
                ),
                max(
                    MIN_CLIENT_HEIGHT,
                    TIME_BAR_HEIGHT + SETTINGS_BAR_HEIGHT + GAMEPLAY_MIN_MAP_VIEWPORT_H,
                ),
            )

        if skip_menus:
            assert game_map is not None
            gm_boot: GameMap = game_map
            natural_hex = compute_render_hex_size(gm_boot)
            natural_map_w, natural_map_h = compute_window_size(gm_boot, natural_hex)
            natural_win_w = natural_map_w + dragon_panel_w + inspector_panel_w
            natural_win_h = natural_map_h + TIME_BAR_HEIGHT + SETTINGS_BAR_HEIGHT
            floor_w, floor_h = gameplay_client_floors()
            initial_w = min(max(natural_win_w, floor_w), cap_w)
            initial_h = min(max(natural_win_h, floor_h), cap_h)
            hex_size = float(natural_hex)
        else:
            initial_w = min(max(_MENU_FALLBACK_W, MIN_CLIENT_WIDTH), cap_w)
            initial_h = min(max(_MENU_FALLBACK_H, MIN_CLIENT_HEIGHT), cap_h)
            hex_size = 30.0

        win_w = initial_w
        win_h = initial_h
        origin: tuple[float, float] = (0.0, 0.0)

        def apply_layout(client_w: int, client_h: int) -> None:
            """Recompute hex size and origin for a client-area size."""

            nonlocal win_w, win_h, hex_size, origin
            win_w, win_h = client_w, client_h
            if game_map is None:
                return
            map_h = max(1, client_h - TIME_BAR_HEIGHT - SETTINGS_BAR_HEIGHT)
            map_canvas_w = max(1, client_w - dragon_panel_w - inspector_panel_w)
            hs, (ox, oy), _ = layout_map_on_canvas(game_map, map_canvas_w, map_h)
            hex_size = hs
            origin = (float(dragon_panel_w) + ox, float(TIME_BAR_HEIGHT) + oy)

        def _ensure_window_meets_gameplay_floors() -> None:
            """Grow the pygame surface if the current size is below gameplay floors."""

            fw, fh = gameplay_client_floors()
            nw, nh = max(win_w, fw), max(win_h, fh)
            nw, nh = clamp_client_window_size(nw, nh, desktop)
            if (nw, nh) != (win_w, win_h):
                pygame.display.set_mode((nw, nh), pygame.RESIZABLE)
                pygame.display.set_caption(window_title)
            apply_layout(nw, nh)

        pygame.display.set_mode((initial_w, initial_h), pygame.RESIZABLE)
        pygame.display.set_caption(window_title)
        clock = pygame.time.Clock()

        apply_layout(initial_w, initial_h)

        day_index = 1
        # Screens: main_menu, new_game_maps, new_game_dragon, game, settings,
        # map_creator_setup, map_creator_editor, map_editor
        screen: str = "game" if skip_menus else "main_menu"
        new_game_map_scroll: int = 0
        new_game_status: str = ""
        pending_map_path: Path | None = None
        dragon_pick_context: DragonPickContext | None = None
        focused_field: str | None = None  # dims | name
        settings_status: str = ""

        draft = _MapCreatorDraft(
            dims=_TextField("Map size (e.g. 50x50)", "30x30", pygame.Rect(60, 170, 260, 36)),
            name=_TextField("Map name", "New Map", pygame.Rect(60, 250, 260, 36)),
        )
        editor: _MapEditorState | None = None
        # Live Village/City/Fort instances — settlement phase, future raids/combat.
        settlements_by_coord: dict[OffsetCoord, Settlement] = {}
        inspector_focus_coord: OffsetCoord | None = None
        inspector_message: str = ""
        inspector_raid_button_rect: pygame.Rect | None = None
        dragon_ability_button_rects: dict[str, pygame.Rect] = {}
        targeting_ability_name: str | None = None
        raid_combat_settlement: Settlement | None = None
        raid_overlay_banner: str = ""
        raid_overlay_auto_close_deadline_ms: int | None = None
        raid_overlay_attack_rect: pygame.Rect | None = None
        raid_overlay_retreat_rect: pygame.Rect | None = None
        splitter_drag: Literal["left", "right"] | None = None
        dragon_upgrade_overlay_active = False
        dragon_upgrade_draft: list[DragonUpgradeStat] = []
        dragon_upgrade_overlay_baseline: DragonUpgradeBaseline | None = None
        dragon_upgrade_overlay_click: DragonUpgradeOverlayClickRects | None = None

        def _sync_settlements_from_map() -> None:
            nonlocal settlements_by_coord
            if game_map is None:
                settlements_by_coord = {}
                return
            settlements_by_coord = settlements_by_coord_from_map(game_map)

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

        def _list_map_files_in_assets() -> list[Path]:
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

        def _load_map_from_assets_path(path: Path) -> tuple[bool, str]:
            """Load a map file, refusing paths outside assets/."""
            ok_path, err_path = _validate_map_json_path_under_assets(path)
            if not ok_path:
                return False, err_path

            try:
                selected_resolved = path.resolve()
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
            nonlocal inspector_focus_coord, inspector_message
            nonlocal dragon_ability_button_rects, targeting_ability_name
            nonlocal raid_combat_settlement, raid_overlay_banner
            nonlocal raid_overlay_auto_close_deadline_ms
            nonlocal dragon_upgrade_overlay_active, dragon_upgrade_draft
            nonlocal dragon_upgrade_overlay_baseline, dragon_upgrade_overlay_click
            game_map = new_map
            citadel_coord = _find_citadel_coord(game_map)
            dragon = new_playable_dragon(session_dragon_kind, citadel_coord)
            day_index = 1
            settings_status = ""
            inspector_focus_coord = None
            inspector_message = ""
            dragon_ability_button_rects = {}
            targeting_ability_name = None
            raid_combat_settlement = None
            raid_overlay_banner = ""
            raid_overlay_auto_close_deadline_ms = None
            dragon_upgrade_overlay_active = False
            dragon_upgrade_draft = []
            dragon_upgrade_overlay_baseline = None
            dragon_upgrade_overlay_click = None
            _sync_settlements_from_map()
            _ensure_window_meets_gameplay_floors()
            screen = "game"

        def _begin_play_session_from_pending_map() -> tuple[bool, str]:
            """Load ``pending_map_path`` with ``session_dragon_kind`` and enter ``game``."""
            nonlocal game_map, citadel_coord, dragon, day_index, screen
            nonlocal settings_status, new_game_status, dragon_pick_context
            nonlocal inspector_focus_coord, inspector_message
            nonlocal dragon_ability_button_rects, targeting_ability_name
            nonlocal raid_combat_settlement, raid_overlay_banner
            nonlocal raid_overlay_auto_close_deadline_ms
            nonlocal dragon_upgrade_overlay_active, dragon_upgrade_draft
            nonlocal dragon_upgrade_overlay_baseline, dragon_upgrade_overlay_click
            if pending_map_path is None:
                return False, "No map selected."
            try:
                assets_resolved = _assets_dir().resolve()
                selected_resolved = pending_map_path.resolve()
                selected_resolved.relative_to(assets_resolved)
            except Exception:
                return False, "Map file must be inside assets/."

            try:
                new_map = load_map(selected_resolved)
            except MapLoadError as exc:
                return False, f"Failed to load map: {exc}"
            except OSError as exc:
                return False, f"Failed to read file: {exc}"

            game_map = new_map
            citadel_coord = _find_citadel_coord(game_map)
            dragon = new_playable_dragon(session_dragon_kind, citadel_coord)
            day_index = 1
            settings_status = ""
            new_game_status = ""
            inspector_focus_coord = None
            inspector_message = ""
            dragon_ability_button_rects = {}
            targeting_ability_name = None
            raid_combat_settlement = None
            raid_overlay_banner = ""
            raid_overlay_auto_close_deadline_ms = None
            dragon_upgrade_overlay_active = False
            dragon_upgrade_draft = []
            dragon_upgrade_overlay_baseline = None
            dragon_upgrade_overlay_click = None
            _sync_settlements_from_map()
            _ensure_window_meets_gameplay_floors()
            screen = "game"
            dragon_pick_context = None
            return True, ""

        if game_map is not None:
            _sync_settlements_from_map()

        def redraw() -> None:
            nonlocal inspector_raid_button_rect
            nonlocal dragon_ability_button_rects
            nonlocal raid_overlay_attack_rect, raid_overlay_retreat_rect
            nonlocal dragon_upgrade_overlay_click
            surf = pygame.display.get_surface()
            surf.fill(BACKGROUND_COLOR)

            if screen == "main_menu":
                surf.fill(_UI_BG_RGB)
                _draw_text(
                    surf,
                    font_big,
                    "Dragonflight",
                    (win_w // 2 - 120, win_h // 2 - 120),
                    _UI_TEXT_RGB,
                )
                mx, my = pygame.mouse.get_pos()
                btn_start = pygame.Rect(win_w // 2 - 110, win_h // 2 - 28, 220, 48)
                _draw_button(
                    surf,
                    font_mid,
                    btn_start,
                    "Start Game",
                    hovered=btn_start.collidepoint(mx, my),
                )
                _draw_text(
                    surf,
                    font,
                    "Esc — quit",
                    (24, win_h - 36),
                    _UI_MUTED_TEXT_RGB,
                )

            elif screen == "new_game_maps":
                surf.fill(_UI_BG_RGB)
                _draw_text(surf, font_big, "Choose a map", (60, 48), _UI_TEXT_RGB)
                _draw_text(
                    surf,
                    font,
                    "JSON files in assets/",
                    (60, 88),
                    _UI_MUTED_TEXT_RGB,
                )
                mx, my = pygame.mouse.get_pos()
                btn_back = pygame.Rect(60, win_h - 70, 120, 36)
                _draw_button(
                    surf, font_mid, btn_back, "Back", hovered=btn_back.collidepoint(mx, my)
                )

                list_rect = pygame.Rect(40, 120, win_w - 80, win_h - 210)
                pygame.draw.rect(surf, _UI_PANEL_RGB, list_rect, border_radius=8)
                pygame.draw.rect(surf, _UI_BORDER_RGB, list_rect, width=1, border_radius=8)

                maps = _list_map_files_in_assets()
                if not maps:
                    _draw_text(
                        surf,
                        font,
                        "No .json maps found in assets/. Add a map or use Map Creator.",
                        (list_rect.x + 16, list_rect.y + 20),
                        _UI_MUTED_TEXT_RGB,
                    )
                else:
                    row_h = 38
                    y = list_rect.y + 8 - new_game_map_scroll
                    for path in maps:
                        pick_rect = pygame.Rect(list_rect.x + 8, y, list_rect.w - 16, row_h - 4)
                        y += row_h
                        if pick_rect.bottom < list_rect.top or pick_rect.top > list_rect.bottom:
                            continue
                        hovered = pick_rect.collidepoint(mx, my)
                        sel = (
                            pending_map_path is not None
                            and path.resolve() == pending_map_path.resolve()
                        )
                        _draw_button(surf, font, pick_rect, path.name, hovered=hovered, active=sel)

                if new_game_status:
                    _draw_text(surf, font, new_game_status, (60, win_h - 110), (240, 120, 120))

            elif screen == "new_game_dragon":
                surf.fill(_UI_BG_RGB)
                title = "Choose your dragon"
                if dragon_pick_context == "same_map_reset":
                    title = f"{title} — same map, fresh run"
                elif pending_map_path is not None:
                    title = f"{title} — {pending_map_path.name}"
                _draw_text(surf, font_big, title, (60, 40), _UI_TEXT_RGB)
                mx, my = pygame.mouse.get_pos()
                btn_back = pygame.Rect(60, win_h - 70, 120, 36)
                _draw_button(
                    surf, font_mid, btn_back, "Back", hovered=btn_back.collidepoint(mx, my)
                )

                y0 = 110
                for i, kind in enumerate(playable_dragon_kinds()):
                    d_row = pygame.Rect(60, y0 + i * 46, min(520, win_w - 120), 40)
                    hovered = d_row.collidepoint(mx, my)
                    active = kind is session_dragon_kind
                    _draw_button(
                        surf,
                        font_mid,
                        d_row,
                        display_name_for_kind(kind),
                        hovered=hovered,
                        active=active,
                    )

                btn_play = pygame.Rect(60, y0 + len(playable_dragon_kinds()) * 46 + 24, 200, 44)
                can_play = pending_map_path is not None or dragon_pick_context == "same_map_reset"
                _draw_button(
                    surf,
                    font_mid,
                    btn_play,
                    "Play",
                    hovered=can_play and btn_play.collidepoint(mx, my),
                    active=False,
                )
                if not can_play:
                    _draw_text(
                        surf,
                        font,
                        "Select a map first (Back).",
                        (btn_play.right + 16, btn_play.y + 12),
                        _UI_MUTED_TEXT_RGB,
                    )

                pick_list_w = min(520, win_w - 120)
                list_right = 60 + pick_list_w
                preview_img = load_detailed_sprite(session_dragon_kind)
                if preview_img is not None:
                    slot_x = list_right + 28
                    slot_w = win_w - slot_x - 28
                    if slot_w >= 120:
                        slot_h = min(280, win_h - y0 - 40)
                        portrait = scaled_to_fit(preview_img, slot_w, max(80, slot_h))
                        surf.blit(portrait, (slot_x, y0))
                    else:
                        below_y = btn_play.bottom + 20
                        slot_h = min(200, win_h - below_y - 90)
                        if slot_h >= 72:
                            portrait = scaled_to_fit(preview_img, pick_list_w, slot_h)
                            surf.blit(portrait, (60, below_y))

                if new_game_status:
                    _draw_text(surf, font, new_game_status, (60, win_h - 110), (240, 120, 120))

            elif screen == "game" and game_map is not None and dragon is not None:
                assert citadel_coord is not None
                caption = font.render(
                    (
                        f"Day {day_index}  |  Gold {dragon.gold}  |  "
                        f"{display_name_for_kind(dragon.kind)}  |  "
                        "Green bar = hours left  |  Muted = unreachable  |  "
                        "Right-click: inspect  |  Citadel: upgrades then next day"
                    ),
                    True,
                    (210, 210, 220),
                )
                surf.blit(caption, (8, 6))
                _draw_hour_bar(surf, dragon.hours_remaining, win_w)

                map_area_h = win_h - TIME_BAR_HEIGHT - SETTINGS_BAR_HEIGHT
                map_viewport = _map_viewport_rect(
                    win_w,
                    win_h,
                    dragon_panel_w=dragon_panel_w,
                    inspector_panel_w=inspector_panel_w,
                )
                clip_prev = surf.get_clip()
                surf.set_clip(map_viewport)
                pygame.draw.rect(surf, BACKGROUND_COLOR, map_viewport)
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
                marker_side = int(max(8, min(hex_size * 1.35, hex_size * 1.55) * 2))
                marker = map_marker_surface(dragon.kind, marker_side)
                if marker is not None:
                    mrect = marker.get_rect(center=(int(round(cx)), int(round(cy))))
                    surf.blit(marker, mrect)
                else:
                    radius = max(3, int(hex_size * 0.18))
                    pygame.draw.circle(
                        surf,
                        _DRAGON_DOT_RGB,
                        (int(round(cx)), int(round(cy))),
                        radius,
                    )
                surf.set_clip(clip_prev)

                dragon_panel_rect = pygame.Rect(0, TIME_BAR_HEIGHT, dragon_panel_w, map_area_h)
                dragon_ability_button_rects = _draw_dragon_panel(
                    surf,
                    font,
                    font_small,
                    panel_rect=dragon_panel_rect,
                    dragon=dragon,
                    world=game_map,
                )

                panel_rect = pygame.Rect(
                    win_w - inspector_panel_w,
                    TIME_BAR_HEIGHT,
                    inspector_panel_w,
                    map_area_h,
                )
                inspector_raid_button_rect = _draw_tile_inspector_panel(
                    surf,
                    font,
                    font_small,
                    panel_rect=panel_rect,
                    game_map=game_map,
                    settlements_by_coord=settlements_by_coord,
                    inspector_focus_coord=inspector_focus_coord,
                    inspector_message=inspector_message,
                    dragon=dragon,
                    raid_combat_active=raid_combat_settlement is not None,
                )

                if raid_combat_settlement is not None:
                    raid_overlay_attack_rect, raid_overlay_retreat_rect = _draw_raid_combat_overlay(
                        surf,
                        font,
                        font_small,
                        map_viewport=map_viewport,
                        dragon=dragon,
                        settlement=raid_combat_settlement,
                        banner=raid_overlay_banner,
                    )
                else:
                    raid_overlay_attack_rect = None
                    raid_overlay_retreat_rect = None

                if targeting_ability_name is not None:
                    mx_t, my_t = pygame.mouse.get_pos()
                    pygame.draw.circle(surf, (90, 210, 255), (mx_t, my_t), 7, width=2)
                    _draw_text(
                        surf,
                        font_small,
                        f"Targeting {targeting_ability_name}: left-click map, right-click/Esc cancel",
                        (dragon_panel_w + 12, TIME_BAR_HEIGHT + 10),
                        (160, 230, 255),
                    )

                bar_rect = pygame.Rect(0, win_h - SETTINGS_BAR_HEIGHT, win_w, SETTINGS_BAR_HEIGHT)
                pygame.draw.rect(surf, _UI_BG_RGB, bar_rect)
                pygame.draw.rect(surf, _UI_BORDER_RGB, bar_rect, width=1)
                btn = pygame.Rect(win_w - 140, win_h - SETTINGS_BAR_HEIGHT + 10, 120, 36)
                hovered = btn.collidepoint(pygame.mouse.get_pos())
                _draw_button(surf, font_mid, btn, "Settings", hovered=hovered)

                dragon_upgrade_overlay_click = None
                if dragon_upgrade_overlay_active and dragon_upgrade_overlay_baseline is not None:
                    dragon_upgrade_overlay_click = _draw_dragon_upgrade_overlay(
                        surf,
                        client_w=win_w,
                        client_h=win_h,
                        font_mid=font_mid,
                        font_small=font_small,
                        font_small_bold=font_small_bold,
                        baseline=dragon_upgrade_overlay_baseline,
                        draft=dragon_upgrade_draft,
                    )

            elif screen == "settings":
                surf.fill(_UI_BG_RGB)
                _draw_text(surf, font_big, "Settings", (60, 60), _UI_TEXT_RGB)

                mx, my = pygame.mouse.get_pos()
                btn_creator = pygame.Rect(60, 130, 260, 40)
                btn_loader = pygame.Rect(60, 182, 260, 40)
                btn_editor = pygame.Rect(60, 234, 260, 40)
                btn_new_game = pygame.Rect(60, 286, 260, 40)
                btn_dev = pygame.Rect(60, 338, 260, 40)
                btn_back = pygame.Rect(60, win_h - 70, 120, 36)

                _draw_button(
                    surf,
                    font_mid,
                    btn_creator,
                    "Map Creator",
                    hovered=btn_creator.collidepoint(mx, my),
                )
                _draw_button(
                    surf,
                    font_mid,
                    btn_loader,
                    "Map Loader",
                    hovered=btn_loader.collidepoint(mx, my),
                )
                _draw_button(
                    surf,
                    font_mid,
                    btn_editor,
                    "Map Editor",
                    hovered=btn_editor.collidepoint(mx, my),
                )
                _draw_button(
                    surf,
                    font_mid,
                    btn_new_game,
                    "New Game",
                    hovered=btn_new_game.collidepoint(mx, my),
                )
                _draw_button(
                    surf,
                    font_mid,
                    btn_dev,
                    "Dev Mode",
                    hovered=btn_dev.collidepoint(mx, my),
                )
                _draw_text(
                    surf,
                    font,
                    "Load + edit; Save overwrites the file.",
                    (60, 386),
                    _UI_MUTED_TEXT_RGB,
                )
                _draw_button(
                    surf, font_mid, btn_back, "Back", hovered=btn_back.collidepoint(mx, my)
                )

                if settings_status:
                    _draw_text(surf, font, settings_status, (60, 426), _UI_MUTED_TEXT_RGB)

            elif screen == "map_creator_setup":
                surf.fill(_UI_BG_RGB)
                _draw_text(surf, font_big, "Map Creator", (60, 60), _UI_TEXT_RGB)
                _draw_text(
                    surf, font, "Enter map dimensions and a name.", (60, 105), _UI_MUTED_TEXT_RGB
                )

                _draw_text_field(surf, font_mid, draft.dims, focused=(focused_field == "dims"))
                _draw_text_field(surf, font_mid, draft.name, focused=(focused_field == "name"))

                mx, my = pygame.mouse.get_pos()
                btn_create = pygame.Rect(60, 320, 140, 40)
                btn_back = pygame.Rect(220, 320, 100, 40)
                _draw_button(
                    surf, font_mid, btn_create, "Create", hovered=btn_create.collidepoint(mx, my)
                )
                _draw_button(
                    surf, font_mid, btn_back, "Back", hovered=btn_back.collidepoint(mx, my)
                )

                if draft.error:
                    _draw_text(surf, font, draft.error, (60, 380), (240, 120, 120))

            elif screen in ("map_creator_editor", "map_editor") and editor is not None:
                ed = editor
                surf.fill(_UI_BG_RGB)
                mode_label = "Map Editor" if screen == "map_editor" else "Map Creator"
                _draw_text(surf, font_big, f"{mode_label} — {ed.name}", (24, 18), _UI_TEXT_RGB)

                toolbar_w = 240
                top_pad = 70
                bottom_pad = SETTINGS_BAR_HEIGHT

                map_view = pygame.Rect(0, top_pad, win_w - toolbar_w, win_h - top_pad - bottom_pad)
                toolbar = pygame.Rect(
                    win_w - toolbar_w,
                    top_pad,
                    toolbar_w,
                    win_h - top_pad - bottom_pad,
                )
                bottom = pygame.Rect(0, win_h - SETTINGS_BAR_HEIGHT, win_w, SETTINGS_BAR_HEIGHT)

                pygame.draw.rect(surf, _UI_PANEL_RGB, toolbar)
                pygame.draw.rect(surf, _UI_BORDER_RGB, toolbar, width=1)
                pygame.draw.rect(surf, _UI_BG_RGB, bottom)
                pygame.draw.rect(surf, _UI_BORDER_RGB, bottom, width=1)

                tiles: dict[OffsetCoord, Tile] = {}
                for coord, terr in ed.tiles.items():
                    terrain = Terrain.GRASSLAND if terr is None else terr
                    sk = (
                        ed.settlement_kinds.get(coord, SettlementType.VILLAGE)
                        if terrain is Terrain.SETTLEMENT
                        else None
                    )
                    tiles[coord] = Tile(coord=coord, terrain=terrain, settlement_kind=sk)
                edit_map = GameMap(
                    width=ed.width,
                    height=ed.height,
                    hex_size=float(_DEFAULT_HEX_SIZE_HINT),
                    orientation="flat",
                    tiles=tiles,
                )

                hs, (ox, oy), _ = layout_map_on_canvas(edit_map, map_view.w, map_view.h)
                origin_edit = (ox + float(map_view.x), oy + float(map_view.y))

                def tile_color(tile: Tile) -> tuple[int, int, int]:
                    terr = ed.tiles.get(tile.coord)
                    if terr is None:
                        return TERRAIN_COLORS[Terrain.GRASSLAND]
                    if terr is Terrain.SETTLEMENT:
                        k = ed.settlement_kinds.get(tile.coord, SettlementType.VILLAGE)
                        return SETTLEMENT_KIND_FILL[k]
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
                stride = button_h + 10
                for label, terr in _tile_types_for_toolbar():
                    r = pygame.Rect(toolbar.x + 14, y, toolbar.w - 28, button_h)
                    hovered = r.collidepoint(mx, my)
                    active = ed.brush == "terrain" and ed.selected is terr
                    _draw_button(surf, font, r, label, hovered=hovered, active=active)
                    y += stride

                y += 6
                _draw_text(surf, font_mid, "Settlement types", (toolbar.x + 14, y), _UI_TEXT_RGB)
                y += 28
                settle_labels = (
                    ("Village", SettlementType.VILLAGE),
                    ("City", SettlementType.CITY),
                    ("Fort", SettlementType.FORT),
                )
                gap_x = 8
                settle_w = max(44, (toolbar.w - 28 - 2 * gap_x) // 3)
                for i, (slabel, skind) in enumerate(settle_labels):
                    r = pygame.Rect(toolbar.x + 14 + i * (settle_w + gap_x), y, settle_w, button_h)
                    hovered = r.collidepoint(mx, my)
                    active = ed.brush == "settlement" and ed.selected_settlement_kind is skind
                    _draw_button(surf, font, r, slabel, hovered=hovered, active=active)
                y += stride

                btn_save = pygame.Rect(toolbar.x + 14, toolbar.bottom - 54, toolbar.w - 28, 40)
                _draw_button(
                    surf, font_mid, btn_save, "Save", hovered=btn_save.collidepoint(mx, my)
                )

                btn_back = pygame.Rect(win_w - 130, win_h - SETTINGS_BAR_HEIGHT + 10, 110, 36)
                _draw_button(
                    surf, font_mid, btn_back, "Back", hovered=btn_back.collidepoint(mx, my)
                )

                if ed.status:
                    _draw_text(
                        surf, font, ed.status, (24, win_h - SETTINGS_BAR_HEIGHT + 18), _UI_TEXT_RGB
                    )

            pygame.display.flip()

        redraw()

        running = True
        while running:
            for event in pygame.event.get():
                if event.type == pygame.QUIT:
                    running = False
                    break
                if event.type == pygame.KEYDOWN and event.key == pygame.K_ESCAPE:
                    if screen == "main_menu":
                        running = False
                        break
                    if screen == "new_game_maps":
                        screen = "main_menu"
                        new_game_map_scroll = 0
                        new_game_status = ""
                        pending_map_path = None
                        dragon_pick_context = None
                        redraw()
                        continue
                    if screen == "new_game_dragon":
                        ctx = dragon_pick_context or "new_game"
                        if ctx in ("load_map", "same_map_reset"):
                            screen = "settings"
                            pending_map_path = None
                            dragon_pick_context = None
                            new_game_status = ""
                            settings_status = ""
                        else:
                            screen = "new_game_maps"
                            new_game_status = ""
                        redraw()
                        continue
                    if screen == "game" and dragon_upgrade_overlay_active:
                        redraw()
                        continue
                    if screen == "game" and targeting_ability_name is not None:
                        targeting_ability_name = None
                        inspector_message = "Ability targeting cancelled."
                        redraw()
                        continue
                    if screen == "game":
                        running = False
                        break
                    if screen == "map_creator_editor":
                        editor = None
                        screen = "map_creator_setup"
                        focused_field = None
                        draft.error = ""
                        redraw()
                        continue
                    if screen == "map_editor":
                        editor = None
                        screen = "settings"
                        settings_status = ""
                        redraw()
                        continue
                    if screen == "map_creator_setup":
                        screen = "settings"
                        focused_field = None
                        draft.error = ""
                        redraw()
                        continue
                    if screen == "settings":
                        screen = "game"
                        settings_status = ""
                        redraw()
                        continue
                    screen = "game"
                    focused_field = None
                    draft.error = ""
                    redraw()
                    continue
                if event.type == pygame.MOUSEWHEEL and screen == "new_game_maps":
                    new_game_map_scroll = max(0, new_game_map_scroll - event.y * 24)
                    redraw()
                    continue

                if event.type == pygame.MOUSEBUTTONUP and event.button == 1:
                    splitter_drag = None

                if (
                    event.type == pygame.MOUSEMOTION
                    and splitter_drag is not None
                    and screen == "game"
                    and game_map is not None
                ):
                    mx_m, _my_m = event.pos
                    if splitter_drag == "left":
                        dragon_panel_w, inspector_panel_w = clamp_gameplay_side_panel_widths(
                            win_w,
                            mx_m,
                            inspector_panel_w,
                            min_dragon=min_dragon_panel_w,
                            min_inspector=min_inspector_panel_w,
                            min_map_viewport_w=GAMEPLAY_MIN_MAP_VIEWPORT_W,
                        )
                    else:
                        dragon_panel_w, inspector_panel_w = clamp_gameplay_side_panel_widths(
                            win_w,
                            dragon_panel_w,
                            win_w - mx_m,
                            min_dragon=min_dragon_panel_w,
                            min_inspector=min_inspector_panel_w,
                            min_map_viewport_w=GAMEPLAY_MIN_MAP_VIEWPORT_W,
                        )
                    apply_layout(win_w, win_h)
                    redraw()
                    continue

                resized = client_size_from_resize_event(event)
                if resized is not None:
                    nw, nh = resized
                    if game_map is not None:
                        fw, fh = gameplay_client_floors()
                        nw = max(nw, fw)
                        nh = max(nh, fh)
                    nw, nh = clamp_client_window_size(nw, nh, desktop)
                    pygame.display.set_mode((nw, nh), pygame.RESIZABLE)
                    pygame.display.set_caption(window_title)
                    if game_map is not None:
                        dragon_panel_w, inspector_panel_w = clamp_gameplay_side_panel_widths(
                            nw,
                            dragon_panel_w,
                            inspector_panel_w,
                            min_dragon=min_dragon_panel_w,
                            min_inspector=min_inspector_panel_w,
                            min_map_viewport_w=GAMEPLAY_MIN_MAP_VIEWPORT_W,
                        )
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

                if event.type == pygame.MOUSEBUTTONDOWN and event.button == 3:
                    in_play_session_rc = (
                        screen == "game"
                        and game_map is not None
                        and dragon is not None
                        and citadel_coord is not None
                    )
                    if in_play_session_rc and not dragon_upgrade_overlay_active:
                        if targeting_ability_name is not None:
                            targeting_ability_name = None
                            inspector_message = "Ability targeting cancelled."
                            redraw()
                            continue
                        mx_r, my_r = event.pos
                        gmap_rc = game_map
                        if gmap_rc is None:
                            continue
                        map_left = dragon_panel_w
                        map_right_excl = win_w - inspector_panel_w
                        if hit_test_gameplay_panel_splitter(
                            mx_r,
                            my_r,
                            win_w,
                            win_h,
                            dragon_panel_w=dragon_panel_w,
                            inspector_panel_w=inspector_panel_w,
                        ):
                            continue
                        if (
                            TIME_BAR_HEIGHT <= my_r <= win_h - SETTINGS_BAR_HEIGHT
                            and map_left <= mx_r < map_right_excl
                        ):
                            inspector_focus_coord = _pick_tile_at_pixel(
                                float(mx_r),
                                float(my_r),
                                gmap_rc,
                                hex_size,
                                origin,
                            )
                            inspector_message = ""
                            redraw()
                    continue

                if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
                    mx, my = event.pos

                    if screen == "main_menu":
                        btn_start = pygame.Rect(win_w // 2 - 110, win_h // 2 - 28, 220, 48)
                        if btn_start.collidepoint(mx, my):
                            screen = "new_game_maps"
                            new_game_map_scroll = 0
                            new_game_status = ""
                            pending_map_path = None
                            dragon_pick_context = None
                            redraw()
                        continue

                    if screen == "new_game_maps":
                        btn_back = pygame.Rect(60, win_h - 70, 120, 36)
                        if btn_back.collidepoint(mx, my):
                            screen = "main_menu"
                            new_game_map_scroll = 0
                            new_game_status = ""
                            pending_map_path = None
                            dragon_pick_context = None
                            redraw()
                            continue
                        list_rect = pygame.Rect(40, 120, win_w - 80, win_h - 210)
                        maps = _list_map_files_in_assets()
                        row_h = 38
                        y = list_rect.y + 8 - new_game_map_scroll
                        picked_path: Path | None = None
                        for path in maps:
                            pick_rect = pygame.Rect(list_rect.x + 8, y, list_rect.w - 16, row_h - 4)
                            y += row_h
                            if pick_rect.collidepoint(mx, my) and list_rect.collidepoint(mx, my):
                                picked_path = path
                                break
                        if picked_path is not None:
                            pending_map_path = picked_path
                            new_game_status = ""
                            dragon_pick_context = "new_game"
                            screen = "new_game_dragon"
                            redraw()
                        continue

                    if screen == "new_game_dragon":
                        btn_back = pygame.Rect(60, win_h - 70, 120, 36)
                        if btn_back.collidepoint(mx, my):
                            ctx = dragon_pick_context or "new_game"
                            if ctx in ("load_map", "same_map_reset"):
                                screen = "settings"
                                pending_map_path = None
                                dragon_pick_context = None
                                new_game_status = ""
                                settings_status = ""
                            else:
                                screen = "new_game_maps"
                                new_game_status = ""
                            redraw()
                            continue
                        y0 = 110
                        clicked_kind: DragonKind | None = None
                        for i, kind in enumerate(playable_dragon_kinds()):
                            d_row = pygame.Rect(60, y0 + i * 46, min(520, win_w - 120), 40)
                            if d_row.collidepoint(mx, my):
                                clicked_kind = kind
                                break
                        if clicked_kind is not None:
                            session_dragon_kind = clicked_kind
                            new_game_status = ""
                            redraw()
                            continue
                        btn_play = pygame.Rect(
                            60, y0 + len(playable_dragon_kinds()) * 46 + 24, 200, 44
                        )
                        can_play = pending_map_path is not None or dragon_pick_context == "same_map_reset"
                        if btn_play.collidepoint(mx, my) and can_play:
                            if dragon_pick_context == "same_map_reset":
                                if game_map is not None:
                                    _reset_session_for_map(game_map)
                                    dragon_pick_context = None
                                    new_game_status = ""
                                else:
                                    new_game_status = "No map loaded."
                            else:
                                ok, err = _begin_play_session_from_pending_map()
                                if not ok:
                                    new_game_status = err
                            redraw()
                        continue

                    in_play_session = (
                        screen == "game"
                        and game_map is not None
                        and dragon is not None
                        and citadel_coord is not None
                    )
                    if in_play_session:
                        assert (
                            game_map is not None
                            and dragon is not None
                            and citadel_coord is not None
                        )
                        gmap, dgn, ccd = game_map, dragon, citadel_coord

                        if dragon_upgrade_overlay_active:
                            if dragon_upgrade_overlay_click is not None:
                                clk = dragon_upgrade_overlay_click
                                assert dragon_upgrade_overlay_baseline is not None
                                base = dragon_upgrade_overlay_baseline
                                if clk.reset.collidepoint(mx, my):
                                    dragon_upgrade_draft = []
                                    redraw()
                                    continue
                                if clk.next_day.collidepoint(mx, my):
                                    total = total_dragon_upgrade_draft_cost(
                                        base, dragon_upgrade_draft
                                    )
                                    if base.gold - total < 0:
                                        redraw()
                                        continue
                                    apply_dragon_upgrade_draft(dgn, list(dragon_upgrade_draft))
                                    dragon_upgrade_draft = []
                                    dragon_upgrade_overlay_active = False
                                    dragon_upgrade_overlay_baseline = None
                                    dragon_upgrade_overlay_click = None
                                    dgn.begin_new_day_at_citadel(ccd)
                                    day_index += 1
                                    for ent in settlements_by_coord.values():
                                        ent.on_settlement_phase_end()
                                    redraw()
                                    continue
                                for st, rr in clk.cost.items():
                                    if rr.collidepoint(mx, my):
                                        trial = list(dragon_upgrade_draft) + [st]
                                        if (
                                            total_dragon_upgrade_draft_cost(base, trial)
                                            <= base.gold
                                        ):
                                            dragon_upgrade_draft.append(st)
                                        redraw()
                                        continue
                            redraw()
                            continue

                        sp_hit = hit_test_gameplay_panel_splitter(
                            mx,
                            my,
                            win_w,
                            win_h,
                            dragon_panel_w=dragon_panel_w,
                            inspector_panel_w=inspector_panel_w,
                        )
                        if sp_hit is not None:
                            splitter_drag = sp_hit
                            redraw()
                            continue
                        settings_btn = pygame.Rect(
                            win_w - 140,
                            win_h - SETTINGS_BAR_HEIGHT + 10,
                            120,
                            36,
                        )
                        if settings_btn.collidepoint(mx, my):
                            screen = "settings"
                            redraw()
                            continue

                        map_row_top = TIME_BAR_HEIGHT
                        map_row_bottom = win_h - SETTINGS_BAR_HEIGHT
                        map_left = dragon_panel_w
                        map_right_excl = win_w - inspector_panel_w
                        in_map_column = map_left <= mx < map_right_excl
                        in_map_row = map_row_top <= my <= map_row_bottom

                        if (
                            map_row_top <= my <= map_row_bottom
                            and mx < dragon_panel_w
                            and raid_combat_settlement is None
                        ):
                            for ability_name, rect in dragon_ability_button_rects.items():
                                if rect.collidepoint(mx, my):
                                    result = try_use_ability(
                                        dgn,
                                        ability_name,
                                        world=gmap,
                                        citadel_coord=ccd,
                                        settlements_by_coord=settlements_by_coord,
                                    )
                                    if result.ok and result.target_required:
                                        targeting_ability_name = ability_name
                                        inspector_message = result.reason
                                    elif result.ok:
                                        targeting_ability_name = None
                                        inspector_message = result.reason
                                    else:
                                        inspector_message = result.reason
                                    redraw()
                                    break
                            else:
                                redraw()
                            continue

                        if targeting_ability_name is not None:
                            if not in_map_row or not in_map_column:
                                continue
                            picked_target = _pick_tile_at_pixel(
                                float(mx),
                                float(my),
                                gmap,
                                hex_size,
                                origin,
                            )
                            if picked_target is None:
                                continue
                            result = try_use_ability(
                                dgn,
                                targeting_ability_name,
                                world=gmap,
                                citadel_coord=ccd,
                                settlements_by_coord=settlements_by_coord,
                                target=picked_target,
                            )
                            inspector_message = result.reason
                            if result.ok:
                                targeting_ability_name = None
                            redraw()
                            continue

                        if raid_combat_settlement is not None:
                            if (
                                raid_overlay_retreat_rect is not None
                                and raid_overlay_retreat_rect.collidepoint(mx, my)
                            ):
                                on_combat_ended(dgn)
                                raid_combat_settlement = None
                                raid_overlay_banner = ""
                                raid_overlay_auto_close_deadline_ms = None
                                redraw()
                                continue
                            if (
                                raid_overlay_attack_rect is not None
                                and raid_overlay_attack_rect.collidepoint(mx, my)
                            ):
                                target = raid_combat_settlement
                                if target.hp <= 0 or dgn.hp <= 0:
                                    redraw()
                                    continue
                                exchange = resolve_settlement_combat_round(
                                    dgn,
                                    target,
                                    gmap,
                                    citadel_coord=ccd,
                                )
                                if isinstance(exchange, MoveAttempt):
                                    on_combat_ended(dgn)
                                    raid_overlay_banner = exchange.reason
                                    raid_combat_settlement = None
                                    raid_overlay_auto_close_deadline_ms = None
                                    inspector_message = exchange.reason
                                    redraw()
                                    continue

                                if target.hp <= 0:
                                    on_combat_ended(dgn)
                                    gold_added, _events = apply_settlement_raid_victory_bundle(
                                        dgn,
                                        target,
                                        list(settlements_by_coord.values()),
                                        map_width=gmap.width,
                                    )
                                    dname = display_name_for_kind(dgn.kind)
                                    raid_overlay_banner = (
                                        f"{dname} won and gained {gold_added} gold"
                                    )
                                    raid_overlay_auto_close_deadline_ms = (
                                        pygame.time.get_ticks() + RAID_COMBAT_OVERLAY_AUTO_CLOSE_MS
                                    )
                                elif dgn.hp <= 0:
                                    on_combat_ended(dgn)
                                    raid_overlay_banner = "Your dragon was defeated."
                                    raid_overlay_auto_close_deadline_ms = (
                                        pygame.time.get_ticks() + RAID_COMBAT_OVERLAY_AUTO_CLOSE_MS
                                    )
                                else:
                                    raid_overlay_banner = ""
                                redraw()
                                continue
                            if in_map_row and in_map_column:
                                redraw()
                                continue

                        if not in_map_column and map_row_top <= my <= map_row_bottom:
                            if (
                                inspector_raid_button_rect is not None
                                and inspector_raid_button_rect.collidepoint(mx, my)
                                and inspector_focus_coord is not None
                            ):
                                target_settlement = settlements_by_coord.get(inspector_focus_coord)
                                if target_settlement is not None:
                                    ok, reason = validate_settlement_raid(
                                        dgn, target_settlement, gmap
                                    )
                                    if ok:
                                        raid_combat_settlement = target_settlement
                                        raid_overlay_banner = ""
                                        raid_overlay_auto_close_deadline_ms = None
                                        inspector_message = ""
                                    else:
                                        inspector_message = reason
                            redraw()
                            continue

                        if not in_map_row or not in_map_column:
                            continue

                        picked = _pick_tile_at_pixel(float(mx), float(my), gmap, hex_size, origin)
                        if picked is None:
                            continue
                        outcome = dgn.move(picked, gmap, ccd)
                        if outcome.ok and dgn.position == ccd:
                            dragon_upgrade_overlay_active = True
                            dragon_upgrade_draft = []
                            dragon_upgrade_overlay_baseline = dragon_upgrade_baseline_from_dragon(
                                dgn
                            )
                            dragon_upgrade_overlay_click = None
                        redraw()
                        continue

                    if screen == "settings":
                        btn_creator = pygame.Rect(60, 130, 260, 40)
                        btn_loader = pygame.Rect(60, 182, 260, 40)
                        btn_editor = pygame.Rect(60, 234, 260, 40)
                        btn_new_game = pygame.Rect(60, 286, 260, 40)
                        btn_dev = pygame.Rect(60, 338, 260, 40)
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
                            ok_path, msg_path = _validate_map_json_path_under_assets(chosen)
                            if not ok_path:
                                settings_status = msg_path
                                redraw()
                                continue
                            pending_map_path = chosen
                            dragon_pick_context = "load_map"
                            new_game_status = ""
                            settings_status = ""
                            screen = "new_game_dragon"
                            redraw()
                            continue
                        if btn_editor.collidepoint(mx, my):
                            chosen = _pick_map_file_from_assets()
                            if chosen is None:
                                settings_status = "No file selected."
                                redraw()
                                continue
                            ok_open, msg_open, ed_state = _open_editor_from_map_path(chosen)
                            if ok_open and ed_state is not None:
                                editor = ed_state
                                settings_status = msg_open
                                screen = "map_editor"
                                redraw()
                                continue
                            settings_status = msg_open
                            redraw()
                            continue
                        if btn_new_game.collidepoint(mx, my):
                            if game_map is None:
                                settings_status = "No map in play."
                                redraw()
                                continue
                            pending_map_path = None
                            dragon_pick_context = "same_map_reset"
                            new_game_status = ""
                            settings_status = ""
                            screen = "new_game_dragon"
                            redraw()
                            continue
                        if btn_dev.collidepoint(mx, my):
                            if dragon is None:
                                settings_status = "No dragon in session."
                                redraw()
                                continue
                            dragon.gold += DEV_MODE_TEST_GOLD_GRANT
                            settings_status = (
                                f"Dev Mode: +{DEV_MODE_TEST_GOLD_GRANT:,} gold."
                            )
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

                    if screen in ("map_creator_editor", "map_editor") and editor is not None:
                        toolbar_w = 240
                        top_pad = 70
                        bottom_pad = SETTINGS_BAR_HEIGHT
                        map_view = pygame.Rect(
                            0, top_pad, win_w - toolbar_w, win_h - top_pad - bottom_pad
                        )
                        toolbar = pygame.Rect(
                            win_w - toolbar_w, top_pad, toolbar_w, win_h - top_pad - bottom_pad
                        )
                        btn_back = pygame.Rect(
                            win_w - 130, win_h - SETTINGS_BAR_HEIGHT + 10, 110, 36
                        )
                        if btn_back.collidepoint(mx, my):
                            if screen == "map_editor":
                                screen = "settings"
                            else:
                                screen = "map_creator_setup"
                            editor = None
                            redraw()
                            continue

                        button_h = 34
                        stride = button_h + 10
                        y_hit = toolbar.y + 16 + 36
                        for _, terr in _tile_types_for_toolbar():
                            r = pygame.Rect(toolbar.x + 14, y_hit, toolbar.w - 28, button_h)
                            if r.collidepoint(mx, my):
                                editor.brush = "terrain"
                                editor.selected = terr
                                editor.status = ""
                                redraw()
                                break
                            y_hit += stride
                        else:
                            y_hit += 6 + 28
                            gap_x = 8
                            settle_w = max(44, (toolbar.w - 28 - 2 * gap_x) // 3)
                            settle_row = (
                                ("Village", SettlementType.VILLAGE),
                                ("City", SettlementType.CITY),
                                ("Fort", SettlementType.FORT),
                            )
                            for i, (_, skind) in enumerate(settle_row):
                                r = pygame.Rect(
                                    toolbar.x + 14 + i * (settle_w + gap_x),
                                    y_hit,
                                    settle_w,
                                    button_h,
                                )
                                if r.collidepoint(mx, my):
                                    editor.brush = "settlement"
                                    editor.selected_settlement_kind = skind
                                    editor.status = "Paint onto settlement hexes."
                                    redraw()
                                    break
                            else:
                                btn_save = pygame.Rect(
                                    toolbar.x + 14, toolbar.bottom - 54, toolbar.w - 28, 40
                                )
                                if btn_save.collidepoint(mx, my):
                                    ok, msg = _save_editor_map(editor)
                                    editor.status = msg
                                    redraw()
                                    continue

                                if map_view.collidepoint(mx, my):
                                    paint_tiles: dict[OffsetCoord, Tile] = {}
                                    for coord in editor.tiles:
                                        cell = editor.tiles.get(coord)
                                        cell_terrain = Terrain.GRASSLAND if cell is None else cell
                                        sk = (
                                            editor.settlement_kinds.get(
                                                coord, SettlementType.VILLAGE
                                            )
                                            if cell_terrain is Terrain.SETTLEMENT
                                            else None
                                        )
                                        paint_tiles[coord] = Tile(
                                            coord=coord,
                                            terrain=cell_terrain,
                                            settlement_kind=sk,
                                        )
                                    edit_map = GameMap(
                                        width=editor.width,
                                        height=editor.height,
                                        hex_size=float(_DEFAULT_HEX_SIZE_HINT),
                                        orientation="flat",
                                        tiles=paint_tiles,
                                    )
                                    hs, (ox, oy), _ = layout_map_on_canvas(
                                        edit_map, map_view.w, map_view.h
                                    )
                                    origin_edit = (ox + float(map_view.x), oy + float(map_view.y))
                                    picked = _pick_tile_at_pixel(
                                        float(mx), float(my), edit_map, hs, origin_edit
                                    )
                                    if picked is not None:
                                        if editor.brush == "terrain":
                                            editor.tiles[picked] = editor.selected
                                            if editor.selected is Terrain.SETTLEMENT:
                                                editor.settlement_kinds[picked] = (
                                                    editor.selected_settlement_kind
                                                )
                                            else:
                                                editor.settlement_kinds.pop(picked, None)
                                            editor.status = ""
                                        elif editor.tiles.get(picked) is Terrain.SETTLEMENT:
                                            editor.settlement_kinds[picked] = (
                                                editor.selected_settlement_kind
                                            )
                                            editor.status = ""
                                        else:
                                            editor.status = "Select a settlement hex first."
                                        redraw()

            if (
                screen == "game"
                and raid_overlay_auto_close_deadline_ms is not None
                and pygame.time.get_ticks() >= raid_overlay_auto_close_deadline_ms
            ):
                raid_combat_settlement = None
                raid_overlay_banner = ""
                raid_overlay_auto_close_deadline_ms = None
                redraw()

            clock.tick(_FRAME_RATE)
    finally:
        pygame.quit()

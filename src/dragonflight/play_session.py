"""Interactive play session — Pygame (pygame required).

Launched by default from ``python -m dragonflight`` (see ``__main__``): main menu,
then new-game map and dragon selection, then the main map session. Settings →
Map Loader picks a file then the same dragon chooser before loading. Click
reachable hexes to move the dragon from the citadel. Invalid tiles (flight range
or mandatory return to citadel on the daily clock) are drawn muted. A 24-segment
hour bar tracks remaining daylight.

Map viewport (central column during play):

- Mouse wheel or + / − controls (top-right of the map): zoom 1× (fit) to
  3×; wheel zoom is anchored under the cursor, buttons zoom toward the viewport
  center. Zooming back to 1× recenters the map and clears pan.
- WASD or arrow keys: pan while zoomed past 1× (ignored at full fit).

Camera math lives in :mod:`dragonflight.map_camera`.

Side-panel and upgrade overlay presentation live in :mod:`dragonflight.play_session_panels`;
shared Pygame chrome (text, buttons, scrollable panel layout) lives in :mod:`dragonflight.play_session_ui`.

This module couples presentation with :class:`~dragonflight.dragon.Dragon` for
the runnable prototype. A static map-only window is :func:`render.run_demo`.
"""

from __future__ import annotations

import json
import random
import re
import uuid
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

import pygame

from . import army_art
from .army import (
    Army,
    ArmyKind,
    HeroesPartyCityPool,
    grant_army_victory_loot,
    spawn_heroes_party_wave,
)
from .combat_preview import preview_army_round, preview_settlement_round
from .combatant_stats import (
    CombatantView,
    entity_combatant_view,
    entity_effective_atk,
    entity_effective_dfn,
)
from .debug_day_log import (
    DayDebugLog,
    SettlementPhaseBefore,
    log_army_phase,
    log_citadel_hp_change,
    log_dragon_end_of_day_heal,
    log_heroes_party_spawn,
    log_settlement_phase,
    log_world_event_effects,
    log_world_event_roll,
    snapshot_armies_before_phase,
)
from .dragon import DamageRoundExchange, Dragon, DragonKind, MoveAttempt
from .dragon_abilities import on_combat_ended, try_use_ability
from .dragon_art import load_detailed_sprite, map_marker_surface, scaled_to_fit
from .dragon_defaults import HOURS_PER_DRAGON_DAY
from .dragon_playables import (
    default_playable_kind,
    display_name_for_kind,
    new_playable_dragon,
    playable_dragon_kinds,
    selection_description_for_kind,
)
from .dragon_progression import (
    DragonUpgradeBaseline,
    DragonUpgradeStat,
    apply_dragon_upgrade_draft,
    dragon_upgrade_baseline_from_dragon,
    total_dragon_upgrade_draft_cost,
)
from .dragon_ui_theme import DragonUITheme, dragon_ui_theme_for_kind
from .entity_stats import StatModifierBag
from .fog_of_war import (
    FOG_UNREVEALED_RGB,
    FogOfWarState,
    init_fog_from_dragon,
    is_revealed,
    reveal_coords_in_range,
)
from .game_tuning import (
    DifficultyLevel,
    GameTuning,
    apply_difficulty_preset,
    default_game_tuning,
)
from .hex_coord import HEX_CORNERS, OffsetCoord, offset_to_pixel
from .hour_bar_layout import hour_bar_segment_layout
from .map_camera import (
    MapViewportCamera,
    apply_keyboard_pan,
    apply_wheel_zoom,
    apply_zoom_step,
    camera_is_pannable,
    resolve_map_view,
)
from .map_loader import MapLoadError, load_map
from .map_state import GameMap, Tile, clone_game_map
from .play_session_panels import (
    DragonUpgradeOverlayClickRects,
    draw_dragon_panel,
    draw_dragon_upgrade_overlay,
    draw_tile_inspector_panel,
)
from .play_session_panels import (
    min_dragon_panel_column_width as _min_dragon_panel_column_width,
)
from .play_session_panels import (
    min_inspector_panel_column_width as _min_inspector_panel_column_width,
)
from .play_session_ui import (
    _UI_BG_RGB,
    _UI_BORDER_RGB,
    _UI_BUTTON_HOVER_RGB,
    _UI_DAMAGE_PREVIEW_RGB,
    _UI_INPUT_FOCUS_RGB,
    _UI_INPUT_RGB,
    _UI_MUTED_TEXT_RGB,
    _UI_PANEL_RGB,
    _UI_TEXT_RGB,
    DebugOverlayClick,
)
from .play_session_ui import (
    clamp_panel_scroll as _clamp_panel_scroll,
)
from .play_session_ui import (
    draw_button as _draw_button,
)
from .play_session_ui import (
    draw_panel_scrollbar as _draw_panel_scrollbar,
)
from .play_session_ui import (
    draw_text as _draw_text,
)
from .play_session_ui import (
    wrap_text_to_width as _wrap_text_to_width,
)
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
    draw_hex_outline,
    hex_corner_offset,
    layout_map_on_canvas,
    render_map,
)
from .settlement import (
    MockArmySpawnEvent,
    Settlement,
    SettlementType,
    apply_settlement_raid_victory_bundle,
    resolve_settlement_combat_round,
    validate_settlement_raid,
)
from .terrain import Terrain
from .tile_inspection import army_display_name_for_kind
from .world_events import (
    WorldEventDayState,
    apply_army_day_speed_modifiers,
    apply_world_event,
    army_movement_context,
    on_golden_caravan_defeated,
    roll_world_event,
    settlement_growth_is_delayed,
    settlement_phase_world_event_hooks,
)
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

#: Raid combat overlay covers this fraction of the map viewport height (central column).
RAID_COMBAT_OVERLAY_HEIGHT_FRACTION: float = 0.5

#: After a terminal combat outcome message, auto-close the raid overlay (milliseconds).
RAID_COMBAT_OVERLAY_AUTO_CLOSE_MS: int = 3000

#: Citadel HP at session start (spec num10 MVP).
CITADEL_STARTING_HP: int = 3

#: Map marker for active armies (drawn under the dragon sprite).
_ARMY_MARKER_RGB: tuple[int, int, int] = (128, 0, 200)
_HEROES_ARMY_MARKER_RGB: tuple[int, int, int] = (240, 160, 50)

#: Army map markers and combat portraits vs the dragon baseline size.
ARMY_MAP_MARKER_SCALE: float = 1.5
COMBAT_PORTRAIT_SCALE: float = 1.5

_MAP_ZOOM_BTN_SIZE: int = 28
_MAP_ZOOM_BTN_MARGIN: int = 8
_MAP_ZOOM_BTN_GAP: int = 4

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


def _draw_muted_hp_line_with_damage_preview(
    surface: pygame.Surface,
    font_small: pygame.font.Font,
    *,
    x: int,
    y: int,
    hp_line: str,
    damage: int,
) -> None:
    """Draw a muted HP line and a red ``  - {damage}`` suffix when ``damage > 0``."""

    _draw_text(surface, font_small, hp_line, (x, y), _UI_MUTED_TEXT_RGB)
    if damage <= 0:
        return
    rendered = font_small.render(hp_line, True, _UI_MUTED_TEXT_RGB)
    suffix = f"  - {damage}"
    _draw_text(surface, font_small, suffix, (x + rendered.get_width(), y), _UI_DAMAGE_PREVIEW_RGB)


_GAME_OPTIONS_FLOAT_SLIDERS = frozenset({"raid_eco_loss_divisor"})
_GAME_OPTIONS_FLOAT_STEP = 0.5


def _game_options_slider_defs() -> tuple[tuple[str, str, int | float, int | float], ...]:
    """``(GameTuning attribute, label, min, max)`` for Game Options sliders."""

    return (
        ("army_movement_speed", "Army movement per day", 1, 24),
        (
            "raid_aggression_dropoff_per_tile",
            "Raid aggression dropoff (per hex)",
            1,
            50,
        ),
        (
            "settlement_growth_eco_percent",
            "Settlement eco growth: (x% of current eco) + (10% of starting eco), max +200/day, rounded up",
            0,
            100,
        ),
        ("settlement_growth_stat_bonus", "Settlement ATK / DFN growth", 0, 10),
        ("raid_eco_loss_divisor", "Settlement eco loss on defeat (current eco / X)", 1.0, 10.0),
        ("raid_stat_loss", "Settlement stat loss on defeat (current eco / X)", 0, 50),
        (
            "settlement_heal_percent_of_max_at_zero",
            "Settlement healing when destroyed/ raided (% of max HP)",
            0,
            100,
        ),
        (
            "settlement_heal_percent_of_max_when_damaged",
            "Settlement healing when partially damaged (% of max HP)",
            0,
            100,
        ),
        (
            "dragon_citadel_end_of_day_base_heal_percent_of_max",
            "End-of-day dragon base heal (% of max HP)",
            0,
            100,
        ),
        (
            "world_event_chance_percent",
            "World event chance at start of each day (%)",
            0,
            100,
        ),
    )


def _game_options_slider_value_label(attr: str, value: int | float) -> str:
    if attr == "raid_eco_loss_divisor":
        return f"{value:g}"
    if attr in (
        "settlement_growth_eco_percent",
        "settlement_heal_percent_of_max_at_zero",
        "settlement_heal_percent_of_max_when_damaged",
        "dragon_citadel_end_of_day_base_heal_percent_of_max",
        "world_event_chance_percent",
    ):
        return f"{value}%"
    return str(value)


def _game_options_set_slider_from_mouse(
    game_tuning: GameTuning,
    attr: str,
    mouse_x: int,
    track: pygame.Rect,
    lo: int | float,
    hi: int | float,
) -> None:
    t = (mouse_x - track.x) / max(1, track.w)
    t = max(0.0, min(1.0, t))
    raw = lo + t * (hi - lo)
    if attr in _GAME_OPTIONS_FLOAT_SLIDERS:
        step = _GAME_OPTIONS_FLOAT_STEP
        v = round(raw / step) * step
        v = max(float(lo), min(float(hi), v))
        setattr(game_tuning, attr, v)
    else:
        v = int(round(raw))
        v = max(int(lo), min(int(hi), v))
        setattr(game_tuning, attr, v)


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


_DARK_ECLIPSE_RGB: tuple[int, int, int] = (8, 8, 12)


def _make_tile_color_fn(
    dragon: Dragon,
    citadel: OffsetCoord,
    game_map: GameMap,
    fog: FogOfWarState,
    *,
    dark_eclipse: bool = False,
):
    """Return per-tile fill: fog gray, else terrain with reachability muting."""

    from .dragon_abilities import effective_flight_range

    flight = effective_flight_range(dragon)

    def tile_color(tile: Tile) -> tuple[int, int, int]:
        if dark_eclipse and dragon.hex_distance_to(tile.coord) > flight:
            return _DARK_ECLIPSE_RGB
        if not is_revealed(fog, tile.coord):
            return FOG_UNREVEALED_RGB
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


def _editor_try_paint_at_pixel(
    editor: _MapEditorState,
    mx: float,
    my: float,
    map_view: pygame.Rect,
    *,
    skip_if_same_as: OffsetCoord | None = None,
) -> tuple[bool, OffsetCoord | None]:
    """Pick the hex under ``(mx, my)`` and apply the current brush.

    If ``skip_if_same_as`` equals the picked coordinate, returns ``(False, picked)``
    without mutating the editor (skips duplicate hexes while LMB-drag painting).

    Returns ``(needs_redraw, picked_coord)`` where ``needs_redraw`` is true when
    terrain/settlement state or editor status changed.
    """

    paint_tiles: dict[OffsetCoord, Tile] = {}
    for coord in editor.tiles:
        cell = editor.tiles.get(coord)
        cell_terrain = Terrain.GRASSLAND if cell is None else cell
        sk = (
            editor.settlement_kinds.get(coord, SettlementType.VILLAGE)
            if cell_terrain is Terrain.SETTLEMENT
            else None
        )
        paint_tiles[coord] = Tile(coord=coord, terrain=cell_terrain, settlement_kind=sk)
    edit_map = GameMap(
        width=editor.width,
        height=editor.height,
        hex_size=float(_DEFAULT_HEX_SIZE_HINT),
        orientation="flat",
        tiles=paint_tiles,
    )
    hs, (ox, oy), _ = layout_map_on_canvas(edit_map, map_view.w, map_view.h)
    origin_edit = (ox + float(map_view.x), oy + float(map_view.y))
    picked = _pick_tile_at_pixel(float(mx), float(my), edit_map, hs, origin_edit)
    if picked is None:
        return False, None
    if skip_if_same_as is not None and picked == skip_if_same_as:
        return False, picked

    if editor.brush == "terrain":
        editor.tiles[picked] = editor.selected
        if editor.selected is Terrain.SETTLEMENT:
            editor.settlement_kinds[picked] = editor.selected_settlement_kind
        else:
            editor.settlement_kinds.pop(picked, None)
        editor.status = ""
    elif editor.tiles.get(picked) is Terrain.SETTLEMENT:
        editor.settlement_kinds[picked] = editor.selected_settlement_kind
        editor.status = ""
    else:
        editor.status = "Select a settlement hex first."
    return True, picked


def _dragon_screen_center(
    position: OffsetCoord,
    hex_size: float,
    origin: tuple[float, float],
) -> tuple[float, float]:
    ox, oy = origin
    cx_off, cy_off = offset_to_pixel(position, hex_size)
    return ox + cx_off, oy + cy_off


@dataclass(slots=True)
class _PlaytestArmy:
    """Fallback army entity until :mod:`dragonflight.army` is available."""

    position: OffsetCoord
    hp: int
    max_hp: int
    atk: int
    dfn: int
    victory_gold: int = 0
    stat_modifiers: StatModifierBag = field(default_factory=StatModifierBag)


def _try_import_army_sim() -> Any | None:
    try:
        from . import army as army_sim

        return army_sim
    except ImportError:
        return None


def _army_position(army: Any) -> OffsetCoord:
    return army.position


def _army_hp(army: Any) -> int:
    return int(army.hp)


def _army_kind(army: Any) -> ArmyKind:
    kind = getattr(army, "kind", ArmyKind.VILLAGE)
    return kind if isinstance(kind, ArmyKind) else ArmyKind.VILLAGE


def _set_army_hp(army: Any, hp: int) -> None:
    army.hp = hp


def _armies_by_coord(armies: list[Any]) -> dict[OffsetCoord, Any]:
    out: dict[OffsetCoord, Any] = {}
    for army in armies:
        if _army_hp(army) > 0:
            out[_army_position(army)] = army
    return out


def _fallback_army_from_spawn_event(
    event: MockArmySpawnEvent,
    settlements_by_coord: dict[OffsetCoord, Settlement],
) -> _PlaytestArmy:
    """Temporary spawn stats until the army simulation module owns creation."""

    settlement = settlements_by_coord.get(event.position)
    settlement_max_hp = settlement.max_hp if settlement is not None else 500
    max_hp = max(1, settlement_max_hp * 66 // 100)
    return _PlaytestArmy(
        position=event.position,
        hp=max_hp,
        max_hp=max_hp,
        atk=max(1, event.atk * 90 // 100),
        dfn=max(0, event.dfn * 50 // 100),
    )


def _spawn_armies_from_events(
    events: Sequence[Army | MockArmySpawnEvent],
    *,
    settlements_by_coord: dict[OffsetCoord, Settlement],
    active_armies: list[Any],
    tuning: GameTuning | None = None,
) -> int:
    """Append armies for spawn events; returns count added."""

    if not events:
        return 0
    sim = _try_import_army_sim()
    added = 0
    for event in events:
        if isinstance(event, Army):
            active_armies.append(event)
            added += 1
            continue
        settlement = settlements_by_coord.get(event.position)
        if sim is not None and hasattr(sim, "army_from_spawn_event"):
            army = sim.army_from_spawn_event(event, settlement, tuning=tuning)
        else:
            army = _fallback_army_from_spawn_event(event, settlements_by_coord)
        active_armies.append(army)
        added += 1
    return added


def _prune_defeated_armies(armies: list[Any]) -> list[Any]:
    return [a for a in armies if _army_hp(a) > 0]


def _run_end_of_day_army_phase(
    game_map: GameMap,
    armies: list[Any],
    *,
    citadel_coord: OffsetCoord,
    citadel_hp: int,
    dragon: Dragon | None = None,
    movement_ctx: object | None = None,
) -> tuple[list[Any], int, list[str], bool, Any | None]:
    """Delegate army movement/attacks to simulation; no-op when module is absent."""

    sim = _try_import_army_sim()
    if sim is None or not hasattr(sim, "run_army_phase"):
        return armies, citadel_hp, [], False, None

    result = sim.run_army_phase(
        game_map,
        list(armies),
        citadel_coord=citadel_coord,
        citadel_hp=citadel_hp,
        dragon=dragon,
        movement_ctx=movement_ctx,
    )
    next_armies = list(getattr(result, "armies", armies))
    next_hp = int(getattr(result, "citadel_hp", citadel_hp))
    messages = list(getattr(result, "messages", ()) or ())
    game_over = bool(getattr(result, "game_over", next_hp <= 0))
    return next_armies, next_hp, messages, game_over, result


def _validate_dragon_vs_army(
    dragon: Dragon,
    army: Any,
    *,
    citadel_coord: OffsetCoord,
) -> tuple[bool, str]:
    sim = _try_import_army_sim()
    if sim is not None and hasattr(sim, "validate_dragon_vs_army"):
        return sim.validate_dragon_vs_army(dragon, army, citadel_coord=citadel_coord)

    if dragon.position != _army_position(army):
        return False, "dragon must occupy the army hex to attack"
    budget = dragon.validate_damage_round_preserves_return_to_citadel(citadel_coord)
    if not budget.ok:
        return False, budget.reason
    return True, ""


def _resolve_army_combat_round(
    dragon: Dragon,
    army: Any,
    world: GameMap,
    *,
    citadel_coord: OffsetCoord,
) -> DamageRoundExchange | MoveAttempt:
    sim = _try_import_army_sim()
    if sim is not None and hasattr(sim, "resolve_army_combat_round"):
        return sim.resolve_army_combat_round(
            dragon,
            army,
            world,
            citadel_coord=citadel_coord,
        )

    budget = dragon.validate_damage_round_preserves_return_to_citadel(citadel_coord)
    if not budget.ok:
        return budget

    from .dragon_abilities import (
        apply_ice_talons_to_army,
        enemy_defence_for_round,
        on_combat_round_started,
    )

    on_combat_round_started(dragon)
    exchange = dragon.attack_army(
        army_hp=_army_hp(army),
        army_atk=entity_effective_atk(army),
        army_dfn=enemy_defence_for_round(dragon, _army_position(army), entity_effective_dfn(army)),
        world=world,
    )
    if isinstance(exchange, DamageRoundExchange):
        _set_army_hp(army, exchange.target_hp_after)
        apply_ice_talons_to_army(dragon, army)
    return exchange


def _draw_army_markers_on_map(
    surface: pygame.Surface,
    armies: list[Any],
    hex_size: float,
    origin: tuple[float, float],
    *,
    fog: FogOfWarState,
) -> None:
    """Army pixel marker on each revealed hex (below the dragon marker); X if art missing."""

    marker_side = int(max(8, min(hex_size * 1.35, hex_size * 1.55) * 2 * ARMY_MAP_MARKER_SCALE))
    half = max(5, int(hex_size * 0.28))
    line_w = max(2, int(hex_size * 0.1))
    for army in armies:
        if _army_hp(army) <= 0:
            continue
        if not is_revealed(fog, _army_position(army)):
            continue
        cx, cy = _dragon_screen_center(_army_position(army), hex_size, origin)
        icx, icy = int(round(cx)), int(round(cy))
        kind = _army_kind(army)
        marker = army_art.map_marker_surface(kind, marker_side)
        if marker is not None:
            mrect = marker.get_rect(center=(icx, icy))
            surface.blit(marker, mrect)
            continue
        marker_rgb = _HEROES_ARMY_MARKER_RGB if kind is ArmyKind.HEROES else _ARMY_MARKER_RGB
        pygame.draw.line(
            surface,
            marker_rgb,
            (icx - half, icy - half),
            (icx + half, icy + half),
            line_w,
        )
        pygame.draw.line(
            surface,
            marker_rgb,
            (icx - half, icy + half),
            (icx + half, icy - half),
            line_w,
        )


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


def _map_zoom_control_rects(
    map_viewport: pygame.Rect,
) -> tuple[pygame.Rect, pygame.Rect, pygame.Rect, pygame.Rect]:
    """Return ``(zoom_in +, zoom_out −, history, debug)`` at the top-right of the map viewport."""

    w = _MAP_ZOOM_BTN_SIZE
    h = _MAP_ZOOM_BTN_SIZE
    x = map_viewport.right - _MAP_ZOOM_BTN_MARGIN - w
    y_in = map_viewport.y + _MAP_ZOOM_BTN_MARGIN
    y_out = y_in + h + _MAP_ZOOM_BTN_GAP
    y_hist = y_out + h + _MAP_ZOOM_BTN_GAP
    y_debug = y_hist + h + _MAP_ZOOM_BTN_GAP
    return (
        pygame.Rect(x, y_in, w, h),
        pygame.Rect(x, y_out, w, h),
        pygame.Rect(x, y_hist, w, h),
        pygame.Rect(x, y_debug, w, h),
    )


def _draw_map_zoom_controls(
    surface: pygame.Surface,
    font: pygame.font.Font,
    map_viewport: pygame.Rect,
    *,
    theme: DragonUITheme,
    debug_active: bool = False,
) -> tuple[pygame.Rect, pygame.Rect, pygame.Rect, pygame.Rect]:
    """Paint + / − / History / Debug buttons; return rects for hit testing."""

    mx, my = pygame.mouse.get_pos()
    zoom_in_rect, zoom_out_rect, history_rect, debug_rect = _map_zoom_control_rects(map_viewport)
    for rect, label, active in (
        (zoom_in_rect, "+", False),
        (zoom_out_rect, "\u2212", False),
        (history_rect, "\u23f0", False),
        (debug_rect, "D", debug_active),
    ):
        _draw_button(
            surface,
            font,
            rect,
            label,
            hovered=rect.collidepoint(mx, my),
            active=active,
            border_rgb=theme.border_rgb,
        )
    return zoom_in_rect, zoom_out_rect, history_rect, debug_rect


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


def _combat_stat_atk_line(view: CombatantView) -> str:
    if view.atk_debuffed:
        return f"ATK: {view.effective_atk} (base {view.base_atk})"
    return f"ATK: {view.base_atk}"


def _combat_stat_dfn_line(view: CombatantView) -> str:
    if view.dfn_debuffed:
        return f"DFN: {view.effective_dfn} (base {view.base_dfn})"
    return f"DFN: {view.base_dfn}"


def _draw_event_popup(
    surface: pygame.Surface,
    font: pygame.font.Font,
    lines: list[str],
    map_viewport: pygame.Rect,
    *,
    theme: DragonUITheme,
) -> None:
    """Top-right popup showing recent event messages, positioned below zoom controls."""

    if not lines:
        return

    pad_x, pad_y = 16, 12
    line_h = font.get_height() + 4
    max_w = int(map_viewport.w * 0.45)
    text_w = max_w - 2 * pad_x

    wrapped: list[str] = []
    for line in lines:
        wrapped.extend(_wrap_text_to_width(font, line, text_w))
        wrapped.append("")  # blank separator between entries
    if wrapped and wrapped[-1] == "":
        wrapped.pop()

    content_h = len(wrapped) * line_h
    popup_h = content_h + 2 * pad_y
    popup_w = max_w

    btn_size = _MAP_ZOOM_BTN_SIZE
    btn_margin = _MAP_ZOOM_BTN_MARGIN
    btn_gap = _MAP_ZOOM_BTN_GAP
    below_zoom = map_viewport.y + btn_margin + 3 * btn_size + 2 * btn_gap + 8

    popup_x = map_viewport.right - btn_margin - popup_w
    popup_y = below_zoom

    popup_rect = pygame.Rect(popup_x, popup_y, popup_w, popup_h)

    bg = pygame.Surface((popup_w, popup_h), pygame.SRCALPHA)
    bg.fill((24, 26, 34, 220))
    surface.blit(bg, (popup_x, popup_y))
    pygame.draw.rect(surface, theme.border_rgb, popup_rect, width=1, border_radius=6)

    y = popup_y + pad_y
    for text in wrapped:
        if text:
            txt_surf = font.render(text, True, _UI_TEXT_RGB)
            surface.blit(txt_surf, (popup_x + pad_x, y))
        y += line_h


def _draw_event_history_overlay(
    surface: pygame.Surface,
    client_w: int,
    client_h: int,
    font_mid: pygame.font.Font,
    font_small: pygame.font.Font,
    event_log: list[tuple[int, str]],
    scroll_y: int,
    *,
    theme: DragonUITheme,
) -> tuple[pygame.Rect, int]:
    """Full-screen modal showing all past events grouped by day. Returns (close_btn_rect, content_height)."""

    dim = pygame.Surface((client_w, client_h), pygame.SRCALPHA)
    dim.fill((12, 14, 20, 200))
    surface.blit(dim, (0, 0))

    panel_w = min(640, max(360, client_w - 120))
    panel_h = min(client_h - 100, max(300, client_h * 3 // 4))
    panel = pygame.Rect(
        (client_w - panel_w) // 2,
        (client_h - panel_h) // 2,
        panel_w,
        panel_h,
    )
    pygame.draw.rect(surface, (38, 41, 52), panel, border_radius=10)
    pygame.draw.rect(surface, theme.border_rgb, panel, width=1, border_radius=10)

    title_surf = font_mid.render("Event History", True, _UI_TEXT_RGB)
    surface.blit(title_surf, (panel.centerx - title_surf.get_width() // 2, panel.y + 16))

    btn_w, btn_h = 100, 34
    close_btn = pygame.Rect(
        panel.centerx - btn_w // 2,
        panel.bottom - btn_h - 14,
        btn_w,
        btn_h,
    )
    mx, my = pygame.mouse.get_pos()
    _draw_button(
        surface,
        font_mid,
        close_btn,
        "Close",
        hovered=close_btn.collidepoint(mx, my),
        border_rgb=theme.border_rgb,
    )

    content_top = panel.y + 52
    content_bottom = close_btn.y - 10
    content_area_h = max(1, content_bottom - content_top)

    clip_prev = surface.get_clip()
    surface.set_clip(pygame.Rect(panel.x, content_top, panel_w, content_area_h))

    line_h = font_small.get_height() + 4
    day_header_h = font_mid.get_height() + 8
    text_w = panel_w - 40

    by_day: dict[int, list[str]] = {}
    for day, msg in event_log:
        by_day.setdefault(day, []).append(msg)

    total_content_h = 0
    draw_items: list[tuple[str, bool, int]] = []  # (text, is_header, y_offset)
    y_accum = 0
    for day in sorted(by_day.keys(), reverse=True):
        draw_items.append((f"Day {day}", True, y_accum))
        y_accum += day_header_h
        for msg in reversed(by_day[day]):
            for wline in _wrap_text_to_width(font_small, msg, text_w):
                draw_items.append((wline, False, y_accum))
                y_accum += line_h
        y_accum += 6  # gap between day groups
    total_content_h = y_accum

    for text, is_header, y_off in draw_items:
        screen_y = content_top + y_off - scroll_y
        if screen_y + line_h < content_top or screen_y > content_bottom:
            continue
        if is_header:
            hdr_surf = font_mid.render(text, True, theme.accent_rgb)
            surface.blit(hdr_surf, (panel.x + 20, screen_y))
        else:
            txt_surf = font_small.render(text, True, _UI_TEXT_RGB)
            surface.blit(txt_surf, (panel.x + 28, screen_y))

    surface.set_clip(clip_prev)

    return close_btn, total_content_h


def _clamp_debug_selected_day(day: int, debug_log: DayDebugLog) -> int:
    days = debug_log.days()
    if not days:
        return max(1, day)
    if day in days:
        return day
    if day < days[0]:
        return days[0]
    if day > days[-1]:
        return days[-1]
    prev = days[0]
    for logged_day in days:
        if logged_day > day:
            return prev
        prev = logged_day
    return days[-1]


def _draw_debug_overlay(
    surface: pygame.Surface,
    client_w: int,
    client_h: int,
    font_mid: pygame.font.Font,
    font_small: pygame.font.Font,
    debug_log: DayDebugLog,
    selected_day: int,
    scroll_y: int,
    *,
    theme: DragonUITheme,
) -> DebugOverlayClick:
    """Full-screen modal showing per-day simulation debug lines."""

    dim = pygame.Surface((client_w, client_h), pygame.SRCALPHA)
    dim.fill((12, 14, 20, 200))
    surface.blit(dim, (0, 0))

    panel_w = min(640, max(360, client_w - 120))
    panel_h = min(client_h - 100, max(300, client_h * 3 // 4))
    panel = pygame.Rect(
        (client_w - panel_w) // 2,
        (client_h - panel_h) // 2,
        panel_w,
        panel_h,
    )
    pygame.draw.rect(surface, (38, 41, 52), panel, border_radius=10)
    pygame.draw.rect(surface, theme.border_rgb, panel, width=1, border_radius=10)

    mx, my = pygame.mouse.get_pos()
    day_btn_w, day_btn_h = 34, 30
    title_text = f"Debug — Day {selected_day}"
    title_surf = font_mid.render(title_text, True, _UI_TEXT_RGB)
    title_x = panel.centerx - title_surf.get_width() // 2
    title_y = panel.y + 16
    day_minus = pygame.Rect(
        title_x - day_btn_w - 10,
        title_y + (title_surf.get_height() - day_btn_h) // 2,
        day_btn_w,
        day_btn_h,
    )
    day_plus = pygame.Rect(
        title_x + title_surf.get_width() + 10,
        title_y + (title_surf.get_height() - day_btn_h) // 2,
        day_btn_w,
        day_btn_h,
    )
    _draw_button(
        surface,
        font_mid,
        day_minus,
        "\u2212",
        hovered=day_minus.collidepoint(mx, my),
        border_rgb=theme.border_rgb,
    )
    surface.blit(title_surf, (title_x, title_y))
    _draw_button(
        surface,
        font_mid,
        day_plus,
        "+",
        hovered=day_plus.collidepoint(mx, my),
        border_rgb=theme.border_rgb,
    )

    btn_w, btn_h = 100, 34
    close_btn = pygame.Rect(
        panel.centerx - btn_w // 2,
        panel.bottom - btn_h - 14,
        btn_w,
        btn_h,
    )
    _draw_button(
        surface,
        font_mid,
        close_btn,
        "Close",
        hovered=close_btn.collidepoint(mx, my),
        border_rgb=theme.border_rgb,
    )

    content_top = panel.y + 52
    content_bottom = close_btn.y - 10
    content_area_h = max(1, content_bottom - content_top)

    clip_prev = surface.get_clip()
    surface.set_clip(pygame.Rect(panel.x, content_top, panel_w, content_area_h))

    line_h = font_small.get_height() + 4
    text_w = panel_w - 40
    raw_lines = debug_log.format_for_display(selected_day)
    has_real_lines = bool(raw_lines)
    display_lines = raw_lines if has_real_lines else ["(No debug lines for this day.)"]

    draw_items: list[tuple[str, int]] = []
    y_accum = 0
    for raw in display_lines:
        wrapped = _wrap_text_to_width(font_small, raw, text_w)
        if not wrapped:
            wrapped = [""]
        for wline in wrapped:
            draw_items.append((wline, y_accum))
            y_accum += line_h
    total_content_h = y_accum

    for text, y_off in draw_items:
        screen_y = content_top + y_off - scroll_y
        if screen_y + line_h < content_top or screen_y > content_bottom:
            continue
        line_rgb = _UI_TEXT_RGB if has_real_lines else _UI_MUTED_TEXT_RGB
        txt_surf = font_small.render(text, True, line_rgb)
        surface.blit(txt_surf, (panel.x + 20, screen_y))

    surface.set_clip(clip_prev)

    return DebugOverlayClick(
        close=close_btn,
        day_minus=day_minus,
        day_plus=day_plus,
        content_height=total_content_h,
        content_viewport_h=content_area_h,
    )


def _draw_raid_combat_overlay(
    surface: pygame.Surface,
    font: pygame.font.Font,
    font_small: pygame.font.Font,
    *,
    theme: DragonUITheme,
    map_viewport: pygame.Rect,
    game_map: GameMap,
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
    pygame.draw.rect(surface, theme.border_rgb, overlay, width=1)

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
    settle_view = entity_combatant_view(settlement)
    s_lines = (
        f"HP: {settlement.hp} / {settlement.max_hp}",
        _combat_stat_atk_line(settle_view),
        _combat_stat_dfn_line(settle_view),
    )
    rd_prev = preview_settlement_round(dragon, settlement, game_map)
    yd = y0
    for i, line in enumerate(d_lines):
        if i == 0:
            _draw_muted_hp_line_with_damage_preview(
                surface,
                font_small,
                x=col_dragon_x,
                y=yd,
                hp_line=line,
                damage=rd_prev.damage_to_dragon,
            )
        else:
            _draw_text(surface, font_small, line, (col_dragon_x, yd), _UI_MUTED_TEXT_RGB)
        yd += 20
    ys = y0
    for i, line in enumerate(s_lines):
        if i == 0:
            _draw_muted_hp_line_with_damage_preview(
                surface,
                font_small,
                x=col_settle_x,
                y=ys,
                hp_line=line,
                damage=rd_prev.damage_to_enemy,
            )
        else:
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
    _draw_button(
        surface,
        font,
        attack_rect,
        "Attack",
        hovered=attack_rect.collidepoint(mx, my),
        border_rgb=theme.border_rgb,
    )
    _draw_button(
        surface,
        font,
        retreat_rect,
        "Retreat",
        hovered=retreat_rect.collidepoint(mx, my),
        border_rgb=theme.border_rgb,
    )
    return attack_rect, retreat_rect


def _draw_army_combat_overlay(
    surface: pygame.Surface,
    font: pygame.font.Font,
    font_small: pygame.font.Font,
    *,
    theme: DragonUITheme,
    map_viewport: pygame.Rect,
    game_map: GameMap,
    dragon: Dragon,
    army: Any,
    banner: str,
) -> tuple[pygame.Rect, pygame.Rect]:
    """Bottom-half overlay for dragon-vs-army combat; returns (attack_rect, retreat_rect)."""

    oh = max(80, int(float(map_viewport.h) * RAID_COMBAT_OVERLAY_HEIGHT_FRACTION))
    overlay = pygame.Rect(map_viewport.x, map_viewport.bottom - oh, map_viewport.w, oh)

    shade = pygame.Surface((overlay.w, overlay.h), pygame.SRCALPHA)
    shade.fill((24, 26, 34, 236))
    surface.blit(shade, overlay.topleft)
    pygame.draw.rect(surface, theme.border_rgb, overlay, width=1)

    inner_pad = 14
    cx = overlay.x + inner_pad
    cy = overlay.y + inner_pad
    col_w = max(120, (overlay.w - 3 * inner_pad) // 2)

    army_kind = _army_kind(army)
    army_label = army_display_name_for_kind(army_kind)
    combat_title = f"{army_label} combat"
    _draw_text(surface, font, combat_title, (cx, cy), _UI_TEXT_RGB)
    cy += 26

    col_dragon_x = cx
    col_army_x = cx + col_w + inner_pad
    portrait_y = cy
    ph_base = min(72, max(40, overlay.h // 5))
    portrait_max_h = max(1, int(round(ph_base * COMBAT_PORTRAIT_SCALE)))
    portrait_max_w = max(1, int(round(col_w * COMBAT_PORTRAIT_SCALE)))

    portrait_row_h = 0
    d_portrait = load_detailed_sprite(dragon.kind)
    if d_portrait is not None:
        ps = scaled_to_fit(d_portrait, portrait_max_w, portrait_max_h)
        surface.blit(ps, (col_dragon_x, portrait_y))
        portrait_row_h = max(portrait_row_h, ps.get_height())
    a_portrait = army_art.load_detailed_sprite(army_kind)
    if a_portrait is not None:
        aps = scaled_to_fit(a_portrait, portrait_max_w, portrait_max_h)
        surface.blit(aps, (col_army_x, portrait_y))
        portrait_row_h = max(portrait_row_h, aps.get_height())

    text_y = portrait_y + (portrait_row_h + 6 if portrait_row_h else 0)
    _draw_text(surface, font_small, "Dragon", (col_dragon_x, text_y), _UI_TEXT_RGB)
    _draw_text(surface, font_small, army_label, (col_army_x, text_y), _UI_TEXT_RGB)
    stat_y = text_y + 22
    army_max_hp = int(army.max_hp)
    army_view = entity_combatant_view(army)
    d_lines = (
        f"HP: {dragon.hp} / {dragon.max_hp}",
        f"ATK: {dragon.atk}",
        f"DFN: {dragon.dfn}",
    )
    a_lines = (
        f"HP: {_army_hp(army)} / {army_max_hp}",
        _combat_stat_atk_line(army_view),
        _combat_stat_dfn_line(army_view),
    )
    army_prev = preview_army_round(dragon, army, game_map)
    yd = stat_y
    for i, line in enumerate(d_lines):
        if i == 0:
            _draw_muted_hp_line_with_damage_preview(
                surface,
                font_small,
                x=col_dragon_x,
                y=yd,
                hp_line=line,
                damage=army_prev.damage_to_dragon,
            )
        else:
            _draw_text(surface, font_small, line, (col_dragon_x, yd), _UI_MUTED_TEXT_RGB)
        yd += 20
    ya = stat_y
    for i, line in enumerate(a_lines):
        if i == 0:
            _draw_muted_hp_line_with_damage_preview(
                surface,
                font_small,
                x=col_army_x,
                y=ya,
                hp_line=line,
                damage=army_prev.damage_to_enemy,
            )
        else:
            _draw_text(surface, font_small, line, (col_army_x, ya), _UI_MUTED_TEXT_RGB)
        ya += 20

    mid_y = max(yd, ya) + 10
    if banner:
        _draw_text(surface, font_small, banner, (cx, mid_y), (200, 220, 160))
        mid_y += 24

    btn_y = overlay.bottom - inner_pad - 40
    btn_w = max(100, (overlay.w - 3 * inner_pad) // 2)
    attack_rect = pygame.Rect(cx, btn_y, btn_w, 36)
    retreat_rect = pygame.Rect(cx + btn_w + inner_pad, btn_y, btn_w, 36)
    mx, my = pygame.mouse.get_pos()
    _draw_button(
        surface,
        font,
        attack_rect,
        "Attack",
        hovered=attack_rect.collidepoint(mx, my),
        border_rgb=theme.border_rgb,
    )
    _draw_button(
        surface,
        font,
        retreat_rect,
        "Retreat",
        hovered=retreat_rect.collidepoint(mx, my),
        border_rgb=theme.border_rgb,
    )
    return attack_rect, retreat_rect


def _draw_game_over_overlay(
    surface: pygame.Surface,
    client_w: int,
    client_h: int,
    font_big: pygame.font.Font,
    font_mid: pygame.font.Font,
    *,
    turns_survived: int,
) -> pygame.Rect:
    """Full-window modal for loss; returns the New Game button rect."""

    dim = pygame.Surface((client_w, client_h), pygame.SRCALPHA)
    dim.fill((12, 14, 20, 240))
    surface.blit(dim, (0, 0))

    panel_w = min(520, max(280, client_w - 80))
    panel_h = min(220, max(160, client_h // 4))
    panel = pygame.Rect(
        (client_w - panel_w) // 2,
        (client_h - panel_h) // 2,
        panel_w,
        panel_h,
    )
    pygame.draw.rect(surface, _UI_PANEL_RGB, panel, border_radius=10)
    pygame.draw.rect(surface, _UI_BORDER_RGB, panel, width=1, border_radius=10)

    title = f"Game over — Survived {turns_survived} turns"
    title_surf = font_big.render(title, True, _UI_TEXT_RGB)
    surface.blit(
        title_surf,
        (panel.centerx - title_surf.get_width() // 2, panel.y + 28),
    )

    btn_w, btn_h = 180, 40
    new_game_btn = pygame.Rect(
        panel.centerx - btn_w // 2,
        panel.bottom - btn_h - 28,
        btn_w,
        btn_h,
    )
    mx, my = pygame.mouse.get_pos()
    _draw_button(
        surface,
        font_mid,
        new_game_btn,
        "New Game",
        hovered=new_game_btn.collidepoint(mx, my),
    )
    return new_game_btn


def _draw_hour_bar(
    surface: pygame.Surface,
    hours_remaining: float,
    bar_width: int,
    *,
    remain_rgb: tuple[int, int, int],
) -> None:
    """Draw 24 equal hour segments; left-to-right shows spent (dark) then left."""
    margin = 8
    inner_w = max(1, bar_width - 2 * margin)
    segment_widths, gap = hour_bar_segment_layout(inner_w, _SEGMENT_GAP)

    hr = max(0.0, min(HOURS_PER_DRAGON_DAY, hours_remaining))
    spent = HOURS_PER_DRAGON_DAY - hr

    spent_rgb = (45, 48, 58)
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


def run_play_session(
    game_map: GameMap | None = None,
    *,
    window_title: str = "Dragonflight",
) -> None:
    """Open a resizable Pygame window.

    When ``game_map`` is ``None`` (default for ``python -m dragonflight``), the
    flow is: Main menu → Start Game → pick a map under ``assets/`` → pick
    a dragon type → then the in-map play session.

    If ``game_map`` is provided, menus are skipped and play starts immediately
    with the default first playable dragon kind (for programmatic / test use).
    """
    citadel_coord: OffsetCoord | None = None
    dragon: Dragon | None = None
    session_dragon_kind: DragonKind = default_playable_kind()
    skip_menus = game_map is not None
    if skip_menus:
        assert game_map is not None
        game_map = clone_game_map(game_map)
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
        map_camera = MapViewportCamera()

        def apply_layout(client_w: int, client_h: int) -> None:
            """Recompute hex size and origin for a client-area size."""

            nonlocal win_w, win_h, hex_size, origin, map_camera
            win_w, win_h = client_w, client_h
            if game_map is None:
                return
            map_h = max(1, client_h - TIME_BAR_HEIGHT - SETTINGS_BAR_HEIGHT)
            map_canvas_w = max(1, client_w - dragon_panel_w - inspector_panel_w)
            resolved = resolve_map_view(game_map, map_canvas_w, map_h, map_camera)
            hex_size = resolved.hex_size
            ox, oy = resolved.origin_local
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
        heroes_party_city_pool = HeroesPartyCityPool()
        heroes_party_rng = random.Random()
        world_event_rng = random.Random()
        world_event_day_state = WorldEventDayState()
        # Screens: main_menu, new_game_maps, new_game_dragon, game, settings,
        # game_options, map_creator_setup, map_creator_editor, map_editor
        screen: str = "game" if skip_menus else "main_menu"
        new_game_map_scroll: int = 0
        new_game_status: str = ""
        pending_map_path: Path | None = None
        dragon_pick_context: DragonPickContext | None = None
        focused_field: str | None = None  # dims | name
        settings_status: str = ""
        game_tuning: GameTuning = default_game_tuning()
        game_options_difficulty: DifficultyLevel = "normal"
        game_options_scroll: int = 0
        game_options_drag_attr: str | None = None
        game_options_track_rects: dict[str, pygame.Rect] = {}
        game_options_preset_rects: dict[DifficultyLevel, pygame.Rect] = {}
        game_over_new_game_rect: pygame.Rect | None = None

        draft = _MapCreatorDraft(
            dims=_TextField("Map size (e.g. 50x50)", "30x30", pygame.Rect(60, 170, 260, 36)),
            name=_TextField("Map name", "New Map", pygame.Rect(60, 250, 260, 36)),
        )
        editor: _MapEditorState | None = None
        # Live Village/City/Fort instances — settlement phase, future raids/combat.
        settlements_by_coord: dict[OffsetCoord, Settlement] = {}
        inspector_focus_coord: OffsetCoord | None = None
        inspector_raid_button_rect: pygame.Rect | None = None
        event_log: list[tuple[int, str]] = []
        pending_event_lines: list[str] = []
        event_popup_active: bool = False
        event_history_open: bool = False
        event_history_scroll: int = 0
        event_history_close_rect: pygame.Rect | None = None
        event_history_content_h: int = 0
        day_debug_log = DayDebugLog()
        debug_overlay_active: bool = False
        debug_selected_day: int = 1
        debug_scroll_y: int = 0
        debug_overlay_click: DebugOverlayClick | None = None
        inspector_army_attack_button_rect: pygame.Rect | None = None
        dragon_ability_button_rects: dict[str, pygame.Rect] = {}
        dragon_panel_scroll: int = 0
        inspector_panel_scroll: int = 0
        dragon_panel_content_h: int = 0
        inspector_panel_content_h: int = 0
        fog_of_war = FogOfWarState()
        targeting_ability_name: str | None = None
        raid_combat_settlement: Settlement | None = None
        raid_overlay_banner: str = ""
        raid_overlay_auto_close_deadline_ms: int | None = None
        raid_overlay_attack_rect: pygame.Rect | None = None
        raid_overlay_retreat_rect: pygame.Rect | None = None
        active_armies: list[Any] = []
        citadel_hp: int = CITADEL_STARTING_HP
        citadel_damage_announced: bool = False
        game_over: bool = False
        army_combat_target: Any | None = None
        army_overlay_banner: str = ""
        army_overlay_auto_close_deadline_ms: int | None = None
        army_overlay_attack_rect: pygame.Rect | None = None
        army_overlay_retreat_rect: pygame.Rect | None = None
        splitter_drag: Literal["left", "right"] | None = None
        editor_paint_drag_active: bool = False
        last_editor_paint_coord: OffsetCoord | None = None
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
                new_map = clone_game_map(load_map(selected_resolved))
            except MapLoadError as exc:
                return False, f"Failed to load map: {exc}"
            except OSError as exc:
                return False, f"Failed to read file: {exc}"

            _reset_session_for_map(new_map)
            rel = selected_resolved.name
            return True, f"Loaded assets/{rel}"

        def _reset_session_for_map(new_map: GameMap) -> None:
            nonlocal game_map, citadel_coord, dragon, day_index, screen, settings_status
            nonlocal fog_of_war
            nonlocal inspector_focus_coord
            nonlocal dragon_ability_button_rects, targeting_ability_name
            nonlocal raid_combat_settlement, raid_overlay_banner
            nonlocal raid_overlay_auto_close_deadline_ms
            nonlocal active_armies, citadel_hp, game_over
            nonlocal army_combat_target, army_overlay_banner, army_overlay_auto_close_deadline_ms
            nonlocal inspector_army_attack_button_rect
            nonlocal dragon_upgrade_overlay_active, dragon_upgrade_draft
            nonlocal dragon_upgrade_overlay_baseline, dragon_upgrade_overlay_click
            nonlocal dragon_panel_scroll, inspector_panel_scroll, map_camera
            nonlocal heroes_party_city_pool, heroes_party_rng
            nonlocal world_event_rng, world_event_day_state
            nonlocal event_popup_active, event_history_open, event_history_scroll
            nonlocal day_debug_log, debug_overlay_active, debug_selected_day, debug_scroll_y
            game_map = new_map
            citadel_coord = _find_citadel_coord(game_map)
            dragon = new_playable_dragon(session_dragon_kind, citadel_coord)
            day_index = 1
            heroes_party_city_pool = HeroesPartyCityPool()
            heroes_party_rng = random.Random()
            world_event_rng = random.Random()
            world_event_day_state.clear()
            settings_status = ""
            inspector_focus_coord = None
            dragon_ability_button_rects = {}
            event_log.clear()
            pending_event_lines.clear()
            event_popup_active = False
            event_history_open = False
            event_history_scroll = 0
            day_debug_log.clear()
            debug_overlay_active = False
            debug_selected_day = 1
            debug_scroll_y = 0
            dragon_panel_scroll = 0
            inspector_panel_scroll = 0
            map_camera = MapViewportCamera()
            targeting_ability_name = None
            raid_combat_settlement = None
            raid_overlay_banner = ""
            raid_overlay_auto_close_deadline_ms = None
            inspector_army_attack_button_rect = None
            active_armies = []
            citadel_hp = CITADEL_STARTING_HP
            game_over = False
            army_combat_target = None
            army_overlay_banner = ""
            army_overlay_auto_close_deadline_ms = None
            dragon_upgrade_overlay_active = False
            dragon_upgrade_draft = []
            dragon_upgrade_overlay_baseline = None
            dragon_upgrade_overlay_click = None
            _sync_settlements_from_map()
            init_fog_from_dragon(fog_of_war, dragon, new_map)
            _ensure_window_meets_gameplay_floors()
            screen = "game"

        def _enter_game_over() -> None:
            """Lock the session until the player starts a new run on the same map."""

            nonlocal game_over
            nonlocal dragon_upgrade_overlay_active, dragon_upgrade_draft
            nonlocal dragon_upgrade_overlay_baseline, dragon_upgrade_overlay_click
            nonlocal targeting_ability_name
            nonlocal raid_combat_settlement, raid_overlay_banner
            nonlocal raid_overlay_auto_close_deadline_ms
            nonlocal army_combat_target, army_overlay_banner
            nonlocal army_overlay_auto_close_deadline_ms
            nonlocal event_popup_active
            if game_over:
                return
            game_over = True
            event_popup_active = False
            pending_event_lines.clear()
            dragon_upgrade_overlay_active = False
            dragon_upgrade_draft = []
            dragon_upgrade_overlay_baseline = None
            dragon_upgrade_overlay_click = None
            targeting_ability_name = None
            raid_combat_settlement = None
            raid_overlay_banner = ""
            raid_overlay_auto_close_deadline_ms = None
            army_combat_target = None
            army_overlay_banner = ""
            army_overlay_auto_close_deadline_ms = None

        def _begin_play_session_from_pending_map() -> tuple[bool, str]:
            """Load ``pending_map_path`` with ``session_dragon_kind`` and enter ``game``."""
            nonlocal game_map, citadel_coord, dragon, day_index, screen
            nonlocal fog_of_war
            nonlocal settings_status, new_game_status, dragon_pick_context
            nonlocal inspector_focus_coord
            nonlocal dragon_ability_button_rects, targeting_ability_name
            nonlocal raid_combat_settlement, raid_overlay_banner
            nonlocal raid_overlay_auto_close_deadline_ms
            nonlocal active_armies, citadel_hp, game_over
            nonlocal army_combat_target, army_overlay_banner, army_overlay_auto_close_deadline_ms
            nonlocal inspector_army_attack_button_rect
            nonlocal dragon_upgrade_overlay_active, dragon_upgrade_draft
            nonlocal dragon_upgrade_overlay_baseline, dragon_upgrade_overlay_click
            nonlocal dragon_panel_scroll, inspector_panel_scroll, map_camera
            nonlocal game_tuning, game_options_difficulty
            nonlocal heroes_party_city_pool, heroes_party_rng
            nonlocal event_popup_active, event_history_open, event_history_scroll
            nonlocal day_debug_log, debug_overlay_active, debug_selected_day, debug_scroll_y
            if pending_map_path is None:
                return False, "No map selected."
            try:
                assets_resolved = _assets_dir().resolve()
                selected_resolved = pending_map_path.resolve()
                selected_resolved.relative_to(assets_resolved)
            except Exception:
                return False, "Map file must be inside assets/."

            try:
                new_map = clone_game_map(load_map(selected_resolved))
            except MapLoadError as exc:
                return False, f"Failed to load map: {exc}"
            except OSError as exc:
                return False, f"Failed to read file: {exc}"

            game_map = new_map
            citadel_coord = _find_citadel_coord(game_map)
            dragon = new_playable_dragon(session_dragon_kind, citadel_coord)
            day_index = 1
            heroes_party_city_pool = HeroesPartyCityPool()
            heroes_party_rng = random.Random()
            settings_status = ""
            new_game_status = ""
            inspector_focus_coord = None
            dragon_ability_button_rects = {}
            dragon_panel_scroll = 0
            inspector_panel_scroll = 0
            map_camera = MapViewportCamera()
            event_log.clear()
            pending_event_lines.clear()
            event_popup_active = False
            event_history_open = False
            event_history_scroll = 0
            day_debug_log.clear()
            debug_overlay_active = False
            debug_selected_day = 1
            debug_scroll_y = 0
            targeting_ability_name = None
            raid_combat_settlement = None
            raid_overlay_banner = ""
            raid_overlay_auto_close_deadline_ms = None
            inspector_army_attack_button_rect = None
            active_armies = []
            citadel_hp = CITADEL_STARTING_HP
            game_over = False
            army_combat_target = None
            army_overlay_banner = ""
            army_overlay_auto_close_deadline_ms = None
            dragon_upgrade_overlay_active = False
            dragon_upgrade_draft = []
            dragon_upgrade_overlay_baseline = None
            dragon_upgrade_overlay_click = None
            _sync_settlements_from_map()
            init_fog_from_dragon(fog_of_war, dragon, new_map)
            _ensure_window_meets_gameplay_floors()
            screen = "game"
            pick_ctx = dragon_pick_context
            if pick_ctx == "new_game":
                game_tuning = default_game_tuning()
                game_options_difficulty = "normal"
            dragon_pick_context = None
            return True, ""

        if game_map is not None:
            _sync_settlements_from_map()
            if skip_menus and dragon is not None:
                init_fog_from_dragon(fog_of_war, dragon, game_map)

        def redraw() -> None:
            nonlocal inspector_raid_button_rect, inspector_army_attack_button_rect
            nonlocal dragon_ability_button_rects
            nonlocal dragon_panel_scroll, inspector_panel_scroll
            nonlocal dragon_panel_content_h, inspector_panel_content_h
            nonlocal raid_overlay_attack_rect, raid_overlay_retreat_rect
            nonlocal army_overlay_attack_rect, army_overlay_retreat_rect
            nonlocal dragon_upgrade_overlay_click
            nonlocal game_options_track_rects
            nonlocal game_options_preset_rects
            nonlocal game_options_scroll
            nonlocal game_over_new_game_rect
            nonlocal event_history_close_rect, event_history_content_h
            nonlocal debug_overlay_click
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
                desc_text = selection_description_for_kind(session_dragon_kind)
                desc_line_gap = font.get_height() + 4
                desc_top_gap = 14
                desc_reserved_h = 88

                def _draw_dragon_selection_description(
                    text_x: int, text_y: int, max_w: int
                ) -> None:
                    if not desc_text:
                        return
                    y = text_y
                    for line in _wrap_text_to_width(font, desc_text, max_w):
                        if y > win_h - 90:
                            break
                        _draw_text(surf, font, line, (text_x, y), _UI_MUTED_TEXT_RGB)
                        y += desc_line_gap

                if preview_img is not None:
                    slot_x = list_right + 28
                    slot_w = win_w - slot_x - 28
                    if slot_w >= 120:
                        column_h = win_h - y0 - 50
                        portrait_max_h = max(80, column_h - desc_reserved_h - desc_top_gap)
                        portrait = scaled_to_fit(preview_img, slot_w, portrait_max_h)
                        surf.blit(portrait, (slot_x, y0))
                        _draw_dragon_selection_description(
                            slot_x,
                            y0 + portrait.get_height() + desc_top_gap,
                            slot_w,
                        )
                    else:
                        below_y = btn_play.bottom + 20
                        column_h = win_h - below_y - 90
                        portrait_max_h = max(72, column_h - desc_reserved_h - desc_top_gap)
                        if portrait_max_h >= 72:
                            portrait = scaled_to_fit(preview_img, pick_list_w, portrait_max_h)
                            surf.blit(portrait, (60, below_y))
                            _draw_dragon_selection_description(
                                60,
                                below_y + portrait.get_height() + desc_top_gap,
                                pick_list_w,
                            )

                if new_game_status:
                    _draw_text(surf, font, new_game_status, (60, win_h - 110), (240, 120, 120))

            elif screen == "game" and game_map is not None and dragon is not None:
                assert citadel_coord is not None
                ui_theme = dragon_ui_theme_for_kind(dragon.kind)
                caption_bits = [
                    f"Day {day_index}",
                    f"Gold {dragon.gold}",
                    f"Citadel HP {citadel_hp}/{CITADEL_STARTING_HP}",
                    display_name_for_kind(dragon.kind),
                    "Right-click tiles to inspect",
                    "Return to the Citadel to upgrade and heal",
                ]
                if game_over:
                    caption_bits.insert(3, "GAME OVER")
                caption = font.render("  |  ".join(caption_bits), True, (210, 210, 220))
                surf.blit(caption, (8, 6))
                _draw_hour_bar(
                    surf,
                    dragon.hours_remaining,
                    win_w,
                    remain_rgb=ui_theme.hour_remain_rgb,
                )

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
                tile_color = _make_tile_color_fn(
                    dragon,
                    citadel_coord,
                    game_map,
                    fog_of_war,
                    dark_eclipse=world_event_day_state.dark_eclipse,
                )
                render_map(
                    surf,
                    game_map,
                    hex_size,
                    origin,
                    tile_color=tile_color,
                    clear_background=False,
                )
                _draw_army_markers_on_map(surf, active_armies, hex_size, origin, fog=fog_of_war)
                if (
                    inspector_focus_coord is not None
                    and game_map.get(inspector_focus_coord) is not None
                    and is_revealed(fog_of_war, inspector_focus_coord)
                ):
                    draw_hex_outline(
                        surf,
                        coord=inspector_focus_coord,
                        hex_size=hex_size,
                        origin=origin,
                        rgb=ui_theme.accent_rgb,
                        width=2,
                    )

                if targeting_ability_name is not None:
                    mx_target, my_target = pygame.mouse.get_pos()
                    if map_viewport.collidepoint(mx_target, my_target):
                        hovered_coord = _pick_tile_at_pixel(
                            float(mx_target),
                            float(my_target),
                            game_map,
                            hex_size,
                            origin,
                        )
                        if hovered_coord is not None:
                            draw_hex_outline(
                                surf,
                                coord=hovered_coord,
                                hex_size=hex_size,
                                origin=origin,
                                rgb=ui_theme.accent_rgb,
                                width=2,
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
                panel_viewport_h = max(1, dragon_panel_rect.h - 24)
                dragon_ability_button_rects, dragon_panel_content_h = draw_dragon_panel(
                    surf,
                    font,
                    font_small,
                    panel_rect=dragon_panel_rect,
                    theme=ui_theme,
                    dragon=dragon,
                    world=game_map,
                    scroll_y=dragon_panel_scroll,
                )
                dragon_panel_scroll = _clamp_panel_scroll(
                    dragon_panel_scroll, dragon_panel_content_h, panel_viewport_h
                )
                _draw_panel_scrollbar(
                    surf,
                    dragon_panel_rect,
                    scroll_y=dragon_panel_scroll,
                    content_height=dragon_panel_content_h,
                    border_rgb=ui_theme.border_rgb,
                )

                panel_rect = pygame.Rect(
                    win_w - inspector_panel_w,
                    TIME_BAR_HEIGHT,
                    inspector_panel_w,
                    map_area_h,
                )
                armies_on_map = _armies_by_coord(active_armies)
                (
                    inspector_raid_button_rect,
                    inspector_army_attack_button_rect,
                    inspector_panel_content_h,
                ) = draw_tile_inspector_panel(
                    surf,
                    font,
                    font_small,
                    panel_rect=panel_rect,
                    theme=ui_theme,
                    game_map=game_map,
                    settlements_by_coord=settlements_by_coord,
                    armies_by_coord=armies_on_map,
                    inspector_focus_coord=inspector_focus_coord,
                    dragon=dragon,
                    raid_combat_active=raid_combat_settlement is not None,
                    army_combat_active=army_combat_target is not None,
                    game_over=game_over,
                    scroll_y=inspector_panel_scroll,
                    dragon_vs_army_allowed=lambda d, a: _validate_dragon_vs_army(
                        d, a, citadel_coord=citadel_coord
                    ),
                    fog_of_war=fog_of_war,
                )
                inspector_panel_scroll = _clamp_panel_scroll(
                    inspector_panel_scroll, inspector_panel_content_h, panel_viewport_h
                )
                _draw_panel_scrollbar(
                    surf,
                    panel_rect,
                    scroll_y=inspector_panel_scroll,
                    content_height=inspector_panel_content_h,
                    border_rgb=ui_theme.border_rgb,
                )

                if raid_combat_settlement is not None:
                    raid_overlay_attack_rect, raid_overlay_retreat_rect = _draw_raid_combat_overlay(
                        surf,
                        font,
                        font_small,
                        theme=ui_theme,
                        map_viewport=map_viewport,
                        game_map=game_map,
                        dragon=dragon,
                        settlement=raid_combat_settlement,
                        banner=raid_overlay_banner,
                    )
                else:
                    raid_overlay_attack_rect = None
                    raid_overlay_retreat_rect = None

                if army_combat_target is not None:
                    army_overlay_attack_rect, army_overlay_retreat_rect = _draw_army_combat_overlay(
                        surf,
                        font,
                        font_small,
                        theme=ui_theme,
                        map_viewport=map_viewport,
                        game_map=game_map,
                        dragon=dragon,
                        army=army_combat_target,
                        banner=army_overlay_banner,
                    )
                else:
                    army_overlay_attack_rect = None
                    army_overlay_retreat_rect = None

                _draw_map_zoom_controls(
                    surf,
                    font_small,
                    map_viewport,
                    theme=ui_theme,
                    debug_active=debug_overlay_active,
                )

                if event_popup_active and pending_event_lines:
                    _draw_event_popup(
                        surf,
                        font,
                        pending_event_lines,
                        map_viewport,
                        theme=ui_theme,
                    )

                if targeting_ability_name is not None:
                    mx_t, my_t = pygame.mouse.get_pos()
                    pygame.draw.circle(surf, ui_theme.accent_rgb, (mx_t, my_t), 7, width=2)
                    _draw_text(
                        surf,
                        font_small,
                        f"Targeting {targeting_ability_name}: left-click map, right-click/Esc cancel",
                        (dragon_panel_w + 12, TIME_BAR_HEIGHT + 10),
                        ui_theme.accent_rgb,
                    )

                bar_rect = pygame.Rect(0, win_h - SETTINGS_BAR_HEIGHT, win_w, SETTINGS_BAR_HEIGHT)
                pygame.draw.rect(surf, _UI_BG_RGB, bar_rect)
                pygame.draw.rect(surf, ui_theme.border_rgb, bar_rect, width=1)
                btn = pygame.Rect(win_w - 140, win_h - SETTINGS_BAR_HEIGHT + 10, 120, 36)
                hovered = btn.collidepoint(pygame.mouse.get_pos())
                _draw_button(
                    surf,
                    font_mid,
                    btn,
                    "Settings",
                    hovered=hovered,
                    border_rgb=ui_theme.border_rgb,
                )

                dragon_upgrade_overlay_click = None
                if (
                    dragon_upgrade_overlay_active
                    and dragon_upgrade_overlay_baseline is not None
                    and not game_over
                ):
                    dragon_upgrade_overlay_click = draw_dragon_upgrade_overlay(
                        surf,
                        theme=ui_theme,
                        client_w=win_w,
                        client_h=win_h,
                        font_mid=font_mid,
                        font_small=font_small,
                        font_small_bold=font_small_bold,
                        baseline=dragon_upgrade_overlay_baseline,
                        draft=dragon_upgrade_draft,
                    )

                event_history_close_rect = None
                if event_history_open:
                    event_history_close_rect, event_history_content_h = _draw_event_history_overlay(
                        surf,
                        win_w,
                        win_h,
                        font_mid,
                        font_small,
                        event_log,
                        event_history_scroll,
                        theme=ui_theme,
                    )

                debug_overlay_click = None
                if debug_overlay_active:
                    debug_overlay_click = _draw_debug_overlay(
                        surf,
                        win_w,
                        win_h,
                        font_mid,
                        font_small,
                        day_debug_log,
                        debug_selected_day,
                        debug_scroll_y,
                        theme=ui_theme,
                    )

                game_over_new_game_rect = None
                if game_over:
                    game_over_new_game_rect = _draw_game_over_overlay(
                        surf,
                        win_w,
                        win_h,
                        font_big,
                        font_mid,
                        turns_survived=day_index,
                    )

            elif screen == "settings":
                surf.fill(_UI_BG_RGB)
                _draw_text(surf, font_big, "Settings", (60, 60), _UI_TEXT_RGB)

                mx, my = pygame.mouse.get_pos()
                btn_game_opts = pygame.Rect(60, 130, 260, 40)
                btn_creator = pygame.Rect(60, 182, 260, 40)
                btn_loader = pygame.Rect(60, 234, 260, 40)
                btn_editor = pygame.Rect(60, 286, 260, 40)
                btn_new_game = pygame.Rect(60, 338, 260, 40)
                btn_dev = pygame.Rect(60, 390, 260, 40)
                btn_back = pygame.Rect(60, win_h - 70, 120, 36)

                _draw_button(
                    surf,
                    font_mid,
                    btn_game_opts,
                    "Game Options",
                    hovered=btn_game_opts.collidepoint(mx, my),
                )
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
                    (60, 438),
                    _UI_MUTED_TEXT_RGB,
                )
                _draw_button(
                    surf, font_mid, btn_back, "Back", hovered=btn_back.collidepoint(mx, my)
                )

                if settings_status:
                    _draw_text(surf, font, settings_status, (60, 478), _UI_MUTED_TEXT_RGB)

            elif screen == "game_options":
                surf.fill(_UI_BG_RGB)
                game_options_track_rects = {}
                game_options_preset_rects = {}
                _draw_text(surf, font_big, "Game Options", (60, 60), _UI_TEXT_RGB)
                mx, my = pygame.mouse.get_pos()
                preset_y = 125
                preset_x = 60
                preset_w, preset_h, preset_gap = 90, 36, 10
                for level, label in (
                    ("easy", "Easy"),
                    ("normal", "Normal"),
                    ("hard", "Hard"),
                ):
                    btn = pygame.Rect(preset_x, preset_y, preset_w, preset_h)
                    preset_x += preset_w + preset_gap
                    game_options_preset_rects[level] = btn
                    _draw_button(
                        surf,
                        font_mid,
                        btn,
                        label,
                        hovered=btn.collidepoint(mx, my),
                        active=game_options_difficulty == level,
                    )
                panel = pygame.Rect(40, 170, win_w - 80, win_h - 250)
                pygame.draw.rect(surf, _UI_PANEL_RGB, panel, border_radius=8)
                pygame.draw.rect(surf, _UI_BORDER_RGB, panel, width=1, border_radius=8)

                inner = panel.inflate(-16, -16)
                row_h = 54
                defs = _game_options_slider_defs()
                content_h = len(defs) * row_h + 24
                scroll_max = max(0, content_h - inner.h)
                game_options_scroll = max(0, min(game_options_scroll, scroll_max))

                clip_prev = surf.get_clip()
                surf.set_clip(inner)
                track_w = max(120, min(340, inner.w - 100))
                y_cursor = inner.y + 8 - game_options_scroll
                x_label = inner.x + 4
                for attr, label, lo, hi in defs:
                    y = y_cursor
                    y_cursor += row_h
                    if y + row_h < inner.top or y > inner.bottom:
                        continue
                    _draw_text(surf, font_small, label, (x_label, y), _UI_TEXT_RGB)
                    track = pygame.Rect(x_label, y + 22, track_w, 12)
                    val = getattr(game_tuning, attr)
                    frac = (val - lo) / max(1, (hi - lo))
                    pygame.draw.rect(surf, _UI_INPUT_RGB, track, border_radius=4)
                    pygame.draw.rect(surf, _UI_BORDER_RGB, track, width=1, border_radius=4)
                    knob_w = max(6, int(track.w * 0.04))
                    kx = int(track.x + frac * max(0, track.w - knob_w))
                    knob = pygame.Rect(kx, track.y - 2, knob_w, track.h + 4)
                    pygame.draw.rect(surf, _UI_BUTTON_HOVER_RGB, knob, border_radius=3)
                    pygame.draw.rect(surf, _UI_BORDER_RGB, knob, width=1, border_radius=3)
                    val_s = _game_options_slider_value_label(attr, val)
                    _draw_text(surf, font_small, val_s, (track.right + 10, y + 20), _UI_TEXT_RGB)
                    game_options_track_rects[attr] = track.inflate(0, 12)

                surf.set_clip(clip_prev)

                btn_back = pygame.Rect(60, win_h - 70, 120, 36)
                _draw_button(
                    surf, font_mid, btn_back, "Back", hovered=btn_back.collidepoint(mx, my)
                )

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
                    if screen == "game" and event_popup_active:
                        event_popup_active = False
                        pending_event_lines.clear()
                        redraw()
                        continue
                    if screen == "game" and event_history_open:
                        event_history_open = False
                        event_history_scroll = 0
                        redraw()
                        continue
                    if screen == "game" and debug_overlay_active:
                        debug_overlay_active = False
                        debug_scroll_y = 0
                        redraw()
                        continue
                    if screen == "game" and dragon_upgrade_overlay_active:
                        redraw()
                        continue
                    if screen == "game" and game_over:
                        redraw()
                        continue
                    if screen == "game" and targeting_ability_name is not None:
                        targeting_ability_name = None
                        event_log.append((day_index, "Ability targeting cancelled."))
                        pending_event_lines.append("Ability targeting cancelled.")
                        event_popup_active = True
                        redraw()
                        continue
                    if screen == "game":
                        running = False
                        break
                    if screen == "map_creator_editor":
                        editor = None
                        editor_paint_drag_active = False
                        last_editor_paint_coord = None
                        screen = "map_creator_setup"
                        focused_field = None
                        draft.error = ""
                        redraw()
                        continue
                    if screen == "map_editor":
                        editor = None
                        editor_paint_drag_active = False
                        last_editor_paint_coord = None
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
                    if screen == "game_options":
                        screen = "settings"
                        game_options_drag_attr = None
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
                if event.type == pygame.MOUSEWHEEL and screen == "game_options":
                    inner_h = max(1, win_h - 200 - 32)
                    content_h = len(_game_options_slider_defs()) * 54 + 24
                    game_options_scroll = _clamp_panel_scroll(
                        game_options_scroll - event.y * 24,
                        content_h,
                        inner_h,
                    )
                    redraw()
                    continue

                if event.type == pygame.MOUSEWHEEL and screen == "game" and event_history_open:
                    event_history_scroll = _clamp_panel_scroll(
                        event_history_scroll - event.y * 24,
                        event_history_content_h,
                        max(1, win_h * 3 // 4 - 120),
                    )
                    redraw()
                    continue

                if (
                    event.type == pygame.MOUSEWHEEL
                    and screen == "game"
                    and debug_overlay_active
                    and debug_overlay_click is not None
                ):
                    debug_scroll_y = _clamp_panel_scroll(
                        debug_scroll_y - event.y * 24,
                        debug_overlay_click.content_height,
                        debug_overlay_click.content_viewport_h,
                    )
                    redraw()
                    continue

                if (
                    event.type == pygame.MOUSEWHEEL
                    and screen == "game"
                    and game_map is not None
                    and dragon is not None
                    and not game_over
                ):
                    mx_w, my_w = pygame.mouse.get_pos()
                    map_row_h = win_h - TIME_BAR_HEIGHT - SETTINGS_BAR_HEIGHT
                    dragon_panel_rect = pygame.Rect(0, TIME_BAR_HEIGHT, dragon_panel_w, map_row_h)
                    inspector_panel_rect = pygame.Rect(
                        win_w - inspector_panel_w,
                        TIME_BAR_HEIGHT,
                        inspector_panel_w,
                        map_row_h,
                    )
                    wheel_step = event.y * 24
                    panel_viewport_h = max(1, map_row_h - 24)
                    if dragon_panel_rect.collidepoint(mx_w, my_w):
                        dragon_panel_scroll = _clamp_panel_scroll(
                            dragon_panel_scroll - wheel_step,
                            dragon_panel_content_h,
                            panel_viewport_h,
                        )
                        redraw()
                        continue
                    if inspector_panel_rect.collidepoint(mx_w, my_w):
                        inspector_panel_scroll = _clamp_panel_scroll(
                            inspector_panel_scroll - wheel_step,
                            inspector_panel_content_h,
                            panel_viewport_h,
                        )
                        redraw()
                        continue
                    map_vp = _map_viewport_rect(
                        win_w,
                        win_h,
                        dragon_panel_w=dragon_panel_w,
                        inspector_panel_w=inspector_panel_w,
                    )
                    if map_vp.collidepoint(mx_w, my_w):
                        # Viewport-local anchor for cursor-anchored zoom (map_camera).
                        anchor_local = (float(mx_w - map_vp.x), float(my_w - map_vp.y))
                        map_camera = apply_wheel_zoom(
                            map_camera,
                            game_map,
                            map_vp.w,
                            map_vp.h,
                            anchor_local=anchor_local,
                            wheel_y=event.y,
                        )
                        apply_layout(win_w, win_h)
                        redraw()
                        continue

                if event.type == pygame.MOUSEBUTTONUP and event.button == 1:
                    splitter_drag = None
                    editor_paint_drag_active = False
                    last_editor_paint_coord = None
                    game_options_drag_attr = None

                if (
                    event.type == pygame.MOUSEMOTION
                    and splitter_drag is not None
                    and screen == "game"
                    and game_map is not None
                    and not game_over
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

                if (
                    event.type == pygame.MOUSEMOTION
                    and game_options_drag_attr is not None
                    and screen == "game_options"
                ):
                    mx_m, _my_m = event.pos
                    track = game_options_track_rects.get(game_options_drag_attr)
                    if track is not None:
                        for attr, _label, lo, hi in _game_options_slider_defs():
                            if attr == game_options_drag_attr:
                                _game_options_set_slider_from_mouse(
                                    game_tuning, attr, mx_m, track, lo, hi
                                )
                                break
                    redraw()
                    continue

                if (
                    event.type == pygame.MOUSEMOTION
                    and editor_paint_drag_active
                    and screen in ("map_creator_editor", "map_editor")
                    and editor is not None
                ):
                    mx_m, my_m = event.pos
                    toolbar_w = 240
                    top_pad = 70
                    bottom_pad = SETTINGS_BAR_HEIGHT
                    map_view_drag = pygame.Rect(
                        0, top_pad, win_w - toolbar_w, win_h - top_pad - bottom_pad
                    )
                    if map_view_drag.collidepoint(mx_m, my_m):
                        chg, picked_drag = _editor_try_paint_at_pixel(
                            editor,
                            float(mx_m),
                            float(my_m),
                            map_view_drag,
                            skip_if_same_as=last_editor_paint_coord,
                        )
                        if chg:
                            last_editor_paint_coord = picked_drag
                            redraw()

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
                    if screen == "game" and event_popup_active:
                        event_popup_active = False
                        pending_event_lines.clear()
                        redraw()
                        continue
                    if screen == "game" and event_history_open:
                        event_history_open = False
                        event_history_scroll = 0
                        redraw()
                        continue
                    if screen == "game" and debug_overlay_active:
                        debug_overlay_active = False
                        debug_scroll_y = 0
                        redraw()
                        continue
                    in_play_session_rc = (
                        screen == "game"
                        and game_map is not None
                        and dragon is not None
                        and citadel_coord is not None
                    )
                    if in_play_session_rc and not dragon_upgrade_overlay_active and not game_over:
                        if targeting_ability_name is not None:
                            targeting_ability_name = None
                            event_log.append((day_index, "Ability targeting cancelled."))
                            pending_event_lines.append("Ability targeting cancelled.")
                            event_popup_active = True
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
                            picked = _pick_tile_at_pixel(
                                float(mx_r),
                                float(my_r),
                                gmap_rc,
                                hex_size,
                                origin,
                            )
                            if picked != inspector_focus_coord:
                                inspector_panel_scroll = 0
                            inspector_focus_coord = picked
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
                        can_play = (
                            pending_map_path is not None or dragon_pick_context == "same_map_reset"
                        )
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

                        if event_popup_active:
                            event_popup_active = False
                            pending_event_lines.clear()
                            redraw()
                            continue

                        if event_history_open:
                            if (
                                event_history_close_rect is not None
                                and event_history_close_rect.collidepoint(mx, my)
                            ):
                                event_history_open = False
                                event_history_scroll = 0
                            redraw()
                            continue

                        if debug_overlay_active:
                            if debug_overlay_click is not None:
                                clk = debug_overlay_click
                                if clk.close.collidepoint(mx, my):
                                    debug_overlay_active = False
                                    debug_scroll_y = 0
                                elif clk.day_minus.collidepoint(mx, my):
                                    log_days = day_debug_log.days()
                                    if log_days:
                                        current = _clamp_debug_selected_day(
                                            debug_selected_day, day_debug_log
                                        )
                                        idx = log_days.index(current)
                                        if idx > 0:
                                            debug_selected_day = log_days[idx - 1]
                                            debug_scroll_y = 0
                                elif clk.day_plus.collidepoint(mx, my):
                                    log_days = day_debug_log.days()
                                    if log_days:
                                        current = _clamp_debug_selected_day(
                                            debug_selected_day, day_debug_log
                                        )
                                        idx = log_days.index(current)
                                        if idx < len(log_days) - 1:
                                            debug_selected_day = log_days[idx + 1]
                                            debug_scroll_y = 0
                            redraw()
                            continue

                        if game_over:
                            if (
                                game_over_new_game_rect is not None
                                and game_over_new_game_rect.collidepoint(mx, my)
                            ):
                                _reset_session_for_map(gmap)
                            redraw()
                            continue

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
                                    dragon_hp_before_heal = dgn.hp
                                    dgn.begin_new_day_at_citadel(ccd, tuning=game_tuning)
                                    world_event_day_state.clear()
                                    day_index += 1
                                    day_debug_log.start_day(day_index)
                                    log_dragon_end_of_day_heal(
                                        day_debug_log,
                                        dragon_hp_before_heal,
                                        dgn.hp,
                                    )
                                    citadel_hp_at_day_start = citadel_hp
                                    world_event_messages: list[str] = []
                                    world_event_effect_msgs: list[str] = []
                                    world_roll = roll_world_event(
                                        game_tuning.world_event_chance_percent,
                                        world_event_rng,
                                    )
                                    log_world_event_roll(
                                        day_debug_log,
                                        game_tuning.world_event_chance_percent,
                                        world_roll,
                                    )
                                    if world_roll.triggered and world_roll.event_id:
                                        citadel_hp, spawned_armies, extra_msgs = apply_world_event(
                                            world_roll.event_id,
                                            dragon=dgn,
                                            game_map=gmap,
                                            settlements=settlements_by_coord.values(),
                                            day_state=world_event_day_state,
                                            citadel_hp=citadel_hp,
                                            max_citadel_hp=CITADEL_STARTING_HP,
                                            fog=fog_of_war,
                                            rng=world_event_rng,
                                        )
                                        active_armies.extend(spawned_armies)
                                        world_event_messages.append(world_roll.description)
                                        world_event_messages.extend(extra_msgs)
                                        world_event_effect_msgs.extend(extra_msgs)
                                    log_world_event_effects(day_debug_log, world_event_effect_msgs)
                                    log_citadel_hp_change(
                                        day_debug_log,
                                        citadel_hp_at_day_start,
                                        citadel_hp,
                                        reason="world event",
                                    )
                                    (
                                        double_growth,
                                        double_heal,
                                        eco_mult,
                                    ) = settlement_phase_world_event_hooks(world_event_day_state)
                                    settlement_phase_outcomes: dict[
                                        OffsetCoord,
                                        tuple[SettlementPhaseBefore, Any, bool],
                                    ] = {}
                                    for coord, ent in settlements_by_coord.items():
                                        growth_delayed = settlement_growth_is_delayed(
                                            world_event_day_state,
                                            coord,
                                        )
                                        before = SettlementPhaseBefore(
                                            eco=int(ent.eco),
                                            atk=int(ent.atk),
                                            dfn=int(ent.dfn),
                                            hp=int(ent.hp),
                                        )
                                        outcome = ent.on_settlement_phase_end(
                                            tuning=game_tuning,
                                            growth_delayed=growth_delayed,
                                            double_growth=double_growth,
                                            double_healing=double_heal,
                                            eco_growth_mult=eco_mult,
                                        )
                                        settlement_phase_outcomes[coord] = (
                                            before,
                                            outcome,
                                            growth_delayed,
                                        )
                                    log_settlement_phase(
                                        day_debug_log,
                                        settlements_by_coord,
                                        settlement_phase_outcomes,
                                    )
                                    heroes_spawned, heroes_party_city_pool = (
                                        spawn_heroes_party_wave(
                                            settlements_by_coord.values(),
                                            day_index,
                                            tuning=game_tuning,
                                            pool=heroes_party_city_pool,
                                            rng=heroes_party_rng,
                                        )
                                    )
                                    log_heroes_party_spawn(day_debug_log, heroes_spawned)
                                    heroes_spawn_message = ""
                                    if heroes_spawned:
                                        active_armies.extend(heroes_spawned)
                                        heroes_spawn_message = (
                                            f"Hero's Party marches from "
                                            f"{len(heroes_spawned)} cities!"
                                        )
                                    apply_army_day_speed_modifiers(
                                        active_armies,
                                        world_event_day_state,
                                    )
                                    armies_before_phase = snapshot_armies_before_phase(
                                        active_armies
                                    )
                                    citadel_hp_before_army = citadel_hp
                                    (
                                        next_armies,
                                        next_citadel_hp,
                                        phase_msgs,
                                        phase_over,
                                        army_phase_result,
                                    ) = _run_end_of_day_army_phase(
                                        gmap,
                                        active_armies,
                                        citadel_coord=ccd,
                                        citadel_hp=citadel_hp,
                                        dragon=dgn,
                                        movement_ctx=army_movement_context(world_event_day_state),
                                    )
                                    if army_phase_result is not None:
                                        log_army_phase(
                                            day_debug_log,
                                            armies_before_phase,
                                            active_armies,
                                            army_phase_result,
                                            citadel_coord=ccd,
                                        )
                                    log_citadel_hp_change(
                                        day_debug_log,
                                        citadel_hp_before_army,
                                        next_citadel_hp,
                                        reason="army phase",
                                    )
                                    active_armies = next_armies
                                    citadel_hp = next_citadel_hp
                                    active_armies = _prune_defeated_armies(active_armies)
                                    if phase_over or citadel_hp <= 0:
                                        citadel_hp = max(0, citadel_hp)
                                        _enter_game_over()
                                    else:
                                        pending_event_lines.clear()
                                        for msg in world_event_messages:
                                            event_log.append((day_index, msg))
                                            pending_event_lines.append(msg)
                                        if phase_msgs:
                                            for msg in phase_msgs:
                                                event_log.append((day_index, msg))
                                                pending_event_lines.append(msg)
                                        if heroes_spawn_message:
                                            event_log.append((day_index, heroes_spawn_message))
                                            pending_event_lines.append(heroes_spawn_message)
                                        if citadel_hp < CITADEL_STARTING_HP:
                                            if not citadel_damage_announced:
                                                cit_msg = (
                                                    f"Citadel struck! "
                                                    f"HP {citadel_hp}/{CITADEL_STARTING_HP}."
                                                )
                                                event_log.append((day_index, cit_msg))
                                                pending_event_lines.append(cit_msg)
                                                citadel_damage_announced = True
                                        else:
                                            citadel_damage_announced = False
                                        if pending_event_lines:
                                            event_popup_active = True
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

                        map_vp_click = _map_viewport_rect(
                            win_w,
                            win_h,
                            dragon_panel_w=dragon_panel_w,
                            inspector_panel_w=inspector_panel_w,
                        )
                        zoom_in_rect, zoom_out_rect, history_btn_rect, debug_btn_rect = (
                            _map_zoom_control_rects(map_vp_click)
                        )
                        zoom_anchor = (map_vp_click.w / 2.0, map_vp_click.h / 2.0)
                        if zoom_in_rect.collidepoint(mx, my):
                            map_camera = apply_zoom_step(
                                map_camera,
                                gmap,
                                map_vp_click.w,
                                map_vp_click.h,
                                anchor_local=zoom_anchor,
                                direction=1,
                            )
                            apply_layout(win_w, win_h)
                            redraw()
                            continue
                        if zoom_out_rect.collidepoint(mx, my):
                            map_camera = apply_zoom_step(
                                map_camera,
                                gmap,
                                map_vp_click.w,
                                map_vp_click.h,
                                anchor_local=zoom_anchor,
                                direction=-1,
                            )
                            apply_layout(win_w, win_h)
                            redraw()
                            continue
                        if history_btn_rect.collidepoint(mx, my):
                            event_history_open = True
                            event_history_scroll = 0
                            debug_overlay_active = False
                            debug_scroll_y = 0
                            redraw()
                            continue
                        if debug_btn_rect.collidepoint(mx, my):
                            debug_overlay_active = not debug_overlay_active
                            if debug_overlay_active:
                                event_history_open = False
                                event_history_scroll = 0
                                debug_selected_day = day_debug_log.latest_day() or day_index
                                debug_scroll_y = 0
                            redraw()
                            continue

                        if (
                            map_row_top <= my <= map_row_bottom
                            and mx < dragon_panel_w
                            and raid_combat_settlement is None
                            and army_combat_target is None
                        ):
                            for ability_name, rect in dragon_ability_button_rects.items():
                                if rect.collidepoint(mx, my):
                                    result = try_use_ability(
                                        dgn,
                                        ability_name,
                                        world=gmap,
                                        citadel_coord=ccd,
                                        settlements_by_coord=settlements_by_coord,
                                        armies_by_coord=_armies_by_coord(active_armies),
                                    )
                                    if result.ok and result.target_required:
                                        targeting_ability_name = ability_name
                                    elif result.ok:
                                        targeting_ability_name = None
                                    event_log.append((day_index, result.reason))
                                    pending_event_lines.append(result.reason)
                                    event_popup_active = True
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
                                armies_by_coord=_armies_by_coord(active_armies),
                            )
                            event_log.append((day_index, result.reason))
                            pending_event_lines.append(result.reason)
                            event_popup_active = True
                            if result.ok:
                                targeting_ability_name = None
                            redraw()
                            continue

                        if army_combat_target is not None:
                            if (
                                army_overlay_retreat_rect is not None
                                and army_overlay_retreat_rect.collidepoint(mx, my)
                            ):
                                on_combat_ended(dgn)
                                army_combat_target = None
                                army_overlay_banner = ""
                                army_overlay_auto_close_deadline_ms = None
                                redraw()
                                continue
                            if (
                                army_overlay_attack_rect is not None
                                and army_overlay_attack_rect.collidepoint(mx, my)
                            ):
                                target_army = army_combat_target
                                if _army_hp(target_army) <= 0 or dgn.hp <= 0:
                                    if dgn.hp <= 0:
                                        on_combat_ended(dgn)
                                        _enter_game_over()
                                    redraw()
                                    continue
                                exchange = _resolve_army_combat_round(
                                    dgn,
                                    target_army,
                                    gmap,
                                    citadel_coord=ccd,
                                )
                                if isinstance(exchange, MoveAttempt):
                                    on_combat_ended(dgn)
                                    army_overlay_banner = exchange.reason
                                    army_combat_target = None
                                    army_overlay_auto_close_deadline_ms = None
                                    event_log.append((day_index, exchange.reason))
                                    pending_event_lines.append(exchange.reason)
                                    event_popup_active = True
                                    redraw()
                                    continue

                                if _army_hp(target_army) <= 0:
                                    on_combat_ended(dgn)
                                    was_caravan = _army_kind(target_army) is ArmyKind.GOLDEN_CARAVAN
                                    gold_granted = grant_army_victory_loot(dgn, target_army)
                                    active_armies[:] = _prune_defeated_armies(active_armies)
                                    if was_caravan:
                                        revenge = on_golden_caravan_defeated(
                                            world_event_day_state,
                                            gmap,
                                            dragon_level=dgn.level,
                                            rng=world_event_rng,
                                        )
                                        if revenge is not None:
                                            active_armies.append(revenge)
                                    dname = display_name_for_kind(dgn.kind)
                                    army_overlay_banner = f"{dname} destroyed the army."
                                    army_win_msg = "Army destroyed!"
                                    if gold_granted:
                                        army_overlay_banner += f" Gained {gold_granted} gold."
                                        army_win_msg += f" Gained {gold_granted} gold."
                                    if was_caravan:
                                        army_win_msg += (
                                            " A Revenge Army marches to punish your greed!"
                                        )
                                    event_log.append((day_index, army_win_msg))
                                    pending_event_lines.append(army_win_msg)
                                    event_popup_active = True
                                    army_overlay_auto_close_deadline_ms = (
                                        pygame.time.get_ticks() + RAID_COMBAT_OVERLAY_AUTO_CLOSE_MS
                                    )
                                elif dgn.hp <= 0:
                                    on_combat_ended(dgn)
                                    _enter_game_over()
                                else:
                                    army_overlay_banner = ""
                                redraw()
                                continue
                            if in_map_row and in_map_column:
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
                                    if dgn.hp <= 0:
                                        on_combat_ended(dgn)
                                        _enter_game_over()
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
                                    event_log.append((day_index, exchange.reason))
                                    pending_event_lines.append(exchange.reason)
                                    event_popup_active = True
                                    redraw()
                                    continue

                                if target.hp <= 0:
                                    on_combat_ended(dgn)
                                    gold_added, spawn_events = apply_settlement_raid_victory_bundle(
                                        dgn,
                                        target,
                                        list(settlements_by_coord.values()),
                                        tuning=game_tuning,
                                    )
                                    spawned = _spawn_armies_from_events(
                                        list(spawn_events),
                                        settlements_by_coord=settlements_by_coord,
                                        active_armies=active_armies,
                                        tuning=game_tuning,
                                    )
                                    dname = display_name_for_kind(dgn.kind)
                                    raid_overlay_banner = (
                                        f"{dname} won and gained {gold_added} gold"
                                    )
                                    raid_win_msg = f"Raid victory! Gained {gold_added} gold."
                                    event_log.append((day_index, raid_win_msg))
                                    pending_event_lines.append(raid_win_msg)
                                    if spawned:
                                        raid_overlay_banner += f"; {spawned} army mobilized"
                                        spawn_msg = (
                                            f"{spawned} army mobilized from nearby settlements!"
                                        )
                                        event_log.append((day_index, spawn_msg))
                                        pending_event_lines.append(spawn_msg)
                                    event_popup_active = True
                                    raid_overlay_auto_close_deadline_ms = (
                                        pygame.time.get_ticks() + RAID_COMBAT_OVERLAY_AUTO_CLOSE_MS
                                    )
                                elif dgn.hp <= 0:
                                    on_combat_ended(dgn)
                                    _enter_game_over()
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
                                    else:
                                        event_log.append((day_index, reason))
                                        pending_event_lines.append(reason)
                                        event_popup_active = True
                            if (
                                inspector_army_attack_button_rect is not None
                                and inspector_army_attack_button_rect.collidepoint(mx, my)
                                and inspector_focus_coord is not None
                            ):
                                target_army = _armies_by_coord(active_armies).get(
                                    inspector_focus_coord
                                )
                                if target_army is not None:
                                    ok_army, reason_army = _validate_dragon_vs_army(
                                        dgn,
                                        target_army,
                                        citadel_coord=ccd,
                                    )
                                    if ok_army:
                                        army_combat_target = target_army
                                        army_overlay_banner = ""
                                        army_overlay_auto_close_deadline_ms = None
                                    else:
                                        event_log.append((day_index, reason_army))
                                        pending_event_lines.append(reason_army)
                                        event_popup_active = True
                            redraw()
                            continue

                        if not in_map_row or not in_map_column:
                            continue

                        picked = _pick_tile_at_pixel(float(mx), float(my), gmap, hex_size, origin)
                        if picked is None:
                            continue
                        outcome = dgn.move(picked, gmap, ccd)
                        if outcome.ok:
                            reveal_coords_in_range(fog_of_war, dgn, gmap)
                        if outcome.ok and dgn.position == ccd:
                            dragon_upgrade_overlay_active = True
                            dragon_upgrade_draft = []
                            dragon_upgrade_overlay_baseline = dragon_upgrade_baseline_from_dragon(
                                dgn
                            )
                            dragon_upgrade_overlay_click = None
                        redraw()
                        continue

                    if screen == "game_options":
                        btn_back = pygame.Rect(60, win_h - 70, 120, 36)
                        if btn_back.collidepoint(mx, my):
                            screen = "settings"
                            game_options_drag_attr = None
                            redraw()
                            continue
                        for level, preset_rect in game_options_preset_rects.items():
                            if preset_rect.collidepoint(mx, my):
                                apply_difficulty_preset(game_tuning, level)
                                game_options_difficulty = level
                                redraw()
                                break
                        else:
                            for attr, _label, lo, hi in _game_options_slider_defs():
                                tr = game_options_track_rects.get(attr)
                                if tr is not None and tr.collidepoint(mx, my):
                                    game_options_drag_attr = attr
                                    _game_options_set_slider_from_mouse(
                                        game_tuning, attr, mx, tr, lo, hi
                                    )
                                    redraw()
                                    break
                        continue

                    if screen == "settings":
                        btn_game_opts = pygame.Rect(60, 130, 260, 40)
                        btn_creator = pygame.Rect(60, 182, 260, 40)
                        btn_loader = pygame.Rect(60, 234, 260, 40)
                        btn_editor = pygame.Rect(60, 286, 260, 40)
                        btn_new_game = pygame.Rect(60, 338, 260, 40)
                        btn_dev = pygame.Rect(60, 390, 260, 40)
                        btn_back = pygame.Rect(60, win_h - 70, 120, 36)
                        if btn_game_opts.collidepoint(mx, my):
                            screen = "game_options"
                            game_options_drag_attr = None
                            redraw()
                            continue
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
                                editor_paint_drag_active = False
                                last_editor_paint_coord = None
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
                            settings_status = f"Dev Mode: +{DEV_MODE_TEST_GOLD_GRANT:,} gold."
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
                            editor_paint_drag_active = False
                            last_editor_paint_coord = None
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
                            editor_paint_drag_active = False
                            last_editor_paint_coord = None
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
                                    editor_paint_drag_active = True
                                    chg, picked_here = _editor_try_paint_at_pixel(
                                        editor, float(mx), float(my), map_view
                                    )
                                    last_editor_paint_coord = picked_here
                                    if chg:
                                        redraw()

            if (
                screen == "game"
                and not game_over
                and raid_overlay_auto_close_deadline_ms is not None
                and pygame.time.get_ticks() >= raid_overlay_auto_close_deadline_ms
            ):
                raid_combat_settlement = None
                raid_overlay_banner = ""
                raid_overlay_auto_close_deadline_ms = None
                redraw()

            if (
                screen == "game"
                and not game_over
                and army_overlay_auto_close_deadline_ms is not None
                and pygame.time.get_ticks() >= army_overlay_auto_close_deadline_ms
            ):
                army_combat_target = None
                army_overlay_banner = ""
                army_overlay_auto_close_deadline_ms = None
                redraw()

            if screen == "game" and not game_over:
                if dragon is not None and dragon.hp <= 0:
                    _enter_game_over()
                    redraw()
                elif citadel_hp <= 0:
                    _enter_game_over()
                    redraw()

            if (
                screen == "game"
                and game_map is not None
                and not game_over
                and camera_is_pannable(map_camera)
            ):
                map_vp_pan = _map_viewport_rect(
                    win_w,
                    win_h,
                    dragon_panel_w=dragon_panel_w,
                    inspector_panel_w=inspector_panel_w,
                )
                keys = pygame.key.get_pressed()
                pan_keys = (
                    pygame.K_w,
                    pygame.K_a,
                    pygame.K_s,
                    pygame.K_d,
                    pygame.K_UP,
                    pygame.K_DOWN,
                    pygame.K_LEFT,
                    pygame.K_RIGHT,
                )
                if any(keys[k] for k in pan_keys):
                    dt_sec = clock.get_time() / 1000.0
                    next_camera = apply_keyboard_pan(
                        map_camera,
                        keys,
                        dt_sec,
                        game_map,
                        map_vp_pan.w,
                        map_vp_pan.h,
                    )
                    if (
                        next_camera.zoom_factor != map_camera.zoom_factor
                        or next_camera.pan_x != map_camera.pan_x
                        or next_camera.pan_y != map_camera.pan_y
                    ):
                        map_camera = next_camera
                        apply_layout(win_w, win_h)
                        redraw()

            clock.tick(_FRAME_RATE)
    finally:
        pygame.quit()

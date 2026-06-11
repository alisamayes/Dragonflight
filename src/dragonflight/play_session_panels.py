"""Gameplay side panels and the dragon upgrade overlay for the Pygame play session.

These surfaces are presentation for dragon/progression and map inspection; they are
not part of hex movement simulation proper. Data lines are sourced from
:mod:`dragonflight.tile_inspection` where possible.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

import pygame

from .combatant_stats import dragon_combatant_view
from .dragon import Dragon
from .dragon_abilities import (
    ability_button_enabled,
    ability_requires_target,
    ability_status_label,
    ability_ui_detail_lines,
    effective_attack,
    effective_defence,
    effective_flight_range,
    effective_speed_hexes_per_hour,
    unlocked_ability_specs,
)
from .dragon_art import load_detailed_sprite, scaled_to_fit
from .dragon_playables import display_name_for_kind, playable_dragon_kinds
from .dragon_progression import (
    DRAGON_UPGRADE_STAT_COLUMN_ORDER,
    DragonUpgradeBaseline,
    DragonUpgradeStat,
    dragon_stat_pill_strings_from_totals,
    marginal_dragon_stat_upgrade_cost,
    preview_dragon_stats_after_draft,
    total_dragon_upgrade_draft_cost,
)
from .dragon_ui_theme import DragonUITheme
from .fog_of_war import FogOfWarState, is_revealed
from .hex_coord import OffsetCoord
from .map_state import GameMap
from .play_session_ui import (
    _UI_BORDER_RGB,
    _UI_BUTTON_RGB,
    _UI_INPUT_RGB,
    _UI_MUTED_TEXT_RGB,
    _UI_TEXT_RGB,
    ScrollPanelLayout,
    draw_button,
    draw_info_panel_chrome,
    draw_text,
    max_text_pixel_width,
    wrap_text_to_width,
)
from .settlement import Settlement, raid_victory_gold_from_eco, validate_settlement_raid
from .terrain import Terrain
from .tile_inspection import (
    terrain_display_name,
    tile_inspect_info,
    tile_inspector_lines,
    unknown_tile_inspector_lines,
)

#: Inspector minimum column width uses this fraction of the font-metric text box (num/den).
INSPECTOR_PANEL_MIN_WIDTH_SCALE_NUM: int = 60
INSPECTOR_PANEL_MIN_WIDTH_SCALE_DEN: int = 100
INSPECTOR_PANEL_MIN_WIDTH_FLOOR_PX: int = 80

__all__ = [
    "INSPECTOR_PANEL_MIN_WIDTH_FLOOR_PX",
    "INSPECTOR_PANEL_MIN_WIDTH_SCALE_DEN",
    "INSPECTOR_PANEL_MIN_WIDTH_SCALE_NUM",
    "DragonUpgradeOverlayClickRects",
    "DragonUpgradeOverlayLayout",
    "dragon_upgrade_overlay_layout",
    "draw_dragon_panel",
    "draw_dragon_upgrade_overlay",
    "draw_tile_inspector_panel",
    "inspector_panel_raw_min_column_width",
    "min_dragon_panel_column_width",
    "min_inspector_panel_column_width",
]


def min_dragon_panel_column_width(font: pygame.font.Font, font_small: pygame.font.Font) -> int:
    """Content-based minimum width for the dragon stats column (padding + widest sample lines)."""

    pad = 12
    header_w = max_text_pixel_width(font, ("Dragon",))
    kind_w = max(
        (
            max_text_pixel_width(font_small, (display_name_for_kind(k),))
            for k in playable_dragon_kinds()
        ),
        default=0,
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
    body_w = max_text_pixel_width(font_small, body_lines)
    inner = max(header_w, kind_w, body_w)
    return inner + 2 * pad


def inspector_panel_raw_min_column_width(
    font: pygame.font.Font, font_small: pygame.font.Font
) -> int:
    """Unscaled font-metric minimum width for the inspector column."""

    pad = 12
    title_w = max_text_pixel_width(font, ("Tile inspector",))
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
    body_w = max_text_pixel_width(font_small, sample_lines)
    inner = max(title_w, body_w)
    return inner + 2 * pad


def min_inspector_panel_column_width(font: pygame.font.Font, font_small: pygame.font.Font) -> int:
    """Content-based minimum width for the tile inspector column (scaled)."""

    raw = inspector_panel_raw_min_column_width(font, font_small)
    scaled = raw * INSPECTOR_PANEL_MIN_WIDTH_SCALE_NUM // INSPECTOR_PANEL_MIN_WIDTH_SCALE_DEN
    return max(INSPECTOR_PANEL_MIN_WIDTH_FLOOR_PX, scaled)


def draw_dragon_panel(
    surface: pygame.Surface,
    font: pygame.font.Font,
    font_small: pygame.font.Font,
    *,
    panel_rect: pygame.Rect,
    theme: DragonUITheme,
    dragon: Dragon,
    world: GameMap,
    scroll_y: int = 0,
) -> tuple[dict[str, pygame.Rect], int]:
    """Left column: dragon identity, level, combat/move stats, and unlocked abilities."""

    draw_info_panel_chrome(surface, panel_rect, theme=theme, stripe_edge="left")

    layout = ScrollPanelLayout(panel_rect=panel_rect, scroll_y=scroll_y)
    layout.begin(surface)

    line_gap = 22
    line_h_small = font_small.get_height()
    portrait = load_detailed_sprite(dragon.kind)
    if portrait is not None:
        art_max_h = min(200, max(72, int(layout.inner_w * 0.75)))
        scaled = scaled_to_fit(portrait, layout.inner_w, art_max_h)
        if layout.is_visible(scaled.get_height()):
            surface.blit(scaled, (layout.x, layout.screen_y()))
        layout.advance(scaled.get_height() + 10)

    if layout.is_visible(line_h_small):
        draw_text(surface, font, "Dragon", (layout.x, layout.screen_y()), _UI_TEXT_RGB)
    layout.advance(28)
    if layout.is_visible(line_h_small):
        draw_text(
            surface,
            font_small,
            display_name_for_kind(dragon.kind),
            (layout.x, layout.screen_y()),
            _UI_TEXT_RGB,
        )
    layout.advance(line_gap)
    if layout.is_visible(line_h_small):
        draw_text(
            surface,
            font_small,
            f"Level: {dragon.level}",
            (layout.x, layout.screen_y()),
            _UI_MUTED_TEXT_RGB,
        )
    layout.advance(line_gap)
    if layout.is_visible(line_h_small):
        draw_text(
            surface,
            font_small,
            f"Gold: {dragon.gold}",
            (layout.x, layout.screen_y()),
            _UI_MUTED_TEXT_RGB,
        )
    layout.advance(line_gap + 6)

    if layout.is_visible(line_h_small):
        draw_text(surface, font_small, "Base Stats", (layout.x, layout.screen_y()), _UI_TEXT_RGB)
    layout.advance(line_gap)
    view = dragon_combatant_view(dragon, world=world)
    base_stats = (
        f"HP: {dragon.hp} / {view.base_max_hp}",
        f"ATK: {dragon.atk}  |  DFN: {dragon.dfn}",
        f"Flight range: {dragon.flight_range_hexes} hexes",
        f"Speed: {dragon.speed_hexes_per_hour:g} hex/h",
    )
    for line in base_stats:
        if layout.is_visible(line_h_small):
            draw_text(surface, font_small, line, (layout.x, layout.screen_y()), _UI_MUTED_TEXT_RGB)
        layout.advance(line_gap)

    layout.advance(6)
    if layout.is_visible(line_h_small):
        draw_text(surface, font_small, "Combat Stats", (layout.x, layout.screen_y()), _UI_TEXT_RGB)
    layout.advance(line_gap)
    combat_atk = effective_attack(dragon, world=world)
    combat_dfn = effective_defence(dragon)
    combat_range = effective_flight_range(dragon)
    combat_speed = effective_speed_hexes_per_hour(dragon, world=world)
    boosted_rgb = (170, 230, 170)
    combat_lines = (
        (f"HP: {dragon.hp} / {view.effective_max_hp}", view.max_hp_boosted),
        (
            f"ATK: {combat_atk}  |  DFN: {combat_dfn}",
            combat_atk > dragon.atk or combat_dfn > dragon.dfn,
        ),
        (f"Flight range: {combat_range} hexes", combat_range > dragon.flight_range_hexes),
        (f"Speed: {combat_speed:g} hex/h", combat_speed > dragon.speed_hexes_per_hour),
    )
    for line, boosted in combat_lines:
        if layout.is_visible(line_h_small):
            draw_text(
                surface,
                font_small,
                line,
                (layout.x, layout.screen_y()),
                boosted_rgb if boosted else _UI_MUTED_TEXT_RGB,
            )
        layout.advance(line_gap)

    layout.advance(6)
    if layout.is_visible(line_h_small):
        draw_text(surface, font_small, "Abilities", (layout.x, layout.screen_y()), _UI_TEXT_RGB)
    layout.advance(line_gap)
    ability_buttons: dict[str, pygame.Rect] = {}
    mx, my = pygame.mouse.get_pos()
    specs = unlocked_ability_specs(dragon)
    if not specs:
        if layout.is_visible(line_h_small):
            draw_text(
                surface,
                font_small,
                "No abilities unlocked yet.",
                (layout.x, layout.screen_y()),
                _UI_MUTED_TEXT_RGB,
            )
        layout.end(surface)
        return ability_buttons, layout.content_height_total()

    for spec in specs:
        label = f"{spec.name} ({'Passive' if spec.category == 'passive' else 'Ability'})"
        if layout.is_visible(line_h_small):
            draw_text(surface, font_small, label, (layout.x, layout.screen_y()), _UI_TEXT_RGB)
        layout.advance(18)
        for detail in ability_ui_detail_lines(dragon, spec, world=world):
            for line in wrap_text_to_width(font_small, detail, layout.inner_w):
                if layout.is_visible(line_h_small):
                    draw_text(
                        surface,
                        font_small,
                        line,
                        (layout.x, layout.screen_y()),
                        _UI_MUTED_TEXT_RGB,
                    )
                layout.advance(17)
        if spec.category == "passive":
            if layout.is_visible(line_h_small):
                draw_text(
                    surface,
                    font_small,
                    "Active",
                    (layout.x, layout.screen_y()),
                    (170, 220, 170),
                )
            layout.advance(24)
            continue
        status = ability_status_label(dragon, spec.name)
        if layout.is_visible(line_h_small):
            draw_text(
                surface,
                font_small,
                status,
                (layout.x, layout.screen_y()),
                _UI_MUTED_TEXT_RGB,
            )
        layout.advance(18)
        btn_h = 28
        btn = pygame.Rect(layout.x, layout.screen_y(), max(80, layout.inner_w), btn_h)
        enabled = ability_button_enabled(dragon, spec.name)
        if layout.is_visible(btn_h):
            draw_button(
                surface,
                font_small,
                btn,
                "Target" if ability_requires_target(spec.name) else "Use",
                hovered=enabled and btn.collidepoint(mx, my),
                active=enabled,
            )
        ability_buttons[spec.name] = btn
        layout.advance(36)

    layout.end(surface)
    return ability_buttons, layout.content_height_total()


@dataclass(slots=True)
class DragonUpgradeOverlayLayout:
    """Pixel geometry for :func:`draw_dragon_upgrade_overlay`."""

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
    border_rgb: tuple[int, int, int] = _UI_BORDER_RGB,
) -> None:
    pygame.draw.rect(surface, _UI_BUTTON_RGB, rect, border_radius=6)
    pygame.draw.rect(surface, border_rgb, rect, width=1, border_radius=6)
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
    border_rgb: tuple[int, int, int] = _UI_BORDER_RGB,
) -> None:
    mx, my = pygame.mouse.get_pos()
    hovered = enabled and rect.collidepoint(mx, my)
    if enabled:
        draw_button(surface, font, rect, label, hovered=hovered, border_rgb=border_rgb)
    else:
        pygame.draw.rect(surface, _UI_INPUT_RGB, rect, border_radius=6)
        pygame.draw.rect(surface, border_rgb, rect, width=1, border_radius=6)
        surf = font.render(label, True, _UI_MUTED_TEXT_RGB)
        surface.blit(
            surf,
            (rect.x + (rect.w - surf.get_width()) // 2, rect.y + (rect.h - surf.get_height()) // 2),
        )


def draw_dragon_upgrade_overlay(
    surface: pygame.Surface,
    *,
    theme: DragonUITheme,
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
    pygame.draw.rect(surface, theme.panel_tint_rgb, layout.panel)
    pygame.draw.rect(surface, theme.border_rgb, layout.panel, width=1)

    draw_text(surface, font_mid, "Draconic Upgrades", layout.title_pos, _UI_TEXT_RGB)

    base_gold_line = f"Gold: {baseline.gold}    Level: {baseline.level}"
    base_surf = font_small_bold.render(base_gold_line, True, _UI_TEXT_RGB)
    surface.blit(base_surf, layout.baseline_pos)

    draw_text(surface, font_small, "Current stats", layout.current_label_pos, _UI_MUTED_TEXT_RGB)
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
            surface,
            font_small,
            r_cur,
            title=stat_title,
            value=cur_pills[i],
            border_rgb=theme.border_rgb,
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
            border_rgb=theme.border_rgb,
        )
        cost_rects[stat] = r_cost

    draw_text(surface, font_small, "Preview stats", layout.preview_label_pos, _UI_MUTED_TEXT_RGB)
    for i, stat in enumerate(DRAGON_UPGRADE_STAT_COLUMN_ORDER):
        _, r_prv, _ = layout.columns[i]
        stat_title = _DRAGON_UPGRADE_STAT_LABELS[stat]
        _draw_dragon_upgrade_stat_pill(
            surface,
            font_small,
            r_prv,
            title=stat_title,
            value=prv_pills[i],
            border_rgb=theme.border_rgb,
        )

    surface.blit(prv_surf, layout.preview_line_pos)

    mx, my = pygame.mouse.get_pos()
    can_next_day = preview_gold >= 0
    draw_button(
        surface,
        font_small,
        layout.reset_btn,
        "Reset",
        hovered=layout.reset_btn.collidepoint(mx, my),
        border_rgb=theme.border_rgb,
    )
    if can_next_day:
        draw_button(
            surface,
            font_small,
            layout.next_day_btn,
            "Next day",
            hovered=layout.next_day_btn.collidepoint(mx, my),
            border_rgb=theme.border_rgb,
        )
    else:
        _draw_dragon_upgrade_cost_tile(
            surface,
            font_small,
            layout.next_day_btn,
            "Next day",
            enabled=False,
            border_rgb=theme.border_rgb,
        )

    return DragonUpgradeOverlayClickRects(
        cost=cost_rects,
        reset=layout.reset_btn,
        next_day=layout.next_day_btn,
    )


def draw_tile_inspector_panel(
    surface: pygame.Surface,
    font: pygame.font.Font,
    font_small: pygame.font.Font,
    *,
    panel_rect: pygame.Rect,
    theme: DragonUITheme,
    game_map: GameMap,
    settlements_by_coord: dict[OffsetCoord, Settlement],
    armies_by_coord: dict[OffsetCoord, Any],
    inspector_focus_coord: OffsetCoord | None,
    dragon: Dragon,
    raid_combat_active: bool,
    army_combat_active: bool,
    game_over: bool,
    scroll_y: int = 0,
    dragon_vs_army_allowed: Callable[[Dragon, Any], tuple[bool, str]],
    fog_of_war: FogOfWarState,
) -> tuple[pygame.Rect | None, pygame.Rect | None, int]:
    """Paint tile details; returns optional (raid_rect, attack_army_rect) and content height."""

    draw_info_panel_chrome(surface, panel_rect, theme=theme, stripe_edge="right")

    layout = ScrollPanelLayout(panel_rect=panel_rect, scroll_y=scroll_y)
    layout.begin(surface)

    line_gap = 22
    line_h_small = font_small.get_height()
    title_h = font.get_height()

    if layout.is_visible(title_h):
        draw_text(surface, font, "Tile inspector", (layout.x, layout.screen_y()), _UI_TEXT_RGB)
    layout.advance(32)

    raid_click_rect: pygame.Rect | None = None
    army_attack_click_rect: pygame.Rect | None = None
    combat_busy = raid_combat_active or army_combat_active
    mx, my = pygame.mouse.get_pos()

    if inspector_focus_coord is None:
        if layout.is_visible(line_h_small):
            draw_text(
                surface,
                font_small,
                "Right-click the map for terrain details.",
                (layout.x, layout.screen_y()),
                _UI_MUTED_TEXT_RGB,
            )
        layout.advance(line_gap)
    else:
        if not is_revealed(fog_of_war, inspector_focus_coord):
            coord_label = f"Offset col {inspector_focus_coord.col}, row {inspector_focus_coord.row}"
            if layout.is_visible(line_h_small):
                draw_text(
                    surface,
                    font_small,
                    coord_label,
                    (layout.x, layout.screen_y()),
                    _UI_MUTED_TEXT_RGB,
                )
            layout.advance(line_gap)
            for row in unknown_tile_inspector_lines():
                if layout.is_visible(line_h_small):
                    draw_text(
                        surface,
                        font_small,
                        row.text,
                        (layout.x, layout.screen_y()),
                        _UI_TEXT_RGB,
                    )
                layout.advance(line_gap)
        elif (
            info := tile_inspect_info(
                game_map,
                inspector_focus_coord,
                settlements_by_coord,
                armies_by_coord=armies_by_coord,
            )
        ) is None:
            if layout.is_visible(line_h_small):
                draw_text(
                    surface,
                    font_small,
                    "Off-map.",
                    (layout.x, layout.screen_y()),
                    _UI_MUTED_TEXT_RGB,
                )
            layout.advance(line_gap)
        else:
            assert info is not None
            coord_label = f"Offset col {info.coord.col}, row {info.coord.row}"
            if layout.is_visible(line_h_small):
                draw_text(
                    surface,
                    font_small,
                    coord_label,
                    (layout.x, layout.screen_y()),
                    _UI_MUTED_TEXT_RGB,
                )
            layout.advance(line_gap)

            for row in tile_inspector_lines(info):
                rgb = (240, 160, 120) if row.kind == "notice" else _UI_TEXT_RGB
                if layout.is_visible(line_h_small):
                    draw_text(
                        surface,
                        font_small,
                        row.text,
                        (layout.x, layout.screen_y()),
                        rgb,
                    )
                layout.advance(line_gap)

            settlement_entity = settlements_by_coord.get(inspector_focus_coord)
            army_entity = armies_by_coord.get(inspector_focus_coord)
            btn_h = 38

            if info.settlement is not None:
                spoils_gold = raid_victory_gold_from_eco(info.settlement.eco)
                spoils = f"Raid Spoils: {spoils_gold}"
                if layout.is_visible(line_h_small):
                    draw_text(
                        surface,
                        font_small,
                        spoils,
                        (layout.x, layout.screen_y()),
                        _UI_MUTED_TEXT_RGB,
                    )
                layout.advance(line_gap)

                can_raid = False
                if settlement_entity is not None and not combat_busy and not game_over:
                    can_raid, _ = validate_settlement_raid(dragon, settlement_entity, game_map)

                raid_rect = pygame.Rect(
                    layout.x,
                    layout.screen_y(),
                    layout.inner_w,
                    btn_h,
                )
                if can_raid:
                    if layout.is_visible(btn_h):
                        draw_button(
                            surface,
                            font,
                            raid_rect,
                            "Raid",
                            hovered=raid_rect.collidepoint(mx, my),
                        )
                    raid_click_rect = raid_rect
                elif layout.is_visible(btn_h):
                    pygame.draw.rect(surface, _UI_INPUT_RGB, raid_rect, border_radius=6)
                    pygame.draw.rect(surface, _UI_BORDER_RGB, raid_rect, width=1, border_radius=6)
                    lbl = "Raid (busy…)" if combat_busy else "Raid (stand on settlement)"
                    label_surf = font_small.render(lbl, True, _UI_MUTED_TEXT_RGB)
                    surface.blit(
                        label_surf,
                        (
                            raid_rect.x + (raid_rect.w - label_surf.get_width()) // 2,
                            raid_rect.y + (raid_rect.h - label_surf.get_height()) // 2,
                        ),
                    )
                layout.advance(btn_h + 8)

            if army_entity is not None:
                destroy_gold = int(getattr(army_entity, "victory_gold", 0))
                destroy_payout = f"Destroy payout: {destroy_gold}"
                if layout.is_visible(line_h_small):
                    draw_text(
                        surface,
                        font_small,
                        destroy_payout,
                        (layout.x, layout.screen_y()),
                        _UI_MUTED_TEXT_RGB,
                    )
                layout.advance(line_gap)

                can_attack = False
                if not combat_busy and not game_over:
                    can_attack, _ = dragon_vs_army_allowed(dragon, army_entity)

                army_rect = pygame.Rect(
                    layout.x,
                    layout.screen_y(),
                    layout.inner_w,
                    btn_h,
                )
                if can_attack:
                    if layout.is_visible(btn_h):
                        draw_button(
                            surface,
                            font,
                            army_rect,
                            "Attack",
                            hovered=army_rect.collidepoint(mx, my),
                        )
                    army_attack_click_rect = army_rect
                elif layout.is_visible(btn_h):
                    pygame.draw.rect(surface, _UI_INPUT_RGB, army_rect, border_radius=6)
                    pygame.draw.rect(surface, _UI_BORDER_RGB, army_rect, width=1, border_radius=6)
                    lbl = "Attack (busy…)" if combat_busy else "Attack (stand on army)"
                    label_surf = font_small.render(lbl, True, _UI_MUTED_TEXT_RGB)
                    surface.blit(
                        label_surf,
                        (
                            army_rect.x + (army_rect.w - label_surf.get_width()) // 2,
                            army_rect.y + (army_rect.h - label_surf.get_height()) // 2,
                        ),
                    )
                layout.advance(btn_h + 8)

    layout.end(surface)
    return raid_click_rect, army_attack_click_rect, layout.content_height_total()

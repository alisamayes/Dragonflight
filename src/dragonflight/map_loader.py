"""JSON → ``GameMap`` loader with strict Pydantic v2 validation at the boundary.

This is the only place where untrusted map JSON is parsed and turned into the
simulation's source-of-truth ``GameMap`` (see ``map_state``). External-input
validation lives here per the Implementation Standards (Pydantic v2 at the
boundary) and the architectural decision that the rest of the codebase stays
Pydantic-agnostic.

Coordinate convention (round Wave-2-revision-1 amendment):

* The JSON's per-tile ``q`` is the **column** index.
* The JSON's per-tile ``r`` is the **row** index.
* Both are non-negative integers within ``[0, settings.width)`` and
  ``[0, settings.height)``.
* The loader builds :class:`~dragonflight.hex_coord.OffsetCoord` directly from
  these values; no axial conversion happens during load. Pathfinding and
  distance code that needs axial calls ``hex_coord.offset_to_axial`` itself.

Resolution rules (spec §5; ``Documentation/map-schema.md`` §5-§7):

1. ``hexType`` matching a recognised built-in (``grassland``, ``forest``,
   ``mountain``) maps directly to a ``Terrain`` value.
2. Otherwise, the value is looked up in the map's ``customHexTypes`` array;
   if found, the entry's ``name`` (case-insensitive) selects the terrain
   from the reserved-names allowlist (``Bridge``, ``Citadel``, ``Settlement``,
   ``River``).
3. Anything else (``ocean``, ``sea``, typos, unknown custom names) raises
   ``MapLoadError`` so authors notice — never silently coerce.

4. Settlement terrain may carry optional ``settlementType`` (``village`` /
   ``city`` / ``fort``); omitted means ``village``. Non-settlement tiles ignore
   a stray ``settlementType`` field.

Security posture (round Wave-2-revision-1, Security L1 fix): every numeric
field on the Pydantic boundary models has an explicit upper bound, and the
top-level ``hexes`` mapping is rejected up-front if it exceeds the
``width × height`` ceiling. This stops a malformed or hostile JSON file from
forcing the loader to materialise an unbounded number of objects.
"""

from __future__ import annotations

import json
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from .hex_coord import OffsetCoord
from .map_state import GameMap, Tile
from .settlement import SettlementType
from .terrain import Terrain

# --- Loader policy constants (no magic numbers in resolution code) ----------

#: Lowest schemaVersion supported by this loader. The Slice 1 vocabulary
#: (Bridge / Citadel / Settlement / River as customHexTypes; ocean retired)
#: was introduced at schemaVersion 3 — see Documentation/map-schema.md §10.
_MIN_SCHEMA_VERSION: int = 3

#: Upper bound on accepted ``schemaVersion``. Lower bound is enforced by the
#: explicit ``schemaVersion >= _MIN_SCHEMA_VERSION`` check below; the upper
#: bound is a defence-in-depth cap so a hostile JSON cannot smuggle an
#: unbounded integer through the Pydantic boundary. Bump deliberately when a
#: future genuine schema bump justifies it.
_MAX_SCHEMA_VERSION: int = 100

#: Slice 1 only supports flat-top axial maps; other orientations are rejected
#: at the boundary so simulation code can assume a single convention.
_SUPPORTED_ORIENTATION: str = "flat"

#: The loader only consumes the surface layer. Other layers (e.g. underdark)
#: are reserved by the editor and ignored by Dragonflight.
_SURFACE_LAYER: str = "surface"

#: Inclusive upper bound on ``settings.width`` / ``settings.height`` (in
#: hexes). 1000×1000 is far above any handcrafted MVP scope and well below
#: the ``_MAX_HEXES`` ceiling; it gives map authors plenty of headroom while
#: capping the worst-case allocation.
_MAX_MAP_DIMENSION: int = 1000

#: Inclusive upper bound on per-tile ``q`` / ``r`` in the JSON. Sized to
#: match ``_MAX_MAP_DIMENSION - 1`` so any value Pydantic accepts is at
#: least *plausible* relative to the map dimension caps. The loader does a
#: tighter, map-specific range check (``< settings.width`` /
#: ``< settings.height``) after Pydantic validation.
_MAX_TILE_INDEX: int = _MAX_MAP_DIMENSION - 1

#: Inclusive upper bound on ``settings.hexSize`` (pixels). Display-only
#: hint; capped to defend against absurd values (e.g. 1e308) that would
#: cause downstream pixel-math overflow in the renderer.
_MAX_HEX_SIZE: float = 1000.0

#: Inclusive upper bound on the number of entries in ``customHexTypes``.
#: The example map declares 4 entries; 64 is comfortably above any
#: plausible authoring need and bounds the resolution-table walk.
_MAX_CUSTOM_HEX_TYPES: int = 64

#: Inclusive upper bound on the number of entries in the top-level ``hexes``
#: mapping. Equals ``_MAX_MAP_DIMENSION ** 2`` — the largest tile count any
#: validly-bounded map can declare. We pre-check this before Pydantic
#: validation so a hostile multi-million-entry mapping is rejected before
#: paying the per-tile validation cost.
_MAX_HEXES: int = _MAX_MAP_DIMENSION * _MAX_MAP_DIMENSION

#: Built-in editor ``hexType`` strings that map straight to ``Terrain``.
#: Per the Architectural Lead's locked contract, this allowlist is exhaustive:
#: anything else (``ocean``, ``sea``, ``woodland``, …) must resolve via a
#: ``customHexTypes`` entry instead, or fail loudly.
_BUILT_IN_TERRAIN: dict[str, Terrain] = {
    "grassland": Terrain.GRASSLAND,
    "forest": Terrain.WOODLAND,
    "mountain": Terrain.MOUNTAIN,
}

#: ``customHexTypes`` ``name`` (lower-cased) → simulation ``Terrain``.
_CUSTOM_NAME_TO_TERRAIN: dict[str, Terrain] = {
    "bridge": Terrain.BRIDGE,
    "citadel": Terrain.CITADEL,
    "settlement": Terrain.SETTLEMENT,
    "river": Terrain.RIVER,
}

#: Per-tile ``settlementType`` JSON strings (lowercase) → enum (schema §3 extension).
_SETTLEMENT_TYPE_JSON: dict[str, SettlementType] = {
    "village": SettlementType.VILLAGE,
    "city": SettlementType.CITY,
    "fort": SettlementType.FORT,
}


class MapLoadError(ValueError):
    """Raised when a map file is unreadable, malformed, or fails Slice 1 rules.

    Subclassing ``ValueError`` lets callers either catch the specific type or
    fall back to ``ValueError`` semantics. Messages always identify the
    offending field / coordinate so authors can fix maps quickly.
    """


# --- Pydantic v2 boundary models --------------------------------------------
#
# These models exist solely to validate JSON shape at the loader boundary.
# They never leak past ``load_map`` — callers receive plain dataclasses
# (``GameMap`` / ``Tile``) so the rest of the code stays Pydantic-agnostic.
#
# ``extra='allow'`` keeps the loader forward-compatible with editor-only fields
# (``regions``, ``paths``, ``notes``, fog flags, ``edgeData``, etc.) that the
# runtime intentionally ignores per the schema doc.
#
# Numeric fields use ``Field(ge=..., le=...)`` to bound malformed or hostile
# input at parse time (Security L1 fix, round Wave-2-revision-1).


class _SettingsModel(BaseModel):
    model_config = ConfigDict(extra="allow")

    width: int = Field(ge=1, le=_MAX_MAP_DIMENSION)
    height: int = Field(ge=1, le=_MAX_MAP_DIMENSION)
    hexSize: float = Field(gt=0, le=_MAX_HEX_SIZE)
    orientation: str


class _HexModel(BaseModel):
    model_config = ConfigDict(extra="allow")

    q: int = Field(ge=0, le=_MAX_TILE_INDEX)
    r: int = Field(ge=0, le=_MAX_TILE_INDEX)
    layer: str
    hexType: str
    settlementType: str | None = None


class _CustomHexTypeModel(BaseModel):
    model_config = ConfigDict(extra="allow")

    id: str
    name: str
    color: str = ""


class _RawMapModel(BaseModel):
    model_config = ConfigDict(extra="allow")

    schemaVersion: int = Field(ge=_MIN_SCHEMA_VERSION, le=_MAX_SCHEMA_VERSION)
    settings: _SettingsModel
    hexes: dict[str, _HexModel]
    customHexTypes: list[_CustomHexTypeModel] = Field(max_length=_MAX_CUSTOM_HEX_TYPES)


# --- Public API -------------------------------------------------------------


def load_map(path: str | Path) -> GameMap:
    """Read ``path`` (a JSON map file) and return a validated ``GameMap``.

    Raises:
        MapLoadError: If the file is unreadable, not valid JSON, fails schema
            validation (including bounds violations on numeric fields),
            uses an unsupported schema version or orientation, references
            unknown ``hexType`` strings, declares more than
            ``_MAX_HEXES`` entries, has a tile coordinate outside
            ``[0, width) × [0, height)``, or has a surface tile count that
            disagrees with ``settings.width * settings.height``.
    """
    file_path = Path(path)

    try:
        raw_text = file_path.read_text(encoding="utf-8")
    except OSError as exc:
        raise MapLoadError(f"could not read map file {file_path}: {exc}") from exc

    try:
        raw_data = json.loads(raw_text)
    except json.JSONDecodeError as exc:
        raise MapLoadError(f"map file {file_path} is not valid JSON: {exc}") from exc

    # Pre-flight DoS guard: reject a hostile or malformed ``hexes`` mapping
    # before Pydantic walks every entry. Pydantic's ``max_length`` does not
    # apply to ``dict[str, X]`` field types in v2 the same way it does for
    # lists, so we enforce the cap explicitly here.
    if isinstance(raw_data, dict):
        raw_hexes = raw_data.get("hexes")
        if isinstance(raw_hexes, dict) and len(raw_hexes) > _MAX_HEXES:
            raise MapLoadError(
                f"map file {file_path} declares {len(raw_hexes)} hexes, "
                f"exceeds upper bound {_MAX_HEXES}"
            )

    try:
        model = _RawMapModel.model_validate(raw_data)
    except ValidationError as exc:
        raise MapLoadError(f"map file {file_path} failed schema validation: {exc}") from exc

    # ``schemaVersion`` falls inside ``[_MIN_SCHEMA_VERSION, _MAX_SCHEMA_VERSION]``
    # by construction (Pydantic Field bounds). We intentionally keep the explicit
    # lower-bound check here as well so the error message points map authors at
    # the supported range rather than the raw Pydantic ValidationError. Any
    # value below the minimum has already been rejected at validation time;
    # this branch is therefore unreachable but defensive.
    if model.schemaVersion < _MIN_SCHEMA_VERSION:  # pragma: no cover - defence in depth
        raise MapLoadError(
            f"unsupported schemaVersion {model.schemaVersion} in {file_path}; "
            f"Slice 1 requires schemaVersion >= {_MIN_SCHEMA_VERSION}"
        )

    settings = model.settings
    if settings.orientation != _SUPPORTED_ORIENTATION:
        raise MapLoadError(
            f"unsupported orientation {settings.orientation!r} in {file_path}; "
            f"Slice 1 only supports {_SUPPORTED_ORIENTATION!r}"
        )

    custom_by_id: dict[str, _CustomHexTypeModel] = {ct.id: ct for ct in model.customHexTypes}

    tiles: dict[OffsetCoord, Tile] = {}
    for key, hex_model in model.hexes.items():
        if hex_model.layer != _SURFACE_LAYER:
            continue
        col = hex_model.q
        row = hex_model.r
        if not (0 <= col < settings.width):
            raise MapLoadError(
                f"tile column {col} out of range [0, {settings.width}) "
                f"at ({col}, {row}) (key {key!r}) in {file_path}"
            )
        if not (0 <= row < settings.height):
            raise MapLoadError(
                f"tile row {row} out of range [0, {settings.height}) "
                f"at ({col}, {row}) (key {key!r}) in {file_path}"
            )
        coord = OffsetCoord(col=col, row=row)
        if coord in tiles:
            raise MapLoadError(
                f"duplicate surface tile at ({coord.col}, {coord.row}) "
                f"(conflicting key {key!r}) in {file_path}"
            )
        terrain = _resolve_terrain(hex_model.hexType, coord, custom_by_id)
        settlement_kind = _resolve_settlement_kind(
            terrain,
            hex_model.settlementType,
            coord,
        )
        tiles[coord] = Tile(coord=coord, terrain=terrain, settlement_kind=settlement_kind)

    expected = settings.width * settings.height
    if len(tiles) != expected:
        raise MapLoadError(
            f"surface tile count mismatch in {file_path}: got {len(tiles)} tiles, "
            f"expected width*height = {settings.width}*{settings.height} = {expected}"
        )

    return GameMap(
        width=settings.width,
        height=settings.height,
        hex_size=float(settings.hexSize),
        orientation=settings.orientation,
        tiles=tiles,
    )


# --- Internal helpers -------------------------------------------------------


def _resolve_settlement_kind(
    terrain: Terrain,
    settlement_type_raw: str | None,
    coord: OffsetCoord,
) -> SettlementType | None:
    """Return settlement subtype for ``SETTLEMENT`` tiles; ``None`` for other terrain."""

    if terrain is not Terrain.SETTLEMENT:
        if settlement_type_raw is not None:
            # Tolerate stray editor fields; gameplay ignores them.
            return None
        return None
    if settlement_type_raw is None:
        return SettlementType.VILLAGE
    key = settlement_type_raw.strip().casefold()
    kind = _SETTLEMENT_TYPE_JSON.get(key)
    if kind is None:
        allowed = ", ".join(sorted(_SETTLEMENT_TYPE_JSON))
        raise MapLoadError(
            f"invalid settlementType {settlement_type_raw!r} at tile ({coord.col}, {coord.row}); "
            f"allowed: {allowed}"
        )
    return kind


def _resolve_terrain(
    hex_type: str,
    coord: OffsetCoord,
    custom_by_id: dict[str, _CustomHexTypeModel],
) -> Terrain:
    """Resolve a tile's ``hexType`` string to a ``Terrain`` value.

    Implements the rule documented in this module's docstring (spec §5;
    ``map-schema.md`` §5-§7). Errors include the offending coordinate so
    map authors can find the bad tile fast.
    """
    if hex_type in _BUILT_IN_TERRAIN:
        return _BUILT_IN_TERRAIN[hex_type]

    custom = custom_by_id.get(hex_type)
    if custom is None:
        allowed_built_ins = ", ".join(sorted(_BUILT_IN_TERRAIN))
        raise MapLoadError(
            f"unknown hexType {hex_type!r} at tile ({coord.col}, {coord.row}); "
            f"allowed built-ins: {allowed_built_ins}; "
            f"custom hex types must be declared in customHexTypes"
        )

    name_key = custom.name.casefold()
    terrain = _CUSTOM_NAME_TO_TERRAIN.get(name_key)
    if terrain is None:
        allowed_names = ", ".join(sorted(_CUSTOM_NAME_TO_TERRAIN))
        raise MapLoadError(
            f"unknown custom hex type name {custom.name!r} (id={custom.id!r}) "
            f"at tile ({coord.col}, {coord.row}); allowed reserved names: {allowed_names}"
        )
    return terrain

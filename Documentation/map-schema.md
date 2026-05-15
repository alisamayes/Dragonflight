# Dragonflight Map Schema

This document describes the JSON schema used by Dragonflight map data files (e.g.
`assets/example_hexmap.json`). It is the authority for the loader and any tool
that consumes or produces map data. It also lists the conventions Dragonflight
uses to translate the editor's vocabulary into the gameplay `Terrain` enum.

- **Schema version:** 3 (Slice 1)
- **Coordinate system:** **odd-q flat-top offset** coordinates `(q = column, r = row)` in JSON; the simulation derives axial via `dragonflight.hex_coord.offset_to_axial` (see §3 and §8). `settings.orientation = "flat"`.
- **Status:** handcrafted MVP map only; procedural generation is out of scope for this slice

## 1. Top-level keys

The map file is a single JSON object with the following keys.

| Key | Type | Required | Notes |
| --- | --- | --- | --- |
| `id` | string (UUID) | yes | Stable map identifier. Do not regenerate when editing existing maps. |
| `name` | string | yes | Human-readable map name. The example map is currently `"Dev Map"`. |
| `description` | string | yes | Free-text description. May be empty. |
| `ownerId` | string \| null | yes | Reserved for future ownership tracking. `null` for handcrafted MVP maps. |
| `settings` | object | yes | Map-wide settings (see §2). |
| `hexes` | object | yes | Map of tile-key → tile object (see §3). |
| `regions` | array | yes | Editor-only region definitions. Currently empty. Loader ignores. |
| `paths` | array | yes | Editor-only path overlays. Currently empty. Loader ignores. |
| `notes` | array | yes | Editor-only annotations. Currently empty. Loader ignores. |
| `customHexTypes` | array | yes | Project-specific hex type definitions (see §4). |
| `activeLayer` | string | yes | Editor's active layer. The MVP loader only consumes the `surface` layer. |
| `schemaVersion` | integer | yes | Schema generation. Currently `3`. Bump when the vocabulary changes (renames, new reserved names). |
| `createdAt` | ISO 8601 timestamp | yes | Creation time, UTC. Never overwritten by edits. |
| `updatedAt` | ISO 8601 timestamp | yes | Updated on every save, UTC, millisecond precision (e.g. `2026-05-08T14:50:17.507Z`). |

## 2. `settings` object

```jsonc
{
  "width": 30,            // map width in hex columns (q-axis)
  "height": 30,           // map height in hex rows (r-axis)
  "hexSize": 30,          // editor pixel hex radius; informational only for the runtime
  "orientation": "flat",  // hex orientation; only "flat" is supported in MVP
  "showGrid": true,       // editor display toggles below — runtime ignores
  "showLabels": false,
  "showCoordinates": false,
  "showBiomeBleed": true,
  "fogEnabled": false,
  "fogDistance": 2,
  "underdarkEnabled": false
}
```

The runtime only consumes `width`, `height`, and `orientation`. Other keys are
editor display preferences and are tolerated but ignored. The aggression
nearby-radius default of 30% of map width (per spec §6 dev tweak) uses `settings.width`
as the reference dimension.

## 3. `hexes` map and per-tile shape

`hexes` is an object whose keys are stringified `"q,r,layer"` triples (e.g.
`"16,16,surface"`). The MVP runtime only consumes tiles where
`layer == "surface"`.

Per-tile fields:

| Field | Type | Required | Notes |
| --- | --- | --- | --- |
| `q` | integer | yes | **Column index** in odd-q flat-top **offset** coordinates (despite the historical `q` letter). See coordinate note below and §8. |
| `r` | integer | yes | **Row index** in odd-q flat-top **offset** coordinates. |
| `layer` | string | yes | `"surface"` for all MVP tiles. Other layers (e.g. `"underdark"`) are reserved and ignored by the loader. |
| `hexType` | string | yes | Either a built-in name (see §5) or a custom-type `id` matching an entry in `customHexTypes`. |
| `fogState` | string | yes | Editor-side fog state. Always `"visible"` in MVP because fog of war is out of scope (spec §4). |
| `edgeData` | object | yes | Reserved for per-edge attributes (e.g. cliffs, river segments). Currently `{}`. |
| `connections` | array | yes | Reserved for explicit graph edges (rare overrides). Currently `[]`. |
| `customColor` | string (hex) | optional | Present on tiles whose `hexType` is a custom type, mirroring the type's `color`. Used by the renderer when a tile carries a custom hex type so colour state survives editor moves. |
| `settlementType` | string | optional | Only on **Settlement** terrain (`hexType` resolving to the Settlement custom type). One of `village`, `city`, `fort` (case-insensitive). If omitted, the loader treats the tile as a **village**. Non-settlement tiles may omit this field; if present on other terrain, the loader ignores it. |

### Coordinate semantics of `q` and `r`

The JSON's `(q, r)` keys are **odd-q flat-top offset** coordinates, not axial:

- `q` is the **column index** (0-based, increases rightward).
- `r` is the **row index** (0-based, increases downward).
- Even columns (`q % 2 == 0`) sit at the row baseline.
- Odd columns (`q % 2 == 1`) are visually shifted **down** by half a hex height (i.e. odd-q "low" offset, the bundled map editor's default for flat-top hexes).

This is the convention used by the bundled map editor and is what the
Dragonflight loader maps **directly** to
`dragonflight.hex_coord.OffsetCoord(col=q, row=r)`. The loader does **not**
treat `(q, r)` as axial coordinates; doing so caused the rendered map to look
like a rhombus instead of a square in earlier slices.

The simulation-side **axial** coordinates (used for distance, neighbour, and
future A* pathfinding math per spec §4 and §14) are derived from the offset
values via `dragonflight.hex_coord.offset_to_axial` using the odd-q formula:

```text
axial.q = col
axial.r = row - (col - (col & 1)) // 2
```

In the inverse direction (axial → offset), the loader uses the corresponding
`axial_to_offset` helper. All hex math happens on the axial representation
inside the simulation; the offset representation is a JSON / editor / renderer
concern only.

## 4. `customHexTypes`

Project-specific hex types live in this array. Each entry is:

```jsonc
{
  "id": "custom-river-0001",
  "name": "River",
  "color": "#3a7bd5"
}
```

`id` is the string referenced by tile `hexType`. The `custom-` prefix is the
established convention; it is recommended but not enforced. `name` is the
human-readable label and the basis for Dragonflight's reserved-name resolution
(see §6).

Current `customHexTypes` in the example map (Slice 1):

| `id` | `name` | `color` | Maps to (Dragonflight `Terrain`) |
| --- | --- | --- | --- |
| `custom-fe6e3b0a` | `Bridge` | `#8B4513` | `BRIDGE` |
| `custom-0d9e6285` | `Citadel` | `#e31616` | `CITADEL` |
| `custom-5c5b120e` | `Settlement` | `#fff705` | `SETTLEMENT` |
| `custom-river-0001` | `River` | `#3a7bd5` | `RIVER` |

## 5. Built-in `hexType` values

Built-ins originate from the editor and are not declared in `customHexTypes`.
The loader recognises:

| Built-in | Maps to (Dragonflight `Terrain`) | Notes |
| --- | --- | --- |
| `grassland` | `GRASSLAND` | Default, no movement modifiers. |
| `mountain` | `MOUNTAIN` | Impassable to armies (spec §5). |
| `forest` | `WOODLAND` | The loader maps `forest` → `Terrain.WOODLAND`. Armies move slower on Woodland and take additional dragon damage (spec §5). The editor's built-in name is `forest`; Dragonflight's spec name is `woodland`. This is the canonical built-in vocabulary for Woodland tiles in Slice 1, and the example map's 180 `forest` tiles are recognised through this rule (no JSON change needed). The string `woodland` itself is **not** accepted as a `hexType` value — only the editor name `forest` resolves to `WOODLAND`. |
| `ocean` | _retired_ | Slice 1 retyped all `ocean` tiles to the new `River` custom type; the loader rejects `ocean` at schema version ≥ 3 with a clear error. |
| `sea` | _not recognised_ | Not a Dragonflight vocabulary term. The example map no longer contains any `sea` tiles (the 3 originally present were retyped to `River` in the Slice 1 round-1 revision). The loader fails map load with a clear error if it encounters `sea` (see §6, §7 — unknown vocabulary is fail-loud, not silently coerced). |

## 6. `hexType` resolution rule

The loader resolves a tile's `hexType` to a `Terrain` enum value as follows:

1. If the value matches a recognised built-in name in §5 (`grassland`,
   `mountain`, `forest`), use the mapping there.
2. Otherwise, look up an entry in `customHexTypes` whose `id` equals the value.
   - If found, resolve by the entry's `name`:
     - `Bridge` → `BRIDGE`
     - `Citadel` → `CITADEL`
     - `Settlement` → `SETTLEMENT`
     - `River` → `RIVER`
     - Anything else → unknown; **fail map load with a clear error** so
       authors notice unrecognised vocabulary (do not silently coerce).
3. If the value is neither a recognised built-in nor a known custom-type `id`
   (this catches values like `ocean`, `sea`, or any typo), treat as malformed
   input and **fail map load with a clear error**.

This means **custom-type `id`s are stable identifiers, but the gameplay
meaning is keyed off `name`**. Renaming a custom type therefore changes its
gameplay role — Slice 1's `Village` → `Settlement` rename is exactly such a
change, with no tile reassignments needed.

## 7. Reserved `customHexTypes` names

The following `name` values are reserved and have gameplay meaning:

- `Bridge` → `BRIDGE` — allows armies to cross adjacent `River` tiles (spec §5).
- `Citadel` → `CITADEL` — the dragon's home base; failure condition tile (spec §10).
- `Settlement` → `SETTLEMENT` — settlement tile. Subtype is set per-hex via optional `settlementType` (`village` \| `city` \| `fort`); see §3.
- `River` → `RIVER` — impassable to armies except via `Bridge` tiles (spec §5).

Names not listed above are unknown; the loader **fails map load** with a clear
error rather than silently coercing the tile (e.g. to `GRASSLAND`). Adding a
reserved name is a schema change and must bump `schemaVersion`.

## 8. Coordinate system

- **JSON storage:** odd-q flat-top **offset** coordinates `(q = column, r = row)`
  on every tile. See §3 for the precise definition (even columns at baseline,
  odd columns shifted down by half a hex height).
- **Hex orientation:** flat-top, per `settings.orientation = "flat"`.
- **Simulation math (neighbours, distance, A* pathfinding per spec §4 and §14):**
  uses **axial** coordinates derived from the offset values via
  `dragonflight.hex_coord.offset_to_axial` (`axial.q = col`,
  `axial.r = row - (col - (col & 1)) // 2`). The inverse helper is
  `axial_to_offset`. All rule code consumes axial; only the loader, the JSON
  on disk, and the renderer touch offset.
- **Why both representations:** offset coordinates match the editor's grid
  layout (rectangular bounding box, rows and columns) and render as a square;
  axial coordinates make hex distance and neighbour math cheap and symmetric.
  Treating offset values as axial makes a square map render as a rhombus —
  this regression was the trigger for clarifying these semantics in v3
  round 2.

## 9. Design intent of the example map (Slice 1)

- **Map name:** `"Dev Map"` (used as the developer-facing scenario; not a
  shipping scenario name).
- **Coordinate convention used in this section:** all `q,r` positions below
  are **offset** (column, row) per §3 / §8.

The example map is a 30×30 surface-layer scenario tuned to exercise:

- **Reachability variety:** multiple `Settlement` clusters spread across the
  map (offset corners and centre) so future army pathfinders have non-trivial
  routes.
- **River + bridge interaction:** a band of `River` tiles bisecting parts of
  the map, with **4 `Bridge` tiles** placed as the only legal army crossings
  (at offset `(q, r)` = `(6, 5)`, `(7, 5)`, `(6, 18)`, `(25, 21)`).
- **Single citadel:** the dragon's home at offset `(q, r) = (16, 16)`, roughly
  central, so no settlement is more than ~half-map away.
- **Mountain belts:** 61 `mountain` tiles forming impassable terrain to test
  army detours.
- **Mixed terrain backdrop:** 539 `grassland` and 180 `forest` tiles so the
  Woodland speed/damage modifiers (spec §5) have surfaces to act on once
  army movement and combat are wired up.

Slice 1 only tests "see the map" — load, parse, and render. Reachability and
balance validation are deliberately deferred until armies and pathfinding land.

## 10. Schema version history

- **v1:** initial editor export. Pre-Dragonflight.
- **v2:** custom hex types `Bridge`, `Citadel`, `Village` introduced. Used by
  the example map prior to Slice 1.
- **v3 (current):** Slice 1.
  - `Village` (custom-5c5b120e) renamed to `Settlement`.
  - New custom type `River` (`custom-river-0001`, `#3a7bd5`) added.
  - All `ocean` tiles retyped to `River` and gained `customColor: #3a7bd5`.
  - Reserved-names contract documented (Bridge / Citadel / Settlement / River).
  - Round-1 revision (data-only, schemaVersion unchanged): the 3 remaining
    `sea` tiles at `(4, 26)`, `(8, 27)`, `(23, 27)` were retyped to the
    `River` custom type with `customColor: #3a7bd5`. The example map now
    contains 0 unknown-vocabulary tiles. The unknown-vocab policy was also
    tightened from "warn and fall back to GRASSLAND" to "fail map load with
    a clear error" (see §5-§7).
  - Round-2 revision (data-light, schemaVersion unchanged): the example map's
    `name` was changed from `"Untitled Map"` to `"Dev Map"`. The schema doc
    was updated to clarify that JSON `(q, r)` are **odd-q flat-top offset**
    coordinates `(column, row)`, not axial — the loader maps them directly
    to `OffsetCoord(col=q, row=r)` and converts to axial via
    `offset_to_axial` for simulation math (see §3, §8). No tile data was
    changed; this round corrects a coordinate-semantics misunderstanding
    that caused the rendered map to look like a rhombus instead of a
    square.

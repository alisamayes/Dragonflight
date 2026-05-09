# Dragonflight

Turn-based dragon raiding strategy game (MVP, Python + Pygame).

## Status / scope

Current development slice is **Slice 1 — "See the map"**: a Pygame window
parses the bundled example map and renders it as flat-top coloured hexes. No
gameplay rules (movement, combat, economy) are wired up yet.

For the full design, see
[`Documentation/Dragonflight Specification and MVP.md`](Documentation/Dragonflight%20Specification%20and%20MVP.md).

## Project layout

| Path | Contents |
| --- | --- |
| `src/dragonflight/` | The `dragonflight` package: hex math, terrain enum, map state, JSON loader, renderer, and the `python -m dragonflight` entry point. |
| `assets/` | Map data files. Currently holds `example_hexmap.json`. |
| `tests/` | Pytest suite (loader, hex math, render sizing). |
| `Documentation/` | Spec and schema docs. |
| `scripts/` | Windows dev helpers (`Setup-DragonflightDev.ps1`, `Open-DragonflightDev.cmd`). |
| `dragonflight.py` | Top-level shim so `python dragonflight.py` works as well as `python -m dragonflight`. |
| `DevShell.ps1` | Dot-sourced PowerShell helper that activates the project venv in the current session. |

## Requirements

- Python 3.11, 3.12, or 3.13 (Pygame ships wheels for these; 3.14+ is intentionally not supported yet).
- [Pygame](https://www.pygame.org/) 2.5+.
- [Pydantic](https://docs.pydantic.dev/) 2.x (used for strict map JSON validation at the loader boundary).

## Setup (Windows / PowerShell)

First-time setup creates a `.venv` and installs the project plus dev tools in editable mode:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\Setup-DragonflightDev.ps1
```

For each new shell, dot-source the dev shell helper from the project root so
the venv stays active in your prompt:

```powershell
. .\DevShell.ps1
```

If you prefer a non-PowerShell prompt, double-click `scripts\Open-DragonflightDev.cmd`
to launch a `cmd.exe` shell with the venv activated.

## Run the demo

Either entry point works — pick whichever feels natural:

```powershell
python -m dragonflight
```

```powershell
python dragonflight.py
```

The demo opens a window that draws the bundled example map
(`assets/example_hexmap.json`) once as flat-top coloured hexes. It does no
animation or simulation. Quit by pressing `ESC` or closing the window.

## Tests + quality gates

Run from the project root with the venv active:

```powershell
ruff format .
ruff check .
mypy src/dragonflight tests
pytest -q
```

The default `pytest -q` run stays headless. There is one opt-in render
integration test that opens an SDL "dummy" surface; enable it by setting
`DRAGONFLIGHT_GUI_TESTS=1` before running pytest.

## Map data

The shipped scenario is `assets/example_hexmap.json`, a 30×30 surface-layer
map at flat-top axial coordinates `(q, r)`. The full schema (top-level keys,
per-tile fields, built-in vs. custom hex-type resolution, reserved names,
schema-version history) lives in
[`Documentation/map-schema.md`](Documentation/map-schema.md).

The loader requires `schemaVersion >= 3` — earlier versions are rejected with
a clear error rather than silently coerced.

## Documentation index

- [`Documentation/Dragonflight Specification and MVP.md`](Documentation/Dragonflight%20Specification%20and%20MVP.md) — authoritative game design spec.
- [`Documentation/map-schema.md`](Documentation/map-schema.md) — map JSON schema, terrain resolution rules, schema-version history.

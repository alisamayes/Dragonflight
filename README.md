# Dragonflight

Turn-based dragon raiding strategy game (MVP, Python + Pygame).

## Status / scope

The default client (`python -m dragonflight`) is an interactive **movement
playtest**: main menu, map and dragon selection, then a three-column session
with dragon movement, combat previews, settlements, and related prototype
systems. A static map-only preview remains available via
`render.run_demo` (see package docs).

For the full design, see
[`Documentation/Dragonflight Specification and MVP.md`](Documentation/Dragonflight%20Specification%20and%20MVP.md).

## Project layout

| Path | Contents |
| --- | --- |
| `src/dragonflight/` | The `dragonflight` package: hex math, map/simulation modules, JSON loader, renderer, map viewport camera (`map_camera`), movement playtest UI, and the `python -m dragonflight` entry point. |
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

## Run the client

Either entry point works — pick whichever feels natural:

```powershell
python -m dragonflight
```

```powershell
python dragonflight.py
```

This opens the main menu, then new-game map and dragon selection, then the
movement playtest. Quit with `ESC` or by closing the window.

### Map viewport controls (playtest)

While in an active game session, the **central map column** supports:

| Input | Effect |
| --- | --- |
| **Mouse wheel** (over the map) | Zoom between **1×** (entire map fits) and **3×**; zoom stays anchored under the cursor. At 1×, pan resets and the map is centered. |
| **WASD** or **arrow keys** | Pan the map when zoomed past 1× (no effect at full fit). |

Implementation: `src/dragonflight/map_camera.py`, wired from `movement_playtest.py`.

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

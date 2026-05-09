"""Top-level entry shim so users can run ``python dragonflight.py``.

Forwards to :func:`dragonflight.__main__.main`, the canonical entry point also
exposed by ``python -m dragonflight`` and the ``dragonflight`` console script
(see ``pyproject.toml``'s ``[project.scripts]``).

Why the import indirection
--------------------------
Running ``python dragonflight.py`` puts the project root at ``sys.path[0]``,
and pytest's default import mode also prepends the project root to
``sys.path`` for test discovery. Either way, a plain ``from
dragonflight.__main__ import main`` would resolve ``dragonflight`` to **this
file** (a single ``.py`` module) instead of the ``dragonflight`` package in
``src/``, which would then break submodule lookups such as
``dragonflight.hex_coord`` (the shim has no ``__path__``).

To honour the brief's "must NOT shadow the package" rule, this shim eagerly
loads the real package via ``importlib.util`` and registers it as
``sys.modules['dragonflight']`` *during its own import*. CPython's import
machinery then returns the registered package — not this shim — to whoever
imported ``dragonflight``. Subsequent ``from dragonflight.X import Y``
statements (in this file's ``__main__`` block, in pytest test modules, or in
ad-hoc REPL sessions started from the project root) all see the real package.

If the editable install (``pip install -e .``) provides ``dragonflight``
without ``src/dragonflight/__init__.py`` present on disk, the redirect is a
no-op and Python falls back to its usual resolution order.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent
_PACKAGE_INIT = _HERE / "src" / "dragonflight" / "__init__.py"


def _load_real_package() -> None:
    """Register the real ``dragonflight`` package as ``sys.modules['dragonflight']``.

    Idempotent: if a proper package (one with ``__path__``) is already loaded
    under that name, this is a no-op so we don't double-execute its
    ``__init__``. If ``src/dragonflight/__init__.py`` is missing (e.g. running
    against an installed wheel rather than the source checkout) we let the
    normal import machinery handle resolution and surface its own errors.
    """
    existing = sys.modules.get("dragonflight")
    if existing is not None and getattr(existing, "__path__", None):
        return
    if not _PACKAGE_INIT.exists():
        return

    spec = importlib.util.spec_from_file_location(
        "dragonflight",
        _PACKAGE_INIT,
        submodule_search_locations=[str(_PACKAGE_INIT.parent)],
    )
    if spec is None or spec.loader is None:
        return

    package = importlib.util.module_from_spec(spec)
    sys.modules["dragonflight"] = package
    spec.loader.exec_module(package)


_load_real_package()


if __name__ == "__main__":
    from dragonflight.__main__ import main

    main()

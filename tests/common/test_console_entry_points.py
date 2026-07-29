"""Regression tests for [project.scripts] console entry points.

Covers discogsography-cu2.88: dashboard and explore declared their console script as
`pkg:main` (e.g. `dashboard:main`), but with `packages = ["."]` the importable package
is the directory's `__init__.py`, which never re-exports `main` — the real `main()`
lives in the submodule (`dashboard.dashboard`, `explore.explore`). The generated
console command therefore crashed with AttributeError on invocation. This resolves the
declared entry point exactly as importlib.metadata's EntryPoint.load() would, without
actually invoking main() (which starts a uvicorn server).
"""

from pathlib import Path
import tomllib

import pytest


REPO_ROOT = Path(__file__).resolve().parents[2]


def _entry_points(pyproject_path: Path) -> dict[str, str]:
    with pyproject_path.open("rb") as f:
        data = tomllib.load(f)
    scripts: dict[str, str] = data["project"]["scripts"]
    return scripts


@pytest.mark.parametrize(
    ("pyproject_relpath", "script_name"),
    [
        ("dashboard/pyproject.toml", "dashboard"),
        ("explore/pyproject.toml", "explore"),
    ],
)
def test_console_script_entry_point_resolves(pyproject_relpath: str, script_name: str) -> None:
    """The declared `module:attr` entry point must import cleanly and expose a callable."""
    entry_points = _entry_points(REPO_ROOT / pyproject_relpath)
    assert script_name in entry_points

    module_path, _, attr = entry_points[script_name].partition(":")
    assert module_path and attr, f"entry point {entry_points[script_name]!r} is not in 'module:attr' form"

    # Same resolution importlib.metadata.EntryPoint.load() performs: import the target
    # module, then getattr() the callable — this is exactly what crashed before the fix
    # (the entry point named the package, whose __init__.py never re-exports `main`).
    import importlib

    module = importlib.import_module(module_path)
    target = getattr(module, attr)
    assert callable(target)


def test_dashboard_entry_point_names_the_submodule() -> None:
    """Regression: must not regress to `dashboard:main` (package __init__, no `main`)."""
    entry_points = _entry_points(REPO_ROOT / "dashboard" / "pyproject.toml")
    assert entry_points["dashboard"] == "dashboard.dashboard:main"


def test_explore_entry_point_names_the_submodule() -> None:
    """Regression: must not regress to `explore:main` (package __init__, no `main`)."""
    entry_points = _entry_points(REPO_ROOT / "explore" / "pyproject.toml")
    assert entry_points["explore"] == "explore.explore:main"

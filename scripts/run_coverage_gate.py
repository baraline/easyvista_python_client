#!/usr/bin/env python
"""Run the unit suite under coverage and enforce the 95% floor.

This is the pre-push half of the coverage gate; the other half is the
``coverage`` job in ``.github/workflows/ci.yml``. Both assert the same floor as
``[tool.coverage.report] fail_under`` in ``pyproject.toml``.

Why a launcher instead of putting the pytest command straight in
``.pre-commit-config.yaml``: that command has to run in the environment where
``pip install -e ".[dev]"`` happened, because coverage of a package that is not
the one under test is meaningless. The obvious spelling -- ``language: system``
with ``entry: python -m pytest ...`` -- resolves a bare ``python`` from ``PATH``,
which on Windows is commonly the Microsoft Store stub, and the hook dies with
exit 9009 and a "Python est introuvable" message unless the developer happened
to run ``git push`` from an activated virtualenv. Measured, not hypothetical: it
is what this repository's own machine does.

So the hook is ``language: python`` instead, which hands this script a
pre-commit-managed interpreter bootstrapped from whatever ran ``pre-commit``
itself -- never a ``PATH`` lookup -- and the script then finds the project's
interpreter explicitly. It imports only the standard library, so that managed
venv needs no ``additional_dependencies``.

Usage::

    python scripts/run_coverage_gate.py

Exits with pytest's own status, so an under-covered push fails the way a broken
test does.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

#: Kept in step with `--cov-fail-under` in the CI coverage job and with
#: `[tool.coverage.report] fail_under`. The duplication is deliberate -- see the
#: comment on that job -- but all three must move together.
FAIL_UNDER = "95"

#: `integration_tests/` calls a real EasyVista instance and creates and closes
#: real tickets. Deselecting it here matches CI and keeps a developer who has
#: credentials on disk from writing to a live instance on every push.
PYTEST_ARGS = [
    "-m",
    "not integration",
    "--cov=easyvista_python_client",
    f"--cov-fail-under={FAIL_UNDER}",
    "-q",
]


def _interpreter_candidates() -> list[Path]:
    """Return interpreters that might have the project's dev install, best first.

    ``.venv`` comes first because it is what ``CONTRIBUTING.md`` tells a
    contributor to create. ``VIRTUAL_ENV`` covers a differently-named or
    out-of-tree environment. ``sys.executable`` is last and normally loses: under
    ``language: python`` it is pre-commit's own managed venv, which has no
    pytest -- it is here for the case where this script is run directly from an
    already-correct interpreter.
    """
    roots = [REPO_ROOT / ".venv"]
    virtual_env = os.environ.get("VIRTUAL_ENV")
    if virtual_env:
        roots.append(Path(virtual_env))

    candidates: list[Path] = []
    for root in roots:
        for rel in ("Scripts/python.exe", "bin/python"):
            candidate = root / rel
            if candidate.is_file() and candidate not in candidates:
                candidates.append(candidate)
    running = Path(sys.executable)
    if running not in candidates:
        candidates.append(running)
    return candidates


def _can_run_the_suite(interpreter: Path) -> bool:
    """Report whether ``interpreter`` has both pytest-cov and the package itself.

    Both halves matter. pytest without ``pytest_cov`` would run the suite and
    silently skip the gate this script exists to enforce, and an interpreter
    without ``easyvista_python_client`` is not the dev install -- measuring it
    would report on a tree nobody edited.
    """
    probe = subprocess.run(
        [
            str(interpreter),
            "-c",
            "import pytest, pytest_cov, easyvista_python_client",
        ],
        cwd=REPO_ROOT,
        capture_output=True,
    )
    return probe.returncode == 0


def main() -> int:
    """Run the gated suite in the project's environment; return its exit code."""
    tried = _interpreter_candidates()
    for interpreter in tried:
        if _can_run_the_suite(interpreter):
            return subprocess.call(
                [str(interpreter), "-m", "pytest", *PYTEST_ARGS],
                cwd=REPO_ROOT,
            )

    print(
        "Could not find an interpreter with the project's dev dependencies "
        "installed, so the coverage gate did not run. Tried:\n  "
        + "\n  ".join(str(path) for path in tried)
        + "\n\nCreate the environment CONTRIBUTING.md describes:\n"
        "  python -m venv .venv\n"
        '  .venv\\Scripts\\python.exe -m pip install -e ".[dev]"',
        file=sys.stderr,
    )
    return 1


if __name__ == "__main__":
    raise SystemExit(main())

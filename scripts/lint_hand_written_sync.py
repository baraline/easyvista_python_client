#!/usr/bin/env python
"""Format and lint the hand-written twins inside the generated ``_sync/`` tree.

``easyvista_python_client/_sync/`` as a whole is excluded from ruff (see
``[tool.ruff] extend-exclude`` in ``pyproject.toml``) because it is generated
from ``_async/`` by :mod:`unasync_build`, and the formatter would otherwise
fight the generator forever. But two files under that tree are hand-written
on *both* sides -- ``_concurrency.py`` and ``tests/test_concurrency.py``,
named in :data:`unasync_build.HAND_WRITTEN` -- and a directory-wide exclusion
skips them too, so nothing has ever formatted or linted them.

This script runs ``ruff format`` and ``ruff check`` on exactly those paths,
with ``--no-force-exclude`` so the directory-wide exclusion above does not
apply to paths named explicitly on the command line. It reads the path list
from ``unasync_build.HAND_WRITTEN`` itself rather than hardcoding it, so it
stays correct if that set ever changes.

Usage::

    python scripts/lint_hand_written_sync.py           format and lint in place
    python scripts/lint_hand_written_sync.py --check    report only, write nothing

``--check`` exists so this can run in CI. Without it the script calls
``ruff format``, which *writes*, and a CI job that silently reformats the
tree it is auditing would report success on files it had just fixed.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from unasync_build import HAND_WRITTEN, SYNC_DIR  # noqa: E402


def main() -> int:
    """Format and lint the hand-written ``_sync/`` twins; return the exit code."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--check",
        action="store_true",
        help="report formatting and lint problems instead of fixing them",
    )
    args = parser.parse_args()

    paths = [str(SYNC_DIR / rel) for rel in sorted(HAND_WRITTEN)]
    missing = [p for p in paths if not Path(p).is_file()]
    if missing:
        print(
            f"hand-written twin(s) named in HAND_WRITTEN not found on disk: {missing}",
            file=sys.stderr,
        )
        return 1

    format_args = ["format", "--no-force-exclude"]
    if args.check:
        format_args.append("--check")
    fmt = subprocess.call([sys.executable, "-m", "ruff", *format_args, *paths])
    chk = subprocess.call(
        [sys.executable, "-m", "ruff", "check", "--no-force-exclude", *paths]
    )
    if (fmt or chk) and args.check:
        print(
            "\nThe hand-written twins under _sync/ are excluded from the "
            "repo-wide ruff run, so this script is the only thing that checks "
            "them. Fix with: python scripts/lint_hand_written_sync.py",
            file=sys.stderr,
        )
    return fmt or chk


if __name__ == "__main__":
    raise SystemExit(main())

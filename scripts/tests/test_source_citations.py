"""No tracked file may cite a gitignored path.

The sibling guard in ``test_skills_contract.py`` enforces this for
``skills/*/SKILL.md``. It does not read Python sources, which is exactly how
three shipped docstrings came to cite ``docs/API_Info.md`` -- a gitignored,
instance-private handover note -- as though it were the vendor specification.
For every reader who has only the published repository those are dead links.

Keep ``_UNPUBLISHED`` here in sync with the tuple of the same name in
``scripts/tests/test_skills_contract.py``. The duplication is deliberate: the
two modules are imported independently by pytest and sharing a constant
between them would mean relying on ``scripts/tests`` landing on ``sys.path``.
"""

from __future__ import annotations

from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]

# A NARROWER list than the sibling guard's, and deliberately so. This one
# forbids citing a gitignored *document as evidence*; it does not forbid
# naming a gitignored *location as an instruction*.
#
# `secrets/`, `.claude/` and `.superpowers/` are therefore absent. Tracked
# documentation must be free to name them: CONTRIBUTING.md tells contributors
# to put credentials under `secrets/`, docs/development.rst documents the
# resolution order, and scripts/tests/test_credential_rename_guard.py asserts
# on `secrets/` filenames as its whole subject. Forbidding those would delete
# correct instructions, which is the opposite of this guard's purpose.
_UNPUBLISHED = (
    "API_Info.md",
    "easyvista-field-inventory.md",
    "easyvista-test-profile-blocked-operations.md",
    "docs/superpowers",
    "scripts/probe_",
)

# The two guard modules quote every needle literally, so they can never be
# their own subjects. generate_field_inventory.py names
# docs/easyvista-field-inventory.md because it WRITES that file -- a generator
# naming its own output path is correct, not a dead citation.
_SELF_EXEMPT = {
    "test_source_citations.py",
    "test_skills_contract.py",
    "generate_field_inventory.py",
}


def _tracked_text_files() -> list[Path]:
    """Every tracked file whose prose a public reader can open."""
    found: list[Path] = []
    for pattern in ("easyvista_python_client/**/*.py", "docs/*.rst"):
        found.extend(REPO_ROOT.glob(pattern))
    for name in ("README.md", "CONTRIBUTING.md", "CHANGELOG.md"):
        path = REPO_ROOT / name
        if path.is_file():
            found.append(path)
    # scripts/probe_*.py is gitignored as a glob; everything else under
    # scripts/ is tracked.
    for path in REPO_ROOT.glob("scripts/**/*.py"):
        if not path.name.startswith("probe_"):
            found.append(path)
    return sorted(p for p in found if p.name not in _SELF_EXEMPT)


def _ids() -> list[str]:
    return [p.relative_to(REPO_ROOT).as_posix() for p in _tracked_text_files()]


@pytest.mark.parametrize("path", _tracked_text_files(), ids=_ids())
def test_no_gitignored_citations(path: Path) -> None:
    text = path.read_text(encoding="utf-8")
    for needle in _UNPUBLISHED:
        assert needle not in text, (
            f"{path.relative_to(REPO_ROOT).as_posix()} references {needle!r}, "
            "which is gitignored and invisible to anyone reading the published "
            "repository. Cite docs/vendor-api-reference.md instead."
        )

"""No tracked file may cite a gitignored path.

The sibling guard in ``test_skills_contract.py`` enforces this for
``skills/*/SKILL.md``. It does not read Python sources, which is exactly how
three shipped docstrings came to cite ``docs/API_Info.md`` -- a gitignored,
instance-private handover note -- as though it were the vendor specification.
For every reader who has only the published repository those are dead links.

``_UNPUBLISHED`` here is deliberately **narrower** than the tuple of the same
name in ``scripts/tests/test_skills_contract.py`` -- see the comment on the
tuple itself for which entries are missing and why. Keep the two in sync only
*where they overlap*: a path added to the sibling because it became gitignored
belongs here too, but the entries this one omits must stay omitted, because
adding them would fail tracked documentation that names those locations as
instructions. The duplication is deliberate: the two modules are imported
independently by pytest and sharing a constant between them would mean relying
on ``scripts/tests`` landing on ``sys.path``.
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
    for pattern in (
        "easyvista_python_client/**/*.py",
        "docs/*.rst",
        "integration_tests/**/*.py",
    ):
        found.extend(REPO_ROOT.glob(pattern))
    for name in ("README.md", "CONTRIBUTING.md", "CHANGELOG.md"):
        path = REPO_ROOT / name
        if path.is_file():
            found.append(path)
    # docs/*.md is tracked EXCEPT the handful of gitignored handover/generated
    # notes already named in _UNPUBLISHED (they exist on a dev machine that
    # has generated them, but are absent from the published repository). Skip
    # those explicitly rather than relying on their absence -- scanning one
    # would fail this guard on the file legitimately containing its own name.
    for path in REPO_ROOT.glob("docs/*.md"):
        if path.name not in _UNPUBLISHED:
            found.append(path)
    # scripts/probe_*.py is gitignored as a glob; everything else under
    # scripts/ is tracked.
    for path in REPO_ROOT.glob("scripts/**/*.py"):
        if not path.name.startswith("probe_"):
            found.append(path)
    return sorted(p for p in found if p.name not in _SELF_EXEMPT)


def _ids() -> list[str]:
    return [p.relative_to(REPO_ROOT).as_posix() for p in _tracked_text_files()]


def test_scan_scope_covers_integration_tests_and_docs_md() -> None:
    """Pins the widened scan scope so a narrower future glob is caught.

    ``integration_tests/`` is prose-heavy and cites source files by name (see
    ``RequestUpdate``'s own docstring, which points at
    ``test_live_ticket_metadata.py``). ``docs/*.md`` must be scanned too --
    otherwise ``docs/vendor-api-reference.md``, the artifact this guard exists
    to make citable, would itself be unguarded against reintroducing exactly
    the citation it replaces.
    """
    found = set(_tracked_text_files())
    assert REPO_ROOT / "integration_tests" / "test_live_ticket_metadata.py" in found
    assert REPO_ROOT / "docs" / "vendor-api-reference.md" in found


@pytest.mark.parametrize("path", _tracked_text_files(), ids=_ids())
def test_no_gitignored_citations(path: Path) -> None:
    text = path.read_text(encoding="utf-8")
    for needle in _UNPUBLISHED:
        assert needle not in text, (
            f"{path.relative_to(REPO_ROOT).as_posix()} references {needle!r}, "
            "which is gitignored and invisible to anyone reading the published "
            "repository. Cite docs/vendor-api-reference.md instead."
        )

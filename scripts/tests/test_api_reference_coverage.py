"""Every public export must appear in ``docs/api_reference.rst``.

An export missing from the reference is invisible to anyone reading the
published documentation: Sphinx renders only what the file lists, so there is
no warning, no broken link and nothing for ``sphinx -W`` to catch. It looks
exactly like a symbol that was never added.

This is not hypothetical. ``PostTask`` -- the model for posting a comment, and
the one write model the actions guide recommends over its sibling -- was
exported, exercised in six user-guide snippets and absent from the reference
until 2026-09-02. So were the two exported module constants.

Offline by construction: imports the package and reads one file.

What this deliberately does **not** check, so a green run is not over-trusted:

- **Not that the entry renders.** A stale dotted path fails the Sphinx build
  instead, which is the gate that owns that question.
- **Not that the docstring is any good**, or that the directive is the right
  one (``autoclass`` versus ``autodata``).
- **Not the reverse direction.** The reference may document a symbol that is
  not in ``__all__`` -- module-level helpers reached through their full path,
  such as ``references.label_from_record``, are legitimately listed.
"""

from __future__ import annotations

import re
from pathlib import Path

import easyvista_python_client as ev

REPO_ROOT = Path(__file__).resolve().parents[2]
API_REFERENCE = REPO_ROOT / "docs" / "api_reference.rst"

#: Exports that belong somewhere other than the API reference, with the reason.
_EXEMPT = {
    # The version string is release metadata, documented in publishing.rst
    # where the four places to bump it are enumerated. An autodata entry here
    # would render a bare literal that goes stale on every release.
    "__version__",
}

_DIRECTIVE = re.compile(
    r"^\.\.\s+auto(?:class|function|data|exception|method)::\s+([\w.]+)",
    re.MULTILINE,
)


def _documented_names() -> set[str]:
    """Trailing attribute names of every autodoc directive in the reference."""
    text = API_REFERENCE.read_text(encoding="utf-8")
    return {path.rsplit(".", 1)[-1] for path in _DIRECTIVE.findall(text)}


def test_api_reference_exists() -> None:
    assert API_REFERENCE.is_file(), f"{API_REFERENCE} is missing"


def test_every_public_export_is_documented() -> None:
    """``__all__`` minus the exemptions must be covered by an autodoc entry."""
    documented = _documented_names()
    missing = sorted(set(ev.__all__) - documented - _EXEMPT)
    assert not missing, (
        f"exported but absent from docs/api_reference.rst: {missing}. Add an "
        "autodoc directive for each, or add it to _EXEMPT here with the reason "
        "it belongs elsewhere."
    )


def test_exemptions_are_still_exported() -> None:
    """An exemption for a symbol that no longer exists is dead weight."""
    stale = sorted(name for name in _EXEMPT if name not in set(ev.__all__))
    assert not stale, f"_EXEMPT names symbols that are no longer exported: {stale}"

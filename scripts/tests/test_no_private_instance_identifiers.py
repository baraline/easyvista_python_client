"""Guard: no private EasyVista instance identifier reaches a tracked file.

``.gitignore`` withholds the instance-describing notes because "they carry the
instance host/account, the end customer's org structure, and a map of that
instance's bespoke customization". That policy had no automated enforcement, and
in the 0.3.0 candidate a real preprod hostname reached
``docs/vendor-api-reference.md`` -- a tracked file in a public repository that
also ships inside the sdist (``pyproject.toml`` includes ``/docs``). All five CI
gates passed on that tree, because none of them looks at prose for this.

Two properties make the leak worth a dedicated guard rather than a review habit:

* **It is irreversible.** A public push writes the host into permanent git
  history, and ``pyproject.toml`` says in as many words that "a PyPI upload
  cannot be taken back". This repository already paid that price once -- its
  history was squashed at publish-prep to purge private-instance references.
* **It is silent.** Nothing about a hostname in a sentence looks wrong to ruff,
  mypy, Sphinx or the test suite.

**Why hashes and not a plaintext needle list.** The obvious implementation --
``git grep`` for the forbidden strings -- requires this file to *contain* them,
and this file is tracked and public like any other. The first draft of this
guard did exactly that: it published the hostname it existed to protect, in a
module exempted from its own check. So the identifiers are stored as SHA-256
digests. The scanner hashes candidate tokens out of each file and compares
digests, so the plaintext appears nowhere in the repository and this module
needs no exemption.

That makes the check one-way, with the trade-offs a one-way check has. It
catches an identifier written *verbatim*; it cannot catch a paraphrase, a
partially redacted host, or a value split across a line break. It is a backstop
against the mistake actually made, not a proof of absence.

To add an identifier, hash it and add the digest with a description::

    import hashlib
    hashlib.sha256(VALUE.lower().encode()).hexdigest()

Scope note: this checks *identifiers*, where ``test_source_citations.py`` checks
*cited paths*. They are deliberately separate guards over the same file set.
"""

from __future__ import annotations

import hashlib
import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]

# SHA-256 of the lowercased token. Plaintext is deliberately absent -- see the
# module docstring. The illustrative account number used throughout the tracked
# docs and tests is NOT listed: an account id alone names no host, and listing
# it would fail this guard on a dozen deliberate uses. Nor is the synthetic
# catalog-code stand-in the tracked tests use. The host is the identifying
# half, and that is what is refused.
_FORBIDDEN_DIGESTS: dict[str, str] = {
    "6c296fde55b852788be0818c74fc20be7554d5fede6bbd3d421965755dd3d0c1": (
        "a private EasyVista instance name"
    ),
    "7df7849f4de367e34a3ecbfa8f4d1ac19a8af929d942dd91ec7f9a0151899f11": (
        "a private EasyVista instance hostname"
    ),
    "d1342080c9d59a1ed80c89b3fd458ec4dde04f2cdb682b2480b006765362fefa": (
        "the private EasyVista instance's domain"
    ),
    "10b52891164a5a877cf3bf66454fad9a00fe2eff00c19bde97c4b77bcb632bb9": (
        "a real catalog GUID from a private instance"
    ),
    "d35d7dc7573826dca2cc3483a0cb17ec5f913d3d7bda7b0d0b9ec1c93fbce2ab": (
        "a real catalog code from a private instance"
    ),
}

# A hostname, GUID, code or bare word: starts alphanumeric, then anything a
# host or identifier may carry. ``\w`` covers the underscore in a catalog code.
_TOKEN = re.compile(r"[A-Za-z0-9][\w.-]*")

# Mirrors test_source_citations.py: gitignored notes that legitimately carry
# these values on a dev machine and are absent from the published repository.
_UNPUBLISHED_FILENAMES = {
    "API_Info.md",
    "easyvista-field-inventory.md",
    "easyvista-test-profile-blocked-operations.md",
}


def _digests(token: str) -> set[str]:
    """Every digest worth testing for one extracted token.

    Three forms, each closing a real gap:

    * the whole token -- an exact hostname or catalog code;
    * each dot-suffix -- so a bare domain is caught inside a longer FQDN;
    * the leading eight characters -- so a full GUID is caught from the
      recorded prefix, which is all that was ever known of it.
    """
    lowered = token.lower().strip(".-")
    if not lowered:
        return set()
    forms = {lowered, lowered[:8]}
    parts = lowered.split(".")
    for index in range(1, len(parts)):
        forms.add(".".join(parts[index:]))
    return {hashlib.sha256(form.encode()).hexdigest() for form in forms if form}


def _offending(text: str) -> tuple[str, str] | None:
    """The first offending token and what it is, or ``None`` when clean."""
    for match in _TOKEN.finditer(text):
        token = match.group(0)
        for digest in _digests(token):
            if digest in _FORBIDDEN_DIGESTS:
                return token, _FORBIDDEN_DIGESTS[digest]
    return None


def _tracked_text_files() -> list[Path]:
    """Every tracked file whose prose a public reader can open."""
    found: list[Path] = []
    for pattern in (
        "easyvista_python_client/**/*.py",
        "docs/*.rst",
        "integration_tests/**/*.py",
        "skills/**/*.md",
        "scripts/**/*.py",
    ):
        found.extend(REPO_ROOT.glob(pattern))
    for name in ("README.md", "CONTRIBUTING.md", "CHANGELOG.md", "CLAUDE.md"):
        path = REPO_ROOT / name
        if path.is_file():
            found.append(path)
    for path in REPO_ROOT.glob("docs/*.md"):
        if path.name not in _UNPUBLISHED_FILENAMES:
            found.append(path)
    # scripts/probe_*.py is gitignored as a glob; everything else is tracked.
    return sorted({p for p in found if not p.name.startswith("probe_")})


def _ids() -> list[str]:
    return [p.relative_to(REPO_ROOT).as_posix() for p in _tracked_text_files()]


def test_scan_scope_covers_the_file_the_leak_reached() -> None:
    """Pins the scope, so a narrower future glob cannot silently un-guard it."""
    found = set(_tracked_text_files())
    assert REPO_ROOT / "docs" / "vendor-api-reference.md" in found
    assert REPO_ROOT / "README.md" in found
    assert REPO_ROOT / "skills" / "easyvista-ticket-actions" / "SKILL.md" in found


def test_this_module_guards_itself() -> None:
    """The hole in the first draft: it was exempt, and it held the plaintext.

    Storing digests means this file needs no exemption, so it is scanned like
    every other. That is the property worth pinning -- an exemption is exactly
    where a leak hides.
    """
    assert Path(__file__).resolve() in set(_tracked_text_files())


def test_the_scanner_catches_a_listed_identifier() -> None:
    """A guard nobody has seen fail is a guard nobody knows works.

    Exercised against a *synthetic* digest injected for the duration of the
    test, because the real plaintext is deliberately not available here -- that
    is the whole design. What this proves is the mechanism: tokenise, hash,
    match, report.
    """
    synthetic = "zzz-not-a-real-instance.invalid"
    digest = hashlib.sha256(synthetic.encode()).hexdigest()
    suffix_digest = hashlib.sha256(b"sub.invalid").hexdigest()
    _FORBIDDEN_DIGESTS[digest] = "a synthetic value, for this test only"
    _FORBIDDEN_DIGESTS[suffix_digest] = "a synthetic domain, for this test only"
    try:
        hit = _offending(f"measured on {synthetic} last week")
        assert hit is not None, "the scanner missed a token whose digest is listed"
        assert hit[0] == synthetic
        # The dot-suffix form: a bare domain caught inside a longer FQDN.
        assert _offending("see host.sub.invalid for details") is not None
    finally:
        _FORBIDDEN_DIGESTS.pop(digest, None)
        _FORBIDDEN_DIGESTS.pop(suffix_digest, None)


def test_the_scanner_allows_the_deliberate_synthetic_values() -> None:
    """The illustrative account number and the code stand-in must stay usable."""
    assert _offending('catalog_code="EAZ_INC_000"') is None
    assert _offending("the account segment, a number such as 50004") is None
    assert _offending("a second 2025.3 deployment") is None


@pytest.mark.parametrize("path", _tracked_text_files(), ids=_ids())
def test_no_private_instance_identifier(path: Path) -> None:
    hit = _offending(path.read_text(encoding="utf-8"))
    assert hit is None, (
        f"{path.relative_to(REPO_ROOT).as_posix()} contains {hit[0]!r} -- "
        f"{hit[1]}. Tracked files are published to a public repository and ship "
        "inside the sdist, and neither a git push nor a PyPI upload can be "
        "taken back. Describe the deployment anonymously instead ('the "
        "development instance', 'a second 2025.3 deployment'); no measurement "
        "in this repository depends on naming a host."
    )

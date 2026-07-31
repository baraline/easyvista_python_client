"""Contract tests for the Agent Skills under ``skills/``.

Every ``SKILL.md`` makes checkable claims about the public surface of
``easyvista_python_client``: the symbols it imports, the client methods it
calls, the keyword arguments it passes, the model fields it sets. This module
re-checks each claim against the installed package, so a rename or a dropped
keyword fails here instead of failing an agent months later against a live
instance.

Offline by construction: it imports the package and reads files. No
credentials, no network, nothing instantiated that would open a socket.
"""

from __future__ import annotations

import ast
import inspect
import re
from pathlib import Path
from typing import Any

import pytest

import easyvista_python_client as ev

REPO_ROOT = Path(__file__).resolve().parents[2]
SKILLS_DIR = REPO_ROOT / "skills"

# The Agent Skills spec caps the description; a longer one is silently
# truncated by the loader, which would hide the trigger conditions.
_MAX_DESCRIPTION = 1024

_PY_BLOCK = re.compile(r"^```python\n(.*?)^```", re.MULTILINE | re.DOTALL)


def _skill_dirs() -> list[Path]:
    """Every skill directory, sorted. Empty when ``skills/`` does not exist."""
    if not SKILLS_DIR.is_dir():
        return []
    return sorted(p for p in SKILLS_DIR.iterdir() if p.is_dir())


def _skill_ids() -> list[str]:
    return [p.name for p in _skill_dirs()]


def _parse_frontmatter(text: str) -> dict[str, Any]:
    """Parse the small YAML subset the frontmatter uses.

    Flat ``key: value`` lines plus one nested block (``metadata:``) of
    two-space-indented ``key: value`` lines. Values may be double-quoted.
    Hand-rolled rather than importing PyYAML: the shape is fixed and adding a
    dependency to lint documentation is not worth it.
    """
    if not text.startswith("---\n"):
        raise ValueError("SKILL.md must open with a '---' frontmatter fence")
    _, _, rest = text.partition("---\n")
    body, fence, _ = rest.partition("\n---\n")
    if not fence:
        raise ValueError("frontmatter is not closed by a '---' line")
    data: dict[str, Any] = {}
    block: dict[str, Any] | None = None
    for line in body.splitlines():
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        key, sep, value = line.partition(":")
        if not sep:
            raise ValueError(f"unparseable frontmatter line: {line!r}")
        text_value = value.strip().strip('"')
        if line.startswith("  "):
            if block is None:
                raise ValueError(f"indented key outside a block: {line!r}")
            block[key.strip()] = text_value
            continue
        if not text_value:
            block = {}
            data[key.strip()] = block
            continue
        block = None
        data[key.strip()] = text_value
    return data


def _python_blocks(text: str) -> list[str]:
    """Every fenced ``python`` code block's source, in document order."""
    return [match.group(1) for match in _PY_BLOCK.finditer(text)]


def test_skills_directory_exists_and_is_populated() -> None:
    assert SKILLS_DIR.is_dir(), f"{SKILLS_DIR} does not exist"
    assert _skill_dirs(), "skills/ holds no skill directories"


@pytest.mark.parametrize("skill", _skill_dirs(), ids=_skill_ids())
def test_skill_directory_holds_exactly_one_skill_md(skill: Path) -> None:
    files = sorted(p.name for p in skill.iterdir())
    assert files == ["SKILL.md"], f"{skill.name} holds {files}, expected ['SKILL.md']"


@pytest.mark.parametrize("skill", _skill_dirs(), ids=_skill_ids())
def test_frontmatter_name_matches_directory(skill: Path) -> None:
    meta = _parse_frontmatter((skill / "SKILL.md").read_text(encoding="utf-8"))
    assert meta.get("name") == skill.name, (
        f"frontmatter name {meta.get('name')!r} != directory {skill.name!r}; "
        "the Agent Skills spec requires them to match"
    )


@pytest.mark.parametrize("skill", _skill_dirs(), ids=_skill_ids())
def test_frontmatter_description_is_present_and_bounded(skill: Path) -> None:
    meta = _parse_frontmatter((skill / "SKILL.md").read_text(encoding="utf-8"))
    description = meta.get("description")
    assert isinstance(description, str) and description.strip(), (
        f"{skill.name} has no description; it is what the agent matches on"
    )
    assert len(description) <= _MAX_DESCRIPTION, (
        f"{skill.name} description is {len(description)} chars, "
        f"over the {_MAX_DESCRIPTION} limit"
    )


@pytest.mark.parametrize("skill", _skill_dirs(), ids=_skill_ids())
def test_frontmatter_metadata_tracks_the_package(skill: Path) -> None:
    meta = _parse_frontmatter((skill / "SKILL.md").read_text(encoding="utf-8"))
    assert meta.get("license") == "MIT"
    block = meta.get("metadata")
    assert isinstance(block, dict), f"{skill.name} has no metadata block"
    assert block.get("package") == "easyvista-python-client"
    # A release that bumps __version__ and forgets the skills fails here.
    assert block.get("version") == ev.__version__, (
        f"{skill.name} claims version {block.get('version')!r}, "
        f"package is {ev.__version__!r}"
    )


@pytest.mark.parametrize("skill", _skill_dirs(), ids=_skill_ids())
def test_python_snippets_parse(skill: Path) -> None:
    blocks = _python_blocks((skill / "SKILL.md").read_text(encoding="utf-8"))
    assert blocks, f"{skill.name} has no python examples"
    for index, block in enumerate(blocks):
        try:
            ast.parse(block)
        except SyntaxError as exc:
            raise AssertionError(
                f"{skill.name} python block #{index + 1} does not parse: {exc}"
            ) from exc


def test_readme_lists_every_skill() -> None:
    readme = SKILLS_DIR / "README.md"
    assert readme.is_file(), "skills/README.md is missing"
    text = readme.read_text(encoding="utf-8")
    listed = set(re.findall(r"`(easyvista-[a-z-]+)`", text))
    present = {p.name for p in _skill_dirs()}
    assert present - listed == set(), (
        f"not listed in README: {sorted(present - listed)}"
    )
    assert listed - present == set(), f"listed but missing: {sorted(listed - present)}"


# Snippets address a client through a variable with one of these names, or
# through the class itself for classmethods like ``from_env``.
_CLIENT_NAMES = {"client", "EasyvistaClient", "AsyncEasyvistaClient"}

# Write payloads a snippet may construct, checked against their real fields.
_WRITE_MODELS = {
    "PostRequest": ev.PostRequest,
    "RequestUpdate": ev.RequestUpdate,
    "PostAction": ev.PostAction,
    "PostAsset": ev.PostAsset,
    "PostDepartment": ev.PostDepartment,
    "DepartmentUpdate": ev.DepartmentUpdate,
    "PostEmployee": ev.PostEmployee,
    "EmployeeUpdate": ev.EmployeeUpdate,
}

# Files that are gitignored: a skill naming one is a dead link for every
# reader who only has the published repository.
_UNPUBLISHED = (
    "API_Info.md",
    "easyvista-field-inventory.md",
    "easyvista-test-profile-blocked-operations.md",
    "docs/superpowers",
    "secrets/",
)

_URL_LITERAL = re.compile(r"https?://[^\s\"']+")


def _client_calls(tree: ast.AST) -> list[ast.Call]:
    """Every ``client.<method>(...)`` call in a parsed snippet."""
    calls = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute):
            continue
        target = node.func.value
        if isinstance(target, ast.Name) and target.id in _CLIENT_NAMES:
            calls.append(node)
    return calls


def _snippet_trees(skill: Path) -> list[ast.Module]:
    text = (skill / "SKILL.md").read_text(encoding="utf-8")
    return [ast.parse(block) for block in _python_blocks(text)]


@pytest.mark.parametrize("skill", _skill_dirs(), ids=_skill_ids())
def test_imported_symbols_are_public(skill: Path) -> None:
    exported = set(ev.__all__)
    for tree in _snippet_trees(skill):
        for node in ast.walk(tree):
            if not isinstance(node, ast.ImportFrom):
                continue
            module = node.module or ""
            assert not module.startswith("easyvista_python_client."), (
                f"{skill.name} imports from the private module {module!r}; "
                "skills use the package root only"
            )
            if module != "easyvista_python_client":
                continue
            for alias in node.names:
                assert alias.name in exported, (
                    f"{skill.name} imports {alias.name!r}, which is not in "
                    "easyvista_python_client.__all__"
                )


@pytest.mark.parametrize("skill", _skill_dirs(), ids=_skill_ids())
def test_client_methods_and_keywords_exist(skill: Path) -> None:
    for tree in _snippet_trees(skill):
        for call in _client_calls(tree):
            method = call.func.attr
            for cls in (ev.EasyvistaClient, ev.AsyncEasyvistaClient):
                bound = getattr(cls, method, None)
                assert bound is not None, (
                    f"{skill.name} calls client.{method}(), which does not exist "
                    f"on {cls.__name__}"
                )
            signature = inspect.signature(getattr(ev.EasyvistaClient, method))
            accepted = set(signature.parameters) - {"self"}
            for keyword in call.keywords:
                if keyword.arg is None:  # **kwargs splat
                    continue
                assert keyword.arg in accepted, (
                    f"{skill.name} passes {keyword.arg}= to client.{method}(), "
                    f"which accepts {sorted(accepted)}"
                )


@pytest.mark.parametrize("skill", _skill_dirs(), ids=_skill_ids())
def test_write_model_keywords_exist(skill: Path) -> None:
    for tree in _snippet_trees(skill):
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Name):
                continue
            model = _WRITE_MODELS.get(node.func.id)
            if model is None:
                continue
            fields = set(model.model_fields)
            for keyword in node.keywords:
                if keyword.arg is None:
                    continue
                assert keyword.arg in fields, (
                    f"{skill.name} sets {keyword.arg}= on {node.func.id}, whose "
                    f"fields are {sorted(fields)}"
                )


@pytest.mark.parametrize("skill", _skill_dirs(), ids=_skill_ids())
def test_no_unpublished_or_private_references(skill: Path) -> None:
    text = (skill / "SKILL.md").read_text(encoding="utf-8")
    for needle in _UNPUBLISHED:
        assert needle not in text, (
            f"{skill.name} references {needle!r}, which is gitignored and "
            "invisible to anyone reading the published repository"
        )
    assert "easyvista_python_client._" not in text, (
        f"{skill.name} names a private module; skills document the public surface"
    )


@pytest.mark.parametrize("skill", _skill_dirs(), ids=_skill_ids())
def test_snippet_hosts_are_synthetic(skill: Path) -> None:
    for tree in _snippet_trees(skill):
        for node in ast.walk(tree):
            if not isinstance(node, ast.Constant) or not isinstance(node.value, str):
                continue
            for url in _URL_LITERAL.findall(node.value):
                assert "example.com" in url, (
                    f"{skill.name} carries a non-synthetic URL {url!r}; every "
                    "host in a skill must sit under example.com"
                )

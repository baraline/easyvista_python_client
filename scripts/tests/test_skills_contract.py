"""Contract tests for the Agent Skills under ``skills/``.

Every ``SKILL.md`` makes checkable claims about the public surface of
``easyvista_python_client``: the symbols it imports, the client methods it
calls, the keyword arguments it passes, the model fields it sets. This module
re-checks each claim against the installed package, so a rename or a dropped
keyword fails here instead of failing an agent months later against a live
instance.

Offline by construction: it imports the package and reads files. No
credentials, no network, nothing instantiated that would open a socket.

What this does *not* check, so that a green run is not over-trusted. It is a
name-and-keyword gate over ``python`` code blocks, not a semantic one:

- **No prose claim is verified.** The Configuration and Errors tables, every
  Procedure step and every Gotcha in every skill are unchecked text. A
  behavioural claim that goes stale fails nothing here.
- **No attribute read on a returned object.** ``ticket.rfc_numbr`` passes;
  only names imported from the package root and keywords passed to a client
  method or a write model are looked up.
- **No positional arguments and no arity.** Only ``keyword=`` arguments are
  matched against the signature.
- **No required fields and no value types.** ``PostAsset(catalog_id="1")``
  passes even though the field is an ``int``, and a write model missing a
  mandatory field passes too -- nothing is ever instantiated.
- **No call through an unrecognized receiver.** A method call is only checked
  when its receiver is named in ``_CLIENT_NAMES``; ``svc.get_ticket(...)``
  is invisible.
- **No code block tagged anything but ``python``/``py``.** A block with
  another tag, or none, skips every snippet check silently.
- **Nothing about the repository beyond existence** for the two link checks
  below: a referenced path is checked to exist, not to still contain the
  symbol or test the prose attributes to it, and a cross-referenced skill is
  checked to exist, not to still cover the topic it is cited for.
"""

from __future__ import annotations

import ast
import inspect
import re
from pathlib import Path
from typing import Any

import pytest

import easyvista_python_client as ev
from easyvista_python_client.models.common import EasyvistaWriteModel

REPO_ROOT = Path(__file__).resolve().parents[2]
SKILLS_DIR = REPO_ROOT / "skills"

# The Agent Skills spec caps the description; a longer one is silently
# truncated by the loader, which would hide the trigger conditions.
_MAX_DESCRIPTION = 1024

# Both tags render identically, so a block tagged ``py`` would otherwise skip
# every snippet check below without any visible difference in the document.
_PY_BLOCK = re.compile(r"^```(?:python|py)\n(.*?)^```", re.MULTILINE | re.DOTALL)


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
    "PostTask": ev.PostTask,
    "ActionUpdate": ev.ActionUpdate,
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
    # `.gitignore` ignores `scripts/probe_*.py` as a glob; the prefix is the
    # substring every one of those paths shares. It deliberately does not
    # match `scripts/validate_live_content_fidelity.py`, which is tracked and
    # which easyvista-ticket-workflow cites.
    "scripts/probe_",
    # Local agent/tooling state, ignored by the same root .gitignore block.
    ".claude/",
    ".superpowers/",
)

_URL_LITERAL = re.compile(r"https?://[^\s\"']+")

# Repo paths a skill cites, extracted deliberately narrowly: an inline-code
# span whose *entire* content is a slash-bearing relative path ending in a
# known source extension, optionally followed by a pytest node id
# (``file.py::test_name``). Three restrictions do the work:
#
# * whole-span match -- prose that merely mentions a filename is never a
#   candidate, only a span the author fenced as a path;
# * a `/` is required -- so a bare `SKILL.md` or `README.md` written about
#   documents in general is not read as a path relative to the repo root;
# * the character class excludes `{`, `<` and spaces -- so API route
#   templates (`{server}/api/{api_version}/{account}`, `requests/{rfc}/comment`,
#   `/api/v1/<account>`) cannot be mistaken for files on disk.
#
# The cost is that a genuinely broken bare-filename reference goes unnoticed.
# That is the intended trade: a false failure here would block a correct
# commit over prose, which is worse than missing one class of dead link.
_REPO_PATH = re.compile(
    r"`([A-Za-z0-9_][A-Za-z0-9_.-]*/[A-Za-z0-9_./-]*"
    r"\.(?:py|md|toml|yml|yaml|cfg|ini|txt))(?:::[A-Za-z0-9_]+)*`"
)

# A cross-referenced sibling skill, always written as an inline-code span.
_SKILL_REF = re.compile(r"`(easyvista-[a-z][a-z-]*)`")

# The distribution name shares the `easyvista-` prefix with every skill name
# but is not one, so a skill that backticks it must not be read as citing a
# missing sibling.
_NOT_A_SKILL_REF = frozenset({"easyvista-python-client"})

# unasync generates the sync client from the async source and renames
# ``aclose`` to ``close`` as part of that transform, so this one pair is
# deliberately asymmetric: only ``EasyvistaClient`` has ``close``, only
# ``AsyncEasyvistaClient`` has ``aclose``. Every other client method is
# expected to exist on both classes; this is the sole exemption from that
# rule, not a general relaxation of it.
_ASYMMETRIC_METHODS = {"close", "aclose"}


def _is_client_expr(node: ast.expr) -> bool:
    """True for a bare client name or an attribute chain ending in one.

    Covers both ``client.foo()`` and ``ctx.client.foo()`` -- the receiver
    does not have to be a bare name for the call to be a real client call.
    """
    if isinstance(node, ast.Name):
        return node.id in _CLIENT_NAMES
    if isinstance(node, ast.Attribute):
        return node.attr in _CLIENT_NAMES
    return False


def _client_calls(tree: ast.AST) -> list[ast.Call]:
    """Every ``client.<method>(...)`` call in a parsed snippet."""
    calls = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute):
            continue
        if _is_client_expr(node.func.value):
            calls.append(node)
    return calls


def _write_model_name(func: ast.expr) -> str | None:
    """The write-model name a call targets, bare or module-qualified.

    Covers both ``PostRequest(...)`` and ``ev.PostRequest(...)`` -- the
    callee does not have to be a bare name for the call to be checkable.
    """
    if isinstance(func, ast.Name):
        return func.id
    if isinstance(func, ast.Attribute):
        return func.attr
    return None


def _snippet_trees(skill: Path) -> list[ast.Module]:
    text = (skill / "SKILL.md").read_text(encoding="utf-8")
    return [ast.parse(block) for block in _python_blocks(text)]


@pytest.mark.parametrize("skill", _skill_dirs(), ids=_skill_ids())
def test_imported_symbols_are_public(skill: Path) -> None:
    exported = set(ev.__all__)
    for tree in _snippet_trees(skill):
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    qualifies = alias.name == "easyvista_python_client" or (
                        alias.name.startswith("easyvista_python_client.")
                    )
                    as_clause = f" as {alias.asname}" if alias.asname else ""
                    assert not qualifies, (
                        f"{skill.name} does `import {alias.name}{as_clause}`; "
                        "snippets must `from easyvista_python_client import "
                        "...` instead, so every name they touch through the "
                        "module is checkable against __all__"
                    )
                continue
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
    all_calls = [call for tree in _snippet_trees(skill) for call in _client_calls(tree)]
    assert all_calls, f"{skill.name} has no client.<method>() call in any example"
    for call in all_calls:
        method = call.func.attr
        if method in _ASYMMETRIC_METHODS:
            owners = [
                cls
                for cls in (ev.EasyvistaClient, ev.AsyncEasyvistaClient)
                if getattr(cls, method, None) is not None
            ]
            assert owners, (
                f"{skill.name} calls client.{method}(), which does not exist "
                "on EasyvistaClient or AsyncEasyvistaClient"
            )
            signature_owner = owners[0]
        else:
            for cls in (ev.EasyvistaClient, ev.AsyncEasyvistaClient):
                bound = getattr(cls, method, None)
                assert bound is not None, (
                    f"{skill.name} calls client.{method}(), which does not exist "
                    f"on {cls.__name__}"
                )
            signature_owner = ev.EasyvistaClient
        signature = inspect.signature(getattr(signature_owner, method))
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
            if not isinstance(node, ast.Call):
                continue
            name = _write_model_name(node.func)
            if name is None:
                continue
            model = _WRITE_MODELS.get(name)
            if model is None:
                continue
            fields = set(model.model_fields)
            for keyword in node.keywords:
                if keyword.arg is None:
                    continue
                assert keyword.arg in fields, (
                    f"{skill.name} sets {keyword.arg}= on {name}, whose "
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
def test_referenced_repo_paths_exist(skill: Path) -> None:
    """Every repo path a skill cites still exists.

    Skills point at live-suite modules and package sources as their evidence
    ("that file is the authority when something here looks wrong"). A rename
    turns those into dead links that nothing else in the repository notices,
    because no import or tool reads a Markdown citation.
    """
    text = (skill / "SKILL.md").read_text(encoding="utf-8")
    for match in _REPO_PATH.finditer(text):
        relative = match.group(1)
        assert (REPO_ROOT / relative).exists(), (
            f"{skill.name} cites {relative!r}, which does not exist under "
            f"{REPO_ROOT}; a rename left the citation pointing at nothing"
        )


@pytest.mark.parametrize("skill", _skill_dirs(), ids=_skill_ids())
def test_cross_referenced_skills_exist(skill: Path) -> None:
    """Every sibling skill a skill routes the agent to is really there.

    The skills form a graph: each one delegates the grammar, the client setup
    or the context bundles to a named peer rather than repeating it. A rename
    or a removal breaks the delegation silently -- the agent is sent to a
    skill that cannot be loaded, and the fact lives nowhere else.
    """
    text = (skill / "SKILL.md").read_text(encoding="utf-8")
    present = {p.name for p in _skill_dirs()}
    for match in _SKILL_REF.finditer(text):
        name = match.group(1)
        if name in _NOT_A_SKILL_REF:
            continue
        assert name in present, (
            f"{skill.name} cross-references the skill {name!r}, which is not "
            f"a directory under {SKILLS_DIR}; skills present are "
            f"{sorted(present)}"
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


def test_write_models_map_is_complete() -> None:
    """Every exported EasyvistaWriteModel subclass maps in _WRITE_MODELS.

    The ``_WRITE_MODELS`` dict pairs write model names to their classes so that
    snippet keyword validation can find them. A write model exported from the
    package but missing from the dict has its snippets silently skipped, leaving
    typos and dropped keywords undetected. This test converts the hand-maintained
    enumeration into a self-checking gate that fails when a new write model is
    exported without a map entry.
    """
    exported = {
        name
        for name in ev.__all__
        if (
            inspect.isclass(obj := getattr(ev, name, None))
            and obj is not EasyvistaWriteModel
            and issubclass(obj, EasyvistaWriteModel)
        )
    }
    mapped = set(_WRITE_MODELS.keys())
    assert exported == mapped, (
        f"exported write models {sorted(exported)} do not match "
        f"_WRITE_MODELS {sorted(mapped)}; missing from map: {sorted(exported - mapped)}"
    )

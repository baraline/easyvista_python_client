"""Guards for the ``_async`` -> ``_sync`` code generation.

The generated tree is protected in CI by regenerating it and diffing. That
catches *staleness* -- someone editing ``_async/`` without rerunning the
build -- and nothing else. In particular it cannot catch the failure mode
that actually worries us:

**A token collision is deterministic, so the diff stays empty.** If a local
variable, parameter or attribute happens to be spelled like a substitution
key, ``unasync`` rewrites it every single time. Regenerating produces exactly
the same wrong file, ``git diff`` is clean, CI is green, and the sync client
is silently incorrect. No amount of diffing finds that.

These tests find it, by scanning the source for identifiers the substitution
map would rewrite and failing on any that are not an intentional rename.
"""

from __future__ import annotations

import ast
import importlib.util
import pathlib

import pytest

pytest.importorskip(
    "unasync",
    reason="unasync is a dev-only dependency; codegen guards need it installed",
)

_REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
_BUILD_SCRIPT = _REPO_ROOT / "unasync_build.py"

#: Names the codegen is *supposed* to rewrite, scoped to the one AST role
#: each is legitimate in.
#:
#: This is deliberately *not* a flat set of strings exempted everywhere: a
#: bare-name allowlist would wave through any binding that happens to share
#: the spelling, not just the one legitimate site. ``AsyncEasyvistaClient``
#: is legitimately introduced only as a class name; ``__aenter__``,
#: ``__aexit__`` and ``aclose`` only as a method name. Scoping the exemption
#: to that construct means a local variable, parameter, or attribute
#: elsewhere named e.g. ``aclose`` still trips the scan.
#:
#: ``AsyncClient`` and ``AsyncRetrying`` need no entry at all: they are
#: third-party names this tree only ever *uses* -- as a bare import name
#: (``from tenacity import AsyncRetrying``) or an ordinary attribute/call
#: reference (``httpx.AsyncClient(...)``) -- and neither of those is a
#: binding this scan treats as a new definition. Giving them a blanket
#: exemption instead is exactly the bug this file exists to avoid: a
#: throwaway ``AsyncRetrying = 1`` local elsewhere in the tree would slip
#: through undetected, exempted only because the *real* ``AsyncRetrying``
#: import happens to share its spelling.
_INTENTIONAL_CLASS_NAMES = {"AsyncEasyvistaClient"}
_INTENTIONAL_DEF_NAMES = {"__aenter__", "__aexit__", "aclose"}


def _build_module():
    """Import ``unasync_build`` from the repository root."""
    spec = importlib.util.spec_from_file_location("unasync_build", _BUILD_SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def build():
    return _build_module()


def _parameter_names(
    node: ast.FunctionDef | ast.AsyncFunctionDef | ast.Lambda,
) -> list[str]:
    """Every name a function/lambda signature binds, all five kinds.

    Positional-only, positional-or-keyword and keyword-only parameters are
    each their own list on ``ast.arguments``; ``*args`` and ``**kwargs`` are
    a single optional ``ast.arg`` apiece, not a list. Skipping either of the
    last two would be a real gap here, not a hypothetical one: this tree
    already defines ``**kwargs``/``**kw`` parameters in its test modules.
    """
    args = node.args
    names = [a.arg for a in args.posonlyargs]
    names.extend(a.arg for a in args.args)
    names.extend(a.arg for a in args.kwonlyargs)
    if args.vararg is not None:
        names.append(args.vararg.arg)
    if args.kwarg is not None:
        names.append(args.kwarg.arg)
    return names


def _rewritable_names(node: ast.AST, keys: set[str]) -> list[str]:
    """Names on ``node`` that match a key and are not a deliberate rename.

    ``unasync`` rewrites a NAME token wherever it appears in the token
    stream, regardless of what role the token plays in the grammar, so this
    has to reach every construct that spells out a new binding: a
    ``def``/``class`` name, every parameter kind, an assignment target (in
    the broad sense ``ast.Store`` covers -- plain and augmented assignment,
    ``for``/comprehension targets and ``with ... as`` bindings are all
    ``ast.Name`` nodes in ``Store`` context, so one check reaches all of
    them), an attribute store (``self.aclose = ...``), an import alias
    (``import x as AsyncRetrying`` -- neither a ``Name`` nor covered by
    ``Store`` context, since ``ast.alias`` carries the name as a plain
    string), an ``except ... as`` name, a ``global``/``nonlocal``
    declaration, and a ``match``/``case`` capture: ``case AsyncClient:``
    (``ast.MatchAs.name``), ``case [*AsyncRetrying]:`` (``ast.MatchStar.name``)
    and ``case {**aclose}:`` (``ast.MatchMapping.rest``) each bind a plain
    name the same way, and none of them is an ``ast.Name`` either. ``match``
    is valid on this project's 3.10 floor, so it is a live construct even
    though nothing in the tree uses it today.

    The exemption for a deliberate rename is scoped to the *specific* role
    it is legitimate in -- a class name for ``AsyncEasyvistaClient``, a
    method name for the dunders and ``aclose`` -- rather than exempted by
    bare string everywhere. A flat name-based allowlist would silently wave
    through a *different* binding that happens to share the spelling: a
    local variable named ``AsyncRetrying`` inside an unrelated method is a
    real collision even though the name is also, correctly, a tenacity
    import elsewhere in the same tree. None of the other categories --
    parameters, plain assignments, attribute stores, import aliases,
    ``except`` names, ``global``/``nonlocal`` -- has a legitimate rename
    site in this tree, so none of them gets an exemption.
    """
    if isinstance(node, ast.ClassDef):
        if node.name in keys and node.name not in _INTENTIONAL_CLASS_NAMES:
            return [node.name]
        return []

    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
        names = []
        if node.name in keys and node.name not in _INTENTIONAL_DEF_NAMES:
            names.append(node.name)
        names.extend(n for n in _parameter_names(node) if n in keys)
        return names

    if isinstance(node, ast.Lambda):
        return [n for n in _parameter_names(node) if n in keys]

    if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Store):
        return [node.id] if node.id in keys else []

    if isinstance(node, ast.Attribute) and isinstance(node.ctx, ast.Store):
        return [node.attr] if node.attr in keys else []

    if isinstance(node, ast.alias) and node.asname is not None:
        return [node.asname] if node.asname in keys else []

    if isinstance(node, ast.ExceptHandler) and node.name is not None:
        return [node.name] if node.name in keys else []

    if isinstance(node, (ast.Global, ast.Nonlocal)):
        return [n for n in node.names if n in keys]

    if isinstance(node, (ast.MatchAs, ast.MatchStar)) and node.name is not None:
        return [node.name] if node.name in keys else []

    if isinstance(node, ast.MatchMapping) and node.rest is not None:
        return [node.rest] if node.rest in keys else []

    return []


def test_no_source_identifier_collides_with_a_substitution_key(build):
    """Every rewritable identifier we define is a deliberate, scoped rename."""
    keys = set(build.TOKEN_REPLACEMENTS) - {"_async"}
    offenders: list[str] = []

    for path in build._source_files():
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            for name in _rewritable_names(node, keys):
                rel = path.relative_to(_REPO_ROOT).as_posix()
                offenders.append(f"{rel}: {name}")

    assert not offenders, (
        "these identifiers collide with a codegen substitution key and would "
        f"be silently rewritten: {offenders}"
    )


def test_the_generated_tree_never_mentions_the_async_one(build):
    """In strings as well as identifiers.

    unasync rewrites a string literal only when its *entire* content is a
    key, so a bare ``_async`` inside a longer docstring survives both the
    token pass and the build script's qualified-prefix post-pass. This is the
    assertion that catches it.
    """
    offenders: list[str] = []
    for path in sorted(build.SYNC_DIR.rglob("*.py")):
        if "__pycache__" in path.parts:
            continue
        for lineno, line in enumerate(
            path.read_text(encoding="utf-8").splitlines(), start=1
        ):
            if "_async" in line:
                rel = path.relative_to(_REPO_ROOT).as_posix()
                offenders.append(f"{rel}:{lineno}: {line.strip()}")
    assert not offenders, f"generated tree mentions the async tree: {offenders}"


def test_every_hand_written_twin_exists_on_both_sides(build):
    """A missing twin would make --check green while a module had none."""
    for rel in sorted(build.HAND_WRITTEN):
        assert (build.ASYNC_DIR / rel).is_file(), f"_async/{rel} is missing"
        assert (build.SYNC_DIR / rel).is_file(), f"_sync/{rel} is missing"


def test_no_substitution_key_is_a_dotted_name(build):
    """A dotted key is accepted silently and never fires."""
    dotted = [k for k in build.TOKEN_REPLACEMENTS if "." in k]
    assert not dotted, (
        f"dotted substitution keys never match and fail silently: {dotted}"
    )

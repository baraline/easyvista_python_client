import re
import subprocess
import sys
import tomllib
from pathlib import Path

import pytest

import easyvista_python_client

_REPO_ROOT = Path(__file__).resolve().parents[2]

#: Each distribution in the optional ``content`` extra, mapped to the module it
#: installs. The two names differ for three of the six, so neither can be
#: derived from the other; ``test_the_content_import_names_match_the_extra``
#: keeps the keys equal to what pyproject.toml actually declares.
_CONTENT_IMPORT_NAMES = {
    "beautifulsoup4": "bs4",
    "cmarkgfm": "cmarkgfm",
    "markdown-it-py": "markdown_it",
    "markdownify": "markdownify",
    "mdformat": "mdformat",
    "mdformat-tables": "mdformat_tables",
}

#: The import names of the optional ``content`` extra's distributions.
_CONTENT_MODULES = tuple(sorted(_CONTENT_IMPORT_NAMES.values()))


def _optional_dependencies() -> dict[str, list[str]]:
    """``[project.optional-dependencies]`` as pyproject.toml declares it."""
    config = tomllib.loads((_REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    extras: dict[str, list[str]] = config["project"]["optional-dependencies"]
    return extras


def _distribution_name(requirement: str) -> str:
    """The normalized project name a PEP 508 requirement string names."""
    match = re.match(r"[A-Za-z0-9._-]+", requirement.strip())
    assert match, f"not a requirement: {requirement!r}"
    return re.sub(r"[-_.]+", "-", match.group(0)).lower()


def _run_python(code: str) -> subprocess.CompletedProcess[str]:
    """Run ``code`` in a fresh interpreter that imports this checkout.

    A fresh one because this process has already imported the extra for the
    converter's own tests, so ``sys.modules`` here can answer nothing about
    what a bare ``import easyvista_python_client`` loads. ``-c`` puts the
    working directory first on ``sys.path``, which is what makes the child
    import the tree under test rather than whatever else is installed.
    """
    return subprocess.run(
        [sys.executable, "-c", code],
        capture_output=True,
        text=True,
        check=False,
        cwd=_REPO_ROOT,
    )


def test_package_imports_and_has_version():
    assert easyvista_python_client.__version__ == "0.4.0"


def test_public_exports_available():
    from easyvista_python_client import (
        Asset,
        AsyncEasyvistaClient,
        Document,
        EasyvistaAuthError,
        EasyvistaClient,
        EasyvistaConfig,
        EasyvistaError,
        PostAction,
        PostAsset,
        PostRequest,
        Request,
        RequestUpdate,
        SearchResult,
    )

    assert EasyvistaClient is not None
    assert AsyncEasyvistaClient is not None
    assert issubclass(EasyvistaAuthError, EasyvistaError)
    for cls in (
        EasyvistaConfig,
        PostRequest,
        Request,
        RequestUpdate,
        PostAction,
        SearchResult,
        Asset,
        PostAsset,
        Document,
    ):
        assert cls is not None


def test_directory_public_exports():
    import easyvista_python_client as evc

    for name in (
        "Department",
        "Employee",
        "PostDepartment",
        "DepartmentUpdate",
        "PostEmployee",
        "EmployeeUpdate",
        "DepartmentContext",
    ):
        assert hasattr(evc, name), name
        assert name in evc.__all__


def test_both_clients_expose_the_same_surface():
    """Parity is a property of the package, not of one client."""
    import inspect

    from easyvista_python_client import AsyncEasyvistaClient, EasyvistaClient

    def public(cls):
        return {
            n for n, _ in inspect.getmembers(cls, callable) if not n.startswith("_")
        }

    sync_only = public(EasyvistaClient) - public(AsyncEasyvistaClient)
    async_only = public(AsyncEasyvistaClient) - public(EasyvistaClient)
    assert sync_only == {"close"}
    assert async_only == {"aclose"}


def test_every_async_client_method_is_awaitable():
    """A coroutine or async generator, never a plain value."""
    import inspect

    from easyvista_python_client import AsyncEasyvistaClient

    for name, member in inspect.getmembers(AsyncEasyvistaClient, inspect.isfunction):
        if name.startswith("_") or name in {"from_env"}:
            continue
        assert inspect.iscoroutinefunction(member) or inspect.isasyncgenfunction(
            member
        ), f"{name} is neither a coroutine nor an async generator"


def test_content_error_is_exported_beside_its_siblings():
    """The error ships in the core, so it is catchable without the extra."""
    import easyvista_python_client as evc

    assert "EasyvistaContentError" in evc.__all__
    assert issubclass(evc.EasyvistaContentError, evc.EasyvistaError)


def test_importing_the_package_does_not_import_the_content_extra():
    """``import easyvista_python_client`` must not pay for the converter."""
    result = _run_python(
        "import sys\n"
        "import easyvista_python_client\n"
        f"print(sorted(m for m in {_CONTENT_MODULES!r} if m in sys.modules))\n"
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "[]"


def test_the_package_works_without_the_content_extra():
    """With the extra uninstalled, only the ``content`` subpackage refuses.

    ``sys.modules[name] = None`` makes the next import of ``name`` raise
    ``ImportError``, which is what an environment without the extra does.
    The core must import, its error class must be there to catch, and the
    subpackage must say how to install what it needs.
    """
    result = _run_python(
        "import sys\n"
        f"for name in {_CONTENT_MODULES!r}:\n"
        "    sys.modules[name] = None\n"
        "import easyvista_python_client\n"
        "print(easyvista_python_client.EasyvistaContentError.__name__)\n"
        "try:\n"
        "    import easyvista_python_client.content\n"
        "except ImportError as exc:\n"
        "    print(exc)\n"
        "else:\n"
        "    raise SystemExit('the content subpackage imported without its extra')\n"
    )

    assert result.returncode == 0, result.stderr
    first, _, rest = result.stdout.partition("\n")
    assert first.strip() == "EasyvistaContentError"
    assert 'pip install "easyvista-python-client[content]"' in rest


def test_dev_and_docs_install_the_content_extra():
    """CI installs ``.[dev]`` and Read the Docs ``.[docs]``; both need the extra.

    Without it in ``dev`` the converter's tests cannot import on CI, and
    without it in ``docs`` autodoc cannot import the module it documents. The
    requirements are written out in each extra, bounds included, and this is
    what keeps the copies in step.
    """
    extras = _optional_dependencies()
    content = set(extras["content"])

    assert content, "the content extra declares nothing"
    assert content <= set(extras["dev"]), sorted(content - set(extras["dev"]))
    assert content <= set(extras["docs"]), sorted(content - set(extras["docs"]))


def test_the_pre_commit_mypy_hook_pins_the_content_extra_as_pyproject_does():
    """The mypy hook's copies of the extra's requirements equal pyproject's.

    The hook builds its own venv from ``additional_dependencies``, so the
    extra's typed packages are written out there a second time, and nothing
    else keeps that copy in step. Read with a regex rather than a YAML parser,
    which the test environment does not otherwise need. The hook lists only
    the typed packages, so a package of the extra may be absent from it, but
    one that is listed must carry the extra's exact bounds.
    """
    config = (_REPO_ROOT / ".pre-commit-config.yaml").read_text(encoding="utf-8")
    hook = re.search(r"- id: mypy\n(.*?)\n\s*exclude:", config, re.DOTALL)
    assert hook, "no mypy hook found in .pre-commit-config.yaml"
    listed = re.findall(r'^\s*-\s*"([^"]+)"\s*$', hook.group(1), re.MULTILINE)
    extra = {_distribution_name(r): r for r in _optional_dependencies()["content"]}

    copies = {
        _distribution_name(r): r for r in listed if _distribution_name(r) in extra
    }

    assert copies, "the mypy hook lists none of the content extra's packages"
    drifted = {name: (r, extra[name]) for name, r in copies.items() if r != extra[name]}
    assert not drifted, f"hook requirement != pyproject's: {drifted}"


def test_the_supported_pythons_agree_everywhere_they_are_written():
    """requires-python, the classifiers and both CI matrices name one range.

    Each lists the supported interpreters by hand, and a floor raised in one
    place and not the others is what this package's drop of 3.10 had to
    chase through all four.
    """
    config = tomllib.loads((_REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    project = config["project"]
    prefix = "Programming Language :: Python :: 3."
    classified = sorted(
        int(c.removeprefix(prefix))
        for c in project["classifiers"]
        if c.startswith(prefix) and c.removeprefix(prefix).isdecimal()
    )
    floor = re.fullmatch(r">=3\.(\d+)", project["requires-python"])
    assert floor, project["requires-python"]
    assert classified, "no Python 3.x classifier"
    assert classified[0] == int(floor.group(1))
    assert classified == list(range(classified[0], classified[-1] + 1))

    for workflow in ("ci.yml", "release.yml"):
        text = (_REPO_ROOT / ".github" / "workflows" / workflow).read_text(
            encoding="utf-8"
        )
        matrices = re.findall(r"python-version:\s*\[([^\]]*)\]", text)
        assert len(matrices) == 1, f"{workflow}: {len(matrices)} matrices"
        versions = re.findall(r'"3\.(\d+)"', matrices[0])
        assert sorted(int(v) for v in versions) == classified, workflow


def test_the_content_import_names_match_the_extra():
    """``_CONTENT_MODULES`` names exactly the modules the extra installs.

    The two import-isolation tests above are only as good as that list: a
    distribution added to the extra but missing here is never checked, and one
    dropped from the extra but left here is checked for nothing -- which is how
    ``markdown`` outlived the python-markdown converter it was listed for. So
    the list is bound to pyproject.toml by distribution name.
    """
    declared = {_distribution_name(r) for r in _optional_dependencies()["content"]}

    assert declared == set(_CONTENT_IMPORT_NAMES), (
        f"in pyproject only: {sorted(declared - set(_CONTENT_IMPORT_NAMES))}; "
        f"listed here only: {sorted(set(_CONTENT_IMPORT_NAMES) - declared)}"
    )


@pytest.mark.parametrize("module", _CONTENT_MODULES)
def test_each_content_dependency_alone_triggers_the_install_hint(module):
    """Any ONE missing distribution makes the subpackage name the extra.

    A partial install is the realistic failure -- a pinned environment that
    predates a dependency the extra gained -- and it must fail at import with
    the install command, not later with a bare ``ModuleNotFoundError`` from
    inside a conversion. A fresh child per module rather than one child
    blocking and unblocking in turn: un-caching a package does not un-cache its
    submodules, so a re-import in the same process can fail for reasons that
    have nothing to do with the guard.
    """
    result = _run_python(
        "import sys\n"
        f"sys.modules[{module!r}] = None\n"
        "try:\n"
        "    import easyvista_python_client.content\n"
        "except ImportError as exc:\n"
        "    print(exc)\n"
        "else:\n"
        "    raise SystemExit('the content subpackage imported without it')\n"
    )

    assert result.returncode == 0, result.stderr
    assert 'pip install "easyvista-python-client[content]"' in result.stdout

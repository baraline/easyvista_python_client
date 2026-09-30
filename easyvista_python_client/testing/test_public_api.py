import subprocess
import sys
from pathlib import Path

import easyvista_python_client

_REPO_ROOT = Path(__file__).resolve().parents[2]

#: The import names of the optional ``content`` extra's three distributions.
_CONTENT_MODULES = ("bs4", "markdown", "markdownify")


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
    """With the three uninstalled, only the ``content`` subpackage refuses.

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
    three requirements are written out in each extra, and this is what keeps
    the copies in step.
    """
    try:
        import tomllib
    except ModuleNotFoundError:  # Python 3.10
        import tomli as tomllib

    config = tomllib.loads((_REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    extras = config["project"]["optional-dependencies"]
    content = set(extras["content"])

    assert content, "the content extra declares nothing"
    assert content <= set(extras["dev"]), sorted(content - set(extras["dev"]))
    assert content <= set(extras["docs"]), sorted(content - set(extras["docs"]))

import easyvista_python_client


def test_package_imports_and_has_version():
    assert easyvista_python_client.__version__ == "0.1.0"


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

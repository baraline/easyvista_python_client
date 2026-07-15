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

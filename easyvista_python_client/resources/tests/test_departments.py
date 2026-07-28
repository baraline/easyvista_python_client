from easyvista_python_client.models.department import PostDepartment
from easyvista_python_client.pagination import SearchResult
from easyvista_python_client.resources import departments as dep


def test_build_get_department():
    spec, parser = dep.build_get_department(60)
    assert spec.method == "GET"
    assert spec.path == "departments/60"
    assert parser({"DEPARTMENT_ID": 60}).department_id == 60


def test_build_search_departments_params_and_result():
    spec, parser = dep.build_search_departments(
        search='DEPARTMENT_CODE:"ACME-CORP"', max_rows=5
    )
    assert spec.path == "departments"
    assert spec.params == {"search": 'DEPARTMENT_CODE:"ACME-CORP"', "max_rows": 5}
    result = parser(
        {"records": [{"DEPARTMENT_ID": 60}], "record_count": 1, "total_record_count": 1}
    )
    assert isinstance(result, SearchResult)
    assert result.records[0].department_id == 60


def test_build_create_department_wraps_envelope():
    payload = PostDepartment(department_code="ACME-CORP")
    spec, parser = dep.build_create_department(payload)
    assert spec.method == "POST"
    assert spec.path == "departments"
    assert spec.json == {"departments": [{"department_code": "ACME-CORP"}]}
    parsed = parser({"HREF": "https://h/api/v1/12345/departments/61"})
    assert parsed.href.endswith("/departments/61")

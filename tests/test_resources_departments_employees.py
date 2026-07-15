from easyvista_python_client.models.department import PostDepartment
from easyvista_python_client.models.employee import EmployeeUpdate
from easyvista_python_client.pagination import SearchResult
from easyvista_python_client.resources import departments as dep
from easyvista_python_client.resources import employees as emp


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


def test_build_get_employee_and_search():
    spec, parser = emp.build_get_employee(6087)
    assert spec.path == "employees/6087"
    assert parser({"EMPLOYEE_ID": 6087}).employee_id == 6087
    sspec, _ = emp.build_search_employees(search='DEPARTMENT_ID:"60"', max_rows=3)
    assert sspec.path == "employees"
    assert sspec.params == {"search": 'DEPARTMENT_ID:"60"', "max_rows": 3}


def test_build_update_employee_sends_bare_payload():
    spec, _ = emp.build_update_employee(6087, EmployeeUpdate(phone_number="0102"))
    assert spec.method == "PUT"
    assert spec.path == "employees/6087"
    assert spec.json == {"phone_number": "0102"}

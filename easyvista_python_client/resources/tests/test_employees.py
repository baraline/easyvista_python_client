from easyvista_python_client.models.employee import EmployeeUpdate
from easyvista_python_client.resources import employees as emp


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

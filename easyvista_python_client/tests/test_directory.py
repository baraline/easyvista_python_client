from easyvista_python_client.directory import (
    DepartmentContext,
    _department_matches,
    _normalize_name,
)
from easyvista_python_client.models.department import Department
from easyvista_python_client.models.employee import Employee


def test_normalize_name_is_space_and_hyphen_and_case_insensitive():
    assert (
        _normalize_name("ACME-CORP")
        == _normalize_name("ACME CORP")
        == _normalize_name("acmecorp")
    )


def test_department_matches_across_localized_fields_and_ignores_href():
    dept = Department.model_validate(
        {"DEPARTMENT_FR": "ACME CORP", "HREF": "https://h/api/v1/12345/departments/60"}
    )
    assert _department_matches(dept, _normalize_name("acmecorp")) is True
    assert _department_matches(dept, _normalize_name("nope")) is False


def test_department_context_holds_all_parts():
    ctx = DepartmentContext(
        department=Department.model_validate({"DEPARTMENT_ID": 60}),
        employees=[Employee.model_validate({"EMPLOYEE_ID": 1})],
        manager=None,
        note=None,
        ticket_count=0,
        recent_tickets=[],
        ticket_statistics=None,
        assets=[],
    )
    assert ctx.department.department_id == 60
    assert ctx.employees[0].employee_id == 1

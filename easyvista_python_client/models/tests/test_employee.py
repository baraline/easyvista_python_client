from easyvista_python_client.models.employee import (
    Employee,
    EmployeeUpdate,
    PostEmployee,
)


def test_employee_aliases_from_single_get():
    emp = Employee.model_validate(
        {
            "EMPLOYEE_ID": 6087,
            "LAST_NAME": "Doe",
            "E_MAIL": "doe@acme-corp.example",
            "DEPARTMENT_ID": 60,
            "LOGIN": "jdoe",
            "MANAGER_ID": 42,
            "FUNCTION_ID": 3,
            "HREF": "https://h/api/v1/12345/employees/6087",
        }
    )
    assert emp.employee_id == 6087
    assert emp.last_name == "Doe"
    assert emp.e_mail == "doe@acme-corp.example"
    assert emp.department_id == 60
    assert emp.login == "jdoe"


def test_employee_empty_string_int_coerced_to_none():
    emp = Employee.model_validate(
        {"EMPLOYEE_ID": "", "FUNCTION_ID": "", "PROFIL_ID": "", "MANAGER_ID": ""}
    )
    assert emp.employee_id is None
    assert emp.function_id is None
    assert emp.profil_id is None
    assert emp.manager_id is None


def test_declared_e_mail_stays_official_not_custom():
    emp = Employee.model_validate(
        {"EMPLOYEE_ID": 1, "E_MAIL": "a@b.c", "E_CUSTOM": "x"}
    )
    fc = emp.classify_fields()
    assert "E_MAIL" in fc.official  # declared alias -> official, never custom
    assert "E_CUSTOM" in fc.custom  # undeclared e_* -> custom


def test_employee_comment_surfaced_as_link():
    emp = Employee.model_validate(
        {
            "EMPLOYEE_ID": 1,
            "COMMENT_EMPLOYEE": {"HREF": "https://h/.../comment_employee"},
        }
    )
    assert "COMMENT_EMPLOYEE" in emp.classify_fields().links


def test_post_employee_to_api():
    payload = PostEmployee(last_name="Doe", e_mail="doe@x.fr", department_id=60)
    assert payload.to_api() == {
        "last_name": "Doe",
        "e_mail": "doe@x.fr",
        "department_id": 60,
    }


def test_employee_update_is_write_model():
    assert EmployeeUpdate(phone_number="0102").to_api() == {"phone_number": "0102"}

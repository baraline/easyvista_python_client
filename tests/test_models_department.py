from easyvista_python_client.models.department import (
    Department,
    DepartmentUpdate,
    PostDepartment,
)


def test_department_aliases():
    dept = Department.model_validate(
        {
            "DEPARTMENT_ID": 60,
            "DEPARTMENT_CODE": "ACME-CORP",
            "DEPARTMENT_PATH": "Clients/Standard/ACME-CORP",
            "MANAGER_ID": 42,
            "LEVEL": 3,
            "HREF": "https://h/api/v1/12345/departments/60",
        }
    )
    assert dept.department_id == 60
    assert dept.department_code == "ACME-CORP"
    assert dept.manager_id == 42
    assert dept.level == 3


def test_department_empty_string_int_coerced_to_none():
    dept = Department.model_validate(
        {"DEPARTMENT_ID": "", "MANAGER_ID": "", "LEVEL": ""}
    )
    assert dept.department_id is None
    assert dept.manager_id is None
    assert dept.level is None


def test_department_name_prefers_localized_label_skipping_brackets():
    dept = Department.model_validate(
        {
            "DEPARTMENT_CODE": "ACME-CORP",
            "DEPARTMENT_EN": "[ACME-CORP]",  # placeholder on this French instance
            "DEPARTMENT_FR": "ACME CORP",
            "DEPARTMENT_PATH": "Clients/Standard/ACME-CORP",
        }
    )
    assert dept.name == "ACME CORP"


def test_department_name_falls_back_to_code_then_path():
    by_code = Department.model_validate(
        {"DEPARTMENT_CODE": "ACME-CORP", "DEPARTMENT_PATH": "A/B"}
    )
    assert by_code.name == "ACME-CORP"
    by_path = Department.model_validate({"DEPARTMENT_PATH": "A/B"})
    assert by_path.name == "A/B"


def test_department_comment_surfaced_as_link_not_declared_field():
    dept = Department.model_validate(
        {
            "DEPARTMENT_ID": 60,
            "COMMENT_DEPARTMENT": {"HREF": "https://h/.../comment_department"},
        }
    )
    assert "COMMENT_DEPARTMENT" in dept.classify_fields().links


def test_post_department_to_api_drops_none_and_prefixes_custom():
    payload = PostDepartment(department_code="ACME-CORP", custom_fields={"sla_1_id": 7})
    assert payload.to_api() == {"department_code": "ACME-CORP", "e_sla_1_id": 7}


def test_department_update_is_write_model():
    assert DepartmentUpdate(manager_id=42).to_api() == {"manager_id": 42}

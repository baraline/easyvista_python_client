from easyvista_python_client.field_model import (
    FieldClassification,
    classify,
    parse_memo,
)


def test_classify_partitions_official_custom_available_links():
    record = {
        "HREF": "https://h/api/v1/acme/employees/1",
        "EMPLOYEE_ID": "1",
        "E_MAIL": "a@b.c",  # declared official -> official
        "E_CUSTOM_REF": "42",  # undeclared e_ -> custom
        "AVAILABLE_FIELD_3": "x",  # available slot
        "COMMENT_EMPLOYEE": {"HREF": "https://h/.../comment_employee"},  # link
        "DEPARTMENT": {  # multi-key -> official
            "DEPARTMENT_FR": "ACME-CORP",
            "DEPARTMENT_ID": "60",
        },
    }
    result = classify(record, declared={"EMPLOYEE_ID", "E_MAIL"})
    assert isinstance(result, FieldClassification)
    assert result.official == {
        "EMPLOYEE_ID": "1",
        "E_MAIL": "a@b.c",
        "DEPARTMENT": {"DEPARTMENT_FR": "ACME-CORP", "DEPARTMENT_ID": "60"},
    }
    assert result.custom == {"E_CUSTOM_REF": "42"}
    assert result.available == {"AVAILABLE_FIELD_3": "x"}
    assert result.links == {"COMMENT_EMPLOYEE": "https://h/.../comment_employee"}


def test_classify_href_selflink_excluded_and_exactly_one_bucket():
    record = {
        "HREF": "self",
        "TITLE": "t",
        "E_X": "1",
        "AVAILABLE_FIELD_1": "a",
        "DESCRIPTION": {"HREF": "d"},
    }
    r = classify(record)
    keys = set(r.official) | set(r.custom) | set(r.available) | set(r.links)
    assert "HREF" not in keys
    assert keys == {"TITLE", "E_X", "AVAILABLE_FIELD_1", "DESCRIPTION"}


def test_classify_non_dict_returns_empty():
    r = classify(None)
    assert r == FieldClassification({}, {}, {}, {})


def test_parse_memo_reads_field_case_insensitively():
    data = {"DESCRIPTION": "<p>hi</p>", "HREF": "x"}
    assert parse_memo(data, "description") == "<p>hi</p>"


def test_parse_memo_preserves_empty_string():
    assert parse_memo({"COMMENT_DEPARTMENT": ""}, "COMMENT_DEPARTMENT") == ""


def test_parse_memo_missing_or_non_dict_returns_none():
    assert parse_memo({"HREF": "x"}, "DESCRIPTION") is None
    assert parse_memo(None, "DESCRIPTION") is None
    assert parse_memo({"DESCRIPTION": {"HREF": "x"}}, "DESCRIPTION") is None  # non-str

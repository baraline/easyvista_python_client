from easyvista_python_client.directory import (
    RECENT_TICKETS_SORT,
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


def test_normalize_name_folds_accents_and_compatibility_forms():
    """Strictly more permissive than the ``lower()`` this replaced.

    It is a pure function of its argument, so every pair that matched before
    still matches (the test above is the guard for that) -- what changes is
    that more pairs now match. The accent case is the one that mattered: on an
    instance whose department labels are French, an unaccented search term
    matched nothing.

    The NO-BREAK-SPACE case pins the ORDER. NFKD itself decomposes U+00A0 (and
    the whole U+2000..U+200A family) to a plain space, so removing spaces
    before normalising would leave one behind.
    """
    assert _normalize_name("Systemes") == _normalize_name("Systèmes")
    assert _normalize_name("Straße") == _normalize_name("STRASSE")
    # Built with chr(), not a literal: a NO-BREAK SPACE is indistinguishable
    # from a plain one on screen, and a reader has to be able to see that
    # these are different characters for the assertion to mean anything.
    nbsp = "ACME" + chr(0xA0) + "CORP"
    assert nbsp != "ACME CORP"
    assert _normalize_name(nbsp) == _normalize_name("ACME CORP")


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
    # Both new fields are defaulted and appended last, so this fully-keyworded
    # construction still works untouched. An empty `degraded` means nothing was
    # swallowed -- NOT that everything came back populated.
    assert ctx.memos == {}
    assert ctx.degraded == frozenset()


def test_recent_tickets_sort_uses_the_space_separated_form():
    """The colon form is SILENTLY IGNORED by EasyVista (measured 2026-08-17).

    On a date column, `FIELD:DESC` returned rows in the API's default order —
    byte-identical to an unsorted page — so a colon-form constant is the
    difference between "most recent" and "arbitrary". The rule is syntactic, so
    it applies to RFC_NUMBER too; the live guard for this exact token lives in
    integration_tests/test_live_change_window.py. A regression here is invisible
    at runtime, which is why it is asserted at all.
    """
    assert RECENT_TICKETS_SORT == "RFC_NUMBER DESC"
    assert ":" not in RECENT_TICKETS_SORT

"""Live, read-only smoke tests for the directory endpoints.

Skipped automatically unless credentials are configured; never runs in CI. Reads
only — never writes (directory writes are provisional and profile-gated). NEVER
point at production.

This module reads the two record types carrying the most instance data --
``Employee`` (names, e-mail addresses, logins) and ``Department`` (labels) --
plus a department's free-text note, which is the Consigne. So every assertion
routes through ``_assertions`` or a pre-bound local, and none names a live value
(design principle P2).

That is not style. pytest's assertion rewriter reports the sub-expressions of a
failing assert, so ``assert isinstance(dept, Department)`` prints the whole
record, ``assert result.total_record_count >= 0`` prints the enclosing result,
and ``assert note is None or isinstance(note, str)`` prints the note text --
the one value this module most needs to keep out of the output. Measured, not
assumed. ``assert_shape`` lives in a module pytest does not rewrite, so only its
label is ever rendered; ``all(... for ...)`` reduces to a bare ``False`` because
the rewriter cannot explain inside a generator expression.
"""

from __future__ import annotations

import pytest

from easyvista_python_client import (
    Department,
    DepartmentContext,
    EasyvistaClient,
    Employee,
)
from integration_tests._assertions import assert_shape

pytestmark = pytest.mark.integration


def test_get_department(
    live_client: EasyvistaClient, sample_department_id: int
) -> None:
    dept = live_client.get_department(sample_department_id)
    assert_shape(dept, Department, "get_department result")
    id_round_trips = dept.department_id == sample_department_id
    assert id_round_trips, "DEPARTMENT_ID does not match the department requested"


def test_search_employees_read_only(live_client: EasyvistaClient) -> None:
    result = live_client.search_employees(max_rows=1)
    assert_shape(result.total_record_count, int, "employees TOTAL_RECORD_COUNT")
    assert all(isinstance(e, Employee) for e in result.records)


def test_get_employee_single_record(live_client: EasyvistaClient) -> None:
    listing = live_client.search_employees(max_rows=1)
    if not listing.records or listing.records[0].employee_id is None:
        pytest.skip("no employees to exercise the single-record GET")
    emp = live_client.get_employee(listing.records[0].employee_id)
    assert_shape(emp, Employee, "get_employee result")


def test_get_department_comment(
    live_client: EasyvistaClient, sample_department_id: int
) -> None:
    # A department note is a Memo: "" (empty) or text; a str either way
    # (or None if absent). Asserted by shape only, and bound first: this note is
    # Consigne text, so it must never become an assert sub-expression (P2).
    note = live_client.get_department_comment(sample_department_id)
    is_optional_str = note is None or isinstance(note, str)
    assert is_optional_str, "get_department_comment returned neither a str nor None"


def test_find_departments_returns_list(live_client: EasyvistaClient) -> None:
    found = live_client.find_departments("the", limit=3)  # fuzzy fallback
    assert_shape(found, list, "find_departments result")
    assert all(isinstance(d, Department) for d in found)


def test_get_department_context(
    live_client: EasyvistaClient, sample_department_id: int
) -> None:
    ctx = live_client.get_department_context(sample_department_id, recent_tickets=3)
    assert_shape(ctx, DepartmentContext, "get_department_context result")
    id_round_trips = ctx.department.department_id == sample_department_id
    assert id_round_trips, "the context is not for the department requested"
    assert_shape(ctx.employees, list, "DepartmentContext.employees")
    assert_shape(ctx.ticket_count, int, "DepartmentContext.ticket_count")

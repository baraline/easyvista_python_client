"""Live, read-only smoke tests for the directory endpoints.

Skipped automatically unless credentials are configured; never runs in CI. Reads
only — never writes (directory writes are provisional and profile-gated). NEVER
point at production.
"""

from __future__ import annotations

import pytest

from easyvista_python_client import (
    Department,
    DepartmentContext,
    EasyvistaClient,
    Employee,
)

pytestmark = pytest.mark.integration


def test_get_department(
    live_client: EasyvistaClient, sample_department_id: int
) -> None:
    dept = live_client.get_department(sample_department_id)
    assert isinstance(dept, Department)
    assert dept.department_id == sample_department_id


def test_search_employees_read_only(live_client: EasyvistaClient) -> None:
    result = live_client.search_employees(max_rows=1)
    assert isinstance(result.total_record_count, int)
    assert all(isinstance(e, Employee) for e in result.records)


def test_get_employee_single_record(live_client: EasyvistaClient) -> None:
    listing = live_client.search_employees(max_rows=1)
    if not listing.records or listing.records[0].employee_id is None:
        pytest.skip("no employees to exercise the single-record GET")
    emp = live_client.get_employee(listing.records[0].employee_id)
    assert isinstance(emp, Employee)


def test_get_department_comment(
    live_client: EasyvistaClient, sample_department_id: int
) -> None:
    # A department note is a Memo: "" (empty) or text; a str either way
    # (or None if absent).
    note = live_client.get_department_comment(sample_department_id)
    assert note is None or isinstance(note, str)


def test_find_departments_returns_list(live_client: EasyvistaClient) -> None:
    found = live_client.find_departments("the", limit=3)  # fuzzy fallback
    assert isinstance(found, list)
    assert all(isinstance(d, Department) for d in found)


def test_get_department_context(
    live_client: EasyvistaClient, sample_department_id: int
) -> None:
    ctx = live_client.get_department_context(sample_department_id, recent_tickets=3)
    assert isinstance(ctx, DepartmentContext)
    assert ctx.department.department_id == sample_department_id
    assert isinstance(ctx.employees, list)
    assert isinstance(ctx.ticket_count, int)

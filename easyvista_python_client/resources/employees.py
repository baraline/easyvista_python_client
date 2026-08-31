"""Builders for the ``employees`` resource — thin declarations over the engine."""

from __future__ import annotations

from collections.abc import Callable, Iterable
from typing import Any

from .._transport import RequestSpec
from ..models.employee import Employee, EmployeeUpdate, PostEmployee
from ..pagination import SearchResult
from .descriptor import (
    ResourceDescriptor,
    build_create,
    build_get,
    build_search,
    build_update,
)

EMPLOYEES: ResourceDescriptor[Employee] = ResourceDescriptor(
    path="employees", envelope_key="employees", model=Employee
)


def build_get_employee(
    employee_id: str | int,
    *,
    context: dict[str, Any] | None = None,
) -> tuple[RequestSpec, Callable[[Any], Employee]]:
    return build_get(EMPLOYEES, employee_id, context=context)


def build_search_employees(
    *,
    search: str | None = None,
    fields: Iterable[str] | str | None = None,
    sort: str | None = None,
    max_rows: int | None = None,
    offset: int | None = None,
    context: dict[str, Any] | None = None,
) -> tuple[RequestSpec, Callable[[Any], SearchResult[Employee]]]:
    return build_search(
        EMPLOYEES,
        search=search,
        fields=fields,
        sort=sort,
        max_rows=max_rows,
        offset=offset,
        context=context,
    )


def build_create_employee(
    payload: PostEmployee,
    *,
    context: dict[str, Any] | None = None,
) -> tuple[RequestSpec, Callable[[Any], Employee]]:
    return build_create(EMPLOYEES, payload, context=context)


def build_update_employee(
    employee_id: str | int,
    update: EmployeeUpdate,
    *,
    context: dict[str, Any] | None = None,
) -> tuple[RequestSpec, Callable[[Any], Employee]]:
    return build_update(EMPLOYEES, employee_id, update, context=context)

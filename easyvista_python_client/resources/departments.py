"""Builders for the ``departments`` resource — thin declarations over the engine."""

from __future__ import annotations

from collections.abc import Callable, Iterable
from typing import Any

from .._transport import RequestSpec
from ..models.department import Department, DepartmentUpdate, PostDepartment
from ..pagination import SearchResult
from .descriptor import (
    ResourceDescriptor,
    build_create,
    build_get,
    build_search,
    build_update,
)

DEPARTMENTS: ResourceDescriptor[Department] = ResourceDescriptor(
    path="departments", envelope_key="departments", model=Department
)


def build_get_department(
    department_id: str | int,
    *,
    context: dict[str, Any] | None = None,
) -> tuple[RequestSpec, Callable[[Any], Department]]:
    return build_get(DEPARTMENTS, department_id, context=context)


def build_search_departments(
    *,
    search: str | None = None,
    fields: Iterable[str] | str | None = None,
    sort: str | None = None,
    max_rows: int | None = None,
    offset: int | None = None,
    context: dict[str, Any] | None = None,
) -> tuple[RequestSpec, Callable[[Any], SearchResult[Department]]]:
    return build_search(
        DEPARTMENTS,
        search=search,
        fields=fields,
        sort=sort,
        max_rows=max_rows,
        offset=offset,
        context=context,
    )


def build_create_department(
    payload: PostDepartment,
    *,
    context: dict[str, Any] | None = None,
) -> tuple[RequestSpec, Callable[[Any], Department]]:
    return build_create(DEPARTMENTS, payload, context=context)


def build_update_department(
    department_id: str | int,
    update: DepartmentUpdate,
    *,
    context: dict[str, Any] | None = None,
) -> tuple[RequestSpec, Callable[[Any], Department]]:
    return build_update(DEPARTMENTS, department_id, update, context=context)

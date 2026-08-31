"""Generic resource engine.

A documented flat-CRUD EasyVista resource is data (a :class:`ResourceDescriptor`),
not a bespoke module: a descriptor + these four builders produce the same
``(RequestSpec, parser)`` pairs the hand-written builders did. Resource-specific
quirks that do not fit the flat shape — the ticket ``close`` body, ``create_action``'s
bare nested POST, and the whole ``documents`` sub-resource (a per-ticket nested path) —
stay as small overrides alongside their descriptor.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass
from typing import Any, Generic, TypeVar

from .._transport import RequestSpec
from ..models.common import EasyvistaModel, EasyvistaWriteModel
from ..pagination import SearchResult, build_search_result, extract_records

M = TypeVar("M", bound=EasyvistaModel)


@dataclass(frozen=True)
class ResourceDescriptor(Generic[M]):
    """A documented EasyVista resource.

    Holds its path, create/list envelope key, and read model.
    """

    path: str
    envelope_key: str
    model: type[M]


def _first_record_parser(
    desc: ResourceDescriptor[M], context: dict[str, Any] | None = None
) -> Callable[[Any], M]:
    """Build a parser that validates the first extracted record (or bare ``data``).

    Shared by :func:`build_get`, :func:`build_create` and :func:`build_update` —
    all three parse a single record, either wrapped in the resource's envelope
    (or ``records``) or returned bare (e.g. a create's ``HREF``-only body).

    ``context`` is the pydantic validation context, bound here at build time
    rather than passed to the returned parser: it is fixed for the lifetime of
    a client, so binding it early keeps the parser signature
    ``Callable[[Any], M]``. ``None`` — the default — makes every
    ``model_validate`` call byte-identical to a context-free one.
    """

    def parse(data: Any) -> M:
        records = extract_records(data, desc.envelope_key)
        return desc.model.model_validate(
            records[0] if records else data, context=context
        )

    return parse


def build_get(
    desc: ResourceDescriptor[M],
    record_id: Any,
    *,
    fields: Iterable[str] | str | None = None,
    context: dict[str, Any] | None = None,
) -> tuple[RequestSpec, Callable[[Any], M]]:
    params: dict[str, Any] = {}
    if fields is not None:
        params["fields"] = fields if isinstance(fields, str) else ",".join(fields)
    # ``params or None`` rather than a bare ``{}``: with no projection the spec
    # must be identical to the one this builder has always produced, and the
    # suite asserts on ``spec.params``.
    return (
        RequestSpec("GET", f"{desc.path}/{record_id}", params=params or None),
        _first_record_parser(desc, context),
    )


def build_search(
    desc: ResourceDescriptor[M],
    *,
    search: str | None = None,
    fields: Iterable[str] | str | None = None,
    sort: str | None = None,
    max_rows: int | None = None,
    offset: int | None = None,
    context: dict[str, Any] | None = None,
) -> tuple[RequestSpec, Callable[[Any], SearchResult[M]]]:
    params: dict[str, Any] = {}
    if search is not None:
        params["search"] = search
    if fields is not None:
        params["fields"] = fields if isinstance(fields, str) else ",".join(fields)
    if sort is not None:
        params["sort"] = sort
    if max_rows is not None:
        params["max_rows"] = max_rows
    if offset is not None:
        params["offset"] = offset

    def parse(data: Any) -> SearchResult[M]:
        records = [
            desc.model.model_validate(r, context=context)
            for r in extract_records(data, desc.envelope_key)
        ]
        return build_search_result(data, records)

    return RequestSpec("GET", desc.path, params=params), parse


def build_create(
    desc: ResourceDescriptor[M],
    payload: EasyvistaWriteModel,
    *,
    context: dict[str, Any] | None = None,
) -> tuple[RequestSpec, Callable[[Any], M]]:
    spec = RequestSpec("POST", desc.path, json={desc.envelope_key: [payload.to_api()]})
    return spec, _first_record_parser(desc, context)


def build_update(
    desc: ResourceDescriptor[M],
    record_id: Any,
    payload: EasyvistaWriteModel,
    *,
    context: dict[str, Any] | None = None,
) -> tuple[RequestSpec, Callable[[Any], M]]:
    spec = RequestSpec("PUT", f"{desc.path}/{record_id}", json=payload.to_api())
    return spec, _first_record_parser(desc, context)

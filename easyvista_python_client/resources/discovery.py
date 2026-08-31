"""Builders for the instance-discovery reads.

Both follow the ``(RequestSpec, parser)`` contract every other resource uses.
``build_list_reference_table`` reuses :func:`~.descriptor.build_search`, so the
parser and the envelope handling are the same ones every list endpoint gets.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping
from dataclasses import replace
from typing import Any

from .._transport import RequestSpec
from ..models.generic import GenericRecord
from ..pagination import SearchResult
from .descriptor import ResourceDescriptor, build_search

#: The route that serves the instance's own OpenAPI description.
#:
#: Measured 2026-08-27 on one instance (may not generalise) and NOT declared in
#: that instance's own ``paths``, so this is a tier-4 constant, not a tier-2
#: one. It is a module constant, and both client methods take a ``path``
#: keyword, so a deployment that publishes elsewhere needs no fork.
SWAGGER_PATH = "swagger"


def build_get_api_spec(
    path: str = SWAGGER_PATH,
) -> tuple[RequestSpec, Callable[[Any], dict[str, Any]]]:
    """A GET for the instance's OpenAPI document, parsed as a plain dict."""

    def parse(data: Any) -> dict[str, Any]:
        return data if isinstance(data, dict) else {}

    return RequestSpec("GET", path), parse


def build_list_reference_table(
    path: str,
    *,
    search: str | None = None,
    fields: Iterable[str] | str | None = None,
    sort: str | None = None,
    max_rows: int | None = None,
    offset: int | None = None,
    params: Mapping[str, Any] | None = None,
    context: dict[str, Any] | None = None,
) -> tuple[RequestSpec, Callable[[Any], SearchResult[GenericRecord]]]:
    """A GET over any list route, parsed into column-free records.

    The descriptor is built per call rather than declared as a constant,
    because the path is the caller's -- that is the whole point of this builder.
    ``envelope_key`` is the last path segment, which is what ``extract_records``
    checks after ``records``; a route that answers with a bare object and no
    envelope at all (the instance's ``GET /status`` schema shows exactly that)
    still parses, via that function's single-object fallback.

    ``params`` is merged last and wins over every modelled parameter above it,
    so a query argument this package does not know about needs no fork.
    """
    resource = path.strip("/")
    desc: ResourceDescriptor[GenericRecord] = ResourceDescriptor(
        path=resource, envelope_key=resource.rsplit("/", 1)[-1], model=GenericRecord
    )
    spec, parse = build_search(
        desc,
        search=search,
        fields=fields,
        sort=sort,
        max_rows=max_rows,
        offset=offset,
        context=context,
    )
    if params:
        merged = dict(spec.params or {})
        merged.update(params)
        spec = replace(spec, params=merged)  # RequestSpec is frozen
    return spec, parse

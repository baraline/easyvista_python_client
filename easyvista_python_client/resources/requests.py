"""Builders for the ``requests`` (ticket) resource.

Get/search/create/update ride the generic resource engine (:mod:`.descriptor`);
only the resource-specific ``close`` override stays bespoke. The clients execute the
returned spec and feed the JSON to the parser, so all request/response logic lives
here and is shared by the sync and async clients.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable
from typing import Any

from .._transport import RequestSpec
from ..models.request import PostRequest, Request, RequestUpdate
from ..pagination import SearchResult, extract_records
from .descriptor import (
    ResourceDescriptor,
    build_create,
    build_get,
    build_search,
    build_update,
)

REQUESTS: ResourceDescriptor[Request] = ResourceDescriptor(
    path="requests", envelope_key="requests", model=Request
)


def build_create_ticket(
    payload: PostRequest,
) -> tuple[RequestSpec, Callable[[Any], Request]]:
    return build_create(REQUESTS, payload)


def build_get_ticket(rfc_number: str) -> tuple[RequestSpec, Callable[[Any], Request]]:
    return build_get(REQUESTS, rfc_number)


def build_search_tickets(
    *,
    search: str | None = None,
    fields: Iterable[str] | str | None = None,
    sort: str | None = None,
    max_rows: int | None = None,
    offset: int | None = None,
) -> tuple[RequestSpec, Callable[[Any], SearchResult[Request]]]:
    return build_search(
        REQUESTS,
        search=search,
        fields=fields,
        sort=sort,
        max_rows=max_rows,
        offset=offset,
    )


def build_update_ticket(
    rfc_number: str, update: RequestUpdate
) -> tuple[RequestSpec, Callable[[Any], Request]]:
    return build_update(REQUESTS, rfc_number, update)


def build_close_ticket(
    rfc_number: str,
    *,
    status_guid: str | None = None,
    delete_actions: int | None = None,
    comment: str | None = None,
) -> tuple[RequestSpec, Callable[[Any], Request]]:
    """Build the ``{"closed": {...}}`` PUT spec — the API's status-set route.

    Despite the wire name, this envelope is **not limited to closing**. It is the
    only working way to set a ticket's status, and it reaches every status:
    handed each of six different ``STATUS_GUID``s in turn, a fresh ticket landed
    on exactly the status requested every time -- including non-terminal ones
    like "A prendre en compte" and "En cours". Nothing was forced to the closed
    status.

    Note the addressing: ``status_GUID``, not ``STATUS_ID``. There is no flat
    status update on this API -- see :class:`RequestUpdate` for what happens if
    you try one. :func:`build_set_status` is the same spec under a name that says
    what it does.

    ``delete_actions=1`` drops the ticket's actions. Shapes follow the documented
    close body (tier 1 -- ``docs/vendor-api-reference.md``), verified live.
    """
    closed: dict[str, Any] = {}
    if status_guid is not None:
        closed["status_GUID"] = status_guid
    if delete_actions is not None:
        closed["delete_actions"] = delete_actions
    if comment is not None:
        closed["comment"] = comment
    spec = RequestSpec("PUT", f"requests/{rfc_number}", json={"closed": closed})

    def parse(data: Any) -> Request:
        records = extract_records(data)
        return Request.model_validate(records[0] if records else data)

    return spec, parse


def build_set_status(
    rfc_number: str,
    *,
    status_guid: str,
    comment: str | None = None,
) -> tuple[RequestSpec, Callable[[Any], Request]]:
    """Build a spec that sets ``rfc_number``'s status to ``status_guid``.

    The same request :func:`build_close_ticket` builds, named for what it
    actually does. ``status_guid`` is required here rather than optional: the
    envelope without one is a close request with nothing to close to, and making
    that unexpressible is the point of having this function at all.
    """
    return build_close_ticket(rfc_number, status_guid=status_guid, comment=comment)

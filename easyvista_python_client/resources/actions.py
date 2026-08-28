"""Builders for the ticket ``actions`` sub-resource.

``list_actions`` rides the generic search builder over the top-level ``/actions``
resource (unwrapping the :class:`SearchResult` to a bare list). ``create_action``
posts a bare body nested under the parent request, which does not fit the flat-CRUD
engine, so it stays a small bespoke override alongside the ``ACTIONS`` descriptor.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable
from typing import Any

from .._transport import RequestSpec
from ..filters import ev_equals_filter
from ..models.action import Action, ActionUpdate, PostAction, PostTask
from ..pagination import SearchResult, extract_records
from .descriptor import ResourceDescriptor, build_get, build_search, build_update

ACTIONS: ResourceDescriptor[Action] = ResourceDescriptor(
    path="actions", envelope_key="actions", model=Action
)


def build_create_action(
    rfc_number: str, payload: PostAction
) -> tuple[RequestSpec, Callable[[Any], Action]]:
    # Create is nested under the request, one action per call, with a bare body
    # (NOT wrapped in an ``actions`` array) — verified against a live instance.
    spec = RequestSpec("POST", f"requests/{rfc_number}/actions", json=payload.to_api())

    def parse(data: Any) -> Action:
        records = extract_records(data)
        return Action.model_validate(records[0] if records else data)

    return spec, parse


def build_create_task(
    rfc_number: str, payload: PostTask
) -> tuple[RequestSpec, Callable[[Any], Action]]:
    """Build ``POST requests/{rfc}/tasks`` -- an action created already ENDED.

    Two differences from :func:`build_create_action`, both measured live
    2026-08-28. The body is **flat** at the root where the action create wraps
    its fields, and the record arrives with ``END_DATE_UT`` and
    ``STATUS_ID_ON_TERMINATE`` already set, so it renders in the ticket history
    with its text instead of as an open row with none.
    """
    spec = RequestSpec("POST", f"requests/{rfc_number}/tasks", json=payload.to_api())

    def parse(data: Any) -> Action:
        records = extract_records(data)
        return Action.model_validate(records[0] if records else data)

    return spec, parse


def build_search_actions(
    rfc_number: str,
    *,
    fields: Iterable[str] | str | None = None,
    max_rows: int | None = None,
    offset: int | None = None,
) -> tuple[RequestSpec, Callable[[Any], SearchResult[Action]]]:
    """One page of a ticket's actions, envelope included.

    Filters the TOP-LEVEL ``/actions`` resource by request number; the nested
    ``requests/{rfc}/actions`` path is rejected as "Unauthorized Method". The
    filter is re-applied on every page. A blank or unsafe ``rfc_number`` raises:
    ``,`` is a live combinator, so a raw value could list another ticket's
    actions.

    ``fields`` grants any scalar requested, but never the memo bodies
    (``DESCRIPTION`` and ``COMMENT`` stay HREF objects), and ``fields="*"``
    reduces to ``ACTION_ID`` alone.

    The envelope carries ``@next``, which is what makes ``offset`` paging
    possible. That contract is unverified on this endpoint -- see
    ``EasyvistaClient.iter_actions``.
    """
    search = ev_equals_filter("REQUEST.RFC_NUMBER", rfc_number)
    if search is None:
        raise ValueError("rfc_number is required to list a ticket's actions")
    return build_search(
        ACTIONS, search=search, fields=fields, max_rows=max_rows, offset=offset
    )


def build_list_actions(
    rfc_number: str,
    *,
    fields: Iterable[str] | str | None = None,
    max_rows: int | None = None,
) -> tuple[RequestSpec, Callable[[Any], list[Action]]]:
    """One page of a ticket's actions, as a bare list.

    :func:`build_search_actions` with the envelope dropped. Returns a single
    page: a ticket with more actions than ``max_rows`` is truncated silently,
    and the dropped envelope leaves the caller no way to detect it.
    ``EasyvistaClient.iter_actions`` pages instead.
    """
    spec, parse_search = build_search_actions(
        rfc_number, fields=fields, max_rows=max_rows
    )

    def parse(data: Any) -> list[Action]:
        return parse_search(data).records

    return spec, parse


def build_get_action(
    action_id: str | int,
) -> tuple[RequestSpec, Callable[[Any], Action]]:
    """Fetch ONE action by id.

    The item-level record is far richer than the list endpoint's: the note text
    a caller passed as ``PostAction.description`` comes back through a
    ``DESCRIPTION`` Memo sub-resource that ``list_actions`` does not return at
    all (verified live). Uses the **top-level** ``actions/{id}`` path — the
    nested ``requests/{rfc}/actions/{id}`` is rejected with HTTP 403, the same
    way the nested list path is.
    """
    return build_get(ACTIONS, action_id)


def build_update_action(
    action_id: str | int, payload: ActionUpdate
) -> tuple[RequestSpec, Callable[[Any], Action]]:
    """Edit one action, via the TOP-LEVEL ``actions/{id}`` path.

    The nested ``requests/{rfc}/actions/{id}`` form is rejected with HTTP 403,
    the same way the nested list and item paths are (verified live).
    """
    return build_update(ACTIONS, action_id, payload)

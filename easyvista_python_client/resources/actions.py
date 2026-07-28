"""Builders for the ticket ``actions`` sub-resource.

``list_actions`` rides the generic search builder over the top-level ``/actions``
resource (unwrapping the :class:`SearchResult` to a bare list). ``create_action``
posts a bare body nested under the parent request, which does not fit the flat-CRUD
engine, so it stays a small bespoke override alongside the ``ACTIONS`` descriptor.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from .._transport import RequestSpec
from ..filters import ev_equals_filter
from ..models.action import Action, PostAction
from ..pagination import extract_records
from .descriptor import ResourceDescriptor, build_get, build_search

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


def build_list_actions(
    rfc_number: str,
) -> tuple[RequestSpec, Callable[[Any], list[Action]]]:
    # Actions are listed via the TOP-LEVEL /actions resource filtered by the
    # request number, not a nested requests/{rfc}/actions path (which the API
    # rejects as "Unauthorized Method"). Verified against a live instance.
    # An unsafe rfc_number raises rather than degrading: ',' is a live combinator,
    # so a raw value could append conditions and list another ticket's actions. A
    # blank one must raise too — ev_equals_filter returns None for blank input, and
    # search=None would list every action just as surely.
    search = ev_equals_filter("REQUEST.RFC_NUMBER", rfc_number)
    if search is None:
        raise ValueError("rfc_number is required to list a ticket's actions")
    spec, parse_search = build_search(ACTIONS, search=search)

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

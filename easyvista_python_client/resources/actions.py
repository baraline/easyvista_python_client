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
    rfc_number: str,
    payload: PostAction,
    *,
    context: dict[str, Any] | None = None,
) -> tuple[RequestSpec, Callable[[Any], Action]]:
    # Create is nested under the request, one action per call, with a bare body
    # (NOT wrapped in an ``actions`` array) — verified against a live instance.
    spec = RequestSpec("POST", f"requests/{rfc_number}/actions", json=payload.to_api())

    def parse(data: Any) -> Action:
        # The envelope key is passed explicitly: a deployment echoing the
        # created record under an ``actions`` wrapper would otherwise hand
        # ``model_validate`` the wrapper itself, and ``extra="allow"`` accepts
        # it silently with every declared field ``None``.
        records = extract_records(data, ACTIONS.envelope_key)
        return Action.model_validate(records[0] if records else data, context=context)

    return spec, parse


def build_create_task(
    rfc_number: str,
    payload: PostTask,
    *,
    context: dict[str, Any] | None = None,
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
        # Same envelope reasoning as build_create_action's parser.
        records = extract_records(data, ACTIONS.envelope_key)
        return Action.model_validate(records[0] if records else data, context=context)

    return spec, parse


def build_search_actions(
    rfc_number: str,
    *,
    fields: Iterable[str] | str | None = None,
    max_rows: int | None = None,
    offset: int | None = None,
    context: dict[str, Any] | None = None,
) -> tuple[RequestSpec, Callable[[Any], SearchResult[Action]]]:
    """One page of a ticket's actions, envelope included.

    Filters the TOP-LEVEL ``/actions`` resource by request number, because
    there is no nested list route to prefer. In the instance OpenAPI document
    (``GET {api_root}/swagger``, read 2026-08-27 -- authoritative for that
    deployment's routes) ``requests/{rfc_number}/actions`` declares **POST
    only**, while the list and item operations live on ``/actions`` and
    ``/actions/{id}``. That is a topology fact, not a permission verdict, and
    the difference matters: an unknown path on this API answers **403**, not
    404 (measured live; date not recorded), so a 403 alone can never say
    whether a route is denied or simply absent. An earlier note here read the
    nested path's rejection as "Unauthorized Method" and inferred a profile
    restriction; the route does not exist. The
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
        ACTIONS,
        search=search,
        fields=fields,
        max_rows=max_rows,
        offset=offset,
        context=context,
    )


def build_list_actions(
    rfc_number: str,
    *,
    fields: Iterable[str] | str | None = None,
    max_rows: int | None = None,
    context: dict[str, Any] | None = None,
) -> tuple[RequestSpec, Callable[[Any], list[Action]]]:
    """One page of a ticket's actions, as a bare list.

    :func:`build_search_actions` with the envelope dropped. Returns a single
    page: a ticket with more actions than ``max_rows`` is truncated silently,
    and the dropped envelope leaves the caller no way to detect it.
    ``EasyvistaClient.iter_actions`` pages instead.
    """
    spec, parse_search = build_search_actions(
        rfc_number, fields=fields, max_rows=max_rows, context=context
    )

    def parse(data: Any) -> list[Action]:
        return parse_search(data).records

    return spec, parse


def build_get_action(
    action_id: str | int,
    *,
    context: dict[str, Any] | None = None,
) -> tuple[RequestSpec, Callable[[Any], Action]]:
    """Fetch ONE action by id.

    The item-level record is far richer than the list endpoint's: the note text
    a caller passed as ``PostAction.description`` comes back through a
    ``DESCRIPTION`` Memo sub-resource that ``list_actions`` does not return at
    all (verified live). Uses the **top-level** ``actions/{id}`` path because
    it is the only one: the instance OpenAPI document read 2026-08-27 declares
    no ``requests/{rfc}/actions/{id}`` route at all. See
    :func:`build_search_actions` for why the HTTP 403 an earlier note recorded
    against that path was never evidence of a permission restriction.
    """
    return build_get(ACTIONS, action_id, context=context)


def build_update_action(
    action_id: str | int,
    payload: ActionUpdate,
    *,
    context: dict[str, Any] | None = None,
) -> tuple[RequestSpec, Callable[[Any], Action]]:
    """Edit one action, via the TOP-LEVEL ``actions/{id}`` path.

    ``PUT`` and ``PATCH`` are declared on ``actions/{id}`` and nowhere else:
    the instance OpenAPI document read 2026-08-27 has no nested
    ``requests/{rfc}/actions/{id}`` route to send them to. See
    :func:`build_search_actions` for why the HTTP 403 an earlier note recorded
    against that path did not distinguish a denied route from an absent one.
    """
    return build_update(ACTIONS, action_id, payload, context=context)


def build_end_action(
    rfc_number: str,
    *,
    action_id: str | int | None = None,
    end_all: bool = False,
    end_date: str | None = None,
    start_date: str | None = None,
    elapsed_time: int | str | None = None,
    doneby_mail: str | None = None,
    context: dict[str, Any] | None = None,
) -> tuple[RequestSpec, Callable[[Any], Action]]:
    """Build the ``{"end_action": {...}}`` PUT spec -- report an action as done.

    Note the addressing, which is the first thing to get wrong: the path
    segment is the **ticket's RFC number**, not the action id. The action is
    named in the *body*. Sending the id in the path answers 404 even when the
    body names it too (measured 2026-09-01).

    The route and the wrapper are the vendor's own:
    https://docs.easyvista.com/docs/rest-api-finish-an-action-attached-to-an-incident-request.md
    The vendor documents ``action_id`` omitted as ending **every open action on
    the ticket**. This builder does not let that happen by omission: it is
    reachable only through ``end_all=True``, and a bare ``action_id=None`` is
    refused.

    That guard is not defensive styling. ``Action.action_id`` is legitimately
    ``None`` across this package -- :func:`build_create_action`'s response
    carries no id at all, and any ``fields=`` projection that omits
    ``ACTION_ID`` yields rows without one -- so forwarding an id a caller
    *thought* they had would otherwise select the bulk form silently. Compare
    ``delete_document``, which refuses a document with no id rather than
    addressing the collection. See the client's ``end_action`` for what ending
    measurably does to a ticket.

    Dates take the instance's own ``DATE_FORMAT``, so they are passed through
    as strings rather than accepting a ``datetime`` this package would have to
    format on a guess -- the same reasoning as
    :func:`~easyvista_python_client.resources.requests.build_close_ticket`'s
    ``end_date``. On the verified instance that format is
    ``dd/mm/yyyy hh:mm:ss`` and **ISO 8601 is refused** with HTTP 590 "Invalid
    End Date" (measured 2026-09-01 on one instance -- one instance, one date,
    so it may not generalise). ``elapsed_time`` is a number of **minutes**.

    A blank ``rfc_number`` is refused rather than allowed to build ``PUT
    actions/``, which addresses the collection instead of a ticket.
    """
    if not rfc_number or not rfc_number.strip():
        raise ValueError(
            "rfc_number is required to end an action: the path segment is the "
            "ticket's RFC number, not the action id. Blank would address "
            "'actions/' -- the collection -- instead of a ticket."
        )
    if action_id is None and not end_all:
        raise ValueError(
            "end_action needs an action_id. Omitting it is the vendor's "
            "'end every open action on this ticket' form, which on a ticket "
            "whose only open action is its workflow step ends that step and "
            "moves the ticket's status -- so it must be asked for explicitly "
            "with end_all=True. Note that action_id is legitimately None all "
            "over this package (create_action's response carries no id, and a "
            "fields= projection without ACTION_ID drops it), which is exactly "
            "the case this refusal is here to catch: recover the id by "
            "diffing list_actions across the create."
        )
    if action_id is not None and end_all:
        raise ValueError(
            "pass either action_id or end_all=True, not both: end_all is the "
            "id-less form, so naming an action contradicts it."
        )
    end: dict[str, Any] = {}
    if action_id is not None:
        end["action_id"] = action_id
    if start_date is not None:
        end["start_date"] = start_date
    if end_date is not None:
        end["end_date"] = end_date
    if elapsed_time is not None:
        end["elapsed_time"] = elapsed_time
    if doneby_mail is not None:
        end["doneby_mail"] = doneby_mail
    spec = RequestSpec("PUT", f"actions/{rfc_number}", json={"end_action": end})

    def parse(data: Any) -> Action:
        # Same envelope reasoning as build_create_action's parser. The measured
        # response is HREF-only and names the parent REQUEST, so the Action
        # this returns is empty by construction -- see the client method.
        records = extract_records(data, ACTIONS.envelope_key)
        return Action.model_validate(records[0] if records else data, context=context)

    return spec, parse

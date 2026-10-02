"""What a write may do to a ticket's workflow -- decided before it is sent.

EasyVista drives a ticket's status from its workflow, not from a field: "A
workflow is a process that handles a type of tickets, arranged in a sequence of
actions performed in steps." ... "Advancing through the steps of a workflow
changes the status of a ticket." (tier 1,
https://docs.easyvista.com/docs/workflow.md, read 2026-10-02). Of the REST
writes the vendor documents, three touch the workflow:

* creating a ticket starts it -- "3. The workflow associated with the ticket
  is started." (https://docs.easyvista.com/docs/rest-api-create-an-incident-request.md);
* the ``closed`` body on ``PUT requests/{rfc_number}`` interrupts it -- "1. The
  workflow of the ticket is interrupted."
  (https://docs.easyvista.com/docs/rest-api-close-an-incident-request.md),
  whatever status it names;
* the ``end_action`` body on ``PUT actions/{rfc_number}`` ends actions, and
  ending a workflow step's action moves the workflow on. The REST page is
  silent about the workflow; the support is the UI's Finish wizard ("The
  workflow will proceed to the next step." --
  https://docs.easyvista.com/docs/action.md) and one measurement (2026-09-01,
  one instance, 2/2, so it may not generalise).

Everything else is undocumented in workflow terms, which is not the same as
neutral: a per-instance business rule can run "On Insert/On Update" of any
record (https://docs.easyvista.com/docs/business-rule.md). So this module
names what it can, and the transport refuses anything named unless the call
site allowed it explicitly, with ``allow_workflow_effect=``.

**What gets named.** (1) The vendor's workflow-control bodies -- ``closed``,
``end_action``, ``suspended``, ``restarted`` -- as a top-level body key, in any
casing, on any path. (2) On ticket and action routes, the columns that hold or
select workflow state: a status, a catalog (which selects the workflow), the
workflow, stage and step links, an action's end date, type, parent or ticket.
(3) Ticket sub-routes that are workflow commands rather than records. Not
named: data the workflow merely reads -- text, owner, group, done-by, impact,
urgency. Reassigning an action's group or person is therefore not refused.

**This is a deny-list, and a deny-list of columns cannot be complete**: the
vendor's update pages accept "all the fields" of the table "except" a short
list. What is not named here is unclassified, not proven neutral.
"""

from __future__ import annotations

import enum
from collections.abc import Iterable, Mapping
from typing import Any
from urllib.parse import unquote


class WorkflowEffect(enum.Enum):
    """What a write may do to a ticket's workflow.

    ``INTERRUPTS``: the vendor documents the write as stopping the workflow
    (the ``closed`` body). ``ADVANCES``: the write ends actions, and ending a
    workflow step moves the workflow on (the ``end_action`` body).
    ``UNKNOWN``: the write touches workflow state, or a route that does, and
    nothing documents or measures what follows.

    Passed to ``allow_workflow_effect=`` as one member or an iterable of
    members. Deliberately not a ``str`` enum, so ``"interrupts"`` is refused
    rather than matched.
    """

    INTERRUPTS = "interrupts"
    ADVANCES = "advances"
    UNKNOWN = "unknown"


#: The vendor's workflow-control bodies, matched as a top-level key on ANY path.
_ENVELOPES: Mapping[str, WorkflowEffect] = {
    "closed": WorkflowEffect.INTERRUPTS,
    "end_action": WorkflowEffect.ADVANCES,
    "suspended": WorkflowEffect.UNKNOWN,
    "restarted": WorkflowEffect.UNKNOWN,
}

#: Columns on ``requests/{rfc}`` that hold or select workflow state. The vendor
#: excludes ``status_id``, ``sd_catalog_id``, ``initial_sd_catalog_id`` and
#: ``parent_request_id`` from the update body outright; a catalog selects which
#: workflow runs, and requalifying "starts a new workflow".
_REQUEST_COLUMNS = frozenset(
    {
        "status_id",
        "status_guid",
        "sd_catalog_id",
        "initial_sd_catalog_id",
        "catalog_guid",
        "catalog_code",
        "parent_request_id",
    }
)

#: Columns on ``actions/{id}`` that end, re-type, re-parent or move an action.
_ACTION_COLUMNS = frozenset(
    {
        "end_date_ut",
        "end_date",
        "status_id_on_terminate",
        "workflow_id",
        "stage_id",
        "process_step_id",
        "parent_action_id",
        "action_type_id",
        "action_type_guid",
        "action_type_name",
        "request_id",
        "rfc_number",
    }
)

#: Columns that would create an action already ended or tied into a step.
_CREATE_ACTION_COLUMNS = frozenset(
    {
        "end_date_ut",
        "end_date",
        "status_id_on_terminate",
        "workflow_id",
        "stage_id",
        "process_step_id",
    }
)

#: The same for a task, which is born ended: its end date is ordinary, a
#: parent is not.
_CREATE_TASK_COLUMNS = frozenset(
    {
        "status_id_on_terminate",
        "workflow_id",
        "stage_id",
        "process_step_id",
        "parent_action_id",
    }
)

#: Ticket sub-resources whose writes create or delete records. Any other
#: ``requests/{rfc}/<x>`` write -- ``close``, ``suspend``, ``restart``,
#: ``workflowstart``, or whatever a deployment adds -- is a command and is named.
_RECORD_SUBRESOURCES = frozenset({"actions", "tasks", "documents"})

_READ_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})

_METHOD_OVERRIDE_HEADERS = frozenset(
    {"x-http-method-override", "x-http-method", "x-method-override"}
)


def as_effects(
    allow: WorkflowEffect | Iterable[WorkflowEffect],
) -> frozenset[WorkflowEffect]:
    """Normalise an ``allow_workflow_effect=`` argument to a frozenset of members.

    Accepts one :class:`WorkflowEffect` or an iterable of them; ``()`` allows
    nothing. Anything else raises ``TypeError``: a string, because
    ``"interrupts"`` is not a member and iterating it yields letters; and the
    enum **class** itself, which is iterable and would allow every effect from a
    one-token typo for ``WorkflowEffect.INTERRUPTS``.
    """
    if isinstance(allow, WorkflowEffect):
        return frozenset({allow})
    if isinstance(allow, (str, bytes, type, Mapping)) or not isinstance(
        allow, Iterable
    ):
        raise TypeError(
            "allow_workflow_effect takes a WorkflowEffect member or an iterable "
            f"of members, not {allow!r}"
        )
    effects = frozenset(allow)
    strays = sorted(
        repr(item) for item in effects if not isinstance(item, WorkflowEffect)
    )
    if strays:
        raise TypeError(
            "allow_workflow_effect takes WorkflowEffect members only; got "
            + ", ".join(strays)
        )
    return effects


def _segments(path: str) -> list[str]:
    """``path``'s non-empty segments, percent-decoded and case-folded.

    Refuses a ``.`` or ``..`` segment: httpx removes dot segments from the URL
    it sends, so ``x/../requests/I1`` reaches ``requests/I1`` -- a route this
    check would otherwise not have read. No API route needs one.

    Also refuses a backslash anywhere in the path, and a segment whose
    percent-decoded form contains ``/`` or ``\\`` (``requests%2FI1%2Fclose``,
    ``requests/I1%5Cclose``): splitting on ``/`` before decoding would read
    either as one opaque segment and miss the route, yet a server may read it as
    a separator. This fails closed -- whether the server decodes ``%2F`` or
    treats ``\\`` as a separator is not measured, and no API route needs either.
    """
    bare = path.split("?", 1)[0].split("#", 1)[0]
    decoded = [unquote(part) for part in bare.split("/") if part]
    if "\\" in bare or any("/" in part or "\\" in part for part in decoded):
        raise ValueError(
            f"refusing path {path!r}: it contains an encoded slash or a "
            "backslash, which a server may read as a path separator, so the "
            "request could reach a different route from the one this check read"
        )
    segments = [part.casefold() for part in decoded]
    if any(part in {".", ".."} for part in segments):
        raise ValueError(
            f"refusing path {path!r}: it contains a dot segment, which the HTTP "
            "client collapses, so the request would reach a different route "
            "from the one written"
        )
    return segments


def _effective_method(method: str, headers: Mapping[str, str] | None) -> str:
    for name, value in (headers or {}).items():
        if name.casefold() in _METHOD_OVERRIDE_HEADERS:
            return str(value).strip().upper()
    return method.upper()


def _body_keys(body: Any) -> set[str]:
    records = (
        [body]
        if isinstance(body, Mapping)
        else [item for item in body if isinstance(item, Mapping)]
        if isinstance(body, list)
        else []
    )
    return {str(key).casefold() for record in records for key in record}


def workflow_triggers(
    method: str,
    path: str,
    body: Any = None,
    headers: Mapping[str, str] | None = None,
) -> tuple[tuple[str, WorkflowEffect], ...]:
    """Every ``(what, effect)`` this request names, envelopes first.

    ``what`` is the case-folded body key, or the route, that matched. Empty for
    a read and for an ordinary write. Raises ``ValueError`` for a path with a
    dot segment, whatever the method.
    """
    segments = _segments(path)
    verb = _effective_method(method, headers)
    if verb in _READ_METHODS:
        return ()
    keys = _body_keys(body)
    found: list[tuple[str, WorkflowEffect]] = [
        (key, _ENVELOPES[key]) for key in sorted(keys) if key in _ENVELOPES
    ]

    def columns(names: frozenset[str]) -> None:
        found.extend((key, WorkflowEffect.UNKNOWN) for key in sorted(keys & names))

    head = segments[0] if segments else ""
    if head == "requests" and len(segments) == 2:
        if segments[1] == "without-workflow":
            found.append(("requests/without-workflow", WorkflowEffect.UNKNOWN))
        else:
            if verb == "DELETE":
                found.append(("DELETE requests/{rfc}", WorkflowEffect.UNKNOWN))
            columns(_REQUEST_COLUMNS)
    elif head == "requests" and len(segments) >= 3:
        sub = segments[2]
        if sub == "actions":
            columns(_CREATE_ACTION_COLUMNS)
        elif sub == "tasks":
            columns(_CREATE_TASK_COLUMNS)
        elif sub not in _RECORD_SUBRESOURCES:
            effect = (
                WorkflowEffect.INTERRUPTS if sub == "close" else WorkflowEffect.UNKNOWN
            )
            found.append((f"requests/{{rfc}}/{sub}", effect))
    elif head == "actions" and len(segments) == 2:
        columns(_ACTION_COLUMNS)
    return tuple(found)


def classify_workflow_effects(
    method: str,
    path: str,
    body: Any = None,
    headers: Mapping[str, str] | None = None,
) -> frozenset[WorkflowEffect]:
    """The set of effects :func:`workflow_triggers` names for this request."""
    return frozenset(
        effect for _, effect in workflow_triggers(method, path, body, headers)
    )

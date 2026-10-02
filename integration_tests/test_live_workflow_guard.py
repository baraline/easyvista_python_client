"""Live checks behind the workflow guard.

``end_action`` refuses to end a workflow step unless the caller allows
``WorkflowEffect.ADVANCES``, and it tells a step from the caller's own action
with one projected item read: ``WORKFLOW_ID`` set means a step. That only works
if the read names the column on BOTH kinds of action -- if it omits the key on
a caller's action, the guard (which fails closed) would refuse every end.

The first two tests here read only. Tests below the census marker WRITE: each
takes the ``census_opt_in`` fixture first, so they run only when
``EASYVISTA_TEST_RUN_WORKFLOW_CENSUS=1`` is set in the environment, which is
how the user's explicit approval is given. Without it they skip before any
ticket is created.
"""

from __future__ import annotations

import os
import time
from collections.abc import Callable
from pathlib import Path
from typing import NamedTuple

import pytest

from easyvista_python_client import Action, ActionUpdate, EasyvistaClient, RequestUpdate

#: Recent tickets scanned for one action of each kind; bounded, so a quiet
#: instance skips instead of sweeping the whole table.
_TICKETS_TO_SCAN = 15
_LIST_PROJECTION = ["ACTION_ID", "ACTION_TYPE_ID", "WORKFLOW_ID", "END_DATE_UT"]
_PROBE_FIELDS = ["ACTION_ID", "WORKFLOW_ID"]


def _one_of_each(client: EasyvistaClient) -> tuple[int, int]:
    """Return (a workflow-step action id, a non-workflow action id)."""
    step: int | None = None
    other: int | None = None
    # The default order is oldest-first, and on the measured instance
    # (2026-10-02) the oldest tickets carry only an already-ended CALL action
    # and no workflow step, so the scan reads the newest tickets instead.
    for ticket in client.iter_tickets(
        fields=["RFC_NUMBER"], sort="REQUEST_ID DESC", max_records=_TICKETS_TO_SCAN
    ):
        if not ticket.rfc_number:
            continue
        for action in client.iter_actions(
            ticket.rfc_number, fields=_LIST_PROJECTION, max_records=200
        ):
            if action.action_id is None:
                continue
            if action.workflow_id is not None:
                step = step or action.action_id
            else:
                other = other or action.action_id
        if step is not None and other is not None:
            return step, other
    pytest.skip(
        f"no ticket among the {_TICKETS_TO_SCAN} scanned carries both a workflow "
        "step and a non-workflow action"
    )


def _probe(client: EasyvistaClient, action_id: int):
    # The same projection end_action's guard asks for, through the public read.
    return client.get_action(action_id, params={"fields": ",".join(_PROBE_FIELDS)})


def test_the_projected_item_read_names_workflow_id_on_both_kinds_of_action(
    live_client: EasyvistaClient,
) -> None:
    step, other = _one_of_each(live_client)
    step_row = _probe(live_client, step)
    other_row = _probe(live_client, other)
    assert "workflow_id" in step_row.model_fields_set
    assert step_row.workflow_id is not None
    assert "workflow_id" in other_row.model_fields_set, (
        "the projected item read omits WORKFLOW_ID on a non-workflow action: "
        "end_action's pre-flight would refuse every caller action"
    )
    assert other_row.workflow_id is None


def test_the_plain_item_read_names_workflow_id_on_both_kinds_of_action(
    live_client: EasyvistaClient,
) -> None:
    """Recorded for comparison; the guard uses the projected read."""
    step, other = _one_of_each(live_client)
    assert "workflow_id" in live_client.get_action(step).model_fields_set
    assert "workflow_id" in live_client.get_action(other).model_fields_set


# --- census: WRITES, run only with the user's explicit approval ------------

_OPT_IN_VARIABLE = "EASYVISTA_TEST_RUN_WORKFLOW_CENSUS"
_SECRETS_DIR = Path(__file__).resolve().parents[1] / "secrets"

#: Seconds between the immediate after-read and the settled one. The assertions
#: run on the settled read; both are printed, so a write that lands late, or
#: reverts, shows up in the output instead of reading as a clean pass.
_SETTLE_SECONDS = 5


@pytest.fixture(scope="session")
def census_opt_in() -> None:
    """Skip the census unless the environment says the user approved the writes.

    Session-scoped and listed first by every census test, so it is evaluated
    before any other fixture and before a ticket can be created.
    """
    if os.environ.get(_OPT_IN_VARIABLE) != "1":
        pytest.skip(
            "the workflow census WRITES to the live instance (creates tickets, "
            f"reassigns a workflow step); set {_OPT_IN_VARIABLE}=1 to run it"
        )


def _resolve_local(env_names: tuple[str, ...], filename: str) -> str | None:
    """Env var first, then ``secrets/<filename>``; ``None`` when neither is set."""
    for name in env_names:
        value = os.environ.get(name)
        if value and value.strip():
            return value.strip()
    path = _SECRETS_DIR / filename
    if path.is_file():
        text = path.read_text(encoding="utf-8").strip()
        if text:
            return text
    return None


# Module-local on purpose: this file must also run from a checkout whose
# conftest.py lacks this fixture.
@pytest.fixture(scope="session")
def live_reassign_config() -> dict[str, str]:
    """The group (and optionally the person) a workflow step is reassigned to.

    Separate from every other write config so that an instance without one
    skips only the reassignment census. The group must differ from the one a
    fresh ticket's workflow step is assigned to, and reassigning to the group
    or to the person may notify them.
    """
    group = _resolve_local(
        ("EASYVISTA_TEST_REASSIGN_GROUP_ID",), "easyvista_test_reassign_group_id"
    )
    if not group:
        pytest.skip(
            "the reassignment census needs EASYVISTA_TEST_REASSIGN_GROUP_ID "
            "(or secrets/easyvista_test_reassign_group_id)"
        )
    resolved = {"group_id": group}
    person = _resolve_local(
        ("EASYVISTA_TEST_REASSIGN_DONE_BY_ID",), "easyvista_test_reassign_done_by_id"
    )
    if person:
        resolved["done_by_id"] = person
    return resolved


_CENSUS_PROJECTION = [
    "ACTION_ID",
    "ACTION_TYPE_ID",
    "WORKFLOW_ID",
    "END_DATE_UT",
    "GROUP_ID",
    "DONE_BY_ID",
    "REQUEST_ID",
]

#: The item read the before and after states both go through, so a before/after
#: difference can never come from comparing two different read paths.
_ITEM_FIELDS = "ACTION_ID,REQUEST_ID,GROUP_ID,DONE_BY_ID,END_DATE_UT,WORKFLOW_ID"


def _require(condition: object, label: str) -> None:
    """Assert ``condition``; the failure text is ``label`` and nothing else.

    The caller evaluates the condition as an argument, and it is bound to a
    plain local here before the assert, so pytest's assertion rewriter has no
    operand to render. An ``assert action.group_id == target`` would print the
    whole ``Action`` -- hrefs and labels -- on failure (P2; see ``_assertions.py``).
    """
    __tracebackhide__ = True
    ok = bool(condition)
    assert ok, label


def _target(config: dict[str, str], key: str) -> int:
    """The configured id as a positive int; fails with a label, never the value.

    Called before ``ticket_factory()`` so a misconfiguration creates no ticket.
    """
    try:
        value = int(config[key])
    except ValueError:
        value = 0
    if value <= 0:
        pytest.fail(f"the configured {key} must be a positive integer", pytrace=False)
    return value


class _Snapshot(NamedTuple):
    """Everything the census compares, read in one pass."""

    request_id: int | None
    status_id: int | None
    ticket_end: object
    ticket_end_named: bool
    open_ids: frozenset[int]
    row_ids: frozenset[int]
    step: Action


def _actions(client: EasyvistaClient, rfc: str) -> list[Action]:
    rows = list(client.iter_actions(rfc, fields=_CENSUS_PROJECTION, max_records=500))
    for row in rows:
        _require(
            "end_date_ut" in row.model_fields_set,
            "END_DATE_UT is not named by the projected list read",
        )
        _require(
            isinstance(row.action_id, int),
            "a row of the projected list read carries no ACTION_ID",
        )
    return rows


def _the_open_step(client: EasyvistaClient, rfc: str) -> Action:
    steps = [
        row
        for row in _actions(client, rfc)
        if row.end_date_ut is None and row.workflow_id is not None
    ]
    _require(
        len(steps) == 1, "the ticket does not carry exactly one open workflow step"
    )
    step = steps[0]
    _require(
        isinstance(step.action_id, int) and step.action_id > 0,
        "the open workflow step carries no usable ACTION_ID",
    )
    return step


def _read(client: EasyvistaClient, action_id: int) -> Action:
    return client.get_action(action_id, params={"fields": _ITEM_FIELDS})


def _snapshot(client: EasyvistaClient, rfc: str, step_id: int) -> _Snapshot:
    ticket = client.get_ticket(rfc)
    rows = _actions(client, rfc)
    return _Snapshot(
        request_id=ticket.request_id,
        status_id=ticket.status_id,
        ticket_end=ticket.end_date_ut,
        ticket_end_named="end_date_ut" in ticket.model_fields_set,
        open_ids=frozenset(
            row.action_id
            for row in rows
            if row.end_date_ut is None and row.action_id is not None
        ),
        row_ids=frozenset(row.action_id for row in rows if row.action_id is not None),
        step=_read(client, step_id),
    )


def _describe(before: _Snapshot, after: _Snapshot, column: str | None) -> str:
    stored = f"stored={getattr(after.step, column)} " if column else ""
    return (
        f"{stored}step_open={after.step.end_date_ut is None} "
        f"status {before.status_id}->{after.status_id} "
        f"ticket_end_date_ut {before.ticket_end}->{after.ticket_end} "
        f"open {sorted(before.open_ids)}->{sorted(after.open_ids)} "
        f"new_rows={sorted(after.row_ids - before.row_ids)}"
    )


def _check_before(step: Action, before: _Snapshot) -> None:
    """Preconditions that make a later "unchanged" verdict mean something.

    Run before the write, so a vacuous read (a column that is not named, a step
    that belongs to another ticket) stops the census with nothing sent.
    """
    _require(before.request_id is not None, "the fresh ticket carries no REQUEST_ID")
    _require(step.request_id is not None, "the listed step carries no REQUEST_ID")
    _require(
        step.request_id == before.request_id,
        "the listed step does not belong to the fresh ticket",
    )
    _require(
        before.step.request_id == before.request_id,
        "the step's item read does not belong to the fresh ticket",
    )
    _require(before.status_id is not None, "the ticket's STATUS_ID reads empty")
    _require(
        before.ticket_end_named,
        "END_DATE_UT is not named by the ticket read, so 'unchanged' is vacuous",
    )
    _require(
        "end_date_ut" in before.step.model_fields_set,
        "END_DATE_UT is not named by the projected item read",
    )
    _require(
        before.step.end_date_ut is None, "the step is already ended before the write"
    )
    _require(before.step.workflow_id is not None, "the step reads as no workflow step")


def _check_unchanged(before: _Snapshot, after: _Snapshot) -> None:
    """The workflow-neutral half of the verdict, on the settled read."""
    _require(
        "end_date_ut" in after.step.model_fields_set,
        "END_DATE_UT is not named by the settled item read",
    )
    _require(after.step.end_date_ut is None, "the write ENDED the workflow step")
    _require(
        after.open_ids == before.open_ids,
        "the write changed the ticket's open actions",
    )
    _require(after.status_id == before.status_id, "the write moved the ticket's status")
    _require(
        after.ticket_end == before.ticket_end,
        "the write changed the ticket's END_DATE_UT",
    )


def _write_and_observe(
    client: EasyvistaClient,
    rfc: str,
    step_id: int,
    label: str,
    before: _Snapshot,
    send: Callable[[], object],
    column: str | None = None,
) -> tuple[Exception | None, _Snapshot]:
    """Send one write, then read the state twice; a failed write still reads.

    A raised write prints only the exception's type and status code (the message
    is server prose this suite did not author), and is handed back for the caller
    to re-raise once the reads are printed. Returns the settled snapshot.
    """
    error: Exception | None = None
    try:
        send()
    except Exception as exc:
        error = exc
        print(
            f"CENSUS {rfc} {label}: the write raised {type(exc).__name__} "
            f"status_code={getattr(exc, 'status_code', None)}"
        )
    immediate = _snapshot(client, rfc, step_id)
    print(f"CENSUS {rfc} {label} immediate: {_describe(before, immediate, column)}")
    time.sleep(_SETTLE_SECONDS)
    settled = _snapshot(client, rfc, step_id)
    print(
        f"CENSUS {rfc} {label} +{_SETTLE_SECONDS}s: "
        f"{_describe(before, settled, column)}"
    )
    return error, settled


def _census(
    client: EasyvistaClient,
    write_client: EasyvistaClient,
    rfc: str,
    step: Action,
    column: str,
    target: int,
    *,
    require_current: bool,
) -> None:
    """Write ``target`` into ``column`` of the step and record what moved.

    The lower-case body key is sent first, as ``PostAction``'s verified create
    body spells it. If the column did not store, the upper-case key goes to the
    SAME step, so the key spelling is settled without a second ticket; both
    outcomes are printed and the test passes if either stored.

    ``require_current`` is for a column a workflow step is born with (the
    group). ``DONE_BY_ID`` is documented empty on a generated step, so there an
    empty before-value is the expected shape; the column must still be NAMED by
    the read, which is what tells empty from unprojected.
    """
    step_id = step.action_id  # a positive int: _the_open_step refuses anything else
    before = _snapshot(client, rfc, step_id)
    _check_before(step, before)
    name = column.upper()
    _require(
        column in before.step.model_fields_set,
        f"{name} is not named by the projected item read",
    )
    current = getattr(before.step, column)
    if require_current:
        _require(
            current is not None, f"{name} reads empty on the step before the write"
        )
    _require(current != target, f"{name} already equals the target before the write")
    print(f"CENSUS {rfc}: before {column}={current} target={target}")

    outcomes: dict[str, bool] = {}
    for key in (column, name):
        body = {key: target}
        error, settled = _write_and_observe(
            client,
            rfc,
            step_id,
            f"key={key}",
            before,
            lambda body=body: write_client.update_action(
                step_id, ActionUpdate(extra_payload=body)
            ),
            column,
        )
        if error is not None:
            raise error
        _check_unchanged(before, settled)
        outcomes[key] = getattr(settled.step, column) == target
        if outcomes[key]:
            break
    print(f"CENSUS {rfc}: stored by key spelling {outcomes}")
    _require(
        any(outcomes.values()),
        f"neither {column!r} nor {name!r} was stored -- a 200 is not a receipt",
    )


def test_reassigning_the_workflow_step_to_a_group_keeps_it_open(
    census_opt_in,
    live_client,
    live_write_client,
    ticket_factory,
    live_reassign_config,
) -> None:
    target = _target(live_reassign_config, "group_id")
    rfc = ticket_factory()
    step = _the_open_step(live_client, rfc)
    _census(
        live_client,
        live_write_client,
        rfc,
        step,
        "group_id",
        target,
        require_current=True,
    )


def test_reassigning_the_workflow_step_to_a_person_keeps_it_open(
    census_opt_in,
    live_client,
    live_write_client,
    ticket_factory,
    live_reassign_config,
) -> None:
    if "done_by_id" not in live_reassign_config:
        pytest.skip("EASYVISTA_TEST_REASSIGN_DONE_BY_ID not configured")
    target = _target(live_reassign_config, "done_by_id")
    rfc = ticket_factory()
    step = _the_open_step(live_client, rfc)
    _census(
        live_client,
        live_write_client,
        rfc,
        step,
        "done_by_id",
        target,
        require_current=False,
    )


def test_the_ticket_writes_the_sync_makes_keep_the_workflow_step_open(
    census_opt_in, live_client, live_write_client, ticket_factory
) -> None:
    """Title is what the sync writes each sweep; only description was censused."""
    rfc = ticket_factory()
    step = _the_open_step(live_client, rfc)
    step_id = step.action_id  # a positive int: _the_open_step refuses anything else
    before = _snapshot(live_client, rfc, step_id)
    _check_before(step, before)
    error, settled = _write_and_observe(
        live_client,
        rfc,
        step_id,
        "title",
        before,
        lambda: live_write_client.update_ticket(
            rfc, RequestUpdate(title=f"{rfc} census title")
        ),
    )
    if error is not None:
        raise error
    _check_unchanged(before, settled)

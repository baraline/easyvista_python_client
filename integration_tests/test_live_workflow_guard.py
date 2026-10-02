"""Live checks behind the workflow guard.

``end_action`` refuses to end a workflow step unless the caller allows
``WorkflowEffect.ADVANCES``, and it tells a step from the caller's own action
with one projected item read: ``WORKFLOW_ID`` set means a step. That only works
if the read names the column on BOTH kinds of action -- if it omits the key on
a caller's action, the guard (which fails closed) would refuse every end.

The first two tests here read only. Tests below the census marker WRITE and
run only with the user's explicit approval.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from easyvista_python_client import ActionUpdate, EasyvistaClient, RequestUpdate

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

_SECRETS_DIR = Path(__file__).resolve().parents[1] / "secrets"


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
    fresh ticket's workflow step is assigned to, and reassigning to it may
    notify it.
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


#: The body key the reassignment sends. Lower case, as PostAction's verified
#: create body spells it; if the census finds it silently dropped, re-run with
#: "GROUP_ID" and record which spelling stored.
_GROUP_KEY = "group_id"
_DONE_BY_KEY = "done_by_id"
_CENSUS_PROJECTION = [
    "ACTION_ID",
    "ACTION_TYPE_ID",
    "WORKFLOW_ID",
    "END_DATE_UT",
    "GROUP_ID",
    "DONE_BY_ID",
]


def _actions(client: EasyvistaClient, rfc: str):
    rows = list(client.iter_actions(rfc, fields=_CENSUS_PROJECTION, max_records=500))
    for row in rows:
        assert "end_date_ut" in row.model_fields_set, "END_DATE_UT not projected"
    return rows


def _open_ids(client: EasyvistaClient, rfc: str) -> set[int | None]:
    return {row.action_id for row in _actions(client, rfc) if row.end_date_ut is None}


def _the_open_step(client: EasyvistaClient, rfc: str):
    steps = [
        row
        for row in _actions(client, rfc)
        if row.end_date_ut is None and row.workflow_id is not None
    ]
    assert len(steps) == 1, f"expected one open workflow step, found {len(steps)}"
    return steps[0]


def _census(client, write_client, rfc, step, body, column):
    before_ticket = client.get_ticket(rfc)
    rows_before = _actions(client, rfc)
    before = {row.action_id for row in rows_before}
    open_before = {row.action_id for row in rows_before if row.end_date_ut is None}

    write_client.update_action(step.action_id, ActionUpdate(extra_payload=body))

    after_step = client.get_action(step.action_id)
    after_ticket = client.get_ticket(rfc)
    rows = _actions(client, rfc)
    open_after = {row.action_id for row in rows if row.end_date_ut is None}
    new_rows = sorted({row.action_id for row in rows} - before)
    print(
        f"CENSUS {rfc}: body={body} stored={getattr(after_step, column)} "
        f"step_open={after_step.end_date_ut is None} "
        f"status {before_ticket.status_id}->{after_ticket.status_id} "
        f"open {sorted(open_before)}->{sorted(open_after)} new_rows={new_rows}"
    )
    assert after_step.end_date_ut is None, "the write ENDED the workflow step"
    assert open_after == open_before, "the write changed the ticket's open actions"
    assert after_ticket.status_id == before_ticket.status_id, "the status moved"
    assert after_ticket.end_date_ut == before_ticket.end_date_ut
    return after_step


def test_reassigning_the_workflow_step_to_a_group_keeps_it_open(
    live_client, live_write_client, ticket_factory, live_reassign_config
) -> None:
    rfc = ticket_factory()
    step = _the_open_step(live_client, rfc)
    target = int(live_reassign_config["group_id"])
    assert step.group_id != target, "choose a group other than the step's own"
    after = _census(
        live_client, live_write_client, rfc, step, {_GROUP_KEY: target}, "group_id"
    )
    assert after.group_id == target, (
        f"{_GROUP_KEY!r} was not stored -- a 200 is not a receipt; try 'GROUP_ID'"
    )


def test_reassigning_the_workflow_step_to_a_person_keeps_it_open(
    live_client, live_write_client, ticket_factory, live_reassign_config
) -> None:
    if "done_by_id" not in live_reassign_config:
        pytest.skip("EASYVISTA_TEST_REASSIGN_DONE_BY_ID not configured")
    rfc = ticket_factory()
    step = _the_open_step(live_client, rfc)
    target = int(live_reassign_config["done_by_id"])
    after = _census(
        live_client, live_write_client, rfc, step, {_DONE_BY_KEY: target}, "done_by_id"
    )
    assert after.done_by_id == target, f"{_DONE_BY_KEY!r} was not stored"


def test_the_ticket_writes_the_sync_makes_keep_the_workflow_step_open(
    live_client, live_write_client, ticket_factory
) -> None:
    """Title is what the sync writes each sweep; only description was censused."""
    rfc = ticket_factory()
    _the_open_step(live_client, rfc)
    open_before = _open_ids(live_client, rfc)
    status_before = live_client.get_ticket(rfc).status_id
    live_write_client.update_ticket(rfc, RequestUpdate(title=f"{rfc} census title"))
    open_after = _open_ids(live_client, rfc)
    assert open_after == open_before
    assert live_client.get_ticket(rfc).status_id == status_before

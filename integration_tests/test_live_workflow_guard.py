"""Live checks behind the workflow guard.

``end_action`` refuses to end a workflow step unless the caller allows
``WorkflowEffect.ADVANCES``, and it tells a step from the caller's own action
with one projected item read: ``WORKFLOW_ID`` set means a step. That only works
if the read names the column on BOTH kinds of action -- if it omits the key on
a caller's action, the guard (which fails closed) would refuse every end.

The first test here reads only. Tests below the census marker WRITE and run
only with the user's explicit approval.
"""

from __future__ import annotations

import pytest

from easyvista_python_client import EasyvistaClient

#: Recent tickets scanned for one action of each kind; bounded, so a quiet
#: instance skips instead of sweeping the whole table.
_TICKETS_TO_SCAN = 15
_LIST_PROJECTION = ["ACTION_ID", "ACTION_TYPE_ID", "WORKFLOW_ID", "END_DATE_UT"]
_PROBE_FIELDS = ["ACTION_ID", "WORKFLOW_ID"]


def _one_of_each(client: EasyvistaClient) -> tuple[int, int]:
    """Return (a workflow-step action id, a non-workflow action id)."""
    step: int | None = None
    other: int | None = None
    for ticket in client.iter_tickets(
        fields=["RFC_NUMBER"], max_records=_TICKETS_TO_SCAN
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

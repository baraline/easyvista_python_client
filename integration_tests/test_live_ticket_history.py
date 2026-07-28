"""Live coverage of a ticket's history: its actions and the rendered context.

Skipped without credentials; never runs in CI. Action bodies are synthetic
``EVCLI<nonce>`` markers this module authors, so every content assertion
compares our own string against itself (design principle P2).

This module WRITES: each test takes a fresh ticket from ``ticket_factory``
(closed in teardown) and, where noted, creates one action on it. The
action-creating tests skip without ``live_action_config``.
"""

from __future__ import annotations

import uuid

import pytest

from easyvista_python_client import Action, EasyvistaClient, PostAction
from easyvista_python_client._html import html_to_text
from integration_tests._assertions import assert_populated, assert_shape

pytestmark = pytest.mark.integration


@pytest.fixture
def ticket_with_action(
    live_client: EasyvistaClient, ticket_factory, live_action_config
):
    """A fresh ticket plus one action we created. Yields ``(rfc, marker, action_id)``.

    The id comes from diffing ``list_actions`` across the create, not from the
    create response: that response is an HREF naming the parent request and
    carries no ``ACTION_ID`` (verified live). A fresh ticket already carries
    ~11 workflow-generated actions, so ``list_actions(rfc)[0]`` is not ours --
    every assertion about our action addresses it by this id.
    """
    rfc = ticket_factory()
    marker = f"EVCLI{uuid.uuid4().hex[:10].upper()}ACTIONBODY"
    before = {a.action_id for a in live_client.list_actions(rfc)}
    live_client.create_action(
        rfc,
        PostAction(
            action_type_id=int(live_action_config["action_type_id"]),
            group_id=int(live_action_config["group_id"]),
            description=marker,
        ),
    )
    fresh = [a for a in live_client.list_actions(rfc) if a.action_id not in before]
    assert len(fresh) == 1, (
        f"expected exactly 1 new action on {rfc} after creating one, got "
        f"{len(fresh)} -- either list_actions is not scoping to this ticket, "
        f"or a workflow step wrote to it concurrently"
    )
    action_id = fresh[0].action_id
    assert action_id is not None, "listed action carries no ACTION_ID"
    return rfc, marker, action_id


def test_list_actions_filters_to_the_requested_ticket(
    live_client: EasyvistaClient, ticket_factory, live_action_config
):
    # THE decisive assertion of this module, and it has to be SPATIAL rather
    # than temporal to be worth anything. An earlier before/after delta on a
    # single ticket was not decisive: if list_actions returned the whole
    # ~35,900-row /actions table, the delta across our own create would still
    # be +1 on a quiet instance, so a broken filter looked identical to a
    # working one.
    #
    # Comparing two fresh tickets removes that dependence on background write
    # activity entirely. A whole-table response returns the same rows for both,
    # so the sets would be equal and our action would appear under BOTH -- which
    # is exactly what this asserts cannot happen. This API silently drops a
    # search condition it cannot honour and returns everything rather than
    # erroring, which is why the guard has to be this explicit.
    rfc_a = ticket_factory()
    rfc_b = ticket_factory()
    before_a = {a.action_id for a in live_client.list_actions(rfc_a)}
    live_client.create_action(
        rfc_a,
        PostAction(
            action_type_id=int(live_action_config["action_type_id"]),
            group_id=int(live_action_config["group_id"]),
            description=f"EVCLI{uuid.uuid4().hex[:10].upper()}FILTERPROBE",
        ),
    )
    ids_a = {a.action_id for a in live_client.list_actions(rfc_a)}
    ids_b = {a.action_id for a in live_client.list_actions(rfc_b)}

    new_ids = ids_a - before_a
    assert len(new_ids) == 1, (
        f"expected exactly 1 new action on {rfc_a} after creating one, got "
        f"{len(new_ids)}"
    )
    assert ids_a != ids_b, (
        f"list_actions returned the same {len(ids_a)} action ids for {rfc_a} "
        f"and {rfc_b} -- it is not scoping to the requested ticket"
    )
    assert not (new_ids & ids_b), (
        f"the action created on {rfc_a} also appears under {rfc_b} -- "
        f"list_actions is returning unrelated tickets' actions"
    )


def test_list_actions_returns_typed_records(
    live_client: EasyvistaClient, ticket_with_action
):
    rfc, _, action_id = ticket_with_action
    listed = live_client.list_actions(rfc)
    assert listed, f"expected at least 1 action on {rfc}, got 0"
    assert_shape(listed[0], Action, "listed action")
    assert any(a.action_id == action_id for a in listed), (
        f"the action we created ({action_id}) is not in list_actions for {rfc}"
    )


def test_created_action_text_is_readable(
    live_client: EasyvistaClient, ticket_with_action
):
    # Phase 0 (U5) found the marker is NOT on Action.comment / COMMENT at all
    # -- not on the list endpoint, and not on the item-level fetch either,
    # where COMMENT is its own unrelated href sub-resource. It is on
    # DESCRIPTION, which only the item-level GET returns, as a Memo-shaped
    # href -- the same shape resolve_memo already handles for a ticket's own
    # DESCRIPTION in Task 8.
    _rfc, marker, action_id = ticket_with_action
    action = live_client.get_action(action_id)
    href = (
        action.description.get("HREF") if isinstance(action.description, dict) else None
    )
    assert href, f"action {action_id} carries no DESCRIPTION href"
    text = live_client.resolve_memo(href)
    assert marker in html_to_text(text or ""), (
        "the created action's body is not readable from its DESCRIPTION memo"
    )


def test_ticket_context_resolves_the_action_body(
    live_client: EasyvistaClient, ticket_with_action
):
    # The Task 10 fix, end to end: before it, get_ticket_context left every
    # action body empty because it read Action.comment.
    rfc, marker, action_id = ticket_with_action
    context = live_client.get_ticket_context(rfc)
    ours = next((a for a in context.actions if a.action_id == action_id), None)
    assert ours is not None, f"action {action_id} missing from the context bundle"
    assert marker in html_to_text(
        ours.description if isinstance(ours.description, str) else ""
    ), "get_ticket_context did not resolve the action's note text"


def test_action_type_reference_resolves(
    live_client: EasyvistaClient, ticket_with_action
):
    _rfc, _, action_id = ticket_with_action
    action = live_client.get_action(action_id)
    assert_populated(
        action.reference("ACTION_TYPE").display, "ACTION_TYPE reference display"
    )


def test_ticket_context_bundles_the_conversation(
    live_client: EasyvistaClient, ticket_with_action
):
    # Proves the bundle assembles and carries our action. Narrative-content
    # resolution is NOT re-asserted here -- it has dedicated coverage in
    # test_live_ticket_metadata.py, and on this instance DESCRIPTION is unused
    # while a factory ticket's COMMENT is never written (Task 8's finding), so
    # asserting either here would pin an instance fact this test is not about.
    rfc, _, action_id = ticket_with_action
    context = live_client.get_ticket_context(rfc)
    assert context.ticket.rfc_number == rfc
    assert any(a.action_id == action_id for a in context.actions), (
        f"action {action_id} missing from the context bundle for {rfc}"
    )
    assert isinstance(context.documents, list)
    assert context.description is None or isinstance(context.description, str)
    assert context.comment is None or isinstance(context.comment, str)


def test_ticket_context_markdown_carries_the_action_and_no_api_urls(
    live_client: EasyvistaClient, ticket_with_action
):
    rfc, marker, _ = ticket_with_action
    markdown = live_client.get_ticket_context(rfc).to_markdown()
    assert marker in markdown, "the action body is missing from the rendered Markdown"
    assert live_client.config.api_root not in markdown, (
        "the rendered Markdown leaked an API URL"
    )

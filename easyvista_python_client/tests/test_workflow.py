"""The workflow-effect classifier: what a request may do to a ticket's workflow."""

import pytest

from easyvista_python_client import EasyvistaError, EasyvistaWorkflowEffectRefused
from easyvista_python_client.workflow import (
    WorkflowEffect,
    as_effects,
    classify_workflow_effects,
    workflow_triggers,
)

I, A, U = (  # noqa: E741 -- short aliases keep the parametrised table readable
    WorkflowEffect.INTERRUPTS,
    WorkflowEffect.ADVANCES,
    WorkflowEffect.UNKNOWN,
)


@pytest.mark.parametrize(
    ("method", "path", "body", "expected"),
    [
        # The vendor's workflow-control bodies, on the routes they belong to.
        ("PUT", "requests/I1", {"closed": {"status_GUID": "{G}"}}, {I}),
        ("PUT", "actions/I1", {"end_action": {"action_id": 1}}, {A}),
        ("PUT", "requests/I1", {"suspended": {}}, {U}),
        ("PUT", "requests/I1", {"restarted": {}}, {U}),
        # ... matched case-insensitively, on any path, and inside a list body.
        ("PUT", "requests/I1", {"Closed": {}}, {I}),
        ("PUT", "actions/60350", {"END_ACTION": {}}, {A}),
        ("PUT", "departments/7", {"closed": {}}, {I}),
        ("PUT", "requests/I1", [{"closed": {}}], {I}),
        # Ticket columns that hold or select workflow state.
        ("PUT", "requests/I1", {"STATUS_ID": 12}, {U}),
        ("PUT", "requests/I1", {"status_guid": "{G}"}, {U}),
        ("PUT", "requests/I1", {"SD_CATALOG_ID": 3}, {U}),
        ("PUT", "requests/I1", {"initial_sd_catalog_id": 3}, {U}),
        ("PUT", "requests/I1", {"catalog_guid": "{C}"}, {U}),
        ("PUT", "requests/I1", {"catalog_code": "X"}, {U}),
        ("PUT", "requests/I1", {"parent_request_id": 9}, {U}),
        # Action columns that end, re-type, re-parent or move an action.
        ("PUT", "actions/60350", {"END_DATE_UT": "01/01/2026 10:00:00"}, {U}),
        ("PUT", "actions/60350", {"workflow_id": 1}, {U}),
        ("PUT", "actions/60350", {"ACTION_TYPE_ID": 20}, {U}),
        ("PUT", "actions/60350", {"parent_action_id": 1}, {U}),
        ("PUT", "actions/60350", {"request_id": 5}, {U}),
        # Create routes: an action born ended, a task tied to a step.
        (
            "POST",
            "requests/I1/actions",
            {"action_type_id": 94, "end_date_ut": "x"},
            {U},
        ),
        (
            "POST",
            "requests/I1/tasks",
            {"action_type_id": 94, "parent_action_id": 1},
            {U},
        ),
        # Workflow routes.
        ("PUT", "requests/I1/close", {}, {I}),
        ("PATCH", "requests/I1/suspend", {}, {U}),
        ("PUT", "requests/I1/restart", {}, {U}),
        ("PUT", "requests/I1/workflowstart", None, {U}),
        ("DELETE", "requests/I1", None, {U}),
        ("POST", "requests/without-workflow", {"requests": [{}]}, {U}),
        # Two effects at once.
        ("PUT", "requests/I1", {"closed": {}, "status_id": 8}, {I, U}),
    ],
)
def test_names_what_a_write_may_do_to_the_workflow(method, path, body, expected):
    assert classify_workflow_effects(method, path, body) == frozenset(expected)


@pytest.mark.parametrize(
    ("method", "path", "body"),
    [
        # What the package's typed writes send, and what itsm_synchronisation sends.
        ("POST", "requests", {"requests": [{"catalog_code": "C", "title": "t"}]}),
        (
            "PUT",
            "requests/I1",
            {
                "title": "t",
                "description": "d",
                "impact_id": 3,
                "owner_id": 7,
                "external_reference": "m",
            },
        ),
        ("PUT", "actions/60350", {"description": "edited"}),
        # Reassignment is supported, so it is not named (design decision e).
        ("PUT", "actions/60350", {"GROUP_ID": 57, "DONE_BY_ID": 12}),
        ("PUT", "actions/60350", {"group_id": 57}),
        (
            "POST",
            "requests/I1/actions",
            {"action_type_id": 94, "group_id": 3, "parent_action_id": 1},
        ),
        (
            "POST",
            "requests/I1/tasks",
            {"action_type_id": 94, "group_id": 3, "end_date_ut": "x"},
        ),
        ("POST", "requests/I1/documents", None),
        ("DELETE", "requests/I1/documents/5", None),
        ("POST", "groups", {"groups": [{}]}),
        # Reads name nothing, whatever the body.
        ("GET", "requests/I1", None),
        ("HEAD", "requests/I1", None),
        ("GET", "requests/I1", {"closed": {}}),
    ],
)
def test_names_nothing_for_ordinary_writes_and_reads(method, path, body):
    assert classify_workflow_effects(method, path, body) == frozenset()


def test_a_method_override_header_is_read_as_the_method():
    effects = classify_workflow_effects(
        "GET", "requests/I1", {"closed": {}}, {"X-HTTP-Method-Override": "put"}
    )
    assert effects == {I}


def test_query_string_case_and_doubled_slashes_do_not_hide_a_route():
    assert classify_workflow_effects("PUT", "/requests//I1/?x=1", {"status_id": 1}) == {
        U
    }
    assert classify_workflow_effects("PUT", "REQUESTS/I1/CLOSE", {}) == {I}


@pytest.mark.parametrize(
    "path",
    [
        "x/../requests/I1",
        "./requests/I1",
        "requests/I1/.",
        "requests/%2e%2e/I1",
        "../50005/requests/I1",
    ],
)
def test_a_dot_segment_is_refused_outright(path):
    with pytest.raises(ValueError, match="dot segment"):
        workflow_triggers("PUT", path, {"title": "t"})


@pytest.mark.parametrize(
    "path",
    [
        "requests%2FI1%2Fclose",
        "requests%2fI1/close",
        "requests\\I1\\close",
        "requests/I1%5Cclose",
    ],
)
def test_an_encoded_slash_or_a_backslash_is_refused_outright(path):
    with pytest.raises(ValueError, match="encoded slash or a backslash"):
        workflow_triggers("PUT", path, {})


def test_triggers_name_the_key_that_matched_envelopes_first():
    assert workflow_triggers("PUT", "requests/I1", {"STATUS_ID": 8, "closed": {}}) == (
        ("closed", I),
        ("status_id", U),
    )


@pytest.mark.parametrize(
    ("allow", "expected"),
    [(I, {I}), ((), set()), ([I, A], {I, A}), (frozenset({U}), {U})],
)
def test_as_effects_accepts_a_member_or_an_iterable_of_members(allow, expected):
    assert as_effects(allow) == frozenset(expected)


@pytest.mark.parametrize(
    "allow",
    [
        WorkflowEffect,
        "interrupts",
        b"x",
        ["interrupts"],
        [I, "advances"],
        1,
        None,
        {"a": I},
    ],
)
def test_as_effects_refuses_anything_else(allow):
    with pytest.raises(TypeError):
        as_effects(allow)


def test_the_refusal_is_a_value_error_and_not_an_easyvista_error():
    exc = EasyvistaWorkflowEffectRefused(
        "no", effects=frozenset({I}), triggers=(("closed", I),)
    )
    assert isinstance(exc, ValueError)
    assert not isinstance(exc, EasyvistaError)
    assert exc.effects == {I}
    assert exc.triggers == (("closed", I),)
    assert str(exc) == "no"

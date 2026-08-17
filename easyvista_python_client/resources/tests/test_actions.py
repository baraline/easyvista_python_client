import pytest

from easyvista_python_client.models.action import Action, ActionUpdate, PostAction
from easyvista_python_client.resources import actions as a
from easyvista_python_client.resources.actions import (
    build_get_action,
    build_list_actions,
    build_update_action,
)


def test_action_accepts_object_action_type():
    # The live list returns ACTION_TYPE as a nested object, not a string.
    act = Action.model_validate(
        {"ACTION_ID": 1, "ACTION_TYPE": {"ACTION_TYPE_ID": "7", "NAME_FR": "Prise"}}
    )
    assert act.action_id == 1
    assert isinstance(act.action_type, dict)


def test_build_create_action_bare_body_and_path():
    spec, parser = a.build_create_action(
        "I1", PostAction(action_type_id=94, group_id=3, description="looking into it")
    )
    assert spec.method == "POST"
    assert spec.path == "requests/I1/actions"
    assert spec.json == {
        "action_type_id": 94,
        "group_id": 3,
        "description": "looking into it",
    }
    parsed = parser({"records": [{"ACTION_ID": 9, "COMMENT": "looking into it"}]})
    assert parsed.action_id == 9


def test_build_create_action_custom_fields_prefix():
    spec, _ = a.build_create_action("I1", PostAction(custom_fields={"team": "L2"}))
    assert spec.json == {"e_team": "L2"}


def test_build_list_actions_uses_top_level_filtered_endpoint():
    spec, parser = a.build_list_actions("I1")
    assert spec.method == "GET"
    assert spec.path == "actions"
    assert spec.params == {"search": 'REQUEST.RFC_NUMBER:"I1"'}
    parsed = parser({"records": [{"ACTION_ID": 1}, {"ACTION_ID": 2}]})
    assert [x.action_id for x in parsed] == [1, 2]


def test_build_list_actions_rejects_unsafe_rfc():
    """An RFC number with a quote is a caller bug; there is no sensible fallback.

    Left raw it could append a ',' condition and list another ticket's actions.
    """
    with pytest.raises(ValueError):
        a.build_list_actions('I240101_0001",REQUEST.RFC_NUMBER:"I240101_0002')


@pytest.mark.parametrize("rfc", ["", "   "])
def test_build_list_actions_rejects_blank_rfc(rfc):
    """A blank rfc_number must not degrade into an unfiltered list.

    ev_equals_filter returns None for blank input, and passing search=None to
    build_search would list EVERY ticket's actions — the same class of failure
    this fix exists to prevent, arriving by a different route.
    """
    with pytest.raises(ValueError):
        a.build_list_actions(rfc)


def test_build_list_actions_filters_by_rfc():
    spec, _ = a.build_list_actions("I240101_0001")
    assert spec.params["search"] == 'REQUEST.RFC_NUMBER:"I240101_0001"'


def test_list_actions_passes_a_fields_projection_through():
    """EV-R3: the projection is what makes comment metadata 1 request, not N."""
    spec, _parse = build_list_actions(
        "I240101_0001", fields=["ACTION_ID", "CREATION_DATE_UT", "LAST_UPDATE"]
    )
    assert spec.params["fields"] == "ACTION_ID,CREATION_DATE_UT,LAST_UPDATE"
    assert spec.params["search"] == 'REQUEST.RFC_NUMBER:"I240101_0001"'


def test_list_actions_accepts_a_bare_string_projection():
    spec, _parse = build_list_actions("I240101_0001", fields="ACTION_ID,LAST_UPDATE")
    assert spec.params["fields"] == "ACTION_ID,LAST_UPDATE"


def test_list_actions_omits_fields_when_not_requested():
    """Absent, not empty: `fields=` with no value is not the same request."""
    spec, _parse = build_list_actions("I240101_0001")
    assert "fields" not in spec.params


def test_build_get_action_targets_the_top_level_path():
    spec, _ = build_get_action(52990)
    assert spec.method == "GET"
    # Top-level actions/{id}: the nested requests/{rfc}/actions/{id} is 403.
    assert spec.path == "actions/52990"


def test_build_get_action_parses_an_enveloped_record():
    _, parse = build_get_action(52990)
    action = parse({"actions": [{"ACTION_ID": 52990}]})
    assert action.action_id == 52990


def test_update_action_uses_the_top_level_path():
    """The nested requests/{rfc}/actions/{id} form returns 403 (verified live)."""
    spec, _parse = build_update_action(57483, ActionUpdate(description="edited"))
    assert spec.method == "PUT"
    assert spec.path == "actions/57483"
    assert spec.json == {"description": "edited"}


def test_update_action_drops_unset_fields():
    spec, _parse = build_update_action(1, ActionUpdate(description="only this"))
    assert "comment" not in spec.json

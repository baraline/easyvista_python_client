import pytest

from easyvista_python_client.models.action import Action, PostAction
from easyvista_python_client.resources import actions as a
from easyvista_python_client.resources.actions import build_get_action


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


def test_build_get_action_targets_the_top_level_path():
    spec, _ = build_get_action(52990)
    assert spec.method == "GET"
    # Top-level actions/{id}: the nested requests/{rfc}/actions/{id} is 403.
    assert spec.path == "actions/52990"


def test_build_get_action_parses_an_enveloped_record():
    _, parse = build_get_action(52990)
    action = parse({"actions": [{"ACTION_ID": 52990}]})
    assert action.action_id == 52990

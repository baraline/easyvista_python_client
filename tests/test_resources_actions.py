from easyvista_python_client.models.action import Action, PostAction
from easyvista_python_client.resources import actions as a


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

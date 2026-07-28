from easyvista_python_client.models.action import Action, PostAction


def test_action_reads_the_item_level_description_memo():
    action = Action.model_validate(
        {
            "ACTION_ID": 52990,
            "COMMENT": {"HREF": "https://ev.test/api/v1/acme/actions/52990/comment"},
            "DESCRIPTION": {
                "HREF": "https://ev.test/api/v1/acme/actions/52990/description"
            },
        }
    )
    assert action.action_id == 52990
    assert action.description == {
        "HREF": "https://ev.test/api/v1/acme/actions/52990/description"
    }


def test_action_id_is_derived_from_the_create_response_href():
    # POST requests/{rfc}/actions echoes an HREF with no populated ACTION_ID
    # (verified live). The trailing segment of that HREF is the id.
    action = Action.model_validate(
        {"HREF": "https://ev.test/api/v1/acme/actions/52990", "ACTION_ID": None}
    )
    assert action.action_id == 52990


def test_action_id_derivation_leaves_a_populated_id_alone():
    action = Action.model_validate(
        {"HREF": "https://ev.test/api/v1/acme/actions/1", "ACTION_ID": 52990}
    )
    assert action.action_id == 52990


def test_action_id_treats_the_empty_string_sentinel_as_none():
    assert Action.model_validate({"ACTION_ID": ""}).action_id is None


def test_action_id_ignores_a_non_numeric_href_tail():
    action = Action.model_validate({"HREF": "https://ev.test/api/v1/acme/actions"})
    assert action.action_id is None


def test_post_action_serializes_description():
    assert PostAction(action_type_id=94, group_id=3, description="hi").to_api() == {
        "action_type_id": 94,
        "group_id": 3,
        "description": "hi",
    }

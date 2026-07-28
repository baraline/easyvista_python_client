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


def test_action_id_is_derived_from_a_numeric_href_tail():
    # The validator is deliberately narrow: it only fires when href's trailing
    # segment is numeric. It does NOT describe the live create response --
    # that names the parent request instead, see the test below.
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


def test_action_id_is_not_derived_from_a_parent_request_href():
    # The live create response names the parent REQUEST, not the action, so the
    # numeric-tail guard must decline rather than parse an RFC as an id.
    action = Action.model_validate(
        {"HREF": "https://ev.test/api/v1/acme/requests/I260728_00013"}
    )
    assert action.action_id is None


def test_post_action_serializes_description():
    assert PostAction(action_type_id=94, group_id=3, description="hi").to_api() == {
        "action_type_id": 94,
        "group_id": 3,
        "description": "hi",
    }

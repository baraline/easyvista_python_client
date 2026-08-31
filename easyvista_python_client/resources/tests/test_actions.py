import pytest

from easyvista_python_client.models.action import (
    Action,
    ActionUpdate,
    PostAction,
    PostTask,
)
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
    spec, _ = a.build_create_action(
        "I1",
        PostAction(action_type_id=94, group_id=3, custom_fields={"team": "L2"}),
    )
    assert spec.json == {"action_type_id": 94, "group_id": 3, "e_team": "L2"}


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


def test_list_actions_sends_the_row_cap_explicitly_when_given_one():
    """The cap must be the CLIENT's, not the server's unstated default.

    This call returns one page and does not paginate, so whoever owns the cap
    owns where the action log gets truncated. Every sibling search on the client
    injects ``config.default_max_rows``; this one used to be the single search
    that deferred to the server (25 on the verified instance), which a caller
    could neither see nor raise.
    """
    spec, _parse = build_list_actions("I240101_0001", max_rows=200)
    assert spec.params["max_rows"] == 200


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


def test_build_search_actions_exposes_the_envelope_a_pager_needs():
    """The parser yields the whole ``SearchResult``, so ``@next`` is readable."""
    spec, parse = a.build_search_actions("I240101_0001")
    assert spec.path == "actions"
    result = parse(
        {
            "records": [{"ACTION_ID": 1}, {"ACTION_ID": 2}],
            "record_count": "2",
            "total_record_count": "3",
            "@next": "https://ev.test/api/v1/acme/actions?offset=2",
        }
    )
    assert [x.action_id for x in result.records] == [1, 2]
    assert result.total_record_count == 3
    assert result.next_url == "https://ev.test/api/v1/acme/actions?offset=2"


def test_build_search_actions_sends_the_offset():
    spec, _parse = a.build_search_actions("I240101_0001", max_rows=25, offset=50)
    assert spec.params["offset"] == 50
    assert spec.params["max_rows"] == 25


def test_build_search_actions_keeps_the_rfc_filter_on_every_page():
    """A page-2 request that lost the filter would sweep the whole table."""
    spec, _parse = a.build_search_actions("I240101_0001", offset=25)
    assert spec.params["search"] == 'REQUEST.RFC_NUMBER:"I240101_0001"'


@pytest.mark.parametrize("rfc", ["", "   ", 'x",REQUEST.RFC_NUMBER:"y'])
def test_build_search_actions_refuses_an_unsafe_or_blank_rfc(rfc):
    """The guard is shared with ``build_list_actions``."""
    with pytest.raises(ValueError):
        a.build_search_actions(rfc)


# --- the create parsers name their envelope ---------------------------------
#
# Both passed `extract_records(data)` with no envelope key. A deployment
# echoing the created record under an `actions` wrapper handed
# `model_validate` the wrapper itself, and `extra="allow"` accepted it
# silently -- so the assert below is on `action_id`, not on the type: the old
# code returned a perfectly well-formed `Action` with every field `None`.


def test_build_create_action_unwraps_an_actions_envelope():
    _, parser = a.build_create_action(
        "I1", PostAction(action_type_id=94, group_id=3)
    )
    assert parser({"actions": [{"ACTION_ID": 9}]}).action_id == 9


def test_build_create_action_unwraps_a_capital_a_actions_envelope():
    _, parser = a.build_create_action(
        "I1", PostAction(action_type_id=94, group_id=3)
    )
    assert parser({"Actions": [{"ACTION_ID": 9}]}).action_id == 9


def test_build_create_task_unwraps_an_actions_envelope():
    _, parser = a.build_create_task("I1", PostTask(action_type_id=94, group_id=3))
    assert parser({"actions": [{"ACTION_ID": 9}]}).action_id == 9

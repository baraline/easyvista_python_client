from datetime import datetime, timedelta, timezone

import pytest
from pydantic import ValidationError

from easyvista_python_client.models.action import Action, PostAction, PostTask

_CEST = timezone(timedelta(hours=2))

# Trimmed from a real item-level GET (see the spec's Appendix A-2); values are
# synthetic, the KEY NAMES are what this test pins.
_ITEM_PAYLOAD = {
    "ACTION_ID": "57483",
    "ACTION_NUMBER": "0",
    "ACTION_TYPE_ID": "20",
    "CREATION_DATE_UT": "2026-08-17T15:40:36.000+02:00",
    "LAST_UPDATE": "2026-08-17T15:40:37.653+02:00",
    "DONE_BY_ID": "6117",
    "GROUP_ID": "57",
    "REQUEST_ID": "7743",
    "STAGE_ID": "10",
    "WORKFLOW_ID": "37",
    "PARENT_ACTION_ID": "",
    "DONE_BY": {"EMPLOYEE_ID": "6117", "LAST_NAME": "Doe"},
    "DESCRIPTION": {"HREF": "https://ev.test/api/v1/12345/actions/57483/description"},
}


def test_item_level_action_exposes_timestamps_and_author():
    """EV-R1: the fields a Comment model needs all exist on the item GET."""
    action = Action.model_validate(_ITEM_PAYLOAD)
    assert action.created_at == datetime(2026, 8, 17, 15, 40, 36, tzinfo=_CEST)
    assert action.updated_at == datetime(2026, 8, 17, 15, 40, 37, 653000, tzinfo=_CEST)
    assert action.done_by_id == 6117
    assert action.action_type_id == 20
    assert action.group_id == 57
    assert action.request_id == 7743


def test_workflow_context_is_declared_so_generated_actions_are_identifiable():
    """A fresh ticket auto-spawns ~12 workflow actions; these tell them apart."""
    action = Action.model_validate(_ITEM_PAYLOAD)
    assert action.stage_id == 10
    assert action.workflow_id == 37
    assert action.parent_action_id is None  # "" sentinel -> None


@pytest.mark.parametrize(
    ("alias", "attr"),
    [
        ("DONE_BY_ID", "done_by_id"),
        ("ACTION_TYPE_ID", "action_type_id"),
        ("GROUP_ID", "group_id"),
        ("REQUEST_ID", "request_id"),
        ("ACTION_NUMBER", "action_number"),
        ("STAGE_ID", "stage_id"),
        ("WORKFLOW_ID", "workflow_id"),
        ("PARENT_ACTION_ID", "parent_action_id"),
    ],
)
def test_the_empty_string_sentinel_maps_to_none_on_every_new_int_field(alias, attr):
    """Workflow-generated actions have an EMPTY DONE_BY_ID (measured live)."""
    action = Action.model_validate({"ACTION_ID": "1", alias: ""})
    assert getattr(action, attr) is None


def test_absent_timestamps_are_none_not_an_error():
    """The list projection omits both date fields entirely."""
    action = Action.model_validate({"ACTION_ID": "1"})
    assert action.created_at is None
    assert action.updated_at is None


def test_action_label_is_declared_not_left_in_model_extra():
    """It rides the default list projection, and ``context.py`` reads it."""
    action = Action.model_validate(
        {"ACTION_ID": "1", "ACTION_LABEL_FR": "Analyse de Resolution"}
    )
    assert action.action_label_fr == "Analyse de Resolution"


def test_a_whole_bracketed_label_echoing_another_language_is_a_placeholder():
    """Brackets around the WHOLE label, echoing another column, mean "untranslated".

    A single-language instance echoes the default-language text wrapped in
    ``[...]`` on every other language column; ``localized_label`` discards them.
    See the sibling test below for the bracket convention that DOES carry
    meaning -- conflating the two once cost this package a true finding.
    """
    from easyvista_python_client.references import localized_label

    item = {
        "ACTION_ID": "1",
        "ACTION_LABEL_FR": "Analyse de Resolution",
        "ACTION_LABEL_EN": "[Analyse de Resolution]",
    }
    assert Action.model_validate(item).action_label_fr == "Analyse de Resolution"
    assert localized_label(item, "ACTION_LABEL") == "Analyse de Resolution"


def test_a_bracketed_suffix_beside_real_translations_is_a_visibility_marker():
    """``Commentaire [Public]`` is a real marker, not a placeholder.

    Measured live 2026-08-28: type 94's sibling columns carry genuine
    translations (``Customer Comment``, ``Kommentar des Kunden``), so the
    French label's ``[Public]`` suffix is content -- the opposite of the
    placeholder above, where the whole label is bracketed and duplicates
    another language.

    ``_usable_label`` already draws this line correctly: it rejects only a
    label that is *entirely* bracketed, so a bracketed SUFFIX survives. The
    code was right; the prose that called every bracket a placeholder was not.
    """
    from easyvista_python_client.references import localized_label

    item = {
        "ACTION_ID": "1",
        "ACTION_LABEL_FR": "Commentaire [Public]",
        "ACTION_LABEL_EN": "Customer Comment",
    }
    assert Action.model_validate(item).action_label_fr == "Commentaire [Public]"
    # _EN is preferred when populated, so the English translation wins here.
    assert localized_label(item, "ACTION_LABEL") == "Customer Comment"
    # The point: with only the French column, the marker is KEPT, not discarded
    # the way a fully-bracketed placeholder would be.
    fr_only = {"ACTION_ID": "1", "ACTION_LABEL_FR": "Note Interne [Prive]"}
    assert localized_label(fr_only, "ACTION_LABEL") == "Note Interne [Prive]"


def test_done_by_reference_resolves_through_the_shared_resolver():
    action = Action.model_validate(_ITEM_PAYLOAD)
    assert action.reference("DONE_BY").id == "6117"


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


def test_action_id_is_derived_from_an_href_with_a_query_suffix():
    # A ?fields= suffix must not defeat the numeric-tail guard: the query is
    # stripped before .isdigit() decides.
    action = Action.model_validate(
        {"HREF": "https://ev.test/api/v1/acme/actions/52990?fields=ACTION_ID"}
    )
    assert action.action_id == 52990


def test_action_id_is_derived_from_an_href_with_a_trailing_slash():
    action = Action.model_validate(
        {"HREF": "https://ev.test/api/v1/acme/actions/52990/"}
    )
    assert action.action_id == 52990


def test_action_id_ignores_an_href_with_an_empty_tail():
    # The degenerate shapes: rsplit leaves "" and "".isdigit() is False, so the
    # validator declines instead of raising on int("").
    assert Action.model_validate({"HREF": "/"}).action_id is None
    assert Action.model_validate({"HREF": ""}).action_id is None


def test_action_id_declines_a_trailing_slash_combined_with_a_query():
    # Known gap, pinned as observed rather than fixed: rstrip("/") runs BEFORE
    # the query is stripped, so ".../52990/?x=1" still ends in "?x=1" when
    # rsplit runs and the tail resolves to "". Nothing live emits this shape --
    # the API returns bare item HREFs -- so the ordering is left alone rather
    # than changed on speculation.
    action = Action.model_validate(
        {"HREF": "https://ev.test/api/v1/acme/actions/52990/?fields=ACTION_ID"}
    )
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


def test_post_action_carries_both_text_channels():
    """An action has two independent memos and a create can populate both.

    Verified live 2026-08-28: a single create carrying ``description`` and
    ``comment`` read back with exactly the text sent in each, addressable
    separately at ``actions/{id}/description`` and ``actions/{id}/comment``.
    ``comment`` was absent from this model until then, which made the second
    channel unreachable at create time without ``extra_payload``.
    """
    assert PostAction(
        action_type_id=94, description="public", comment="internal"
    ).to_api() == {
        "action_type_id": 94,
        "description": "public",
        "comment": "internal",
    }


def test_post_action_omits_an_unset_comment():
    """The new field must not widen the body every caller already sends."""
    assert "comment" not in PostAction(action_type_id=94, description="hi").to_api()


def test_post_task_serializes_flat_for_the_tasks_endpoint():
    """The task body is FLAT at the root; the action body is wrapped.

    Verified live 2026-08-28 -- POST requests/{rfc}/tasks with this shape
    returned 201 and a record already carrying END_DATE_UT.
    """
    assert PostTask(
        action_type_id=95, group_id=3, description="internal note"
    ).to_api() == {
        "action_type_id": 95,
        "group_id": 3,
        "description": "internal note",
    }


def test_post_task_refuses_a_body_with_no_action_type():
    """The type is mandatory AND carries the public/internal distinction."""
    with pytest.raises(ValidationError, match="needs an action type"):
        PostTask(group_id=3, description="orphan")


def test_post_task_refuses_a_body_with_no_group():
    """Omitting the group draws a 590 naming a field the caller never sent."""
    with pytest.raises(ValidationError, match="needs an assigned group"):
        PostTask(action_type_id=94, description="orphan")


def test_post_task_accepts_any_of_the_three_group_spellings():
    """group_id / group_name / group_mail are documented alternatives.

    The instance OpenAPI's example shows only group_mail, which is what led an
    earlier pass to believe a 403 on GET /groups made this endpoint unusable.
    """
    for kwargs in ({"group_id": 3}, {"group_name": "N1"}, {"group_mail": "a@b.fr"}):
        assert PostTask(action_type_id=94, **kwargs).to_api()["action_type_id"] == 94


def test_post_task_omits_unset_optional_fields():
    """An unset elapsed_time is computed by EasyVista, not sent as null."""
    body = PostTask(action_type_id=94, group_id=3).to_api()
    for absent in ("elapsed_time", "time_cost", "end_date_ut", "comment"):
        assert absent not in body

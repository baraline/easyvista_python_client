from datetime import datetime, timedelta, timezone
from decimal import Decimal

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
        action_type_id=94, group_id=3, description="public", comment="internal"
    ).to_api() == {
        "action_type_id": 94,
        "group_id": 3,
        "description": "public",
        "comment": "internal",
    }


def test_post_action_omits_an_unset_comment():
    """The new field must not widen the body every caller already sends."""
    assert (
        "comment"
        not in PostAction(action_type_id=94, group_id=3, description="hi").to_api()
    )


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


def test_action_label_property_returns_the_real_text_on_an_english_instance():
    # Why the property exists. On a single-language instance the OTHER language
    # columns echo the primary text wrapped in brackets, so reading the one
    # named column yields the placeholder rather than None -- asserted on both
    # attributes so the difference is visible.
    action = Action.model_validate(
        {"ACTION_LABEL_EN": "Customer Comment", "ACTION_LABEL_FR": "[Customer Comment]"}
    )
    assert action.action_label_fr == "[Customer Comment]"
    assert action.label == "Customer Comment"


def test_action_label_keeps_a_bracketed_suffix_which_is_real_content():
    # A label wrapped ENTIRELY in brackets is an untranslated placeholder; a
    # bracketed SUFFIX on otherwise distinct text is a genuine marker and must
    # survive. Conflating the two once deleted a true finding.
    action = Action.model_validate({"ACTION_LABEL_FR": "Commentaire [Public]"})
    assert action.label == "Commentaire [Public]"


def test_action_label_on_a_non_french_instance_skips_the_bracketed_echo():
    """The exact behaviour the guide's `label` prose claims.

    On an English deployment ``action_label_fr`` is not ``None`` -- it holds
    the default-language text wrapped in brackets, ``'[Customer Comment]'`` --
    so reading that column directly gives bracket noise rather than an absence,
    which is the failure that is easy to miss.
    """
    action = Action.model_validate(
        {
            "ACTION_ID": 1,
            "ACTION_LABEL_FR": "[Customer Comment]",
            "ACTION_LABEL_EN": "Customer Comment",
        }
    )
    assert action.label == "Customer Comment"
    assert action.action_label_fr == "[Customer Comment]"  # the trap


def test_action_label_is_none_when_no_label_column_is_populated():
    assert Action.model_validate({"ACTION_ID": 1}).label is None
    # And in the pathological case where every column is a placeholder: the
    # caller supplies its own last-resort text.
    assert Action.model_validate({"ACTION_LABEL_FR": "[X]"}).label is None


# --- PostAction gains PostTask's guard, on the same tier-1 sentence ----------
#
# `docs/vendor-api-reference.md` quotes the vendor's create-an-ACTION page as
# "Required: action_type_id, and one of group_id / group_mail / group_name" --
# so this is if anything better evidence here than on the task route. Before
# this, `PostAction()` constructed fine and shipped `{"action": {}}`, drawing an
# HTTP 590 that named no field at all.


def test_post_action_requires_a_type_and_a_group():
    with pytest.raises(ValidationError, match="needs an action type"):
        PostAction(group_id=3, description="orphan")
    with pytest.raises(ValidationError, match="needs an assigned group"):
        PostAction(action_type_id=94, description="orphan")


def test_post_action_accepts_a_string_type_id_like_post_task_does():
    """The two models' id types diverged for no recorded reason.

    ``int | None`` here against ``int | str | None`` on ``PostTask`` made a
    non-numeric type or group id work through ``create_task`` and fail through
    ``create_action`` -- an inconsistency inside the package with no evidence
    behind it. The instance's own OpenAPI declares ``action_type_id`` on this
    route as a *string* (tier 3, illustrative), which argues for accepting one,
    not for coercing to one: whichever type is passed serializes unchanged.
    """
    body = PostAction(action_type_id="94", group_id="GRP-1").to_api()
    assert body["action_type_id"] == "94"
    assert body["group_id"] == "GRP-1"


def test_post_action_ships_group_mail_and_parent_action_id_and_guid():
    """Three tier-1 optional fields the model did not declare."""
    body = PostAction(
        action_type_guid="{TYPE}", group_mail="n1@example.invalid", parent_action_id=7
    ).to_api()
    assert body["action_type_guid"] == "{TYPE}"
    assert body["group_mail"] == "n1@example.invalid"
    assert body["parent_action_id"] == 7


def test_extra_payload_satisfies_the_action_guards():
    """A guard reading declared attributes would refuse a body the API accepts."""
    payload = PostAction(
        extra_payload={"action_type_id": 94, "group_mail": "n1@example.invalid"}
    )
    assert payload.to_api() == {
        "action_type_id": 94,
        "group_mail": "n1@example.invalid",
    }


def test_an_extra_payload_action_type_guid_satisfies_the_task_guard():
    """``PostTask`` deliberately does NOT declare ``action_type_guid``.

    On the action route the field is tier 1 (2023.4+) and the instance's own
    OpenAPI declares it; on the TASK route neither holds -- the vendor's task
    page has never been transcribed into this repo (O-TASKDOC) and the
    instance's schema for that route lists eleven properties without it.
    Declaring it would put the model's word behind a field nothing supports
    there. So the guard accepts the key without the model asserting the field
    exists, and ``extra_payload`` is how it arrives.
    """
    body = PostTask(group_id=3, extra_payload={"action_type_guid": "{TYPE}"}).to_api()
    assert body["action_type_guid"] == "{TYPE}"


# --- the effort/cost columns (EV-TASKSHAPE) ----------------------------------
# A GLPI comment maps to an EasyVista TASK, not an ACTION, so a caller syncing
# a timeline must be able to see whether an effort column APPLIES to a record
# at all. These five columns arrived as untyped ``extra="allow"`` strings until
# 0.3.0; the tests below pin the one distinction that carries the signal.


def test_elapsed_time_distinguishes_absent_from_zero():
    """`''` means the column does not apply; `'0'` means it applies and is zero.

    Measured 2026-09-02 over 1500 live action rows: 384 carried ``''`` and 895
    carried ``'0'``. Collapsing the two -- to ``0`` or to ``None`` -- destroys
    the only signal that says whether a row tracks effort.
    """

    def elapsed(raw):
        row = {"ACTION_ID": "1", "ELAPSED_TIME": raw}
        return Action.model_validate(row).elapsed_time

    assert elapsed("") is None
    assert elapsed("0") == 0
    assert elapsed("27") == 27


def test_the_absent_versus_zero_distinction_survives_a_dump():
    """A caller comparing two rows dumps them; ``None`` and ``0`` must not merge."""
    absent = Action.model_validate(
        {"ACTION_ID": "1", "ELAPSED_TIME": "", "TIME_COST": ""}
    )
    zero = Action.model_validate(
        {"ACTION_ID": "2", "ELAPSED_TIME": "0", "TIME_COST": "0,00"}
    )
    assert absent.model_dump(by_alias=True)["ELAPSED_TIME"] is None
    assert zero.model_dump(by_alias=True)["ELAPSED_TIME"] == 0
    assert absent.model_dump(by_alias=True)["TIME_COST"] is None
    assert zero.model_dump(by_alias=True)["TIME_COST"] == Decimal("0.00")


@pytest.mark.parametrize("alias", ["TIME_COST", "CONTRACTUAL_COST"])
def test_a_french_decimal_comma_cost_parses_exactly(alias):
    """Both cost columns arrive comma-separated (``'0,00'``, ``'99,00'``)."""
    attr = alias.lower()
    assert getattr(Action.model_validate({alias: ""}), attr) is None
    assert getattr(Action.model_validate({alias: "0,00"}), attr) == Decimal("0.00")
    assert getattr(Action.model_validate({alias: "99,00"}), attr) == Decimal("99.00")
    # Decimal equality is scale-insensitive, so '129,00' equals Decimal("129").
    # That is NOT the float-exactness claim -- see
    # test_a_cost_is_an_exact_decimal_not_a_float for that.
    assert getattr(Action.model_validate({alias: "129,00"}), attr) == Decimal("129")


@pytest.mark.parametrize("alias", ["TIME_COST", "CONTRACTUAL_COST"])
def test_a_dot_separated_cost_parses_too(alias):
    """The separator is a deployment's locale, not an EasyVista constant."""
    assert getattr(Action.model_validate({alias: "99.00"}), alias.lower()) == Decimal(
        "99.00"
    )


@pytest.mark.parametrize("value", ["1 234,56", "1.234,56", "1,234.56", "abc", "9,999"])
def test_an_unrecognised_cost_is_reported_not_guessed_at(value):
    """A grouped or junk amount raises rather than inventing a wrong number.

    ``'1.234,56'`` and ``'1,234.56'`` are the same amount under opposite
    conventions and ``'9,999'`` is either 9.999 or 9999 -- unguessable. A wrong
    money value is worse than a loud failure, the same trade
    ``OptionalDateTime`` makes for a wrong instant.
    """
    with pytest.raises(ValidationError):
        Action.model_validate({"TIME_COST": value})


def test_the_effort_window_parses_as_aware_datetimes():
    """``START_DATE_UT``/``END_DATE_UT`` are the action's own effort window."""
    action = Action.model_validate(
        {
            "ACTION_ID": "1",
            "START_DATE_UT": "2026-09-02T09:04:01.000+02:00",
            "END_DATE_UT": "",
        }
    )
    assert action.start_date_ut == datetime(2026, 9, 2, 9, 4, 1, tzinfo=_CEST)
    assert action.end_date_ut is None


@pytest.mark.parametrize(
    "alias",
    ["ELAPSED_TIME", "TIME_COST", "CONTRACTUAL_COST", "START_DATE_UT", "END_DATE_UT"],
)
def test_the_effort_columns_are_declared_not_left_in_model_extra(alias):
    """Before 0.3.0 all five reached callers only as untyped extras."""
    action = Action.model_validate({"ACTION_ID": "1", alias: ""})
    assert alias not in (action.model_extra or {})


def test_is_workflow_generated_reads_the_workflow_id():
    """1500/1500 live rows: a WORKFLOW_ID is set iff the engine owns the row."""
    assert Action.model_validate({"WORKFLOW_ID": "37"}).is_workflow_generated is True
    assert Action.model_validate({"WORKFLOW_ID": ""}).is_workflow_generated is False
    assert Action.model_validate({"ACTION_ID": "1"}).is_workflow_generated is False


def test_a_public_comment_carrying_effort_is_not_reported_as_workflow_generated():
    """The counter-example that refutes the effort-shape heuristic.

    Measured 2026-09-02: a type-94 ``Commentaire [Public]`` carried
    ``ELAPSED_TIME='12'``, ``TIME_COST='99,00'`` and ``CONTRACTUAL_COST='129,00'``
    with an empty ``WORKFLOW_ID``. Any "effort set => not a comment" filter
    drops it.
    """
    action = Action.model_validate(
        {
            "ACTION_ID": "14980",
            "ACTION_TYPE_ID": "94",
            "ACTION_LABEL_FR": "Commentaire [Public]",
            "ELAPSED_TIME": "12",
            "TIME_COST": "99,00",
            "CONTRACTUAL_COST": "129,00",
            "WORKFLOW_ID": "",
        }
    )
    assert action.is_workflow_generated is False
    assert action.elapsed_time == 12
    assert action.time_cost == Decimal("99.00")
    assert action.contractual_cost == Decimal("129.00")


def test_a_cost_is_an_exact_decimal_not_a_float():
    """Pins Decimal specifically -- a float field would pass the assertions above.

    ``Decimal("0.1") + Decimal("0.2") == Decimal("0.3")``; the float equivalent
    does not. If ``time_cost`` were ever retyped to ``float`` every other cost
    test here would still pass, so this is the one that would fail.
    """
    a = Action.model_validate({"TIME_COST": "0,10"})
    b = Action.model_validate({"TIME_COST": "0,20"})
    assert isinstance(a.time_cost, Decimal)
    assert a.time_cost + b.time_cost == Decimal("0.30")
    assert 0.1 + 0.2 != 0.3  # the float trap this type avoids


def test_magnitude_is_not_what_the_cost_parser_refuses():
    """``'1000,00'`` parses; only the FORMAT is refused, never the size.

    An earlier revision of the docs said "an amount above 999 is the case that
    would trigger it", which was wrong -- 1000,00 carries no grouping separator.
    """
    assert Action.model_validate({"TIME_COST": "1000,00"}).time_cost == Decimal("1000")
    assert Action.model_validate({"TIME_COST": "999999,99"}).time_cost == Decimal(
        "999999.99"
    )


def test_three_fraction_digits_are_refused_as_ambiguous():
    """``'1,234'`` is either 1.234 or a comma-grouped 1234 -- unguessable."""
    with pytest.raises(ValidationError):
        Action.model_validate({"TIME_COST": "1,234"})


def test_none_does_not_distinguish_absent_from_not_projected():
    """The documented ambiguity, pinned so nobody "fixes" it into a wrong answer.

    A default ``list_actions`` row omits all five effort columns, so they read
    ``None`` there -- the SAME value the ``""`` sentinel produces. The model
    cannot tell "does not apply" from "not returned", which is why the docstring
    tells callers to project the columns before reading meaning into a ``None``.
    """
    not_projected = Action.model_validate({"ACTION_ID": "1"})
    does_not_apply = Action.model_validate({"ACTION_ID": "1", "ELAPSED_TIME": ""})
    assert not_projected.elapsed_time is None
    assert does_not_apply.elapsed_time is None


def test_the_effort_columns_are_always_present_in_a_dump_once_declared():
    """Declaring them changed PRESENCE, not the classify_fields bucket.

    None of the five starts with ``E_``, so ``classify()`` always put them in
    ``.official``. What the 0.3.0 change altered is that the keys are now
    present even when the API did not return them.
    """
    action = Action.model_validate({"ACTION_ID": "1"})
    official = action.classify_fields().official
    for alias in (
        "ELAPSED_TIME",
        "TIME_COST",
        "CONTRACTUAL_COST",
        "START_DATE_UT",
        "END_DATE_UT",
    ):
        assert alias in official
        assert official[alias] is None
        assert alias not in action.classify_fields().custom


def test_a_cost_survives_a_json_mode_dump():
    """A Decimal is not JSON-native; ``mode="json"`` is the documented recipe."""
    import json

    action = Action.model_validate({"ACTION_ID": "1", "TIME_COST": "99,00"})
    with pytest.raises(TypeError):
        json.dumps(action.model_dump(by_alias=True))
    dumped = action.model_dump(mode="json", by_alias=True)
    assert json.dumps(dumped)  # does not raise
    # Renders with a '.', not the ',' the API sent -- documented in user_guide.
    assert "99.00" in str(dumped["TIME_COST"])


def test_reference_renders_a_cost_column_instead_of_returning_it_empty():
    """``_scalar`` gained a Decimal branch; without it this Reference was empty."""
    action = Action.model_validate({"ACTION_ID": "1", "TIME_COST": "99,00"})
    assert action.reference("TIME_COST").display == "99.00"

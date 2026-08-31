from datetime import datetime, timedelta, timezone

from easyvista_python_client.models.request import Request
from easyvista_python_client.references import (
    Reference,
    _scalar,
    label_from_record,
    localized_label,
    resolve_reference,
)


def test_display_prefers_label_then_id_then_none():
    assert Reference(id="1", label="Open").display == "Open"
    assert Reference(id="1", label=None).display == "1"
    assert Reference(id=None, label=None).display is None


def test_nested_label_prefers_en_then_fr_then_other_languages_then_path():
    rec = {
        "STATUS": {
            "STATUS_FR": "En cours",
            "STATUS_EN": "Open",
            "STATUS_GE": "Offen",
            "HREF": "http://x/api/v1",
        },
        "STATUS_ID": "12",
    }
    ref = resolve_reference(rec, "STATUS")
    assert ref.label == "Open"  # _EN wins over _FR
    assert ref.id == "12"
    assert ref.display == "Open"


def test_nested_label_falls_back_to_fr_then_path():
    only_fr = {"DEPARTMENT": {"DEPARTMENT_FR": "Grp", "DEPARTMENT_PATH": "Grp/Sub"}}
    assert resolve_reference(only_fr, "DEPARTMENT").label == "Grp"
    only_path = {"LOCATION": {"LOCATION_PATH": "Site A"}}
    assert resolve_reference(only_path, "LOCATION").label == "Site A"


def test_nested_label_skips_empty_strings():
    rec = {"LOCATION": {"LOCATION_EN": "", "LOCATION_FR": "-"}}
    assert resolve_reference(rec, "LOCATION").label == "-"


def test_id_only_reference_from_top_level_id():
    ref = resolve_reference({"URGENCY_ID": "1"}, "URGENCY")
    assert ref.id == "1"
    assert ref.label is None
    assert ref.display == "1"


def test_catalog_id_falls_back_to_nested_sd_catalog_id():
    """No CATALOG_REQUEST_ID/_GUID at top level or nested, so the resolver falls
    back to the first *_ID sub-key."""
    rec = {
        "CATALOG_REQUEST": {
            "TITLE_FR": "Cat",
            "SD_CATALOG_ID": "5791",
            "HREF": "http://x",
        },
    }
    ref = resolve_reference(rec, "CATALOG_REQUEST")
    assert ref.label == "Cat"
    assert ref.id == "5791"  # nested *_ID fallback


def test_bare_id_field_passed_directly():
    ref = resolve_reference({"URGENCY_ID": "1"}, "URGENCY_ID")
    assert ref.id == "1" and ref.label is None


def test_case_insensitive_name():
    rec = {"STATUS": {"STATUS_FR": "En cours"}, "STATUS_ID": "12"}
    assert resolve_reference(rec, "status").label == "En cours"
    assert resolve_reference(rec, "status").id == "12"


def test_custom_e_field_nested_and_scalar():
    nested = {"e_site": {"E_SITE_FR": "Paris"}}
    assert resolve_reference(nested, "e_site").label == "Paris"
    scalar = {"e_ref": "ABC"}
    assert resolve_reference(scalar, "e_ref").id == "ABC"


def test_missing_field_returns_empty_reference():
    ref = resolve_reference({"RFC_NUMBER": "I1"}, "STATUS")
    assert ref == Reference(id=None, label=None)
    assert ref.display is None


def test_resolve_non_dict_record_is_empty():
    assert resolve_reference(None, "STATUS") == Reference(id=None, label=None)
    assert resolve_reference([], "STATUS") == Reference(id=None, label=None)


def test_resolve_is_case_insensitive_on_record_keys():
    rec = {"Status": {"Status_FR": "En cours"}, "Status_ID": "12"}
    ref = resolve_reference(rec, "STATUS")
    assert ref.label == "En cours"
    assert ref.id == "12"


def test_model_reference_resolves_nested_and_id_only():
    ticket = Request.model_validate(
        {
            "RFC_NUMBER": "I1",
            "STATUS": {"STATUS_FR": "En cours"},
            "STATUS_ID": "12",
            "URGENCY_ID": "1",
        }
    )
    assert ticket.reference("STATUS").display == "En cours"
    assert ticket.reference("STATUS").id == "12"
    assert ticket.reference("URGENCY").display == "1"
    assert ticket.reference("URGENCY").label is None


def test_model_reference_missing_field_is_empty():
    ticket = Request.model_validate({"RFC_NUMBER": "I1"})
    assert ticket.reference("DEPARTMENT") == Reference(id=None, label=None)


def test_scalar_renders_an_aware_datetime_as_the_ev_wire_format():
    value = datetime(
        2026, 8, 17, 15, 40, 41, 610000, tzinfo=timezone(timedelta(hours=2))
    )
    assert _scalar(value) == "2026-08-17T15:40:41.610+02:00"


def test_scalar_renders_a_naive_datetime_via_isoformat_fallback():
    # format_ev_datetime refuses a naive datetime; _scalar must never raise, so
    # it falls back to plain .isoformat() rather than propagating that error.
    value = datetime(2026, 8, 17, 15, 40, 41)
    assert _scalar(value) == "2026-08-17T15:40:41"


def test_model_reference_on_a_retyped_timestamp_field_is_populated():
    """Request.reference("LAST_UPDATE") must not regress to an empty Reference
    now that last_update is a datetime rather than a str (2026-08-17 retype)."""
    ticket = Request.model_validate(
        {"RFC_NUMBER": "I1", "LAST_UPDATE": "2026-08-17T15:40:41.610+02:00"}
    )
    ref = ticket.reference("LAST_UPDATE")
    assert ref.display == "2026-08-17T15:40:41.610+02:00"


def test_reference_exported_from_package():
    import easyvista_python_client as evc

    assert evc.Reference is Reference


# --- language order and the placeholder rule ---------------------------------


def test_nested_label_skips_a_bracketed_placeholder_so_fr_wins():
    # THE deliberate behaviour change. An unpopulated localized column on a
    # single-language instance echoes the primary text in brackets; before this,
    # that echo won because it came first in the scan and was rendered verbatim.
    rec = {"STATUS": {"STATUS_EN": "[En cours]", "STATUS_FR": "En cours"}}
    assert resolve_reference(rec, "STATUS").label == "En cours"


def test_nested_label_keeps_a_fully_placeholder_record_rather_than_losing_the_heading():
    # The regression guard for the whole design. This function's callers render
    # NOTHING when it returns None -- to_markdown drops the table row entirely,
    # and a statistics bucket collapses onto the bare id -- so a record whose
    # every language column is a placeholder must still yield what it always
    # yielded. Losing a heading is worse than an ugly one.
    rec = {"STATUS": {"STATUS_EN": "[X]", "STATUS_FR": "[X]"}}
    assert resolve_reference(rec, "STATUS").label == "[X]"


def test_nested_label_prefers_a_language_column_over_path():
    # _PATH used to be the third and last rung, so it beat everything after _FR.
    # A real language label is a better heading than a path.
    rec = {
        "LOCATION": {
            "LOCATION_EN": "[Site A]",
            "LOCATION_GE": "Standort A",
            "LOCATION_PATH": "A/B",
        }
    }
    assert resolve_reference(rec, "LOCATION").label == "Standort A"


def test_languages_argument_reorders_the_scan():
    rec = {"STATUS": {"STATUS_EN": "Open", "STATUS_FR": "En cours"}}
    assert resolve_reference(rec, "STATUS").label == "Open"
    assert resolve_reference(rec, "STATUS", languages=("_FR", "_EN")).label == (
        "En cours"
    )
    # A bare "FR" normalizes to the "_FR" suffix, so a caller need not know the
    # storage form.
    assert (
        localized_label(
            {"DEPARTMENT_EN": "Dept", "DEPARTMENT_FR": "Service"},
            "DEPARTMENT",
            languages=("FR",),
        )
        == "Service"
    )


def test_default_language_order_is_exported_and_starts_english_first():
    # The gate that keeps a skill snippet importable: the contract test rejects
    # any snippet importing a name that is not public.
    import easyvista_python_client as evc

    assert evc.DEFAULT_LANGUAGE_ORDER[:6] == ("_EN", "_FR", "_GE", "_IT", "_PO", "_SP")
    assert evc.localized_label is localized_label


def test_localized_label_prefers_en_then_fr():
    rec = {"DEPARTMENT_EN": "Dept", "DEPARTMENT_FR": "Service"}
    assert localized_label(rec, "DEPARTMENT") == "Dept"


def test_localized_label_skips_bracketed_placeholder_so_fr_wins():
    # Unpopulated localized columns echo a "[CODE]" placeholder on this instance.
    rec = {"DEPARTMENT_EN": "[ACME-CORP]", "DEPARTMENT_FR": "ACME CORP"}
    assert localized_label(rec, "DEPARTMENT") == "ACME CORP"


def test_localized_label_keeps_a_bracketed_suffix_marker():
    """The other half of the bracket rule, and the one nothing pinned.

    Two bracket conventions appear in ``ACTION_LABEL_*`` and they mean OPPOSITE
    things. A label wrapped ENTIRELY in brackets, echoing another language, is
    an untranslated placeholder and is discarded -- that is the test above. A
    bracketed SUFFIX on otherwise distinct text, with real sibling
    translations, is a genuine marker written by whoever configured the
    instance, and must survive.

    Only the placeholder case was pinned before, so nothing stopped a
    well-meant "strip the brackets" cleanup from re-deleting the finding the
    documentation now teaches. An earlier revision of this package did exactly
    that.
    """
    # Real translations on both sides: the preferred language wins, brackets or
    # not, and neither is treated as noise.
    assert (
        localized_label(
            {
                "ACTION_LABEL_EN": "Customer Comment",
                "ACTION_LABEL_FR": "Commentaire [Public]",
            },
            "ACTION_LABEL",
        )
        == "Customer Comment"
    )
    # The load-bearing one: a bracketed SUFFIX is the only label there is, and
    # it survives. Discarding it would return None and lose the marker.
    assert (
        localized_label({"ACTION_LABEL_FR": "Commentaire [Public]"}, "ACTION_LABEL")
        == "Commentaire [Public]"
    )


def test_localized_label_skips_empty_and_does_not_match_code_or_path():
    # _CODE / _PATH are not language columns and must never be picked as the label.
    rec = {"DEPARTMENT_EN": "", "DEPARTMENT_CODE": "UTX", "DEPARTMENT_PATH": "A/B"}
    assert localized_label(rec, "DEPARTMENT") is None


def test_localized_label_falls_back_in_order():
    rec = {"DEPARTMENT_EN": "[ACME-CORP]"}
    assert localized_label(rec, "DEPARTMENT", fallbacks=("UTX", "A/B")) == "UTX"
    assert localized_label(rec, "DEPARTMENT", fallbacks=(None, "A/B")) == "A/B"


def test_localized_label_none_when_nothing_usable():
    assert localized_label({}, "DEPARTMENT") is None
    assert (
        localized_label({"DEPARTMENT_FR": "[x]"}, "DEPARTMENT", fallbacks=(None,))
        is None
    )


# --- label_from_record: a reference table names its label after nothing ------


def test_label_from_record_matches_by_suffix_across_four_prefixes():
    """Four tables, four different label prefixes, one suffix rule.

    On the verified instance's own response schemas ``groups`` returns
    ``GROUP_EN``, ``locations`` returns ``LOCATION_FR``, ``catalog-requests``
    returns ``TITLE_EN`` and ``slas`` returns ``NAME_FR``. Those schemas are
    tier 3, which is the second reason to match on the suffix rather than on a
    prefix a caller would have to know in advance.
    """
    assert label_from_record({"GROUP_ID": 3, "GROUP_EN": "N1"}) == "N1"
    assert label_from_record({"LOCATION_FR": "Paris"}) == "Paris"
    assert label_from_record({"SD_CATALOG_ID": 1, "TITLE_EN": "Incident"}) == (
        "Incident"
    )
    assert label_from_record({"SLA_ID": 1, "NAME_FR": "Standard"}) == "Standard"


def test_label_from_record_skips_a_bracketed_placeholder():
    """An unpopulated translation column echoes ``"[CODE]"``."""
    assert label_from_record({"NAME_EN": "[Standard]", "NAME_FR": "Standard"}) == (
        "Standard"
    )


def test_label_from_record_never_returns_an_href():
    assert label_from_record({"HREF": "https://h/api/v1/acme/groups/3"}) is None


def test_label_from_record_falls_back_through_label_then_path_then_code():
    assert label_from_record({"SOME_LABEL": "L"}) == "L"
    assert label_from_record({"DEPARTMENT_PATH": "ACME/IT"}) == "ACME/IT"
    assert label_from_record({"LOCATION_CODE": "PAR"}) == "PAR"
    # And the order between them: a real label beats a path beats a code.
    assert label_from_record(
        {"LOCATION_CODE": "PAR", "SOME_LABEL": "L", "X_PATH": "p"}
    ) == "L"


def test_label_from_record_honours_a_language_reordering():
    row = {"GROUP_EN": "Level 1", "GROUP_FR": "Niveau 1"}
    assert label_from_record(row) == "Level 1"
    assert label_from_record(row, languages=("_FR", "_EN")) == "Niveau 1"


def test_resolve_reference_is_unchanged_by_the_new_helper():
    """``label_from_record`` deliberately does NOT feed ``resolve_reference``.

    The nested-label scan runs a bracket-TOLERANT second pass so a fully
    untranslated record still renders something, and it appends ``_PATH`` to
    the language order rather than treating it as a separate rung. Routing it
    through the stricter helper would change what ``.reference("STATUS").label``
    returns on such a record -- a behaviour change, not a refactor.
    """
    record = {"STATUS": {"STATUS_GE": "[x]", "STATUS_PATH": "Real Text"}}
    assert resolve_reference(record, "STATUS").label == "Real Text"
    # The stricter helper prefers the language column even when bracketed is
    # all that column has -- which is exactly why the two are kept apart.
    assert label_from_record(record["STATUS"]) == "Real Text"

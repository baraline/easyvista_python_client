from datetime import datetime, timedelta, timezone

from easyvista_python_client.models.request import Request
from easyvista_python_client.references import (
    Reference,
    _scalar,
    localized_label,
    resolve_reference,
)


def test_display_prefers_label_then_id_then_none():
    assert Reference(id="1", label="Open").display == "Open"
    assert Reference(id="1", label=None).display == "1"
    assert Reference(id=None, label=None).display is None


def test_nested_label_prefers_en_then_fr_then_path_and_drops_href():
    rec = {
        "STATUS": {
            "STATUS_FR": "En cours",
            "STATUS_EN": "Open",
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


def test_localized_label_prefers_en_then_fr():
    rec = {"DEPARTMENT_EN": "Dept", "DEPARTMENT_FR": "Service"}
    assert localized_label(rec, "DEPARTMENT") == "Dept"


def test_localized_label_skips_bracketed_placeholder_so_fr_wins():
    # Unpopulated localized columns echo a "[CODE]" placeholder on this instance.
    rec = {"DEPARTMENT_EN": "[ACME-CORP]", "DEPARTMENT_FR": "ACME CORP"}
    assert localized_label(rec, "DEPARTMENT") == "ACME CORP"


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

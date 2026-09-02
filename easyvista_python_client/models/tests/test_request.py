from datetime import datetime, timedelta, timezone

import pydantic
import pytest
from pydantic import ValidationError

from easyvista_python_client import ev_since_filter
from easyvista_python_client.models.request import PostRequest, Request, RequestUpdate


def test_request_accepts_href_reference_description():
    # The single-ticket GET expands DESCRIPTION into an HREF ref (open item O4).
    req = Request.model_validate(
        {"RFC_NUMBER": "I1", "DESCRIPTION": {"HREF": "https://ev.test/.../description"}}
    )
    assert isinstance(req.description, dict)
    assert req.description["HREF"].endswith("/description")


def test_request_reads_aliased_fields():
    req = Request.model_validate(
        {"RFC_NUMBER": "I240101_0001", "HREF": "https://ev.test/.../requests/123"}
    )
    assert req.rfc_number == "I240101_0001"
    assert req.href.endswith("/requests/123")


def test_post_request_to_api_uses_known_fields():
    payload = PostRequest(catalog_code="CODE1", title="T", description="hi")
    body = payload.to_api()
    assert body == {"catalog_code": "CODE1", "title": "T", "description": "hi"}


def test_catalog_guid_is_accepted_and_serialized() -> None:
    body = PostRequest(catalog_guid="{ABC-123}").to_api()
    assert body["catalog_guid"] == "{ABC-123}"


def test_catalog_code_alone_still_works() -> None:
    body = PostRequest(catalog_code="EAZ_INC_000").to_api()
    assert body["catalog_code"] == "EAZ_INC_000"


def test_both_catalog_identifiers_may_be_sent() -> None:
    body = PostRequest(catalog_guid="{ABC-123}", catalog_code="EAZ_INC_000").to_api()
    assert body["catalog_guid"] == "{ABC-123}"
    assert body["catalog_code"] == "EAZ_INC_000"


def test_neither_catalog_identifier_is_refused_locally() -> None:
    """The server answers this with a 590 naming no field; fail here instead."""
    with pytest.raises(ValidationError) as excinfo:
        PostRequest(title="no subject")
    assert "catalog_guid" in str(excinfo.value)
    assert "catalog_code" in str(excinfo.value)


def test_post_request_to_api_includes_documented_create_fields():
    payload = PostRequest(
        catalog_code="SAMPLE_CATALOG",
        title="Printer down",
        description="It is broken",
        origin=7,
        department_id=9,
        urgency_id=8,
        impact_id=28,
        recipient_mail="user@example.com",
        external_reference="REF-1",
    )
    assert payload.to_api() == {
        "catalog_code": "SAMPLE_CATALOG",
        "title": "Printer down",
        "description": "It is broken",
        "origin": 7,
        "department_id": 9,
        "urgency_id": 8,
        "impact_id": 28,
        "recipient_mail": "user@example.com",
        "external_reference": "REF-1",
    }


def test_post_request_custom_fields_get_e_prefix():
    payload = PostRequest(
        catalog_code="C", custom_fields={"site": "Paris", "e_lvl": "3"}
    )
    body = payload.to_api()
    assert body["catalog_code"] == "C"
    assert body["e_site"] == "Paris"
    assert body["e_lvl"] == "3"


def test_request_update_to_api_omits_none():
    update = RequestUpdate(impact_id=5)
    assert update.to_api() == {"impact_id": 5}


def test_request_declares_title_and_core_scalars():
    """A live-shaped single-ticket GET parses into typed attributes."""
    req = Request.model_validate(
        {
            "RFC_NUMBER": "I240101_0001",
            "REQUEST_ID": "4242",
            "HREF": "https://ev.test/api/v1/00000/requests/4242",
            "TITLE": "Printer down",
            "DESCRIPTION": "The 3rd-floor printer is offline",
            "EXTERNAL_REFERENCE": "REF-1",
            "SD_CATALOG_ID": "5791",
            "STATUS_ID": "3",
            "URGENCY_ID": "8",
            "IMPACT_ID": "28",
            "SEVERITY_ID": "2",
            "REQUEST_ORIGIN_ID": "7",
            "DEPARTMENT_ID": "9",
            "LOCATION_ID": "11",
            "REQUESTOR_ID": "12",
            "RECIPIENT_ID": "13",
            "OWNER_ID": "14",
            "SUBMIT_DATE_UT": "2026-01-01 09:00:00",
            "LAST_UPDATE": "2026-01-02 10:30:00",
        }
    )
    assert req.title == "Printer down"
    assert req.request_id == 4242  # str -> int coercion
    assert req.sd_catalog_id == 5791
    assert req.status_id == 3
    assert req.urgency_id == 8
    assert req.impact_id == 28
    assert req.severity_id == 2
    assert req.request_origin_id == 7
    assert req.department_id == 9
    assert req.location_id == 11
    assert req.requestor_id == 12
    assert req.recipient_id == 13
    assert req.owner_id == 14
    assert req.external_reference == "REF-1"
    # No offset in the fixture -> parse_ev_datetime treats it as UTC.
    assert req.submit_date_ut == datetime(2026, 1, 1, 9, 0, 0, tzinfo=timezone.utc)
    assert req.last_update == datetime(2026, 1, 2, 10, 30, 0, tzinfo=timezone.utc)


def test_request_coerces_empty_string_numerics_to_none():
    """EasyVista returns "" for an absent numeric; a bare int|None would raise."""
    req = Request.model_validate(
        {"RFC_NUMBER": "I1", "STATUS_ID": "", "DEPARTMENT_ID": "", "OWNER_ID": ""}
    )
    assert req.status_id is None
    assert req.department_id is None
    assert req.owner_id is None


def test_request_has_no_catalog_guid_attribute():
    """CATALOG_GUID is not a field on requests: 0/25 live GETs, absent from the
    vendor docs. Declaring it promised an attribute that could never populate."""
    assert "catalog_guid" not in Request.model_fields


def test_request_keeps_undeclared_fields_as_extras():
    """The deliberately-undeclared keys must survive, not be dropped.

    Round-tripping alone doesn't prove these stay *undeclared*:
    ``model_dump(by_alias=True)`` emits the same output whether a key is a
    real declared field or an ``extra="allow"`` extra. So this also asserts
    each family is absent from ``Request.model_fields`` (keyed by python
    field name, not alias — see ``test_request_has_no_catalog_guid_attribute``),
    which is the actual binding constraint: none of these may ever be
    promoted to a declared field.
    """
    req = Request.model_validate(
        {
            "RFC_NUMBER": "I1",
            "SD_CATALOG_PATH": "Cat/Sub/Leaf",  # returned but unsearchable
            "DEPARTMENT_PATH": "Dept/Sub",  # returned but unsearchable
            # LOCATION_PATH: returned; unsearchable presumed by family
            # resemblance to the two above, never tested (spec O-PATH-SCOPE).
            "LOCATION_PATH": "Site/Building",
            "E_GTI_ID": "77",  # instance-custom
            "AVAILABLE_FIELD_1": "x",  # available slot
        }
    )
    dumped = req.model_dump(by_alias=True)
    assert dumped["SD_CATALOG_PATH"] == "Cat/Sub/Leaf"
    assert dumped["DEPARTMENT_PATH"] == "Dept/Sub"
    assert dumped["LOCATION_PATH"] == "Site/Building"
    assert dumped["E_GTI_ID"] == "77"
    assert dumped["AVAILABLE_FIELD_1"] == "x"

    assert "sd_catalog_path" not in Request.model_fields
    assert "department_path" not in Request.model_fields
    assert "location_path" not in Request.model_fields
    assert "e_gti_id" not in Request.model_fields
    assert "available_field_1" not in Request.model_fields


def test_request_title_absent_is_none_not_error():
    """Portal-created tickets carry no TITLE; that must parse, not raise."""
    assert Request.model_validate({"RFC_NUMBER": "I1"}).title is None


def test_request_update_serializes_title():
    assert RequestUpdate(title="New title").to_api() == {"title": "New title"}


def test_request_update_omits_unset_fields():
    assert RequestUpdate(impact_id=3).to_api() == {"impact_id": 3}


def test_request_declares_the_official_time_fields():
    ticket = Request.model_validate(
        {
            "RFC_NUMBER": "I1",
            "CREATION_DATE_UT": "2026-07-28 09:00:00",
            "MAX_RESOLUTION_DATE_UT": "2026-07-30 09:00:00",
            "EXPECTED_DATE_UT": "2026-07-29 09:00:00",
            "END_DATE_UT": "",
            "SLA_ID": 4,
            # A string, not an int: the 2026-07-28 Phase 0 probe found this
            # field consistently typed str across every ticket it checked.
            "TIME_USED_TO_SOLVE_REQUEST": "3600",
        }
    )
    # No offset in the fixtures -> parse_ev_datetime treats them as UTC.
    assert ticket.creation_date_ut == datetime(
        2026, 7, 28, 9, 0, 0, tzinfo=timezone.utc
    )
    assert ticket.max_resolution_date_ut == datetime(
        2026, 7, 30, 9, 0, 0, tzinfo=timezone.utc
    )
    assert ticket.expected_date_ut == datetime(
        2026, 7, 29, 9, 0, 0, tzinfo=timezone.utc
    )
    assert ticket.end_date_ut is None  # "" sentinel
    assert ticket.sla_id == 4
    assert ticket.time_used_to_solve_request == "3600"


def test_request_time_fields_default_to_none_when_absent():
    ticket = Request.model_validate({"RFC_NUMBER": "I1"})
    assert ticket.creation_date_ut is None
    assert ticket.max_resolution_date_ut is None
    assert ticket.sla_id is None


def test_sla_id_treats_the_empty_string_sentinel_as_none():
    assert Request.model_validate({"RFC_NUMBER": "I1", "SLA_ID": ""}).sla_id is None


def test_gtr_custom_fields_stay_out_of_the_official_bucket():
    # Declaring the official time fields must not pull the instance-specific
    # E_GTR_*/E_GTI_* family in with them: those are per-deployment and belong
    # in classify_fields().custom, which is what keeps this library portable.
    fc = Request.model_validate(
        {"RFC_NUMBER": "I1", "SLA_ID": 4, "E_GTR_STATUS": "OK", "E_GTI_UT": "x"}
    ).classify_fields()
    assert set(fc.custom) == {"E_GTR_STATUS", "E_GTI_UT"}
    assert "SLA_ID" in fc.official
    assert "MAX_RESOLUTION_DATE_UT" in fc.official


def test_request_timestamps_are_aware_datetimes():
    """BREAKING as of 2026-08-17: these were str. EV-R7 proved the format."""
    request = Request.model_validate(
        {
            "RFC_NUMBER": "I240101_0001",
            "LAST_UPDATE": "2026-08-17T15:40:41.610+02:00",
            "CREATION_DATE_UT": "2026-08-17T15:40:36.383+02:00",
            "END_DATE_UT": "",
        }
    )
    assert request.last_update.tzinfo is not None
    assert request.last_update.utcoffset() == timedelta(hours=2)
    assert request.creation_date_ut.year == 2026
    assert request.end_date_ut is None  # "" sentinel


def test_a_request_timestamp_round_trips_into_a_change_window_filter():
    """The retype must not cost the ability to build an interval (EV-R5)."""
    request = Request.model_validate(
        {"RFC_NUMBER": "I240101_0001", "LAST_UPDATE": "2026-08-17T15:40:41.610+02:00"}
    )
    assert ev_since_filter("LAST_UPDATE", request.last_update) == (
        "LAST_UPDATE:(2026-08-17T15:40:41.610+02:00;)"
    )


def test_request_update_carries_the_writable_columns():
    """Pins the emitted body SHAPE only -- the client's own lowercase key names.

    This asserts nothing about the wire. A 200 on a PUT is not a receipt on this
    API: a field it cannot honour is silently dropped while the request succeeds.
    The read-back that does establish these three land lives in
    ``integration_tests/test_live_ticket_identity.py``
    ``::test_request_update_writes_impact_owner_and_external_reference``.
    """
    body = RequestUpdate(
        title="t",
        impact_id=1,
        owner_id=42,
        external_reference="PEER-abc123",
    ).to_api()
    assert body == {
        "title": "t",
        "impact_id": 1,
        "owner_id": 42,
        "external_reference": "PEER-abc123",
    }


def test_request_update_still_rejects_an_unverified_field():
    """extra="forbid" is the guard that caught SEVERITY_ID before the wire."""
    with pytest.raises(pydantic.ValidationError):
        RequestUpdate(severity_id=2)


def test_external_reference_longer_than_fifty_characters_is_refused_locally():
    """Bisected live: 50 accepted, 51 -> HTTP 590. Refuse before the round trip.

    Over-length is REJECTED server-side, not truncated, and the previously
    stored value survives — so this guard loses nothing and saves a request.
    """
    with pytest.raises(pydantic.ValidationError):
        RequestUpdate(external_reference="X" * 51)
    assert (
        RequestUpdate(external_reference="X" * 50).to_api()["external_reference"]
        == "X" * 50
    )


def test_request_update_refuses_status_id():
    """``RequestUpdate(status_id=...)`` must not be constructible.

    A regression guard with teeth, because the field existed and its failure was
    invisible: measured live, a flat status write is rejected 590 when sent alone
    and -- far worse -- returns 200, applies its companion field and drops the
    status silently when sent beside one. Anything that reinstates this field
    reinstates a write that reports success and stores nothing. The status route
    is ``set_status`` / the ``{"closed": {"status_GUID": ...}}`` envelope.
    """
    with pytest.raises(ValidationError) as excinfo:
        RequestUpdate(status_id=2)
    assert "status_id" in str(excinfo.value)


def test_post_request_carries_the_measured_safe_create_body():
    """Every field of the measured-safe create body survives ``to_api``.

    Tier 4, measured on one instance on 2026-08-18, and it may not generalise:
    the seven-field body -- catalog + origin + title + description +
    department_id + urgency_id + impact_id -- was accepted on every catalog
    tried, while the same body minus the four ids was refused on some of them
    with an HTTP 590 whose message is a bare SQL parser error naming no field.

    The vendor requires only ``catalog_guid`` or ``catalog_code``
    (``docs/vendor-api-reference.md``, tier 1); the fuller body is a hedge
    against per-catalog configuration, not an API requirement. The shape is
    pinned here anyway, because a field silently dropped from this model would
    take that hedge away from every caller relying on it.
    """
    body = PostRequest(
        catalog_code="SYNTH_INC_001",
        origin=7,
        title="t",
        description="d",
        department_id=9,
        urgency_id=7,
        impact_id=21,
        external_reference="X",
    ).to_api()
    assert body == {
        "catalog_code": "SYNTH_INC_001",
        "origin": 7,
        "title": "t",
        "description": "d",
        "department_id": 9,
        "urgency_id": 7,
        "impact_id": 21,
        "external_reference": "X",
    }


def test_origin_accepts_the_vendor_documented_string() -> None:
    body = PostRequest(catalog_code="X", origin="Phone").to_api()
    assert body["origin"] == "Phone"


def test_origin_still_accepts_an_int() -> None:
    body = PostRequest(catalog_code="X", origin=7).to_api()
    assert body["origin"] == 7


def test_origin_keeps_a_numeric_string_as_a_string() -> None:
    """``origin="7"`` must reach the wire as ``"7"``, not as ``7``.

    The vendor documents ``origin`` as a **string** (tier 1), so the string
    form is the documented one and there is nothing to normalize towards. This
    pins the smart-union behaviour: before the field was widened to
    ``int | str`` the declared ``int`` coerced ``"7"`` to ``7``, so this is the
    wire form that changed, and it must not drift back.
    """
    assert PostRequest(catalog_code="X", origin="7").to_api()["origin"] == "7"


def test_impact_id_coerces_a_numeric_string_to_the_documented_int() -> None:
    """``impact_id="28"`` must reach the wire as ``28``.

    The vendor documents ``impact_id`` as an **integer** (tier 1). The ``str``
    branch exists so a caller who quotes the value is not rejected -- not so
    that the quoted form ships. ``union_mode="left_to_right"`` puts ``int``
    first, which restores the normalization the declared ``int`` used to do.
    """
    assert PostRequest(catalog_code="X", impact_id="28").to_api()["impact_id"] == 28
    assert PostRequest(catalog_code="X", impact_id=17).to_api()["impact_id"] == 17


def test_impact_id_still_accepts_a_non_numeric_string() -> None:
    """The ``str`` branch must survive the left-to-right union.

    ``left_to_right`` tries ``int`` first; a value that is not a number must
    fall through to ``str`` rather than raise. Nothing a caller could send
    before may be refused now.
    """
    body = PostRequest(catalog_code="X", impact_id="Critical").to_api()
    assert body["impact_id"] == "Critical"


def test_department_id_and_recipient_id_accept_the_documented_string() -> None:
    """Both are vendor-documented as **strings** (tier 1), so both take one.

    They were typed ``int`` until this change, which accepted the documented
    string form and then coerced it to a number on the way out. It is no
    longer rewritten: the string reaches the wire as written, and an int
    still reaches it as an int.
    """
    body = PostRequest(
        catalog_code="X", department_id="9", recipient_id="42"
    ).to_api()
    assert body["department_id"] == "9"
    assert body["recipient_id"] == "42"
    ints = PostRequest(catalog_code="X", department_id=9, recipient_id=42).to_api()
    assert ints["department_id"] == 9
    assert ints["recipient_id"] == 42


_VENDOR_CREATE_FIELDS = (
    "location_id",
    "location_code",
    "department_code",
    "recipient_name",
    "recipient_identification",
    "requestor_identification",
    "requestor_mail",
    "requestor_name",
    "parentrequest",
    "phone",
    "submit_date",
)


@pytest.mark.parametrize("name", _VENDOR_CREATE_FIELDS)
def test_vendor_documented_create_field_is_declared(name: str) -> None:
    """Each is tier 1 -- documented by the vendor, not verified live here."""
    body = PostRequest(catalog_code="X", **{name: "value"}).to_api()
    assert body[name] == "value"


def test_workflow_start_is_a_boolean() -> None:
    body = PostRequest(catalog_code="X", workflow_start=True).to_api()
    assert body["workflow_start"] is True


def test_workflow_start_false_is_sent_not_dropped() -> None:
    """exclude_none drops None, not False -- a caller disabling the workflow
    must not have that silently discarded."""
    body = PostRequest(catalog_code="X", workflow_start=False).to_api()
    assert body["workflow_start"] is False


# --- the create guard reads the body that ships, not the attributes declared --


def test_extra_payload_satisfies_the_catalog_guard() -> None:
    """``extra_payload`` is the documented route past a declared field.

    A guard reading ``self.catalog_guid`` refused this body even though it is
    exactly what the vendor documents as a complete create -- the model's own
    escape hatch was unusable for the one field the model requires. Deriving
    from ``to_api()`` fixes that and cannot drift from its case-insensitive
    merge rule, because it *is* that rule.
    """
    payload = PostRequest(extra_payload={"CATALOG_GUID": "{ABC}"})
    assert payload.to_api() == {"CATALOG_GUID": "{ABC}"}


def test_an_explicit_none_in_extra_payload_does_not_satisfy_the_guard() -> None:
    """A ``None`` is an absent value, not a supplied one.

    ``to_api()`` already drops ``None`` for declared fields; without the
    ``value is not None`` filter in ``_shipped_keys``, an explicit
    ``{"catalog_code": None}`` would satisfy a guard while shipping nothing.
    """
    with pytest.raises(ValidationError, match="needs a subject"):
        PostRequest(extra_payload={"catalog_code": None})


def test_a_custom_field_named_catalog_code_does_not_satisfy_the_guard() -> None:
    """``custom_fields`` serialize with an ``e_`` prefix, so the key differs.

    ``e_catalog_code`` is not the key the API reads, and the guard correctly
    still refuses -- deriving from ``to_api()`` gets this right for free.
    """
    with pytest.raises(ValidationError, match="needs a subject"):
        PostRequest(custom_fields={"catalog_code": "X"})


# --- the asset / CI selectors -----------------------------------------------


def test_post_request_ships_the_asset_and_ci_selectors() -> None:
    """All six are tier 1, and the wire spellings have NO underscore.

    ``to_api()`` serializes by attribute name (``model_dump()`` without
    ``by_alias``), so a ``serialization_alias`` would never reach the body and
    renaming these to ``asset_id`` / ``asset_tag`` would ship keys the vendor
    does not document. The documented case-insensitivity is not
    underscore-insensitivity, which is what this test pins.
    """
    body = PostRequest(
        catalog_code="X",
        assetid=9504,
        assettag="ZGCSS_732",
        asset_name="a laptop",
        ci_id=77,
        ci_asset_tag="CI-1",
        ci_name="a service",
    ).to_api()
    assert body["assetid"] == 9504
    assert body["assettag"] == "ZGCSS_732"
    assert body["asset_name"] == "a laptop"
    assert body["ci_id"] == 77
    assert body["ci_asset_tag"] == "CI-1"
    assert body["ci_name"] == "a service"
    assert "asset_id" not in body
    assert "asset_tag" not in body


def test_an_int_assetid_serializes_unchanged() -> None:
    """The vendor types it a string; the int branch exists because a caller
    holding ``Asset.asset_id`` holds an int. Neither branch coerces."""
    assert PostRequest(catalog_code="X", assetid=9504).to_api()["assetid"] == 9504
    assert PostRequest(catalog_code="X", assetid="9504").to_api()["assetid"] == "9504"


def test_time_used_to_solve_request_accepts_both_a_string_and_an_int() -> None:
    """Tier 4 measured a string on one instance on one day; that is evidence
    about the instance, not about the column. A ``str``-only declaration
    rejected ``3600`` and failed the whole record -- on a search, the whole
    page. Neither branch coerces into the other."""
    assert (
        Request.model_validate(
            {"TIME_USED_TO_SOLVE_REQUEST": "3600"}
        ).time_used_to_solve_request
        == "3600"
    )
    assert (
        Request.model_validate(
            {"TIME_USED_TO_SOLVE_REQUEST": 3600}
        ).time_used_to_solve_request
        == 3600
    )

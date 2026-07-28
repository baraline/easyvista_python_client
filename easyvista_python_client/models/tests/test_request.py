import pytest
from pydantic import ValidationError

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


def test_post_request_rejects_catalog_guid():
    """catalog_guid is not a verified create field and cannot be verified on the
    probe profile (GET /catalog-requests is 403). extra="forbid" now rejects it
    rather than silently sending a field the server may ignore."""
    with pytest.raises(ValidationError):
        PostRequest(catalog_code="CODE1", catalog_guid="GUID1")


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
    update = RequestUpdate(status_id=5)
    assert update.to_api() == {"status_id": 5}


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
    assert req.submit_date_ut == "2026-01-01 09:00:00"
    assert req.last_update == "2026-01-02 10:30:00"


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
    assert RequestUpdate(status_id=3).to_api() == {"status_id": 3}


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
    assert ticket.creation_date_ut == "2026-07-28 09:00:00"
    assert ticket.max_resolution_date_ut == "2026-07-30 09:00:00"
    assert ticket.expected_date_ut == "2026-07-29 09:00:00"
    assert ticket.end_date_ut == ""
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

import pytest
from pydantic import ValidationError

from easyvista_python_client.models.common import EasyvistaModel
from easyvista_python_client.models.request import PostRequest, Request, RequestUpdate
from easyvista_python_client.pagination import (
    SearchResult,
    build_search_result,
    extract_records,
)


class _Sample(EasyvistaModel):
    pass


def test_base_model_keeps_unknown_fields():
    model = _Sample.model_validate({"RFC_NUMBER": "I123", "e_custom1": "x"})
    dumped = model.model_dump(by_alias=True)
    assert dumped["RFC_NUMBER"] == "I123"
    assert dumped["e_custom1"] == "x"


def test_extract_records_reads_records_key():
    data = {"records": [{"a": 1}], "record_count": 1, "total_record_count": 5}
    assert extract_records(data) == [{"a": 1}]


def test_extract_records_handles_requests_envelope():
    data = {"requests": [{"a": 1}, {"b": 2}]}
    assert extract_records(data) == [{"a": 1}, {"b": 2}]


def test_extract_records_handles_assets_and_documents_envelopes():
    assert extract_records({"assets": [{"a": 1}]}) == [{"a": 1}]
    assert extract_records({"documents": [{"d": 1}, {"d": 2}]}) == [{"d": 1}, {"d": 2}]


def test_extract_records_wraps_single_object():
    assert extract_records({"RFC_NUMBER": "I1"}) == [{"RFC_NUMBER": "I1"}]


def test_search_result_holds_counts():
    sr = SearchResult(records=[1, 2], record_count=2, total_record_count=9, href="h")
    assert sr.records == [1, 2]
    assert sr.total_record_count == 9


def test_build_search_result_coerces_string_counts():
    # The live API returns counts as strings (open item O1).
    sr = build_search_result(
        {
            "record_count": "1",
            "total_record_count": "42",
            "HREF": "h",
            "@next": "https://ev.test/requests?offset=1&max_rows=1",
        },
        records=[1],
    )
    assert sr.record_count == 1
    assert sr.total_record_count == 42
    assert isinstance(sr.total_record_count, int)
    assert sr.href == "h"
    assert sr.next_url == "https://ev.test/requests?offset=1&max_rows=1"


def test_build_search_result_next_url_absent_is_none():
    sr = build_search_result(
        {"record_count": "1", "total_record_count": "1"}, records=[1]
    )
    assert sr.next_url is None


def test_build_search_result_falls_back_when_counts_absent_or_bad():
    sr = build_search_result({"total_record_count": "not-a-number"}, records=[1, 2])
    assert sr.record_count == 2  # falls back to len(records)
    assert sr.total_record_count == 2  # bad value -> falls back to record_count


def test_build_search_result_handles_non_dict_payload():
    sr = build_search_result([{"a": 1}], records=[1, 2, 3])
    assert sr.record_count == 3
    assert sr.total_record_count == 3
    assert sr.href is None


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

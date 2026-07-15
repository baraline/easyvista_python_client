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
    payload = PostRequest(catalog_guid="GUID1", catalog_code="CODE1", description="hi")
    body = payload.to_api()
    assert body == {
        "catalog_guid": "GUID1",
        "catalog_code": "CODE1",
        "description": "hi",
    }


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

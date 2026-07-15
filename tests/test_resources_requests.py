from easyvista_python_client.models.request import PostRequest, RequestUpdate
from easyvista_python_client.pagination import SearchResult
from easyvista_python_client.resources import requests as r


def test_build_create_ticket_wraps_batch_envelope():
    spec, parser = r.build_create_ticket(PostRequest(catalog_code="C"))
    assert spec.method == "POST"
    assert spec.path == "requests"
    assert spec.json == {"requests": [{"catalog_code": "C"}]}
    parsed = parser({"records": [{"RFC_NUMBER": "I1"}]})
    assert parsed.rfc_number == "I1"


def test_create_ticket_derives_rfc_from_href_only_response():
    # POST /requests returns an HREF-only body (no RFC_NUMBER); the id is the
    # last path segment of the HREF and must populate rfc_number.
    _spec, parser = r.build_create_ticket(PostRequest(catalog_code="C"))
    parsed = parser({"HREF": "https://host/api/v1/12345/requests/I240101_0010"})
    assert parsed.rfc_number == "I240101_0010"
    assert parsed.href == "https://host/api/v1/12345/requests/I240101_0010"


def test_explicit_rfc_number_not_overwritten_by_href():
    # A normal read (RFC_NUMBER present) must keep its value even if HREF differs.
    _spec, parser = r.build_get_ticket("I1")
    parsed = parser(
        {"RFC_NUMBER": "I1", "HREF": "https://host/api/v1/12345/requests/I1"}
    )
    assert parsed.rfc_number == "I1"


def test_build_get_ticket():
    spec, parser = r.build_get_ticket("I1")
    assert spec.method == "GET"
    assert spec.path == "requests/I1"
    assert parser({"RFC_NUMBER": "I1"}).rfc_number == "I1"


def test_build_search_tickets_params():
    spec, parser = r.build_search_tickets(
        search="STATUS_EN~Closed",
        fields=["RFC_NUMBER", "HREF"],
        sort="RFC_NUMBER",
        max_rows=50,
    )
    assert spec.method == "GET"
    assert spec.path == "requests"
    assert spec.params == {
        "search": "STATUS_EN~Closed",
        "fields": "RFC_NUMBER,HREF",
        "sort": "RFC_NUMBER",
        "max_rows": 50,
    }
    result = parser(
        {
            "records": [{"RFC_NUMBER": "I1"}],
            "record_count": 1,
            "total_record_count": 7,
            "HREF": "h",
        }
    )
    assert isinstance(result, SearchResult)
    assert result.total_record_count == 7
    assert result.records[0].rfc_number == "I1"


def test_build_search_tickets_omits_unset_params():
    spec, _ = r.build_search_tickets()
    assert spec.params == {}


def test_build_search_tickets_includes_offset():
    spec, _ = r.build_search_tickets(max_rows=10, offset=20)
    assert spec.params == {"max_rows": 10, "offset": 20}

    spec0, _ = r.build_search_tickets(offset=0)
    assert spec0.params == {"offset": 0}


def test_build_update_ticket():
    spec, _parser = r.build_update_ticket("I1", RequestUpdate(status_id=3))
    assert spec.method == "PUT"
    assert spec.path == "requests/I1"
    assert spec.json == {"status_id": 3}


def test_build_close_ticket_default_and_comment():
    spec, _ = r.build_close_ticket("I1")
    assert spec.json == {"closed": {}}
    spec2, _ = r.build_close_ticket("I1", comment="done")
    assert spec2.json == {"closed": {"comment": "done"}}


def test_build_close_ticket_full_documented_shape():
    spec, _ = r.build_close_ticket(
        "I1",
        status_guid="{00000000-0000-0000-0000-000000000000}",
        delete_actions=1,
        comment="resolved",
    )
    assert spec.method == "PUT"
    assert spec.path == "requests/I1"
    assert spec.json == {
        "closed": {
            "status_GUID": "{00000000-0000-0000-0000-000000000000}",
            "delete_actions": 1,
            "comment": "resolved",
        }
    }

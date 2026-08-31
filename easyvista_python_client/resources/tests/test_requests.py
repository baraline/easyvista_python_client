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
        search='STATUS_ID:"3"',
        fields=["RFC_NUMBER", "HREF"],
        sort="RFC_NUMBER",
        max_rows=50,
    )
    assert spec.method == "GET"
    assert spec.path == "requests"
    assert spec.params == {
        "search": 'STATUS_ID:"3"',
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
    spec, _parser = r.build_update_ticket("I1", RequestUpdate(impact_id=3))
    assert spec.method == "PUT"
    assert spec.path == "requests/I1"
    assert spec.json == {"impact_id": 3}


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


def test_build_set_status_sends_the_closed_envelope():
    """``set_status`` is the ``closed`` envelope, addressed by GUID.

    Pins both halves of the call shape that took several wrong turns to find: the
    body is wrapped in ``closed`` (not flat), and the key is ``status_GUID`` (not
    ``STATUS_ID``). The envelope is not limited to closing -- six different status
    GUIDs each landed on exactly the status requested.
    """
    spec, _parser = r.build_set_status("I1", status_guid="{G}", comment="c")
    assert spec.method == "PUT"
    assert spec.path == "requests/I1"
    assert spec.json == {"closed": {"status_GUID": "{G}", "comment": "c"}}


def test_build_set_status_matches_build_close_ticket():
    """The two builders are the same request; only the name differs."""
    a, _ = r.build_set_status("I1", status_guid="{G}")
    b, _ = r.build_close_ticket("I1", status_guid="{G}")
    assert (a.method, a.path, a.json) == (b.method, b.path, b.json)


def test_close_ticket_carries_the_two_previously_undeclared_documented_fields():
    """``end_date`` and ``catalog_GUID`` are tier 1 and were unreachable.

    The vendor's close body is status_GUID / end_date / catalog_GUID /
    delete_actions / comment; this package declared only three of the five, so
    requalifying-on-close and back-dating a closure needed extra_payload -- and
    neither field is on a write model, so there was no extra_payload to use.
    """
    spec, _ = r.build_close_ticket(
        "I1",
        status_guid="{G}",
        end_date="28/08/2026",
        catalog_guid="{C}",
        comment="done",
        delete_actions=True,
    )
    assert spec.json == {
        "closed": {
            "status_GUID": "{G}",
            "delete_actions": True,
            "comment": "done",
            "end_date": "28/08/2026",
            "catalog_GUID": "{C}",
        }
    }


def test_close_ticket_omits_every_unset_field():
    """All five are optional: an empty envelope closes to the default status."""
    spec, _ = r.build_close_ticket("I1")
    assert spec.json == {"closed": {}}


def test_close_ticket_uses_the_vendor_route_not_the_close_subpath():
    """``PUT requests/{rfc}`` with a wrapper IS the documented route.

    An instance's OpenAPI also declares ``PUT|PATCH requests/{rfc}/close``;
    this pins that the package deliberately sends the documented one, so a
    later reader does not "fix" it into the subpath.
    """
    spec, _ = r.build_close_ticket("I1", status_guid="{G}")
    assert spec.method == "PUT"
    assert spec.path == "requests/I1"


def test_delete_actions_passes_a_bool_through_unchanged():
    """The vendor types it boolean; the package used to type it int only."""
    spec, _ = r.build_close_ticket("I1", delete_actions=False)
    assert spec.json["closed"]["delete_actions"] is False


def test_build_get_ticket_forwards_a_fields_projection():
    """No projection means no ``fields`` parameter at all -- the request this
    builder has always sent."""
    spec, _ = r.build_get_ticket("I1")
    assert spec.params is None
    spec, _ = r.build_get_ticket("I1", fields=["RFC_NUMBER", "TITLE"])
    assert spec.params == {"fields": "RFC_NUMBER,TITLE"}


def test_build_close_ticket_unwraps_a_requests_envelope():
    """Green before and after -- it pins the accident.

    This parser passed no envelope key and worked only because ``"requests"``
    happens to sit in ``extract_records``' hardcoded fallback tuple, a list
    that belongs to no resource in particular. The key is now explicit.
    """
    _, parser = r.build_close_ticket("I1")
    assert parser({"requests": [{"RFC_NUMBER": "I1"}]}).rfc_number == "I1"


def test_build_close_ticket_unwraps_a_capital_r_requests_envelope():
    """Red before the case-insensitive match."""
    _, parser = r.build_close_ticket("I1")
    assert parser({"Requests": [{"RFC_NUMBER": "I1"}]}).rfc_number == "I1"

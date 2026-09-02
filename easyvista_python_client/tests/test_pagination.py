from easyvista_python_client.pagination import (
    SearchResult,
    build_search_result,
    extract_records,
)


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


# --- envelope casing is not stable across deployments ------------------------


def test_extract_records_matches_an_envelope_key_case_insensitively():
    """The instance already answers a capital-D ``Documents``.

    Measured 2026-08-17 on the verified instance, where the same instance's own
    OpenAPI examples spell every envelope lowercase -- so matching the casing
    exactly is a coin flip per deployment.
    """
    assert extract_records({"Documents": [{"d": 1}]}) == [{"d": 1}]
    assert extract_records({"Actions": [{"a": 1}]}, "actions") == [{"a": 1}]
    assert extract_records({"REQUESTS": [{"r": 1}]}) == [{"r": 1}]


def test_extract_records_still_prefers_records_over_a_resource_envelope():
    """Priority is unchanged: ``records`` first, then the envelope key.

    The case-insensitive rewrite must not disturb the order, or a payload
    carrying both would start unwrapping the wrong one.
    """
    payload = {"records": [{"r": 1}], "Actions": [{"a": 1}]}
    assert extract_records(payload, "actions") == [{"r": 1}]


def test_extract_records_ignores_a_scalar_list_under_an_envelope_name():
    """A list of scalars is not an envelope of records.

    Without this check the payload below returned ``[]`` -- silently, and
    indistinguishably from an empty page -- rather than falling through to
    ``[data]``. The check matters more now that matching is case-insensitive:
    it is the guard against a record column that happens to be named like an
    envelope and to hold a list.
    """
    assert extract_records({"REQUESTS": ["a", "b"]}) == [{"REQUESTS": ["a", "b"]}]


def test_extract_records_still_returns_an_empty_page_as_empty():
    """An empty envelope list is a legitimate empty page, not a fallthrough."""
    assert extract_records({"records": []}) == []
    assert extract_records({"Documents": []}) == []

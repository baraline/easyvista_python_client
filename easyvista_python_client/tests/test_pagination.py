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

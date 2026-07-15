from easyvista_python_client.models.asset import Asset, PostAsset
from easyvista_python_client.pagination import SearchResult, extract_records
from easyvista_python_client.resources.descriptor import (
    ResourceDescriptor,
    build_create,
    build_get,
    build_search,
    build_update,
)

ASSETS = ResourceDescriptor(path="assets", envelope_key="assets", model=Asset)


def test_extract_records_default_behavior_unchanged():
    assert extract_records({"records": [{"A": 1}]}) == [{"A": 1}]
    assert extract_records({"assets": [{"A": 1}]}) == [{"A": 1}]
    assert extract_records({"HREF": "x"}) == [{"HREF": "x"}]


def test_extract_records_honors_envelope_key():
    # A response echoed in a resource's own envelope is unwrapped when named.
    assert extract_records({"departments": [{"D": 1}]}, "departments") == [{"D": 1}]
    # records still wins and precedes the envelope key.
    assert extract_records({"records": [{"R": 1}]}, "departments") == [{"R": 1}]


def test_build_get_returns_spec_and_first_record_parser():
    spec, parser = build_get(ASSETS, "9504")
    assert spec.method == "GET"
    assert spec.path == "assets/9504"
    assert parser({"ASSET_TAG": "T1"}).asset_tag == "T1"


def test_build_search_builds_params_and_search_result():
    spec, parser = build_search(
        ASSETS, search="ASSET_TAG~T", fields=["ASSET_TAG"], max_rows=5
    )
    assert spec.method == "GET"
    assert spec.path == "assets"
    assert spec.params == {
        "search": "ASSET_TAG~T",
        "fields": "ASSET_TAG",
        "max_rows": 5,
    }
    result = parser(
        {"records": [{"ASSET_TAG": "T1"}], "record_count": 1, "total_record_count": 4}
    )
    assert isinstance(result, SearchResult)
    assert result.total_record_count == 4
    assert result.records[0].asset_tag == "T1"


def test_build_create_wraps_envelope_and_parses_bare_href():
    spec, parser = build_create(ASSETS, PostAsset(catalog_id=3153, asset_tag="T1"))
    assert spec.method == "POST"
    assert spec.path == "assets"
    assert spec.json == {"assets": [{"catalog_id": 3153, "asset_tag": "T1"}]}
    assert parser({"HREF": "https://h/api/v1/acme/assets/9504"}).href.endswith(
        "/assets/9504"
    )


def test_build_update_sends_bare_payload():
    spec, _ = build_update(ASSETS, "9504", PostAsset(catalog_id=3153))
    assert spec.method == "PUT"
    assert spec.path == "assets/9504"
    assert spec.json == {"catalog_id": 3153}

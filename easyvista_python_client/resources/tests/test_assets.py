from easyvista_python_client.models.asset import PostAsset
from easyvista_python_client.pagination import SearchResult
from easyvista_python_client.resources import assets as a


def test_build_create_asset_wraps_envelope():
    spec, parser = a.build_create_asset(PostAsset(catalog_id=3153, asset_tag="T1"))
    assert spec.method == "POST"
    assert spec.path == "assets"
    assert spec.json == {"assets": [{"catalog_id": 3153, "asset_tag": "T1"}]}
    parsed = parser({"HREF": "https://ev.test/api/v1/acme/assets/9504"})
    assert parsed.href.endswith("/assets/9504")


def test_build_get_asset():
    spec, parser = a.build_get_asset("9504")
    assert spec.method == "GET"
    assert spec.path == "assets/9504"
    assert parser({"ASSET_TAG": "T1"}).asset_tag == "T1"


def test_build_search_assets_params():
    spec, parser = a.build_search_assets(
        search="ASSET_TAG~T",
        fields=["ASSET_TAG", "HREF"],
        sort="ASSET_TAG",
        max_rows=20,
    )
    assert spec.method == "GET"
    assert spec.path == "assets"
    assert spec.params == {
        "search": "ASSET_TAG~T",
        "fields": "ASSET_TAG,HREF",
        "sort": "ASSET_TAG",
        "max_rows": 20,
    }
    result = parser(
        {"records": [{"ASSET_TAG": "T1"}], "record_count": 1, "total_record_count": 4}
    )
    assert isinstance(result, SearchResult)
    assert result.total_record_count == 4
    assert result.records[0].asset_tag == "T1"


def test_build_search_assets_omits_unset_params():
    spec, _ = a.build_search_assets()
    assert spec.params == {}

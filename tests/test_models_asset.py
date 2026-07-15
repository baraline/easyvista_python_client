from easyvista_python_client.models.asset import Asset, PostAsset


def test_asset_reads_aliased_fields():
    asset = Asset.model_validate(
        {"ASSET_TAG": "ZGCSS_732", "SERIAL_NUMBER": "DGSF-1", "HREF": ".../assets/9504"}
    )
    assert asset.asset_tag == "ZGCSS_732"
    assert asset.serial_number == "DGSF-1"
    assert asset.href.endswith("/assets/9504")


def test_post_asset_to_api_uses_known_fields():
    payload = PostAsset(catalog_id=3153, asset_tag="ZGCSS_732", status_id=1)
    assert payload.to_api() == {
        "catalog_id": 3153,
        "asset_tag": "ZGCSS_732",
        "status_id": 1,
    }


def test_post_asset_custom_fields_get_e_prefix():
    payload = PostAsset(catalog_id=1, custom_fields={"last_date_update": "12/09/2025"})
    body = payload.to_api()
    assert body["catalog_id"] == 1
    assert body["e_last_date_update"] == "12/09/2025"

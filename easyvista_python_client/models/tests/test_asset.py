from easyvista_python_client.models.asset import Asset, PostAsset


def test_asset_reads_aliased_fields():
    asset = Asset.model_validate(
        {"ASSET_TAG": "ZGCSS_732", "SERIAL_NUMBER": "DGSF-1", "HREF": ".../assets/9504"}
    )
    assert asset.asset_tag == "ZGCSS_732"
    assert asset.serial_number == "DGSF-1"
    assert asset.href.endswith("/assets/9504")


def test_asset_accepts_the_empty_string_sentinel_on_every_id():
    """A CMDB row with no status is ordinary data, and used to fail a whole page.

    ``Asset`` was the only read model on a bare ``int | None`` while every other
    used ``OptionalInt``. EasyVista sends ``""`` for a numeric column carrying
    no value, so such a row raised -- and because ``build_search``'s parser
    validates a page in one list comprehension, it failed every OTHER asset on
    the page with it. Worse, ``get_department_context``'s assets branch catches
    only ``EasyvistaAuthError``/``EasyvistaNotFound``, so the ``ValidationError``
    escaped and took the whole bundle down.
    """
    asset = Asset.model_validate({"ASSET_ID": "", "STATUS_ID": ""})
    assert asset.asset_id is None
    assert asset.status_id is None


def test_asset_accepts_a_numeric_string_id():
    """``OptionalInt`` coerces the string form the API sometimes sends."""
    assert Asset.model_validate({"ASSET_ID": "9504"}).asset_id == 9504


def test_post_asset_to_api_uses_known_fields():
    payload = PostAsset(catalog_id=3153, asset_tag="ZGCSS_732", status_id=1)
    assert payload.to_api() == {
        "catalog_id": 3153,
        "asset_tag": "ZGCSS_732",
        "status_id": 1,
    }


def test_post_asset_coerces_a_quoted_catalog_id():
    """``union_mode="left_to_right"`` tries ``int`` first, so a numeric string
    becomes the number the instance's own create example shows."""
    assert PostAsset(catalog_id="3153").to_api()["catalog_id"] == 3153


def test_post_asset_passes_a_non_numeric_status_through():
    """The point of the ``str`` branch: a value this package cannot
    vendor-document is sent as written rather than refused."""
    assert PostAsset(catalog_id=1, status_id="IN_STOCK").to_api()["status_id"] == (
        "IN_STOCK"
    )


def test_post_asset_custom_fields_get_e_prefix():
    payload = PostAsset(catalog_id=1, custom_fields={"last_date_update": "12/09/2025"})
    body = payload.to_api()
    assert body["catalog_id"] == 1
    assert body["e_last_date_update"] == "12/09/2025"

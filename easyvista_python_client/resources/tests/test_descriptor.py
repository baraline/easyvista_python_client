import pydantic
import pytest

from easyvista_python_client.models.asset import Asset, PostAsset
from easyvista_python_client.models.request import Request
from easyvista_python_client.pagination import SearchResult, extract_records
from easyvista_python_client.resources.descriptor import (
    ResourceDescriptor,
    build_create,
    build_get,
    build_search,
    build_update,
)

ASSETS = ResourceDescriptor(path="assets", envelope_key="assets", model=Asset)
# A second descriptor, because ``Asset`` declares no timestamp column and the
# context tests need one that does.
REQUESTS = ResourceDescriptor(path="requests", envelope_key="requests", model=Request)


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


# --- a projection on the item route, and the validation context -------------


def test_build_get_sends_no_params_without_a_fields_projection():
    """With no projection the spec must be the one this builder always built.

    ``params or None`` rather than a bare ``{}``: an empty dict would probably
    behave the same through httpx, but the suite asserts on ``spec.params``
    elsewhere and "probably" is not the standard here.
    """
    spec, _ = build_get(ASSETS, "9504")
    assert spec.params is None


def test_build_get_sends_a_joined_fields_projection():
    spec, _ = build_get(ASSETS, "9504", fields=["ASSET_ID", "ASSET_TAG"])
    assert spec.params == {"fields": "ASSET_ID,ASSET_TAG"}
    # A string is passed through as written, not re-joined character by
    # character.
    spec, _ = build_get(ASSETS, "9504", fields="ASSET_ID")
    assert spec.params == {"fields": "ASSET_ID"}


_ODD_FORMAT = {"datetime_input_formats": ["%d/%m/%Y %H:%M:%S"]}


def test_a_validation_context_reaches_the_search_parser():
    """The context is bound at build time, so the parser signature never
    changes -- but it must actually arrive at ``model_validate``."""
    _, parse = build_search(REQUESTS, context=_ODD_FORMAT)
    result = parse(
        {"records": [{"RFC_NUMBER": "I1", "LAST_UPDATE": "17/08/2026 15:40:00"}]}
    )
    assert result.records[0].last_update is not None
    # And without it the same payload is refused, which is what makes the
    # assertion above mean something.
    _, plain = build_search(REQUESTS)
    with pytest.raises(pydantic.ValidationError):
        plain({"records": [{"RFC_NUMBER": "I1", "LAST_UPDATE": "17/08/2026 15:40:00"}]})


def test_a_validation_context_reaches_the_single_record_parser():
    """``_first_record_parser`` serves get, create and update alike."""
    _, parse = build_get(REQUESTS, "I1", context=_ODD_FORMAT)
    parsed = parse(
        {"records": [{"RFC_NUMBER": "I1", "LAST_UPDATE": "17/08/2026 15:40:00"}]}
    )
    assert parsed.last_update is not None

import pytest

from easyvista_python_client.resources.discovery import (
    SWAGGER_PATH,
    build_get_api_spec,
    build_list_reference_table,
)


def test_build_get_api_spec_uses_the_measured_route_and_sends_no_params():
    spec, _ = build_get_api_spec()
    assert (spec.method, spec.path) == ("GET", SWAGGER_PATH)
    assert spec.params is None


def test_build_get_api_spec_honours_a_custom_path():
    """The route is tier 4 -- measured on one instance and NOT declared in that
    instance's own paths -- so a deployment publishing elsewhere needs a way
    through that is not a fork."""
    spec, _ = build_get_api_spec("openapi.json")
    assert spec.path == "openapi.json"


def test_build_get_api_spec_parses_a_non_dict_body_to_an_empty_dict():
    _, parse = build_get_api_spec()
    assert parse(["not", "a", "document"]) == {}
    assert parse({"info": {}})["info"] == {}


def test_build_list_reference_table_sends_no_params_by_default():
    """The default call is the bare route.

    Every query parameter is sent only when passed -- ``offset`` included,
    which is vendor-documented for the requests list and merely inferred on
    these routes.
    """
    spec, _ = build_list_reference_table("catalog-requests")
    assert (spec.method, spec.path) == ("GET", "catalog-requests")
    assert spec.params == {}


@pytest.mark.parametrize(
    ("kwargs", "expected"),
    [
        ({"search": 'CODE:"INC"'}, {"search": 'CODE:"INC"'}),
        ({"max_rows": 5}, {"max_rows": 5}),
        ({"offset": 10}, {"offset": 10}),
        ({"sort": "CODE"}, {"sort": "CODE"}),
        ({"fields": ["CODE", "TITLE_EN"]}, {"fields": "CODE,TITLE_EN"}),
    ],
)
def test_each_keyword_adds_exactly_its_own_param(kwargs, expected):
    spec, _ = build_list_reference_table("status", **kwargs)
    assert spec.params == expected


def test_params_is_merged_last_and_overrides_a_modelled_one():
    """The escape hatch for a query argument this signature does not model."""
    spec, _ = build_list_reference_table(
        "status", max_rows=5, params={"max_rows": 99, "formatDate": "iso"}
    )
    assert spec.params == {"max_rows": 99, "formatDate": "iso"}


def test_a_slashed_path_is_stripped():
    spec, _ = build_list_reference_table("/catalog-requests/")
    assert spec.path == "catalog-requests"


def test_the_parser_handles_all_three_envelope_shapes():
    """``records``, the resource-named envelope, and a BARE object.

    The bare case is not hypothetical: the instance's own ``GET /status``
    schema shows an object with no ``records`` envelope at all.
    """
    _, parse = build_list_reference_table("status")

    def first_status_id(payload):
        return parse(payload).records[0].model_dump(by_alias=True)["STATUS_ID"]

    assert first_status_id({"records": [{"STATUS_ID": 8}]}) == 8
    assert first_status_id({"status": [{"STATUS_ID": 8}]}) == 8
    assert first_status_id({"STATUS_ID": 8, "NAME_FR": "Cloture"}) == 8

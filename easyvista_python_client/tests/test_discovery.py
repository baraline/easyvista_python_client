"""Offline tests for the discovery extractors. Nothing here touches a network."""

import pytest

from easyvista_python_client.discovery import (
    REFERENCE_SOURCES,
    ReferenceSource,
    guids_from_sample,
    merge_guids,
    reference_from_table_row,
    references_from_sample,
    resolve_source,
    sample_fields,
)

# --- the name -> route map ---------------------------------------------------


@pytest.mark.parametrize(
    ("name", "path"),
    [
        ("STATUS", "status"),
        # SINGULAR, and asserted as such on purpose: the vendor documents
        # `GET /urgencies` (tier 1) while this deployment declares
        # `GET /urgency` (tier 2). A well-meaning "fix" to the plural must fail
        # here rather than silently 403 on the instance the package was
        # characterized against. O-URGPATH stays open; `reference_path=` is the
        # escape hatch, not a resolution.
        ("URGENCY", "urgency"),
        ("CATALOG_REQUEST", "catalog-requests"),
        ("LOCATION", "locations"),
        ("DEPARTMENT", "departments"),
        ("GROUP", "groups"),
        ("SLA", "slas"),
    ],
)
def test_resolve_source_maps_a_declared_route(name, path):
    assert resolve_source(name).reference_path == path
    # Case-insensitively, so a caller may pass the lowercase column name.
    assert resolve_source(name.lower()).reference_path == path


@pytest.mark.parametrize("name", ["IMPACT", "SEVERITY", "ORIGIN", "ACTION_TYPE"])
def test_four_names_have_no_reference_route_at_all(name):
    """A topology fact from the spec's ``paths``, not a 403 someone measured.

    No strategy can reach a table for these, so what discovery returns is "the
    ids in use in the sample" -- an id configured but unused is invisible.
    """
    assert resolve_source(name).reference_path is None


def test_an_unknown_name_becomes_a_sampling_only_ticket_source():
    """Exactly right for a custom ``e_*`` column, which has no table."""
    source = resolve_source("e_site")
    assert source.name == "E_SITE"
    assert source.reference_path is None
    assert source.sample_from == "tickets"
    assert source.sample_field == "E_SITE"


def test_reference_path_overrides_a_mapped_route_and_supplies_a_missing_one():
    assert resolve_source("URGENCY", reference_path="urgencies").reference_path == (
        "urgencies"
    )
    # And for a name the map gives no route at all.
    impact = resolve_source("IMPACT", reference_path="impacts")
    assert impact.reference_path == "impacts"
    assert impact.sample_field == "IMPACT"  # the rest of the source is preserved


def test_origin_samples_the_column_that_is_actually_returned():
    """``PostRequest.origin`` reads back as ``REQUEST_ORIGIN_ID``.

    ``ORIGIN`` itself is never returned, so projecting it would sample a column
    that is always absent.
    """
    assert resolve_source("ORIGIN").sample_field == "REQUEST_ORIGIN"


def test_group_samples_from_actions_because_no_ticket_carries_one():
    assert REFERENCE_SOURCES["GROUP"].sample_from == "actions"
    assert REFERENCE_SOURCES["STATUS"].sample_from == "tickets"


# --- one reference-table row -------------------------------------------------


def test_table_row_id_prefers_the_mapped_id_field():
    """``catalog-requests`` names its id ``SD_CATALOG_ID``, not ``*_ID``."""
    row = {"CODE": "INC", "SD_CATALOG_ID": 5791, "TITLE_EN": "Incident"}
    got = reference_from_table_row(row, resolve_source("CATALOG_REQUEST"))
    assert got.id == "5791"
    assert got.code == "INC"
    assert got.label == "Incident"


def test_table_row_id_falls_back_to_the_name_prefixed_column():
    row = {"LOCATION_ID": 12, "LOCATION_FR": "Paris", "LOCATION_CODE": "PAR"}
    got = reference_from_table_row(row, resolve_source("LOCATION"))
    assert (got.id, got.label, got.code) == ("12", "Paris", "PAR")


def test_table_row_id_falls_back_to_the_href_tail():
    row = {"HREF": "https://h/api/v1/acme/locations/12/"}
    assert reference_from_table_row(row, resolve_source("LOCATION")).id == "12"


def test_a_nested_id_never_becomes_the_row_id():
    """Only TOP-LEVEL keys are scanned.

    A ``/catalog-requests`` row carries a nested ``MANAGER`` and a nested
    ``SLA``, each with its own ``*_ID``. Scanning recursively would let an
    employee id become the catalog id, silently.
    """
    row = {
        "CODE": "INC",
        "MANAGER": {"EMPLOYEE_ID": 42},
        "SLA": {"SLA_ID": 7},
        "SD_CATALOG_ID": 5791,
    }
    assert reference_from_table_row(row, resolve_source("CATALOG_REQUEST")).id == "5791"
    # And with the mapped id absent, the nested ones still cannot win.
    del row["SD_CATALOG_ID"]
    assert reference_from_table_row(row, resolve_source("CATALOG_REQUEST")).id is None


def test_code_precedence_prefers_the_name_prefixed_column():
    row = {"LOCATION_ID": 1, "ZIP_CODE": "75001", "LOCATION_CODE": "PAR"}
    assert reference_from_table_row(row, resolve_source("LOCATION")).code == "PAR"


def test_path_resolves_from_the_name_prefixed_column():
    row = {"DEPARTMENT_ID": 60, "DEPARTMENT_PATH": "ACME/IT"}
    assert reference_from_table_row(row, resolve_source("DEPARTMENT")).path == "ACME/IT"


def test_the_raw_row_is_kept_verbatim():
    """So an instance-specific column is still one dict lookup away."""
    row = {"GROUP_ID": 3, "GROUP_EN": "N1", "E_SITE": "Paris"}
    got = reference_from_table_row(row, resolve_source("GROUP"))
    assert got.record["E_SITE"] == "Paris"


def test_label_from_a_table_row_matches_by_suffix_not_by_prefix():
    """Four tables, four different label prefixes, one suffix rule."""
    cases = [
        ({"GROUP_ID": 3, "GROUP_EN": "N1"}, "GROUP", "N1"),
        ({"LOCATION_ID": 1, "LOCATION_FR": "Paris"}, "LOCATION", "Paris"),
        ({"SD_CATALOG_ID": 1, "TITLE_EN": "Incident"}, "CATALOG_REQUEST", "Incident"),
        ({"SLA_ID": 1, "NAME_FR": "Standard"}, "SLA", "Standard"),
    ]
    for row, name, expected in cases:
        assert reference_from_table_row(row, resolve_source(name)).label == expected


# --- sampled records ---------------------------------------------------------


def test_references_from_sample_groups_counts_and_orders():
    records = [
        {"STATUS": {"STATUS_ID": "2", "STATUS_EN": "Open"}},
        {"STATUS": {"STATUS_ID": "8", "STATUS_EN": "Closed"}},
        {"STATUS": {"STATUS_ID": "2", "STATUS_EN": "Open"}},
    ]
    got = references_from_sample(records, resolve_source("STATUS"))
    assert [(r.id, r.label, r.count) for r in got] == [
        ("2", "Open", 2),
        ("8", "Closed", 1),
    ]
    assert all(r.source == "sample" for r in got)


def test_references_from_sample_reads_a_bare_top_level_id():
    """Not every reference comes back as a nested object."""
    records = [{"URGENCY_ID": "1"}, {"URGENCY_ID": "2"}, {"URGENCY_ID": "1"}]
    got = references_from_sample(records, resolve_source("URGENCY"))
    assert [(r.id, r.count) for r in got] == [("1", 2), ("2", 1)]


def test_a_sampled_group_has_no_label_rather_than_a_fabricated_one():
    """An action carries ``GROUP_ID`` but no group label.

    Inventing one from the id would be worse than saying so: a caller would
    render "3" as if it were a group name.
    """
    got = references_from_sample(
        [{"ACTION_ID": 1, "GROUP_ID": 3}], resolve_source("GROUP")
    )
    assert [(r.id, r.label) for r in got] == [("3", None)]


def test_a_sampled_action_type_reads_its_label_from_the_sibling_columns():
    """An action's type label is NOT in a nested object.

    It lives in sibling ``ACTION_LABEL_<lang>`` columns, which is the one shape
    ``resolve_reference`` cannot read on its own. ``sample_fields`` projects
    those columns for exactly this reason -- without the fallback the
    projection would be requested and then ignored, and every discovered action
    type would come back with ``label=None``.
    """
    records = [
        {
            "ACTION_ID": 1,
            "ACTION_TYPE_ID": 94,
            "ACTION_LABEL_EN": "Customer Comment",
        }
    ]
    got = references_from_sample(records, resolve_source("ACTION_TYPE"))
    assert [(r.id, r.label) for r in got] == [("94", "Customer Comment")]


def test_a_bracketed_action_label_is_not_mistaken_for_a_translation():
    """On a single-language instance the other columns echo the primary text
    in brackets. ``localized_label`` already skips those, and the fallback must
    inherit that rather than reintroducing the placeholder."""
    records = [
        {
            "ACTION_ID": 1,
            "ACTION_TYPE_ID": 95,
            "ACTION_LABEL_EN": "[Note Interne]",
            "ACTION_LABEL_FR": "Note Interne",
        }
    ]
    got = references_from_sample(records, resolve_source("ACTION_TYPE"))
    assert got[0].label == "Note Interne"


def test_a_sampled_group_still_has_no_label_after_the_action_fallback():
    """The fallback is scoped to ACTION_TYPE, not to every action source.

    An action carries ``GROUP_ID`` and an ``ACTION_LABEL_*`` describing the
    ACTION, not the group -- borrowing it would label group 3 "Customer
    Comment".
    """
    records = [
        {"ACTION_ID": 1, "GROUP_ID": 3, "ACTION_LABEL_EN": "Customer Comment"}
    ]
    got = references_from_sample(records, resolve_source("GROUP"))
    assert [(r.id, r.label) for r in got] == [("3", None)]


def test_a_sampled_entry_carries_no_code_or_path():
    """Those are reference-table columns; a sampled record has neither."""
    got = references_from_sample(
        [{"STATUS": {"STATUS_ID": "2", "STATUS_EN": "Open"}}],
        resolve_source("STATUS"),
    )
    assert got[0].code is None
    assert got[0].path is None


# --- the STATUS_GUID recipe --------------------------------------------------


def test_guids_from_sample_reads_the_nested_status_guid():
    records = [
        {"STATUS": {"STATUS_ID": "8", "STATUS_GUID": "{ABC}", "STATUS_FR": "Cloture"}},
        {"STATUS": {"STATUS_ID": "12", "STATUS_GUID": "{DEF}"}},
    ]
    assert guids_from_sample(records, resolve_source("STATUS")) == {
        "8": "{ABC}",
        "12": "{DEF}",
    }


def test_guids_from_sample_is_empty_for_a_source_with_no_guid_field():
    """Today only STATUS has one, so nothing else pays for the lookup."""
    records = [{"URGENCY": {"URGENCY_ID": "1", "URGENCY_GUID": "{X}"}}]
    assert guids_from_sample(records, resolve_source("URGENCY")) == {}


def test_merge_guids_fills_only_matching_ids():
    """A status no sampled ticket holds keeps ``guid=None``.

    The sample cannot reach it, and inventing one would hand a caller a GUID
    that addresses nothing.
    """
    discovered = references_from_sample(
        [{"STATUS": {"STATUS_ID": "2"}}, {"STATUS": {"STATUS_ID": "8"}}],
        resolve_source("STATUS"),
    )
    merged = merge_guids(discovered, {"2": "{ABC}"})
    assert {r.id: r.guid for r in merged} == {"2": "{ABC}", "8": None}
    assert len(merged) == len(discovered)  # nothing dropped


# --- the sample projection ---------------------------------------------------


def test_sample_fields_for_a_ticket_source_asks_for_the_nested_object_and_ids():
    fields = sample_fields(resolve_source("STATUS"))
    for expected in ("RFC_NUMBER", "STATUS", "STATUS_ID", "STATUS_GUID"):
        assert expected in fields


def test_sample_fields_adds_action_labels_only_for_action_type():
    """An action's default row is deliberately slim, so the translated
    ``ACTION_LABEL_<LANG>`` columns must be asked for by name -- but only where
    they are the label, which is ACTION_TYPE and not GROUP."""
    action_type = sample_fields(resolve_source("ACTION_TYPE"))
    assert "ACTION_LABEL_EN" in action_type
    assert "ACTION_TYPE_ID" in action_type

    group = sample_fields(resolve_source("GROUP"))
    assert "GROUP_ID" in group
    assert not any(f.startswith("ACTION_LABEL") for f in group)


def test_sample_fields_honours_a_language_reordering():
    fields = sample_fields(resolve_source("ACTION_TYPE"), languages=("_FR",))
    assert "ACTION_LABEL_FR" in fields
    assert "ACTION_LABEL_EN" not in fields


def test_a_custom_source_map_replaces_the_whole_routing_table():
    """For a deployment that routes a table somewhere else entirely."""
    custom = {"STATUS": ReferenceSource("STATUS", "etats", "tickets", "STATUS")}
    assert resolve_source("STATUS", sources=custom).reference_path == "etats"

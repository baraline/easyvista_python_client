from datetime import datetime, timezone

import pytest

from easyvista_python_client.models.request import Request
from easyvista_python_client.reporting import (
    DEFAULT_DIMENSIONS,
    TicketStatistics,
    _parse_iso_datetime,
    aggregate_tickets,
)


def test_parse_offset_with_3_digit_milliseconds():
    # EasyVista's CREATION_DATE_UT format; 3.10's fromisoformat rejects 3-digit ms.
    dt = _parse_iso_datetime("2025-11-28T11:35:22.900+01:00")
    assert dt is not None
    assert dt.year == 2025 and dt.month == 11 and dt.day == 28
    assert dt.utcoffset() is not None  # timezone-aware


def test_parse_trailing_z_is_utc():
    dt = _parse_iso_datetime("2025-01-02T03:04:05Z")
    assert dt == datetime(2025, 1, 2, 3, 4, 5, tzinfo=timezone.utc)


def test_parse_no_fraction():
    dt = _parse_iso_datetime("2025-06-15T08:00:00+02:00")
    assert dt is not None and dt.utcoffset() is not None


def test_parse_naive_string_becomes_utc():
    dt = _parse_iso_datetime("2025-06-15T08:00:00")
    assert dt == datetime(2025, 6, 15, 8, 0, 0, tzinfo=timezone.utc)


def test_parse_datetime_passthrough_makes_naive_utc():
    naive = datetime(2025, 6, 15, 8, 0, 0)
    assert _parse_iso_datetime(naive) == naive.replace(tzinfo=timezone.utc)
    aware = datetime(2025, 6, 15, 8, 0, 0, tzinfo=timezone.utc)
    assert _parse_iso_datetime(aware) == aware


def test_parse_invalid_returns_none():
    assert _parse_iso_datetime("not-a-date") is None
    assert _parse_iso_datetime("") is None
    assert _parse_iso_datetime(None) is None
    assert _parse_iso_datetime(12345) is None


def _ticket(**fields) -> Request:
    return Request.model_validate(fields)


def test_total_counts_all_tickets_without_window():
    tickets = [_ticket(RFC_NUMBER="I1"), _ticket(RFC_NUMBER="I2")]
    stats = aggregate_tickets(tickets, dimensions=())
    assert isinstance(stats, TicketStatistics)
    assert stats.total == 2
    assert stats.breakdowns == {}


def test_status_breakdown_prefers_label():
    tickets = [
        _ticket(RFC_NUMBER="I1", STATUS_ID=2, STATUS={"STATUS_EN": "Open"}),
        _ticket(RFC_NUMBER="I2", STATUS_ID=3, STATUS={"STATUS_EN": "Closed"}),
        _ticket(RFC_NUMBER="I3", STATUS_ID=2, STATUS={"STATUS_EN": "Open"}),
    ]
    stats = aggregate_tickets(tickets, dimensions=("STATUS",))
    assert stats.breakdowns["STATUS"] == {"Open": 2, "Closed": 1}
    assert sum(stats.breakdowns["STATUS"].values()) == stats.total


def test_dimension_id_fallback_when_no_label():
    tickets = [_ticket(RFC_NUMBER="I1", STATUS_ID=7)]
    stats = aggregate_tickets(tickets, dimensions=("STATUS",))
    assert stats.breakdowns["STATUS"] == {"7": 1}


def test_dimension_unknown_bucket_when_no_label_or_id():
    tickets = [_ticket(RFC_NUMBER="I1")]
    stats = aggregate_tickets(tickets, dimensions=("DEPARTMENT",))
    assert stats.breakdowns["DEPARTMENT"] == {"(unknown)": 1}


def test_default_dimensions_computed_when_omitted():
    tickets = [_ticket(RFC_NUMBER="I1", STATUS={"STATUS_EN": "Open"})]
    stats = aggregate_tickets(tickets)
    assert set(stats.breakdowns) == set(DEFAULT_DIMENSIONS)
    for dim in DEFAULT_DIMENSIONS:
        assert sum(stats.breakdowns[dim].values()) == stats.total


def test_urgency_dimension_buckets_by_id():
    # Id-only ref: no nested URGENCY object, only URGENCY_ID.
    tickets = [
        _ticket(RFC_NUMBER="I1", URGENCY_ID="1"),
        _ticket(RFC_NUMBER="I2", URGENCY_ID="2"),
        _ticket(RFC_NUMBER="I3", URGENCY_ID="1"),
    ]
    stats = aggregate_tickets(tickets, dimensions=("URGENCY",))
    assert stats.breakdowns["URGENCY"] == {"1": 2, "2": 1}


def test_custom_field_dimension():
    tickets = [
        _ticket(RFC_NUMBER="I1", e_site="Paris"),
        _ticket(RFC_NUMBER="I2", e_site="Lyon"),
    ]
    stats = aggregate_tickets(tickets, dimensions=("e_site",))
    assert stats.breakdowns["e_site"] == {"Paris": 1, "Lyon": 1}


def test_fields_for_references_union_and_creation_date():
    from easyvista_python_client.reporting import fields_for_references

    fields = fields_for_references(("STATUS", "URGENCY"), include_creation_date=False)
    assert fields[0] == "RFC_NUMBER"
    for expected in (
        "STATUS",
        "STATUS_ID",
        "STATUS_GUID",
        "URGENCY",
        "URGENCY_ID",
        "URGENCY_GUID",
    ):
        assert expected in fields
    assert "CREATION_DATE_UT" not in fields
    assert len(fields) == len(set(fields))  # de-duplicated

    windowed = fields_for_references(("STATUS",), include_creation_date=True)
    assert "CREATION_DATE_UT" in windowed


def test_created_since_until_inclusive_bounds():
    tickets = [
        _ticket(RFC_NUMBER="I1", CREATION_DATE_UT="2025-01-01T00:00:00+00:00"),
        _ticket(RFC_NUMBER="I2", CREATION_DATE_UT="2025-06-15T12:00:00+00:00"),
        _ticket(RFC_NUMBER="I3", CREATION_DATE_UT="2025-12-31T23:59:59+00:00"),
    ]
    stats = aggregate_tickets(
        tickets,
        dimensions=(),
        created_since="2025-06-15T12:00:00+00:00",  # exactly on lower bound -> included
        created_until="2025-12-31T23:59:59+00:00",  # exactly on upper bound -> included
    )
    assert stats.total == 2


def test_window_excludes_missing_or_unparseable_dates():
    tickets = [
        _ticket(RFC_NUMBER="I1", CREATION_DATE_UT="2025-06-15T12:00:00+00:00"),
        _ticket(RFC_NUMBER="I2"),  # no date
        _ticket(RFC_NUMBER="I3", CREATION_DATE_UT="garbage"),
    ]
    stats = aggregate_tickets(
        tickets, dimensions=(), created_since="2025-01-01T00:00:00+00:00"
    )
    assert stats.total == 1


def test_malformed_bound_raises_valueerror():
    with pytest.raises(ValueError, match="created_since"):
        aggregate_tickets(
            [_ticket(RFC_NUMBER="I1")], dimensions=(), created_since="nope"
        )


def test_created_until_excludes_newer_records():
    tickets = [
        _ticket(RFC_NUMBER="I1", CREATION_DATE_UT="2025-06-15T12:00:00+00:00"),
        _ticket(RFC_NUMBER="I2", CREATION_DATE_UT="2025-12-31T23:59:59+00:00"),
    ]
    stats = aggregate_tickets(
        tickets, dimensions=(), created_until="2025-06-15T12:00:00+00:00"
    )
    assert stats.total == 1  # I2 is newer than created_until -> excluded

"""Pure, offline ticket statistics — counts and per-dimension breakdowns.

Network-free by design: it consumes already-fetched :class:`Request` objects so it
can be unit-tested without a client. The sync/async clients fetch records and
delegate to :func:`aggregate_tickets`.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from .models.request import Request
from .references import resolve_reference
from .timestamps import parse_ev_datetime

# Kept as a module-level alias so the eight existing tests in
# tests/test_reporting.py keep importing the name they were written against.
_parse_iso_datetime = parse_ev_datetime

DEFAULT_DIMENSIONS: tuple[str, ...] = (
    "STATUS",
    "DEPARTMENT",
    "CATALOG_REQUEST",
    "URGENCY",
    "IMPACT",
)

_UNKNOWN = "(unknown)"


@dataclass
class TicketStatistics:
    """A ticket count plus per-dimension breakdowns.

    ``total`` is the number of tickets aggregated (after any date window).
    ``breakdowns`` maps each requested dimension name to ``{label: count}``; for
    every dimension ``sum(breakdowns[dim].values()) == total``.
    """

    total: int
    breakdowns: dict[str, dict[str, int]]


def _dimension_value(data: dict[str, Any], name: str) -> str:
    """Group key for one ticket on one dimension: label, else id, else unknown."""
    return resolve_reference(data, name).display or _UNKNOWN


def fields_for_references(
    names: Sequence[str], *, include_creation_date: bool
) -> list[str]:
    """Search-projection field list covering every reference in ``names``.

    Requests each reference's nested object and its id fields so both label and id
    are available when aggregating over search results; over-requesting a
    non-existent field is ignored by the API.
    """
    fields: list[str] = ["RFC_NUMBER"]
    for name in names:
        for field in (name, f"{name}_ID", f"{name}_GUID"):
            if field not in fields:
                fields.append(field)
    if include_creation_date and "CREATION_DATE_UT" not in fields:
        fields.append("CREATION_DATE_UT")
    return fields


def _bound(value: datetime | str | None, name: str) -> datetime | None:
    """Parse a window bound; raise ValueError on a malformed string."""
    if value is None:
        return None
    parsed = _parse_iso_datetime(value)
    if parsed is None:
        raise ValueError(f"{name} is not a valid datetime: {value!r}")
    return parsed


def aggregate_tickets(
    tickets: Iterable[Request],
    *,
    dimensions: Sequence[str] = DEFAULT_DIMENSIONS,
    created_since: datetime | str | None = None,
    created_until: datetime | str | None = None,
) -> TicketStatistics:
    """Aggregate tickets into a total plus per-dimension breakdowns.

    ``dimensions`` selects which breakdowns to compute (default: all of
    ``DEFAULT_DIMENSIONS``); any field name is valid, including custom ``e_*``.
    ``created_since`` / ``created_until`` are inclusive bounds on the ticket's
    ``CREATION_DATE_UT`` (a ``datetime`` or ISO string); a ticket with a
    missing/unparseable date is excluded when a bound is set. Raises ``ValueError``
    for a malformed bound string.

    **An offset-less bound is interpreted as UTC**, not as instance-local time,
    because it routes through
    :func:`~easyvista_python_client.parse_ev_datetime`. On a ``+02:00`` instance
    ``created_since="2026-01-01T00:00:00"`` therefore silently excludes every
    ticket created between 00:00 and 02:00 local on 1 January -- a two-hour hole
    in a bound this docstring calls inclusive. Pass an aware ``datetime``, or an
    offset-bearing string, when the boundary matters. Note this filter is
    client-side and deliberately more permissive than the *wire* builders, which
    refuse an offset-less time outright
    (:func:`~easyvista_python_client.ev_since_filter`); making the two agree is a
    behaviour change and a candidate follow-up.

    The "unparseable" half of that per-ticket guard is unreachable for a
    ``Request`` built the normal way: ``Request.model_validate`` itself now
    rejects a malformed ``CREATION_DATE_UT`` before this function ever sees the
    ticket (see ``OptionalDateTime`` in ``models/common.py``). It stays as
    defence-in-depth for a ``Request`` assembled some other way (e.g.
    ``model_construct``, which bypasses validation) -- do not delete it as dead
    code.
    """
    since = _bound(created_since, "created_since")
    until = _bound(created_until, "created_until")
    filtering = since is not None or until is not None

    total = 0
    breakdowns: dict[str, dict[str, int]] = {dim: {} for dim in dimensions}
    for ticket in tickets:
        data = ticket.model_dump(by_alias=True)
        if filtering:
            created = _parse_iso_datetime(data.get("CREATION_DATE_UT"))
            if created is None:
                continue
            if since is not None and created < since:
                continue
            if until is not None and created > until:
                continue
        total += 1
        for dim in dimensions:
            key = _dimension_value(data, dim)
            counts = breakdowns[dim]
            counts[key] = counts.get(key, 0) + 1
    return TicketStatistics(total=total, breakdowns=breakdowns)

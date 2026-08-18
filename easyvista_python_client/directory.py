"""Directory aggregation and fuzzy department resolution (client-agnostic helpers)."""

from __future__ import annotations

from dataclasses import dataclass

from .models.asset import Asset
from .models.department import Department
from .models.employee import Employee
from .models.request import Request
from .reporting import TicketStatistics

# O-DIR-1: the descending-sort token must be SPACE-separated. Measured live
# 2026-08-17 on a date column: `FIELD DESC` and `FIELD desc` genuinely reorder,
# while `FIELD:DESC`, `-FIELD` and `DESC(FIELD)` are silently ignored — they
# return the API's default order, byte-identical to an unsorted page, with no
# error. This constant previously used the ignored colon form, so
# `recent_tickets` was never actually sorted. The rule is syntactic rather than
# field-specific, so it is applied to RFC_NUMBER here by inference;
# integration_tests/test_live_change_window.py pins this exact token live.
#
# What is measured is the DESCENDING-ness, not recency. RFC_NUMBER is a varchar
# (`I240101_0001`), so a descending string sort orders by the request-type
# prefix FIRST and the date second: on an instance that issues more than one
# prefix letter, every `R...` ticket outranks every `I...` ticket regardless of
# date. Hence the docstrings say "descending RFC_NUMBER" rather than
# "newest-first". Switching to a date column (`CREATION_DATE_UT DESC`) would
# make recency literal and is a candidate follow-up; it is a behaviour change
# and wants its own live check first.
RECENT_TICKETS_SORT = "RFC_NUMBER DESC"


@dataclass
class DepartmentContext:
    """A department plus its related directory/ticket/asset context.

    Only ``department`` is guaranteed; every related part degrades to ``[]`` / ``None``
    / ``0`` when a profile restriction (403) or a missing record (404) blocks it.
    """

    department: Department
    employees: list[Employee]
    manager: Employee | None
    note: str | None
    ticket_count: int
    recent_tickets: list[Request]
    ticket_statistics: TicketStatistics | None
    assets: list[Asset]


def _normalize_name(value: str) -> str:
    """Case-, space- and hyphen-insensitive key for fuzzy name matching."""
    return value.replace("-", "").replace(" ", "").lower()


def _department_matches(dept: Department, needle: str) -> bool:
    """True if ``needle`` (already normalized) is a substring of any string field.

    Scans every localized label + code + path (all string fields), skipping the
    record's own ``HREF`` so a URL never yields a false positive.
    """
    for key, value in dept.model_dump(by_alias=True).items():
        if isinstance(key, str) and key.upper() == "HREF":
            continue
        if isinstance(value, str) and needle in _normalize_name(value):
            return True
    return False

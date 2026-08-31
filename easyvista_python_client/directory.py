"""Directory aggregation and fuzzy department resolution (client-agnostic helpers)."""

from __future__ import annotations

import unicodedata
from collections.abc import Sequence
from dataclasses import dataclass, field

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

# The final path segment of ``GET departments/{id}/{comment}``. In the instance
# OpenAPI document read 2026-08-27 that segment is a path *parameter* named
# ``comment``, not a literal: the sibling ``GET requests/{rfc_number}/{comment}``
# describes the same parameter as "Memo field type, could be comment,
# description". The route therefore selects a memo column, and this value is
# only the column the verified instance carries -- a deployment that names its
# department memo differently passes its own.
DEPARTMENT_MEMO_FIELD = "comment_department"

#: Memo sub-resources ``get_department_context`` resolves for a department.
#: The API models a memo name as a path segment (``GET departments/{id}/{memo}``),
#: so a deployment carrying its directory note under another column is reached
#: by naming it, not by editing this module. Derived from
#: :data:`DEPARTMENT_MEMO_FIELD` so the single-memo and multi-memo defaults
#: cannot drift apart.
DEPARTMENT_NOTE_FIELDS: tuple[str, ...] = (DEPARTMENT_MEMO_FIELD,)

#: Default ``fields=`` projection for ``get_department_context``'s recent
#: tickets. Passing *no* projection is not a neutral default here: on the
#: verified instance the default list projection returns ``TITLE`` present but
#: EMPTY (tier 4 -- measured on one instance, 400 tickets scanned via a plain
#: search, zero with a populated title; it may not generalise). See
#: ``integration_tests/conftest.py`` (``_adopt_by_title``) and
#: ``test_title_search_requires_the_fields_projection_to_return_a_value`` in
#: ``integration_tests/test_live_search_syntax.py``. So an unprojected recent
#: ticket has ``title is None`` on that instance, always.
#:
#: ``END_DATE_UT`` is included on purpose: a status id is per-instance and says
#: nothing portable about openness, while ``END_DATE_UT`` is empty on an open
#: ticket and stamped on a closed one. ``STATUS`` (the nested object) and
#: ``STATUS_ID`` are both requested so ``.reference("STATUS")`` resolves a label
#: where the instance returns one and an id where it does not.
#:
#: Pass ``ticket_fields=None`` to restore the unprojected request.
RECENT_TICKET_FIELDS: tuple[str, ...] = (
    "RFC_NUMBER",
    "TITLE",
    "STATUS",
    "STATUS_ID",
    "CREATION_DATE_UT",
    "LAST_UPDATE",
    "END_DATE_UT",
)

#: Columns ``find_departments(by="auto")`` tries, in order, for an all-digit
#: name. Code first: a department whose CODE is all digits is otherwise
#: resolved as an ID and the wrong record comes back with no error.
DEPARTMENT_NAME_COLUMNS: tuple[str, ...] = ("DEPARTMENT_CODE", "DEPARTMENT_ID")


@dataclass
class DepartmentContext:
    """A department plus its related directory/ticket/asset context.

    Only ``department`` is guaranteed; every related part degrades to ``[]`` / ``None``
    / ``0`` when a profile restriction (403) or a missing record (404) blocks it.

    ``memos`` carries every memo resolved, keyed by the field name requested
    through ``memo_fields``; ``note`` is the first of them that came back with
    text, which on a default call is ``comment_department``.

    ``degraded`` records which branches were swallowed, so a caller can tell
    "no employees" from "employees were forbidden". Each entry is
    ``"<branch>:<http-status>"`` -- split it with ``rsplit(":", 1)``, because a
    memo branch is itself named ``"memo:<field>"``. Branch names are
    ``employees``, ``manager``, ``ticket_count``, ``recent_tickets``,
    ``statistics``, ``assets`` and ``memo:<field>``. An empty set means nothing
    was swallowed; it does not mean everything was populated.
    """

    department: Department
    employees: list[Employee]
    manager: Employee | None
    note: str | None
    ticket_count: int
    recent_tickets: list[Request]
    ticket_statistics: TicketStatistics | None
    assets: list[Asset]
    memos: dict[str, str | None] = field(default_factory=dict)
    degraded: frozenset[str] = frozenset()


def _as_fields(value: str | Sequence[str] | None) -> str | list[str] | None:
    """Normalize a projection argument to what the search builders accept.

    A bare ``str`` passes through unchanged -- the wire format is a
    comma-separated list, so ``"RFC_NUMBER,TITLE"`` is a legal single argument
    and must not be exploded into one character per field.
    """
    if value is None or isinstance(value, str):
        return value
    return list(value)


def _normalize_name(value: str) -> str:
    """Accent-, case-, space- and hyphen-insensitive key for fuzzy name matching.

    NFKD-decomposes, drops every combining mark, case-folds, then removes ASCII
    hyphens and spaces -- in that order. The order is load-bearing: NFKD can
    itself produce a space (NO-BREAK SPACE and the U+2000..U+200A family all
    decompose to U+0020), so a removal done first would leave one behind.

    Strictly more permissive than the plain ``lower()`` this replaced: it is a
    pure function of its argument, so every pair of names that matched before
    still matches, and ``"Systemes"`` now also matches ``"Systemes"`` written
    with its accents -- which it did not, on an instance whose department
    labels are French.

    ``unicodedata.combining`` rather than a ``category(ch) == "Mn"`` test: that
    would also strip spacing and enclosing marks, which are part of the word in
    several scripts.
    """
    decomposed = unicodedata.normalize("NFKD", value)
    unmarked = "".join(ch for ch in decomposed if not unicodedata.combining(ch))
    return unmarked.casefold().replace("-", "").replace(" ", "")


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

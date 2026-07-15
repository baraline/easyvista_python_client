"""Search-result container and record extraction for list endpoints."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Generic, TypeVar

T = TypeVar("T")


@dataclass
class SearchResult(Generic[T]):
    """A page of search results plus EasyVista's record counts.

    ``next_url`` is the API's ``@next`` link (an ``offset``-based next-page URL)
    when more records exist than were returned, else ``None``. It is the
    authoritative "are there more pages?" signal used by the iterators.
    """

    records: list[T]
    record_count: int
    total_record_count: int
    href: str | None = None
    next_url: str | None = None


def _to_int(value: Any, default: int) -> int:
    """Coerce an EasyVista count to ``int``, falling back to ``default``."""
    if value is None:
        return default
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def build_search_result(data: Any, records: list[T]) -> SearchResult[T]:
    """Assemble a :class:`SearchResult` from a payload and its typed records.

    The live API returns ``record_count`` / ``total_record_count`` as **strings**
    (spec open item O1), so they are coerced to ``int`` here — the single place
    both the ``requests`` and ``assets`` search parsers funnel through.
    """
    if not isinstance(data, dict):
        return SearchResult(
            records=records,
            record_count=len(records),
            total_record_count=len(records),
        )
    count = _to_int(data.get("record_count"), len(records))
    total = _to_int(data.get("total_record_count"), count)
    href = data.get("HREF")
    next_url = data.get("@next")
    return SearchResult(
        records=records,
        record_count=count,
        total_record_count=total,
        href=href if isinstance(href, str) else None,
        next_url=next_url if isinstance(next_url, str) else None,
    )


def extract_records(data: Any, envelope_key: str | None = None) -> list[dict[str, Any]]:
    """Pull a list of record dicts out of an EasyVista JSON payload.

    Handles the ``records`` list (GET list), the resource-named create/list
    envelopes, and a bare single object. ``envelope_key`` names a resource's own
    envelope (e.g. ``"departments"``) so a response echoed in that wrapper is
    unwrapped too; it is checked right after ``records`` and before the legacy
    defaults. With ``envelope_key=None`` the behavior is unchanged.
    """
    if isinstance(data, dict):
        keys = ["records"]
        if envelope_key and envelope_key not in keys:
            keys.append(envelope_key)
        keys.extend(k for k in ("requests", "assets", "documents") if k not in keys)
        for key in keys:
            value = data.get(key)
            if isinstance(value, list):
                return [r for r in value if isinstance(r, dict)]
        return [data]
    if isinstance(data, list):
        return [r for r in data if isinstance(r, dict)]
    return []

"""Shared helpers for extracting human labels from EasyVista field objects.

EasyVista nests label+href objects (``STATUS``, ``DEPARTMENT``, ``CATALOG_REQUEST``,
``URGENCY``, ``IMPACT``). The Markdown renderer (:mod:`context`) needs to pick the
human label and never an href, so the logic lives here once. (:mod:`reporting`
aggregates the same nested objects but does **not** route through this module --
it goes through :func:`~easyvista_python_client.references.resolve_reference`.)

Its consumer reads a ``model_dump(by_alias=True)`` dict, so a timestamp column
(``LAST_UPDATE``, ``CREATION_DATE_UT``, …) arrives here as a ``datetime`` since
the 2026-08-17 read-path retype
(:class:`~easyvista_python_client.models.common.OptionalDateTime`), not a
``str``. :func:`_text` renders it rather than discarding it, which is why this
leaf now imports :mod:`~easyvista_python_client.timestamps`.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from .timestamps import format_ev_datetime


def _text(value: Any) -> str:
    """First stripped string form of ``value``; ``""`` if it doesn't render as text.

    A ``datetime`` renders as EasyVista's own wire format (:func:`format_ev_datetime`)
    so the extracted text is byte-identical to EasyVista's own
    millisecond-precision-with-offset rendering, and to what ``ev_since_filter``
    accepts. Not necessarily byte-identical to the *input* bytes: the fraction is
    always 3 digits, so a source string with a different precision round-trips to
    3 digits here. ``format_ev_datetime`` raises on a *naive*
    datetime, which should not occur for a value that came through
    ``OptionalDateTime`` (it always normalizes to aware) -- but this is an
    extractor, which must never raise, so a naive value still falls back to
    plain ``.isoformat()`` instead.
    """
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, datetime):
        try:
            return format_ev_datetime(value)
        except ValueError:
            return value.isoformat()
    return ""


def _label(obj: Any, keys: tuple[str, ...]) -> str:
    """First non-empty string among ``keys`` of a nested object; never an href."""
    if isinstance(obj, dict):
        for key in keys:
            value = obj.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
    return ""

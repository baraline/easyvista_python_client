"""Shared helper for extracting plain text from EasyVista field values.

Human *labels* -- the nested ``STATUS`` / ``DEPARTMENT`` / ``ACTION_TYPE``
objects and the ``*_EN`` / ``*_FR`` / … language columns -- are resolved in
:mod:`~easyvista_python_client.references` alone
(:func:`~easyvista_python_client.references.resolve_reference` and
:func:`~easyvista_python_client.localized_label`), so the package has one
placeholder rule and one language order rather than three. This module is left
with :func:`_text`, the scalar-to-string extractor.

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



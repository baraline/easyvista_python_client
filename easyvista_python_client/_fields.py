"""Shared helpers for extracting human labels from EasyVista field objects.

EasyVista nests label+href objects (``STATUS``, ``DEPARTMENT``, ``CATALOG_REQUEST``,
``URGENCY``, ``IMPACT``). Both the Markdown renderer (:mod:`context`) and the
statistics aggregator (:mod:`reporting`) need to pick the human label and never an
href, so the logic lives here once.
"""

from __future__ import annotations

from typing import Any


def _text(value: Any) -> str:
    """First stripped string form of ``value``; ``""`` if it is not a string."""
    return value.strip() if isinstance(value, str) else ""


def _label(obj: Any, keys: tuple[str, ...]) -> str:
    """First non-empty string among ``keys`` of a nested object; never an href."""
    if isinstance(obj, dict):
        for key in keys:
            value = obj.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
    return ""

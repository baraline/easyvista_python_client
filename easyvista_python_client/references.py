"""Generic, config-free resolution of EasyVista reference attributes.

EasyVista returns reference attributes in two shapes: nested objects that carry a
human label in ``*_EN`` / ``*_FR`` / ``*_PATH`` sub-keys (e.g. ``STATUS``,
``DEPARTMENT``, ``CATALOG_REQUEST``), and bare ids (e.g. ``URGENCY_ID``). This
module normalizes both to a :class:`Reference` using only the API's naming
conventions, so any field — including custom ``e_*`` fields on any instance —
resolves the same way with no registry or configuration.

Leaf module: stdlib only, no model/client imports.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class Reference:
    """A normalized EasyVista reference: an id and/or a human label."""

    id: str | None
    label: str | None

    @property
    def display(self) -> str | None:
        """The human label when available, else the id, else ``None``."""
        return self.label or self.id


def _scalar(value: Any) -> str | None:
    """A non-empty id-like scalar as a string, else ``None`` (bools rejected)."""
    if isinstance(value, bool):
        return None
    if isinstance(value, (str, int)) and str(value).strip():
        return str(value).strip()
    return None


def _nested_label(nested: dict[str, Any] | None) -> str | None:
    """First non-empty ``*_EN`` then ``*_FR`` then ``*_PATH`` string; never an href."""
    if not nested:
        return None
    # Suffix-scan (not <name>_* prefix) so labels under any sub-key resolve —
    # e.g. CATALOG_REQUEST's human label lives in TITLE_FR / TITLE_EN.
    for suffix in ("_EN", "_FR", "_PATH"):
        for key, value in nested.items():
            if (
                key.upper().endswith(suffix)
                and isinstance(value, str)
                and value.strip()
            ):
                return value.strip()
    return None


def resolve_reference(record: dict[str, Any], name: str) -> Reference:
    """Resolve reference ``name`` in a model's by-alias dump to ``(id, label)``.

    ``name`` is a raw API field name, matched case-insensitively. See the module
    docstring for the conventions. Never raises; a non-dict record or a missing
    field yields an empty :class:`Reference`.
    """
    if not isinstance(record, dict):
        return Reference(id=None, label=None)
    # Index top-level keys case-insensitively (EasyVista keys are ALL_CAPS, but
    # custom fields on some instances are not — stay generic).
    upper = {k.upper(): v for k, v in record.items() if isinstance(k, str)}
    key = name.upper()

    value = upper.get(key)
    nested = value if isinstance(value, dict) else None

    label = _nested_label(nested)
    id_ = _resolve_id(upper, key, nested)
    return Reference(id=id_, label=label)


def _resolve_id(
    upper: dict[str, Any], key: str, nested: dict[str, Any] | None
) -> str | None:
    # 1. top-level <name>_ID / <name>_GUID / the scalar at <name> itself
    for candidate in (f"{key}_ID", f"{key}_GUID", key):
        got = _scalar(upper.get(candidate))
        if got is not None:
            return got
    if nested:
        # 2. exact <name>_ID / <name>_GUID inside the nested object
        for sub in (f"{key}_ID", f"{key}_GUID"):
            for nkey, nval in nested.items():
                if isinstance(nkey, str) and nkey.upper() == sub:
                    got = _scalar(nval)
                    if got is not None:
                        return got
        # Best-effort: first *_ID/_GUID sub-key by dict order (fine for the
        # single-id nested objects EasyVista returns).
        for nkey, nval in nested.items():
            if isinstance(nkey, str) and nkey.upper().endswith(("_ID", "_GUID")):
                got = _scalar(nval)
                if got is not None:
                    return got
    return None


_LANG_SUFFIXES = ("_EN", "_FR", "_GE", "_IT", "_PO", "_SP")


def _usable_label(value: Any) -> str | None:
    """A stripped non-empty string that is not a ``[bracketed]`` placeholder.

    Returns ``None`` otherwise.
    """
    if not isinstance(value, str):
        return None
    text = value.strip()
    if not text or (text.startswith("[") and text.endswith("]")):
        return None
    return text


def localized_label(
    record: dict[str, Any], prefix: str, *, fallbacks: tuple[str | None, ...] = ()
) -> str | None:
    """Best populated ``"<prefix>_<lang>"`` label, else first usable ``fallbacks``.

    Scans the EasyVista language columns ``<prefix>_EN`` → ``_FR`` → ``_GE`` → ``_IT``
    → ``_PO`` → ``_SP`` and returns the first value that is a non-empty string and not
    a ``[bracketed]`` placeholder (unpopulated localized columns on a single-language
    instance echo ``"[CODE]"``). Only the language suffixes are considered, so
    ``_CODE`` / ``_PATH`` are never mistaken for a label. Falls back to the first
    usable value in ``fallbacks`` (e.g. a code then a path). Case-insensitive on keys;
    never raises; returns ``None`` when nothing usable is found.
    """
    if isinstance(record, dict):
        upper = {k.upper(): v for k, v in record.items() if isinstance(k, str)}
        base = prefix.upper()
        for suffix in _LANG_SUFFIXES:
            got = _usable_label(upper.get(base + suffix))
            if got is not None:
                return got
    for value in fallbacks:
        got = _usable_label(value)
        if got is not None:
            return got
    return None

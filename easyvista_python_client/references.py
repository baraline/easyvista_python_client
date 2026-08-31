"""Generic, config-free resolution of EasyVista reference attributes.

EasyVista returns reference attributes in two shapes: nested objects that carry a
human label in ``*_EN`` / ``*_FR`` / ``*_PATH`` sub-keys (e.g. ``STATUS``,
``DEPARTMENT``, ``CATALOG_REQUEST``), and bare ids (e.g. ``URGENCY_ID``). This
module normalizes both to a :class:`Reference` using only the API's naming
conventions, so any field — including custom ``e_*`` fields on any instance —
resolves the same way with no registry or configuration.

**This module owns label resolution for the whole package.** There is one
placeholder rule (:func:`_usable_label`) and one language order
(:data:`DEFAULT_LANGUAGE_ORDER`), both reachable by callers through a
``languages=`` keyword, so a deployment whose primary language is not English
reorders them rather than forking.

Leaf module: only stdlib plus the :mod:`~easyvista_python_client.timestamps`
leaf (no cycle: that module imports nothing from the package either), no
model/client imports. The timestamps import exists so ``.reference()`` on a
timestamp column (``LAST_UPDATE``, …) — now a ``datetime`` since the
2026-08-17 read-path retype — resolves to its rendered value instead of an
empty :class:`Reference`.
"""

from __future__ import annotations

from collections.abc import Iterator, Sequence
from dataclasses import dataclass
from datetime import datetime
from functools import lru_cache
from typing import Any

from .timestamps import format_ev_datetime

DEFAULT_LANGUAGE_ORDER: tuple[str, ...] = (
    "_EN",
    "_FR",
    "_GE",
    "_IT",
    "_PO",
    "_SP",
    "_L1",
    "_L2",
    "_L3",
    "_L4",
    "_L5",
    "_L6",
)
"""Default order in which EasyVista language columns are tried for a label.

Every label resolver in this package -- :func:`resolve_reference`,
:func:`localized_label`,
:meth:`~easyvista_python_client.models.common.EasyvistaModel.reference`,
:meth:`~easyvista_python_client.TicketContext.to_markdown`,
:func:`~easyvista_python_client.aggregate_tickets` and both clients'
``ticket_statistics`` -- takes a ``languages=`` argument defaulting to this
tuple, so an English-first or German-first deployment reorders it once and
passes it, rather than forking the package or setting an environment variable.

Entries are matched as *suffixes* and normalized before use, so ``"en"``,
``"EN"`` and ``"_EN"`` are the same thing.

``_EN`` .. ``_SP`` are the six columns EasyVista documents and the six this
package has always scanned. ``_L1`` .. ``_L6`` are the six additional
custom-language columns: they are declared on flat record shapes in the
instance's own OpenAPI (tier 3 -- example-derived and illustrative only), and
whether a *nested* reference object such as ``STATUS`` ever carries
``STATUS_L1`` has **not** been tested on any instance. They are listed last and
are harmless where they do not exist: a suffix that matches no key contributes
nothing, and on the verified instance the ``_Lx`` columns hold either an empty
string or a fully ``[bracketed]`` untranslated echo, both of which
:func:`_usable_label` already rejects. So they can only ever supply a label
where every documented column supplied none.
"""


@lru_cache(maxsize=32)
def _normalized(languages: tuple[str, ...]) -> tuple[str, ...]:
    """Language entries as upper-case ``_XX`` suffixes, blanks dropped.

    Cached because :func:`~easyvista_python_client.aggregate_tickets` calls this
    once per ticket per dimension. ``maxsize=32`` rather than ``None`` so a
    caller building a fresh tuple inside a loop cannot grow it without bound.
    """
    return tuple(
        "_" + item.strip().lstrip("_").upper()
        for item in languages
        if isinstance(item, str) and item.strip().strip("_")
    )


def _any_text(value: Any) -> str | None:
    """A stripped non-empty string, ``[bracketed]`` placeholders included."""
    if isinstance(value, str) and value.strip():
        return value.strip()
    return None


def _usable_label(value: Any) -> str | None:
    """A stripped non-empty string that is not a ``[bracketed]`` placeholder.

    Rejects a label wrapped *entirely* in brackets -- how a single-language
    instance marks an untranslated column. A bracketed *suffix* on otherwise
    distinct text (``"Commentaire [Public]"``) is content and is kept; so is
    ``"[EXAMPLE] - ticket"``, which only starts with a bracket. Returns ``None``
    otherwise.
    """
    text = _any_text(value)
    if text is None or (text.startswith("[") and text.endswith("]")):
        return None
    return text


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
    """A non-empty id-like scalar as a string, else ``None`` (bools rejected).

    A ``datetime`` renders as EasyVista's own wire format
    (:func:`~easyvista_python_client.timestamps.format_ev_datetime`), so
    ``.reference("LAST_UPDATE")`` on a retyped timestamp field still resolves
    to a populated :class:`Reference` instead of an empty one. That function
    raises on a *naive* datetime -- which should not occur for a value that
    came through ``OptionalDateTime`` -- but this must never raise, so a naive
    value falls back to plain ``.isoformat()`` instead.
    """
    if isinstance(value, bool):
        return None
    if isinstance(value, datetime):
        try:
            return format_ev_datetime(value)
        except ValueError:
            return value.isoformat()
    if isinstance(value, (str, int)) and str(value).strip():
        return str(value).strip()
    return None


def _suffix_values(nested: dict[str, Any], suffix: str) -> Iterator[Any]:
    """Values of every sub-key whose name ends with ``suffix`` (case-blind)."""
    for key, value in nested.items():
        if isinstance(key, str) and key.upper().endswith(suffix):
            yield value


def _nested_label(
    nested: dict[str, Any] | None,
    languages: Sequence[str] = DEFAULT_LANGUAGE_ORDER,
) -> str | None:
    """Best label under a language suffix, then ``_PATH``; never an href.

    Sub-keys are matched by *suffix*, not by a ``<name>_`` prefix, so a label
    under any sub-key resolves -- ``CATALOG_REQUEST``'s human label lives in
    ``TITLE_FR`` / ``TITLE_EN``, not in ``CATALOG_REQUEST_FR``.

    Two passes run over the same order (``languages``, then ``"_PATH"``). The
    first accepts only a *usable* value (:func:`_usable_label`), so a column
    holding a fully ``[bracketed]`` untranslated echo is skipped and a real
    sibling translation wins. The second repeats the scan accepting any
    non-empty string: a record in which *every* language column is a
    placeholder still yields the label it always yielded, because the callers
    of this function do not render a fallback -- a missing label removes a
    Markdown table row, or collapses a statistics bucket onto a bare id.
    """
    if not nested:
        return None
    order = (*_normalized(tuple(languages)), "_PATH")
    for accept in (_usable_label, _any_text):
        for suffix in order:
            for value in _suffix_values(nested, suffix):
                got = accept(value)
                if got is not None:
                    return got
    return None


def resolve_reference(
    record: dict[str, Any],
    name: str,
    *,
    languages: Sequence[str] = DEFAULT_LANGUAGE_ORDER,
) -> Reference:
    """Resolve reference ``name`` in a model's by-alias dump to ``(id, label)``.

    ``name`` is a raw API field name, matched case-insensitively. See the module
    docstring for the conventions. ``languages`` is the order in which the
    nested object's language columns are tried before its ``_PATH`` (default:
    :data:`DEFAULT_LANGUAGE_ORDER`); reorder it for a deployment whose primary
    language is not English. Never raises; a non-dict record or a missing field
    yields an empty :class:`Reference`.
    """
    if not isinstance(record, dict):
        return Reference(id=None, label=None)
    # Index top-level keys case-insensitively (EasyVista keys are ALL_CAPS, but
    # custom fields on some instances are not — stay generic).
    upper = {k.upper(): v for k, v in record.items() if isinstance(k, str)}
    key = name.upper()

    value = upper.get(key)
    nested = value if isinstance(value, dict) else None

    label = _nested_label(nested, languages)
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


def localized_label(
    record: dict[str, Any],
    prefix: str,
    *,
    fallbacks: tuple[str | None, ...] = (),
    languages: Sequence[str] = DEFAULT_LANGUAGE_ORDER,
) -> str | None:
    """Best populated ``"<prefix>_<lang>"`` label, else first usable ``fallbacks``.

    Scans ``"<prefix>" + suffix`` for each suffix in ``languages`` (default:
    :data:`DEFAULT_LANGUAGE_ORDER`, i.e. ``_EN`` first) and returns the first
    value that is a non-empty string and not a ``[bracketed]`` placeholder --
    unpopulated localized columns on a single-language instance echo the primary
    text in brackets. Pass a reordered ``languages`` on a deployment whose
    primary language is not English. Only the language suffixes are considered,
    so ``_CODE`` / ``_PATH`` are never mistaken for a label. Falls back to the
    first usable value in ``fallbacks`` (e.g. a code then a path).
    Case-insensitive on keys; never raises; returns ``None`` when nothing usable
    is found -- including when every language column holds a placeholder, so a
    caller that must always render something supplies its own last-resort text.

    Deliberately stricter than :func:`_nested_label`, which falls back to a
    placeholder rather than returning ``None``. The asymmetry is intentional:
    every caller here sits behind an explicit fallback of its own, while
    ``_nested_label``'s callers render nothing at all when the label is missing.
    """
    if isinstance(record, dict):
        upper = {k.upper(): v for k, v in record.items() if isinstance(k, str)}
        base = prefix.upper()
        for suffix in _normalized(tuple(languages)):
            got = _usable_label(upper.get(base + suffix))
            if got is not None:
                return got
    for value in fallbacks:
        got = _usable_label(value)
        if got is not None:
            return got
    return None


def label_from_record(
    record: dict[str, Any],
    *,
    languages: Sequence[str] = DEFAULT_LANGUAGE_ORDER,
    fallback_suffixes: Sequence[str] = ("_LABEL", "_PATH", "_CODE"),
) -> str | None:
    """The best human label anywhere in a reference-table row, matched by suffix.

    A reference table does not name its label column after the table. On the
    verified instance's own OpenAPI response schemas ``groups`` returns
    ``GROUP_EN``, ``locations`` returns ``LOCATION_FR``, ``catalog-requests``
    returns ``TITLE_EN`` and ``slas`` returns ``NAME_FR`` -- four different
    prefixes for the same job. Those schemas are tier 3 (example-derived,
    illustrative only), which is the second reason to match on the *suffix*
    rather than on a prefix a caller would have to know in advance.

    Scans for the first key ending in one of ``languages``, in the order
    ``languages`` gives, whose value is a usable label; then the first key
    ending in one of ``fallback_suffixes``. A ``[bracketed]`` value is skipped
    (an unpopulated translation column echoes ``"[CODE]"`` on a single-language
    instance) and ``HREF`` is never a label. Case-insensitive on keys; never
    raises; returns ``None`` when nothing usable is found.

    :func:`resolve_reference` deliberately does **not** route through this. Its
    own nested-label scan runs a bracket-tolerant second pass so a fully
    untranslated record still renders something, and it appends ``_PATH`` to
    the language order rather than treating it as a separate rung. Routing it
    through here would change what ``.reference("STATUS").label`` returns on a
    record whose every language column holds a placeholder -- a behaviour
    change, not a refactor, and out of scope here.
    """
    if not isinstance(record, dict):
        return None
    items = [(k.upper(), v) for k, v in record.items() if isinstance(k, str)]
    for suffix in _normalized(tuple(languages)):
        for key, value in items:
            if key == "HREF" or not key.endswith(suffix):
                continue
            got = _usable_label(value)
            if got is not None:
                return got
    for suffix in fallback_suffixes:
        upper_suffix = suffix.upper()
        for key, value in items:
            if key == "HREF" or not key.endswith(upper_suffix):
                continue
            got = _usable_label(value)
            if got is not None:
                return got
    return None

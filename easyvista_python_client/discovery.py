"""Instance discovery: where each reference lives, and how to read it.

Pure and offline. Holds the name-to-route map, the two result dataclasses and
the extractors the clients delegate to; nothing here performs I/O or imports a
client.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

from .references import (
    DEFAULT_LANGUAGE_ORDER,
    Reference,
    label_from_record,
    localized_label,
    resolve_reference,
)
from .reporting import fields_for_references


@dataclass(frozen=True)
class ReferenceSource:
    """Where one reference name can be read on an EasyVista instance.

    ``reference_path`` is the list route, or ``None`` when this deployment's
    OpenAPI declares no route for it at all -- in which case the only way to
    learn the ids is to sample records that carry them.
    """

    name: str
    reference_path: str | None
    sample_from: str  # "tickets" | "actions"
    sample_field: str
    id_field: str | None = None
    guid_field: str | None = None


#: Name -> where to read it. Every path here is declared in the verified
#: instance's OpenAPI ``paths`` (tier 2, read 2026-08-27, EasyVista 2025.3);
#: every ``None`` is a route that is **absent** from those 100 paths.
#:
#: ``urgency`` is SINGULAR. The vendor documents ``GET /urgencies`` (tier 1)
#: and the instance declares ``GET /urgency`` (tier 2); which is canonical is
#: unresolved -- open item O-URGPATH in ``docs/vendor-api-reference.md``. The
#: default is the spelling this deployment declares, and
#: ``discover(reference_path=...)`` reaches the other without a fork.
#:
#: ``IMPACT``, ``SEVERITY``, ``ORIGIN`` and ``ACTION_TYPE`` have no route in
#: the spec, so they are sampling-only by construction rather than by a 403
#: someone measured. Priority has neither a route nor a column: EasyVista
#: derives it from urgency x impact, so there is nothing to discover.
REFERENCE_SOURCES: dict[str, ReferenceSource] = {
    "STATUS": ReferenceSource(
        "STATUS", "status", "tickets", "STATUS", guid_field="STATUS_GUID"
    ),
    "URGENCY": ReferenceSource("URGENCY", "urgency", "tickets", "URGENCY"),
    "CATALOG_REQUEST": ReferenceSource(
        "CATALOG_REQUEST",
        "catalog-requests",
        "tickets",
        "CATALOG_REQUEST",
        id_field="SD_CATALOG_ID",
    ),
    "LOCATION": ReferenceSource("LOCATION", "locations", "tickets", "LOCATION"),
    "DEPARTMENT": ReferenceSource(
        "DEPARTMENT", "departments", "tickets", "DEPARTMENT"
    ),
    "SLA": ReferenceSource("SLA", "slas", "tickets", "SLA"),
    # No ticket column carries a group; an action does (ACTION.GROUP_ID).
    "GROUP": ReferenceSource("GROUP", "groups", "actions", "GROUP"),
    "IMPACT": ReferenceSource("IMPACT", None, "tickets", "IMPACT"),
    "SEVERITY": ReferenceSource("SEVERITY", None, "tickets", "SEVERITY"),
    # PostRequest.origin reads back as REQUEST_ORIGIN_ID; ORIGIN is not
    # returned at all, so that is the column to project.
    "ORIGIN": ReferenceSource("ORIGIN", None, "tickets", "REQUEST_ORIGIN"),
    "ACTION_TYPE": ReferenceSource("ACTION_TYPE", None, "actions", "ACTION_TYPE"),
}

#: The names ``describe_instance`` profiles when none are given.
DEFAULT_DISCOVERY_NAMES: tuple[str, ...] = tuple(REFERENCE_SOURCES)


@dataclass(frozen=True)
class DiscoveredReference:
    """One value of one reference, as found on this instance.

    ``id`` is what a write model takes (``urgency_id``, ``impact_id``,
    ``department_id``, ...). ``guid`` is populated only where a GUID is
    reachable -- today that is ``STATUS``, read off sampled tickets. ``code``
    is the instance's own short code, and for ``CATALOG_REQUEST`` it is what
    ``PostRequest.catalog_code`` accepts. ``count`` is how many sampled records
    carried this value, and is ``None`` for a value read from a reference
    table. ``source`` is ``"reference"`` or ``"sample"``. ``record`` is the raw
    row, unmodelled, so an instance-specific column is still reachable.

    Every value here is **per-deployment configuration**, not an API constant.
    Do not hardcode one; rediscover it, or resolve it at start-up and fail
    loudly when it is gone.
    """

    name: str
    id: str | None
    label: str | None = None
    guid: str | None = None
    code: str | None = None
    path: str | None = None
    count: int | None = None
    source: str = "reference"
    record: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class InstanceProfile:
    """What one EasyVista deployment could tell this client about itself.

    ``references`` maps each requested name to what was found. ``unavailable``
    maps a part that is missing or incomplete to a reason whose first token is
    machine-readable: ``denied`` (401/403), ``failed`` (any other transport or
    server error), ``no-route`` (the spec declares none, so sampling was the
    only option), ``empty`` (the read succeeded and returned nothing) or
    ``truncated`` (a page cap cut the table short -- the rows present are real,
    they are just not all of them). A name can appear in **both** dicts;
    ``truncated`` is exactly that case.

    **This never raises for one part.** Every fetch is attempted; a failure is
    recorded and the rest continues. An empty ``spec_paths`` together with a
    ``references`` dict of empty lists means the instance was unreachable, not
    that it has no statuses -- read ``unavailable`` before believing a gap.

    What discovery **cannot** reach, whatever the profile:

    * **``catalog_guid``.** No route returns it. ``GET /catalog-requests``
      exists on this deployment (tier 2) and its response schema declares
      ``CODE``, ``SD_CATALOG_ID``, ``TITLE_EN``, ``CATALOG_REQUEST_PATH``,
      nested ``MANAGER`` and nested ``SLA`` (tier 3 -- example-derived,
      illustrative only). ``CODE`` is what ``PostRequest.catalog_code`` accepts
      and ``SD_CATALOG_ID`` is what reads back as ``Request.sd_catalog_id``;
      there is no ``CATALOG_GUID`` column in the schema and none was observed
      live. So build with ``catalog_code``. The vendor documents
      ``catalog_guid`` as the *preferred* identifier (tier 1) and
      ``close_ticket`` accepts one -- you just cannot read one from here.
    * **``catalog_code`` when the route is denied.** A 403 on
      ``/catalog-requests`` is a **profile restriction on a route that
      exists**, not an API limitation: ask your EasyVista administrator to
      grant the profile read access to the request catalog. Until then the
      sampling fallback returns only catalogs already used by a ticket you can
      see.
    * **Which ``ACTION_TYPE_ID`` means "internal note" and which means
      "customer comment".** The ids are discoverable -- every action row
      carries ``ACTION_TYPE_ID`` beside translated ``ACTION_LABEL_*`` columns,
      and there is no route for the type table (tier 2: none is declared). The
      *meaning* is a label a human has to read. On the verified instance type
      94 is ``Commentaire [Public]`` / Customer Comment and 95 is
      ``Note Interne [Prive]`` / Internal Note (tier 4, one instance, date not
      recorded); ids are per-deployment and those two are not portable. There
      is no public/private boolean on an action record to fall back on.
    * **``group_id`` when ``/groups`` is denied.** Creating an action requires
      one of ``group_id`` / ``group_mail`` / ``group_name`` (tier 1). With the
      route denied, the sampled fallback reads ``GROUP_ID`` off existing
      actions -- ids only, no labels -- and reaches only groups already in use.
    * **A full enumeration of IMPACT, SEVERITY or ORIGIN.** No route exists for
      any of them, so what you get is "the ids in use in the sample". An id
      that is configured but unused is invisible, and a count from a sample is
      not a population count. Priority is not discoverable at all: EasyVista
      derives it from urgency x impact.
    * **A ``STATUS_GUID`` for a status no sampled ticket currently holds.**
    """

    api_root: str
    version: str | None
    spec_paths: tuple[str, ...]
    references: dict[str, list[DiscoveredReference]]
    unavailable: dict[str, str]


def resolve_source(
    name: str,
    *,
    reference_path: str | None = None,
    sources: Mapping[str, ReferenceSource] = REFERENCE_SOURCES,
) -> ReferenceSource:
    """The :class:`ReferenceSource` for ``name``, case-insensitively.

    An unknown name is not an error: it yields a sampling-only source that
    reads ``name`` off a ticket, which is exactly right for a custom ``e_*``
    column. ``reference_path`` overrides the mapped route (or supplies one for
    a name that has none); ``sources`` replaces the whole map for a deployment
    that routes a table somewhere else. Both are arguments rather than
    configuration a caller has to patch into the package.
    """
    key = name.strip().upper()
    source = sources.get(key)
    if source is None:
        source = ReferenceSource(key, None, "tickets", key)
    if reference_path is not None:
        source = ReferenceSource(
            source.name,
            reference_path,
            source.sample_from,
            source.sample_field,
            source.id_field,
            source.guid_field,
        )
    return source


def _upper_items(row: Mapping[str, Any]) -> list[tuple[str, Any]]:
    return [(k.upper(), v) for k, v in row.items() if isinstance(k, str)]


def _scalar_text(value: Any) -> str | None:
    """A non-empty scalar rendered as text, else ``None``.

    Nested objects and lists are never ids or codes, so they are refused rather
    than stringified into something that looks like one.
    """
    if value is None or isinstance(value, dict | list):
        return None
    text = str(value).strip()
    return text or None


def _table_row_id(row: Mapping[str, Any], source: ReferenceSource) -> str | None:
    """The id of a reference-table row, by precedence.

    Only TOP-LEVEL keys are scanned, so a nested ``MANAGER.EMPLOYEE_ID`` or
    ``SLA.SLA_ID`` on a catalog row cannot win.
    """
    items = _upper_items(row)
    lookup = dict(items)
    candidates = []
    if source.id_field:
        candidates.append(source.id_field.upper())
    candidates.append(f"{source.name}_ID")
    for candidate in candidates:
        got = _scalar_text(lookup.get(candidate))
        if got is not None:
            return got
    for key, value in items:
        if key.endswith(("_ID", "_GUID")):
            got = _scalar_text(value)
            if got is not None:
                return got
    href = _scalar_text(lookup.get("HREF"))
    if href:
        tail = href.rstrip("/").rsplit("/", 1)[-1]
        return tail or None
    return None


def _by_suffix(
    items: Sequence[tuple[str, Any]], preferred: str, suffix: str
) -> str | None:
    """The value of ``preferred``, else the first key ending in ``suffix``.

    A bare key equal to the suffix without its leading underscore also counts:
    ``catalog-requests`` names its short code plain ``CODE``.
    """
    lookup = dict(items)
    for candidate in (preferred, suffix.lstrip("_")):
        got = _scalar_text(lookup.get(candidate))
        if got is not None:
            return got
    for key, value in items:
        if key.endswith(suffix):
            got = _scalar_text(value)
            if got is not None:
                return got
    return None


def reference_from_table_row(
    row: Mapping[str, Any],
    source: ReferenceSource,
    *,
    languages: Sequence[str] = DEFAULT_LANGUAGE_ORDER,
) -> DiscoveredReference:
    """Turn one reference-table row into a :class:`DiscoveredReference`.

    Column naming is not consistent across the tables, so each part is resolved
    by a precedence chain rather than a fixed name:

    * **id** -- ``source.id_field`` when the map names one (``SD_CATALOG_ID``
      for ``catalog-requests``), else ``<NAME>_ID`` (``LOCATION_ID``,
      ``GROUP_ID``, ``SLA_ID``), else the first top-level ``*_ID`` / ``*_GUID``
      key in document order, else the trailing segment of ``HREF``. Only
      TOP-LEVEL keys are scanned, so a nested ``MANAGER.EMPLOYEE_ID`` or
      ``SLA.SLA_ID`` on a catalog row cannot win.
    * **label** -- :func:`~easyvista_python_client.references.label_from_record`.
    * **code** -- ``<NAME>_CODE``, else a bare ``CODE`` (which is what
      ``catalog-requests`` uses), else the first ``*_CODE``.
    * **path** -- ``<NAME>_PATH``, else the first ``*_PATH``.

    ``.record`` keeps the row verbatim, so an instance-specific column this
    function knows nothing about is still one dict lookup away.
    """
    items = _upper_items(row)
    return DiscoveredReference(
        name=source.name,
        id=_table_row_id(row, source),
        label=label_from_record(dict(row), languages=languages),
        code=_by_suffix(items, f"{source.name}_CODE", "_CODE"),
        path=_by_suffix(items, f"{source.name}_PATH", "_PATH"),
        source="reference",
        record=dict(row),
    )


def references_from_sample(
    records: Iterable[Mapping[str, Any]],
    source: ReferenceSource,
    *,
    languages: Sequence[str] = DEFAULT_LANGUAGE_ORDER,
) -> list[DiscoveredReference]:
    """Distinct values of ``source`` across sampled records, with occurrence counts.

    Each record goes through
    :func:`~easyvista_python_client.references.resolve_reference`, which already
    handles both shapes EasyVista uses -- a nested object carrying ``*_EN`` /
    ``*_FR`` labels, and a bare top-level ``<NAME>_ID``. Grouped by id (or by
    label when there is no id), ordered by descending ``count`` then by id, with
    ``source="sample"``. ``.code`` and ``.path`` stay ``None``: those are
    reference-table columns, and a sampled record carries neither.

    An action record is the one shape ``resolve_reference`` cannot read on its
    own: its type label lives in SIBLING ``ACTION_LABEL_<lang>`` columns rather
    than in a nested ``ACTION_TYPE`` object, so those are consulted as a second
    rung. :func:`sample_fields` projects them for exactly this reason -- without
    the fallback, that projection would be requested and then ignored, and
    every discovered action type would come back with ``label=None``.

    This can only ever see values *in use*. An id configured on the instance but
    absent from every sampled record is invisible here, and no count from a
    sample is a population count.
    """
    seen: dict[str, DiscoveredReference] = {}
    counts: dict[str, int] = {}
    label_prefix = (
        "ACTION_LABEL"
        if source.sample_from == "actions" and source.sample_field == "ACTION_TYPE"
        else None
    )
    for record in records:
        ref = resolve_reference(dict(record), source.sample_field, languages=languages)
        sibling_label = (
            localized_label(dict(record), label_prefix, languages=languages)
            if label_prefix
            else None
        )
        if sibling_label is not None and ref.label is None:
            ref = Reference(id=ref.id, label=sibling_label)
        if ref.id is None and ref.label is None:
            continue
        key = ref.id if ref.id is not None else f"label:{ref.label}"
        counts[key] = counts.get(key, 0) + 1
        if key not in seen:
            seen[key] = DiscoveredReference(
                name=source.name,
                id=ref.id,
                label=ref.label,
                source="sample",
                record=dict(record),
            )
        elif seen[key].label is None and ref.label is not None:
            # A later record carried the label an earlier one lacked. Keep it:
            # a projection can return the id on one row and the nested object
            # on another.
            seen[key] = DiscoveredReference(
                name=source.name,
                id=ref.id,
                label=ref.label,
                source="sample",
                record=dict(record),
            )
    found = [
        DiscoveredReference(
            name=ref.name,
            id=ref.id,
            label=ref.label,
            guid=ref.guid,
            code=ref.code,
            path=ref.path,
            count=counts[key],
            source="sample",
            record=ref.record,
        )
        for key, ref in seen.items()
    ]
    found.sort(key=lambda r: (-(r.count or 0), r.id or ""))
    return found


def guids_from_sample(
    records: Iterable[Mapping[str, Any]], source: ReferenceSource
) -> dict[str, str]:
    """``{id: guid}`` read out of sampled records' nested reference objects.

    Empty unless ``source.guid_field`` is set -- today that is ``STATUS``
    alone. See ``discover`` on either client for why this exists and what it
    costs.
    """
    if not source.guid_field:
        return {}
    guid_key = source.guid_field.upper()
    id_key = f"{source.sample_field.upper()}_ID"
    out: dict[str, str] = {}
    for record in records:
        nested = next(
            (
                value
                for key, value in _upper_items(record)
                if key == source.sample_field.upper() and isinstance(value, dict)
            ),
            None,
        )
        if not nested:
            continue
        nested_items = dict(_upper_items(nested))
        guid = _scalar_text(nested_items.get(guid_key))
        ident = _scalar_text(nested_items.get(id_key)) or _scalar_text(
            dict(_upper_items(record)).get(id_key)
        )
        if guid and ident and ident not in out:
            out[ident] = guid
    return out


def merge_guids(
    discovered: Sequence[DiscoveredReference], guids: Mapping[str, str]
) -> list[DiscoveredReference]:
    """Copy of ``discovered`` with ``.guid`` filled in where ``guids`` has the id.

    Entries with no matching id keep ``guid=None``; nothing is dropped and
    nothing is invented.
    """
    out: list[DiscoveredReference] = []
    for ref in discovered:
        guid = guids.get(ref.id) if ref.id is not None else None
        if guid is None or ref.guid is not None:
            out.append(ref)
            continue
        out.append(
            DiscoveredReference(
                name=ref.name,
                id=ref.id,
                label=ref.label,
                guid=guid,
                code=ref.code,
                path=ref.path,
                count=ref.count,
                source=ref.source,
                record=ref.record,
            )
        )
    return out


def sample_fields(
    source: ReferenceSource,
    *,
    languages: Sequence[str] = DEFAULT_LANGUAGE_ORDER,
) -> list[str]:
    """The ``fields=`` projection that makes ``source`` resolvable on a sample row.

    Tickets ride
    :func:`~easyvista_python_client.reporting.fields_for_references` unchanged:
    it already asks for the nested object plus ``_ID`` and ``_GUID``, and the
    API ignores a projected column it does not have.

    Actions need their own list, because the actions list returns a deliberately
    slim default row -- ``ACTION_ID``, ``ACTION_LABEL_FR``, ``ACTION_NUMBER``,
    ``DONE_BY_ID``, ``EXPECTED_START_DATE_UT`` -- so the translated
    ``ACTION_LABEL_<LANG>`` columns must be asked for by name. They are added
    only for ``ACTION_TYPE``: an action carries ``GROUP_ID`` but no group label,
    so discovering ``GROUP`` by sampling yields ids with ``label=None``. That is
    stated rather than papered over with a fabricated label.
    """
    if source.sample_from == "actions":
        fields = ["ACTION_ID", source.sample_field, f"{source.sample_field}_ID"]
        if source.sample_field == "ACTION_TYPE":
            fields += [
                f"ACTION_LABEL{suffix}"
                for suffix in ("_" + s.strip().lstrip("_").upper() for s in languages)
            ]
        return fields
    return fields_for_references([source.sample_field], include_creation_date=False)

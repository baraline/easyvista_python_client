"""EasyVista client — a flat facade over the resource builders.

The blocking and the coroutine surface are two spellings of one source: they
differ only in the ``async``/``await`` keywords and in the few names that must
differ (the client class, its iterator types, ``aclose``/``close``). Every
docstring and comment in this module therefore describes both, and prose here
must read true on either surface -- never "see the other client", and never a
claim that holds on only one of them.
"""

from __future__ import annotations

from collections.abc import Iterator, Iterable, Mapping, Sequence
from datetime import datetime
from typing import Any

from easyvista_python_client._sync._concurrency import Semaphore, settle
from easyvista_python_client._sync._transport import (
    DEFAULT_STREAM_CHUNK_SIZE,
    Transport,
)
from easyvista_python_client._transport import RequestSpec
from easyvista_python_client.config import DocumentDeletePathStyle, EasyvistaConfig
from easyvista_python_client.context import TicketContext, _degraded_entry
from easyvista_python_client.directory import (
    DEPARTMENT_MEMO_FIELD,
    DEPARTMENT_NAME_COLUMNS,
    DEPARTMENT_NOTE_FIELDS,
    RECENT_TICKET_FIELDS,
    RECENT_TICKETS_SORT,
    DepartmentContext,
    _as_fields,
    _department_matches,
    _normalize_name,
)
from easyvista_python_client.discovery import (
    DEFAULT_DISCOVERY_NAMES,
    DiscoveredReference,
    InstanceProfile,
    ReferenceSource,
    guids_from_sample,
    merge_guids,
    reference_from_table_row,
    references_from_sample,
    resolve_source,
    sample_fields,
)
from easyvista_python_client.exceptions import (
    EasyvistaAuthError,
    EasyvistaError,
    EasyvistaNotFound,
)
from easyvista_python_client.field_model import parse_memo
from easyvista_python_client.filters import ev_equals_filter, is_safe_ev_value
from easyvista_python_client.models.action import (
    Action,
    ActionUpdate,
    PostAction,
    PostTask,
)
from easyvista_python_client.models.asset import Asset, PostAsset
from easyvista_python_client.models.department import (
    Department,
    DepartmentUpdate,
    PostDepartment,
)
from easyvista_python_client.models.document import Document
from easyvista_python_client.models.employee import (
    Employee,
    EmployeeUpdate,
    PostEmployee,
)
from easyvista_python_client.models.generic import GenericRecord
from easyvista_python_client.models.request import PostRequest, Request, RequestUpdate
from easyvista_python_client.pagination import SearchResult
from easyvista_python_client.references import DEFAULT_LANGUAGE_ORDER
from easyvista_python_client.reporting import (
    DEFAULT_DIMENSIONS,
    TicketStatistics,
    aggregate_tickets,
    fields_for_references,
)
from easyvista_python_client.resources import actions as actions_res
from easyvista_python_client.resources import assets as assets_res
from easyvista_python_client.resources import departments as departments_res
from easyvista_python_client.resources import discovery as discovery_res
from easyvista_python_client.resources import documents as documents_res
from easyvista_python_client.resources import employees as employees_res
from easyvista_python_client.resources import requests as requests_res
from easyvista_python_client.resources.discovery import SWAGGER_PATH

# Width of the action-body fan-out: a ceiling on requests in flight at once on
# the async surface, inert on the sync one. This is the one fan-out here whose
# width is set by the server (a ticket can carry any number of actions); the
# department fan-out is a fixed seven and needs no bound. Deliberately not a
# config field: nobody has asked for it, and measured against a live instance a
# limit of 8 costs nothing (19 actions took 5.31s at limit 8 vs 5.43s unbounded
# -- the server, not the client, is the bottleneck).
_ACTION_FANOUT = 8


def _unavailable_reason(exc: EasyvistaError) -> str:
    """One ``InstanceProfile.unavailable`` value, first token machine-readable.

    ``denied`` for 401/403, ``failed`` for everything else. The rest of the
    string is for a human; split on the first space to branch on it.

    A 403 here does NOT prove the route is denied: this API answers 403 for a
    path that does not exist as well as for one a profile blocks, so the reason
    says "denied or absent" rather than asserting which.
    """
    status = getattr(exc, "status_code", None)
    if status in (401, 403):
        return (
            f"denied HTTP {status} -- the profile may lack read access, or the "
            "route may not exist on this deployment; this API answers 403 for "
            "both. Check get_api_spec()['paths']."
        )
    detail = f"HTTP {status}" if isinstance(status, int) else type(exc).__name__
    return f"failed {detail}"


class EasyvistaClient:
    """Client for the EasyVista Service Manager REST API.

    Blocking as ``EasyvistaClient``, coroutine-returning as
    ``AsyncEasyvistaClient``: same methods, same arguments, same results.
    """

    def __init__(self, config: EasyvistaConfig) -> None:
        self.config = config
        self._transport = Transport(config)
        # Built once and passed to every resource builder. ``None`` unless the
        # caller named extra timestamp formats, so the default path calls
        # ``model_validate(record, context=None)`` -- exactly what it always
        # called.
        self._validation_context: dict[str, Any] | None = (
            {"datetime_input_formats": config.datetime_input_formats}
            if config.datetime_input_formats
            else None
        )

    @classmethod
    def from_env(cls) -> EasyvistaClient:
        return cls(EasyvistaConfig.from_env())

    def __enter__(self) -> EasyvistaClient:
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()

    def close(self) -> None:
        self._transport.close()

    # --- escape hatch --------------------------------------------------------
    def send(
        self,
        method: str,
        path: str,
        *,
        params: Mapping[str, Any] | None = None,
        json: Any = None,
        headers: Mapping[str, str] | None = None,
    ) -> Any:
        """Issue an arbitrary request against this instance's API root.

        The escape hatch. This package wraps roughly ten of the paths the
        instance's own OpenAPI document advertises -- about a hundred of them on
        the verified 2025.3 instance, read from ``GET {api_root}/swagger`` (tier
        2: authoritative for that deployment, and another deployment may
        advertise a different set). This reaches the rest without forking the
        package: reference tables such as ``status``, ``urgency``, ``groups``,
        ``locations`` and ``slas``, the external-table route, and whole families
        like ``problems`` and ``known-errors``.

        ``path`` joins to ``config.api_root`` exactly as every built-in method's
        path does; a leading ``/`` is stripped, so ``"status"`` and ``"/status"``
        address the same route. An absolute URL is **not** accepted, which is
        what keeps the credential scoped to the configured instance by
        construction. To fetch a URL the API handed back, use
        :meth:`download_document` or :meth:`stream_document`.

        Everything else is shared with the typed methods: ``config.max_retries``
        attempts with the same backoff, and the same exception mapping -- 401 and
        403 to :class:`~easyvista_python_client.EasyvistaAuthError`, 404 to
        :class:`~easyvista_python_client.EasyvistaNotFound`, 400 and 590 to
        :class:`~easyvista_python_client.EasyvistaValidationError`, with 590 never
        retried because it is a rejected request rather than a transient one.
        ``config.default_params`` is merged under ``params``; ``headers`` is
        merged over the client-level ones and may not carry ``Authorization``.

        Returns the decoded JSON body, or ``{}`` when the response has none.
        Nothing is validated into a model and no envelope is unwrapped: the
        caller owns the shape, which is the point -- there is no model for a
        route this package does not wrap.

        Two cautions that apply to every route reached this way. A 590 on a
        create may still have created the row, so retrying can duplicate it. And
        this API answers a write with HTTP 200 while silently dropping fields it
        did not accept, so a 200 is not a receipt -- re-read.
        """
        return self._transport.send(
            RequestSpec(
                method.upper(),
                path,
                json=json,
                headers=dict(headers) if headers else None,
            ),
            params=params,
        )

    # --- tickets -------------------------------------------------------------
    def create_ticket(self, ticket: PostRequest) -> Request:
        spec, parse = requests_res.build_create_ticket(
            ticket, context=self._validation_context
        )
        return parse(self._transport.send(spec))

    def create_tickets(self, tickets: Sequence[PostRequest]) -> list[Request]:
        # One request per ticket (EasyVista creates only the first item of a
        # multi-item body).
        #
        # Stays SEQUENTIAL on purpose on BOTH surfaces -- unlike the read
        # bundles below, which fan out on the async one. These are writes:
        # EasyVista assigns the RFC number server-side, so concurrent POSTs
        # return in scheduling order, and a failure part-way through would
        # leave the caller holding an exception with no way to say which tickets
        # now exist. Sequentially a failure at item k means 0..k-1 exist and the
        # rest do not, which is a contract a caller can act on. Do not "fix"
        # this into a fan-out.
        return [self.create_ticket(ticket) for ticket in tickets]

    def get_ticket(
        self,
        rfc_number: str,
        *,
        fields: str | list[str] | None = None,
        params: Mapping[str, Any] | None = None,
    ) -> Request:
        """Fetch one ticket by RFC number.

        ``fields`` is a projection -- the same comma-separated column list
        :meth:`search_tickets` takes. Left ``None`` it sends no ``fields``
        parameter at all, which is every request this method has ever sent.

        Pass it when one column poisons the whole record. A value the read
        model refuses -- a timestamp in an unexpected format, say -- fails the
        entire :class:`Request`, and there is otherwise no way to read the rest
        of the ticket.

        One caveat, and it cuts against this parameter. The verified instance's
        own OpenAPI declares ``fields`` on ``GET /requests`` (the list) but
        **not** on ``GET /requests/{rfc_number}`` -- tier 2, read 2026-08-31 --
        so the item route may ignore it and return the full record anyway. It
        costs one request to find out on your deployment. The route that *is*
        declared to take a projection is the list one, and it reaches the same
        ticket::

            search_tickets(
                search=ev_equals_filter("RFC_NUMBER", rfc),
                fields=["RFC_NUMBER", "TITLE"],
                max_rows=1,
            )
        """
        spec, parse = requests_res.build_get_ticket(
            rfc_number, fields=fields, context=self._validation_context
        )
        return parse(self._transport.send(spec, params=params))

    def search_tickets(
        self,
        *,
        search: str | None = None,
        fields: str | list[str] | None = None,
        sort: str | None = None,
        max_rows: int | None = None,
        offset: int | None = None,
        params: Mapping[str, Any] | None = None,
    ) -> SearchResult[Request]:
        if max_rows is None:
            max_rows = self.config.default_max_rows
        spec, parse = requests_res.build_search_tickets(
            search=search,
            fields=fields,
            sort=sort,
            max_rows=max_rows,
            offset=offset,
            context=self._validation_context,
        )
        return parse(self._transport.send(spec, params=params))

    def iter_tickets(
        self,
        *,
        search: str | None = None,
        fields: str | list[str] | None = None,
        sort: str | None = None,
        page_size: int | None = None,
        max_records: int | None = None,
        params: Mapping[str, Any] | None = None,
    ) -> Iterator[Request]:
        """Yield tickets across pages, following the API's offset pagination.

        Pages of ``page_size`` (default ``config.default_max_rows``) until the
        server reports no further page (``@next``) or ``max_records`` is reached.

        ``sort`` is forwarded to the wire and its token must be
        **space-separated** — ``"LAST_UPDATE"`` or ``"LAST_UPDATE DESC"``.
        ``"LAST_UPDATE:DESC"``, ``"-LAST_UPDATE"`` and ``"DESC(LAST_UPDATE)"``
        are each **silently ignored** (measured live): the server returns its
        default order with no error, so an unsorted result looks sorted. This is
        not validated locally, so the token is the caller's to get right.

        Sorting is not cosmetic when the filter selects rows that are changing:
        an unsorted offset sweep over a change window can skip a record
        permanently, and the two sort DIRECTIONS do not fail the same way --
        descending defers such a miss to the next sweep, ascending loses it. See
        :func:`~easyvista_python_client.ev_since_filter`, which rules on the
        direction and names the keyset alternative for a caller who cannot
        tolerate even a deferred miss.
        """
        if page_size is None:
            page_size = self.config.default_max_rows
        offset = 0
        yielded = 0
        while max_records is None or yielded < max_records:
            result = self.search_tickets(
                search=search,
                fields=fields,
                sort=sort,
                max_rows=page_size,
                offset=offset,
                params=params,
            )
            if not result.records:
                return
            for record in result.records:
                yield record
                yielded += 1
                if max_records is not None and yielded >= max_records:
                    return
            if result.next_url is None:
                return
            offset += len(result.records)

    def count_tickets(self, search: str | None = None) -> int:
        """Return the number of tickets matching ``search`` (one cheap call).

        Uses ``max_rows=1`` and reads the envelope's ``total_record_count``, so
        it does not fetch the matching records.
        """
        result = self.search_tickets(search=search, max_rows=1)
        return result.total_record_count

    def _collect_tickets(
        self,
        *,
        search: str | None,
        fields: str | list[str] | None,
        max_records: int | None,
    ) -> tuple[list[Request], int | None]:
        """Page tickets, returning them plus the first page's reported total.

        Exists because :meth:`iter_tickets` discards the envelope: it yields
        records one at a time and has no way to also hand back
        ``total_record_count``, which is what tells a capped aggregation how
        large the population it sampled actually was. The paging is the same
        offset walk :meth:`iter_tickets` performs and issues the same requests
        for the same cap; it collects a whole page and trims at the end rather
        than stopping mid-page, which changes nothing on the wire.

        The total is the server's count for ``search`` alone. Any client-side
        date window is applied later, so it is not comparable with the
        aggregated total when one is set.
        """
        page_size = self.config.default_max_rows
        offset = 0
        population_total: int | None = None
        records: list[Request] = []
        while max_records is None or len(records) < max_records:
            result = self.search_tickets(
                search=search, fields=fields, max_rows=page_size, offset=offset
            )
            if population_total is None:
                population_total = result.total_record_count
            if not result.records:
                break
            records.extend(result.records)
            if result.next_url is None:
                break
            offset += len(result.records)
        if max_records is not None:
            del records[max_records:]
        return records, population_total

    def ticket_statistics(
        self,
        *,
        search: str | None = None,
        dimensions: Sequence[str] | None = None,
        created_since: datetime | str | None = None,
        created_until: datetime | str | None = None,
        max_records: int | None = 100,
        languages: Sequence[str] = DEFAULT_LANGUAGE_ORDER,
    ) -> TicketStatistics:
        """Aggregate matching tickets into a total plus per-dimension breakdowns.

        Fetches up to ``max_records`` tickets matching ``search`` (default cap 100;
        pass ``None`` to aggregate all) and groups them by each name in
        ``dimensions`` (default: all of ``DEFAULT_DIMENSIONS``). ``created_since`` /
        ``created_until`` apply an inclusive client-side window on the ticket's
        creation date.

        When the cap truncates, the result describes the fetched subset and
        ``TicketStatistics.truncated`` is ``True``; ``population_total`` carries
        the server's own count for ``search``, read off the first page at no
        extra request. ``truncated`` reports "the cap was reached", so it is
        ``True`` for a population whose size is exactly the cap; compare it
        against ``population_total`` when that distinction matters.
        ``population_total`` is counted before any client-side
        ``created_since``/``created_until`` window, so it is not comparable with
        ``total`` when one is set.

        Delegates to the same pure :func:`aggregate_tickets` on both surfaces.
        The page is collected into a list first because that function consumes
        a plain iterable.
        """
        dims = DEFAULT_DIMENSIONS if dimensions is None else dimensions
        has_date_filter = created_since is not None or created_until is not None
        fields = fields_for_references(dims, include_creation_date=has_date_filter)
        tickets, population_total = self._collect_tickets(
            search=search, fields=fields, max_records=max_records
        )
        stats = aggregate_tickets(
            tickets,
            dimensions=dims,
            created_since=created_since,
            created_until=created_until,
            languages=languages,
        )
        # aggregate_tickets is offline and knows nothing about pages or caps,
        # so these two are stamped here rather than computed in there.
        stats.truncated = max_records is not None and len(tickets) >= max_records
        stats.population_total = population_total
        return stats

    def update_ticket(self, rfc_number: str, update: RequestUpdate) -> Request:
        """Update a ticket's writable fields.

        Cannot set a status: there is no flat status update on this API. See
        :meth:`set_status`, and :class:`RequestUpdate` for the measurements.
        """
        spec, parse = requests_res.build_update_ticket(
            rfc_number, update, context=self._validation_context
        )
        return parse(self._transport.send(spec))

    def set_status(
        self, rfc_number: str, *, status_guid: str, comment: str | None = None
    ) -> Request:
        """Set a ticket's status, addressed by ``STATUS_GUID``.

        This is the API's only working status write, and it reaches **every**
        status rather than only terminal ones: given six different status GUIDs
        in turn, a fresh ticket landed on exactly the status requested every
        time, non-terminal ones included.

        It sends the documented ``{"closed": {"status_GUID": ...}}`` body -- the
        same request :meth:`close_ticket` sends, under a name that matches what
        it does, because "close" is what the wire calls it and not what it is
        limited to.

        Note the addressing. A ``STATUS_GUID`` is not a ``STATUS_ID``; the two
        are different columns, and only the GUID works here. Read a status's GUID
        off any ticket in that status (the nested ``STATUS`` object carries
        ``STATUS_GUID``) -- they are stable per instance but are **not**
        portable between instances.
        """
        spec, parse = requests_res.build_set_status(
            rfc_number,
            status_guid=status_guid,
            comment=comment,
            context=self._validation_context,
        )
        return parse(self._transport.send(spec))

    def close_ticket(
        self,
        rfc_number: str,
        *,
        status_guid: str | None = None,
        delete_actions: int | bool | None = None,
        comment: str | None = None,
        end_date: str | None = None,
        catalog_guid: str | None = None,
    ) -> Request:
        """Close a ticket, via the vendor's documented close route.

        Sends ``PUT requests/{rfc}`` with a ``closed`` wrapper --
        https://docs.easyvista.com/docs/rest-api-close-an-incident-request.md.
        Every argument is optional. With no ``end_date`` the server stamps now.
        With no ``status_guid`` this client sends no status of its own -- but
        **where the ticket then lands is not established here**: the behaviour
        is not recorded in ``docs/vendor-api-reference.md`` and no live test
        exercises the omitted form, every one of them passing an explicit
        ``status_guid``. Try it on a throwaway ticket and re-read before
        relying on it (open item O-CLOSE-DEFAULT).

        **Verify the close by re-reading the status, not by the return value.**
        A status id is per-instance configuration and nothing about it is
        guessable: on the verified instance ``8`` is *Cloturé* and ``12`` is
        *En cours* -- adjacent numbers, opposite meanings. Code that infers
        "closed" from an id it did not read off that instance will eventually
        skip a ticket it believed was already closed. Read
        ``get_ticket(rfc).status_id`` (or ``.reference("STATUS")`` for the
        label) afterwards, and compare against a status you resolved from the
        instance rather than a constant::

            client.close_ticket(rfc, status_guid=CLOSED_GUID)
            after = client.get_ticket(rfc)
            assert after.end_date_ut is not None  # the close actually landed

        ``end_date_ut`` is the more portable signal than any status id: it is
        empty while a ticket is being worked and stamped once it is finished.
        Note the boundary is **resolution, not closure** — measured 2026-09-02
        on one instance (one instance, one date, so it may not generalise), a
        ticket that reached *Résolu* already carried an ``end_date_ut``, and
        closing it afterwards left that original stamp untouched rather than
        re-stamping it. So a populated ``end_date_ut`` means "resolved or
        closed", which is the right test for "stop working this ticket" but
        **not** a test for "closed" specifically. Nothing in this package
        distinguishes the two without resolving the status against the
        instance.

        ``status_guid`` reaches **any** status, not only terminal ones -- see
        :meth:`set_status`, which is this same request under a name that says
        so. ``catalog_guid`` requalifies the ticket as it closes.
        ``delete_actions`` drops its actions.

        ``end_date`` takes the instance's own date format, which is not ISO 8601
        everywhere (``dd/mm/yyyy`` on the verified instance -- read
        ``DATE_FORMAT`` off any employee record), so it is a string this client
        passes through rather than a ``datetime`` it would have to format on a
        guess.
        """
        spec, parse = requests_res.build_close_ticket(
            rfc_number,
            status_guid=status_guid,
            delete_actions=delete_actions,
            comment=comment,
            end_date=end_date,
            catalog_guid=catalog_guid,
            context=self._validation_context,
        )
        return parse(self._transport.send(spec))

    # --- actions -------------------------------------------------------------
    def create_action(self, rfc_number: str, action: PostAction) -> Action:
        """Create one action on a ticket.

        The returned :class:`Action` carries **no usable ``action_id``**: the
        live create response is an HREF naming the parent request, with no
        ``ACTION_ID`` (verified live). To address the action you just created,
        diff :meth:`list_actions` across the call — see
        ``integration_tests/test_live_ticket_history.py`` for the pattern.

        **For a comment, use :meth:`create_task` instead.** An action is created
        **open** — work still to do — and an open action shows in the UI as a
        pending row with its text NOT displayed, which reads as though the note
        was lost. Only an *ended* action becomes a readable history entry.
        :meth:`create_task` posts the same record already ended, in one call.
        Reach for ``create_action`` only when you genuinely mean "someone must
        still do this", and finish it with :meth:`end_action` — which also
        advances the ticket's workflow when the action is a workflow step, so
        read that method before calling it.

        Public versus internal is the ``action_type_id``, not a flag on the
        body — see :class:`~easyvista_python_client.PostAction`. Put the text a
        person must read in ``description``: it shadows ``comment`` in the UI.

        **This route resolves an implicit PARENT action, and that is what most
        rejections are about.** Measured 2026-09-01 on one instance (one
        instance, one date, may not generalise), the outcome tracks how many
        actions are currently **open** on the ticket:

        =================  ==========================================
        open actions       result
        =================  ==========================================
        0                  ``590 Parent action not found or incorrect``
        exactly 1          succeeds
        2 or more          ``590 Ambiguous query : many parent actions found``
        =================  ==========================================

        Passing ``parent_action_id`` for an **open** action succeeds at any
        count; naming an **ended** one is refused. A fresh ticket carries
        exactly one open workflow action, and every status change ends the
        ticket's open actions — which is why an otherwise valid payload can be
        refused on a ticket that accepted the same body earlier. The messages
        are literal, not a stage gate. :meth:`create_task` is not
        parent-resolved and is unaffected.
        """
        spec, parse = actions_res.build_create_action(
            rfc_number, action, context=self._validation_context
        )
        return parse(self._transport.send(spec))

    def create_task(self, rfc_number: str, task: PostTask) -> Action:
        """Create a task on a ticket — an action that arrives already ENDED.

        **This is how you post a comment.** A task and an action are the same
        underlying record, created in different states: an action starts open
        (a pending row whose text the UI does not display), a task starts
        ended, so it lands in the ticket's history with its text visible. One
        call, no termination step. Verified live 2026-08-28: tasks came back
        with ``END_DATE_UT`` and ``STATUS_ID_ON_TERMINATE`` already set.

        **Put that text in ``description``, not ``comment``**, despite the
        name. :class:`~easyvista_python_client.PostTask` accepts both, but the
        UI renders one field per action — ``description``, falling back to
        ``comment`` only when the description memo is empty (measured in the UI
        2026-09-01 on one instance; one instance, one date, may not
        generalise). A task carrying both shows only the description, so a note
        split across the two loses half of itself with no error.

        Public versus internal is carried by ``action_type_id`` — the type's
        own ``ACTION_LABEL_*`` columns say which it is. Unlike
        :meth:`create_action`, this route is **not** parent-resolved: it needs
        no ``parent_action_id`` and works on a ticket at any stage, including
        one whose open actions a status change has already drained.

        Like :meth:`create_action`, the returned :class:`Action` carries **no
        usable ``action_id``** — the create response is an HREF naming the
        parent request. Diff :meth:`list_actions` across the call to address
        what you just created.
        """
        spec, parse = actions_res.build_create_task(
            rfc_number, task, context=self._validation_context
        )
        return parse(self._transport.send(spec))

    def list_actions(
        self,
        rfc_number: str,
        *,
        fields: Iterable[str] | str | None = None,
        params: Mapping[str, Any] | None = None,
    ) -> list[Action]:
        """List a ticket's actions.

        The default projection is slim: it carries ``ACTION_ID``,
        ``ACTION_LABEL_FR``, ``ACTION_NUMBER``, ``DONE_BY_ID`` and
        ``EXPECTED_START_DATE_UT`` but **no** ``CREATION_DATE_UT`` or
        ``LAST_UPDATE``. Pass ``fields`` to project them onto the list and read
        a page of actions' timestamps and authors in one request rather than one
        item fetch each::

            actions = client.list_actions(
                rfc,
                fields=["ACTION_ID", "ACTION_TYPE_ID", "CREATION_DATE_UT",
                        "LAST_UPDATE", "DONE_BY_ID"],
            )

        **Returns at most ONE page and does not paginate.** The cap is
        ``config.default_max_rows``; a ticket with more actions than that is
        **truncated with no error**, and this method discards the envelope's
        total, so a caller cannot detect the truncation from the result. This is
        not hypothetical: a freshly created ticket already carries about twelve
        actions, most of them workflow-generated. Use
        :meth:`iter_actions` to page the whole log, or raise
        ``EasyvistaConfig.default_max_rows`` to widen this single page.

        The note text is never projectable — ``DESCRIPTION`` and ``COMMENT``
        are Memo sub-resources and come back as HREF objects under every
        projection, so a body still costs one :meth:`resolve_memo` per action.

        ``fields`` has two more silent footguns: ``"*"`` is not a wildcard —
        it silently reduces to ``ACTION_ID`` alone — and a dotted path such as
        ``DESCRIPTION.HREF`` is silently dropped.
        """
        spec, parse = actions_res.build_list_actions(
            rfc_number,
            fields=fields,
            max_rows=self.config.default_max_rows,
            context=self._validation_context,
        )
        return parse(self._transport.send(spec, params=params))

    def iter_actions(
        self,
        rfc_number: str,
        *,
        fields: Iterable[str] | str | None = None,
        page_size: int | None = None,
        max_records: int | None = None,
        params: Mapping[str, Any] | None = None,
    ) -> Iterator[Action]:
        """Yield a ticket's actions across pages, following offset pagination.

        Pages of ``page_size`` (default ``config.default_max_rows``) until the
        server reports no further page (``@next``) or ``max_records`` is
        reached. ``fields`` and the ticket filter apply to every page. See
        :meth:`list_actions` for what a projection can and cannot reach.

        A blank or unsafe ``rfc_number`` raises ``ValueError`` on the first
        iteration rather than at the call, since this is a generator.

        .. warning::

           The ``offset``/``@next`` contract is unverified on the ``actions``
           endpoint. If an instance ignores ``offset``, page two repeats page
           one and the sweep never ends; bound it with ``max_records``.
        """
        if page_size is None:
            page_size = self.config.default_max_rows
        offset = 0
        yielded = 0
        while max_records is None or yielded < max_records:
            spec, parse = actions_res.build_search_actions(
                rfc_number,
                fields=fields,
                max_rows=page_size,
                offset=offset,
                context=self._validation_context,
            )
            result = parse(self._transport.send(spec, params=params))
            if not result.records:
                return
            for record in result.records:
                yield record
                yielded += 1
                if max_records is not None and yielded >= max_records:
                    return
            if result.next_url is None:
                return
            offset += len(result.records)

    def get_action(
        self, action_id: str | int, *, params: Mapping[str, Any] | None = None
    ) -> Action:
        """Fetch one action, including the Memo links ``list_actions`` omits.

        The note text lives behind :attr:`Action.description`'s href on this
        record — but only while that memo has text. ``comment`` is a second
        href beside it, and it matters when ``description`` resolves empty:
        the UI renders one field per action, falling back to ``comment``
        exactly then (measured in the UI 2026-09-01 on one instance; one
        instance, one date, may not generalise). To reproduce what a person
        saw, resolve ``description`` first and ``comment`` only if it comes
        back empty. :meth:`get_ticket_context` applies that rule for you.
        """
        spec, parse = actions_res.build_get_action(
            action_id, context=self._validation_context
        )
        return parse(self._transport.send(spec, params=params))

    def update_action(self, action_id: str | int, update: ActionUpdate) -> Action:
        """Edit an existing action's note text.

        ``ActionUpdate`` carries two fields, ``description`` and ``comment``,
        and they are **not** interchangeable to a reader. The UI renders one
        text field per action — ``description``, falling back to ``comment``
        only when the description memo is empty (measured in the UI 2026-09-01
        on one instance; one instance, one date, may not generalise). So
        ``ActionUpdate(comment=...)`` on an action that already has a
        description returns 200, re-reads cleanly through the API, and changes
        nothing anyone sees. **Write ``description`` to change what a person
        reads.**

        Live-verified 2026-08-17 by re-reading the memo afterwards, not by the
        status code, and again 2026-09-01 on an action that had already been
        **ended**, where the new ``description`` rendered in the history — an
        ended action is not frozen, and this is how to correct or extend a
        resolution visibly. Note that an action can be edited but **not
        deleted**: the
        instance OpenAPI document (``GET {api_root}/swagger``, read 2026-08-27)
        declares only GET, PUT and PATCH on ``actions/{id}``, no DELETE, so
        there is deliberately no ``delete_action``. The 403 an earlier note
        recorded for that verb is what this API answers for an absent route as
        well as a denied one, so it did not distinguish them.

        The returned :class:`Action` is the API's own echo and is **not
        verified**: the PUT's response body has never been captured, and if it
        answers empty or href-only the parser yields an ``Action`` whose fields
        are all ``None``. Re-read with :meth:`get_action` rather than reading
        fields off the return value.
        """
        spec, parse = actions_res.build_update_action(
            action_id, update, context=self._validation_context
        )
        return parse(self._transport.send(spec))

    def end_action(
        self,
        rfc_number: str,
        *,
        action_id: str | int | None = None,
        end_all: bool = False,
        end_date: str | None = None,
        start_date: str | None = None,
        elapsed_time: int | str | None = None,
        doneby_mail: str | None = None,
    ) -> Action:
        """Report an action as done — the step :meth:`create_action` leaves open.

        An action is born **open** and its text does not render in the ticket
        history until it is ended, so this is what turns a ``create_action``
        into something a person can read. A comment needs neither call:
        :meth:`create_task` posts an already-ended record in one request.

        Addressed by the **ticket**, not the action: the path segment is
        ``rfc_number`` and the action is named in the body. Passing an action
        id as the path answers 404 even with the id also in the body (measured
        2026-09-01).

        .. warning::

           **Ending the ticket's own workflow action advances the workflow.**
           This call is not bookkeeping. Measured 2026-09-01 on one instance
           (Service Manager 2025.3 — one instance, one date, so it may not
           generalise), ending a fresh ticket's open type-20 *Traitement
           Operation* action moved the **ticket** from *En cours* to *Résolu*
           and spawned a new open type-1 *Validation Self Service* action
           (2 tickets, 2/2). Controls the same day and the next showed the
           opposite for an action the caller had created: ending a type-94
           action left the ticket's status and its action count untouched
           (3 tickets, 3/3). So ending your own action changes that action
           only — it still ends it, which is the whole point, and its text
           then renders — while ending a workflow step also changes the
           ticket. Status ids are per-instance, so treat 12 and 2 as this
           deployment's, not as values to hardcode.

           **This is why ``action_id`` is required.** The vendor documents
           the id-less form as ending *every open action on the ticket*, which
           on a ticket whose only open action is its workflow step means
           resolving it. That form is reachable only through ``end_all=True``;
           a bare ``action_id=None`` raises ``ValueError`` before any request.
           The guard exists because ``Action.action_id`` is legitimately
           ``None`` all over this package — :meth:`create_action`'s response
           carries no id, and a ``fields=`` projection without ``ACTION_ID``
           drops it — so an id a caller thought they had would otherwise
           select the bulk form in silence. Only ``end_all=True`` was measured
           with a single open action, so *how* it behaves against several open
           at once is vendor-documented, not measured here.

        Both dates are passed through as **strings**, because the accepted
        format follows the instance rather than a standard: it is not ISO 8601
        on every deployment, and accepting a ``datetime`` would mean this
        package formatting one on a guess. The date part is the instance's own
        ``DATE_FORMAT`` (readable off any employee record); the time part is
        not covered by that column, so the whole accepted spelling has to be
        measured per deployment. On the verified instance it is
        ``dd/mm/yyyy hh:mm:ss`` — ``dd/mm/yyyy hh:mm`` also works, a bare
        ``dd/mm/yyyy`` lands at midnight, and **ISO 8601 is refused** with HTTP
        590 "Invalid End Date" (measured 2026-09-01/02 on one instance, so it
        may not generalise; ``close_ticket``'s ``end_date`` documents the
        date-only spelling from an earlier measurement of the same instance).

        **Send ``start_date`` explicitly.** Left out, the server derives it as
        ``end_date`` minus ``elapsed_time`` and then minus the instance's UTC
        offset, so the stored start is early by that offset — one hour or two
        depending on DST (measured 2026-09-01 against a +02:00 instance and
        against a February date at +01:00; confirmed to the second 2026-09-02,
        where ``end_date`` 08:14:35 with ``elapsed_time`` 15 stored a start of
        05:59:35). An explicit ``start_date`` is stored faithfully.

        ``elapsed_time`` is a number of **minutes**, and it is neither derived
        nor cross-checked. Measured 2026-09-02 on one instance (one instance,
        one date, so it may not generalise):

        * Omitted entirely, it stays **empty** — the server does not compute it
          from your two dates, so send it if you want one.
        * Sent, it is stored **as given, even when it contradicts the dates**:
          60 was stored against a 15-minute window. Both ``60`` and ``"7"``
          were honoured, so the type does not matter.
        * The one exception: when ``start_date`` **equals** ``end_date``, the
          stored value is ``0`` whatever you send (3/3). A zero-length window
          silently discards it, which is easy to hit by passing the same
          timestamp to both.

        Raises :class:`~easyvista_python_client.EasyvistaValidationError` (HTTP
        590, EV code 2013) with ``Action not found`` when **no open action
        matches** — which is what replaying this call against an
        already-ended action looks like. An earlier version of this package's
        documentation read that message as a profile restriction to raise with
        an administrator; that was wrong, and ending an open action succeeds.

        ``doneby_mail`` attributes the work to somebody other than the
        authenticating account; left out, the API credits that account.

        The returned :class:`Action` carries **only ``href``**: the measured
        response is href-only and names the parent *request*, exactly like
        :meth:`create_action`'s, so ``action_id`` and every other field are
        ``None`` — and because that href's tail is an RFC number rather than a
        numeric id, no id is derived from it either. Re-read with
        :meth:`get_action` to confirm ``END_DATE_UT``; a 200 is not a receipt
        on this API.
        """
        spec, parse = actions_res.build_end_action(
            rfc_number,
            action_id=action_id,
            end_all=end_all,
            end_date=end_date,
            start_date=start_date,
            elapsed_time=elapsed_time,
            doneby_mail=doneby_mail,
            context=self._validation_context,
        )
        return parse(self._transport.send(spec))

    def _resolve_action_body(self, action: Action) -> Action:
        """Return ``action`` with its note text resolved onto the memo that shows.

        Resolves ``DESCRIPTION``, and ``COMMENT`` **only when ``DESCRIPTION``
        comes back empty** -- mirroring what a reader sees. The UI renders one
        text field per action, under a header reading "comment or description":
        ``DESCRIPTION`` when it has text, falling back to ``COMMENT`` when it
        does not (measured in the UI 2026-09-01 on one instance, Service
        Manager 2025.3 -- one instance, one date, so it may not generalise).
        Resolving ``DESCRIPTION`` alone dropped the body of exactly the actions
        a human *can* read, so a ticket exported through
        :meth:`get_ticket_context` disagreed with the ticket on screen.

        Costs two requests per action (item fetch, then the Memo), and a third
        only in that fallback case, so a populated description never pays for
        it. Callers that do not need bodies pass ``resolve_action_bodies=False``.
        Degrades to the unresolved record on 403/404 rather than failing the
        bundle.
        """
        if action.action_id is None:
            return action
        try:
            full = self.get_action(action.action_id)
        except (EasyvistaNotFound, EasyvistaAuthError):
            return action
        if isinstance(full.description, dict):
            href = full.description.get("HREF")
            full.description = self._safe_memo(href) if href else None
        if not full.description and isinstance(full.comment, dict):
            href = full.comment.get("HREF")
            full.comment = self._safe_memo(href) if href else None
        return full

    # --- assets --------------------------------------------------------------
    def create_asset(self, asset: PostAsset) -> Asset:
        spec, parse = assets_res.build_create_asset(
            asset, context=self._validation_context
        )
        return parse(self._transport.send(spec))

    def get_asset(
        self, asset_id: str, *, params: Mapping[str, Any] | None = None
    ) -> Asset:
        spec, parse = assets_res.build_get_asset(
            asset_id, context=self._validation_context
        )
        return parse(self._transport.send(spec, params=params))

    def search_assets(
        self,
        *,
        search: str | None = None,
        fields: str | list[str] | None = None,
        sort: str | None = None,
        max_rows: int | None = None,
        offset: int | None = None,
        params: Mapping[str, Any] | None = None,
    ) -> SearchResult[Asset]:
        if max_rows is None:
            max_rows = self.config.default_max_rows
        spec, parse = assets_res.build_search_assets(
            search=search,
            fields=fields,
            sort=sort,
            max_rows=max_rows,
            offset=offset,
            context=self._validation_context,
        )
        return parse(self._transport.send(spec, params=params))

    def iter_assets(
        self,
        *,
        search: str | None = None,
        fields: str | list[str] | None = None,
        sort: str | None = None,
        page_size: int | None = None,
        max_records: int | None = None,
        params: Mapping[str, Any] | None = None,
    ) -> Iterator[Asset]:
        """Yield assets across pages (see :meth:`iter_tickets`)."""
        if page_size is None:
            page_size = self.config.default_max_rows
        offset = 0
        yielded = 0
        while max_records is None or yielded < max_records:
            result = self.search_assets(
                search=search,
                fields=fields,
                sort=sort,
                max_rows=page_size,
                offset=offset,
                params=params,
            )
            if not result.records:
                return
            for record in result.records:
                yield record
                yielded += 1
                if max_records is not None and yielded >= max_records:
                    return
            if result.next_url is None:
                return
            offset += len(result.records)

    # --- documents -----------------------------------------------------------
    def add_document(
        self, rfc_number: str, *, filename: str, content: bytes
    ) -> Document:
        spec, parse = documents_res.build_add_document(
            rfc_number,
            filename=filename,
            content=content,
            context=self._validation_context,
        )
        return parse(self._transport.send(spec))

    def list_documents(self, rfc_number: str) -> list[Document]:
        spec, parse = documents_res.build_list_documents(
            rfc_number, context=self._validation_context
        )
        return parse(self._transport.send(spec))

    def delete_document(
        self,
        rfc_number: str | None,
        document_id: str | int | Document,
        *,
        path_style: DocumentDeletePathStyle | None = None,
    ) -> None:
        """Remove an attachment from a ticket.

        ``document_id`` is the ``DOCUMENT_ID`` from :meth:`list_documents`, or
        the :class:`Document` itself, whose ``DOCUMENT_ID`` is read off it -- a
        record carrying none raises ``ValueError`` rather than sending a request
        that would address the collection. Returns nothing: the API answers with
        an empty body, so re-list to confirm.

        Two routes exist for this. The instance OpenAPI document read 2026-08-27
        declares DELETE on both ``requests/{rfc}/documents/{id}`` and
        ``documents/{id}``, marking only the second ``deprecated``, so which one
        works is a profile question rather than a routing one. ``path_style``
        picks one for this call and defaults to
        :attr:`EasyvistaConfig.document_delete_path_style`, itself ``"nested"``
        -- the form verified live 2026-08-17 by re-listing the ticket's
        documents afterwards, on one instance, which may not generalise. Under
        ``"top_level"`` the id addresses the record on its own and
        ``rfc_number`` is unused: pass ``None``.
        """
        if isinstance(document_id, Document):
            if not document_id.document_id:
                raise ValueError(
                    "this Document carries no DOCUMENT_ID; pass the id directly"
                )
            document_id = document_id.document_id
        if path_style is None:
            path_style = self.config.document_delete_path_style
        self._transport.send(
            documents_res.build_delete_document(
                rfc_number, document_id, path_style=path_style
            )
        )

    def download_document(self, document: Document | str) -> bytes:
        """Fetch an attachment's bytes.

        ``document`` is a :class:`Document` from :meth:`list_documents` or a raw
        href/path. Raises :class:`ValueError` when the record carries no
        download URL, and :class:`EasyvistaError` when that URL points outside
        the configured instance (see
        :meth:`~easyvista_python_client._sync._transport.BaseTransport.resolve_url`).
        """
        return self._transport.get_bytes(documents_res.download_href(document))

    def stream_document(
        self, document: Document | str, *, chunk_size: int = DEFAULT_STREAM_CHUNK_SIZE
    ) -> Iterator[bytes]:
        """Fetch an attachment's bytes in chunks, without holding the file whole.

        Accepts exactly what :meth:`download_document` accepts -- a
        :class:`Document` from :meth:`list_documents` or a raw href/path -- and
        resolves it identically, refusing a URL outside the configured instance
        for the same reason. Use this when the bytes are on their way somewhere
        else in pieces (a file on disk, a hash, another API) and
        :meth:`download_document` when a single ``bytes`` object is what you
        wanted anyway.

        Called ``stream_`` rather than ``iter_`` on purpose: every ``iter_*``
        method on this client iterates *records*, and this iterates the bytes of
        one document.

        The opposite direction cannot stream at all. :meth:`add_document` sends
        base64 inside a JSON body, so an upload has to materialise the whole
        payload however it is called; the asymmetry is the API's, not an
        oversight here.

        Retrying covers opening the download only. Once the first chunk has been
        handed over the request is committed, and a transport failure raises
        :class:`~easyvista_python_client.exceptions.EasyvistaConnectionError`
        rather than starting again -- starting again would re-deliver bytes the
        caller already has. A partly consumed stream is never resumed, so
        deciding what to do with a mid-stream failure is the caller's. See
        :meth:`~easyvista_python_client._sync._transport.Transport.stream_bytes`.

        Nothing is requested until iteration begins: this is a generator, so
        :class:`ValueError` for a record carrying no download URL and
        :class:`EasyvistaError` for one pointing off the instance both surface
        on the first step rather than at the call.

        **Stopping early:** on the async surface a bare ``break`` leaves the
        response checked out of the connection pool until the event loop's
        async-generator finalizer runs, which is a garbage-collection cycle away
        (measured) -- so a caller that reads only a prefix of many attachments
        under a bounded ``max_connections`` can stall on connections it appears
        to have released. Close the generator instead (``aclose()``, or
        ``contextlib.aclosing``). On the sync surface refcounting releases it at
        the ``break`` and nothing is needed.
        """
        stream = self._transport.stream_bytes(
            documents_res.download_href(document), chunk_size=chunk_size
        )
        # Close the inner generator in a `finally` rather than leaving it to be
        # collected. `stream`'s own `finally` is what releases the response and
        # returns its connection to the pool, and unwinding *this* generator
        # does not reach it on its own -- the loop below simply exits.
        #
        # What this buys, stated precisely: one deferral instead of two. Closing
        # this generator -- explicitly, or by an exception propagating out of it
        # -- now releases the response at once. A bare `break` still defers on
        # the async surface, because unwinding this generator is itself left to
        # the event loop's async-generator finalizer; what the `finally` removes
        # is the *second* wait, for `stream` to become garbage in its own right.
        # On the sync surface refcounting closes it promptly either way.
        # `contextlib.closing`/`aclosing` would say this in one line, but those
        # two names differ by more than a token so the codegen cannot generate
        # the pair; `stream.close()`/`stream.aclose()` it can.
        try:
            for chunk in stream:
                yield chunk
        finally:
            stream.close()

    # --- departments ----------------------------------------------------------
    def get_department(
        self, department_id: str | int, *, params: Mapping[str, Any] | None = None
    ) -> Department:
        spec, parse = departments_res.build_get_department(
            department_id, context=self._validation_context
        )
        return parse(self._transport.send(spec, params=params))

    def search_departments(
        self,
        *,
        search: str | None = None,
        fields: str | list[str] | None = None,
        sort: str | None = None,
        max_rows: int | None = None,
        offset: int | None = None,
        params: Mapping[str, Any] | None = None,
    ) -> SearchResult[Department]:
        if max_rows is None:
            max_rows = self.config.default_max_rows
        spec, parse = departments_res.build_search_departments(
            search=search,
            fields=fields,
            sort=sort,
            max_rows=max_rows,
            offset=offset,
            context=self._validation_context,
        )
        return parse(self._transport.send(spec, params=params))

    def iter_departments(
        self,
        *,
        search: str | None = None,
        fields: str | list[str] | None = None,
        sort: str | None = None,
        page_size: int | None = None,
        max_records: int | None = None,
        params: Mapping[str, Any] | None = None,
    ) -> Iterator[Department]:
        """Yield departments across pages (see :meth:`iter_tickets`)."""
        if page_size is None:
            page_size = self.config.default_max_rows
        offset = 0
        yielded = 0
        while max_records is None or yielded < max_records:
            result = self.search_departments(
                search=search,
                fields=fields,
                sort=sort,
                max_rows=page_size,
                offset=offset,
                params=params,
            )
            if not result.records:
                return
            for record in result.records:
                yield record
                yielded += 1
                if max_records is not None and yielded >= max_records:
                    return
            if result.next_url is None:
                return
            offset += len(result.records)

    def get_department_comment(
        self,
        department_id: str | int,
        *,
        memo_field: str = DEPARTMENT_MEMO_FIELD,
    ) -> str | None:
        """Return the department's note (a Memo).

        ``""`` for an empty note; propagates transport errors so a 403/404 is
        distinguishable from an empty note (uses the generic ``resolve_memo``).

        ``memo_field`` is the last path segment of
        ``GET departments/{id}/{comment}``. In the instance OpenAPI document
        read 2026-08-27 that segment is a path *parameter* named ``comment``,
        not a literal -- the sibling ``GET requests/{rfc_number}/{comment}``
        describes the same parameter as "Memo field type, could be comment,
        description". So the route selects a memo column, and the default is
        only the column the verified instance carries. Same idea as
        :meth:`get_ticket_context`'s ``memo_fields``.
        """
        return self.resolve_memo(f"departments/{department_id}/{memo_field}")

    def find_departments(
        self,
        name: str,
        *,
        limit: int | None = None,
        by: str | Sequence[str] = "auto",
    ) -> list[Department]:
        """Resolve departments by a fuzzy, language-agnostic ``name``.

        Fast path (server-side, exact): ``by`` names the columns to try, in
        order, and the first one that returns records wins. ``"auto"`` tries
        ``DEPARTMENT_CODE`` alone for a name containing anything but digits,
        and ``DEPARTMENT_CODE`` then ``DEPARTMENT_ID`` for an all-digit one --
        code first, because a department whose code is all digits would
        otherwise be looked up as an id and a different department would come
        back with no error. That costs one extra round trip when the digits are
        an id and not a code. Pass a single column name to pin one lookup
        (``by="DEPARTMENT_ID"``), an ordered sequence to choose your own, or an
        empty sequence to skip the fast path.

        Fuzzy fallback: scan every department and match ``name`` -- normalized
        so ``"Acme Corp" == "ACME-CORP" == "acmecorp"``, and accent- and
        case-folded so ``"Systemes"`` matches the same name written with its
        accents -- as a substring of any string field. ``limit`` caps the result
        count. Returns ``[]`` on no match.

        A ``name`` that cannot be expressed in EasyVista's search grammar (see
        :func:`~easyvista_python_client.is_safe_ev_value`) skips the server fast
        path and falls back directly to the client-side scan, so this method
        returns correct results rather than raising.
        """
        # The server fast path is only an optimization, and a name that cannot be
        # expressed server-side would otherwise be interpolated raw — where a ','
        # silently widens the result set. Such names skip straight to the local
        # scan below, which handles any characters.
        #
        # `isinstance(by, str)` is checked BEFORE the sequence branch, or
        # `by="DEPARTMENT_ID"` would be read as eleven single-character columns.
        if by == "auto":
            columns: tuple[str, ...] = (
                DEPARTMENT_NAME_COLUMNS if name.isdigit() else ("DEPARTMENT_CODE",)
            )
        elif isinstance(by, str):
            columns = (by,)
        else:
            columns = tuple(by)
        if is_safe_ev_value(name):
            for column in columns:
                search = ev_equals_filter(column, name)
                if search is None:
                    continue
                fast = self.search_departments(search=search)
                if fast.records:
                    return fast.records if limit is None else fast.records[:limit]
        needle = _normalize_name(name)
        if not needle:
            return []
        matches: list[Department] = []
        for dept in self.iter_departments():
            if _department_matches(dept, needle):
                matches.append(dept)
                if limit is not None and len(matches) >= limit:
                    break
        return matches

    def create_department(self, department: PostDepartment) -> Department:
        """Create a department (provisional; profile-gated — spec open item O-DIR-2)."""
        spec, parse = departments_res.build_create_department(
            department, context=self._validation_context
        )
        return parse(self._transport.send(spec))

    def update_department(
        self, department_id: str | int, update: DepartmentUpdate
    ) -> Department:
        """Update a department via PUT (provisional; profile-gated)."""
        spec, parse = departments_res.build_update_department(
            department_id, update, context=self._validation_context
        )
        return parse(self._transport.send(spec))

    # --- employees ------------------------------------------------------------
    def get_employee(
        self, employee_id: str | int, *, params: Mapping[str, Any] | None = None
    ) -> Employee:
        spec, parse = employees_res.build_get_employee(
            employee_id, context=self._validation_context
        )
        return parse(self._transport.send(spec, params=params))

    def search_employees(
        self,
        *,
        search: str | None = None,
        fields: str | list[str] | None = None,
        sort: str | None = None,
        max_rows: int | None = None,
        offset: int | None = None,
        params: Mapping[str, Any] | None = None,
    ) -> SearchResult[Employee]:
        if max_rows is None:
            max_rows = self.config.default_max_rows
        spec, parse = employees_res.build_search_employees(
            search=search,
            fields=fields,
            sort=sort,
            max_rows=max_rows,
            offset=offset,
            context=self._validation_context,
        )
        return parse(self._transport.send(spec, params=params))

    def iter_employees(
        self,
        *,
        search: str | None = None,
        fields: str | list[str] | None = None,
        sort: str | None = None,
        page_size: int | None = None,
        max_records: int | None = None,
        params: Mapping[str, Any] | None = None,
    ) -> Iterator[Employee]:
        """Yield employees across pages (see :meth:`iter_tickets`)."""
        if page_size is None:
            page_size = self.config.default_max_rows
        offset = 0
        yielded = 0
        while max_records is None or yielded < max_records:
            result = self.search_employees(
                search=search,
                fields=fields,
                sort=sort,
                max_rows=page_size,
                offset=offset,
                params=params,
            )
            if not result.records:
                return
            for record in result.records:
                yield record
                yielded += 1
                if max_records is not None and yielded >= max_records:
                    return
            if result.next_url is None:
                return
            offset += len(result.records)

    def create_employee(self, employee: PostEmployee) -> Employee:
        """Create an employee (provisional; profile-gated — spec open item O-DIR-2)."""
        spec, parse = employees_res.build_create_employee(
            employee, context=self._validation_context
        )
        return parse(self._transport.send(spec))

    def update_employee(
        self, employee_id: str | int, update: EmployeeUpdate
    ) -> Employee:
        """Update an employee via PUT (provisional; profile-gated)."""
        spec, parse = employees_res.build_update_employee(
            employee_id, update, context=self._validation_context
        )
        return parse(self._transport.send(spec))

    # --- aggregated context --------------------------------------------------
    def resolve_memo(self, href: str) -> str | None:
        """Fetch a Memo/link field's text from its sub-resource.

        ``href`` may be a full URL (as returned in a record's link) or a
        resource-relative path. Propagates transport errors so callers can tell
        an empty Memo (``""``) from a 403/404.
        """
        path = href
        root = self.config.api_root
        if path.startswith(root):
            path = path[len(root) :]
        path = path.lstrip("/")
        field = path.rstrip("/").rsplit("/", 1)[-1]
        return parse_memo(self._transport.send(RequestSpec("GET", path)), field)

    # --- instance discovery --------------------------------------------------
    def get_api_spec(self, *, path: str = SWAGGER_PATH) -> dict[str, Any]:
        """Fetch the instance's own OpenAPI description.

        Returns the parsed document: ``info`` (``description`` carries the
        product version, e.g. ``"Easyvista Service Manager REST API - 2025.3"``),
        ``paths`` -- the routes *this* deployment exposes -- and ``components``.

        **Trust the two halves differently.** ``paths`` is tier 2:
        authoritative for this deployment, and the reason :meth:`discover` reads
        urgencies at ``urgency`` rather than at the vendor-documented
        ``urgencies``. ``components.schemas`` is tier 3: example-derived and
        illustrative only. It declares ``required: []`` throughout and lists
        whichever private ``E_*`` columns the example happened to carry, so a
        field appearing in a schema is not a requirement and a field missing
        from one is not forbidden.

        .. warning::

           **A GET to this route answers HTTP 201, not 200** (measured
           2026-08-27 against one instance; it may not generalise). This client
           is unaffected -- its transport treats any 2xx as success -- but code
           you write beside it that gates on ``response.status_code == 200``
           skips this document in silence and concludes the instance publishes
           no spec. The route is ``{api_root}/swagger``, that is
           ``/api/{api_version}/{account}/swagger``; the bare-host
           ``{server}/swagger`` answers 403.

        ``path`` is a keyword so a deployment that publishes its description
        elsewhere is reachable without patching this package; the default is the
        route measured on the verified instance.

        Raises like any other read -- a 401/403 becomes ``EasyvistaAuthError``
        rather than an empty document, because an empty document and a denied
        one must not look alike.
        """
        spec, parse = discovery_res.build_get_api_spec(path)
        return parse(self._transport.send(spec))

    def list_reference_table(
        self,
        path: str,
        *,
        search: str | None = None,
        fields: Iterable[str] | str | None = None,
        sort: str | None = None,
        max_rows: int | None = None,
        offset: int | None = None,
        params: Mapping[str, Any] | None = None,
    ) -> SearchResult[GenericRecord]:
        """Read any of the instance's list routes into column-free records.

        ``path`` is resource-relative: ``"status"``, ``"urgency"``,
        ``"catalog-requests"``, ``"locations"``, ``"groups"``, ``"slas"``,
        ``"domains"``, ``"suppliers"``. Call :meth:`get_api_spec` and read
        ``["paths"]`` to see which of them your deployment actually declares --
        this package wraps about ten of that instance's hundred routes, and this
        method is how you reach the rest of the read-only ones.

        Records come back as :class:`GenericRecord`, which declares **no
        columns**: nothing here assumes a schema, because the OpenAPI schemas for
        these routes are tier 3 and one of them (``/status``) is visibly wrong.
        Read a column by its API name from ``record.model_dump(by_alias=True)``,
        or let ``record.reference(name)`` and ``record.classify_fields()`` do it
        generically.

        The four query parameters the spec declares on these routes are
        ``max_rows``, ``sort``, ``fields`` and ``search``; each is sent only when
        passed, so the default call is the bare route. ``offset`` is
        vendor-documented for the requests list and merely *inferred* here, so it
        too is sent only when asked for. ``params`` is merged last and wins, for
        anything this signature does not model.

        **A 403 propagates as ``EasyvistaAuthError``; it does not become
        ``[]``.** An empty reference table is a legitimate answer on a lightly
        configured instance, so collapsing a denial into an empty list would make
        "you may not read this" indistinguishable from "there is nothing here" --
        and a caller that builds a status map from an empty list concludes the
        instance has no statuses and hardcodes a constant instead.
        :meth:`describe_instance` is the layer that swallows the denial, and it
        names the gap in ``.unavailable`` so the loss stays visible.

        Note what a 403 does *not* tell you: this API answers **403 rather than
        404 for a route that does not exist**, so a denied table and a misspelled
        path are the same exception. ``get_api_spec()["paths"]`` distinguishes
        them.

        The result is a :class:`SearchResult`, not a list, so truncation is
        detectable: compare ``.record_count`` with ``.total_record_count`` before
        treating a page as the whole table. A route that answers with a bare
        object and no envelope reports both as the number of records parsed, in
        which case truncation cannot be detected from the response at all.
        """
        spec, parse = discovery_res.build_list_reference_table(
            path,
            search=search,
            fields=fields,
            sort=sort,
            max_rows=max_rows,
            offset=offset,
            params=params,
            context=self._validation_context,
        )
        return parse(self._transport.send(spec))

    def _sample_records(
        self,
        source: ReferenceSource,
        *,
        sample_size: int,
        search: str | None,
        action_sample_tickets: int,
        languages: Sequence[str],
    ) -> list[dict[str, Any]]:
        """Sampled records carrying ``source``, as by-alias dumps.

        Tickets are one sweep. Actions need a ticket sweep first, because the
        actions list is filtered per ticket -- so the first
        ``action_sample_tickets`` sampled RFC numbers are swept for their
        actions. That sweep is always bounded: the ``offset``/``@next`` contract
        is unverified on the actions endpoint (see :meth:`iter_actions`), and an
        instance that ignores ``offset`` would otherwise repeat page one forever.
        """
        projection = sample_fields(source, languages=languages)
        if source.sample_from != "actions":
            return [
                t.model_dump(by_alias=True)
                for t in self.iter_tickets(
                    search=search, fields=projection, max_records=sample_size
                )
            ]
        rfcs = [
            t.rfc_number
            for t in self.iter_tickets(
                search=search,
                fields=["RFC_NUMBER"],
                max_records=max(action_sample_tickets, 1),
            )
            if t.rfc_number
        ]
        records: list[dict[str, Any]] = []
        for rfc in rfcs:
            records.extend(
                [
                    a.model_dump(by_alias=True)
                    for a in self.iter_actions(
                        rfc, fields=projection, max_records=sample_size
                    )
                ]
            )
        return records

    def discover(
        self,
        name: str,
        *,
        strategy: str = "auto",
        reference_path: str | None = None,
        sample_size: int = 200,
        action_sample_tickets: int = 5,
        search: str | None = None,
        reference_search: str | None = None,
        max_rows: int | None = None,
        with_guid: bool = True,
        languages: Sequence[str] = DEFAULT_LANGUAGE_ORDER,
    ) -> list[DiscoveredReference]:
        """Find the ids, labels and codes one reference uses on this instance.

        ``name`` is a reference name: ``"STATUS"``, ``"URGENCY"``,
        ``"CATALOG_REQUEST"``, ``"LOCATION"``, ``"DEPARTMENT"``, ``"SLA"``,
        ``"GROUP"``, ``"IMPACT"``, ``"SEVERITY"``, ``"ORIGIN"``,
        ``"ACTION_TYPE"`` -- or any other column, including a custom ``e_*``
        one, which is read off sampled tickets.

        ``strategy``:

        * ``"auto"`` (default) -- read the reference table when this
          deployment's OpenAPI declares a route for the name, and fall back to
          sampling if that route is denied. Names with no route go straight to
          sampling and cost no wasted request.
        * ``"reference"`` -- the table only. A denial raises. A name with no
          route and no ``reference_path`` raises ``ValueError`` rather than
          quietly sampling.
        * ``"sample"`` -- sampling only; no reference route is called.

        **Four names have no route at all** on the verified instance:
        ``IMPACT``, ``SEVERITY``, ``ORIGIN`` and ``ACTION_TYPE``. That is a
        topology fact read from the spec's ``paths`` (tier 2), not a 403 someone
        measured, so no strategy reaches a table for them. What comes back is
        the ids *in use* in the sample: an id configured but unused is
        invisible, and a ``count`` is a sample count, never a population one.

        ``reference_path`` overrides the route -- the escape hatch for a
        deployment that spells a table differently. Urgencies are the live
        example: the vendor documents ``GET /urgencies`` while the verified
        instance declares ``GET /urgency``, so the default is the singular one
        and ``reference_path="urgencies"`` reaches the other.

        ``search`` filters the **sample** (a ticket or action filter -- see the
        ``easyvista-search-syntax`` skill, and note that unparseable syntax
        returns the whole table rather than erroring). ``reference_search``
        filters the **table**. ``sample_size`` caps records fetched client-side;
        ``max_rows`` caps the table page.

        **``STATUS`` also gets its GUID, and only from a sample.** A
        ``STATUS_GUID`` is not searchable and no reference read returns one, but
        every ticket's nested ``STATUS`` object carries it -- so with
        ``with_guid`` on (the default) discovering ``STATUS`` additionally
        sweeps tickets, reads ``record["STATUS"]["STATUS_GUID"]``, and merges
        each guid onto the matching id. That costs one extra ticket sweep even
        under ``strategy="reference"``; pass ``with_guid=False`` to skip it. The
        GUID is what :meth:`set_status` and :meth:`close_ticket` address a
        status by -- a ``STATUS_ID`` will not work there -- so this is usually
        the value you came for. A status no sampled ticket currently holds keeps
        ``guid=None``: the sample cannot reach it.

        Everything returned is per-deployment configuration. Ids are not
        portable; ``8`` is *Cloture* and ``12`` is *En cours* on the verified
        instance -- adjacent numbers, opposite meanings. Resolve at start-up and
        fail loudly, do not freeze a constant.
        """
        if strategy not in ("auto", "reference", "sample"):
            raise ValueError(
                f"strategy={strategy!r} is not one of 'auto', 'reference', "
                "'sample'"
            )
        source = resolve_source(name, reference_path=reference_path)
        found: list[DiscoveredReference] = []

        if strategy == "reference" and source.reference_path is None:
            raise ValueError(
                f"{source.name} has no reference route in this deployment's "
                "OpenAPI paths, so strategy='reference' cannot read one. Pass "
                "reference_path= if your deployment declares one, or use "
                "strategy='sample' (which is what 'auto' does here)."
            )

        if strategy != "sample" and source.reference_path is not None:
            try:
                page = self.list_reference_table(
                    source.reference_path, search=reference_search, max_rows=max_rows
                )
            except EasyvistaAuthError:
                if strategy == "reference":
                    raise
                page = None
            if page is not None:
                found = [
                    reference_from_table_row(
                        row.model_dump(by_alias=True), source, languages=languages
                    )
                    for row in page.records
                ]

        needs_sample = not found and strategy != "reference"
        wants_guid = with_guid and bool(source.guid_field)
        if needs_sample or wants_guid:
            records = self._sample_records(
                source,
                sample_size=sample_size,
                search=search,
                action_sample_tickets=action_sample_tickets,
                languages=languages,
            )
            if needs_sample:
                found = references_from_sample(
                    records, source, languages=languages
                )
            if wants_guid:
                found = merge_guids(found, guids_from_sample(records, source))
        return found

    def describe_instance(
        self,
        *,
        names: Sequence[str] = DEFAULT_DISCOVERY_NAMES,
        strategy: str = "auto",
        reference_paths: Mapping[str, str] | None = None,
        sample_size: int = 200,
        action_sample_tickets: int = 5,
        search: str | None = None,
        max_rows: int | None = None,
        include_spec: bool = True,
        languages: Sequence[str] = DEFAULT_LANGUAGE_ORDER,
    ) -> InstanceProfile:
        """Profile this deployment: its version, its routes, and its reference ids.

        One call that answers "what do I have to pass to create a ticket
        *here*". Returns an :class:`InstanceProfile`; read its docstring for what
        discovery cannot reach, which is as important as what it can.

        **No part can fail the whole.** Each fetch is attempted independently; an
        EasyVista error is recorded in ``.unavailable`` -- keyed by ``"spec"`` or
        by the reference name, with a first token of ``denied``, ``failed``,
        ``no-route``, ``empty`` or ``truncated`` -- and the remaining parts still
        run. Nothing is invented for a part that failed: its entry in
        ``.references`` is an empty list, and the reason is in ``.unavailable``.
        Read that dict before concluding an instance has no statuses; a total
        outage looks exactly like a bare instance except that every gap is named.

        Only ``EasyvistaError`` and its subclasses are caught. A bug inside this
        package therefore still propagates rather than being buried as a fake
        instance limitation.

        **It samples once, not once per name.** Every name that needs sampling is
        projected into a single ticket sweep of at most ``sample_size`` records,
        and the names that live on actions come from one action sweep over the
        first ``action_sample_tickets`` of those tickets. So the cost is roughly
        one spec read, one read per declared reference table, and two short
        sweeps -- all GETs, nothing written.

        ``reference_paths`` overrides individual routes by name (e.g.
        ``{"URGENCY": "urgencies"}``); ``names`` narrows the work;
        ``include_spec=False`` skips the OpenAPI read, at the cost of leaving
        ``version`` and ``spec_paths`` empty. Every default is the value that
        works on the verified instance today.
        """
        overrides = dict(reference_paths or {})
        unavailable: dict[str, str] = {}
        version: str | None = None
        spec_paths: tuple[str, ...] = ()

        if include_spec:
            try:
                document = self.get_api_spec()
            except EasyvistaError as exc:
                unavailable["spec"] = _unavailable_reason(exc)
            else:
                info = document.get("info")
                if isinstance(info, dict):
                    description = info.get("description") or info.get("title")
                    version = description if isinstance(description, str) else None
                paths = document.get("paths")
                if isinstance(paths, dict):
                    spec_paths = tuple(str(p) for p in paths)

        sources = [
            resolve_source(name, reference_path=overrides.get(name.strip().upper()))
            for name in names
        ]

        # One sweep per surface, shared by every name that needs it, rather than
        # one sweep per name -- which would be eleven.
        ticket_projection: list[str] = []
        action_projection: list[str] = []
        for source in sources:
            projection = sample_fields(source, languages=languages)
            target = (
                action_projection
                if source.sample_from == "actions"
                else ticket_projection
            )
            target.extend(c for c in projection if c not in target)

        tickets: list[dict[str, Any]] = []
        actions: list[dict[str, Any]] = []
        rfcs: list[str] = []
        try:
            tickets = [
                t.model_dump(by_alias=True)
                for t in self.iter_tickets(
                    search=search, fields=ticket_projection, max_records=sample_size
                )
            ]
            rfcs = [
                str(t["RFC_NUMBER"])
                for t in tickets[: max(action_sample_tickets, 0)]
                if t.get("RFC_NUMBER")
            ]
        except EasyvistaError as exc:
            unavailable["sample:tickets"] = _unavailable_reason(exc)

        if action_projection and rfcs:
            try:
                for rfc in rfcs:
                    actions.extend(
                        [
                            a.model_dump(by_alias=True)
                            for a in self.iter_actions(
                                rfc, fields=action_projection, max_records=sample_size
                            )
                        ]
                    )
            except EasyvistaError as exc:
                unavailable["sample:actions"] = _unavailable_reason(exc)

        references: dict[str, list[DiscoveredReference]] = {}
        for source in sources:
            found: list[DiscoveredReference] = []
            if source.reference_path is None:
                unavailable[source.name] = (
                    "no-route this deployment's OpenAPI declares no list route "
                    "for it, so the ids below are only those in use in the "
                    "sample"
                )
            elif strategy != "sample":
                try:
                    page = self.list_reference_table(
                        source.reference_path, max_rows=max_rows
                    )
                except EasyvistaError as exc:
                    unavailable[source.name] = _unavailable_reason(exc)
                else:
                    found = [
                        reference_from_table_row(
                            row.model_dump(by_alias=True), source, languages=languages
                        )
                        for row in page.records
                    ]
                    if page.total_record_count > page.record_count:
                        unavailable[source.name] = (
                            f"truncated {page.record_count} of "
                            f"{page.total_record_count} rows read"
                        )
            if not found:
                records = actions if source.sample_from == "actions" else tickets
                found = references_from_sample(records, source, languages=languages)
            if source.guid_field:
                found = merge_guids(found, guids_from_sample(tickets, source))
            if not found and source.name not in unavailable:
                unavailable[source.name] = (
                    "empty the read succeeded and returned nothing"
                )
            references[source.name] = found

        return InstanceProfile(
            api_root=self.config.api_root,
            version=version,
            spec_paths=spec_paths,
            references=references,
            unavailable=unavailable,
        )

    def get_ticket_context(
        self,
        rfc_number: str,
        *,
        resolve_action_bodies: bool = True,
        memo_fields: Sequence[str] = ("description", "comment"),
    ) -> TicketContext:
        """Fetch a ticket plus its resolved narrative content as a bundle.

        Resolves the href-only ``description``/``comment`` sub-resources and
        lists actions/documents. Missing sub-resources (404) or
        profile-restricted lists (403) degrade to ``None`` / ``[]`` rather than
        failing the whole call.

        ``memo_fields`` names which Memo sub-resources to resolve, defaulting to
        the two EasyVista populates by default. The API models the memo name as
        a path segment (``GET /requests/{rfc}/{memo}``), so an instance
        configured with a different body memo is reached by naming it here
        (tier 2 -- ``docs/vendor-api-reference.md``: declared in the instance's
        OpenAPI ``paths``). Every resolved memo lands in
        :attr:`TicketContext.memos`; ``description`` and ``comment``
        additionally keep their own attributes, and are ``None`` when not
        requested.

        Pass a tuple or list, not a bare string: ``str`` itself satisfies
        ``Sequence[str]``, so ``memo_fields="solution"`` type-checks and then
        iterates individual characters, issuing one nonsense sub-resource
        request per letter instead of the one you meant.

        ``resolve_action_bodies`` (default on) additionally fetches each action
        item-level and resolves its note text, because ``list_actions`` does not
        return it — without this the rendered Markdown has empty action bodies.
        It costs two extra requests per action; pass ``False`` to skip it when
        you only need the action list.

        **The action log is capped at one page.** It comes from
        :meth:`list_actions`, which returns at most ``config.default_max_rows``
        actions and does not paginate, so on a busy ticket
        :attr:`TicketContext.actions` — and therefore
        :meth:`TicketContext.to_markdown`'s rendered log — is silently truncated
        with no error. Raise ``default_max_rows`` if completeness matters.

        On the async surface the independent requests (the requested memos
        plus the actions and documents lists) are issued concurrently, in up
        to three waves; on the sync surface they run one after another in
        source order, costing ``len(memo_fields) + 2 + 2N`` serial round
        trips for a ticket with ``N`` actions. Measured against a live
        instance on a 19-action ticket with the default two-memo
        ``memo_fields``: 5.31s concurrent, 14.65s serial.

        Peak in-flight on the async surface is ``len(memo_fields) + 2``
        sub-resource requests, then up to ``_ACTION_FANOUT`` action-body
        resolutions; the sync surface issues one request at a time
        throughout. On a hard failure (5xx, a transport error) siblings
        already in flight on the async surface run to completion before the
        error propagates, so a failing call there can issue more requests
        than the sequential surface does. That is the deliberate trade:
        settling every sibling is what keeps an orphaned request from
        outliving the call that issued it, and what makes the exception a
        caller sees the one the sequential surface would have raised rather
        than whichever branch happened to fail soonest.
        """
        # Issued first, and deliberately outside the fan-out: this is the one
        # call with no fallback, so a wrong RFC number should cost one request,
        # not five.
        ticket = self.get_ticket(rfc_number)

        degraded: set[str] = set()

        # The asymmetry between these two except clauses is real and
        # load-bearing: the memos degrade on 404 *and* 403, while the two list
        # calls catch EasyvistaAuthError ONLY, so a 404 there still fails the
        # bundle. Do not tidy them into a shared handler. Each records its own
        # swallow inside its own clause, which keeps that asymmetry visible
        # rather than hiding it behind a helper.
        def _actions() -> list[Action]:
            try:
                return self.list_actions(rfc_number)
            except EasyvistaAuthError as exc:
                degraded.add(_degraded_entry("actions", exc))
                return []

        def _documents() -> list[Document]:
            try:
                return self.list_documents(rfc_number)
            except EasyvistaAuthError as exc:
                degraded.add(_degraded_entry("documents", exc))
                return []

        memo_results = settle(
            *(
                self._safe_memo(
                    f"requests/{rfc_number}/{name}",
                    degraded=degraded,
                    branch=f"memo:{name}",
                )
                for name in memo_fields
            ),
            _actions(),
            _documents(),
        )
        memos = dict(
            zip(memo_fields, memo_results[: len(memo_fields)], strict=True)
        )
        actions, documents = memo_results[len(memo_fields) :]

        if resolve_action_bodies:
            actions = self._resolve_action_bodies(actions)

        return TicketContext(
            ticket=ticket,
            description=memos.get("description"),
            comment=memos.get("comment"),
            actions=actions,
            documents=documents,
            memos=memos,
            degraded=frozenset(degraded),
        )

    def _resolve_action_bodies(self, actions: list[Action]) -> list[Action]:
        """Resolve every action's note text, preserving ``list_actions`` order.

        On the async surface the resolutions are issued concurrently, at most
        ``_ACTION_FANOUT`` in flight; on the sync surface they run one after
        another and the bound is inert. ``settle`` preserves source order on
        either surface, so the returned list matches ``list_actions`` order
        whichever resolution finishes first.

        The limiter is built **here, per call**. On the async surface it is an
        ``asyncio.Semaphore``, which binds to the first event loop that
        *contends* it -- an uncontended acquire never touches the loop at all --
        so one stored on the client or at module level would pass every
        low-traffic test and then raise ``RuntimeError: bound to a different
        event loop`` the first time a second loop contended it, i.e. in
        production under load (measured on 3.10). A per-call limiter cannot do
        that.
        """
        limiter = Semaphore(_ACTION_FANOUT)

        def _one(action: Action) -> Action:
            with limiter:
                return self._resolve_action_body(action)

        resolved: list[Action] = settle(*(_one(a) for a in actions))
        return resolved

    def get_department_context(
        self,
        department_id: str | int,
        *,
        recent_tickets: int = 10,
        recent_tickets_sort: str | None = RECENT_TICKETS_SORT,
        ticket_fields: str | Sequence[str] | None = RECENT_TICKET_FIELDS,
        employee_fields: str | Sequence[str] | None = None,
        asset_fields: str | Sequence[str] | None = None,
        dimensions: Sequence[str] | None = None,
        languages: Sequence[str] = DEFAULT_LANGUAGE_ORDER,
        statistics_max_records: int | None = 100,
        memo_fields: Sequence[str] = DEPARTMENT_NOTE_FIELDS,
        include_statistics: bool = True,
        include_assets: bool = True,
        resolve_manager: bool = True,
        include_note: bool = True,
    ) -> DepartmentContext:
        """Assemble a department plus its employees, manager, note, tickets and assets.

        Only :meth:`get_department` is required; every related part is wrapped
        so a 403/404 degrades it to ``[]`` / ``None`` / ``0``, and records
        itself in ``DepartmentContext.degraded`` so the degradation is visible
        rather than silent. The flags trim the heavier related calls. Tickets
        and assets filter on ``DEPARTMENT_ID:"<id>"``.

        Every value this method samples with is a keyword, and every default is
        what it sampled with before -- with one exception, ``ticket_fields``.

        ``recent_tickets_sort`` is the sort token for the recent-ticket page,
        defaulting to ``RECENT_TICKETS_SORT`` (``"RFC_NUMBER DESC"``). That is
        **descending RFC_NUMBER**, which is newest-first only where RFC numbers
        are issued monotonically: it is a varchar, so the sort orders by the
        request-type prefix letter before the date, and on an instance issuing
        more than one prefix every ``R...`` outranks every ``I...``. The default
        is deliberately not a date column: an unhonoured sort token is silently
        ignored by this API and degrades to the server's default order with no
        error (see :meth:`iter_tickets`), so a date default would swap a
        disclosed flaw for a hidden one, and ``RFC_NUMBER DESC`` is the one
        token this repository has actually measured for this call. Pass
        ``recent_tickets_sort="CREATION_DATE_UT DESC"`` on a deployment where
        you have checked that a date sort is honoured, or ``None`` to send no
        sort at all -- in which case "recent" means whatever order the server
        returns.

        ``ticket_fields`` is the ``fields=`` projection for the recent tickets.
        Its default, ``RECENT_TICKET_FIELDS``, **projects** -- unlike every
        other default here, this is a change from the previous behaviour, and
        it is deliberate. Sending no projection is not neutral: on the verified
        instance the default list projection returns ``TITLE`` present but empty
        (tier 4 -- measured on one instance, 400 tickets scanned, zero with a
        populated title; it may not generalise), so ``recent_tickets[i].title``
        was ``None`` for every caller. Projecting also narrows what else comes
        back: pass ``ticket_fields=None`` to send no projection, or your own
        list to widen it.

        ``employee_fields`` and ``asset_fields`` project the employee and asset
        sweeps; both default to ``None``, which sends no projection, as before.

        ``statistics_max_records`` caps the statistics sample and defaults to
        100 -- the cap ``ticket_statistics`` applies, which this call inherited
        silently before. The sample is unsorted, so it is not the department's
        first hundred tickets by any ordering; when it truncates,
        ``ticket_statistics.truncated`` is ``True`` and ``population_total``
        carries the server's own count. ``ticket_count`` remains the true total
        and is unaffected by this cap. Pass ``None`` to aggregate every ticket.

        ``memo_fields`` names which Memo sub-resources to resolve, defaulting to
        ``("comment_department",)``. The API models a memo name as a path
        segment (``GET departments/{id}/{memo}``) (tier 2 --
        ``docs/vendor-api-reference.md``: declared in the instance's OpenAPI
        ``paths``), so a deployment carrying its directory note elsewhere is
        reached by naming it here. Every resolved memo lands in
        ``DepartmentContext.memos``; ``note`` is the first one that came back
        with text. ``include_note=False`` skips all of them. Pass a tuple or
        list, not a bare string: ``str`` itself satisfies ``Sequence[str]``, so
        a bare name would be iterated one character at a time, one nonsense
        request per letter.

        On the async surface the seven independent branches are issued
        concurrently, costing two waves instead of eight serial steps; on the
        sync surface they run one after another in source order. The three
        paginating branches still page serially within themselves on either
        surface -- offset pagination cannot be parallelised -- but on the async
        surface they page alongside each other.
        """
        # Issued first, outside the fan-out: the department itself, plus the
        # search guard. Kept outside because the manager lookup needs
        # `department.manager_id`, and because a bad department_id should cost
        # one request, not seven.
        department = self.get_department(department_id)
        search = ev_equals_filter("DEPARTMENT_ID", department_id)
        if search is None:
            raise ValueError("department_id is required to build a department context")

        degraded: set[str] = set()
        ticket_projection = _as_fields(ticket_fields)

        # Every branch here degrades on both 403 and 404, unlike the ticket
        # bundle above, whose two list calls catch EasyvistaAuthError only. The
        # `include_*` / `resolve_*` flags sit inside the branch so a disabled one
        # costs no request at all, exactly as a plain `if` around the call would.
        def _employees() -> list[Employee]:
            try:
                return [
                    e
                    for e in self.iter_employees(
                        search=search, fields=_as_fields(employee_fields)
                    )
                ]
            except (EasyvistaAuthError, EasyvistaNotFound) as exc:
                degraded.add(_degraded_entry("employees", exc))
                return []

        def _manager() -> Employee | None:
            if not resolve_manager or department.manager_id is None:
                return None
            try:
                return self.get_employee(department.manager_id)
            except (EasyvistaAuthError, EasyvistaNotFound) as exc:
                degraded.add(_degraded_entry("manager", exc))
                return None

        def _memos() -> dict[str, str | None]:
            if not include_note:
                return {}
            return {
                name: self._safe_memo(
                    f"departments/{department_id}/{name}",
                    degraded=degraded,
                    branch=f"memo:{name}",
                )
                for name in memo_fields
            }

        def _ticket_count() -> int:
            try:
                return self.count_tickets(search=search)
            except (EasyvistaAuthError, EasyvistaNotFound) as exc:
                degraded.add(_degraded_entry("ticket_count", exc))
                return 0

        def _recent() -> list[Request]:
            try:
                return [
                    t
                    for t in self.iter_tickets(
                        search=search,
                        fields=ticket_projection,
                        sort=recent_tickets_sort,
                        max_records=recent_tickets,
                    )
                ]
            except (EasyvistaAuthError, EasyvistaNotFound) as exc:
                degraded.add(_degraded_entry("recent_tickets", exc))
                return []

        def _statistics() -> TicketStatistics | None:
            if not include_statistics:
                return None
            try:
                return self.ticket_statistics(
                    search=search,
                    dimensions=dimensions,
                    languages=languages,
                    max_records=statistics_max_records,
                )
            except (EasyvistaAuthError, EasyvistaNotFound) as exc:
                degraded.add(_degraded_entry("statistics", exc))
                return None

        def _assets() -> list[Asset]:
            if not include_assets:
                return []
            try:
                return [
                    a
                    for a in self.iter_assets(
                        search=search, fields=_as_fields(asset_fields)
                    )
                ]
            except (EasyvistaAuthError, EasyvistaNotFound) as exc:
                degraded.add(_degraded_entry("assets", exc))
                return []

        (
            employees,
            manager,
            memos,
            ticket_count,
            recent,
            statistics,
            assets,
        ) = settle(
            _employees(),
            _manager(),
            _memos(),
            _ticket_count(),
            _recent(),
            _statistics(),
            _assets(),
        )

        note = next((text for text in memos.values() if text), None)
        return DepartmentContext(
            department=department,
            employees=employees,
            manager=manager,
            note=note,
            ticket_count=ticket_count,
            recent_tickets=recent,
            ticket_statistics=statistics,
            assets=assets,
            memos=memos,
            degraded=frozenset(degraded),
        )

    def _safe_memo(
        self,
        path: str,
        *,
        degraded: set[str] | None = None,
        branch: str = "",
    ) -> str | None:
        """Resolve a Memo, degrading a 403/404 to ``None``.

        When ``degraded`` is given, a swallowed failure is recorded there as
        ``"<branch>:<status>"`` so the bundle can report it. Left at ``None``
        for the action-body resolution, where a missing note is not a section
        the caller could be misled about.
        """
        try:
            return self.resolve_memo(path)
        except (EasyvistaNotFound, EasyvistaAuthError) as exc:
            if degraded is not None:
                degraded.add(_degraded_entry(branch or path, exc))
            return None

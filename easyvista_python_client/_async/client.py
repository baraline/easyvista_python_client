"""EasyVista client — a flat facade over the resource builders.

The blocking and the coroutine surface are two spellings of one source: they
differ only in the ``async``/``await`` keywords and in the few names that must
differ (the client class, its iterator types, ``aclose``/``close``). Every
docstring and comment in this module therefore describes both, and prose here
must read true on either surface -- never "see the other client", and never a
claim that holds on only one of them.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Iterable, Sequence
from datetime import datetime

from easyvista_python_client._async._concurrency import Semaphore, settle
from easyvista_python_client._async._transport import (
    DEFAULT_STREAM_CHUNK_SIZE,
    Transport,
)
from easyvista_python_client._transport import RequestSpec
from easyvista_python_client.config import EasyvistaConfig
from easyvista_python_client.context import TicketContext
from easyvista_python_client.directory import (
    RECENT_TICKETS_SORT,
    DepartmentContext,
    _department_matches,
    _normalize_name,
)
from easyvista_python_client.exceptions import EasyvistaAuthError, EasyvistaNotFound
from easyvista_python_client.field_model import parse_memo
from easyvista_python_client.filters import ev_equals_filter, is_safe_ev_value
from easyvista_python_client.models.action import Action, ActionUpdate, PostAction
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
from easyvista_python_client.models.request import PostRequest, Request, RequestUpdate
from easyvista_python_client.pagination import SearchResult
from easyvista_python_client.reporting import (
    DEFAULT_DIMENSIONS,
    TicketStatistics,
    aggregate_tickets,
    fields_for_references,
)
from easyvista_python_client.resources import actions as actions_res
from easyvista_python_client.resources import assets as assets_res
from easyvista_python_client.resources import departments as departments_res
from easyvista_python_client.resources import documents as documents_res
from easyvista_python_client.resources import employees as employees_res
from easyvista_python_client.resources import requests as requests_res

# Width of the action-body fan-out: a ceiling on requests in flight at once on
# the async surface, inert on the sync one. This is the one fan-out here whose
# width is set by the server (a ticket can carry any number of actions); the
# department fan-out is a fixed seven and needs no bound. Deliberately not a
# config field: nobody has asked for it, and measured against a live instance a
# limit of 8 costs nothing (19 actions took 5.31s at limit 8 vs 5.43s unbounded
# -- the server, not the client, is the bottleneck).
_ACTION_FANOUT = 8


class AsyncEasyvistaClient:
    """Client for the EasyVista Service Manager REST API.

    Blocking as ``EasyvistaClient``, coroutine-returning as
    ``AsyncEasyvistaClient``: same methods, same arguments, same results.
    """

    def __init__(self, config: EasyvistaConfig) -> None:
        self.config = config
        self._transport = Transport(config)

    @classmethod
    def from_env(cls) -> AsyncEasyvistaClient:
        return cls(EasyvistaConfig.from_env())

    async def __aenter__(self) -> AsyncEasyvistaClient:
        return self

    async def __aexit__(self, *exc_info: object) -> None:
        await self.aclose()

    async def aclose(self) -> None:
        await self._transport.aclose()

    # --- tickets -------------------------------------------------------------
    async def create_ticket(self, ticket: PostRequest) -> Request:
        spec, parse = requests_res.build_create_ticket(ticket)
        return parse(await self._transport.send(spec))

    async def create_tickets(self, tickets: Sequence[PostRequest]) -> list[Request]:
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
        return [await self.create_ticket(ticket) for ticket in tickets]

    async def get_ticket(self, rfc_number: str) -> Request:
        spec, parse = requests_res.build_get_ticket(rfc_number)
        return parse(await self._transport.send(spec))

    async def search_tickets(
        self,
        *,
        search: str | None = None,
        fields: str | list[str] | None = None,
        sort: str | None = None,
        max_rows: int | None = None,
        offset: int | None = None,
    ) -> SearchResult[Request]:
        if max_rows is None:
            max_rows = self.config.default_max_rows
        spec, parse = requests_res.build_search_tickets(
            search=search, fields=fields, sort=sort, max_rows=max_rows, offset=offset
        )
        return parse(await self._transport.send(spec))

    async def iter_tickets(
        self,
        *,
        search: str | None = None,
        fields: str | list[str] | None = None,
        sort: str | None = None,
        page_size: int | None = None,
        max_records: int | None = None,
    ) -> AsyncIterator[Request]:
        """Yield tickets across pages, following the API's offset pagination.

        Pages of ``page_size`` (default ``config.default_max_rows``) until the
        server reports no further page (``@next``) or ``max_records`` is reached.

        ``sort`` is forwarded to the wire and its token must be
        **space-separated** — ``"LAST_UPDATE"`` or ``"LAST_UPDATE DESC"``.
        ``"LAST_UPDATE:DESC"``, ``"-LAST_UPDATE"`` and ``"DESC(LAST_UPDATE)"``
        are each **silently ignored** (measured live): the server returns its
        default order with no error, so an unsorted result looks sorted. This is
        not validated locally, so the token is the caller's to get right.

        Sorting is not cosmetic when the filter selects rows that are changing --
        an unsorted offset sweep over a change window can skip a record
        permanently. See :func:`~easyvista_python_client.ev_since_filter`.
        """
        if page_size is None:
            page_size = self.config.default_max_rows
        offset = 0
        yielded = 0
        while max_records is None or yielded < max_records:
            result = await self.search_tickets(
                search=search,
                fields=fields,
                sort=sort,
                max_rows=page_size,
                offset=offset,
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

    async def count_tickets(self, search: str | None = None) -> int:
        """Return the number of tickets matching ``search`` (one cheap call).

        Uses ``max_rows=1`` and reads the envelope's ``total_record_count``, so
        it does not fetch the matching records.
        """
        result = await self.search_tickets(search=search, max_rows=1)
        return result.total_record_count

    async def ticket_statistics(
        self,
        *,
        search: str | None = None,
        dimensions: Sequence[str] | None = None,
        created_since: datetime | str | None = None,
        created_until: datetime | str | None = None,
        max_records: int | None = 100,
    ) -> TicketStatistics:
        """Aggregate matching tickets into a total plus per-dimension breakdowns.

        Fetches up to ``max_records`` tickets matching ``search`` (default cap 100;
        pass ``None`` to aggregate all) and groups them by each name in
        ``dimensions`` (default: all of ``DEFAULT_DIMENSIONS``). ``created_since`` /
        ``created_until`` apply an inclusive client-side window on the ticket's
        creation date. When the cap truncates, the result describes the fetched
        subset — use :meth:`count_tickets` for the true total.

        Delegates to the same pure :func:`aggregate_tickets` on both surfaces.
        The page is collected into a list first because that function consumes
        a plain iterable, and the async surface's ``iter_tickets`` is an async
        generator it cannot take directly.
        """
        dims = DEFAULT_DIMENSIONS if dimensions is None else dimensions
        has_date_filter = created_since is not None or created_until is not None
        fields = fields_for_references(dims, include_creation_date=has_date_filter)
        tickets = [
            t
            async for t in self.iter_tickets(
                search=search, fields=fields, max_records=max_records
            )
        ]
        return aggregate_tickets(
            tickets,
            dimensions=dims,
            created_since=created_since,
            created_until=created_until,
        )

    async def update_ticket(self, rfc_number: str, update: RequestUpdate) -> Request:
        spec, parse = requests_res.build_update_ticket(rfc_number, update)
        return parse(await self._transport.send(spec))

    async def close_ticket(
        self,
        rfc_number: str,
        *,
        status_guid: str | None = None,
        delete_actions: int | None = None,
        comment: str | None = None,
    ) -> Request:
        spec, parse = requests_res.build_close_ticket(
            rfc_number,
            status_guid=status_guid,
            delete_actions=delete_actions,
            comment=comment,
        )
        return parse(await self._transport.send(spec))

    # --- actions -------------------------------------------------------------
    async def create_action(self, rfc_number: str, action: PostAction) -> Action:
        """Create one action on a ticket.

        The returned :class:`Action` carries **no usable ``action_id``**: the
        live create response is an HREF naming the parent request, with no
        ``ACTION_ID`` (verified live). To address the action you just created,
        diff :meth:`list_actions` across the call — see
        ``integration_tests/test_live_ticket_history.py`` for the pattern.
        """
        spec, parse = actions_res.build_create_action(rfc_number, action)
        return parse(await self._transport.send(spec))

    async def list_actions(
        self, rfc_number: str, *, fields: Iterable[str] | str | None = None
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
        actions, most of them workflow-generated. Raise
        ``EasyvistaConfig.default_max_rows`` if a ticket's whole log matters.

        The note text is never projectable — ``DESCRIPTION`` and ``COMMENT``
        are Memo sub-resources and come back as HREF objects under every
        projection, so a body still costs one :meth:`resolve_memo` per action.

        ``fields`` has two more silent footguns: ``"*"`` is not a wildcard —
        it silently reduces to ``ACTION_ID`` alone — and a dotted path such as
        ``DESCRIPTION.HREF`` is silently dropped.
        """
        spec, parse = actions_res.build_list_actions(
            rfc_number, fields=fields, max_rows=self.config.default_max_rows
        )
        return parse(await self._transport.send(spec))

    async def get_action(self, action_id: str | int) -> Action:
        """Fetch one action, including the Memo links ``list_actions`` omits.

        The note text lives behind :attr:`Action.description`'s href on this
        record; :meth:`get_ticket_context` resolves it for you.
        """
        spec, parse = actions_res.build_get_action(action_id)
        return parse(await self._transport.send(spec))

    async def update_action(self, action_id: str | int, update: ActionUpdate) -> Action:
        """Edit an existing action's note text.

        Live-verified 2026-08-17 by re-reading the memo afterwards, not by the
        status code. Note that an action can be edited but **not deleted** —
        ``DELETE actions/{id}`` is refused with HTTP 403 — so there is
        deliberately no ``delete_action``.

        The returned :class:`Action` is the API's own echo and is **not
        verified**: the PUT's response body has never been captured, and if it
        answers empty or href-only the parser yields an ``Action`` whose fields
        are all ``None``. Re-read with :meth:`get_action` rather than reading
        fields off the return value.
        """
        spec, parse = actions_res.build_update_action(action_id, update)
        return parse(await self._transport.send(spec))

    async def _resolve_action_body(self, action: Action) -> Action:
        """Return ``action`` with its note text resolved onto ``description``.

        Costs two requests per action (item fetch, then the Memo), so callers
        that do not need bodies pass ``resolve_action_bodies=False``. Degrades
        to the unresolved record on 403/404 rather than failing the bundle.
        """
        if action.action_id is None:
            return action
        try:
            full = await self.get_action(action.action_id)
        except (EasyvistaNotFound, EasyvistaAuthError):
            return action
        if isinstance(full.description, dict):
            href = full.description.get("HREF")
            full.description = await self._safe_memo(href) if href else None
        return full

    # --- assets --------------------------------------------------------------
    async def create_asset(self, asset: PostAsset) -> Asset:
        spec, parse = assets_res.build_create_asset(asset)
        return parse(await self._transport.send(spec))

    async def get_asset(self, asset_id: str) -> Asset:
        spec, parse = assets_res.build_get_asset(asset_id)
        return parse(await self._transport.send(spec))

    async def search_assets(
        self,
        *,
        search: str | None = None,
        fields: str | list[str] | None = None,
        sort: str | None = None,
        max_rows: int | None = None,
        offset: int | None = None,
    ) -> SearchResult[Asset]:
        if max_rows is None:
            max_rows = self.config.default_max_rows
        spec, parse = assets_res.build_search_assets(
            search=search, fields=fields, sort=sort, max_rows=max_rows, offset=offset
        )
        return parse(await self._transport.send(spec))

    async def iter_assets(
        self,
        *,
        search: str | None = None,
        fields: str | list[str] | None = None,
        sort: str | None = None,
        page_size: int | None = None,
        max_records: int | None = None,
    ) -> AsyncIterator[Asset]:
        """Yield assets across pages (see :meth:`iter_tickets`)."""
        if page_size is None:
            page_size = self.config.default_max_rows
        offset = 0
        yielded = 0
        while max_records is None or yielded < max_records:
            result = await self.search_assets(
                search=search,
                fields=fields,
                sort=sort,
                max_rows=page_size,
                offset=offset,
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
    async def add_document(
        self, rfc_number: str, *, filename: str, content: bytes
    ) -> Document:
        spec, parse = documents_res.build_add_document(
            rfc_number, filename=filename, content=content
        )
        return parse(await self._transport.send(spec))

    async def list_documents(self, rfc_number: str) -> list[Document]:
        spec, parse = documents_res.build_list_documents(rfc_number)
        return parse(await self._transport.send(spec))

    async def delete_document(self, rfc_number: str, document_id: str) -> None:
        """Remove an attachment from a ticket.

        ``document_id`` is the ``DOCUMENT_ID`` from :meth:`list_documents`.
        Live-verified 2026-08-17 by re-listing the ticket's documents
        afterwards. Returns nothing: the API answers with an empty body.
        """
        await self._transport.send(
            documents_res.build_delete_document(rfc_number, document_id)
        )

    async def download_document(self, document: Document | str) -> bytes:
        """Fetch an attachment's bytes.

        ``document`` is a :class:`Document` from :meth:`list_documents` or a raw
        href/path. Raises :class:`ValueError` when the record carries no
        download URL, and :class:`EasyvistaError` when that URL points outside
        the configured instance (see
        :meth:`~easyvista_python_client._async._transport.BaseTransport.resolve_url`).
        """
        return await self._transport.get_bytes(documents_res.download_href(document))

    async def stream_document(
        self, document: Document | str, *, chunk_size: int = DEFAULT_STREAM_CHUNK_SIZE
    ) -> AsyncIterator[bytes]:
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
        :meth:`~easyvista_python_client._async._transport.Transport.stream_bytes`.

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
            async for chunk in stream:
                yield chunk
        finally:
            await stream.aclose()

    # --- departments ----------------------------------------------------------
    async def get_department(self, department_id: str | int) -> Department:
        spec, parse = departments_res.build_get_department(department_id)
        return parse(await self._transport.send(spec))

    async def search_departments(
        self,
        *,
        search: str | None = None,
        fields: str | list[str] | None = None,
        sort: str | None = None,
        max_rows: int | None = None,
        offset: int | None = None,
    ) -> SearchResult[Department]:
        if max_rows is None:
            max_rows = self.config.default_max_rows
        spec, parse = departments_res.build_search_departments(
            search=search, fields=fields, sort=sort, max_rows=max_rows, offset=offset
        )
        return parse(await self._transport.send(spec))

    async def iter_departments(
        self,
        *,
        search: str | None = None,
        fields: str | list[str] | None = None,
        sort: str | None = None,
        page_size: int | None = None,
        max_records: int | None = None,
    ) -> AsyncIterator[Department]:
        """Yield departments across pages (see :meth:`iter_tickets`)."""
        if page_size is None:
            page_size = self.config.default_max_rows
        offset = 0
        yielded = 0
        while max_records is None or yielded < max_records:
            result = await self.search_departments(
                search=search,
                fields=fields,
                sort=sort,
                max_rows=page_size,
                offset=offset,
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

    async def get_department_comment(self, department_id: str | int) -> str | None:
        """Return the department's note (a Memo).

        ``""`` for an empty note; propagates transport errors so a 403/404 is
        distinguishable from an empty note (uses the generic ``resolve_memo``).
        """
        return await self.resolve_memo(
            f"departments/{department_id}/comment_department"
        )

    async def find_departments(
        self, name: str, *, limit: int | None = None
    ) -> list[Department]:
        """Resolve departments by a fuzzy, language-agnostic ``name``.

        Fast path (neutral): an all-digit ``name`` matches ``DEPARTMENT_ID`` exactly,
        otherwise ``DEPARTMENT_CODE`` exactly; a hit returns immediately. Fuzzy
        fallback: scan every department and match ``name`` — normalized so
        ``"Acme Corp" == "ACME-CORP" == "acmecorp"`` — as a substring of any
        string field. ``limit`` caps the result count. Returns ``[]`` on no match.

        A ``name`` that cannot be expressed in EasyVista's search grammar (see
        :func:`~easyvista_python_client.is_safe_ev_value`) skips the server fast
        path and falls back directly to the client-side scan, so this method
        returns correct results rather than raising.
        """
        # The server fast path is only an optimization, and a name that cannot be
        # expressed server-side would otherwise be interpolated raw — where a ','
        # silently widens the result set. Such names skip straight to the local
        # scan below, which handles any characters.
        field = "DEPARTMENT_ID" if name.isdigit() else "DEPARTMENT_CODE"
        if is_safe_ev_value(name):
            search = ev_equals_filter(field, name)
            if search is not None:
                fast = await self.search_departments(search=search)
                if fast.records:
                    return fast.records if limit is None else fast.records[:limit]
        needle = _normalize_name(name)
        if not needle:
            return []
        matches: list[Department] = []
        async for dept in self.iter_departments():
            if _department_matches(dept, needle):
                matches.append(dept)
                if limit is not None and len(matches) >= limit:
                    break
        return matches

    async def create_department(self, department: PostDepartment) -> Department:
        """Create a department (provisional; profile-gated — spec open item O-DIR-2)."""
        spec, parse = departments_res.build_create_department(department)
        return parse(await self._transport.send(spec))

    async def update_department(
        self, department_id: str | int, update: DepartmentUpdate
    ) -> Department:
        """Update a department via PUT (provisional; profile-gated)."""
        spec, parse = departments_res.build_update_department(department_id, update)
        return parse(await self._transport.send(spec))

    # --- employees ------------------------------------------------------------
    async def get_employee(self, employee_id: str | int) -> Employee:
        spec, parse = employees_res.build_get_employee(employee_id)
        return parse(await self._transport.send(spec))

    async def search_employees(
        self,
        *,
        search: str | None = None,
        fields: str | list[str] | None = None,
        sort: str | None = None,
        max_rows: int | None = None,
        offset: int | None = None,
    ) -> SearchResult[Employee]:
        if max_rows is None:
            max_rows = self.config.default_max_rows
        spec, parse = employees_res.build_search_employees(
            search=search, fields=fields, sort=sort, max_rows=max_rows, offset=offset
        )
        return parse(await self._transport.send(spec))

    async def iter_employees(
        self,
        *,
        search: str | None = None,
        fields: str | list[str] | None = None,
        sort: str | None = None,
        page_size: int | None = None,
        max_records: int | None = None,
    ) -> AsyncIterator[Employee]:
        """Yield employees across pages (see :meth:`iter_tickets`)."""
        if page_size is None:
            page_size = self.config.default_max_rows
        offset = 0
        yielded = 0
        while max_records is None or yielded < max_records:
            result = await self.search_employees(
                search=search,
                fields=fields,
                sort=sort,
                max_rows=page_size,
                offset=offset,
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

    async def create_employee(self, employee: PostEmployee) -> Employee:
        """Create an employee (provisional; profile-gated — spec open item O-DIR-2)."""
        spec, parse = employees_res.build_create_employee(employee)
        return parse(await self._transport.send(spec))

    async def update_employee(
        self, employee_id: str | int, update: EmployeeUpdate
    ) -> Employee:
        """Update an employee via PUT (provisional; profile-gated)."""
        spec, parse = employees_res.build_update_employee(employee_id, update)
        return parse(await self._transport.send(spec))

    # --- aggregated context --------------------------------------------------
    async def resolve_memo(self, href: str) -> str | None:
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
        return parse_memo(await self._transport.send(RequestSpec("GET", path)), field)

    async def get_ticket_context(
        self, rfc_number: str, *, resolve_action_bodies: bool = True
    ) -> TicketContext:
        """Fetch a ticket plus its resolved narrative content as a bundle.

        Resolves the href-only ``description``/``comment`` sub-resources and
        lists actions/documents. Missing sub-resources (404) or
        profile-restricted lists (403) degrade to ``None`` / ``[]`` rather than
        failing the whole call.

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

        On the async surface the independent requests (the two memos plus the
        actions and documents lists) are issued concurrently, in up to three
        waves; on the sync surface they run one after another in source order,
        costing ``4 + 2N`` serial round trips for a ticket with ``N`` actions.
        Measured against a live instance on a 19-action ticket: 5.31s
        concurrent, 14.65s serial.

        Peak in-flight on the async surface is four sub-resource requests, then
        up to ``_ACTION_FANOUT`` action-body resolutions; the sync surface
        issues one request at a time throughout. On a hard failure (5xx, a
        transport error) siblings already in flight on the async surface run to
        completion before the error propagates, so a failing call there can
        issue more requests than the sequential surface does. That is the
        deliberate trade: settling every sibling is what keeps an orphaned
        request from outliving the call that issued it, and what makes the
        exception a caller sees the one the sequential surface would have
        raised rather than whichever branch happened to fail soonest.
        """
        # Issued first, and deliberately outside the fan-out: this is the one
        # call with no fallback, so a wrong RFC number should cost one request,
        # not five.
        ticket = await self.get_ticket(rfc_number)

        # The asymmetry between these two except clauses is real and
        # load-bearing: the memos degrade on 404 *and* 403, while the two list
        # calls catch EasyvistaAuthError ONLY, so a 404 there still fails the
        # bundle. Do not tidy them into a shared handler.
        async def _actions() -> list[Action]:
            try:
                return await self.list_actions(rfc_number)
            except EasyvistaAuthError:
                return []

        async def _documents() -> list[Document]:
            try:
                return await self.list_documents(rfc_number)
            except EasyvistaAuthError:
                return []

        description, comment, actions, documents = await settle(
            self._safe_memo(f"requests/{rfc_number}/description"),
            self._safe_memo(f"requests/{rfc_number}/comment"),
            _actions(),
            _documents(),
        )

        if resolve_action_bodies:
            actions = await self._resolve_action_bodies(actions)

        return TicketContext(
            ticket=ticket,
            description=description,
            comment=comment,
            actions=actions,
            documents=documents,
        )

    async def _resolve_action_bodies(self, actions: list[Action]) -> list[Action]:
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

        async def _one(action: Action) -> Action:
            async with limiter:
                return await self._resolve_action_body(action)

        resolved: list[Action] = await settle(*(_one(a) for a in actions))
        return resolved

    async def get_department_context(
        self,
        department_id: str | int,
        *,
        recent_tickets: int = 10,
        dimensions: Sequence[str] | None = None,
        include_statistics: bool = True,
        include_assets: bool = True,
        resolve_manager: bool = True,
        include_note: bool = True,
    ) -> DepartmentContext:
        """Assemble a department plus its employees, manager, note, tickets and assets.

        Only :meth:`get_department` is required; every related part is wrapped so a
        403/404 degrades it to ``[]`` / ``None`` / ``0`` (same pattern as
        :meth:`get_ticket_context`). The flags trim the heavier related calls.
        Tickets and assets filter on ``DEPARTMENT_ID:"<id>"``. ``recent_tickets``
        is ordered by **descending ``RFC_NUMBER``** (``RECENT_TICKETS_SORT``),
        which is newest-first only where RFC numbers are issued monotonically:
        it is a varchar, so the sort orders by the request-type prefix letter
        before the date. The token must stay
        space-separated: a colon form is silently ignored and degrades to the
        API's default order with no error (measured live 2026-08-17). Ordering
        therefore depends on the server honouring that token, which the live
        suite asserts rather than this method.

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
        department = await self.get_department(department_id)
        search = ev_equals_filter("DEPARTMENT_ID", department_id)
        if search is None:
            raise ValueError("department_id is required to build a department context")

        # Every branch here degrades on both 403 and 404, unlike the ticket
        # bundle above, whose two list calls catch EasyvistaAuthError only. The
        # `include_*` / `resolve_*` flags sit inside the branch so a disabled one
        # costs no request at all, exactly as a plain `if` around the call would.
        async def _employees() -> list[Employee]:
            try:
                return [e async for e in self.iter_employees(search=search)]
            except (EasyvistaAuthError, EasyvistaNotFound):
                return []

        async def _manager() -> Employee | None:
            if not resolve_manager or department.manager_id is None:
                return None
            try:
                return await self.get_employee(department.manager_id)
            except (EasyvistaAuthError, EasyvistaNotFound):
                return None

        async def _note() -> str | None:
            if not include_note:
                return None
            return await self._safe_memo(
                f"departments/{department_id}/comment_department"
            )

        async def _ticket_count() -> int:
            try:
                return await self.count_tickets(search=search)
            except (EasyvistaAuthError, EasyvistaNotFound):
                return 0

        async def _recent() -> list[Request]:
            try:
                return [
                    t
                    async for t in self.iter_tickets(
                        search=search,
                        sort=RECENT_TICKETS_SORT,
                        max_records=recent_tickets,
                    )
                ]
            except (EasyvistaAuthError, EasyvistaNotFound):
                return []

        async def _statistics() -> TicketStatistics | None:
            if not include_statistics:
                return None
            try:
                return await self.ticket_statistics(
                    search=search, dimensions=dimensions
                )
            except (EasyvistaAuthError, EasyvistaNotFound):
                return None

        async def _assets() -> list[Asset]:
            if not include_assets:
                return []
            try:
                return [a async for a in self.iter_assets(search=search)]
            except (EasyvistaAuthError, EasyvistaNotFound):
                return []

        (
            employees,
            manager,
            note,
            ticket_count,
            recent,
            statistics,
            assets,
        ) = await settle(
            _employees(),
            _manager(),
            _note(),
            _ticket_count(),
            _recent(),
            _statistics(),
            _assets(),
        )

        return DepartmentContext(
            department=department,
            employees=employees,
            manager=manager,
            note=note,
            ticket_count=ticket_count,
            recent_tickets=recent,
            ticket_statistics=statistics,
            assets=assets,
        )

    async def _safe_memo(self, path: str) -> str | None:
        try:
            return await self.resolve_memo(path)
        except (EasyvistaNotFound, EasyvistaAuthError):
            return None

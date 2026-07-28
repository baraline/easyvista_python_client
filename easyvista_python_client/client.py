"""Synchronous EasyVista client — a flat facade over the resource builders."""

from __future__ import annotations

from collections.abc import Iterator, Sequence
from datetime import datetime

from ._transport import RequestSpec, SyncTransport
from .config import EasyvistaConfig
from .context import TicketContext
from .directory import (
    RECENT_TICKETS_SORT,
    DepartmentContext,
    _department_matches,
    _normalize_name,
)
from .exceptions import EasyvistaAuthError, EasyvistaNotFound
from .field_model import parse_memo
from .filters import ev_equals_filter, is_safe_ev_value
from .models.action import Action, PostAction
from .models.asset import Asset, PostAsset
from .models.department import Department, DepartmentUpdate, PostDepartment
from .models.document import Document
from .models.employee import Employee, EmployeeUpdate, PostEmployee
from .models.request import PostRequest, Request, RequestUpdate
from .pagination import SearchResult
from .reporting import (
    DEFAULT_DIMENSIONS,
    TicketStatistics,
    aggregate_tickets,
    fields_for_references,
)
from .resources import actions as actions_res
from .resources import assets as assets_res
from .resources import departments as departments_res
from .resources import documents as documents_res
from .resources import employees as employees_res
from .resources import requests as requests_res


class EasyvistaClient:
    """Blocking client for the EasyVista Service Manager REST API."""

    def __init__(self, config: EasyvistaConfig) -> None:
        self.config = config
        self._transport = SyncTransport(config)

    @classmethod
    def from_env(cls) -> EasyvistaClient:
        return cls(EasyvistaConfig.from_env())

    def __enter__(self) -> EasyvistaClient:
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()

    def close(self) -> None:
        self._transport.close()

    # --- tickets -------------------------------------------------------------
    def create_ticket(self, ticket: PostRequest) -> Request:
        spec, parse = requests_res.build_create_ticket(ticket)
        return parse(self._transport.send(spec))

    def create_tickets(self, tickets: Sequence[PostRequest]) -> list[Request]:
        # EasyVista's POST /requests creates only the first item of a multi-item
        # body, so create each ticket with its own request.
        return [self.create_ticket(ticket) for ticket in tickets]

    def get_ticket(self, rfc_number: str) -> Request:
        spec, parse = requests_res.build_get_ticket(rfc_number)
        return parse(self._transport.send(spec))

    def search_tickets(
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
        return parse(self._transport.send(spec))

    def iter_tickets(
        self,
        *,
        search: str | None = None,
        fields: str | list[str] | None = None,
        sort: str | None = None,
        page_size: int | None = None,
        max_records: int | None = None,
    ) -> Iterator[Request]:
        """Yield tickets across pages, following the API's offset pagination.

        Pages of ``page_size`` (default ``config.default_max_rows``) until the
        server reports no further page (``@next``) or ``max_records`` is reached.
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

        Uses ``max_rows=1`` and reads the envelope's ``total_record_count``, so it
        does not fetch the matching records.
        """
        return self.search_tickets(search=search, max_rows=1).total_record_count

    def ticket_statistics(
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
        """
        dims = DEFAULT_DIMENSIONS if dimensions is None else dimensions
        has_date_filter = created_since is not None or created_until is not None
        fields = fields_for_references(dims, include_creation_date=has_date_filter)
        tickets = self.iter_tickets(
            search=search, fields=fields, max_records=max_records
        )
        return aggregate_tickets(
            tickets,
            dimensions=dims,
            created_since=created_since,
            created_until=created_until,
        )

    def update_ticket(self, rfc_number: str, update: RequestUpdate) -> Request:
        spec, parse = requests_res.build_update_ticket(rfc_number, update)
        return parse(self._transport.send(spec))

    def close_ticket(
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
        return parse(self._transport.send(spec))

    # --- actions -------------------------------------------------------------
    def create_action(self, rfc_number: str, action: PostAction) -> Action:
        spec, parse = actions_res.build_create_action(rfc_number, action)
        return parse(self._transport.send(spec))

    def list_actions(self, rfc_number: str) -> list[Action]:
        spec, parse = actions_res.build_list_actions(rfc_number)
        return parse(self._transport.send(spec))

    # --- assets --------------------------------------------------------------
    def create_asset(self, asset: PostAsset) -> Asset:
        spec, parse = assets_res.build_create_asset(asset)
        return parse(self._transport.send(spec))

    def get_asset(self, asset_id: str) -> Asset:
        spec, parse = assets_res.build_get_asset(asset_id)
        return parse(self._transport.send(spec))

    def search_assets(
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
        return parse(self._transport.send(spec))

    def iter_assets(
        self,
        *,
        search: str | None = None,
        fields: str | list[str] | None = None,
        sort: str | None = None,
        page_size: int | None = None,
        max_records: int | None = None,
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
            rfc_number, filename=filename, content=content
        )
        return parse(self._transport.send(spec))

    def list_documents(self, rfc_number: str) -> list[Document]:
        spec, parse = documents_res.build_list_documents(rfc_number)
        return parse(self._transport.send(spec))

    def download_document(self, document: Document | str) -> bytes:
        """Fetch an attachment's bytes.

        ``document`` is a :class:`Document` from :meth:`list_documents` or a raw
        href/path. Raises :class:`ValueError` when the record carries no
        download URL, and :class:`EasyvistaError` when that URL points outside
        the configured instance (see
        :meth:`~easyvista_python_client._transport.BaseTransport.resolve_url`).
        """
        return self._transport.get_bytes(documents_res.download_href(document))

    # --- departments ----------------------------------------------------------
    def get_department(self, department_id: str | int) -> Department:
        spec, parse = departments_res.build_get_department(department_id)
        return parse(self._transport.send(spec))

    def search_departments(
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
        return parse(self._transport.send(spec))

    def iter_departments(
        self,
        *,
        search: str | None = None,
        fields: str | list[str] | None = None,
        sort: str | None = None,
        page_size: int | None = None,
        max_records: int | None = None,
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

    def get_department_comment(self, department_id: str | int) -> str | None:
        """Return the department's note (a Memo).

        ``""`` for an empty note; propagates transport errors so a 403/404 is
        distinguishable from an empty note (uses the generic ``resolve_memo``).
        """
        return self.resolve_memo(f"departments/{department_id}/comment_department")

    def find_departments(
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
        spec, parse = departments_res.build_create_department(department)
        return parse(self._transport.send(spec))

    def update_department(
        self, department_id: str | int, update: DepartmentUpdate
    ) -> Department:
        """Update a department via PUT (provisional; profile-gated)."""
        spec, parse = departments_res.build_update_department(department_id, update)
        return parse(self._transport.send(spec))

    # --- employees ------------------------------------------------------------
    def get_employee(self, employee_id: str | int) -> Employee:
        spec, parse = employees_res.build_get_employee(employee_id)
        return parse(self._transport.send(spec))

    def search_employees(
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
        return parse(self._transport.send(spec))

    def iter_employees(
        self,
        *,
        search: str | None = None,
        fields: str | list[str] | None = None,
        sort: str | None = None,
        page_size: int | None = None,
        max_records: int | None = None,
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
        spec, parse = employees_res.build_create_employee(employee)
        return parse(self._transport.send(spec))

    def update_employee(
        self, employee_id: str | int, update: EmployeeUpdate
    ) -> Employee:
        """Update an employee via PUT (provisional; profile-gated)."""
        spec, parse = employees_res.build_update_employee(employee_id, update)
        return parse(self._transport.send(spec))

    # --- aggregated context --------------------------------------------------
    def resolve_memo(self, href: str) -> str | None:
        """Fetch a Memo/link field's text from its sub-resource.

        ``href`` may be a full URL (as returned in a record's link) or a
        resource-relative path. Propagates transport errors so callers can tell an
        empty Memo (``""``) from a 403/404.
        """
        path = href
        root = self.config.api_root
        if path.startswith(root):
            path = path[len(root) :]
        path = path.lstrip("/")
        field = path.rstrip("/").rsplit("/", 1)[-1]
        return parse_memo(self._transport.send(RequestSpec("GET", path)), field)

    def get_ticket_context(self, rfc_number: str) -> TicketContext:
        """Fetch a ticket plus its resolved narrative content as a bundle.

        Resolves the href-only ``description``/``comment`` sub-resources and lists
        actions/documents. Missing sub-resources (404) or profile-restricted lists
        (403) degrade to ``None`` / ``[]`` rather than failing the whole call.
        """
        ticket = self.get_ticket(rfc_number)
        description = self._safe_memo(f"requests/{rfc_number}/description")
        comment = self._safe_memo(f"requests/{rfc_number}/comment")
        try:
            actions = self.list_actions(rfc_number)
        except EasyvistaAuthError:
            actions = []
        try:
            documents = self.list_documents(rfc_number)
        except EasyvistaAuthError:
            documents = []
        return TicketContext(
            ticket=ticket,
            description=description,
            comment=comment,
            actions=actions,
            documents=documents,
        )

    def get_department_context(
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
        ordering is best-effort: it relies on the server honoring
        ``RECENT_TICKETS_SORT`` (open item O-DIR-1) and silently degrades to the
        API's default order otherwise.
        """
        department = self.get_department(department_id)
        search = ev_equals_filter("DEPARTMENT_ID", department_id)
        if search is None:
            raise ValueError("department_id is required to build a department context")

        try:
            employees = list(self.iter_employees(search=search))
        except (EasyvistaAuthError, EasyvistaNotFound):
            employees = []

        manager: Employee | None = None
        if resolve_manager and department.manager_id is not None:
            try:
                manager = self.get_employee(department.manager_id)
            except (EasyvistaAuthError, EasyvistaNotFound):
                manager = None

        note = (
            self._safe_memo(f"departments/{department_id}/comment_department")
            if include_note
            else None
        )

        try:
            ticket_count = self.count_tickets(search=search)
        except (EasyvistaAuthError, EasyvistaNotFound):
            ticket_count = 0

        try:
            recent = list(
                self.iter_tickets(
                    search=search, sort=RECENT_TICKETS_SORT, max_records=recent_tickets
                )
            )
        except (EasyvistaAuthError, EasyvistaNotFound):
            recent = []

        statistics: TicketStatistics | None = None
        if include_statistics:
            try:
                statistics = self.ticket_statistics(
                    search=search, dimensions=dimensions
                )
            except (EasyvistaAuthError, EasyvistaNotFound):
                statistics = None

        assets: list[Asset] = []
        if include_assets:
            try:
                assets = list(self.iter_assets(search=search))
            except (EasyvistaAuthError, EasyvistaNotFound):
                assets = []

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

    def _safe_memo(self, path: str) -> str | None:
        try:
            return self.resolve_memo(path)
        except (EasyvistaNotFound, EasyvistaAuthError):
            return None

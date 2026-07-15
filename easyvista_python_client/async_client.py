"""Native-async EasyVista client — mirrors EasyvistaClient with coroutines."""

from __future__ import annotations

from collections.abc import AsyncIterator, Sequence
from datetime import datetime

from ._transport import AsyncTransport, RequestSpec
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


class AsyncEasyvistaClient:
    """Async client for the EasyVista Service Manager REST API."""

    def __init__(self, config: EasyvistaConfig) -> None:
        self.config = config
        self._transport = AsyncTransport(config)

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
        return parse(await self._transport.asend(spec))

    async def create_tickets(self, tickets: Sequence[PostRequest]) -> list[Request]:
        # One request per ticket (EasyVista creates only the first item of a
        # multi-item body).
        return [await self.create_ticket(ticket) for ticket in tickets]

    async def get_ticket(self, rfc_number: str) -> Request:
        spec, parse = requests_res.build_get_ticket(rfc_number)
        return parse(await self._transport.asend(spec))

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
        return parse(await self._transport.asend(spec))

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
        """Async twin of :meth:`EasyvistaClient.count_tickets`."""
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
        """Async twin of :meth:`EasyvistaClient.ticket_statistics`.

        Collects the ``iter_tickets`` async generator into a list, then delegates to
        the same pure :func:`aggregate_tickets`.
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
        return parse(await self._transport.asend(spec))

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
        return parse(await self._transport.asend(spec))

    # --- actions -------------------------------------------------------------
    async def create_action(self, rfc_number: str, action: PostAction) -> Action:
        spec, parse = actions_res.build_create_action(rfc_number, action)
        return parse(await self._transport.asend(spec))

    async def list_actions(self, rfc_number: str) -> list[Action]:
        spec, parse = actions_res.build_list_actions(rfc_number)
        return parse(await self._transport.asend(spec))

    # --- assets --------------------------------------------------------------
    async def create_asset(self, asset: PostAsset) -> Asset:
        spec, parse = assets_res.build_create_asset(asset)
        return parse(await self._transport.asend(spec))

    async def get_asset(self, asset_id: str) -> Asset:
        spec, parse = assets_res.build_get_asset(asset_id)
        return parse(await self._transport.asend(spec))

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
        return parse(await self._transport.asend(spec))

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
        return parse(await self._transport.asend(spec))

    async def list_documents(self, rfc_number: str) -> list[Document]:
        spec, parse = documents_res.build_list_documents(rfc_number)
        return parse(await self._transport.asend(spec))

    # --- departments ----------------------------------------------------------
    async def get_department(self, department_id: str | int) -> Department:
        spec, parse = departments_res.build_get_department(department_id)
        return parse(await self._transport.asend(spec))

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
        return parse(await self._transport.asend(spec))

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
        """Async twin of :meth:`EasyvistaClient.get_department_comment`."""
        return await self.resolve_memo(
            f"departments/{department_id}/comment_department"
        )

    async def find_departments(
        self, name: str, *, limit: int | None = None
    ) -> list[Department]:
        """Async twin of :meth:`EasyvistaClient.find_departments`."""
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
        """Async twin of :meth:`EasyvistaClient.create_department` (provisional)."""
        spec, parse = departments_res.build_create_department(department)
        return parse(await self._transport.asend(spec))

    async def update_department(
        self, department_id: str | int, update: DepartmentUpdate
    ) -> Department:
        """Async twin of :meth:`EasyvistaClient.update_department` (provisional)."""
        spec, parse = departments_res.build_update_department(department_id, update)
        return parse(await self._transport.asend(spec))

    # --- employees ------------------------------------------------------------
    async def get_employee(self, employee_id: str | int) -> Employee:
        spec, parse = employees_res.build_get_employee(employee_id)
        return parse(await self._transport.asend(spec))

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
        return parse(await self._transport.asend(spec))

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
        """Async twin of :meth:`EasyvistaClient.create_employee` (provisional)."""
        spec, parse = employees_res.build_create_employee(employee)
        return parse(await self._transport.asend(spec))

    async def update_employee(
        self, employee_id: str | int, update: EmployeeUpdate
    ) -> Employee:
        """Async twin of :meth:`EasyvistaClient.update_employee` (provisional)."""
        spec, parse = employees_res.build_update_employee(employee_id, update)
        return parse(await self._transport.asend(spec))

    # --- aggregated context --------------------------------------------------
    async def resolve_memo(self, href: str) -> str | None:
        """Async twin of :meth:`EasyvistaClient.resolve_memo`."""
        path = href
        root = self.config.api_root
        if path.startswith(root):
            path = path[len(root) :]
        path = path.lstrip("/")
        field = path.rstrip("/").rsplit("/", 1)[-1]
        return parse_memo(await self._transport.asend(RequestSpec("GET", path)), field)

    async def get_ticket_context(self, rfc_number: str) -> TicketContext:
        """Async twin of :meth:`EasyvistaClient.get_ticket_context`."""
        ticket = await self.get_ticket(rfc_number)
        description = await self._safe_memo(f"requests/{rfc_number}/description")
        comment = await self._safe_memo(f"requests/{rfc_number}/comment")
        try:
            actions = await self.list_actions(rfc_number)
        except EasyvistaAuthError:
            actions = []
        try:
            documents = await self.list_documents(rfc_number)
        except EasyvistaAuthError:
            documents = []
        return TicketContext(
            ticket=ticket,
            description=description,
            comment=comment,
            actions=actions,
            documents=documents,
        )

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
        """Async twin of :meth:`EasyvistaClient.get_department_context`.

        ``recent_tickets`` ordering is best-effort: it relies on the server
        honoring ``RECENT_TICKETS_SORT`` (open item O-DIR-1) and silently
        degrades to the API's default order otherwise.
        """
        department = await self.get_department(department_id)
        search = ev_equals_filter("DEPARTMENT_ID", department_id)
        if search is None:
            raise ValueError("department_id is required to build a department context")

        try:
            employees = [e async for e in self.iter_employees(search=search)]
        except (EasyvistaAuthError, EasyvistaNotFound):
            employees = []

        manager: Employee | None = None
        if resolve_manager and department.manager_id is not None:
            try:
                manager = await self.get_employee(department.manager_id)
            except (EasyvistaAuthError, EasyvistaNotFound):
                manager = None

        note = (
            await self._safe_memo(f"departments/{department_id}/comment_department")
            if include_note
            else None
        )

        try:
            ticket_count = await self.count_tickets(search=search)
        except (EasyvistaAuthError, EasyvistaNotFound):
            ticket_count = 0

        try:
            recent = [
                t
                async for t in self.iter_tickets(
                    search=search, sort=RECENT_TICKETS_SORT, max_records=recent_tickets
                )
            ]
        except (EasyvistaAuthError, EasyvistaNotFound):
            recent = []

        statistics: TicketStatistics | None = None
        if include_statistics:
            try:
                statistics = await self.ticket_statistics(
                    search=search, dimensions=dimensions
                )
            except (EasyvistaAuthError, EasyvistaNotFound):
                statistics = None

        assets: list[Asset] = []
        if include_assets:
            try:
                assets = [a async for a in self.iter_assets(search=search)]
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

    async def _safe_memo(self, path: str) -> str | None:
        try:
            return await self.resolve_memo(path)
        except (EasyvistaNotFound, EasyvistaAuthError):
            return None

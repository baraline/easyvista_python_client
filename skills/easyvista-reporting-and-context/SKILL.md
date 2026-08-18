---
name: easyvista-reporting-and-context
description: "Aggregate EasyVista tickets into counts and per-dimension breakdowns, and assemble one-call context bundles, with easyvista_python_client — count_tickets, ticket_statistics, aggregate_tickets, TicketStatistics, get_ticket_context, TicketContext.to_markdown and get_department_context. Use for ticket dashboards, per-status or per-department counts, and for exporting a ticket or a department as an LLM-ready document."
license: MIT
compatibility: "Requires Python 3.10+, easyvista-python-client, and network access to an EasyVista Service Manager REST API."
metadata:
  package: easyvista-python-client
  version: "0.2.0"
---

> **Sync and async.** Examples use `EasyvistaClient`. For `AsyncEasyvistaClient`,
> use `async with`, `await` every call, and `async for` over the `iter_*`
> methods — the method names and arguments are identical. See
> `easyvista-client-setup`.

Two related jobs. Reporting turns matching tickets into counts and
breakdowns. Context bundles fetch a record plus everything hanging off it in
one call, degrading around profile restrictions instead of failing.

## Reporting

- `count_tickets(search=None)` — one cheap call. Sends `max_rows=1` and reads
  the envelope's `total_record_count`; fetches no records.
- `ticket_statistics(search=..., dimensions=..., created_since=...,
  created_until=..., max_records=100)` — fetches up to `max_records` matching
  tickets and groups them. **The default cap is 100**; pass `max_records=None`
  to aggregate all.
- `aggregate_tickets(tickets, dimensions=..., created_since=...,
  created_until=...)` — the same aggregation, pure and offline, over tickets
  you already hold.
- `TicketStatistics` carries `total` and `breakdowns` (`{dimension: {label:
  count}}`). For every dimension, `sum(breakdowns[dim].values()) == total`.
- The default dimensions are `STATUS`, `DEPARTMENT`, `CATALOG_REQUEST`,
  `URGENCY` and `IMPACT`. Any field name works, including custom `e_*`
  columns. Pass them explicitly as a list — the default tuple is not part of
  the public surface.
- `created_since` / `created_until` are **inclusive** bounds on
  `CREATION_DATE_UT`, accepting a `datetime` or an ISO-8601 string, applied
  client-side. A ticket with a missing or unparseable date is excluded when a
  bound is set. A malformed bound string raises `ValueError`.

## Context bundles

- `get_ticket_context(rfc, resolve_action_bodies=True)` →
  `TicketContext(ticket, description, comment, actions, documents)`. It
  resolves the href-only description/comment memos and lists actions and
  documents. Missing sub-resources (404) and profile-restricted lists (403)
  degrade to `None` / `[]` rather than failing the call. Actions in the bundle
  come back pre-resolved to a string body; for the raw list/item record shapes
  and how to find a just-created action's id (diff `list_actions` across the
  call), see `easyvista-ticket-actions`.
- `TicketContext.to_markdown()` renders an **href-free** Markdown document: an
  `# Ticket <rfc>` heading, a field table, the body, `## Actions` and
  `## Attachments`. Nothing in the output leaks an API URL.
- `get_department_context(department_id, recent_tickets=10, dimensions=None,
  include_statistics=True, include_assets=True, resolve_manager=True,
  include_note=True)` → `DepartmentContext(department, employees, manager,
  note, ticket_count, recent_tickets, ticket_statistics, assets)`. Only the
  department itself is guaranteed; each related part degrades to `[]` / `None`
  / `0`. Resolve a human name or code to a `department_id` with
  `find_departments` first, and read the department's own note independently
  with `get_department_comment` — see `easyvista-directory`.

## Procedure

1. For a single number, use `count_tickets`.
2. For a breakdown, use `ticket_statistics` and pass the dimensions you want
   explicitly.
3. Raise or remove `max_records` when the breakdown must describe the whole
   population — and cross-check the total against `count_tickets`.
4. For one ticket as a document, `get_ticket_context(rfc).to_markdown()`.
5. For a department overview, resolve the id with `find_departments` if you
   only have a name (see `easyvista-directory`), then call
   `get_department_context(id)`; switch off the parts you do not need to save
   requests.
6. When you already hold `Request` objects, call `aggregate_tickets` directly
   — no network.

## Examples

```python
from easyvista_python_client import EasyvistaClient, ev_equals_filter

with EasyvistaClient.from_env() as client:
    search = ev_equals_filter("DEPARTMENT_ID", 42)

    print("open tickets:", client.count_tickets(search=search))

    stats = client.ticket_statistics(
        search=search, dimensions=["STATUS", "URGENCY"], max_records=None
    )
    print("aggregated:", stats.total)
    for dimension, counts in stats.breakdowns.items():
        for label, count in sorted(counts.items(), key=lambda item: -item[1]):
            print(f"{dimension}: {label} = {count}")
```

```python
from datetime import datetime, timezone

from easyvista_python_client import EasyvistaClient

with EasyvistaClient.from_env() as client:
    stats = client.ticket_statistics(
        dimensions=["STATUS"],
        created_since=datetime(2026, 1, 1, tzinfo=timezone.utc),
        created_until="2026-06-30T23:59:59Z",
        max_records=None,
    )
    print(stats.total, stats.breakdowns["STATUS"])
```

```python
from easyvista_python_client import EasyvistaClient, aggregate_tickets

with EasyvistaClient.from_env() as client:
    tickets = list(client.iter_tickets(max_records=500))

# Offline: no further requests.
stats = aggregate_tickets(tickets, dimensions=["STATUS", "DEPARTMENT"])
print(stats.total, stats.breakdowns)
```

```python
from pathlib import Path

from easyvista_python_client import EasyvistaClient

with EasyvistaClient.from_env() as client:
    context = client.get_ticket_context("YOUR_RFC_NUMBER")
    print(context.ticket.rfc_number, len(context.actions), len(context.documents))
    Path("ticket.md").write_text(context.to_markdown(), encoding="utf-8")
```

```python
from easyvista_python_client import EasyvistaClient

with EasyvistaClient.from_env() as client:
    overview = client.get_department_context(
        42, recent_tickets=5, include_assets=False, dimensions=["STATUS"]
    )
    print(overview.department.name, overview.ticket_count)
    print("manager:", overview.manager.last_name if overview.manager else None)
    print("people:", len(overview.employees))
    if overview.ticket_statistics is not None:
        print(overview.ticket_statistics.breakdowns["STATUS"])
```

## Gotchas

- **`ticket_statistics` caps at 100 tickets by default.** When the cap
  truncates, the result describes the fetched subset, not the population —
  compare `stats.total` against `count_tickets(search=...)` and pass
  `max_records=None` when they disagree.
- A dimension whose label cannot be resolved groups under `"(unknown)"`; the
  breakdown still sums to `total`.
- `get_ticket_context` resolves action bodies by default at **two extra
  requests per action**. Pass `resolve_action_bodies=False` when the list is
  enough.
- The bundles' degradation rules differ on purpose: in the ticket bundle the
  two memos degrade on both 403 and 404 while the action and document lists
  degrade on 403 **only**, so a 404 there still fails the call. In the
  department bundle every branch degrades on both.
- The async surface issues the independent branches concurrently and the sync
  one runs them in order; results are identical either way. On a hard failure
  the async surface lets siblings already in flight settle before the error
  propagates, so a failing call can issue more requests than the sync surface
  would.
- `recent_tickets` is genuinely sorted newest-first: `RECENT_TICKETS_SORT`
  uses the space-separated descending token (`RFC_NUMBER DESC`), which
  EasyVista honours — verified live 2026-08-17 by
  `integration_tests/test_live_change_window.py` (closes open item O-DIR-1).
  A colon-separated token (`RFC_NUMBER:DESC`), `-RFC_NUMBER` and
  `DESC(RFC_NUMBER)` are all silently ignored instead, falling back to the
  server's default order with no error — that was the earlier, unconfirmed
  form this constant used to rely on.
- `TicketContext.to_markdown()` titles the body "Description" whichever memo
  carried it, and emits both headings only when both memos have text. Do not
  parse the heading to infer the source field — read `context.description` /
  `context.comment`.
- `aggregate_tickets` needs the dimension columns to have been fetched.
  `ticket_statistics` requests them for you; a hand-rolled
  `iter_tickets(fields=[...])` that omits them yields `"(unknown)"`
  everywhere.

# easyvista-python-client Agent Skills

This folder holds Agent Skills for the operations exposed by the public
`easyvista_python_client` API. Each child directory is a standalone skill
following the Agent Skills specification: the directory name matches the `name`
frontmatter field, and the instructions live in `SKILL.md`.

These skills are source-tree project material. They ship in the source
distribution for contributors and source consumers; they are not part of the
installed wheel, which carries only the `easyvista_python_client` package.

## Skills

| Skill | Use when the agent needs to | Main public API |
| --- | --- | --- |
| `easyvista-client-setup` | Build and configure an authenticated client | `EasyvistaConfig`, `EasyvistaClient`, `AsyncEasyvistaClient` |
| `easyvista-search-syntax` | Write or debug any `search=` expression, including a date/time window | `ev_equals_filter`, `ev_in_filter`, `ev_contains_filter`, `ev_since_filter`, and 4 more filter builders |
| `easyvista-ticket-workflow` | Create, read, search, update or close tickets, or read instance-specific columns off any record | `PostRequest`, `Request`, `RequestUpdate`, `SearchResult`, `Reference`, `FieldClassification` |
| `easyvista-ticket-actions` | Read or write a ticket's action log | `PostAction`, `Action`, `ActionUpdate`, `resolve_memo` |
| `easyvista-document-workflow` | Attach, list, download, stream or delete ticket files | `Document`, `add_document`, `download_document`, `stream_document`, `delete_document` |
| `easyvista-asset-workflow` | Create, fetch, search or iterate assets | `PostAsset`, `Asset` |
| `easyvista-directory` | Resolve or provision departments and employees | `Department`, `Employee`, `find_departments` |
| `easyvista-reporting-and-context` | Count and break down tickets, or build one context bundle | `TicketStatistics`, `aggregate_tickets`, `TicketContext`, `DepartmentContext` |

## Sync and async

The package ships two clients with one endpoint surface:

- `EasyvistaClient` — synchronous. `with EasyvistaClient(config) as client`, no
  `await`, `for` over the iterators.
- `AsyncEasyvistaClient` — asynchronous, doing real non-blocking I/O.
  `async with AsyncEasyvistaClient(config) as client`, `await` every method,
  `async for` over the iterators and over `stream_document`, which is an async
  generator rather than a coroutine.

Neither wraps the other. `_async/` is hand-written and `_sync/` is generated
from it by `unasync_build.py` under a byte-equality CI gate, so the two surfaces
cannot drift apart. Examples in these skills are synchronous; the async form is
shown in full in `easyvista-client-setup`.

## Instance-specific values

Every id in EasyVista — catalog codes, status ids, urgency and impact ids,
action type ids, group ids — is configured per instance. No example here carries
a real one. Where a write needs an id, the skill shows how to read it off the
instance first and uses an obvious placeholder in the payload.

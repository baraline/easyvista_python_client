---
name: easyvista-ticket-workflow
description: "Create, read, search, paginate, update and close EasyVista tickets (requests) with easyvista_python_client — PostRequest, Request, RequestUpdate, create_ticket, create_tickets, get_ticket, search_tickets, iter_tickets, count_tickets, update_ticket and close_ticket. Use for any ticket/incident/request operation, including discovering the instance-specific catalog codes and ids a create needs."
license: MIT
compatibility: "Requires Python 3.10+, easyvista-python-client, network access to an EasyVista Service Manager REST API, and a profile authorized for the requests resource."
metadata:
  package: easyvista-python-client
  version: "0.2.0"
---

> **Sync and async.** Examples use `EasyvistaClient`. For `AsyncEasyvistaClient`,
> use `async with`, `await` every call, and `async for` over the `iter_*`
> methods — the method names and arguments are identical. See
> `easyvista-client-setup`.

Tickets are EasyVista's `requests` resource. Reads are `get_ticket`,
`search_tickets`, `iter_tickets` and `count_tickets`; writes are
`create_ticket`, `create_tickets`, `update_ticket` and `close_ticket`.
Filtering any `search=` argument follows the grammar in
`easyvista-search-syntax` — see that skill for the rules; they are not
repeated here.

## Discover the ids first

Which fields a create actually requires is configured **per catalog, on the
EasyVista side** — the client cannot know them statically, and a missing one
comes back as `EasyvistaValidationError` (HTTP 590, code 2013). So before
writing anything: read a real ticket, and take the ids off it.

```python
from easyvista_python_client import EasyvistaClient

with EasyvistaClient.from_env() as client:
    probe = client.search_tickets(max_rows=1)
    sample = client.get_ticket(probe.records[0].rfc_number)

    # Ids this instance actually uses, with their human labels.
    for name in ("STATUS", "DEPARTMENT", "URGENCY", "IMPACT", "CATALOG_REQUEST"):
        ref = sample.reference(name)
        print(name, "->", ref.id, ref.display)

    # Instance-specific custom columns, separated from the official ones.
    buckets = sample.classify_fields()
    print("custom:", sorted(buckets.custom))
    print("links:", sorted(buckets.links))
```

`reference(name)` resolves any reference attribute — nested object or bare
id — to a `Reference` with `.id`, `.label` and `.display` (label if present,
else id, else `None`). `classify_fields()` partitions the record into a
`FieldClassification` with `.official`, `.custom` (the instance's `e_*`
columns), `.available` and `.links` buckets. Both work on any record from any
instance with no configuration, so this pattern is how you learn what *this*
deployment needs before you build a payload for it.

## Procedure

1. Discover the ids (above). Never hardcode an id copied from another
   instance — catalog codes, status/urgency/impact ids and group ids are all
   instance-specific.
2. Build a `PostRequest`. `catalog_code` plus `title` is the practical
   minimum; most catalogs also require `origin`, `department_id`,
   `urgency_id` and `impact_id`.
3. Put instance-specific columns in `custom_fields`; they serialize with an
   `e_` prefix unless already prefixed.
4. Call `create_ticket(ticket)`. It returns a `Request` whose `rfc_number` is
   usable immediately — see the first Gotcha for why.
5. To set body text you can read back afterwards, follow the create with
   `update_ticket(rfc, RequestUpdate(description=...))`. `RequestUpdate` also
   accepts `title`, `status_id`, `impact_id`, `owner_id` and
   `external_reference` (capped at 50 characters) after create — see the
   Gotchas for what it deliberately omits.
6. Read one ticket with `get_ticket(rfc)`; search a page with
   `search_tickets(...)`, which returns a `SearchResult` carrying `.records`,
   `.record_count` (this page) and `.total_record_count` (every match on the
   server); walk every match with `iter_tickets(...)`, which yields `Request`
   objects directly and pages for you.
7. Close with `close_ticket(rfc, status_guid=..., delete_actions=...,
   comment=...)`.

## Examples

```python
from easyvista_python_client import EasyvistaClient, PostRequest

with EasyvistaClient.from_env() as client:
    ticket = client.create_ticket(
        PostRequest(
            catalog_code="YOUR_CATALOG_CODE",
            title="Printer offline on the third floor",
            origin=1,
            department_id=1,
            urgency_id=1,
            impact_id=1,
            recipient_mail="user@example.com",
            custom_fields={"building": "HQ"},
        )
    )
    print(ticket.rfc_number)
```

Every numeric id above is a placeholder — `origin=1`, `department_id=1`,
`urgency_id=1` and `impact_id=1` are not guaranteed to mean anything on your
instance. Use the ids the discovery block printed for it instead.

```python
from easyvista_python_client import EasyvistaClient, RequestUpdate

with EasyvistaClient.from_env() as client:
    updated = client.update_ticket(
        "YOUR_RFC_NUMBER",
        RequestUpdate(title="Printer offline - third floor", description="Confirmed offline at 09:15."),
    )
    print(updated.rfc_number)
```

```python
from easyvista_python_client import EasyvistaClient, RequestUpdate

with EasyvistaClient.from_env() as client:
    # impact_id, owner_id and external_reference can all be changed after
    # create, not only set at create time. external_reference is capped at
    # 50 characters -- 51 raises pydantic's own ValidationError locally,
    # before any request is sent.
    updated = client.update_ticket(
        "YOUR_RFC_NUMBER",
        RequestUpdate(impact_id=1, owner_id=1, external_reference="TICKET-REF-0001"),
    )
    print(updated.rfc_number)
```

```python
from easyvista_python_client import EasyvistaClient, ev_equals_filter

with EasyvistaClient.from_env() as client:
    search = ev_equals_filter("STATUS_ID", 3)

    page = client.search_tickets(search=search, fields=["RFC_NUMBER", "TITLE"], max_rows=50)
    print(page.record_count, "of", page.total_record_count)

    for ticket in client.iter_tickets(search=search, page_size=100, max_records=500):
        print(ticket.rfc_number, ticket.title)

    print("total matching:", client.count_tickets(search=search))
```

```python
from easyvista_python_client import EasyvistaClient

with EasyvistaClient.from_env() as client:
    closed = client.close_ticket(
        "YOUR_RFC_NUMBER",
        status_guid="YOUR_CLOSED_STATUS_GUID",
        delete_actions=1,
        comment="Resolved: printer power-cycled.",
    )
    print(closed.rfc_number)
```

```python
from easyvista_python_client import EasyvistaClient, PostRequest

with EasyvistaClient.from_env() as client:
    made = client.create_tickets(
        [
            PostRequest(catalog_code="YOUR_CATALOG_CODE", title="Batch item one"),
            PostRequest(catalog_code="YOUR_CATALOG_CODE", title="Batch item two"),
        ]
    )
    print([t.rfc_number for t in made])
```

## Gotchas

- **Timestamp columns are aware `datetime`, so a record dump is not
  JSON-serialisable.** `submit_date_ut`, `creation_date_ut`,
  `max_resolution_date_ut`, `expected_date_ut`, `end_date_ut` and `last_update`
  are parsed, so `json.dumps(ticket.model_dump(by_alias=True))` and
  `json.dumps(ticket.classify_fields().official)` raise `TypeError`. For a dump,
  use `model_dump(mode="json")`. `classify_fields()` takes **no arguments**, so
  that keyword has nowhere to go there: render the values with
  `format_ev_datetime` before serialising the bucket, or re-key a JSON-mode dump
  by the bucket's keys — `dumped = ticket.model_dump(mode="json",
  by_alias=True)`, then `{k: dumped[k] for k in ticket.classify_fields().official}`.
  Only the
  **declared** columns are parsed — an instance-specific date reached through
  `classify_fields().custom` is still the raw string, so pass it through
  `parse_ev_datetime` before comparing the two. No write model accepts a
  `datetime`, `custom_fields` included: a `datetime` there fails inside the HTTP
  layer with a bare `TypeError`, so render it yourself.
- `create_ticket`'s response body is **HREF-only** — the API returns no
  `RFC_NUMBER`. `Request` derives `rfc_number` from the trailing path segment
  of the `href` (its own model validator does this, and it is checked against
  a live create response, not just a synthetic one), so `ticket.rfc_number`
  works right after a create; nothing else on the returned `Request` is
  populated. Re-read with `get_ticket(ticket.rfc_number)` if you need the
  full record.
- `RequestUpdate(description=...)` writes the ticket's **COMMENT** memo, not
  `DESCRIPTION` — on the instance this client was verified against,
  `DESCRIPTION` stayed empty and `COMMENT` carried the text. Which one a given
  deployment actually populates is a per-instance configuration choice. Read
  it back with `resolve_memo("requests/{rfc}/comment")`, or take
  `TicketContext.comment`, which resolves it for you.
- A `description` passed to **`PostRequest`** at create time was not readable
  back through either memo on the verified instance. Follow the create with
  an `update_ticket` when the body must be retrievable.
- `create_tickets` sends **one POST per ticket, sequentially, on both
  surfaces** — EasyVista creates only the first item of a multi-item body. A
  failure at item *k* means items 0..k-1 exist and the rest do not. It is
  deliberately not a fan-out.
- `Request.title` is legitimately `None` for tickets created through the
  portal/catalog on some instances; the human summary lives in the
  description or the catalog path instead.
- Write models reject unknown fields (`extra="forbid"`), so a typo raises
  locally rather than being silently dropped by the API.
- Mandatory fields are per-catalog. HTTP 590 with code 2013 means a missing
  mandatory field or an invalid catalog reference — it is **not** retried,
  because it is deterministic.
- The project's own content-fidelity probe script
  (`scripts/validate_live_content_fidelity.py`) keeps its create payload to
  plain ASCII, avoiding `--`, `[`, `]`, `/` and `.`, as a **precaution**
  against a server-side content rejection (HTTP 590) — its own comment
  reasons that the create call "is not wrapped, so a server-side content
  rejection (HTTP 590) here would abort the whole run." No tracked test has
  actually observed such a rejection, so treat this as a precaution worth
  copying, not a documented rule: if a create 590s and every id above checks
  out, stripping punctuation from the title/description before concluding
  the catalog is misconfigured is a reasonable next thing to try.
- The accepted **write** format for the date fields is unverified; both a
  string and an int probe returned 590. Do not attempt to set them.
- `RequestUpdate` deliberately does **not** expose `severity_id` (`SEVERITY_ID`
  is rejected with HTTP 590) or a priority field (EasyVista derives priority
  from urgency x impact rather than exposing a writable column). `urgency_id`
  is also absent: it raised HTTP 590 while still changing the stored value on
  the verified instance, so it is not offered until that is resolved (open
  item `O-590-PARTIAL`).

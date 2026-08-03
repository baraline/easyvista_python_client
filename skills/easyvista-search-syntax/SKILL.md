---
name: easyvista-search-syntax
description: "Write correct EasyVista server-side search expressions for search_tickets, iter_tickets, count_tickets, search_assets, search_departments and search_employees using ev_equals_filter, ev_in_filter, escape_ev_value and is_safe_ev_value. Use whenever building a search= argument, filtering EasyVista records, or debugging a filter that returned everything or nothing — EasyVista silently ignores conditions it cannot honour and returns the whole table."
license: MIT
compatibility: "Requires Python 3.10+, easyvista-python-client, and network access to an EasyVista Service Manager REST API."
metadata:
  package: easyvista-python-client
  version: "0.1.0"
---

> **Sync and async.** Examples use `EasyvistaClient`. For `AsyncEasyvistaClient`,
> use `async with`, `await` every call, and `async for` over the `iter_*`
> methods — the method names and arguments are identical. See
> `easyvista-client-setup`.

Every `search_*` and `iter_*` method takes the same `search` string. The
grammar is small and two of its three failure modes are silent, so this skill
is a prerequisite for any filtering work. Except where a claim below is
explicitly flagged as unconfirmed, everything here was characterized against a
live instance by `integration_tests/test_live_search_syntax.py` — that file is
the authority when something here looks wrong.

## The grammar

- `FIELD:"value"` — exact match.
- `~` is a **synonym for `:`** — exact match, not "contains", on code-like
  fields (`DEPARTMENT_CODE`, `ASSET_TAG`) and on free-text label fields
  (`DEPARTMENT_FR`) alike. Vendor documentation claiming otherwise is wrong.
  **No substring operator has been identified.**
- `%` inside a value is a **literal character**, not a wildcard.
- `,` combines conditions: **OR** when every condition names the same field,
  **AND** across different fields.
- `;` is **not** a combinator; it is swallowed into the quoted value.
- There is **no escape for a `"` inside a value**. Raw, backslash-escaped and
  doubled renderings were all tested against a ticket verifiably created with
  a quote in its title; none matched.

## Three fates of a condition

1. **Honoured.**
2. **Silently dropped** — no error. EasyVista removes any condition it cannot
   honour and applies what is left; with nothing left, it returns **every**
   row. This happens for structurally unparseable input
   (`DEPARTMENT_FR LIKE "%TECH%"`, bare garbage), for an unknown field, and
   for a well-formed condition on a returned-but-unsearchable field. Dropping
   is **per condition**: in a two-condition search, one can be honoured while
   the other vanishes.
3. **Rejected outright** — `EasyvistaValidationError` (HTTP 590) when the
   value's *type* does not match the column, e.g. sending a status name to
   the integer `STATUS_ID`. This is the friendly failure.

The counter-intuitive case: a **broken quote does not** return the table.
`DEPARTMENT_CODE:"X""` still parses as a field expression, the value swallows
the junk, and it matches nothing (0 rows).

## What is searchable

Only **top-level scalar columns**. Two families are returned but not
searchable, and naming one matches everything:

- the denormalized `*_PATH` display columns (`SD_CATALOG_PATH`,
  `DEPARTMENT_PATH`) — filter the `*_ID` sibling instead;
- the sub-keys of a nested reference object (`STATUS_EN` / `STATUS_FR`
  inside `STATUS`) — they are not top-level columns at all. Filter
  `STATUS_ID`.

The rule is about **nesting, not language**: `DEPARTMENT_FR` is a top-level
column on `departments` and filters correctly. `CATALOG_GUID` is not an
instance of this rule — it is not returned at all, so it is merely an unknown
field. There is **no verified way to filter tickets by status name**; status
ids are instance-specific.

## Procedure

1. Build every filter with `ev_equals_filter` / `ev_in_filter`. Never
   f-string a value into a `search`.
2. Handle `None`: both builders return `None` for a blank or missing value,
   so `search=None` means unfiltered — guard when that is not what you want.
3. Call `is_safe_ev_value(value)` first when you would rather skip a filter
   than raise; `escape_ev_value` raises `ValueError` on a value containing
   `"`.
4. Prefer an `*_ID` column over any label column.
5. Verify the filter was applied: compare the filtered count against the
   unfiltered baseline (see below) before trusting a result set.
6. If the call raises 590, the value's type does not match the column — that
   is a real signal, not a bug.

## Examples

```python
from easyvista_python_client import EasyvistaClient, ev_equals_filter

with EasyvistaClient.from_env() as client:
    search = ev_equals_filter("STATUS_ID", 3)
    result = client.search_tickets(search=search, max_rows=50)
    print(result.record_count, "of", result.total_record_count)
    for ticket in result.records:
        print(ticket.rfc_number, ticket.title)
```

```python
from easyvista_python_client import EasyvistaClient, ev_in_filter

with EasyvistaClient.from_env() as client:
    # ',' is OR when every condition names the same field.
    search = ev_in_filter("DEPARTMENT_CODE", ["ACME", "GLOBEX"])
    result = client.search_departments(search=search)
    print(result.total_record_count)
```

```python
from easyvista_python_client import EasyvistaClient, ev_equals_filter

with EasyvistaClient.from_env() as client:
    # ',' is AND across different fields: build the parts, then join them.
    parts = [
        ev_equals_filter("STATUS_ID", 3),
        ev_equals_filter("DEPARTMENT_ID", 42),
    ]
    search = ",".join(part for part in parts if part is not None)
    print(client.count_tickets(search=search))
```

```python
from easyvista_python_client import EasyvistaClient, ev_equals_filter

with EasyvistaClient.from_env() as client:
    # Prove the filter was applied. A silently-dropped condition returns the
    # whole table, which is indistinguishable from a filter that matched
    # everything -- except by comparison with the unfiltered baseline.
    baseline = client.count_tickets()
    search = ev_equals_filter("DEPARTMENT_ID", 42)
    matched = client.count_tickets(search=search)
    if matched >= baseline:
        raise RuntimeError(
            f"search={search!r} matched {matched} of {baseline} records -- "
            "EasyVista ignored the condition"
        )
```

```python
from easyvista_python_client import EasyvistaClient, is_safe_ev_value, ev_equals_filter

user_supplied = 'ACME "North"'

with EasyvistaClient.from_env() as client:
    if is_safe_ev_value(user_supplied):
        result = client.search_departments(
            search=ev_equals_filter("DEPARTMENT_CODE", user_supplied)
        )
    else:
        # No escape for '"' exists; fall back to the client-side fuzzy scan.
        result = client.find_departments(user_supplied, limit=10)
```

## Gotchas

- A `,` reaching the server inside untrusted input **widens** a same-field
  query — this is the injection vector. A `,` **inside** the quotes is
  inert, so blocking the `"` is what blocks the attack, which is exactly what
  `escape_ev_value` does.
- `ev_equals_filter` returns `None` for a blank value; passing that straight
  through as `search=` silently means "no filter".
- An unknown `sort` token is believed to be ignored, not rejected, falling
  back to the default order — but unlike the rest of this skill, that is
  **not** covered by the live suite. It is what
  `easyvista_python_client/directory.py`'s `RECENT_TICKETS_SORT` relies on
  (open item O-DIR-1); treat it as unconfirmed until checked against your
  own instance.
- `count_tickets` is the cheap way to check a filter: it sends `max_rows=1`
  and reads the envelope total without fetching records.
- `search_*` returns one page; `iter_*` pages until the server reports no
  `@next` or `max_records` is reached.

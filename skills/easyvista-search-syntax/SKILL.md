---
name: easyvista-search-syntax
description: "Write correct EasyVista server-side search expressions for search_tickets, iter_tickets, count_tickets, search_assets, search_departments and search_employees using ev_equals_filter, ev_in_filter, ev_contains_filter, ev_starts_with_filter, ev_since_filter, ev_between_filter, escape_ev_value and is_safe_ev_value. Use whenever building a search= argument, filtering EasyVista records, filtering by a date/time window, or debugging a filter that returned everything or nothing — EasyVista silently ignores conditions it cannot honour and returns the whole table."
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
is a prerequisite for any filtering work. Everything here was characterized
against a live instance by `integration_tests/test_live_search_syntax.py`
(the base grammar) and `integration_tests/test_live_change_window.py` (the
interval, wildcard and sort grammars) — those files are the authority when
something here looks wrong.

## The grammar

- `FIELD:"value"` — exact match.
- `~` is a **pattern operator**, not a synonym for `:`. It only behaves like
  "contains" or "starts with" when the value carries an **explicit** wildcard:
  `*` and `%` both expand (`FIELD~"*abc*"` substring, `FIELD~"abc*"` prefix —
  verified live 2026-08-17, and `%` reproduces the same match count as `*`).
  Given a **bare** value with no wildcard, `~` degenerates to exact match —
  identical to `:` — which is why this skill previously documented it as
  exact-match-only; that conclusion held only for the wildcard-free inputs it
  was tested with. `:` never expands a wildcard, even when one is present in
  the value: `FIELD:"abc*"` matches nothing. Use `ev_contains_filter` /
  `ev_starts_with_filter` rather than building the pattern by hand.
- `,` combines conditions: **OR** when every condition names the same field,
  **AND** across different fields.
- `;` is **not** a combinator; it is swallowed into the quoted value.
- There is **no comparison operator** (`>=`, `BETWEEN`, `[a TO b]`…). Writing
  one fails one of two different ways depending on its exact shape — see fate
  3 below — never by narrowing the result. Use `ev_since_filter` /
  `ev_between_filter` for a date/time window instead (see "Filtering by a
  change window").
- There is **no escape for a `"` inside a value**. Raw, backslash-escaped and
  doubled renderings were all tested against a ticket verifiably created with
  a quote in its title; none matched.

## Three fates of a condition

1. **Honoured.**
2. **Silently dropped** — no error. EasyVista removes any condition it cannot
   honour and applies what is left; with nothing left, it returns **every**
   row. This happens for structurally unparseable input
   (`DEPARTMENT_FR LIKE "%TECH%"`, bare garbage, a colon-free comparison like
   `LAST_UPDATE>="2026-01-01"`), for an unknown field, and for a well-formed
   condition on a returned-but-unsearchable field. Dropping is **per
   condition**: in a two-condition search, one can be honoured while the
   other vanishes.
3. **Rejected outright** — `EasyvistaValidationError` (HTTP 590) when the
   value's *type* does not match the column, e.g. sending a status name to
   the integer `STATUS_ID`. This is the friendly failure. A comparison
   operator embedded *inside* `FIELD:"value"` syntax lands here too —
   `LAST_UPDATE:">=2026-01-01"` and `LAST_UPDATE:"[2026-01-01 TO *]"` both
   raise HTTP 590, because the quoted text must still parse as `LAST_UPDATE`'s
   date type. So a comparison operator has **two** fates, not one: drop the
   `FIELD:` colon and it is silently dropped (fate 2); keep the colon and
   embed the operator in the value and it is a type mismatch (fate 3).
   Neither ever narrows the result.

The counter-intuitive case: a **broken quote does not** return the table.
`DEPARTMENT_CODE:"X""` still parses as a field expression, the value swallows
the junk, and it matches nothing (0 rows).

## Filtering by a change window

There is no comparison operator, so a range is an interval in the *value*
position: `ev_since_filter("LAST_UPDATE", watermark)` builds
`LAST_UPDATE:(<watermark>;)`, an open-ended lower bound; `ev_between_filter`
builds a closed `LAST_UPDATE:(a;b)`. Pass a `datetime` (preferred, and what a
`Request` timestamp field already is) or a timestamp string — either bound is
validated as a real timestamp because it is interpolated **unquoted**, so a
stray `;` or `)` inside it would silently change the query rather than being
escaped away.

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

1. Build every filter with a helper: `ev_equals_filter` / `ev_in_filter` for
   exact match, `ev_contains_filter` / `ev_starts_with_filter` for a pattern,
   `ev_since_filter` / `ev_between_filter` for a date/time window. Never
   f-string a value into a `search`.
2. Handle `None`: every builder returns `None` for a blank or missing value,
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

```python
from easyvista_python_client import EasyvistaClient, ev_contains_filter

with EasyvistaClient.from_env() as client:
    # A bare '~' is exact match; the wildcard is what makes it "contains".
    result = client.search_assets(search=ev_contains_filter("ASSET_TAG", "LAPTOP"))
    print(result.total_record_count)
```

```python
from easyvista_python_client import EasyvistaClient, ev_since_filter

with EasyvistaClient.from_env() as client:
    ticket = client.get_ticket("I240101_0001")
    # ticket.last_update is already an aware datetime -- feed it straight back
    # in as a watermark for "everything changed since this ticket".
    search = ev_since_filter("LAST_UPDATE", ticket.last_update)
    if search is not None:
        for changed in client.iter_tickets(search=search, page_size=100):
            print(changed.rfc_number)
```

## Gotchas

- A `,` reaching the server inside untrusted input **widens** a same-field
  query — this is the injection vector. A `,` **inside** the quotes is
  inert, so blocking the `"` is what blocks the attack, which is exactly what
  `escape_ev_value` does.
- `ev_equals_filter` returns `None` for a blank value; passing that straight
  through as `search=` silently means "no filter".
- The descending-sort token must be **space-separated**: `FIELD DESC` (or
  `field desc`) genuinely reorders the result, verified live 2026-08-17 by
  `integration_tests/test_live_change_window.py`. `FIELD:DESC`, `-FIELD` and
  `DESC(FIELD)` are all silently ignored — the query falls back to the
  server's default order with no error. This is what
  `easyvista_python_client/directory.py`'s `RECENT_TICKETS_SORT` relies on
  (closes open item O-DIR-1).
- `count_tickets` is the cheap way to check a filter: it sends `max_rows=1`
  and reads the envelope total without fetching records.
- `search_*` returns one page; `iter_*` pages until the server reports no
  `@next` or `max_records` is reached.

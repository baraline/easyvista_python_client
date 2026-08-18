---
name: easyvista-search-syntax
description: "Write correct EasyVista server-side search expressions for search_tickets, iter_tickets, count_tickets, search_assets, search_departments and search_employees using ev_equals_filter, ev_in_filter, ev_contains_filter, ev_starts_with_filter, ev_since_filter, ev_between_filter, escape_ev_value and is_safe_ev_value. Use whenever building a search= argument, filtering EasyVista records, filtering by a date/time window, or debugging a filter that returned everything or nothing — EasyVista silently ignores conditions it cannot honour and returns the whole table."
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
- `*` and `%` are not the only metacharacters under `~`. `_` matches any
  **single** character and `[` opens a character class — measured live,
  replacing one character of an RFC that matched 1 row with `_`, or with
  `[0-9]`, matched 9. There is **no escape**: `\_` returned 0 rows, i.e. the
  backslash is compared literally. `ev_contains_filter` /
  `ev_starts_with_filter` therefore raise `ValueError` for a value containing
  any of `* % _ [`, because silently matching more rows is worse than failing.
  This bites on ordinary input, not exotic input: `_` is pervasive in EasyVista
  codes, and `ev_contains_filter("ASSET_TAG", "LAPTOP_01")` would otherwise also
  match `LAPTOP-01` and `LAPTOP001` with HTTP 200 and no hint. For an **exact**
  match on such a value use `ev_equals_filter` — `:` does not expand a wildcard,
  so a `_` in the value is compared literally there. Only if you need to
  pattern-match *around* a literal `_` are you stuck: filter server-side on a
  wider condition and match exactly in Python.
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

**A bound naming a time must carry its UTC offset**, and both builders refuse one
that does not — as a `datetime` or as a string. EasyVista *accepts* an
offset-less literal and reads it in another zone, moving the bound later and
skipping records with no error (measured live: 13 rows with the offset, 11
without, same wall-clock text). A bare date is fine; it has no time to misplace.

An admitted string bound naming a **time** is re-rendered to millisecond
precision with an offset, because that is the only time rendering the wire
honours: `LAST_UPDATE:(2025-11-28T16:14:41+01:00;)` — second precision with an
offset, the most obvious way to satisfy the rule above — is **HTTP 590**, as are
minute precision and a space instead of `T` (what `str(aware_datetime)`
produces). So the string and `datetime` paths emit identical bounds; do not
hand-build the literal.

The lower bound is **inclusive** and milliseconds are honoured (verified live on
three independent boundaries), so a watermark taken as `max(t.last_update)`
re-reads the boundary record on the next sweep. De-duplicate by `rfc_number`.

**Sort a sweep `LAST_UPDATE DESC`, and de-duplicate.** `iter_*` walks the result
set by *offset*, and the rows a change window selects are by construction the
rows that are changing, so a ticket touched between two pages moves *within the
set being paged*. An unsorted sweep can drop such a row silently — and so can
either sort direction. What differs is where the dropped row's own timestamp
lands relative to the watermark this sweep records:

- **`LAST_UPDATE DESC`**: the re-touched row jumps to the head, behind the read
  cursor, so this sweep misses it — but its stamp is now *above* the watermark,
  so the next sweep selects it again. **Deferred, self-healing.**
- **`LAST_UPDATE` / `LAST_UPDATE ASC`**: the re-touched row moves to the tail and
  everything behind it shifts one place head-ward, so the row that crosses the
  cursor is one whose own stamp did **not** change. It falls *below* the new
  watermark and no later sweep selects it. **Permanent miss.**

Both tokens are honoured (measured live); descending is chosen for the reason
above. De-duplicate by `rfc_number` — the duplicates are the deferred rows
arriving on a later sweep, plus the inclusive-boundary re-read.

**A sweep that never finishes is a separate trap.** `DESC` yields the newest
row first, so the watermark reaches its *final* value on page 1. A sweep that
is interrupted, or capped with `max_records` (as some pagination examples in
this repo do), still ends up holding the newest stamp — advance the watermark
from that and the next window's `(newest;)` bound permanently excludes every
row the incomplete sweep never read. Only advance the watermark after a sweep
runs to completion.

If even a deferred miss is unacceptable, do not use `iter_*`: page
`search_tickets` yourself with **keyset** pagination — sort ascending and, after
each page, advance the *window* to `ev_since_filter(field, max(stamps on the
page))` at `offset=0` instead of incrementing an offset. With no offset there is
no cursor for a row to shift past. `iter_tickets` cannot express this because it
owns its own offset.

(An earlier version of this skill recommended ascending, reasoning that it turns
a permanent miss into a duplicate. That was wrong: the row an ascending sweep
drops is not the re-touched one.)

## What is searchable

Only **top-level scalar columns**. Two families are returned but not
searchable, and naming one matches everything:

- the denormalized `*_PATH` display columns (`SD_CATALOG_PATH`,
  `DEPARTMENT_PATH`) — filter the `*_ID` sibling instead;
- the sub-keys of a nested reference object (`STATUS_EN` / `STATUS_FR`
  inside `STATUS`) — they are not top-level columns at all. Filter
  `STATUS_ID`.

A **dotted path across a relation** is the exception and IS honoured in
`search`: `REQUEST.RFC_NUMBER:"<rfc>"` on `/actions` genuinely scopes, and it is
what `list_actions` is built on (pinned by
`integration_tests/test_live_ticket_history.py::test_list_actions_filters_to_the_requested_ticket`).
What is silently ignored is a **bare** nested sub-key (`STATUS_EN`) and a
`*_PATH` display column — not the dotted form. Note `fields` does not accept the
dotted form even where `search` does: a projection like `DESCRIPTION.HREF` is
silently dropped.

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
        # The sort direction is load-bearing. Descending on the filtered
        # column defers a mid-sweep miss to the next sweep (the row's stamp
        # ends up above the watermark); ascending loses it for good. Hence
        # the de-duplication -- see "Filtering by a change window".
        seen = set()
        for changed in client.iter_tickets(
            search=search, sort="LAST_UPDATE DESC", page_size=100
        ):
            if changed.rfc_number in seen:
                continue
            seen.add(changed.rfc_number)
            print(changed.rfc_number)
```

## Gotchas

- A `,` reaching the server inside untrusted input **widens** a same-field
  query — this is the injection vector. A `,` **inside** the quotes is
  inert, so blocking the `"` is what blocks the attack, which is exactly what
  `escape_ev_value` does.
- `ev_equals_filter` returns `None` for a blank value; passing that straight
  through as `search=` silently means "no filter".
- The sort token must be **space-separated**: `FIELD DESC` (or `field desc`)
  genuinely reorders the result, and bare `FIELD` / `FIELD ASC` both sort
  ascending — verified live by
  `integration_tests/test_live_change_window.py`. `FIELD:DESC`, `-FIELD` and
  `DESC(FIELD)` are all silently ignored — the query falls back to the
  server's default order with no error, so a sweep written with one of those
  looks sorted and is not. Nothing validates the token locally. This is what
  `easyvista_python_client/directory.py`'s `RECENT_TICKETS_SORT` relies on
  (closes open item O-DIR-1).
- `count_tickets` is the cheap way to check a filter: it sends `max_rows=1`
  and reads the envelope total without fetching records.
- `search_*` returns one page; `iter_*` pages until the server reports no
  `@next` or `max_records` is reached.

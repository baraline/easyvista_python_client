---
name: easyvista-ticket-actions
description: "Read and write the action log on an EasyVista ticket with easyvista_python_client — create_action, list_actions, iter_actions, get_action and update_action with PostAction, Action and ActionUpdate, including why there is no private-comment flag and what to do instead, how to recover a created action's id, how to page a whole log past the one-page cap, and how to resolve an action's note text, which the list endpoint does not return. Use for ticket followups, work notes, internal or private comments, progress entries or any per-ticket action history."
license: MIT
compatibility: "Requires Python 3.10+, easyvista-python-client, network access to an EasyVista Service Manager REST API, and a profile authorized for the actions sub-resource."
metadata:
  package: easyvista-python-client
  version: "0.2.0"
---

> **Sync and async.** Examples use `EasyvistaClient`. For `AsyncEasyvistaClient`,
> use `async with`, `await` every call, and `async for` over the `iter_*`
> methods — the method names and arguments are identical. See
> `easyvista-client-setup`.

Actions are EasyVista's per-ticket work log — the closest equivalent to a
followup. Five methods: `create_action(rfc, action)`, `list_actions(rfc)`,
`iter_actions(rfc)`, `get_action(action_id)` and `update_action(action_id,
update)`. The list and item shapes differ substantially, which is where most
mistakes come from.

## Two shapes of the same record

- `list_actions(rfc)` returns a **slim collection record**: by default it
  carries `ACTION_ID`, `ACTION_LABEL_FR`, `ACTION_NUMBER`, `DONE_BY_ID` and
  `EXPECTED_START_DATE_UT`, but **not** the note text, and not
  `CREATION_DATE_UT`/`LAST_UPDATE` either.
- Pass `fields=` to widen that projection in one request instead of an item
  fetch per action: `list_actions(rfc, fields=["ACTION_ID",
  "ACTION_TYPE_ID", "CREATION_DATE_UT", "LAST_UPDATE", "DONE_BY_ID"])`
  returns those columns top-level on every row. The note text stays
  unreachable this way — `DESCRIPTION`/`COMMENT` are Memo sub-resources and
  come back as HREF objects under any projection — and `fields="*"` is
  **not** a wildcard, it silently reduces to `ACTION_ID` alone.
- `iter_actions(rfc)` is `list_actions` with paging: same records, same
  `fields=` projection, but it follows `@next` until the server runs out
  instead of stopping at one page. Use it whenever a ticket's **complete** log
  matters; see the pagination gotcha below.
- `get_action(action_id)` returns a **fuller item record** whose `DESCRIPTION`
  and `COMMENT` are memo href objects — that is, `action.description` is a
  `dict` with an `HREF`, not a string, until something resolves it.
- The note text supplied as `PostAction.description` comes back through
  **`DESCRIPTION`**, not `COMMENT`.
- The simplest way to get resolved bodies is `client.get_ticket_context(rfc)`,
  which fetches each action item-level and resolves its memo for you — see
  `easyvista-reporting-and-context`.

## "Private" comments: there is no such feature

**Do not tell a user this package can post a private comment.** An action
carries no visibility flag — the complete item-level record was captured
field by field and holds no public/private boolean — so there is no
argument for it on `PostAction` and nothing for the client to expose.

`action_type_id` is the only per-action discriminator that exists. If a
deployment separates internal notes from customer-facing ones, it does so with
distinct action types — but that is a property of **that deployment**, not
of EasyVista's API, and the API cannot reveal which type is which:

- `GET action-types` answers **403** on a standard profile, so the type table
  cannot be enumerated.
- Nothing on an action record states what its type *means*.
- **There is no naming convention to pattern-match.** Brackets in
  `ACTION_LABEL_*` mark an *untranslated* label: on a single-language instance
  the unpopulated language columns echo the default-language text wrapped in
  `[...]`. `localized_label` already skips them. They carry no visibility
  meaning — do not read `[...]` as "restricted".

The honest answer to "how do I post an internal note?" is: **ask the EasyVista
administrator which action type id to use**, pin it in configuration, and pass
it.

```python
from easyvista_python_client import EasyvistaClient, PostAction

INTERNAL_NOTE_TYPE_ID = 20  # from YOUR administrator -- not discoverable

with EasyvistaClient.from_env() as client:
    client.create_action(
        "YOUR_RFC_NUMBER",
        PostAction(
            action_type_id=INTERNAL_NOTE_TYPE_ID,
            description="Internal: credentials rotated.",
        ),
    )
```

To reconcile what the administrator says against the data, list the types a
ticket already uses. Most will be workflow-generated steps, not human notes —
those carry an empty `DONE_BY_ID`.

```python
from easyvista_python_client import EasyvistaClient

with EasyvistaClient.from_env() as client:
    for action in client.iter_actions("YOUR_RFC_NUMBER"):
        action_type = action.reference("ACTION_TYPE")
        print(action_type.id, action_type.display, action.done_by_id)
```

## Editing an action

`update_action(action_id, ActionUpdate(description=...))` edits an existing
action's note (`comment` is also available, for a deployment configured the
other way round). Two asymmetries worth knowing:

- Unlike `create_action`/`list_actions`, which are ticket-scoped
  (`rfc_number`), `update_action` is keyed on the **action id alone** — it
  calls the top-level `PUT actions/{id}`, not a
  `requests/{rfc}/actions/{id}` path.
- An action can be **edited but not deleted**: `DELETE actions/{id}` is
  refused with HTTP 403, so there is deliberately no `delete_action`.

## Discover the ids first

`action_type_id` and `group_id` are instance-specific. Read them off existing
actions before writing.

```python
from easyvista_python_client import EasyvistaClient

with EasyvistaClient.from_env() as client:
    for action in client.list_actions("YOUR_RFC_NUMBER"):
        print(action.action_id, action.reference("ACTION_TYPE").display)
```

## Procedure

1. List existing actions to learn the instance's action types and groups.
   Which type ids (if any) mean "internal" is NOT discoverable from the API --
   ask the administrator (see above).
2. Build a `PostAction`: identify the type with `action_type_id` (or
   `action_type_name`) and the assigned group with `group_id` (or
   `group_name`); put the note in `description`.
3. `create_action(rfc, action)`.
4. To address the action you just created, diff `list_actions` across the
   call — the create response cannot give you the id (see Gotchas).
5. To read note text, either call `get_action` and resolve the memo href with
   `resolve_memo`, or take `get_ticket_context(rfc)` and read
   `context.actions`.
6. To edit an action's note afterwards, call `update_action(action_id,
   ActionUpdate(description=...))` — by the action id alone, not the ticket.

## Examples

```python
from easyvista_python_client import EasyvistaClient, PostAction

with EasyvistaClient.from_env() as client:
    action = client.create_action(
        "YOUR_RFC_NUMBER",
        PostAction(
            action_type_id=1,
            group_id=1,
            description="Called the user back; printer power-cycled.",
        ),
    )
    print(action.href)
```

`action_type_id=1` and `group_id=1` above are placeholders — use the ids the
discovery block printed for your instance.

```python
from easyvista_python_client import EasyvistaClient, PostAction

with EasyvistaClient.from_env() as client:
    rfc = "YOUR_RFC_NUMBER"

    # The create response carries no ACTION_ID, so diff the list around it.
    before = {a.action_id for a in client.list_actions(rfc)}
    client.create_action(rfc, PostAction(action_type_id=1, description="Triaged."))
    after = client.list_actions(rfc)
    created = [a for a in after if a.action_id not in before]
    print([a.action_id for a in created])
```

```python
from easyvista_python_client import EasyvistaClient

with EasyvistaClient.from_env() as client:
    action = client.get_action(12345)

    # On the item-level record the note is a memo href, not a string.
    body = action.description
    if isinstance(body, dict) and body.get("HREF"):
        body = client.resolve_memo(body["HREF"])
    print(body)
```

```python
from easyvista_python_client import EasyvistaClient

with EasyvistaClient.from_env() as client:
    context = client.get_ticket_context("YOUR_RFC_NUMBER")
    for action in context.actions:
        print(action.action_id, action.description)
```

```python
from easyvista_python_client import ActionUpdate, EasyvistaClient

with EasyvistaClient.from_env() as client:
    # Keyed on the action id alone -- NOT the ticket's rfc_number.
    client.update_action(
        12345, ActionUpdate(description="Corrected: printer power-cycled twice.")
    )
    # The PUT's own response body has never been captured, so do not read the
    # returned Action's fields -- re-read instead.
    print(client.get_action(12345).description)
```

```python
from easyvista_python_client import EasyvistaClient

with EasyvistaClient.from_env() as client:
    # Project timestamps and author onto the list in one request instead of
    # an item fetch per action.
    actions = client.list_actions(
        "YOUR_RFC_NUMBER",
        fields=["ACTION_ID", "ACTION_TYPE_ID", "CREATION_DATE_UT", "DONE_BY_ID"],
    )
    for action in actions:
        print(action.action_id, action.created_at, action.done_by_id)
```

## Gotchas

- **`create_action` gives you no usable id.** The live create response is an
  HREF naming the **parent request**, with no `ACTION_ID`. The model's
  href-derivation deliberately declines to fire (the tail is an RFC number,
  not a numeric id) rather than inventing one. Diff `list_actions` across the
  call. `integration_tests/test_live_ticket_history.py` shows the pattern.
- `list_actions` does not return note text. A rendering built from the list
  alone has empty bodies.
- `action.description` and `action.comment` are `str | dict | None`. Check
  the type before treating either as text.
- `action.action_type` is a nested object on the live API, not a string. Use
  `action.reference("ACTION_TYPE").display` for the label.
- Resolving every body costs two extra requests per action (item fetch, then
  memo). `get_ticket_context(rfc, resolve_action_bodies=False)` skips it when
  you only need the list.
- A profile restriction on the actions sub-resource surfaces as
  `EasyvistaAuthError` (403); the context bundle degrades to `[]` rather than
  failing.
- `update_action` takes only an `action_id`, no `rfc_number` — passing the
  nested `requests/{rfc}/actions/{id}` shape (as `create_action` and
  `list_actions` do) is not how this one works, and the nested form is
  rejected with HTTP 403 anyway.
- `list_actions(fields=...)` has two silent footguns: `fields="*"` is not a
  wildcard (it reduces to `ACTION_ID` alone), and a dotted path like
  `"DESCRIPTION.HREF"` is silently dropped rather than raising.
- **`list_actions` returns ONE page and does not paginate.** The cap is
  `config.default_max_rows`; a ticket with more actions than that is truncated
  with **no error**, and the call discards the envelope's total so nothing in the
  result reveals it. A freshly created ticket already carries about twelve
  actions (most workflow-generated), so a busy ticket crosses a default cap
  easily. The same cap truncates `get_ticket_context`'s `actions` and
  `TicketContext.to_markdown()`'s rendered log — for a comment sync, that means
  silently missing comments on exactly the busiest tickets. **Use
  `iter_actions(rfc)`** when a whole log matters, or raise
  `EasyvistaConfig.default_max_rows` to widen the single page.
- **`iter_actions`' pagination is not live-verified.** It assumes the
  `offset`/`@next` contract every other search on this API follows, but unlike
  `iter_tickets` that has not been measured on the `actions` endpoint. If the
  endpoint ignores `offset`, page two repeats page one and the sweep never
  terminates. Bound it with `max_records` the first time you point it at a
  ticket whose action count you do not already know.
- **`update_action`'s return value is an unverified echo.** The PUT's response
  body has never been captured, and the parser falls back to the raw body when
  there are no records — so if the API answers empty or HREF-only, you get an
  `Action` whose every field is `None`. Re-read with `get_action` instead of
  reading fields off the returned object.
- `Action` names its timestamps `created_at`/`updated_at` where `Request` and
  `Employee` use `creation_date_ut`/`last_update` for the identical wire
  columns. `getattr(record, "last_update")` raises `AttributeError` on an
  `Action`; for code spanning record types, go through `classify_fields()` or
  `.reference()`, where the wire alias is uniform.

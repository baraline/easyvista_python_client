---
name: easyvista-ticket-actions
description: "Read and write the action log on an EasyVista ticket with easyvista_python_client — create_task and PostTask (the one call that posts a COMMENT: a task is an action born already ended, so its text shows in the history), plus create_action, list_actions, iter_actions, get_action and update_action with PostAction, Action and ActionUpdate. Covers why there is no private-comment flag and that visibility is the action TYPE instead, how to recover a created action's id, how to page a whole log past the one-page cap, and how to resolve an action's note text, which the list endpoint does not return. Use for ticket comments, followups, work notes, internal or private comments, progress entries or any per-ticket action history."
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
  `CREATION_DATE_UT`/`LAST_UPDATE` either. (Which language column the default
  projection returns was measured on one French instance and may differ on
  yours.)
- **Read `action.label`, never `action.action_label_fr`.** `label` is a
  property that scans every `ACTION_LABEL_<lang>` column in
  `DEFAULT_LANGUAGE_ORDER` and skips untranslated `[placeholder]` values. On a
  single-language instance the *other* language columns echo the primary text
  wrapped in brackets, so on an English deployment `action_label_fr` is
  `"[Customer Comment]"` — not `None` — and reading it directly yields the
  placeholder. Being a property, it is not a serialized field: it never appears
  in `model_dump()` or `classify_fields()`. For a different language order call
  `localized_label(action.model_dump(by_alias=True), "ACTION_LABEL",
  languages=("_GE",))`.
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

## "Private" comments: two channels, but no visibility flag

**An action has two independent text channels**, `description` and `comment`,
each addressable afterwards as its own memo (`actions/{id}/description`,
`actions/{id}/comment`). `PostAction` writes both, and both persist from a
single create — verified live 2026-08-28: each read back with exactly the text
sent. The instance's own OpenAPI declares both on the create body and its
example populates both.

```python
PostAction(
    action_type_id=YOUR_TYPE_ID,
    group_id=YOUR_GROUP_ID,
    description="Visible to the requester.",
    comment="Internal working note.",
)
```

## To post a comment, create a TASK — not an action

**This is the single most important thing in this skill.** A task and an action
are the same underlying record; they differ in the state they are born in, and
that decides whether anyone ever sees the text.

| | `create_action` | `create_task` |
|---|---|---|
| endpoint | `POST requests/{rfc}/actions` | `POST requests/{rfc}/tasks` |
| body | wrapped | **flat** at the root |
| born | **open** — work still to do | **ended** — work reported |
| in the UI | pending row, text **not** shown | history entry **with** its text |
| needs ending | yes | no |
| `parent_action_id` | required for an internal-note type | not needed |
| use for | work someone must still do | **comments** |

```python
from easyvista_python_client import PostTask

client.create_task(
    "YOUR_RFC_NUMBER",
    PostTask(
        action_type_id=YOUR_INTERNAL_TYPE_ID,
        group_id=YOUR_GROUP_ID,
        description="Internal working note.",
    ),
)
```

Verified live 2026-08-28: tasks came back with `END_DATE_UT` and
`STATUS_ID_ON_TERMINATE` already set, and their text appeared in the history.
`action_type_id` and one of `group_id` / `group_name` / `group_mail` are
mandatory; `PostTask` refuses a body missing either rather than letting the
server answer with a 590 that names no field.

**If a caller creates an action and stops**, nothing is lost — the text is
stored — but the row renders without it until the action is ended. Ending is
vendor-documented as `PUT actions/{rfc_number}` with an `end_action` wrapper
and dates in the instance's `DATE_FORMAT` (`dd/mm/yyyy`, **not** ISO 8601) —
[docs](https://docs.easyvista.com/docs/rest-api-finish-an-action-attached-to-an-incident-request.md).
**This package does not implement it**: every documented form returned
`590 Action not found` on the verified instance, including for a user who could
end the same action in the UI. That is an instance/profile restriction to raise
with an administrator — and for comments it never arises, because a task is
born ended.

## Visibility is by action TYPE, and the labels say which

There is no per-action visibility flag — 88 item-level columns, no
public/private boolean. The distinction lives in the **type**. On the verified
instance: **94** = `Commentaire [Public]` / `Customer Comment`, **95** =
`Note Interne [Privé]` / `Internal Note`.

**There is no reference table, and the ids are still discoverable.** Both
halves matter:

- The instance's own OpenAPI declares **no `action-types` route at all** (read
  from `GET {api_root}/swagger`, 2026-08-27, EasyVista 2025.3). `GET
  action-types` answers 403, but on this API a forbidden path and an unknown
  one both answer 403, so that response never told you which it was. There is
  nothing to enumerate and nothing for an administrator to unblock here.
- Every action record nevertheless carries its own `ACTION_TYPE_ID` beside
  translated `ACTION_LABEL_*` columns, so the types an instance actually uses
  are recoverable from the data — `client.discover("ACTION_TYPE")` does exactly
  that sampling for you (see `easyvista-instance-discovery`).

Two bracket conventions appear in `ACTION_LABEL_*` and they mean **opposite**
things:

| In `ACTION_LABEL_*` | Means | Example |
|---|---|---|
| whole label wrapped in brackets, echoing another language | untranslated placeholder, no meaning — `localized_label` discards it | `EN='[Analyse et résolution]'` on a French instance |
| bracketed **suffix** on distinct text, with real sibling translations | a genuine marker written by whoever configured the instance | `FR='Commentaire [Public]'` beside `EN='Customer Comment'` |

The test is whether the siblings are real translations or brackets — not
whether brackets are present. An earlier revision of this package conflated
the two and deleted the true finding. Do not read every `[...]` as noise, and
do not read one as "restricted" either: a marker is a convention on one
deployment, not an API feature. Nothing on an action record states what its
type *means*, so confirm the mapping with whoever administers the instance
before relying on it for anything that must not leak.

The honest answer to "how do I post an internal note?" is: **ask the EasyVista
administrator which action type id to use**, pin it in configuration, and pass
it.

```python
from easyvista_python_client import EasyvistaClient, PostAction

# Read off YOUR instance with the block above and confirmed with its
# administrator. 94/95 are what the verified instance uses; not portable.
INTERNAL_NOTE_TYPE_ID = 95
YOUR_GROUP_ID = 3

with EasyvistaClient.from_env() as client:
    client.create_action(
        "YOUR_RFC_NUMBER",
        PostAction(
            action_type_id=INTERNAL_NOTE_TYPE_ID,
            group_id=YOUR_GROUP_ID,
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
  calls the top-level `PUT actions/{id}`. That is not a permission quirk: no
  `requests/{rfc}/actions/{id}` route exists on this API at all.
  `POST requests/{rfc}/actions` is create-only; the list, item and update
  operations live on `/actions` and `/actions/{id}`. A 403 here would not have
  told you which, because this API answers 403 for an unknown path as well as
  for a denied one.
- An action can be **edited but not deleted**: this API declares only GET, PUT
  and PATCH on `actions/{id}` — there is no DELETE verb — so there is
  deliberately no `delete_action`.

## Discover the ids first

`action_type_id` and `group_id` are instance-specific. One call finds both —
see `easyvista-instance-discovery`:

```python
from easyvista_python_client import EasyvistaClient

with EasyvistaClient.from_env() as client:
    for found in client.discover("ACTION_TYPE"):
        print(found.id, found.label, found.count)
    for group in client.discover("GROUP"):
        print(group.id, group.label)
```

Sampling by hand is the same thing spelled out. Most rows are
workflow-generated steps rather than human notes — those carry an empty
`DONE_BY_ID`:

```python
from easyvista_python_client import EasyvistaClient

with EasyvistaClient.from_env() as client:
    for action in client.iter_actions("YOUR_RFC_NUMBER"):
        print(action.action_id, action.action_type_id, action.label,
              action.done_by_id)
```

The **ids** are discoverable either way. Which one means "internal note" and
which means "customer comment" is a label a human still has to read: confirm it
with the EasyVista administrator, then pin the ids in your own configuration.

## Procedure

1. Discover the instance's action type ids and group ids, with their labels
   (see "Discover the ids first" above). Which id means "internal" is a
   per-deployment configuration choice: confirm it with the EasyVista
   administrator, then pin it in your own configuration.
2. Decide what the record IS, because it decides the call:
   - **a comment** — something to be read — go to 3a;
   - **work someone must still do** — go to 3b.
3. a. `create_task(rfc, PostTask(action_type_id=..., group_id=..., description=...))`.
      This is the default and covers every comment, note and progress update.
      A task is the same record as an action but born **ended**, so its text
      appears in the ticket history immediately. `action_type_id` (or
      `action_type_name`) and one of `group_id` / `group_name` / `group_mail`
      are mandatory; `PostTask` refuses a body missing either locally, rather
      than letting the server answer with a 590 that names no field.

   b. `create_action(rfc, PostAction(action_type_id=..., group_id=..., description=...))`.
      Use it **only** for work still to be done. The action is created *open*,
      and an open action renders in the UI as a pending row with its text NOT
      shown, which reads as though the note was lost. Ending it afterwards
      needs `PUT actions/{rfc_number}`, which returned `590 Action not found`
      for every documented form on the verified instance — so an action you
      create is one you may not be able to end from the API.
4. To address the action or task you just created, diff `list_actions` across
   the call — the create response cannot give you the id (see Gotchas).
5. To read note text, either call `get_action` and resolve the memo href with
   `resolve_memo`, or take `get_ticket_context(rfc)` and read
   `context.actions`.
6. To edit a note afterwards, call `update_action(action_id,
   ActionUpdate(description=...))` — by the action id alone, not the ticket.

## Examples

Posting a comment — the common case, and a **task**, not an action:

```python
from easyvista_python_client import EasyvistaClient, PostTask

with EasyvistaClient.from_env() as client:
    client.create_task(
        "YOUR_RFC_NUMBER",
        PostTask(
            action_type_id=1,
            group_id=1,
            description="Called the user back; printer power-cycled.",
        ),
    )
```

Only when the work is genuinely still to be done, an **action** instead. It is
born open, so its text does not render in the history until it is ended — and
ending it is 590-blocked on the verified instance:

```python
from easyvista_python_client import EasyvistaClient, PostAction

with EasyvistaClient.from_env() as client:
    action = client.create_action(
        "YOUR_RFC_NUMBER",
        PostAction(
            action_type_id=1,
            group_id=1,
            description="Chase the supplier for a replacement drum.",
        ),
    )
    print(action.href)
```

`action_type_id=1` and `group_id=1` above are placeholders — use the ids
`client.discover("ACTION_TYPE")` and `client.discover("GROUP")` printed for
your instance.

```python
from easyvista_python_client import EasyvistaClient, PostAction

with EasyvistaClient.from_env() as client:
    rfc = "YOUR_RFC_NUMBER"

    # The create response carries no ACTION_ID, so diff the list around it.
    before = {a.action_id for a in client.list_actions(rfc)}
    client.create_action(
        rfc, PostAction(action_type_id=1, group_id=1, description="Triaged.")
    )
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

- **`PostAction` requires an action type and a group.** Tier 1 lists both as
  required on the create-an-action route, so a body missing either is refused
  at construction rather than drawing an HTTP 590 that names no field. Name the
  type with `action_type_id` (preferred), `action_type_name` or
  `action_type_guid`, and the group with `group_id`, `group_name` or
  `group_mail` — any one of each is enough, and a field passed through
  `extra_payload` counts. `PostTask` has always enforced the same rule on the
  same vendor sentence. `parent_action_id` is also available, for an action of
  a child type hanging off its parent.
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

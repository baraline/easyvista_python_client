# EasyVista REST API — vendor reference

The facts this package depends on, each tagged with the kind of evidence
behind it, so a reader can tell "the vendor says so" from "we saw it once".

**Baseline: EasyVista 2025.3.** Measured 2026-08-27 against the development
instance: `GET {api_root}/swagger` returns `info.description = "Easyvista
Service Manager REST API - 2025.3"` (OpenAPI 3.1.0, spec version 1.9.4,
100 paths).

Two traps, both of which cost time to rediscover:

* The route is `{api_root}/swagger` — that is `/api/v1/{account}/swagger`.
  The bare-host `{host}/swagger` returns 403.
* **A GET to it answers HTTP 201**, not 200. Code gating on `== 200` skips
  it in silence.

## Claim tiers

| Tier | Meaning | Trust |
|------|---------|-------|
| 1 — Vendor-documented | docs.easyvista.com states it | Portable across deployments |
| 2 — Spec path | Declared in the instance's OpenAPI `paths` | Authoritative for this deployment |
| 3 — Spec schema | Declared in the instance's OpenAPI `components.schemas` | **Illustrative only** |
| 4 — Measured | Observed live, one instance, one date | May not generalise |

Tier 3 is the subtle one. The instance's own `POST /requests` schema declares
`required: []` and lists `E_TEST_REST` / `E_TEST_REST_2` — that deployment's
private custom columns. Those schemas are generated from examples, not from a
normative contract. They look authoritative; they are not.

## Create a ticket — `POST /requests` (tier 1)

Source: <https://docs.easyvista.com/docs/rest-api-create-an-incident-request>
(read 2026-08-27). Envelope key `requests`, an array. Field names are
case-insensitive. Success is HTTP 201 with an `HREF` to the created resource.

**Required: `catalog_guid` OR `catalog_code`.** `catalog_guid` is documented
as the preferred subject identifier. Every other field is optional.

| Field | Type | Note |
|-------|------|------|
| `catalog_guid` / `catalog_code` | string | Subject; guid preferred |
| `assetid` / `assettag` / `asset_name` | string | Asset, in priority order |
| `ci_id` / `ci_asset_tag` / `ci_name` | string | Configuration item, in priority order |
| `department_id` / `department_code` | string | Requestor department |
| `location_id` / `location_code` | string | Requestor location |
| `description` | string | |
| `title` | string | 2018.1.183.0+ |
| `impact_id` | integer | 2020.2.122.2+ |
| `urgency_id` | integer | |
| `severity_id` | integer | |
| `origin` | string | e.g. Phone, Email |
| `external_reference` | string | |
| `parentrequest` | string | |
| `phone` | string | |
| `recipient_id` / `recipient_identification` / `recipient_mail` / `recipient_name` | string | Priority order |
| `requestor_identification` / `requestor_mail` / `requestor_name` | string | Priority order |
| `submit_date` | string | Respects the employee location's format |
| `e_*` | various | Custom fields, 2018.1.183.0+ |

**Not in the table above, and not vendor-documented at all: `workflow_start`**
(tier 3, illustrative only). It appears only in the instance's own OpenAPI
schema for this route (`components.schemas`, read 2026-08-27): boolean,
"Optional. If true, starts the workflow for the created incident." Per the
tier table above, that schema is example-derived and not a normative
contract, so treat this field as unverified until tested against the
deployment you use it on.

## Create an action — `POST /requests/{rfc_number}/actions` (tier 1)

Source: <https://docs.easyvista.com/xwiki/bin/view/Documentation/Integration/WebService%20REST/REST%20API%20-%20Create%20an%20action%20for%20an%20incident-request/>
(read 2026-08-27).

Required: `action_type_id`, and one of `group_id` / `group_mail` /
`group_name`. Optional includes `comment`, `description`, `creation_date_ut`,
`contact_*`, `done_by_*`, `expected_start_date_ut`, `expected_end_date_ut`,
`max_intervention_date_ut`, `parent_action_id`, `action_type_guid` (2023.4+).
Action status is set to "In progress" automatically.

`PostAction` declares `action_type_id`, `action_type_name`, `action_type_guid`,
`group_id`, `group_name`, `group_mail`, `parent_action_id`, `description` and
`comment`, and enforces the required rule above at construction. The `contact_*`
/ `done_by_*` / date fields are deliberately **not** declared — nothing in this
package exercises them and `extra_payload` reaches them today.

## Create a task — `POST /requests/{rfc_number}/tasks`

**The vendor page has NOT been transcribed here.** It exists
(<https://docs.easyvista.com/docs/rest-api-create-a-task-for-an-incident-request.md>,
cited in `PostTask`'s docstring) but nobody has read its field table into this
file, so `PostTask`'s eleven declared fields cannot be diffed against tier 1
from inside the repository. That is a gap, not a finding.

What the instance's own OpenAPI declares for this route — **tier 3,
illustrative only** (read 2026-08-31): `action_type_id` (string), `group_mail`,
`Elapsed_Time`, `time_cost`, `contractual_cost`, `description`,
`creation_date_ut`, `start_date_ut`, `end_date_ut`, `available_field_1`,
`available_field_6`, with `required: ["action_type_id", "group_mail"]`. Three
notes on reading that: it is the only body schema in this instance's spec that
declares a non-empty `required`, which is corroboration for `PostTask`'s guard
and not proof of it; it omits `group_id`, `group_name` and `comment`, which
`PostTask` declares and which an example-derived schema would omit anyway; and
it lists `available_field_1`/`_6`, which `PostTask` does not declare and which
`extra_payload` reaches.

### A task is write-only as a resource, and read back as an action

**Tier 2, read 2026-09-02** on the development instance (100 paths), and
independently the same day on a second deployment (also 2025.3, also 100
paths). Both declare exactly:

| Path | Verbs |
| --- | --- |
| `/requests/{rfc_number}/tasks` | **POST only** |
| `/requests/{rfc_number}/actions` | POST only |
| `/actions` | GET |
| `/actions/{id}` | GET, PATCH, PUT |
| `/actions/{id}/{comment}` | GET |

There is **no read route for a task** — no `GET /requests/{rfc}/tasks`, no
`/tasks/{id}`, nothing under any other spelling. The only timeline reads are
the three `/actions` routes. So a task is *written* through `tasks` and *read
back* through `actions`, and that is the whole story: a task and an action are
the same row in the same table, differing only in the state they are born in
(open vs already ended). This is why the package has `list_actions` and
deliberately **no `list_tasks`/`iter_tasks`** — there is no route to wrap.

A GET against the tasks path answers `403 "Unauthorized Method for your
profile"`, which per *Route topology* above proves nothing either way; the
spec's `paths` is what settles it.

**`create_task` returns an `Action`.** That is where a reader first meets the
confusion, and the annotation is correct rather than sloppy: there is no task
resource to model, so there is no `Task` read model and could not be one.

### The effort columns, and why they do not discriminate task from action

Five columns on an action record — `ELAPSED_TIME`, `TIME_COST`,
`CONTRACTUAL_COST`, `START_DATE_UT`, `END_DATE_UT` — are declared on `Action`
as of 0.3.0. Until then they arrived only as `extra="allow"` extras: untyped
strings, with a French decimal comma on the two costs.

**Tier 4, measured 2026-09-02, 1500 action rows on the development instance**
(one instance, one date, so it may not generalise), corroborated by an
independent measurement the same day on that second deployment (1465 timeline
entries across 120 tickets), which agreed on every point below.

**`""` and `"0"` are different answers.** `""` means the column does not apply
to this record; `"0"` (or `"0,00"`) means it applies and is zero.

| Column | `""` | zero | non-zero |
| --- | --- | --- | --- |
| `ELAPSED_TIME` | 384 | 895 (`'0'`) | 221 |
| `TIME_COST` | 691 | 808 (`'0,00'`) | 1 (`'99,00'`) |
| `CONTRACTUAL_COST` | 691 | 808 (`'0,00'`) | 1 (`'129,00'`) |

A parser that maps both to `0`, or both to `None`, destroys the only signal
that says whether a record tracks effort. `Action` preserves it: `None` for
`""`, `0` / `Decimal("0.00")` for the zeroes.

**The shape heuristic is false in both directions.** It is tempting to read
"workflow rows carry `WORKFLOW_ID`/`STAGE_ID` with `ELAPSED_TIME='0'` and
`'0,00'` costs, task-shaped rows carry none of it and empty effort" as a
task/action discriminator. Measured, it fails both ways:

* **173 of 1500** rows carried a `WORKFLOW_ID` *and* an empty `ELAPSED_TIME`
  — 126 of them the type-20 `Analyse et résolution` workflow step. So
  "workflow row ⇒ effort is `'0'`" is false.
* **171 of 1500** rows carried no `WORKFLOW_ID` *and* a non-empty
  `ELAPSED_TIME`. Among them **39 of the 49** type-94 `Commentaire [Public]`
  rows — ordinary public comments — usually with `ELAPSED_TIME='1'`. One
  public comment carried `ELAPSED_TIME='12'`, `TIME_COST='99,00'` and
  `CONTRACTUAL_COST='129,00'`. So "effort recorded ⇒ not a comment" is false,
  and a filter built on it drops four public comments in five.

`ACTION_TYPE_ID` alone does not discriminate either, which the second
deployment measured directly: type 94 appeared in both shapes there (74 rows
with a `PARENT_ACTION_ID`, 18 without; 37 with a non-zero `ELAPSED_TIME`, 55
without).

What an effort column reports is **whether effort was recorded**, not what kind
of record this is. No column examined across those 1500 rows recorded which
route created it — stated as a measurement, not as a proof of absence: the
item-level record carries 88 columns, not all of which were tallied, and a
deployment may populate one this instance leaves empty. If you find a column
that does discriminate, it belongs here.

**What *is* clean: `WORKFLOW_ID`.** 1500/1500 rows — a `WORKFLOW_ID` is set iff
the workflow engine produced the row. No row of the conversation types (94
`Commentaire [Public]`, 95 `Note Interne [Privé]`, 7 `Appel`) carried one.
`Action.is_workflow_generated` exposes exactly that and nothing more. Deciding
which of the remaining types count as conversation is per-deployment policy —
an `action_type_id` allowlist — and stays with the caller.

**Side finding, tier 4, same measurement: `ACTION_LABEL_*` is the label of the
workflow *step*, not the name of the action type.** Type 20 appeared as
`Analyse et résolution` (126 rows), `Traitement` (10), `Traitement du refus`,
`Traitement de la demande`, `test` and `notif`; type 30 as `stocker le groupe
d'implémentation`, `Mise à jour SLA` and `sauvegarde`; type 82 under two
labels. So for **workflow** types the label varies row to row and cannot be
used as a type name. For the non-workflow types (94, 95, 7) it was stable and
is the type's real name. This qualifies the *Visibility is by action type*
note: `discover("ACTION_TYPE")` recovers real names for the human types, and
per-step text for the workflow ones.

**Types 14, 27 and 28 have an empty `ACTION_LABEL_*` in every language column**
— all six on the list projection and all twelve (`_EN`, `_FR`, `_GE`, `_IT`,
`_PO`, `_SP`, `_L1`..`_L6`) on the item GET. There is no `action-types` route
to ask, so on this deployment those ids **cannot be named through the API at
all**. What is known about 28 is behavioural, not nominal: it is the row that
carries the text passed to `close_ticket(comment=...)`, so it must not be
filtered out of a timeline read.

Also worth recording without acting on it: the instance's `POST /assets` schema
(tier 3) titles its array `asset` while its own example uses `assets`, which is
what this package sends and what works. That is an inconsistency inside one
spec; the descriptor is not changed on it.

## Query grammar (tier 1)

Source: <https://docs.easyvista.com/xwiki/bin/view/Documentation/Integration/WebService%20REST/REST%20API%20-%20See%20a%20list%20of%20incidents-requests/>
(read 2026-08-27).

| Parameter | Syntax / note |
|-----------|---------------|
| `max_rows` | Integer. Default 100. |
| `offset` | Paging offset. Envelope carries `@previous` / `@next`. |
| `sort` | `field1[+asc\|+desc],field2[+asc\|+desc]` |
| `fields` | Comma-separated projection |
| `search` | Field-based filter |
| `~` / `!~` / `!` | Contains / not-contains / not-equals (Oxygen 1.7+). Counter-evidence, tier 4 — measured live 2026-08-17: `~` behaves as a *pattern* operator and needs an explicit `*`, so `FIELD~"value"` degenerates to an exact match and quietly returns the wrong rows. `ev_contains_filter` supplies the wildcards by default; on a deployment that follows the tier-1 reading and compares `*` literally, that default returns zero rows with HTTP 200 — pass `wildcard=None` (or `wildcard="%"`). Neither failure is visible in the response. See its docstring in `easyvista_python_client/filters.py`. |
| `is_null` / `is_not_null` | Oxygen 2.1.2+ |
| `formatDate` | Oxygen 1.7+ |

`+` in a query string decodes to a space, so the documented `RFC_NUMBER+desc`
and this package's measured `"RFC_NUMBER DESC"` are the same token.
Dotted sub-field access works in both `sort` and `search`
(`employee.last_name+desc`, `search=employee.e_mail:...`), and relative date
tokens exist (`search=field:last_week`). Neither is exposed by this package.

Envelope: `HREF`, `record_count`, `total_record_count`, `records`, `@next`.

## Ticket workflow — what each documented write does to it (tier 1, read 2026-10-02)

"A workflow is a process that handles a type of tickets, arranged in a sequence of
actions performed in steps." … "Advancing through the steps of a workflow changes the
status of a ticket." — https://docs.easyvista.com/docs/workflow.md (also
references-tables.md: "The change of a meta-status performs actions in the workflow.")

| Write | Effect on the workflow | Evidence |
| --- | --- | --- |
| `POST /requests` (create) | **starts** it | "3. The workflow associated with the ticket is started." — rest-api-create-an-incident-request.md |
| `POST /requests/without-workflow` (virtual agent) | does not start it | "3. The workflow associated with the ticket will not be started." — ev-service-manager-rest-api-create-ticket-via-virtual-agent.md |
| `PUT /requests/{rfc}` `{"closed": …}` | **interrupts** it, whatever status is sent | "1. The workflow of the ticket is interrupted." (sub-bullet: "workflowstop function, with **rfc_number** passed as a parameter"); then status = "the final status of the ticket"; "The unfinished actions associated with the ticket are deleted." (`end_date_ut = NULL` iff `delete_actions = True`; otherwise `end_date` is the "Closing date of open actions"); "An anticipated closing action associated with the ticket is inserted."; "Any further modification is impossible." — rest-api-close-an-incident-request.md. An omitted `status_GUID` defaults to the Closed meta-status (same page). |
| `PUT /actions/{rfc}` `{"end_action": …}` | **advances** it when the action is a workflow step | REST page: "If the action_id is not specified, all the ongoing actions associated with the rfc_number are ended." — rest-api-finish-an-action-attached-to-an-incident-request.md; it never mentions the workflow. UI Finish wizard: "The workflow will proceed to the next step." — action.md. Tier 4: 2026-09-01, one instance, 2/2 (step ended → ticket Résolu); a caller's own action, 3/3, no change. May not generalise. |
| `PUT /requests/{rfc}` `{"suspended"…}` / `{"restarted"…}` | not documented | "A suspend action for the ticket is created." / "Create a reopening action for the ticket." — nothing on open actions or status. rest-api-suspend-an-incident-request.md, rest-api-reopen-an-incident-request.md |
| Everything else (update a ticket, update/create an action or task, documents) | not documented | The update pages accept "all the fields … except" a list; no processing section. rest-api-update-an-incident-request.md, rest-api-update-an-action.md |

The vendor documents no REST write that sets a ticket's status outside the rows
above: the ticket update page excludes `status_id` from its body, with
`sd_catalog_id`, `initial_sd_catalog_id` and `parent_request_id`
(rest-api-update-an-incident-request.md). There is no status setter; this package
removed `set_status` (it was the close request). Not documented is not the same as
impossible — see the business-rule caveat below.

**The vendor documents no REST route that reassigns or transfers an action.** The
UI's "Assign action" button runs a wizard ("The action will automatically be
transferred." — action.md). `PUT /actions/{id}` with the group and/or the person is
allowed by the update page's "all the fields from the AM_ACTION table except those
mentioned below" rule, and its exclusion list does not name `GROUP_ID` or `DONE_BY_ID`
(rest-api-update-an-action.md, tier 1). This package does not refuse it, but its
effect on the action and on the workflow is **not yet measured**: allowed by the
documentation is not the same as shown harmless.

**Business rules can fire on any write** — "On Insert/On Update" of any record
(business-rule.md) — so a write this package does not gate is unclassified, not proven
neutral.

**The guard.** `easyvista_python_client.workflow` names what a write may do, and the
transport refuses it, before any request is sent, unless the call passes
`allow_workflow_effect=`. Named: the four bodies above on any path; on ticket routes,
status and catalog columns; on action routes, end date, type, parent,
workflow/stage/step and ticket links; ticket sub-routes other than
`actions`/`tasks`/`documents`. Not named: text, owner, group, done-by, impact,
urgency. A column deny-list cannot be complete, and this one says so.

* **A request counts as a read only when its method and every method-override header
  value are reads.** The method and the value of each of `X-HTTP-Method-Override`,
  `X-HTTP-Method` and `X-Method-Override` (any casing) must all be `GET`, `HEAD` or
  `OPTIONS`; otherwise it is classified as a write, so an override that says `GET`
  cannot hide one. Whether this API honours any of those headers is not recorded here.
* **Refused outright, whatever the method and whatever `allow_workflow_effect` says**
  (a `ValueError`, no request sent): a path with a dot segment (`.` or `..`, also
  percent-encoded), a percent-encoded slash or backslash (`%2F`, `%5C`), or a raw
  backslash. The HTTP client collapses a dot segment, so the request would reach a
  route other than the one checked; a server may read an encoded slash or a backslash
  as a path separator. Whether this server does is not measured — the check fails
  closed, and no API route needs any of them.
* **`end_action` reads the action first.** Unless `allow_workflow_effect` includes
  `WorkflowEffect.ADVANCES`, it makes one item read projecting `ACTION_ID` and
  `WORKFLOW_ID`, and refuses — with no end request sent — a workflow step
  (`WORKFLOW_ID` set), a record that comes back without the `WORKFLOW_ID` column at
  all (which cannot be told from a step), or a record naming a different `ACTION_ID`
  than the one asked for. `end_all=True` is refused outright without `ADVANCES`.
  Ending a caller's own action needs no opt-in. What separates a workflow step from
  a caller's action is `WORKFLOW_ID` (tier 4: 1500 of 1500 rows, 2026-09-02, one
  instance). The live check that an item read of an action carries the column:
  tier 4, 2026-10-02, one instance, may not generalise — the item read, with
  `fields=ACTION_ID,WORKFLOW_ID` and without it, named `WORKFLOW_ID` on a workflow
  step (set) and on a non-workflow action (present, empty). Whether an action
  created under a step by `create_action` carries one is unmeasured; if it does,
  ending it is refused too, the safe direction.

## Route topology (tier 2) — `GET {api_root}/swagger`, read 2026-08-27

**A 403 does not discriminate.** This API answers 403 for a path that does not
exist as well as for one a profile denies (measured; date not recorded). Every
"blocked" conclusion drawn from a status code alone is therefore unsound; the
spec's `paths` is what settles whether a route exists.

| Path | Verbs | Note |
| --- | --- | --- |
| `/requests/{rfc_number}/actions` | POST | create-only; no nested list, item or update |
| `/requests/{rfc_number}/tasks` | POST | create-only; **no task read route exists** — read them back through `/actions` |
| `/actions` | GET | the only action list |
| `/actions/{id}` | GET, PATCH, PUT | the only action item; **no DELETE** |
| `/actions/{id}/{comment}` | GET | `{comment}` is a memo-field *selector*, not a literal |
| `/requests/{RFC_NUMBER}/documents` | GET, POST | |
| `/requests/{RFC_NUMBER}/documents/{id}` | GET, DELETE | what this package sends by default |
| `/documents/{id}` | GET, DELETE | marked `deprecated`; opt in with `document_delete_path_style="top_level"` |
| `/departments/{id}/{comment}` | GET | `{comment}` is a memo-field *selector*, not a literal |

Reference tables that exist: `/status`, `/urgency` and `/urgency/{id}`
(**singular**; `/urgencies` is not declared), `/catalog-requests`,
`/catalog-requests-paths`, `/groups` (GET, POST), `/locations`, `/slas`,
`/domains`, `/suppliers`, `/departments`, `/employees`.

No route is declared for action-types, impact, severity, origin or priority:
those values are discoverable only by sampling records that carry them.

The package wraps roughly 10 of the spec's 100 paths.

## Routes present in the spec, not implemented here (tier 2)

Read from `GET {api_root}/swagger`, 2026-08-27.

* `PUT|PATCH /requests/{rfc_number}/close` — a dedicated close route exists
  (tier 2) taking a **flat** body (tier 3, illustrative only:
  `STATUS_GUID`, `END_DATE`, `CATALOG_GUID`, `DELETE_ACTIONS`, `COMMENT`).
  **O-CLOSE is CLOSED, in this package's favour.** The vendor documents closing
  as `PUT /requests/{rfc_number}` with a `{"closed": {...}}` wrapper — the
  route this package already sends — so the subpath is an alternate, not the
  canonical one, and there is nothing to switch to. Tier 1:
  https://docs.easyvista.com/docs/rest-api-close-an-incident-request.md
  The same page supplied two body fields the package had never declared
  (`end_date`, `catalog_GUID`), both now exposed on `close_ticket`.
* `PUT|PATCH /requests/{rfc_number}/suspend`, `/restart`.
* `GET /requests/{rfc_number}/{comment}` — the final segment is a **memo-field
  selector**, documented in the spec's own parameter description as "Memo
  field type, could be comment, description". Same shape on
  `GET /actions/{id}/{comment}`.
* `GET /problems`, `GET /configuration-items`, `GET /questionnaires`,
  `POST /tokens`, and the external-table routes `GET|POST /{E_Your_Table}`.
  These have no typed wrapper; `send()` and `list_reference_table(path)` reach
  every read-only one of them.
* The reference tables — `GET /status`, `/urgency`, `/locations`, `/groups`,
  `/slas`, `/suppliers`, `/domains`, `/catalog-requests` — are now reachable
  through `list_reference_table(path)` and `discover(name)`, which map each
  name to the route this deployment declares.

### `GET /catalog-requests` response columns — **tier 3, illustrative only**

`CODE`, `SD_CATALOG_ID`, `TITLE_EN`, `CATALOG_REQUEST_PATH`, plus nested
`MANAGER` and nested `SLA`. `CODE` is what `PostRequest.catalog_code` accepts
and `SD_CATALOG_ID` is what reads back as `Request.sd_catalog_id`. **There is
no `CATALOG_GUID` column** in the schema and none was observed live, so a
catalog GUID cannot be discovered from this route — build with `catalog_code`.
The vendor documents `catalog_guid` as the *preferred* identifier (tier 1) and
`close_ticket` accepts one; you simply cannot read one back.

## Memo content (tier 4)

Measured 2026-09-30 on one instance, may not generalise: a ticket's `COMMENT`
memo written through the API with HTML -- `<p>` paragraphs, an `<a>` anchor and
character references -- was stored byte for byte and read back identically
(the `DESCRIPTION` memo stayed empty), and the web UI rendered the `<p>`
elements as paragraphs. So a memo's format is whatever its writer sent, and the
API altered nothing in that sample. No vendor documentation of the memo format
is recorded here. `easyvista_python_client.content` converts memo HTML to and
from Markdown; see open item O-MEMOFORMAT for what is not yet known.

## Open items

* **O-MEMOFORMAT** -- the memo format rests on the one tier-4 sample above.
  Not yet known: what the web UI's own editor writes into a memo; whether the
  UI shows the newlines python-markdown puts between blocks as the whitespace
  HTML makes of them; and what the UI shows for a memo holding raw markup, a
  `<script>` or an unknown tag. Look for the vendor documentation first.

* **O-URG** — `PUT /requests/{rfc_number}` declares `Urgency_ID` as a
  **string** (tier 3). This package sent an **int** when it measured the 590
  that caused `RequestUpdate.urgency_id` to be removed. The exclusion may be a
  type mismatch we authored rather than an API limitation. Unresolved: settling
  it needs a live write. Same question for `severity_id`.
* **O-URGPATH** — the vendor documents `GET /urgencies`; the instance spec
  declares `GET /urgency`. Both return 200 live. Which is canonical is unknown.
* **O-CLOSE-DEFAULT** — **CLOSED at tier 1 (2026-10-02).** The vendor close page documents an omitted status_GUID as defaulting to the Closed meta-status. Not measured here.
* **O-COSTGROUP** — `TIME_COST` / `CONTRACTUAL_COST` are parsed by
  `models/common._parse_ev_decimal`, which accepts either decimal separator and
  **refuses a grouping separator** rather than guessing (`'1.234,56'` and
  `'1,234.56'` are the same amount under opposite conventions). Every amount
  observed live had exactly two fraction digits and no grouping (1500 rows,
  2026-09-02), so the refusal has never fired. It **also** refuses three or more
  fraction digits, for the same ambiguity (`'1,234'` could be `1.234` or a
  comma-grouped `1234`) — which means a genuinely 3-decimal currency is refused
  too. **Magnitude is not a trigger**: `'1000,00'` parses fine, since it carries
  no grouping separator. Because the descriptor validates a page in a list
  comprehension, a refusal fails a whole `list_actions` call, not one row. If a
  refused literal is ever seen, record it here and widen the pattern with
  evidence.
* **O-ACTIONTYPE28** — types 14, 27 and 28 have an empty `ACTION_LABEL_*` in
  every language column at both list and item level, and there is no
  `action-types` route, so nothing in the API can name them. Type 28 is known
  behaviourally (it carries `close_ticket(comment=...)` text) and 14 and 27 not
  at all. Settling this needs the EasyVista **admin console**, not the API: the
  administration screen listing action types, and specifically which type ids
  that deployment classes as *task* types. Nobody working on this package has
  console access; if you do, transcribe the list here.
* **O-TASKDOC** — transcribe the vendor's create-a-task field table into the
  section above, so `PostTask` can be diffed against tier 1. Until then
  `action_type_guid` is declared on `PostAction` (tier 1, 2023.4+) and **not**
  on `PostTask`, and `PostTask`'s guard accepts the key without the model
  asserting the field exists on that route.

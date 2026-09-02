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
carries the text passed to `set_status(comment=...)`, so it must not be
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

## Open items

* **O-URG** — `PUT /requests/{rfc_number}` declares `Urgency_ID` as a
  **string** (tier 3). This package sent an **int** when it measured the 590
  that caused `RequestUpdate.urgency_id` to be removed. The exclusion may be a
  type mismatch we authored rather than an API limitation. Unresolved: settling
  it needs a live write. Same question for `severity_id`.
* **O-CLOSE** — should the close route move to `PUT /requests/{rfc}/close`?
* **O-URGPATH** — the vendor documents `GET /urgencies`; the instance spec
  declares `GET /urgency`. Both return 200 live. Which is canonical is unknown.
* **O-CLOSE-DEFAULT** — `close_ticket` omits `status_GUID` from the body when
  the caller omits it, and two docstrings previously stated that this closes
  the ticket to the instance's default *Closed* meta-status, attributing it to
  the vendor close page. **That sentence is not recorded anywhere in this file
  and the behaviour is not exercised by the live suite** — every `close_ticket`
  call in `integration_tests/` passes an explicit `status_guid`. Both
  docstrings now hedge. Until someone either re-reads the vendor page and adds
  the row here, or measures the omitted form live and dates it, the
  documentation must not assert it.
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
  behaviourally (it carries `set_status(comment=...)` text) and 14 and 27 not
  at all. Settling this needs the EasyVista **admin console**, not the API: the
  administration screen listing action types, and specifically which type ids
  that deployment classes as *task* types. Nobody working on this package has
  console access; if you do, transcribe the list here.
* **O-TASKDOC** — transcribe the vendor's create-a-task field table into the
  section above, so `PostTask` can be diffed against tier 1. Until then
  `action_type_guid` is declared on `PostAction` (tier 1, 2023.4+) and **not**
  on `PostTask`, and `PostTask`'s guard accepts the key without the model
  asserting the field exists on that route.

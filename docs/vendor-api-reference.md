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
| `/actions` | GET | the only action list |
| `/actions/{id}` | GET, PATCH, PUT | the only action item; **no DELETE** |
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
* **O-TASKDOC** — transcribe the vendor's create-a-task field table into the
  section above, so `PostTask` can be diffed against tier 1. Until then
  `action_type_guid` is declared on `PostAction` (tier 1, 2023.4+) and **not**
  on `PostTask`, and `PostTask`'s guard accepts the key without the model
  asserting the field exists on that route.

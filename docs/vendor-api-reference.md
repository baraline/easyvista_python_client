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
| `~` / `!~` / `!` | Contains / not-contains / not-equals (Oxygen 1.7+). Counter-evidence, tier 4 — measured live 2026-08-17: `~` behaves as a *pattern* operator and needs an explicit `*`, so `FIELD~"value"` degenerates to an exact match and quietly returns the wrong rows. `ev_contains_filter` supplies the wildcards; see its docstring in `easyvista_python_client/filters.py`. |
| `is_null` / `is_not_null` | Oxygen 2.1.2+ |
| `formatDate` | Oxygen 1.7+ |

`+` in a query string decodes to a space, so the documented `RFC_NUMBER+desc`
and this package's measured `"RFC_NUMBER DESC"` are the same token.
Dotted sub-field access works in both `sort` and `search`
(`employee.last_name+desc`, `search=employee.e_mail:...`), and relative date
tokens exist (`search=field:last_week`). Neither is exposed by this package.

Envelope: `HREF`, `record_count`, `total_record_count`, `records`, `@next`.

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
* `GET /status`, `GET /urgency`, `GET /locations`, `GET /groups`,
  `GET /problems`, `GET /configuration-items`, `GET /questionnaires`,
  `GET /slas`, `GET /suppliers`, `GET /domains`, `POST /tokens`,
  and the external-table routes `GET|POST /{E_Your_Table}`.

## Open items

* **O-URG** — `PUT /requests/{rfc_number}` declares `Urgency_ID` as a
  **string** (tier 3). This package sent an **int** when it measured the 590
  that caused `RequestUpdate.urgency_id` to be removed. The exclusion may be a
  type mismatch we authored rather than an API limitation. Unresolved: settling
  it needs a live write. Same question for `severity_id`.
* **O-CLOSE** — should the close route move to `PUT /requests/{rfc}/close`?
* **O-URGPATH** — the vendor documents `GET /urgencies`; the instance spec
  declares `GET /urgency`. Both return 200 live. Which is canonical is unknown.

# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).
While the package is pre-1.0, breaking changes may land between minor versions;
a deprecation policy will follow the 1.0 release.

## [Unreleased]

### Removed

- **BREAKING**: `RequestUpdate.status_id`. There is no flat status update on this
  API and this field never worked. Sent alone the PUT is rejected 590/2013; sent
  beside any other field the PUT returns **200, applies the other field, and
  drops the status in silence** — measured on one ticket, title updated,
  `STATUS_ID` unchanged. A write that reports success and stores nothing is worse
  than one that fails, so the field is gone; `extra="forbid"` now makes
  `RequestUpdate(status_id=...)` raise at construction. Use `set_status`.

### Added

- `EasyvistaClient.iter_actions` / `AsyncEasyvistaClient.iter_actions` page a
  ticket's **whole** action log. `list_actions` returns one page and truncates a
  longer log with no error — and because it discards the envelope's total,
  nothing in the result reveals the truncation. That is not a corner case: a
  freshly created ticket already carries about a dozen workflow-generated
  actions before anyone has commented, so a ticket with real conversation on it
  crosses a default cap easily, and the comments lost are the oldest ones.
  `iter_actions` follows `@next` until the server runs out, takes the same
  `fields=` projection, and re-applies the ticket filter on every page.
  **Caveat:** unlike `iter_tickets`, the `offset`/`@next` contract has not been
  measured on the `actions` endpoint specifically. If an instance ignores
  `offset`, page two repeats page one and the sweep will not terminate — bound
  it with `max_records` the first time you use it on a ticket whose action count
  you do not know. `scripts/validate_docs_examples.py` now checks this against a
  live instance when credentials resolve.
- `Action.action_label_fr` (`ACTION_LABEL_FR`). Already returned on the default
  list projection, it was reachable only through `model_extra` — undeclared, and
  so named by no docstring, even though `context.py` already relied on it as the
  Markdown heading fallback. Note the item-level record carries eleven language
  columns; on a single-language instance the unpopulated ones echo the
  default-language text wrapped in `[...]`. Prefer `localized_label` there.
- `resources.actions.build_search_actions` — one page of a ticket's actions with
  the envelope kept, so `@next` is visible to a pager. `build_list_actions` is
  now a thin wrapper over it that drops the envelope; the unsafe/blank
  `rfc_number` guard moved into the shared builder so neither entry point can
  bypass it.
- `EasyvistaClient.set_status` / `AsyncEasyvistaClient.set_status` set a ticket's
  status, addressed by `STATUS_GUID`. This sends the documented
  `{"closed": {"status_GUID": ...}}` body — the same request `close_ticket`
  sends, under a name that matches what it does. Despite the wire name, the
  envelope is **not** limited to closing: handed each of six different status
  GUIDs in turn, a fresh ticket landed on exactly the status requested every
  time, non-terminal ones included. Status GUIDs are per-instance configuration
  and are not portable between deployments; read one off any ticket already in
  that status (the nested `STATUS` object carries `STATUS_GUID`).
- `PostRequest.catalog_guid`. The vendor documents it as the **preferred**
  subject identifier; it had been removed on the authority of a customer
  handover note that the package cited as the vendor specification. A create
  body with neither `catalog_guid` nor `catalog_code` now raises locally
  instead of drawing an HTTP 590 whose SQL parser error names no field.
- Eleven vendor-documented create fields that `PostRequest` did not declare:
  `location_id`, `location_code`, `department_code`, `recipient_name`,
  `recipient_identification`, `requestor_identification`, `requestor_mail`,
  `requestor_name`, `parentrequest`, `phone`, `submit_date`. Tier 1 —
  vendor-documented, not verified live by this package.
- `PostRequest.workflow_start`, a twelfth field reachable the same way but
  **not** vendor-documented like the eleven above: its only source is the
  instance's own OpenAPI schema for `POST /requests` ("Optional. If true,
  starts the workflow for the created incident."), which makes it tier 3 —
  illustrative only, example-derived, not a normative contract. Treat it as
  unverified until tested against the deployment you use it on.
- `extra_payload` on every write model: an un-prefixed passthrough merged last,
  overriding declared fields and `custom_fields` alike. Every field these models
  decline to declare rests on behaviour measured against a single instance;
  `extra="forbid"` turned each of those measurements into a hard wall for every
  other deployment, and `custom_fields` could not help because it only emits
  `e_`-prefixed keys.
- `get_ticket_context(..., memo_fields=...)` and `TicketContext.memos`. The API
  models the memo name as a path segment, and the instance's own OpenAPI spec
  documents it as a selector ("Memo field type, could be comment, description";
  tier 2 — declared in the instance's OpenAPI `paths`, not vendor-documented),
  so which memo carries a ticket's body is per-deployment configuration the
  client was hardcoding. Default behaviour is unchanged. `TicketContext.description`
  / `.comment` stay dataclass fields rather than becoming properties over
  `memos`, a deliberate deviation to avoid breaking positional construction of
  a public dataclass.
- `docs/vendor-api-reference.md` — the vendor facts this package depends on,
  each tagged with the evidence behind it, plus the routes present in the
  instance's OpenAPI that the package does not implement.

### Fixed

- **Documented that this API has no private-comment feature.** The package
  looked as though it were missing one. It is not: an action carries no
  visibility flag at all, so there is nothing to expose. `action_type_id` is the
  only per-action discriminator, and whether a deployment uses distinct types to
  separate internal from customer-facing notes is a property of that deployment
  which the API cannot reveal — `GET action-types` is 403 on a standard profile.
  `PostAction`, `create_action`, the user guide and the `easyvista-ticket-actions`
  skill now say so, and point the caller at their EasyVista administrator rather
  than at a discovery routine that cannot work.
  **Correction:** an earlier draft of this documentation claimed the human-comment
  action types carry a `[Public]` / `[Private]`-style suffix in `ACTION_LABEL_*`.
  That was a misreading of the *untranslated-label placeholder*: on a
  single-language instance the unpopulated language columns echo the
  default-language text wrapped in `[...]`, which is why
  `references.localized_label` already discards them. The brackets encode no
  visibility. No release carried the wrong claim.
- `PostRequest`'s docstring claimed a ticket "needs at minimum `catalog_code`
  plus `title`". That was wrong in a way that cost real debugging time. **Send
  the whole documented create body** — `catalog_code`, `origin`, `title`,
  `description`, `department_id`, `urgency_id`, `impact_id`. The full body is
  accepted everywhere tried; the same body minus those ids is accepted on some
  catalogs and rejected on others with the *identical* remaining bytes. The
  rejection's message is a bare **SQL parser error** naming no field
  (`=(1,35) expected token:( * + - . IDENTIFIER CASE NOT JOIN ...`), which reads
  like a server-side defect and is not one — it is what an under-specified create
  looks like here. Every id in that body was verified to persist by reading it
  back under an explicit projection (these columns are absent from the default
  projection, like `TITLE`, so an unprojected read shows `None` regardless).
- Documented that **a rejected create may still have created the ticket**: 12
  attempts returned 3 `RFC_NUMBER`s and afterwards all 12 tickets existed. A 590
  therefore means *possibly created*, never *not created* — retrying duplicates,
  and the caller never learns the id. The `external_reference` marker does
  survive the failed insert and is searchable, which is the only way to reconcile
  such an orphan.
- `integration_tests/test_live_smoke.py` leaked one ticket per live run. Its
  `test_missing_mandatory_field_raises_validation_error` asserted that a create
  with a catalog but no title is rejected "(no ticket created), so this stays
  read-only-safe by construction" — both halves false: `title` is not the
  mandatory field (the full documented body with no title creates fine), and the
  rejection does create a row. Replaced by
  `test_an_underspecified_create_body_raises_validation_error`, which omits the
  ids that really are required and reconciles the leftover ticket by its marker
  in a `finally`. Two tests added beside it: one pinning that the documented body
  lands every id, one pinning that `set_status` reaches a **non-terminal**
  status.
- `PostRequest.origin` and `PostRequest.impact_id` now accept `int | str`, but
  they were widened for different reasons, not the same one. `origin` is
  vendor-documented as a **string** (tier 1); an `int` was separately measured
  accepted on one instance (tier 4, date not recorded). `impact_id` is
  vendor-documented as an **integer** (tier 1); its `str` branch exists so a
  caller who quotes it is not rejected, not because a string was independently
  measured landing here. `origin` sends whichever type is passed, unchanged;
  `impact_id` normalizes a numeric string back to the vendor's documented int —
  see **Changed** below, where the wire-form consequences of both are set out.
- Three shipped docstrings cited a gitignored, instance-private handover note
  as the documented request body. That file is invisible to every reader of the
  published repository — a dead link — and was never the vendor documentation
  it was cited as; `docs/vendor-api-reference.md` now carries the citable
  facts instead. A new guard (`scripts/tests/test_source_citations.py`) fails
  the suite if any tracked file cites a gitignored path again — it scans
  `easyvista_python_client/**/*.py`, `scripts/**/*.py`, `docs/*.rst`,
  `docs/*.md`, `integration_tests/**/*.py`, and the root `.md` files,
  including this changelog.
- `PostRequest`'s "send the whole documented set" doctrine is corrected. The
  vendor requires only `catalog_guid` or `catalog_code`; the seven-field body
  is a hedge against per-catalog configuration measured on one instance, which
  the docstring stated as an API requirement.
- `TicketContext.to_markdown` dropped a non-default memo. Fetch was
  parameterised by `memo_fields` and rendering was not, so
  `get_ticket_context(rfc, memo_fields=("solution",))` — the headline case for
  that parameter, a deployment whose body memo is neither default — produced a
  Markdown export with no body section and no warning. It now applies the same
  role-naming rule to `memos`: when neither `description` nor `comment` has
  text, a single populated memo becomes the body under `## Description`, and
  several each get a heading derived from the field name requested.

### Changed

- **The wire form changed for a caller who passes an id as a numeric string.**
  Widening a `PostRequest` field from `int` to `int | str` is not purely
  additive, and the entries above previously implied it was: pydantic's smart
  union keeps the exact type match where the old `int` field coerced. So
  `PostRequest(origin="7")` used to send `7` and now sends `"7"`, and the same
  is true of `department_id` and `recipient_id`, widened in this release for
  the same reason. The vendor documents all three columns as **strings**
  (tier 1, `docs/vendor-api-reference.md`), so the string form is the
  documented one and there is nothing to normalize towards. An id was measured
  accepted in either form on one instance (tier 4, 2026-08-25), so on that
  deployment this changes the bytes and not the outcome — but a deployment that
  discriminates on JSON type would see a behaviour change. Pass an `int` to get
  the old bytes.
- **`PostRequest.impact_id` is the exception, and it coerces again.** It is
  declared `Field(union_mode="left_to_right")` with `int` first, so
  `impact_id="28"` reaches the wire as `28`. The vendor documents this column
  as an **integer** (tier 1), which is the form worth normalizing towards; the
  `str` branch exists so a caller who quotes the value is not rejected, not so
  that the quoted form ships. A non-numeric string is still accepted and passes
  through as written, so nothing previously accepted is refused now. (Between
  the widening and this entry `impact_id="28"` did ship as `"28"`; both changes
  fall in this same unreleased section, so no release carried it.)
- **`extra_payload` overrides a declared field across letter case.** EasyVista's
  field names are case-insensitive, so the exact-key merge broke the escape
  hatch's own promise: `PostRequest(urgency_id=8,
  extra_payload={"URGENCY_ID": "4"})` put **both** spellings on the wire with
  conflicting values and left the winner to the server. An `extra_payload` key
  now replaces any declared or `custom_fields`-produced key it matches when
  case is ignored, and `extra_payload`'s spelling and value are what ship. The
  `ALL_CAPS` form is the likely one, not a corner case — it mirrors the read
  side, which is where callers copy names from. This is a merge rule: a
  collision is never an error.
- **Live-test credential renamed** (contributor-facing; the published package is
  unaffected). `EASYVISTA_TEST_USER` / `secrets/easyvista_test_user` are now
  `EASYVISTA_TEST_ACCOUNT` / `secrets/easyvista_test_account`. The value never
  was a login: it is the EasyVista **account**, the instance identifier that
  forms the `{account}` path segment of `https://host/api/{version}/{account}`
  (a number such as `50004`), and it feeds `EasyvistaConfig.account`.
  Authentication is the Bearer token alone. The old name is **not** accepted as a
  fallback — `integration_tests/`, `scripts/validate_docs_examples.py` and
  `scripts/validate_live_content_fidelity.py` now abort with a message naming the
  replacement if it is still configured, because silently honouring it would
  preserve exactly the misreading the rename removes. Rename your local file;
  `secrets/` is gitignored as a whole directory, so the new name stays ignored.
  Note the value is consulted **only** when the URL is a bare host — a full API
  root already carries the account, and most setups never read it at all.

## [0.2.0] - 2026-08-18

### Added

- `EasyvistaClient.stream_document` / `AsyncEasyvistaClient.stream_document`
  yield an attachment's bytes in chunks (64 KiB by default, `chunk_size=` to
  change it) instead of returning them whole. Motivation: a consumer mirroring
  attachments had no choice but to buffer, because `download_document`
  materialises the whole file before it returns anything. What this removes is
  that download buffer and only that — one attachment's worth of memory, so a
  32 MB file is held a chunk at a time instead of whole. The upload leg is
  unaffected: `add_document` takes `content: bytes` and base64-encodes it, so a
  mirror that re-uploads still materialises that payload in full (see below for
  why no streaming upload is possible). Accepts exactly what `download_document`
  accepts and resolves the URL identically, so the same-origin refusal, the
  `follow_redirects` behaviour and the error mapping (a 403 is still
  `EasyvistaAuthError`, a 590 is still not retried) are the same on both paths.
  **Only the download direction streams, and that is the API's constraint:**
  EasyVista takes an attachment as base64 inside a JSON body, so `add_document`
  must materialise the whole payload before it can send anything — no streaming
  upload is possible, and the asymmetry is not an oversight here.
  **A mid-stream failure is not retried.** Opening the download is retried under
  the usual policy, and the first chunk is fetched inside that retried unit so a
  failure fetching it is still safe to restart; from that chunk onwards the
  request is committed and a transport error raises `EasyvistaConnectionError`
  rather than starting over, because starting over would re-deliver bytes the
  caller already holds. Nothing resumes a partly consumed stream, so a caller
  that must survive a mid-stream failure decides for itself whether to discard
  what it collected and ask again; `download_document` retries the whole fetch
  and stays the simpler choice for a file small enough to buffer.

- Python 3.13 and 3.14 are now tested and declared supported (classifiers, and
  the CI/release matrices, now span 3.10--3.14). No code changed: the suite
  passes unmodified on both, with the same statement count and coverage as on
  3.10, and the generated `_sync/` tree regenerates byte-identically under each
  interpreter's tokenizer.
- `.github/workflows/release.yml`: releases are built and published to PyPI by
  CI when a GitHub release is published, using Trusted Publishing (no API token
  in the repository). The workflow re-runs the test matrix and the quality gates,
  refuses to build when the release tag, `pyproject.toml` and
  `easyvista_python_client.__version__` disagree, runs `twine check`, and then
  triggers a Read the Docs build for the release. `workflow_dispatch` rehearses
  everything except the upload. See `docs/publishing.rst`.
- `skills/`: eight Agent Skills covering client setup, search syntax, tickets,
  ticket actions, documents, assets, the directory and reporting/context, with
  an index in `skills/README.md`. Shipped in the source distribution, not in
  the wheel.
- `scripts/tests/test_skills_contract.py`: checks every skill's frontmatter and
  code snippets against the real public API, so a rename fails CI.
- Public `filters.py`: `ev_equals_filter`, `ev_in_filter`, `escape_ev_value`, and
  `is_safe_ev_value` for building EasyVista `search` expressions safely.
- `ev_since_filter` / `ev_between_filter` — the interval grammar
  (`FIELD:(a;b)`) that is the only server-side range filter this API honours.
  EasyVista has no comparison operator (`>=`, `BETWEEN`, `[a TO b]`…): either
  rendering is silently dropped or, if it keeps `FIELD:"value"` syntax while
  embedding the operator in the value, raises HTTP 590 as a type mismatch.
  Neither ever narrows a result, which is why these builders exist.
- `ev_contains_filter` / `ev_starts_with_filter` — `~` with an explicit
  wildcard (`*` or `%`; both work identically). A bare value under `~`
  degenerates to exact match, which these builders avoid by construction.
  A value containing any of `*`, `%`, `_` or `[` raises `ValueError`: all four
  are metacharacters to `~` (`_` matches any single character, `[` opens a
  character class — measured live: replacing one character of an RFC that
  matched 1 row with `_`, or with `[0-9]`, matched 9), and no escape for them
  exists (`\_` is compared literally). Refusing beats silently matching records
  the caller did not ask for, which matters because `_` is pervasive in
  EasyVista codes: `ev_contains_filter("ASSET_TAG", "LAPTOP_01")` would
  otherwise also match `LAPTOP-01` and `LAPTOP001`, with HTTP 200 and no hint.
- `parse_ev_datetime` / `format_ev_datetime` (new `timestamps.py` module) —
  parse an EasyVista timestamp to an aware `datetime` and render one back to
  the literal the search grammar and the wire format both accept.
- `Request` now declares fields that were previously reachable only as untyped
  `extra="allow"` data — each verified present on live single-ticket GETs:
  `title`, `request_id`, `external_reference`, `sd_catalog_id`, `urgency_id`,
  `impact_id`, `severity_id`, `request_origin_id`, `department_id`,
  `location_id`, `requestor_id`, `recipient_id`, `owner_id`, `submit_date_ut`,
  and `last_update`.
- `RequestUpdate.title` — a ticket's title can now be changed after creation
  (`PUT /requests/{rfc}`), not only set at create time.
- `RequestUpdate` now also carries `impact_id`, `owner_id` and
  `external_reference` (capped at 50 characters — bisected live: 50 is
  accepted, 51 is rejected). `severity_id`, a writable priority field, and
  `urgency_id` are deliberately still absent; see the `O-590-PARTIAL` note.
- `EasyvistaClient.download_document` / `AsyncEasyvistaClient.download_document`
  fetch an attachment's bytes. An absolute download URL is followed only when
  its scheme and host match the configured `server`: every request carries the
  instance's Bearer token, so a URL naming another host is refused rather than
  followed.
- `Request` now declares the official time-limit fields as typed attributes:
  `creation_date_ut`, `max_resolution_date_ut`, `expected_date_ut` and
  `end_date_ut` (timezone-aware `datetime`, parsed the same way as the other
  timestamps below), plus `sla_id` (int) and `time_used_to_solve_request` (a
  string on every ticket checked, never an int, so no int branch is declared).
  The instance-specific `E_GTR_*` / `E_GTI_*` family stays undeclared and
  reachable through `classify_fields().custom`.
- `EasyvistaClient.get_action` / `AsyncEasyvistaClient.get_action` fetch a single
  action. The item-level record carries Memo links that `list_actions` omits —
  including `DESCRIPTION`, which is where an action's note text actually lives.
- `Action.description` and `Action.href`, plus an `action_id` derived from `href`
  when the API omits it. The derivation is deliberately narrow: it uses `href`'s
  trailing segment only when that segment is numeric, which is the case for an
  item-level `GET actions/{id}`, and it never overwrites an `ACTION_ID` the API
  did send. It does **not** fire for a create response — `POST
  requests/{rfc}/actions` echoes an HREF naming the **parent request**, so the
  tail is an RFC number rather than an id. A created action's id is therefore not
  recoverable from its create response at all; diff `list_actions` across the
  create to identify it (verified live).
- `list_actions(fields=...)` — project timestamps and author onto the list and
  read a whole **page** of action metadata in one request instead of one item
  fetch per action. Three silent footguns come with it: `"*"` is not a wildcard
  (it reduces to `ACTION_ID` alone), a dotted path (`DESCRIPTION.HREF`) is
  silently dropped, and `list_actions` returns **one page and does not
  paginate** — a ticket with more actions than `config.default_max_rows` is
  truncated with no error, and the call discards the envelope's total so the
  caller cannot detect it. That is not a corner case: a freshly created ticket
  already carries about twelve actions, most of them workflow-generated. The
  same cap therefore truncates `get_ticket_context`'s action log and
  `TicketContext.to_markdown()`'s rendering of it. `list_actions` now sends
  `config.default_max_rows` explicitly, the way every sibling search does, so
  the cap is the client's and can be raised; real pagination is a follow-up.
- `Action` now declares its timestamps (`created_at`/`CREATION_DATE_UT`,
  `updated_at`/`LAST_UPDATE`), author (`done_by_id`) and workflow context
  (`action_type_id`, `group_id`, `request_id`, `action_number`, `stage_id`,
  `workflow_id`, `parent_action_id`) — verified live 2026-08-17. Availability
  on the LIST endpoint is not uniform across these; pass `fields=` to project
  the ones a default list row omits. Note the naming diverges from the two
  models already shipped: `Action.created_at`/`updated_at` alias the same wire
  columns that `Request` and `Employee` expose as
  `creation_date_ut`/`last_update`. The wire aliases are identical on all three,
  so code spanning record types should reach the value through
  `classify_fields()` / `.reference()` rather than a shared attribute name —
  `getattr(record, "last_update")` raises `AttributeError` on an `Action`.
- `update_action` and `delete_document`, with `ActionUpdate`. `PUT
  actions/{id}` edits an action's note (verified live by re-reading it
  afterwards, not by trusting HTTP 200); an action can be edited but not
  deleted (`DELETE actions/{id}` is refused with HTTP 403). `DELETE
  requests/{rfc}/documents/{document_id}` removes an attachment — the
  top-level `DELETE documents/{id}` returns HTTP 403.
- `get_ticket_context(..., resolve_action_bodies=True)` resolves each action's
  note text. Pass `False` to skip it — it costs two extra requests per action.

### Changed

- **BREAKING:** Read-model timestamps are now timezone-aware `datetime`
  instead of `str`: `Request.submit_date_ut`, `creation_date_ut`,
  `max_resolution_date_ut`, `expected_date_ut`, `end_date_ut`, `last_update`,
  and `Employee.last_update`. EasyVista returns ISO 8601 with an explicit UTC
  offset and millisecond precision (verified live 2026-08-17), so parsing is
  no longer left to callers. An unset date (`""` on the wire) is `None`. Write
  models are **unchanged** — the accepted write format for a date is still
  unverified. Migration: drop your own parsing; to rebuild a search literal
  use `format_ev_datetime(value)`, or pass the `datetime` straight to
  `ev_since_filter`. One more consequence, easy to miss: a record dump is no
  longer directly JSON-serialisable. `model_dump()` and `classify_fields()`
  now yield `datetime` objects for these columns, so
  `json.dumps(ticket.classify_fields().official)` raises
  `TypeError: Object of type datetime is not JSON serializable` where it used to
  work — pass `model_dump(mode="json")` on any path that caches, exports or logs
  a record as JSON. `classify_fields()` takes **no arguments**, so `mode="json"`
  cannot be applied to it: render its values with `format_ev_datetime` before
  serialising, or re-key a JSON-mode dump by the bucket's keys
  (`dumped = ticket.model_dump(mode="json", by_alias=True)`, then
  `{k: dumped[k] for k in ticket.classify_fields().official}`).
  **Scope note — the `0.1.0` boundary is ambiguous, read both.** Relative to
  the `## [0.1.0] - 2026-07-15` release **commit** (`6df6a75`), only
  `Employee.last_update` is a pre-existing field — the six `Request` fields
  above were themselves first declared later, during this 0.2.0 cycle
  (see `Added`), so under that reading only one field is retyped out
  from under a shipped release. But the `0.1.0` **git tag** currently resolves
  to a later commit (`3216a33`, 2026-08-04, 117 commits after the release
  commit), at which all six `Request` fields and `Employee.last_update` were
  already declared as `str | None`. Anyone who installed or pinned against the
  `0.1.0` tag therefore sees **all seven** fields change type, not one — check
  which commit your `0.1.0` actually resolves to before assuming the narrower
  case.
- **Documentation correction:** the `search` operator `~` was documented as
  exact-match-only, identical to `:`. Measured live, `~` **is** a pattern
  operator — it needs an explicit wildcard (`*` or `%`, both work identically)
  to act as one: `~"*260817*"` matched 33 rows and `~"I26081*"` matched 32,
  while `:"I26081*"` matched 0, because `:` never expands a wildcard. Without
  one, `~` degenerates to exact match, which is exactly what the earlier
  tests observed and over-generalised from. Examples implying substring
  matching with a bare value (`ASSET_TAG~LAPTOP`) were wrong and have been
  replaced with `ev_contains_filter("ASSET_TAG", "LAPTOP")` →
  `ASSET_TAG~"*LAPTOP*"`. `*` and `%` are not the only metacharacters either:
  under `~`, `_` matches any single character and `[` opens a character class
  (both measured live). The unverified `!~` / `!` / `is_null` /
  `is_not_null` operators are still not documented as fact.
- **Documentation correction:** the README's and user guide's tutorial examples filtered with
  `ev_equals_filter("STATUS_EN", "Open")`. `STATUS_EN` is a sub-key of the nested `STATUS`
  object, not a top-level column, so EasyVista silently ignored the condition and every example
  returned *all* tickets, not just open ones. This was a documentation defect, not a library bug
  — the library does not special-case field names, so nothing in the shipped code was broken.
  Replaced with `ev_equals_filter("STATUS_ID", 3)` throughout, and the user guide now documents
  which returned fields are actually searchable and the third (HTTP 590 type-mismatch) search
  outcome.
- `AsyncEasyvistaClient.get_ticket_context` and `get_department_context` now issue their
  independent sub-requests **concurrently** instead of one after another. The async client
  previously awaited every call in sequence, so it was no faster than the synchronous one
  (measured against a live instance on a ticket with 19 actions: 14.65s async, 13.44s sync,
  5.31s after this change). Same requests, same results, same degradation on 403/404 — only
  the issue order changed. Peak in-flight is 4 sub-resource requests then at most 8
  concurrent action-body resolutions for a ticket, and 7 branches for a department.
  Two deltas worth knowing: on a **failing** bundle the siblings already in flight are
  awaited before the error propagates, so an error path can issue more requests than it did
  before (bounded by the fan-out width, and all of them reads); and when two branches fail,
  the exception raised is the first in source order — the one the sequential version would
  have raised — rather than whichever failed soonest. `create_tickets` stays deliberately
  sequential: those are writes, and a mid-batch failure must leave a knowable prefix.
- `TicketContext.to_markdown()` now titles a lone narrative block `## Description` whichever
  memo it arrived in. A ticket's body does not always live in `DESCRIPTION` — on the verified
  instance that memo is unused and `COMMENT` carries the body (and `RequestUpdate.description`
  writes `COMMENT` on any instance), so the rendered document titled a ticket's main text
  "Comment", which misleads an LLM or a RAG chunker splitting on headings. The renderer no longer
  assumes either mapping: when only one memo has text it is the body and is titled
  `## Description`; when both do, the distinction is real and each keeps its own heading, byte
  identical to before. An instance that populates `DESCRIPTION` is unaffected. The
  `TicketContext.description` / `.comment` attributes are unchanged and still name their
  source memo.
- **Documentation of observed behaviour, not a code change:** a `description` supplied to
  `PostRequest` at create time is not readable back through either the `DESCRIPTION` or the
  `COMMENT` Memo on the verified instance. `RequestUpdate.description` writes the ticket's
  `COMMENT` Memo, not `DESCRIPTION` — verified live by re-reading the memo after a write, not
  by trusting HTTP 200. Nothing is claimed here about how often `DESCRIPTION` is populated on
  an instance: an earlier reading of that (`0/15` sampled tickets) is explicitly withdrawn by
  the DESCRIPTION-sampling correction under `Fixed` below. Read the body
  text back with `TicketContext.comment` (or `resolve_memo("requests/{rfc}/comment")`
  directly), not `Request.description`. Both fields stay as they are; nothing was renamed.
- `Request.status_id`, along with the model's other numeric identity/classification fields, now
  uses an `OptionalInt` type that tolerates the API's `""` for an absent numeric; `status_id`
  previously raised a validation error on that value.
- `get_department_context` now raises `ValueError` for a blank or unrenderable `department_id`
  rather than building a malformed search (defence in depth; not a demonstrated exploitable path).
- The synchronous client is now **generated** from the asynchronous one with
  `unasync`. `easyvista_python_client/_async/` is the only hand-written client
  source; `_sync/` is produced by `python unasync_build.py`, checked in, and
  verified in CI. Sync/async parity is enforced by a build gate instead of by
  convention.
- **Internal module paths moved.** `easyvista_python_client.client` and
  `easyvista_python_client.async_client` no longer exist. Import from the
  package root instead — `from easyvista_python_client import EasyvistaClient,
  AsyncEasyvistaClient` — which is unchanged and has always been the supported
  surface. `easyvista_python_client._transport.RequestSpec` is also unchanged.
- `EasyvistaClient.ticket_statistics` now collects its page of tickets into a
  list before aggregating, rather than streaming the iterator. No behavioural
  difference at the default `max_records=100`; at `max_records=None` peak
  memory is now proportional to the result set.
- `EasyvistaClient.get_ticket_context` now lists documents before resolving
  action bodies, rather than after. The same requests are issued and the
  result is identical; only their order on the wire changed.

### Removed

- **Breaking:** `PostRequest.catalog_guid` and `Request.catalog_guid` are gone.
  `CATALOG_GUID` is absent from every sampled live ticket (0/25 single-ticket
  GETs), from the documented create body, and from the vendor field inventory —
  it could never populate. `PostRequest(catalog_guid=...)` previously validated
  and was sent to the API; it now raises (`extra="forbid"`) instead of being
  silently accepted. Use `catalog_code` to name a catalog on create.
  **Update, recorded here rather than silently edited into the entry above:**
  `PostRequest.catalog_guid` was restored in `[Unreleased]` — the vendor
  documents it as the **preferred** subject identifier, and the removal above
  rested on a customer handover note the package had cited as the vendor
  specification, not on the vendor docs themselves. `Request.catalog_guid`
  remains gone, correctly: `Request` is a read model, `CATALOG_GUID` was never
  returned on any sampled ticket, and `test_request_has_no_catalog_guid_attribute`
  now pins its absence.

### Fixed

- `ev_since_filter` / `ev_between_filter` accepted a **timestamp string with no
  UTC offset** and passed it to the wire. EasyVista accepts such a literal and
  reads it in a different zone, which moves the bound and **silently skips
  records** — measured live 2026-08-18, the same wall-clock text with and without
  its offset enumerated 13 rows and 11 rows against one instance. Both builders
  now refuse a time that carries no offset (or `Z`), matching the guard
  `format_ev_datetime` already applied to a naive `datetime`; a bare date is
  still accepted, having no time to misplace. Found by probing, not by review:
  the datetime path was guarded and the string path was not, for the identical
  hazard.
- `ev_since_filter` / `ev_between_filter` now **normalise** a timestamp string
  bound instead of passing it through. The offset gate above made an offset
  mandatory, and the obvious way to comply with a stored
  `"2026-08-17T20:26:40"` watermark is to append `+02:00` — but measured live
  2026-08-18, `LAST_UPDATE:(2025-11-28T16:14:41+01:00;)` is **HTTP 590**, as are
  minute precision, `seconds+00:00` and a space instead of `T` (which is what
  `str(aware_datetime)` produces). Only a bare date and
  millisecond-precision-with-offset (or `Z`) are honoured. An admitted string
  bound is therefore re-rendered through
  `format_ev_datetime(parse_ev_datetime(text))`, so the string and datetime
  paths now emit byte-identical bounds and both emit a rendering the wire
  accepts; a bare date is still passed through unchanged. Lowercase `z` is now
  accepted too — `parse_ev_datetime` already accepted it on the read path, so
  refusing it here rejected a value this package itself produces. The rendered
  bound is validated as well, so a `datetime` in a zone whose UTC offset is not
  a whole number of minutes (every pre-1900 `zoneinfo` entry) raises locally
  instead of emitting `+05:53:20`.
- **Documented, not changed:** the interval's lower bound is **inclusive** and
  milliseconds are honoured (verified live on three independent boundaries), so
  a watermark set to `max(t.last_update)` re-reads that boundary record on the
  next sweep. And an offset-pagination sweep over a change window must be sorted
  **descending** (`sort="LAST_UPDATE DESC"`) and de-duplicated: the rows the
  filter selects are by construction the rows that are changing, so a ticket
  touched between two pages moves within the set being paged and can slip past
  the read cursor. Descending, the row that slips is the re-touched one, whose
  stamp is now *above* the watermark, so the next sweep picks it up — the miss is
  deferred. Ascending, the row that slips is a neighbour whose stamp did *not*
  change, so it falls *below* the watermark and is lost. A caller who cannot
  tolerate even a deferred miss must page `search_tickets` with keyset
  pagination (advance the window to the last row's stamp instead of an offset),
  which `iter_tickets` cannot express. The sweep examples in `ev_since_filter`,
  the user guide and the search-syntax skill all carry the sort and the
  de-duplication. **Undocumented until now:** because descending yields the
  newest row first, the watermark reaches its final value on page 1 of any
  given sweep, so a sweep that is interrupted or capped with `max_records`
  still ends up holding the newest stamp — advancing the watermark from it
  permanently excludes every row the incomplete sweep never read. The four
  sites above now say so: advance the watermark only after a sweep runs to
  completion, and checkpoint a mid-sweep caller with keyset pagination instead.
- `Request`/`Action`/`Employee` timestamp columns now **raise** on a malformed
  value instead of falling through to pydantic's own datetime parser, which is
  far more permissive than EasyVista's format and invented plausible-looking
  instants: `"20260817"` became `1970-08-23T12:00:17Z` (56 years off) and
  `1755434441610` — what an epoch-millis format change would look like — became
  a wholly credible `2025-08-17T12:40:41.610Z`. Absorbing a format change is the
  opposite of what the guard exists for, and the docstring already promised a
  raise. The `""` unset sentinel still becomes `None`, unchanged.
- **Documentation correction:** `RequestUpdate`'s docstring claimed `DESCRIPTION`
  is empty on every ticket of the verified instance. It is not. A pooled 77-row
  sample across four orderings found `COMMENT` populated on 57 rows,
  `DESCRIPTION` on 27 and *both* on 24, with the proportions flipping by slice
  (measured 2026-08-18). The earlier 0/15 reading was a sampling artifact drawn
  from probe-authored tickets. The load-bearing claim is unchanged and still
  verified: `RequestUpdate.description` writes the `COMMENT` memo. What is
  withdrawn is the generalisation about `DESCRIPTION` being universally empty —
  which also means an instance's body memo cannot be auto-detected by sampling.
- `find_departments` and `list_actions` interpolated caller values into a `search` expression
  unescaped. Because `,` is an EasyVista combinator, a crafted value could silently widen the
  result set (verified live: a department lookup returned 2 records instead of 1). Both now
  validate the value.
- `TicketContext.to_markdown` rendered every action with an empty body. It read
  the text from `Action.comment`, but `COMMENT` is a distinct field that never
  carries it; the note supplied as `PostAction.description` comes back through
  the action's `DESCRIPTION` Memo, which is reachable only via an item-level
  `GET actions/{id}`. Verified against a live instance.
- **Every mapped exception's message no longer interpolates the raw HTTP response
  body.** For a body this client does not recognize (an nginx or WAF HTML page, a
  plain-text 503, any unmodelled shape), the message previously ended with that
  body's literal text — which then surfaced verbatim wherever the exception was
  rendered (`str(exc)`, a traceback, a test runner's failure summary), regardless
  of what the body actually contained. The message now reports only the byte
  count. **Added:** `EasyvistaError.body` (`bytes | None`) carries the raw
  response body, so the content dropped from the message is not lost — it is the
  only way left to retrieve an unrecognized body. `.status_code`, `.ev_code` and
  `.ev_message` are unaffected: a *recognized* EasyVista error body (one with a
  parseable `error`/`error_code` shape) reads exactly as it did before.
- `RECENT_TICKETS_SORT` used a colon-separated token (`RFC_NUMBER:DESC`) that
  EasyVista silently ignores, so `get_department_context(recent_tickets=...)`
  returned tickets in the API's default order rather than newest-first. The
  descending token must be space-separated (`RFC_NUMBER DESC`) — verified live
  2026-08-17 by `integration_tests/test_live_change_window.py`. Closes O-DIR-1.

### Notes

- Open item **O-590-PARTIAL**: `PUT requests/{rfc}` with `URGENCY_ID` returned
  HTTP 590 (code 2013) while nevertheless changing the stored value. A rejected
  update may therefore have partially applied — re-read before retrying. Needs a
  focused live probe (set each id from `GET /urgencies` in turn and re-read)
  before `urgency_id` can be added to `RequestUpdate`.

## [0.1.0] - 2026-07-15

Initial public release.

### Added

- Synchronous `EasyvistaClient` and asynchronous `AsyncEasyvistaClient` over the
  EasyVista Service Manager REST API, with Bearer or HTTP Basic authentication
  and `EasyvistaConfig.from_env()`.
- Tickets (requests): create, batch create, get, update, search, close, and
  offset-following `iter_tickets()` pagination.
- Assets, actions, and documents (base64-in-JSON upload, attachment listing).
- Departments and employees directory, including fuzzy `find_departments()`
  and department context.
- `TicketContext.get_ticket_context()` with an href-free `to_markdown()`
  renderer.
- Reporting helpers: `count_tickets`, `ticket_statistics`, and the pure
  `aggregate_tickets()` core.
- Reference normalization (`Reference`, `localized_label`) and a generic field
  model (`FieldClassification`) separating official from custom `e_*` fields.
- Typed exception hierarchy rooted at `EasyvistaError`, carrying the EasyVista
  status/error code, with non-retryable validation errors (HTTP 590, code 2013).
- `py.typed` marker — the package ships inline type information.

[Unreleased]: https://github.com/baraline/easyvista_python_client/compare/v0.2.0...HEAD
[0.2.0]: https://github.com/baraline/easyvista_python_client/compare/0.1.0...v0.2.0
[0.1.0]: https://github.com/baraline/easyvista_python_client/releases/tag/0.1.0

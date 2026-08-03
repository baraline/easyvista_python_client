# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).
While the package is pre-1.0, breaking changes may land between minor versions;
a deprecation policy will follow the 1.0 release.

## [Unreleased]

### Added

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
- `Request` now declares fields that were previously reachable only as untyped
  `extra="allow"` data — each verified present on live single-ticket GETs:
  `title`, `request_id`, `external_reference`, `sd_catalog_id`, `urgency_id`,
  `impact_id`, `severity_id`, `request_origin_id`, `department_id`,
  `location_id`, `requestor_id`, `recipient_id`, `owner_id`, `submit_date_ut`,
  and `last_update`.
- `RequestUpdate.title` — a ticket's title can now be changed after creation
  (`PUT /requests/{rfc}`), not only set at create time.
- `EasyvistaClient.download_document` / `AsyncEasyvistaClient.download_document`
  fetch an attachment's bytes. An absolute download URL is followed only when
  its scheme and host match the configured `server`: every request carries the
  instance's Bearer token, so a URL naming another host is refused rather than
  followed.
- `Request` now declares the official time-limit fields as typed attributes:
  `creation_date_ut`, `max_resolution_date_ut`, `expected_date_ut`,
  `end_date_ut`, `sla_id` and `time_used_to_solve_request`. As with the existing
  timestamps, they are verified *returned* and no datetime parsing is claimed.
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
- `get_ticket_context(..., resolve_action_bodies=True)` resolves each action's
  note text. Pass `False` to skip it — it costs two extra requests per action.

### Removed

- **Breaking:** `PostRequest.catalog_guid` and `Request.catalog_guid` are gone.
  `CATALOG_GUID` is absent from every sampled live ticket (0/25 single-ticket
  GETs), from the documented create body, and from the vendor field inventory —
  it could never populate. `PostRequest(catalog_guid=...)` previously validated
  and was sent to the API; it now raises (`extra="forbid"`) instead of being
  silently accepted. Use `catalog_code` to name a catalog on create.

### Fixed

- `find_departments` and `list_actions` interpolated caller values into a `search` expression
  unescaped. Because `,` is an EasyVista combinator, a crafted value could silently widen the
  result set (verified live: a department lookup returned 2 records instead of 1). Both now
  validate the value.
- `TicketContext.to_markdown` rendered every action with an empty body. It read
  the text from `Action.comment`, but `COMMENT` is a distinct field that never
  carries it; the note supplied as `PostAction.description` comes back through
  the action's `DESCRIPTION` Memo, which is reachable only via an item-level
  `GET actions/{id}`. Verified against a live instance.

### Changed

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
  `COMMENT` Memo, not `DESCRIPTION` — verified live (0/15 sampled tickets, portal-created
  included, have a non-empty `DESCRIPTION`; 15/15 have a non-empty `COMMENT`). Read the body
  text back with `TicketContext.comment` (or `resolve_memo("requests/{rfc}/comment")`
  directly), not `Request.description`. Both fields stay as they are; nothing was renamed.
- **Documentation correction:** the `search` operator `~` was documented as "contains". It is
  **exact match**, identical to `:` — verified against a live instance. Examples implying
  substring matching (`ASSET_TAG~LAPTOP`) were wrong and have been replaced. The unverified
  `!~` / `!` / `is_null` / `is_not_null` operators are no longer documented as fact.
- **Documentation correction:** the README's and user guide's tutorial examples filtered with
  `ev_equals_filter("STATUS_EN", "Open")`. `STATUS_EN` is a sub-key of the nested `STATUS`
  object, not a top-level column, so EasyVista silently ignored the condition and every example
  returned *all* tickets, not just open ones. This was a documentation defect, not a library bug
  — the library does not special-case field names, so nothing in the shipped code was broken.
  Replaced with `ev_equals_filter("STATUS_ID", 3)` throughout, and the user guide now documents
  which returned fields are actually searchable and the third (HTTP 590 type-mismatch) search
  outcome.
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

[Unreleased]: https://github.com/baraline/easyvista_python_client/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/baraline/easyvista_python_client/releases/tag/v0.1.0

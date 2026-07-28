# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).
While the package is pre-1.0, breaking changes may land between minor versions;
a deprecation policy will follow the 1.0 release.

## [Unreleased]

### Added

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

### Changed

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

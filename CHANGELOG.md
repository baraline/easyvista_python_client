# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).
While the package is pre-1.0, breaking changes may land between minor versions;
a deprecation policy will follow the 1.0 release.

## [Unreleased]

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

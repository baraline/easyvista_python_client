# Contributing

Thank you for improving `easyvista-python-client`.

The full guide lives in [docs/development.rst](docs/development.rst) (published as
the [development guide](https://easyvista-python-client.readthedocs.io/en/latest/development.html));
this page is the short version.

## Development Setup

```bash
python -m venv .venv
.venv\Scripts\activate
python -m pip install -e ".[dev]"
python -m pre_commit install
python -m pre_commit run --all-files
python -m pytest -m "not integration"
```

## Quality Checks

Run these before opening a pull request:

```bash
python -m pre_commit run --all-files
python -m pytest -m "not integration"
python -m ruff check .
python -m mypy easyvista_python_client
```

A single-file run needs no extra flags — `--cov` is not in `addopts`:

```bash
python -m pytest easyvista_python_client/tests/test_pagination.py
```

## Coverage

The floor is 95% (`[tool.coverage.report] fail_under`), measured on
`easyvista_python_client` minus the tests and the generated `_sync/` modules —
those are a token transform of `_async/`, so counting both would score the same
logic twice. Reproduce what CI's `coverage` job asserts:

```bash
python -m pytest -m "not integration" --cov=easyvista_python_client --cov-report=term-missing --cov-fail-under=95
```

Add `--cov-report=html` for a browsable report in `htmlcov/`. The same gate runs
as a **pre-push** hook, so `pre-commit install` now needs to wire up two hook
types:

```bash
python -m pre_commit install --install-hooks
```

If you set up the repo before that hook existed, re-run the line above or your
pushes are ungated.

## Documentation build

```bash
python -m sphinx -W --keep-going -b html docs docs/_build/html
```

## Live integration tests

`integration_tests/` lives at the repository root, apart from the unit tests
inside the package, because it calls a **real EasyVista instance that you
supply**. It never runs in CI — CI runs `pytest -m "not integration"`.

Credentials come from `EASYVISTA_TEST_*` environment variables, falling back to
files under `secrets/` (both gitignored). With none configured the suite skips
cleanly, so `pytest` on a fresh checkout is offline and green.

> **These tests are not read-only.** They create tickets and close them in
> teardown. Once your credentials are present they run as part of a plain
> `pytest` — use `pytest -m "not integration"` for a unit-only run. Point them at
> a preprod or test instance, never production.

Never commit an instance host, account id, or token — see the note below.

## Design Guidelines

- Keep API calls behind `EasyvistaClient` / `AsyncEasyvistaClient` methods. The
  two surfaces are hand-maintained in parallel: a method added to one must be
  added to the other with the same name and signature.
- Prefer declaring a new documented endpoint as a resource descriptor plus a
  model over hand-writing a builder.
- Prefer field-validated Pydantic models for request and response payloads.
- Keep instance-specific values out of the library, the docs, and the tests.
  Catalog codes, department/urgency/impact ids, and status GUIDs vary per
  EasyVista instance; use obviously synthetic placeholders in examples and
  fixtures rather than values copied from a real instance.
- Add tests for payload serialization and response normalization when adding
  endpoints. Unit tests live beside the code: one test module per source
  module, in that package's `tests/` directory (`models/request.py` is covered
  by `models/tests/test_request.py`). Tests that span several modules, and any
  shared fixture, belong in `easyvista_python_client/testing/`. Neither
  directory ships in the wheel or the sdist.
- "One test module per source module" is a ceiling, not a floor: a source
  module whose behaviour is fully exercised through a caller's tests (for
  example a model asserted only via the resource and client tests that build
  it) does not need its own near-empty test file. Check coverage before adding
  one.

## Agent skills

A change to the public API must update the affected `skills/*/SKILL.md`, and a
release that bumps `__version__` must bump every skill's `metadata.version`.
`scripts/tests/test_skills_contract.py` is the gate: it parses every `SKILL.md`
and asserts each symbol, client method, keyword argument and model field the
skill names still exists on the public surface. Run it with
`pytest scripts/tests/test_skills_contract.py`.

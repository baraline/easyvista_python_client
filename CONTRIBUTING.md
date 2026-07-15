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
python -m pytest
```

## Quality Checks

Run these before opening a pull request:

```bash
python -m pre_commit run --all-files
python -m pytest
python -m ruff check .
python -m mypy easyvista_python_client
```

Coverage is enforced at 95% and `--cov` is always on via `addopts`, so a
single-file run needs `--no-cov` to avoid a spurious under-coverage failure:

```bash
python -m pytest tests/test_client_sync.py --no-cov
```

## Documentation build

```bash
python -m sphinx -W --keep-going -b html docs docs/_build/html
```

## Live integration tests

The default suite never touches the network. The `integration`-marked tests run
only with `--run-integration` and credentials supplied via `EASYVISTA_TEST_*`
environment variables or files under `secrets/`, both of which are gitignored.
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
  endpoints.

"""Fixtures for live integration tests.

These tests call a real EasyVista instance, so they live apart from the unit
tests inside the package and are **never run in CI** — CI runs
``pytest -m "not integration"``. You supply your own instance: every test here
skips cleanly when credentials are absent, so a checkout with no ``secrets/``
and no ``EASYVISTA_TEST_*`` environment simply skips the suite rather than
failing it.

They are not read-only. The ``probe_tickets`` fixture creates two tickets and
closes both in teardown; ``test_live_smoke`` additionally issues one create that
the server is *expected to reject*, so no ticket persists from it. Point them at
a preprod/test instance, never production.

Credentials resolve from an uppercase env var first, then a lowercase file under
``secrets/``:

    url    <- EASYVISTA_TEST_URL    | secrets/easyvista_test_url
    user   <- EASYVISTA_TEST_USER (or _ACCOUNT) | secrets/easyvista_test_user
    token  <- EASYVISTA_TEST_TOKEN  | secrets/easyvista_test_token

Auth is **Bearer** (the ``token`` value) — confirmed against the live preprod
instance. The ``url`` value is the **full API root** (it already ends in
``/api/v1/{account}``), so we split it back into ``server`` + ``account`` so
``EasyvistaConfig.api_root`` reconstructs it exactly. If the URL is instead a
bare host (no ``/api/`` segment), the ``user`` value is used as the account.

The secret values are loaded by this test process at runtime and never printed.
"""

from __future__ import annotations

import os
import uuid
from collections.abc import Iterator
from pathlib import Path

import pytest

from easyvista_python_client import EasyvistaClient, EasyvistaConfig

_HERE = Path(__file__).resolve().parent


def pytest_collection_modifyitems(items: list[pytest.Item]) -> None:
    """Mark every test **in this directory** ``integration``, whatever it declares.

    CI's ``pytest -m "not integration"`` is the guarantee that nothing here ever
    calls a live instance from a runner. Leaving that to a per-module
    ``pytestmark`` makes the guarantee a convention: a new file that forgets it —
    or misspells it — is collected and run, and ``--strict-markers`` does not
    save you (in ``addopts`` pytest 9 silently ignores it — verified). Marking by
    location makes the guarantee structural, so it cannot be forgotten.

    The path check is essential, not defensive: pytest hands this hook **every**
    collected item in the session, not only the ones under this conftest. Without
    it this would mark the entire unit suite ``integration`` and CI would
    deselect all of it.
    """
    for item in items:
        path = getattr(item, "path", None)
        if path is not None and _HERE in Path(path).resolve().parents:
            item.add_marker(pytest.mark.integration)


# secrets/ lives at the repo root: integration_tests/conftest.py -> parents[1].
_SECRETS_DIR = Path(__file__).resolve().parents[1] / "secrets"


def _resolve(env_names: tuple[str, ...], filename: str) -> str | None:
    for name in env_names:
        value = os.environ.get(name)
        if value and value.strip():
            return value.strip()
    path = _SECRETS_DIR / filename
    if path.is_file():
        text = path.read_text(encoding="utf-8").strip()
        if text:
            return text
    return None


@pytest.fixture(scope="session")
def live_config() -> EasyvistaConfig:
    url = _resolve(("EASYVISTA_TEST_URL",), "easyvista_test_url")
    user = _resolve(
        ("EASYVISTA_TEST_USER", "EASYVISTA_TEST_ACCOUNT"), "easyvista_test_user"
    )
    token = _resolve(("EASYVISTA_TEST_TOKEN",), "easyvista_test_token")
    if not url or not token:
        pytest.skip(
            "live credentials unavailable (need url + token; set EASYVISTA_TEST_* "
            "env vars or add secrets/easyvista_test_* files)"
        )

    root = url.rstrip("/")
    if "/api/" in root:
        # url is the full API root, e.g. https://host/api/v1/12345 -> split it.
        server, _, rest = root.partition("/api/")
        version, _, account_tail = rest.partition("/")
        account = account_tail.split("/")[0]
        if not account:
            pytest.skip(f"could not parse an account from the API root URL ({root!r})")
        return EasyvistaConfig(
            server=server, account=account, token=token, api_version=version
        )
    # url is a bare host; the account comes from the user value.
    if not user:
        pytest.skip("URL has no /api/ segment, so a user/account value is required")
    return EasyvistaConfig(server=root, account=user, token=token)


@pytest.fixture(scope="session")
def live_client(live_config: EasyvistaConfig) -> Iterator[EasyvistaClient]:
    with EasyvistaClient(live_config) as client:
        yield client


@pytest.fixture(scope="session")
def sample_rfc(live_client: EasyvistaClient) -> str:
    """An RFC number from the live instance, for ticket sub-resource reads."""
    result = live_client.search_tickets(max_rows=1)
    if not result.records:
        pytest.skip("no tickets on the live instance to exercise ticket reads")
    rfc = result.records[0].rfc_number
    if not rfc:
        pytest.skip("live ticket returned without an RFC_NUMBER")
    return rfc


@pytest.fixture(scope="session")
def sample_department_id(live_client: EasyvistaClient) -> int:
    """A department id from the live instance, for directory reads."""
    result = live_client.search_departments(max_rows=1)
    if not result.records or result.records[0].department_id is None:
        pytest.skip("no departments on the live instance to exercise directory reads")
    return result.records[0].department_id


@pytest.fixture(scope="session")
def sample_department_code(live_client: EasyvistaClient) -> str:
    """A real DEPARTMENT_CODE from the live instance, for search-syntax probes."""
    result = live_client.search_departments(max_rows=25)
    for dept in result.records:
        code = dept.department_code
        if code and code.strip() and len(code.strip()) >= 3:
            return code.strip()
    pytest.skip("no department with a usable DEPARTMENT_CODE on the live instance")


@pytest.fixture(scope="session")
def sample_catalog_code() -> str:
    """A catalog code valid on the live instance.

    Resolved at runtime, never hardcoded: a test that needs a *valid* catalog to
    isolate a different failure cannot use a made-up one, and the real code must
    not live in a tracked file.
    """
    value = _resolve(("EASYVISTA_TEST_CATALOG_CODE",), "easyvista_test_catalog_code")
    if not value:
        pytest.skip(
            "needs EASYVISTA_TEST_CATALOG_CODE (or secrets/easyvista_test_catalog_code)"
        )
    return value


@pytest.fixture(scope="session")
def live_write_config() -> dict[str, str]:
    """Instance-specific fields needed to create and close probe tickets.

    Skips unless every value is configured: these are per-instance and must not
    be hardcoded into a tracked test.
    """
    keys = {
        "catalog_code": ("EASYVISTA_TEST_CATALOG_CODE", "easyvista_test_catalog_code"),
        "origin": ("EASYVISTA_TEST_ORIGIN", "easyvista_test_origin"),
        "department_id": (
            "EASYVISTA_TEST_DEPARTMENT_ID",
            "easyvista_test_department_id",
        ),
        "urgency_id": ("EASYVISTA_TEST_URGENCY_ID", "easyvista_test_urgency_id"),
        "impact_id": ("EASYVISTA_TEST_IMPACT_ID", "easyvista_test_impact_id"),
        "status_guid": ("EASYVISTA_TEST_STATUS_GUID", "easyvista_test_status_guid"),
    }
    resolved: dict[str, str] = {}
    for name, (env, filename) in keys.items():
        value = _resolve((env,), filename)
        if not value:
            pytest.skip(f"write probes need {env} (or secrets/{filename})")
        resolved[name] = value
    return resolved


@pytest.fixture(scope="session")
def probe_tickets(live_client, live_write_config) -> Iterator[tuple[str, str, str]]:
    """Create two probe tickets; always close both.

    Yields (nonce, rfc_control, rfc_quoted):
      - control ticket title: ``EVCLI{nonce}A``            (quote-free)
      - quoted  ticket title: ``EVCLI{nonce}B 22" monitor`` (contains a literal ")
    """
    from easyvista_python_client import PostRequest

    cfg = live_write_config
    nonce = uuid.uuid4().hex[:10].upper()

    def _create(title: str) -> str:
        ticket = live_client.create_ticket(
            PostRequest(
                catalog_code=cfg["catalog_code"],
                title=title,
                description="search-syntax characterization probe; safe to close",
                origin=int(cfg["origin"]),
                department_id=int(cfg["department_id"]),
                urgency_id=int(cfg["urgency_id"]),
                impact_id=int(cfg["impact_id"]),
            )
        )
        assert ticket.rfc_number, "create_ticket returned no rfc_number"
        return ticket.rfc_number

    created: list[str] = []
    try:
        rfc_control = _create(f"EVCLI{nonce}A")
        created.append(rfc_control)
        rfc_quoted = _create(f'EVCLI{nonce}B 22" monitor')
        created.append(rfc_quoted)
        yield nonce, rfc_control, rfc_quoted
    finally:
        errors = []
        for rfc in created:
            try:
                live_client.close_ticket(
                    rfc,
                    status_guid=cfg["status_guid"],
                    delete_actions=1,
                    comment="probe cleanup",
                )
            except Exception as exc:  # every ticket must be attempted regardless
                errors.append((rfc, exc))
        if errors:
            raise RuntimeError(f"failed to close probe ticket(s): {errors}")

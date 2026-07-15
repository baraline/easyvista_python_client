"""Fixtures for live integration tests.

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
from collections.abc import Iterator
from pathlib import Path

import pytest

from easyvista_python_client import EasyvistaClient, EasyvistaConfig

# secrets/ lives at the repo root: tests/integration/conftest.py -> parents[2].
_SECRETS_DIR = Path(__file__).resolve().parents[2] / "secrets"


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

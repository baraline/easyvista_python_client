"""Pin the baseline this package is written against.

Everything in ``docs/vendor-api-reference.md`` is stated for EasyVista 2025.3.
An instance upgrade should surface here as a failing test rather than as
behaviour nobody can account for.

Credential-gated like the rest of ``integration_tests/`` and never run in CI.
"""

from __future__ import annotations

import httpx
import pytest

from easyvista_python_client import EasyvistaConfig

BASELINE = "2025.3"

pytestmark = pytest.mark.integration


def test_instance_still_reports_the_baseline_version(
    live_config: EasyvistaConfig,
) -> None:
    headers = {"Accept": "application/json"}
    if live_config.token:
        headers["Authorization"] = f"Bearer {live_config.token}"
        auth = None
    else:
        auth = httpx.BasicAuth(live_config.login or "", live_config.password or "")

    response = httpx.get(
        f"{live_config.api_root}/swagger",
        headers=headers,
        auth=auth,
        timeout=live_config.timeout,
        verify=live_config.verify_ssl,
    )

    # Deliberately not `== 200`. A GET here answers 201, which is odd enough
    # that a status check written from habit would skip the assertion below
    # and pass for the wrong reason.
    assert response.status_code == 201, (
        f"GET {{api_root}}/swagger returned {response.status_code}; it has "
        "answered 201 since this baseline was measured"
    )

    info = response.json().get("info", {})
    assert BASELINE in info.get("description", ""), (
        f"instance reports {info.get('description')!r}, but this package's "
        f"docs/vendor-api-reference.md is written against {BASELINE}"
    )

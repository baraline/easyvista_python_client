import os

import pytest

from easyvista_python_client.config import EasyvistaConfig


def pytest_addoption(parser):
    parser.addoption(
        "--run-integration",
        action="store_true",
        default=False,
        help="run live integration tests against a real EasyVista instance",
    )


def pytest_collection_modifyitems(config, items):
    """Skip integration-marked tests unless explicitly opted in.

    Opt in with ``--run-integration`` or ``EASYVISTA_RUN_INTEGRATION=1`` so a
    normal ``pytest`` run never makes live calls, even when secret files exist.
    """
    opted_in = (
        config.getoption("--run-integration")
        or os.environ.get("EASYVISTA_RUN_INTEGRATION") == "1"
    )
    if opted_in:
        return
    skip_integration = pytest.mark.skip(
        reason="needs --run-integration (or EASYVISTA_RUN_INTEGRATION=1)"
    )
    for item in items:
        if "integration" in item.keywords:
            item.add_marker(skip_integration)


@pytest.fixture
def config():
    return EasyvistaConfig(server="https://ev.test", account="acme", token="tok")

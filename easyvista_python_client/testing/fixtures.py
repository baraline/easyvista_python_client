"""Shared pytest fixtures for the unit suite.

These live inside the package so the test commons sit next to the code they
serve. They are registered globally by the repository-root ``conftest.py``:
fixtures defined in a ``testing/conftest.py`` would only be visible to tests
under ``testing/``, not to ``models/tests/`` or ``resources/tests/``.

Excluded from both build targets -- see ``[tool.hatch.build]`` in pyproject.toml.
"""

import pytest

from easyvista_python_client.config import EasyvistaConfig


@pytest.fixture
def config():
    return EasyvistaConfig(server="https://ev.test", account="acme", token="tok")

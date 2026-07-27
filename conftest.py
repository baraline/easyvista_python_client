"""Registers the package's shared test fixtures.

``pytest_plugins`` is only honoured in the rootdir conftest, which is why this
one-liner sits at the repository root while the fixture bodies live in
``easyvista_python_client/testing/fixtures.py``.

This file ships nowhere: it is outside the wheel's package root and absent from
the sdist allowlist.
"""

pytest_plugins = ["easyvista_python_client.testing.fixtures"]

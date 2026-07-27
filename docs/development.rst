Development
===========

Setup
-----

.. code-block:: bash

   pip install -e ".[dev]"
   pip install -e ".[docs]"
   pre-commit install

Tests
-----

The suite uses ``pytest`` with ``respx`` for HTTP mocking, and asserts a coverage floor.

.. code-block:: bash

   pytest

Linting and type-checking
--------------------------

.. code-block:: bash

   ruff check .
   mypy easyvista_python_client

Integration tests
------------------

``integration_tests/`` (at the repository root, apart from the unit tests inside the package)
calls a **real EasyVista instance** that you supply. It never runs in CI — CI runs
``pytest -m "not integration"``.

Credentials resolve from ``EASYVISTA_TEST_URL`` / ``EASYVISTA_TEST_USER`` / ``EASYVISTA_TEST_TOKEN``,
falling back to files under ``secrets/`` (both gitignored). With no credentials configured the suite
**skips cleanly**, so a plain ``pytest`` on a fresh checkout is offline and green.

.. warning::

   These tests are **not read-only**: they create tickets and close them in teardown. Once
   credentials are present they run as part of a plain ``pytest``. Point them at a preprod or test
   instance, never production.

.. code-block:: bash

   pytest                      # unit tests + live tests (if credentials are configured)
   pytest -m "not integration" # unit tests only -- what CI runs
   pytest integration_tests    # live tests only

Building the docs
-----------------

.. code-block:: bash

   sphinx-build -b html -W docs docs/_build/html

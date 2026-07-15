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

Live integration tests are opt-in and read-only by default. Enable them with
``--run-integration`` (or ``EASYVISTA_RUN_INTEGRATION=1``); credentials resolve from environment
variables, falling back to files under ``secrets/``.

.. code-block:: bash

   pytest --run-integration

Building the docs
-----------------

.. code-block:: bash

   sphinx-build -b html -W docs docs/_build/html

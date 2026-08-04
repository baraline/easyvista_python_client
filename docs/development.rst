Development
===========

Setup
-----

.. code-block:: bash

   pip install -e ".[dev]"
   pip install -e ".[docs]"
   pre-commit install --install-hooks

``--install-hooks`` matters: one hook runs at **pre-push** rather than pre-commit
(see :ref:`coverage`), and ``pre-commit install`` only writes the hook types the
config declares. If you set the repository up before that hook existed, re-run
the line above or your pushes are ungated.

Tests
-----

The suite uses ``pytest`` with ``respx`` for HTTP mocking.

.. code-block:: bash

   pytest -m "not integration"

.. _coverage:

Coverage
--------

The floor is 95%, set by ``[tool.coverage.report] fail_under`` in
``pyproject.toml``. It is measured on ``easyvista_python_client`` with two things
excluded: the test modules, which live inside the package and would otherwise
weigh thousands of lines of always-executed test code against the source, and
the generated ``_sync/`` modules, which are a token transform of ``_async/`` and
would score the same logic twice behind a doubled denominator (see
:ref:`the generated sync client <generated-sync-client>`).

``--cov`` is **not** in ``addopts``, so a plain or single-file ``pytest`` run
neither measures nor gates coverage. Reproduce what CI asserts with:

.. code-block:: bash

   pytest -m "not integration" --cov=easyvista_python_client --cov-report=term-missing --cov-fail-under=95

Add ``--cov-report=html`` for a browsable report under ``htmlcov/``. The gate is
enforced in two places: the ``coverage`` job in ``.github/workflows/ci.yml``,
which also uploads ``coverage.xml`` to Codecov, and the ``pytest-coverage``
pre-push hook, which runs ``scripts/run_coverage_gate.py``. That script locates
the project's interpreter itself -- preferring ``.venv``, then ``VIRTUAL_ENV`` --
so ``git push`` gates correctly whether or not the virtualenv is activated. If it
cannot find an interpreter with the dev dependencies installed it says so and
fails rather than passing silently.

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

.. _generated-sync-client:

The generated sync client
-------------------------

``easyvista_python_client/_async/`` is the only hand-written client source.
``easyvista_python_client/_sync/`` is generated from it by `unasync
<https://github.com/python-trio/unasync>`_, checked into the repository, and
verified in CI.

After any edit under ``_async/``, regenerate::

    python unasync_build.py

To check for staleness without writing, as CI does::

    python unasync_build.py --check

**Never edit anything under ``_sync/`` by hand.** Two files are the
exception, and they are hand-written on *both* sides:

``_concurrency.py``
    A fan-out is ``asyncio.gather`` on the async side and plain sequential
    evaluation on the sync side, and bounding it needs an
    ``asyncio.Semaphore`` there and nothing at all here. ``unasync``
    substitutes single NAME tokens, so it cannot express either -- and a
    dotted key like ``asyncio.Semaphore`` is accepted *silently and never
    fires*.

``tests/test_concurrency.py``
    Follows for the same reason: the claims differ in kind, not in spelling.

The generated tree is excluded from ruff because stripping ``async`` and
``await`` shortens lines that the generator keeps wrapped; formatting it
would fight regeneration forever. It is still type-checked under mypy strict.
The two hand-written twins above are the exception here too: pre-commit runs
``ruff format`` / ``ruff check`` on exactly those paths (driven off
``unasync_build.HAND_WRITTEN``), since a directory-wide exclusion would
otherwise silently skip the only two files in that tree that are actually
someone's to format.

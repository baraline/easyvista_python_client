Publishing
==========

The project builds with ``hatchling`` and publishes to PyPI as ``easyvista-python-client``.

Releases are published by ``.github/workflows/release.yml``, which runs when a GitHub
release is *published*. No maintainer uploads by hand, and no PyPI API token is stored
in the repository: the workflow authenticates to PyPI with `Trusted Publishing
<https://docs.pypi.org/trusted-publishers/>`_, which mints a short-lived credential from
the workflow's OIDC identity.

Cutting a release
-----------------

#. Bump the version in **all four** places, or CI goes red on an otherwise correct
   bump:

   * ``pyproject.toml`` (``project.version``);
   * ``easyvista_python_client.__version__``;
   * the hardcoded literal in ``easyvista_python_client/testing/test_public_api.py``
     (asserted by the unit suite);
   * every ``skills/*/SKILL.md`` ``metadata.version`` (asserted by
     ``scripts/tests/test_skills_contract.py``).

   The release workflow additionally refuses to build if the first two disagree with
   each other or with the tag.
#. Move the ``CHANGELOG.md`` ``[Unreleased]`` entries under the new version and update the
   compare links at the bottom of the file.
#. Merge to ``main`` and let CI go green.
#. Publish a GitHub release whose tag is the version, ``v``-prefixed --
   ``v0.2.0`` for version ``0.2.0``. (The workflow strips a leading ``v`` before comparing,
   so an unprefixed tag also passes. The only tag that exists today, ``0.1.0``, is
   **unprefixed** -- ``v``-prefixing starts at ``v0.2.0``, which is why the
   ``CHANGELOG.md`` link for ``0.1.0`` points at the bare tag.)

The workflow then runs the test matrix (3.10--3.14) and the quality gates -- Ruff, mypy,
the generated-``_sync``-tree check, the hand-written-twin lint and a warnings-as-errors
Sphinx build -- validates the tag against the package version, builds the wheel and the
sdist, runs ``twine check``, uploads to PyPI, and finally triggers a Read the Docs build
for the release version.

Rehearsing without publishing
-----------------------------

Running the workflow manually (``workflow_dispatch``) exercises everything except the
upload: ``publish-pypi`` is gated on the event being a release. Use it to check that a
release *would* build before tagging.

One-time setup
--------------

Trusted Publishing
   Configure a publisher on PyPI for the project pointing at owner ``baraline``,
   repository ``easyvista_python_client``, workflow ``release.yml``, environment ``pypi``.
   ``0.1.0`` is already on PyPI, so the project is past the *pending* publisher stage
   this section used to describe -- a pending publisher is only needed before a project's
   first upload exists. The ``pypi`` GitHub environment is also where a required-reviewer
   gate on the upload step belongs, if the project wants one.

Read the Docs (optional)
   The docs job self-skips when unconfigured. To enable it, set the ``READTHEDOCS_PROJECT``
   and ``READTHEDOCS_TOKEN`` secrets, and optionally the ``READTHEDOCS_BASE_URL`` and
   ``READTHEDOCS_RELEASE_VERSION`` variables (defaults: ``https://app.readthedocs.org``
   and ``stable``).

Building locally
----------------

.. code-block:: bash

   python -m build
   twine check dist/*

This writes a wheel and an sdist to ``dist/`` and validates their metadata -- the same two
steps the release workflow runs. Uploading from a workstation with ``twine upload`` still
works, but it bypasses every gate above and is not how releases are cut; prefer fixing the
workflow over working around it.

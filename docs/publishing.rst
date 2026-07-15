Publishing
==========

The project builds with ``hatchling`` and publishes to PyPI as ``easyvista-python-client``.

Build the distribution
-----------------------

.. code-block:: bash

   python -m build

This writes a wheel and an sdist to ``dist/``.

Check and upload
----------------

.. code-block:: bash

   twine check dist/*
   twine upload dist/*

Bump the version in ``pyproject.toml`` (and ``easyvista_python_client.__version__``) before building
a release.

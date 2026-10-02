Installation
============

Requirements
------------

* Python 3.11 or newer. Release 0.4.0 dropped 3.10, which reaches end of life
  in October 2026 (PEP 619). On 3.10, ``pip`` installs 0.3.0, the last release that
  supports it. 0.3.0 has no ``content`` extra: asked for
  ``easyvista-python-client[content]`` on 3.10, ``pip`` warns and installs
  0.3.0 without the converter, which needs 3.11 or newer.
* Runtime dependencies (installed automatically): ``httpx``, ``pydantic>=2``, ``tenacity``.

From PyPI
---------

.. code-block:: bash

   pip install easyvista-python-client

To convert memo text between HTML and Markdown, add the optional ``content`` extra (see
:doc:`content`). It brings ``beautifulsoup4``, ``cmarkgfm``, ``markdown-it-py``, ``markdownify``,
``mdformat`` and ``mdformat-tables``, most of them with an upper bound:

.. code-block:: bash

   pip install "easyvista-python-client[content]"

``cmarkgfm`` wraps a C library. PyPI lists no wheel of ``cmarkgfm`` 2025.10.22 for macOS x86_64 or
Windows ARM64 (read 2026-10-02). Unless a later release adds one, ``pip`` builds it from source on
those platforms, which needs a C compiler.

From source
-----------

.. code-block:: bash

   git clone https://github.com/baraline/easyvista_python_client.git
   cd easyvista_python_client
   pip install -e .

Development and documentation tooling
-------------------------------------

The optional ``dev`` extra installs the linters, type-checker, and test tooling; the ``docs`` extra
installs Sphinx and the theme used to build this site. Both also install the ``content`` extra's
packages, with the same bounds, because the unit suite tests the converter and the API reference
imports it.

.. code-block:: bash

   pip install -e ".[dev]"
   pip install -e ".[docs]"

Building the documentation locally
-----------------------------------

.. code-block:: bash

   pip install -e ".[docs]"
   sphinx-build -b html -W docs docs/_build/html

Then open ``docs/_build/html/index.html`` in a browser. The ``-W`` flag turns warnings into errors,
matching the ReadTheDocs build (``fail_on_warning: true``).

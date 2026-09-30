Installation
============

Requirements
------------

* Python 3.10 or newer.
* Runtime dependencies (installed automatically): ``httpx``, ``pydantic>=2``, ``tenacity``.

From PyPI
---------

.. code-block:: bash

   pip install easyvista-python-client

To convert memo text between HTML and Markdown, add the optional ``content`` extra, which brings
``beautifulsoup4``, ``markdown`` and ``markdownify`` (see :doc:`content`):

.. code-block:: bash

   pip install "easyvista-python-client[content]"

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
three packages, because the unit suite tests the converter and the API reference imports it.

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
